import os
import subprocess
import sys
import time
import traceback
from queue import Queue
from threading import Thread

from colors import blue, red
from config import DESIGN_REPO, GITHUB_TOKEN
from distribution import TestingJob, add_to_dist_queue
from jobs import BuildJob
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
    global active_build  # noqa: PLW0603
    active_build = job
    job.status = "BUILDING"
    job.start_time = time.time()
    push_webhook("BUILD", job)

    build_folder = f"./builds/{job.commit.run_id}"

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
            job.conn.sendall(output.stdout)
            job.conn.sendall(output.stderr)
        except subprocess.CalledProcessError as e:
            job.on_error(
                e, f"[BUILD] Failed to build commit {job.commit.hash}! No commit found."
            )

            job.status = "FAILED"
            push_webhook("BUILD", job)
            return

        job.log(blue("[BUILD] Building secrets..."))
        # build secrets
        try:
            # todo: change active channels
            output = subprocess.run(
                "cd 2025-eCTF-design &&"
                "rm -rf secrets/* &&"
                "mkdir -p secrets &&"
                ". ./.venv/bin/activate &&"
                "pip install -e ./design &&"
                "python -m ectf25_design.gen_secrets secrets/global.secrets 1 2 3 4",
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            job.conn.sendall(output.stdout)
            job.conn.sendall(output.stderr)
        except subprocess.CalledProcessError as e:
            job.on_error(
                e,
                f"[BUILD] Failed to build commit {job.commit.hash}! Failed to build secrets!",
            )

            job.status = "FAILED"
            push_webhook("BUILD", job)
            return

        job.log(blue("[BUILD] Building decoder..."))
        # build decoder
        try:
            if os.getenv("DOCKER"):
                # docker-in-docker jank
                # ectf_build_server_build_out is volume mounted to ~/mounts/build_out which is symlinked to ~/src/2025-eCTF-design/build_out
                # ectf_build_server_decoder is volume mounted to ~/mounts/decoder which is copied from ~/src/2025-eCTF-design/decoder
                # ectf_build_server_secrets is volume mounted to ~/mounts/secrets which is symlinked to ~/src/2025-eCTF-design/secrets
                output = subprocess.run(
                    "cd 2025-eCTF-design && "
                    "cp -r decoder/* ~/mounts/decoder && rm -rf build_out/* &&"
                    "(cd decoder && docker build -t decoder . && "
                    "docker run --rm -v ectf_build_server_build_out:/out "
                    "-v ectf_build_server_decoder:/decoder -v ectf_build_server_secrets:/secrets:ro "
                    "-e DECODER_ID=0xdeadbeef -e LOCAL_SECRETS_FILE=/secrets/global.secrets decoder;) &&"
                    '[ -n "$(ls -A build_out 2>/dev/null)" ]',
                    shell=True,
                    check=True,
                    timeout=60 * 10,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            else:
                output = subprocess.run(
                    "cd 2025-eCTF-design && ./build.sh && "
                    '[ -n "$(ls -A build_out 2>/dev/null)" ]',
                    shell=True,
                    check=True,
                    timeout=60 * 10,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            job.conn.sendall(output.stdout)
            job.conn.sendall(output.stderr)
        except subprocess.SubprocessError as e:
            job.on_error(
                e, f"[BUILD] Failed to build commit {job.commit.hash}! Build failed!"
            )

            job.status = "FAILED"
            push_webhook("BUILD", job)
            return

        # output in build_out
        try:
            subprocess.run(
                f"cp -Lr 2025-eCTF-design/ {build_folder}",
                shell=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            job.on_error(
                e, f"[BUILD] Failed to build commit {job.commit.hash}! Build failed!"
            )

            job.status = "FAILED"
            push_webhook("BUILD", job)
            return

        job.log(blue(f"[BUILD] Built {job.commit.hash}!"))

        active_build = None
        push_webhook()

        add_to_dist_queue(
            TestingJob(
                job.conn,
                "PENDING",
                time.time(),
                build_folder,
                job.commit,
            )
        )
    finally:
        active_build = None
        BUILD_QUEUE.task_done()


def build_loop():
    while True:
        job = BUILD_QUEUE.get()
        try:
            build(job)
        except (BrokenPipeError, TimeoutError):
            print(red("[BUILD] Client disconnected"))
        except Exception:  # noqa: BLE001
            # error handling :tm:
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
            check=False,
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
        except subprocess.CalledProcessError:
            print(red("[BUILD] Failed to set up git!"))
            print(red(traceback.format_exc()))
            sys.exit(1)
            return

    # pull repo
    if (
        subprocess.run(
            "cd 2025-eCTF-design && git status",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        ).returncode
        == 0
    ):
        print("[BUILD] Found existing repo, reusing...")
    else:
        print("[BUILD] Cloning repo...")
        subprocess.run(
            ["git", "clone", DESIGN_REPO, "2025-eCTF-design"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    if os.getenv("DOCKER"):  # setup for docker-in-docker jank
        subprocess.run(
            "rm -rf ./2025-eCTF-design/secrets ./2025-eCTF-design/build_out;"
            "ln -s ~/mounts/secrets ./2025-eCTF-design/secrets;"
            "ln -s ~/mounts/build_out ./2025-eCTF-design/build_out",
            shell=True,
            check=True,
        )

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
    except subprocess.SubprocessError:
        print(red("[BUILD] Failed to create venv!"))
        print(traceback.format_exc())
        sys.exit(1)
        return

    subprocess.run(["rm", "-rf", "./builds"], check=True)
    subprocess.run(["mkdir", "-p", "./builds"], check=True)

    print(blue("[BUILD] Build queue ready..."))
    Thread(target=build_loop, daemon=True).start()
