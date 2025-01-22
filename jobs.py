from dataclasses import dataclass
from socket import socket


@dataclass
class CommitInfo:
    hash: str
    author: str
    message: str
    run_id: str


@dataclass
class BuildJob:
    conn: socket
    commit: CommitInfo
    status: str
    start_time: float


@dataclass
class DistributionJob:
    conn: socket
    name: str
    in_path: str
    out_path: str
    status: str
    start_time: float
