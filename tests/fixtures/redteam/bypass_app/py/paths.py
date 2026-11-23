"""Request-derived paths: route parameters, more sinks, and checks that do not contain anything."""

import builtins
import logging
import os
import re
import tarfile
from pathlib import Path

import aiofiles
from fastapi import FastAPI
from fastapi.responses import FileResponse
from flask import Flask, abort, request
from tornado.web import RequestHandler

app = Flask(__name__)
api = FastAPI()
UPLOADS = "/srv/uploads"
BASE = Path("/srv/files")
BLOCKED = {"secret.txt"}


@app.route("/files/<path:name>")
def flask_route(name):
    return open(os.path.join(UPLOADS, name), "rb").read()  # seeded: RT-PY-PATH


@api.get("/download/{filename}")
def fastapi_route(filename: str):
    return FileResponse(os.path.join(UPLOADS, filename))  # seeded: RT-PY-PATH


class Files(RequestHandler):
    def get(self):
        name = self.get_argument("name")
        with open(os.path.join(UPLOADS, name)) as fh:  # seeded: RT-PY-PATH
            self.write(fh.read())


async def aio(request):
    async with aiofiles.open("/srv/uploads/" + request.match_info["name"]) as fh:  # seeded: RT-PY-PATH
        return await fh.read()


def builtin_open():
    return builtins.open("/srv/uploads/" + request.args["name"]).read()  # seeded: RT-PY-PATH


def zip_slip():
    tarfile.open(fileobj=request.files["archive"].stream).extractall("/srv/unpacked")  # seeded: RT-PY-PATH


def startswith_unresolved():
    base = os.path.abspath("uploads")
    path = os.path.join(base, request.args["name"])
    if not path.startswith(base):
        abort(403)
    return open(path).read()  # seeded: RT-PY-PATH


def commonpath_unresolved():
    path = os.path.join(UPLOADS, request.args["name"])
    if os.path.commonpath([UPLOADS, path]) != UPLOADS:
        abort(403)
    return open(path).read()  # seeded: RT-PY-PATH


def logged_only():
    p = (BASE / request.args["name"]).resolve()
    if not p.is_relative_to(BASE):
        logging.warning("outside the base: %s", p)
    return p.read_bytes()  # seeded: RT-PY-PATH


def denylist():
    name = request.args["name"]
    if name in BLOCKED:
        abort(403)
    return open(os.path.join(UPLOADS, name)).read()  # seeded: RT-PY-PATH


def not_in_empty():
    name = request.args.get("name")
    if name not in (None, ""):
        return open(os.path.join("/srv/uploads", name)).read()  # seeded: RT-PY-PATH
    return ""


def regex_allows_dots():
    name = request.args["name"]
    if not re.fullmatch(r"[\w./-]+", name):
        abort(400)
    return open(os.path.join(UPLOADS, name)).read()  # seeded: RT-PY-PATH
