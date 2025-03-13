import re
import socket
import sys
import time
import traceback

from builder import add_to_build_queue
from colors import blue
from config import AUTH_TOKEN, PORT
from distribution import AttackingJob, AttackScriptJob, UpdateCIJob, add_to_dist_queue
from jobs import BuildJob, CommitInfo
from webhook import push_webhook

# create socket, interface with github


def serve():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", PORT))  # noqa: S104
    server.listen()

    print(blue(f"[CONN] Listening on port {PORT}..."))
    sys.stdout.flush()

    while True:
        try:
            conn, addr = server.accept()
            conn.settimeout(10)
            print(f"[CONN] New connection from {addr}")

            try:
                token, method = conn.recv(1024).decode().split("|")
                if token != AUTH_TOKEN:
                    print("[CONN] Invalid connection, wrong token")
                    conn.close()
                    continue

                if method == "build-ours":
                    conn.sendall(b"[CONN] Building our design\n")
                    hash, author, name, run_id = (
                        conn.recv(1024).decode("utf-8").split("|")
                    )
                    print(f"[CONN] New build request for commit {hash}...")

                    if len(hash) > 40 or len(hash) < 7 or re.search(r"[^0-9a-f]", hash):
                        print(f"[CONN] Invalid hash {hash}")
                        conn.sendall(f"[CONN] Invalid hash {hash}\n".encode())
                        conn.close()
                        continue

                    print(f"[CONN] Queuing build for commit {hash}...")

                    req = BuildJob(
                        conn,
                        "PENDING",
                        time.time(),
                        CommitInfo(hash, author, name, run_id),
                    )
                    add_to_build_queue(req)
                    push_webhook()
                elif method == "attack-target":
                    conn.sendall(b"[CONN] Attacking target design\n")
                    team = conn.recv(1024).decode("utf-8")

                    if "/" in team:
                        print(f"[CONN] Invalid team {team}")
                        conn.sendall(f"[CONN] Invalid team{team}\n".encode())
                        conn.close()
                        continue

                    add_to_dist_queue(AttackingJob(conn, "PENDING", time.time(), team))
                    push_webhook()
                elif method == "attack-script":
                    conn.sendall(b"[CONN] Attacking target with manual attack script\n")
                    script_name, team = conn.recv(1024).decode("utf-8").split("|")

                    if "/" in script_name:
                        print(f"[CONN] Invalid script name {script_name}")
                        conn.sendall(
                            f"[CONN] Invalid script name {script_name}\n".encode()
                        )
                        conn.close()
                        continue

                    add_to_dist_queue(
                        AttackScriptJob(conn, "PENDING", time.time(), team, script_name)
                    )
                    push_webhook()
                elif method == "update-ci":
                    conn.sendall(b"[CONN] Updating CI\n")
                    UpdateCIJob(conn, "PENDING", time.time()).update_ci()

            except Exception:  # noqa: BLE001
                traceback.print_exc()
                conn.close()
                continue
        except KeyboardInterrupt:
            server.shutdown(socket.SHUT_RDWR)
            server.close()
            break
