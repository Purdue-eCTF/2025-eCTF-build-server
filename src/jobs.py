import subprocess
import traceback
from dataclasses import dataclass
from socket import socket

from colors import red


@dataclass
class CommitInfo:
    hash: str
    author: str
    message: str
    run_id: str

    def to_json(self):
        return {
            "hash": self.hash,
            "name": self.message,
            "author": self.author,
            "runId": self.run_id,
        }


@dataclass
class Job:
    conn: socket
    status: str
    start_time: float

    def to_json(self):
        return {}

    def log(self, msg: str):
        print(msg)
        self.conn.send(msg.encode() + b"\n")

    def on_error(self, e: Exception, msg: str):
        self.log(red(msg))
        if isinstance(e, subprocess.CalledProcessError):
            self.conn.send(e.stdout or b"")
            self.conn.send(e.stderr or b"")
        self.log(red(traceback.format_exc()))
        self.conn.send(b"%*&1\n")
        self.conn.close()
        self.status = "FAILED"


@dataclass
class BuildJob(Job):
    commit: CommitInfo

    def to_json(self):
        return {
            "result": self.status,
            "actionStart": round(self.start_time),
            "commit": self.commit.to_json(),
        }
