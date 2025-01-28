from dataclasses import dataclass
from socket import socket


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


@dataclass
class BuildJob(Job):
    commit: CommitInfo

    def to_json(self):
        return {
            "result": self.status,
            "actionStart": round(self.start_time),
            "commit": self.commit.to_json(),
        }
