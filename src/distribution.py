# ruff: noqa: S607, UP022
import shutil
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass
from queue import Queue

from colors import blue, red
from config import IPS
from jobs import DistributionJob
from webhook import push_webhook

distribution_queue: Queue[DistributionJob] = Queue()
upload_status: dict[str, "TestServerStatus"] = {}
server_queue: Queue[str] = Queue()


@dataclass
class TestServerStatus:
    job: DistributionJob | None = None

    def is_avail(self):
        return not self.job or self.job.status != "TESTING"


def add_to_dist_queue(job: DistributionJob):
    distribution_queue.put(job)


def distribute(job: DistributionJob, ip: str):
    path = "~/ectf2025/build_out/"
    venv = ". ~/ectf2025/.venv/bin/activate"
    update_script = "~/ectf2025/CI/update"

    job.status = "TESTING"
    job.start_time = time.time()
    push_webhook("TEST", job)

    try:
        # upload to server
        job.log(blue(f"[DIST] Uploading {job.name} to {ip}"))
        try:
            subprocess.run(
                [
                    "rsync",
                    "--rsh=ssh -F ssh_config -i id_ed25519 -o StrictHostKeyChecking=accept-new",
                    "-av",
                    "--progress",
                    "--delete",
                    "--ignore-times",
                    f"{job.in_path}/",
                    f"{ip}:{path}",
                ],
                timeout=60 * 2,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.SubprocessError as e:
            job.log(red(f"[DIST] Failed to upload to {ip}"))
            if isinstance(e, subprocess.CalledProcessError):
                job.conn.send(e.stdout or b"")
                job.conn.send(e.stderr or b"")
            job.log(red(traceback.format_exc()))
            job.conn.send(b"%*&1\n")
            job.conn.close()

            job.status = "FAILED"
            push_webhook("TEST", job)
            return

        # flash binary
        job.log(blue("[DIST] Flashing binary"))
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
                    f"{venv} || exit 1; {update_script} {path}/max78000.bin; exit_code=$?; rm -rf {path}; exit $exit_code",
                ],
                timeout=60 * 2,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            job.conn.send(output.stdout)
            job.conn.send(output.stderr)
        except subprocess.SubprocessError as e:
            job.log(red(f"[DIST] Failed to flash on {ip}"))
            if isinstance(e, subprocess.CalledProcessError):
                job.conn.send(e.stdout or b"")
                job.conn.send(e.stderr or b"")
            job.log(red(traceback.format_exc()))
            job.conn.send(b"%*&1\n")
            job.conn.close()

            job.status = "FAILED"
            push_webhook("TEST", job)
            return

        # run tests
        job.log(blue(f"[DIST] Flashed! Running tests for {job.name}\n"))
        # TODO
        """
        try:
            subprocess.run(
                f'ssh {ip} "bash -l -c \\"cd CI/rpi/; chmod +x run-tests.sh; nix-shell --run \'./run-tests.sh {job.out_path}\' \\" "'
            )
        except Exception:
            job.conn.send(
                (colorama.Fore.RED + f"Tests failed!" + colorama.Fore.RESET + "\n").encode()
            )
            print(f"Tests failed for {job.name}")
            job.conn.send(b"%*&1\n")
            job.status = "FAILED"
            push_webhook("TEST", job)
            return
        """
        job.log(blue(f"[DIST] Tests OK for {job.name}"))
        job.conn.send(b"%*&0\n")
        job.conn.close()
        job.status = "SUCCESS"
        push_webhook("TEST", job)
    except (BrokenPipeError, TimeoutError):
        print(red("[DIST] Client disconnected"))
    finally:
        upload_status[ip].job = None
        server_queue.put(ip)
        shutil.rmtree(job.in_path)


def distribution_loop():
    while True:
        req = distribution_queue.get()
        avail_ip = server_queue.get()
        req.status = "TESTING"
        req.start_time = time.time()
        upload_status[avail_ip].job = req
        push_webhook()
        threading.Thread(target=distribute, args=(req, avail_ip), daemon=True).start()


def init_distribution_queue():
    # setup ssh
    with open("ssh_config", "w", encoding="utf-8") as f:
        for ip in IPS:
            f.write(
                f"Host {ip.split("@")[1]}\nProxyCommand cloudflared access ssh --hostname %h\n"
            )
            upload_status[ip] = TestServerStatus()
            server_queue.put(ip)
    push_webhook()
    print(blue(f"[DIST] Loaded {len(IPS)} ips"))

    print(blue("[DIST] Dist queue ready..."))
    threading.Thread(target=distribution_loop, daemon=True).start()
