import socket
import sys

conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
conn.connect(("localhost", 8889))

conn.send(b"test|build-ours")
print(conn.recv(1024).decode())
conn.send(f"f3496314afb4f91519e104b962febd8d67b4d6b1|author|name|run_id".encode())

while True:
    buf = conn.recv(1024)
    if not buf:
        break
    line = buf.decode()
    if "%*&" in line:
        print(line[: (line.find("%*&"))])
        sys.exit(int(line[(line.find("%*&") + 3) :].split("\n")[0]))
    print(line, end="")
