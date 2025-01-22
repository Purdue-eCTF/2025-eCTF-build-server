import os
import subprocess
import time
import traceback
from queue import Queue
from threading import Thread

from colors import blue, red
from config import GITHUB_TOKEN
from distribution import add_to_dist_queue
from jobs import BuildJob, DistributionJob

BUILD_QUEUE = Queue()
active_build: BuildJob | None = None


def add_to_build_queue(job: BuildJob):
    """
    Add a job to the build queue
    :param job: The job to add
    """
    BUILD_QUEUE.put(job)
    pass


def build(job: BuildJob):
    global active_build
    active_build = job

    try:
        job.log(blue(f"[BUILD] Pulling from repo..."))
        # pull from repo
        try:
            output = subprocess.run(
                "cd 2025-eCTF-design &&"
                "git reset --hard &&"
                "git checkout main &&"
                "git pull &&"
                f"git checkout {job.commit.hash}",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            job.conn.send(output.stdout)
            job.conn.send(output.stderr)
        except Exception:
            job.log(
                red(f"[BUILD] Failed to build commit {job.commit.hash}! No commit found.")
            )
            job.log(red(traceback.format_exc()))
            job.conn.send(b"%*&1\n")
            job.conn.close()
            return

        job.log(blue(f"[BUILD] Building secrets..."))
        # build secrets
        try:
            # todo: change active channels
            output = subprocess.run(
                "cd 2025-eCTF-design &&"
                "rm -rf secrets &&"
                "mkdir secrets &&"
                "python -m ectf25_design.gen_secrets secrets/secrets.json 1 2 3 4",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            job.conn.send(output.stdout)
            job.conn.send(output.stderr)
        except Exception:
            job.log(
                red(
                    f"[BUILD] Failed to build commit {job.commit.hash}! Failed to build secrets!"
                )
            )
            job.log(red(traceback.format_exc()))
            job.conn.send(b"%*&1\n")
            job.conn.close()
            return

        job.log(blue(f"[BUILD] Building decoder..."))
        # build decoder
        try:
            output = subprocess.run(
                "cd 2025-eCTF-design &&" "./build.sh &&" "[ -d build_out ]",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            job.conn.send(output.stdout)
            job.conn.send(output.stderr)
        except Exception:
            job.log(
                red(f"[BUILD] Failed to build commit {job.commit.hash}! Build failed!")
            )
            job.log(red(traceback.format_exc()))
            job.conn.send(b"%*&1\n")
            job.conn.close()
            return

        # output in build_out
        subprocess.run(
            f"cd 2025-eCTF-design && mv build_out ../builds/{job.commit.hash}",
            shell=True,
            check=True,
        )
        job.log(blue(f"[BUILD] Built {job.commit.hash}!"))

        # send success
        job.conn.send(b"%*&0\n")
        job.conn.close()

        add_to_dist_queue(
            DistributionJob(
                job.conn,
                "PENDING",
                time.time(),
                job.commit.hash,
                f"./builds/{job.commit.hash}",
                "out_path",
            )
        )
    finally:
        active_build = None


def build_loop():
    while True:
        job = BUILD_QUEUE.get()
        build(job)


def init_build_queue():
    """
    Start the build queue
    """

    # login into github
    if (
        subprocess.run(
            ["gh", "auth", "status"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ).returncode
        != 0
    ):
        print("[BUILD] Setting up git...")
        try:
            subprocess.run(
                f"echo {GITHUB_TOKEN} | gh auth login --with-token",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["gh", "auth", "setup-git"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
        except Exception:
            print(red("[BUILD] Failed to set up git!"))
            print(red(traceback.format_exc()))
            os._exit(1)
            return

    # pull repo
    if (
        subprocess.run(
            ["git", "clone", "https://github.com/Purdue-eCTF/2025-eCTF-design"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).returncode
        != 0
    ):
        print("[BUILD] Found existing repo, reusing...")

    # create venv
    try:
        subprocess.run(
            "cd 2025-eCTF-design &&"
            "python -m venv .venv --prompt ectf-example &&"
            ". ./.venv/bin/activate &&"
            "python -m pip install ./tools/ &&"
            "python -m pip install -e ./design/",
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        print(red("[BUILD] Failed to create venv!"))
        print(traceback.format_exc())
        os._exit(1)
        return

    subprocess.run(["rm", "-rf", "./builds"])
    subprocess.run(["mkdir", "-p", "./builds"])

    print(blue("[BUILD] Build queue ready..."))
    Thread(target=build_loop, daemon=True).start()
