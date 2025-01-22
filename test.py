import socket
import sys

conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
conn.connect(("localhost", 8888))

conn.send("test|build-ours".encode())
conn.recv(1024)
conn.send(f"4a98b591453bfd4346edfd89ccfdfc15816d478c|author|name|run_id".encode())

while True:
  buf = conn.recv(1024)
  if not buf:
    break
  line = buf.decode()
  if "%*&" in line:
      print(line[:(line.find("%*&"))])
      sys.exit(int(line[(line.find("%*&") + 3):].split("\n")[0]))
  print(line, end = "")