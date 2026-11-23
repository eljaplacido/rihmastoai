"""The product's routes."""

import ast
import os
import re
import sqlite3
import subprocess
from pathlib import Path

from app.server import route

STATIC = Path(__file__).resolve().parent / "static"
HOST_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{0,252}")


@route("GET", "/files/{name}")
def download(req):
    path = (STATIC / req.params["name"]).resolve()
    if not path.is_relative_to(STATIC):
        return 404, {"error": "not found"}
    with open(path, "rb") as fh:
        return 200, fh.read()


@route("GET", "/icons/{name}")
def icon(req):
    name = os.path.basename(req.params["name"])
    with open(os.path.join(STATIC, "icons", name), "rb") as fh:
        return 200, fh.read()


@route("GET", "/loans")
def loans(req):
    db = sqlite3.connect("data/loans.db")
    owner = req.query.get("owner", "")
    rows = db.execute("SELECT id, title FROM loans WHERE owner = ?", (owner,)).fetchall()
    return 200, rows


@route("POST", "/loans/batch")
def loans_by_id(req):
    db = sqlite3.connect("data/loans.db")
    ids = [int(i) for i in req.body.get("ids", [])]
    marks = ",".join("?" * len(ids))
    return 200, db.execute(f"SELECT id, title FROM loans WHERE id IN ({marks})", ids).fetchall()


@route("POST", "/ping")
def ping(req):
    host = req.body.get("host", "")
    if not HOST_NAME.fullmatch(host):
        return 400, {"error": "not a host name"}
    done = subprocess.run(["ping", "-c", "1", host], capture_output=True, timeout=10)
    return 200, done.stdout.decode("utf-8", "replace")


@route("GET", "/uptime")
def uptime(req):
    done = subprocess.run("uptime", shell=True, capture_output=True, timeout=5)
    return 200, done.stdout.decode("utf-8", "replace")


@route("POST", "/total")
def total(req):
    return 200, {"total": ast.literal_eval(req.body.get("expression", "0"))}
