import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from queue import Queue
from socket import socket

from colors import blue, red
from config import IPS
from jobs import CommitInfo, Job
from webhook import push_webhook

distribution_queue: Queue["DistributionJob"] = Queue()
upload_status: dict[str, "TestServerStatus"] = {}
server_queue: Queue[str] = Queue()

OUT_PATH = "~/ectf2025/build_out/"
TEST_OUT_PATH = "~/ectf2025/test_out/"
CI_PATH = "~/ectf2025/CI/"
VENV = ". ~/ectf2025/.venv/bin/activate"


@dataclass
class DistributionJob(Job):
    name: str
    in_path: str
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
                self.conn.send(output.stdout)
                self.conn.send(output.stderr)
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
            server_queue.put(ip)
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
            conn, status, start_time, name, build_folder + "/build_out/", commit
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
                    f"{self.build_folder}/secrets",
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
                    f"{VENV} || exit 1; {CI_PATH}/run_build_tests.sh; exit_code=$?; rm -rf {TEST_OUT_PATH}; exit $exit_code",
                ],
                timeout=60 * 2,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.conn.send(output.stdout)
            self.conn.send(output.stderr)
        except subprocess.SubprocessError as e:
            self.on_error(e, f"[TEST] Tests failed for {self.name}")

            self.status = "FAILED"
            push_webhook("TEST", self)
            return

        self.log(blue(f"[TEST] Tests OK for {self.name}"))
        self.conn.send(b"%*&0\n")
        self.conn.close()
        self.status = "SUCCESS"
        push_webhook("TEST", self)


def distribution_loop():
    while True:
        req = distribution_queue.get()
        avail_ip = server_queue.get()
        req.status = "TESTING"
        req.start_time = time.time()
        upload_status[avail_ip].job = req
        push_webhook()
        threading.Thread(target=req.distribute, args=(avail_ip,), daemon=True).start()


@dataclass
class TestServerStatus:
    job: DistributionJob | None = None

    def is_avail(self):
        return not self.job or self.job.status != "TESTING"


def add_to_dist_queue(job: DistributionJob):
    distribution_queue.put(job)


def init_distribution_queue():
    # setup ssh
    with open("ssh_config", "w", encoding="utf-8") as f:
        for ip in IPS:
            f.write(
                f"Host {ip.split('@')[1]}\nProxyCommand cloudflared access ssh --hostname %h\n"
            )
            upload_status[ip] = TestServerStatus()
            server_queue.put(ip)
    push_webhook()
    print(blue(f"[DIST] Loaded {len(IPS)} ips"))

    print(blue("[DIST] Dist queue ready..."))
    threading.Thread(target=distribution_loop, daemon=True).start()
