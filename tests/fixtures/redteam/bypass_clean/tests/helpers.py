"""Test helpers: a free port is found by binding port 0 and releasing it."""

import socket


def free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]
