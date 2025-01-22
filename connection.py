import re
import socket
import time
import traceback

from builder import add_to_build_queue
from colors import blue, red
from jobs import BuildJob, CommitInfo
from webhook import push_webhook

# create socket, interface with github
PORT = 8888
TOKEN = "test"


def serve():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", PORT))
    server.listen()

    print(blue(f"[CONN] Listening on port {PORT}..."))

    while True:
        try:
            conn, addr = server.accept()
            print(f"[CONN] New connection from {addr}")

            try:
                token, method = conn.recv(1024).decode().split("|")
                if token != TOKEN:
                    print(f"[CONN] Invalid connection, wrong token")
                    conn.close()
                    continue

                if method == "build-ours":
                    conn.send(b"Building our design\n")
                    hash, author, name, run_id = (
                        conn.recv(1024).decode("utf-8").split("|")
                    )
                    print(f"[CONN] New build request for commit {hash}...")

                    if len(hash) > 40 or len(hash) < 7 or re.search("[^0-9a-f]", hash):
                        conn.send(b"Invalid input!")
                        conn.close()
                        continue
                    print(f"Queuing build for commit {hash}...")

                    req = BuildJob(
                        conn,
                        CommitInfo(hash, author, name, run_id),
                        "PENDING",
                        time.time(),
                    )
                    add_to_build_queue(req)
                    push_webhook()
                elif method == "build-target":
                    conn.send(b"Building target design\n")
                    # TODO

            except Exception:
                traceback.print_exc()
                conn.close()
                continue

            #  threading.Thread(target=check_close, args=(req,), daemon=True).start()

        except KeyboardInterrupt:
            break
