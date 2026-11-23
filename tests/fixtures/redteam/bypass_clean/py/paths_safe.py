"""Request-derived paths with a check that really contains them."""

import os
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from flask import Flask, abort, request
from werkzeug.utils import safe_join

app = Flask(__name__)
BASE = Path("/srv/files").resolve()
UPLOADS = "/srv/uploads"
PAGES = {"/": "index.html", "/about": "about.html"}
NAME = re.compile(r"[a-z0-9_-]{1,64}\.txt")


@app.route("/files/<path:name>")
def joined_safely(name):
    path = safe_join(UPLOADS, name)
    if path is None:
        abort(404)
    return open(path, "rb").read()


@app.route("/docs/<path:name>")
def parents_check(name):
    p = (BASE / name).resolve()
    if BASE not in p.parents:
        abort(403)
    return p.read_bytes()


@app.route("/notes/<path:name>")
def resolved_relative(name):
    p = (BASE / name).resolve()
    if not p.is_relative_to(BASE):
        abort(403)
    return p.read_text()


def realpath_prefix():
    real = os.path.realpath(os.path.join(UPLOADS, request.args["name"]))
    if not real.startswith(UPLOADS + os.sep):
        abort(403)
    return open(real).read()


def strict_pattern():
    name = request.args["name"]
    if not NAME.fullmatch(name):
        abort(400)
    return open(os.path.join(UPLOADS, name)).read()


def fixed_names():
    name = request.args["name"]
    if name not in ("report.pdf", "logo.png"):
        abort(404)
    return open(os.path.join(UPLOADS, name), "rb").read()


class Pages(BaseHTTPRequestHandler):
    def do_GET(self):
        page = PAGES.get(self.path)
        if page is None:
            self.send_error(404)
            return
        with open(os.path.join("www", page), "rb") as fh:
            self.wfile.write(fh.read())
