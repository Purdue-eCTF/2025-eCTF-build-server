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
    path = f"~/ectf2025/build_out/{job.out_path}"
    venv = ". ~/ectf2025/.venv/bin/activate"
    update_script = "~/ectf2025/CI/update"

    try:
        job.log(blue(f"[DIST] Uploading {job.name} to {ip}"))

        # upload to server
        try:
            subprocess.run(
                f'rsync --rsh="ssh -i id_ed25519 -o StrictHostKeyChecking=accept-new" -av --progress --delete --ignore-times'
                f" {job.in_path}/max78000.bin {ip}:{path}",
                shell=True,
                check=True,
            )
        except subprocess.SubprocessError:
            job.log(red(f"[DIST] Failed to upload to {ip}"))
            traceback.print_exc()
            job.conn.send(b"%*&1\n")
            job.conn.close()
            return

        try:
            subprocess.run(
                [
                    "ssh",
                    "-i",
                    "id_ed25519",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    ip,
                    f"{venv} && {update_script} {path}/max78000.bin && rm -rf {path}",
                ],
                check=True,
            )
        except subprocess.SubprocessError:
            job.log(red(f"[DIST] Failed to flash on {ip}"))
            traceback.print_exc()
            job.conn.send(b"%*&1\n")
            job.conn.close()
            return

        # sh.run_cmd(f"rm -rf 2024-ectf-secure-example/build/{job.out_path}")

        # run tests
        job.log(blue(f"[DIST] Uploaded! Running tests for {job.name}\n"))
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
            job.time = time.time()
            push_webhook("TEST", job)
            return
        print(f"Tests OK for {job.name}")
        """
        job.conn.send(b"%*&0\n")
        job.conn.close()
        job.status = "SUCCESS"
        # job.time = time.time()
        push_webhook("TEST", job)
    except (BrokenPipeError, TimeoutError):
        print(red("[DIST] Client disconnected"))
    finally:
        upload_status[ip].job = None
        server_queue.put(ip)


def distribution_loop():
    while True:
        req = distribution_queue.get()
        avail_ip = server_queue.get()
        req.status = "TESTING"
        req.start_time = time.time()
        upload_status[avail_ip].job = req
        push_webhook()
        # for other_req in distribution_queue:
        #    other_req.conn.send(
        #        f"There are {upload_queue.size()} uploads in queue. \n".encode()
        #    )
        threading.Thread(target=distribute, args=(req, avail_ip), daemon=True).start()


def init_distribution_queue():
    # setup ssh
    # subprocess.run("mkdir -p ~/.ssh", shell=True, check=True)
    # subprocess.run("rm -f ~/.ssh/config", shell=True, check=True)

    for ip in IPS:
        """subprocess.run(
            f"echo 'Host {ip.split("@")[1]}\nProxyCommand $(which cloudflared) access ssh --hostname %h\n' >> ~/.ssh/config",
            shell=True,
            check=True,
        )"""
        upload_status[ip] = TestServerStatus()
        server_queue.put(ip)
    push_webhook()
    print(blue(f"Loaded {len(IPS)} ips"))

    print(blue("[DIST] Dist queue ready..."))
    threading.Thread(target=distribution_loop, daemon=True).start()
