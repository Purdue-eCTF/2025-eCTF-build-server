import subprocess
import threading
import time
from dataclasses import dataclass
from queue import Queue

from colors import blue, red
from jobs import DistributionJob
from webhook import push_webhook

distribution_queue: Queue[DistributionJob] = Queue()
upload_status: dict[str, "TestServerStatus"] = {}
server_queue: Queue[str] = Queue()


@dataclass
class TestServerStatus:
    locked: bool
    job: DistributionJob

    def is_avail(self):
        return not self.locked or not self.job or self.job.status != "TESTING"


def add_to_dist_queue(job: DistributionJob):
    distribution_queue.put(job)


def distribute(job: DistributionJob, ip: str):
    job.conn.send(blue(f"Uploading {job.name}...\n").encode())
    print(f"Uploading {job.name} to {ip}...")

    # upload to server
    try:
        # TODO
        subprocess.run(
            f'rsync --rsh="ssh -o StrictHostKeyChecking=accept-new" -av --progress --delete --ignore-times'
            f" {job.in_path}/{{*.img,test_data}} {ip}:~/CI/upload/{job.out_path}",
            check=True,
        )
    except subprocess.SubprocessError:
        print("Failed to upload!")
        job.conn.send(red("Failed to upload!\n").encode())
        job.conn.send(b"%*&1\n")
        job.conn.close()
        return

    # sh.run_cmd(f"rm -rf 2024-ectf-secure-example/build/{job.out_path}")

    job.conn.send(blue("Uploaded! Running tests...\n").encode())
    # TODO
    """
    print(f"Running tests for {job.info.hash}...")
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
