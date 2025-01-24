import subprocess
import sys
import time
import traceback
from queue import Queue
from threading import Thread

from colors import blue, red
from config import DESIGN_REPO, GITHUB_TOKEN
from distribution import add_to_dist_queue
from jobs import BuildJob, DistributionJob
from webhook import push_webhook

BUILD_QUEUE: Queue[BuildJob] = Queue()
active_build: BuildJob | None = None


def add_to_build_queue(job: BuildJob):
    """
    Add a job to the build queue
    :param job: The job to add
    """
    BUILD_QUEUE.put(job)


def build(job: BuildJob):
    global active_build
    active_build = job
    job.status = "BUILDING"
    push_webhook("BUILD", job)

    try:
        job.log(blue("[BUILD] Pulling from repo..."))
        # pull from repo
        try:
            output = subprocess.run(
                "cd 2025-eCTF-design &&"
                "git checkout main &&"
                "git fetch &&"
                "git reset --hard origin/main &&"
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

            job.status = "FAILED"
            push_webhook("BUILD", job)
            return

        job.log(blue("[BUILD] Building secrets..."))
        # build secrets
        try:
            # todo: change active channels
            output = subprocess.run(
                "cd 2025-eCTF-design &&"
                "rm -rf secrets &&"
                "mkdir secrets &&"
                ". ./.venv/bin/activate &&"
                "python -m ectf25_design.gen_secrets secrets/secrets.json 1 2 3 4",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            job.conn.send(output.stdout)
            job.conn.send(output.stderr)
        except subprocess.CalledProcessError as e:
            job.log(
                red(
                    f"[BUILD] Failed to build commit {job.commit.hash}! Failed to build secrets!"
                )
            )
            job.conn.send(e.stdout or b"")
            job.conn.send(e.stderr or b"")
            job.log(red(traceback.format_exc()))
            job.conn.send(b"%*&1\n")
            job.conn.close()

            job.status = "FAILED"
            push_webhook("BUILD", job)
            return

        job.log(blue(f"[BUILD] Building decoder..."))
        # build decoder
        try:
            output = subprocess.run(
                "cd 2025-eCTF-design && ./build.sh && "
                '[ -n "$(ls -A build_out 2>/dev/null)" ]',
                shell=True,
                check=True,
                timeout=60 * 5,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            job.conn.send(output.stdout)
            job.conn.send(output.stderr)
        except subprocess.CalledProcessError as e:
            job.log(
                red(f"[BUILD] Failed to build commit {job.commit.hash}! Build failed!")
            )
            job.conn.send(e.stdout or b"")
            job.conn.send(e.stderr or b"")
            job.log(red(traceback.format_exc()))
            job.conn.send(b"%*&1\n")
            job.conn.close()

            job.status = "FAILED"
            push_webhook("BUILD", job)
            return

        # output in build_out
        try:
            subprocess.run(
                f"cd 2025-eCTF-design && rm -rf ../builds/{job.commit.hash} && mv build_out ../builds/{job.commit.hash}",
                shell=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            job.log(
                red(f"[BUILD] Failed to build commit {job.commit.hash}! Build failed!")
            )
            job.conn.send(e.stdout or b"")
            job.conn.send(e.stderr or b"")
            job.log(red(traceback.format_exc()))
            job.conn.send(b"%*&1\n")
            job.conn.close()

            job.status = "FAILED"
            push_webhook("BUILD", job)
            return

        job.log(blue(f"[BUILD] Built {job.commit.hash}!"))

        active_build = None
        push_webhook()

        add_to_dist_queue(
            DistributionJob(
                job.conn,
                "PENDING",
                time.time(),
                job.commit.hash,
                f"./builds/{job.commit.hash}",
                job.commit.hash,
                job.commit,
            )
        )
    finally:
        active_build = None


def build_loop():
    while True:
        job = BUILD_QUEUE.get()
        try:
            build(job)
        except (BrokenPipeError, TimeoutError):
            print(red("[BUILD] Client disconnected"))
        except Exception:  # error handling :tm:
            push_webhook("BUILD", job)
            traceback.print_exc()


def init_build_queue():
    """
    Start the build queue
    """

    # login into github
    if (
        subprocess.run(
            ["gh", "auth", "status"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
            sys.exit(1)
            return

    # pull repo
    if (
        subprocess.run(
            [
                "git",
                "clone",
                DESIGN_REPO,
                "2025-eCTF-design",
            ],
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
            timeout=60,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except Exception:
        print(red("[BUILD] Failed to create venv!"))
        print(traceback.format_exc())
        sys.exit(1)
        return

    subprocess.run(["rm", "-rf", "./builds"])
    subprocess.run(["mkdir", "-p", "./builds"])

    print(blue("[BUILD] Build queue ready..."))
    Thread(target=build_loop, daemon=True).start()
