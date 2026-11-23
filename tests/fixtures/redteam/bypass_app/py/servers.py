"""Servers bound to every interface with the host given by position."""

import asyncio

from flask import Flask

app = Flask(__name__)


def flask_positional():
    app.run("0.0.0.0", 8080)  # seeded: RT-PY-BINDALL


async def loop_server(proto):
    loop = asyncio.get_running_loop()
    return await loop.create_server(proto, "0.0.0.0", 8080)  # seeded: RT-PY-BINDALL


async def stream_server(handle):
    return await asyncio.start_server(handle, "0.0.0.0", 8080)  # seeded: RT-PY-BINDALL
