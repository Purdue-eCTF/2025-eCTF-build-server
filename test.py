import socket
import sys

conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
conn.connect(("localhost", 8888))

conn.send(b"test|build-ours")
print(conn.recv(1024).decode())
conn.send(
    f"aa22e6bd84dd79993bd0a4256d9fcbbbda548ca6|author|{sys.argv[1] if len(sys.argv) > 1 else "name"}|run_id".encode()
)

while True:
    buf = conn.recv(1024)
    if not buf:
        break
    line = buf.decode()
    if "%*&" in line:
        print(line[: (line.find("%*&"))])
        sys.exit(int(line[(line.find("%*&") + 3) :].split("\n")[0]))
    print(line, end="")
