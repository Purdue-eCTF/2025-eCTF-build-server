import re
import socket
import sys
import time
import traceback

from builder import add_to_build_queue
from colors import blue
from config import AUTH_TOKEN, PORT
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
                    conn.sendall(b"Building our design\n")
                    hash, author, name, run_id = (
                        conn.recv(1024).decode("utf-8").split("|")
                    )
                    print(f"[CONN] New build request for commit {hash}...")

                    if len(hash) > 40 or len(hash) < 7 or re.search("[^0-9a-f]", hash):
                        print(f"[CONN] Invalid hash {hash}")
                        conn.sendall(b"Invalid input!")
                        conn.close()
                        continue

                    print(f"[CONN] Queuing build for commit {hash}...")

                    req = BuildJob(
                        conn,
                        "PENDING",
                        time.time(),
                        CommitInfo(hash, author, name, run_id),
                    )
                    push_webhook()
                    add_to_build_queue(req)
                elif method == "attack-target":
                    conn.sendall(b"Uploading target design\n")
                    # TODO

            except Exception:  # noqa: BLE001
                traceback.print_exc()
                conn.close()
                continue
        except KeyboardInterrupt:
            server.shutdown(socket.SHUT_RDWR)
            server.close()
            break
