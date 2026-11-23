"""A worker the entry script runs: it listens on every interface inside the container."""

import socket


def listen():
    s = socket.socket()
    s.bind(("0.0.0.0", 9090))
    s.listen()
    return s
