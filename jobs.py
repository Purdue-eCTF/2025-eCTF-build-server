from dataclasses import dataclass
from socket import socket


@dataclass
class BuildJob:
  hash: str
  conn: socket


@dataclass
class DistributionJob:
  path: str
  conn: socket

