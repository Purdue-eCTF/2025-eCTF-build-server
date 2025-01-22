from dataclasses import dataclass
from socket import socket


@dataclass
class CommitInfo:
    hash: str
    author: str
    message: str
    run_id: str


@dataclass
class Job:
    conn: socket
    status: str
    start_time: float

    def to_json(self):
        return "{}"

    def log(self, msg: str):
        print(msg)
        self.conn.send(msg.encode() + b"\n")


@dataclass
class BuildJob(Job):
    commit: CommitInfo


@dataclass
class DistributionJob(Job):
    name: str
    in_path: str
    out_path: str
