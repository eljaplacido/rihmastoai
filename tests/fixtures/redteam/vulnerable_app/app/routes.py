"""The product's routes."""

import os
import sqlite3
import subprocess

from app.server import route

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@route("GET", "/files/{name}")
def download(req):
    path = os.path.join(STATIC, req.params["name"])
    with open(path, "rb") as fh:  # seeded: RT-PY-PATH
        return 200, fh.read()


@route("GET", "/loans")
def loans(req):
    db = sqlite3.connect("data/loans.db")
    owner = req.query.get("owner", "")
    rows = db.execute(f"SELECT id, title FROM loans WHERE owner = '{owner}'").fetchall()  # seeded: RT-PY-SQL
    return 200, rows


@route("POST", "/ping")
def ping(req):
    host = req.body.get("host", "")
    done = subprocess.run("ping -c 1 " + host, shell=True, capture_output=True)  # seeded: RT-PY-SHELL
    return 200, done.stdout.decode("utf-8", "replace")


@route("POST", "/total")
def total(req):
    return 200, {"total": eval(req.body.get("expression", "0"))}  # seeded: RT-PY-EVAL
