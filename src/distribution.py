import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from queue import Queue
from socket import socket

from colors import blue, red
from config import GITHUB_TOKEN, GITHUB_USERNAME, IPS
from jobs import CommitInfo, Job
from webhook import push_webhook

distribution_queue: Queue["DistributionJob"] = Queue()
upload_status: dict[str, "UploadServerStatus"] = {}
server_queues: dict[str, Queue[str]] = {"TEST": Queue(), "ATTACK": Queue()}

OUT_PATH = "~/ectf2025/build_out/"
TEST_OUT_PATH = "~/ectf2025/test_out/"
CI_PATH = "~/ectf2025/CI/"
VENV = ". ~/ectf2025/.venv/bin/activate"


@dataclass
class DistributionJob(Job):
    name: str
    in_path: str
    queue_type: str
    commit: CommitInfo | None = None

    def to_json(self):
        return {
            "result": self.status,
            "actionStart": round(self.start_time),
            "commit": self.commit and self.commit.to_json(),
        }

    def distribute(self, ip: str):
        self.status = "TESTING"
        self.start_time = time.time()
        push_webhook("TEST", self)

        try:
            # upload to server
            self.log(blue(f"[DIST] Uploading {self.name} to {ip}"))
            try:
                subprocess.run(
                    [
                        "rsync",
                        "--rsh=ssh -F ssh_config -i id_ed25519 -o StrictHostKeyChecking=accept-new",
                        "-av",
                        "--progress",
                        "--delete",
                        "--ignore-times",
                        f"{self.in_path}/",
                        f"{ip}:{OUT_PATH}",
                    ],
                    timeout=60 * 2,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except subprocess.SubprocessError as e:
                if (
                    isinstance(e, subprocess.CalledProcessError)
                    and b"Connection closed by UNKNOWN port 65535" in e.stderr
                ):
                    self.log(f"[DIST] {ip} is disconnected, changing servers")

                    self.status = "PENDING"
                    push_webhook("TEST", self)

                    upload_status[ip].connected = False
                    add_to_dist_queue(self)
                else:
                    self.on_error(e, f"[DIST] Failed to upload to {ip}")

                    self.status = "FAILED"
                    push_webhook("TEST", self)
                return

            # flash binary
            self.log(blue("[DIST] Flashing binary"))
            try:
                output = subprocess.run(
                    [
                        "ssh",
                        "-F",
                        "ssh_config",
                        "-i",
                        "id_ed25519",
                        "-o",
                        "StrictHostKeyChecking=accept-new",
                        ip,
                        f"{VENV} || exit 1; {CI_PATH}/update {OUT_PATH}/max78000.bin; exit_code=$?; rm -rf {OUT_PATH}; exit $exit_code",
                    ],
                    timeout=60 * 2,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.conn.sendall(output.stdout)
                self.conn.sendall(output.stderr)
            except subprocess.SubprocessError as e:
                self.on_error(e, f"[DIST] Failed to flash on {ip}")

                self.status = "FAILED"
                push_webhook("TEST", self)
                return

            self.log(blue("[DIST] Flashed!"))
            self.post_upload(ip)
        except (BrokenPipeError, TimeoutError):
            print(red("[DIST] Client disconnected"))
        finally:
            if upload_status[ip].connected:
                # if not changing servers
                server_queues[self.queue_type].put(ip)
                self.cleanup()
            distribution_queue.task_done()

    def cleanup(self):
        shutil.rmtree(self.in_path)

    def post_upload(self, ip: str):
        pass


class TestingJob(DistributionJob):
    def __init__(
        self,
        conn: socket,
        status: str,
        start_time: float,
        name: str,
        build_folder: str,
        commit: CommitInfo | None = None,
    ):
        self.build_folder = build_folder
        super().__init__(
            conn,
            status,
            start_time,
            name,
            build_folder + "/build_out/",
            "TEST",
            commit,
        )

    def post_upload(self, ip: str):
        # run tests
        self.log(blue(f"[TEST] Running tests for {self.name}\n"))

        # upload test data to server
        self.log(blue(f"[TEST] Uploading test data to {ip}"))
        try:
            subprocess.run(
                [
                    "rsync",
                    "--rsh=ssh -F ssh_config -i id_ed25519 -o StrictHostKeyChecking=accept-new",
                    "-av",
                    "--progress",
                    "--delete",
                    "--ignore-times",
                    f"{self.build_folder}/design",
                    f"{self.build_folder}/secrets/global.secrets",
                    f"{ip}:{TEST_OUT_PATH}",
                ],
                timeout=60 * 2,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.SubprocessError as e:
            self.on_error(e, f"[TEST] Failed to upload to {ip}")

            self.status = "FAILED"
            push_webhook("TEST", self)
            return

        self.log(blue(f"[TEST] Running tests on {ip}"))

        try:
            output = subprocess.run(
                [
                    "ssh",
                    "-F",
                    "ssh_config",
                    "-i",
                    "id_ed25519",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    ip,
                    f"{VENV} || exit 1; {CI_PATH}/run_build_tests.sh;",
                ],
                timeout=60 * 10,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.conn.sendall(output.stdout)
            self.conn.sendall(output.stderr)

        except subprocess.SubprocessError as e:
            self.on_error(e, f"[TEST] Tests failed for {self.name}")

            self.status = "FAILED"
            push_webhook("TEST", self)
            return

        self.log(blue(f"[TEST] Tests OK for {self.name}"))
        self.conn.sendall(b"%*&0\n")
        self.conn.close()
        self.status = "SUCCESS"
        push_webhook("TEST", self)

    def cleanup(self):
        shutil.rmtree(self.build_folder)


class AttackingJob(DistributionJob):
    def __init__(
        self,
        conn: socket,
        status: str,
        start_time: float,
        name: str,
        build_folder: str,
        scenario: str,
    ):
        self.build_folder = build_folder
        self.scenario = scenario
        super().__init__(
            conn,
            status,
            start_time,
            name,
            build_folder,
            "ATTACK",
            None,
        )

    def post_upload(self, ip: str):
        # run attacks
        self.log(blue(f"[ATTACK] Running attacks for {self.name} on {ip}\n"))

        try:
            output = subprocess.run(
                [
                    "ssh",
                    "-F",
                    "ssh_config",
                    "-i",
                    "id_ed25519",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    ip,
                    f"{VENV} || exit 1; {CI_PATH}/run_attack_tests.sh {self.scenario};",
                ],
                timeout=60 * 10,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.conn.sendall(output.stdout)
            self.conn.sendall(output.stderr)

            # search for flags
            potential_flags = set(
                re.findall(
                    r"ectf\{[a-zA-Z0-9_]+\}", output.stdout.decode(errors="replace")
                )
            )
            # todo, submit
        except subprocess.SubprocessError as e:
            self.on_error(e, f"[ATTACK] Attacks failed for {self.name}")

            self.status = "FAILED"
            push_webhook("TEST", self)
            return

        self.log(blue(f"[ATTACK] ATTACK OK for {self.name}"))
        self.conn.sendall(b"%*&0\n")
        self.conn.close()
        self.status = "SUCCESS"
        push_webhook("TEST", self)


def distribution_loop():
    while True:
        req = distribution_queue.get()
        avail_ip = server_queues[req.queue_type].get()
        req.status = "TESTING"
        req.start_time = time.time()
        upload_status[avail_ip].job = req
        push_webhook()
        threading.Thread(target=req.distribute, args=(avail_ip,), daemon=True).start()


class UpdateCIJob(Job):
    def update_ci(self):
        from builder import BUILD_QUEUE  # noqa: PLC0415

        BUILD_QUEUE.join()
        distribution_queue.join()

        for ip, status in upload_status.items():
            if status.connected:
                self.log(blue(f"[UPDATE] Updating CI on {ip}"))
                try:
                    output = subprocess.run(
                        [
                            "ssh",
                            "-F",
                            "ssh_config",
                            "-i",
                            "id_ed25519",
                            "-o",
                            "StrictHostKeyChecking=accept-new",
                            ip,
                            f"cd {CI_PATH} && "
                            f"GITHUB_USERNAME={GITHUB_USERNAME} GITHUB_TOKEN={GITHUB_TOKEN} "
                            f"GIT_ASKPASS={CI_PATH}/git-askpass.sh git pull --ff-only origin main",
                        ],
                        timeout=60 * 2,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    self.conn.sendall(output.stdout)
                    self.conn.sendall(output.stderr)
                except subprocess.SubprocessError as e:
                    self.on_error(e, f"[UPDATE] Failed to update CI on {ip}")

                    self.status = "FAILED"
                    return
            else:
                self.log(
                    red(f"[UPDATE] Skipping CI update on {ip} because it is disconnected")
                )

        self.log(blue("[UPDATE] CI updates complete"))
        self.conn.sendall(b"%*&0\n")
        self.conn.close()
        self.status = "SUCCESS"


@dataclass
class UploadServerStatus:
    job: DistributionJob | None = None
    connected: bool = True

    def is_avail(self):
        return self.connected and (not self.job or self.job.status != "TESTING")


def add_to_dist_queue(job: DistributionJob):
    distribution_queue.put(job)


def init_distribution_queue():
    # setup ssh
    with open("ssh_config", "w", encoding="utf-8") as f:
        for ip, queue_type in IPS:
            f.write(
                f"Host {ip.split('@')[1]}\nProxyCommand cloudflared access ssh --hostname %h\n"
            )
            upload_status[ip] = UploadServerStatus()
            server_queues[queue_type].put(ip)
    push_webhook()
    print(blue(f"[DIST] Loaded {len(IPS)} ips"))

    print(blue("[DIST] Dist queue ready..."))
    threading.Thread(target=distribution_loop, daemon=True).start()
