"""Commands and queries whose data arrives on a binding the last plain assignment does not show."""

import os
import sqlite3
import subprocess

from flask import request

CMD = "uptime"
target = "localhost"


def augmented():
    cmd = "ping -c 1 "
    cmd += request.args["host"]
    subprocess.run(cmd, shell=True)  # seeded: RT-PY-SHELL


def branch(custom):
    if custom:
        cmd = request.args["custom"]
    else:
        cmd = "uptime"
    return subprocess.check_output(cmd, shell=True)  # seeded: RT-PY-SHELL


def loop():
    cmd = "true"
    for cmd in request.json["steps"]:
        subprocess.run(cmd, shell=True)  # seeded: RT-PY-SHELL


def default(cmd=CMD):
    subprocess.run(cmd, shell=True)  # seeded: RT-PY-SHELL


def shadow(target):
    os.system("ping -c 1 " + target)  # seeded: RT-PY-SHELL


def search(name):
    con = sqlite3.connect("app.db")
    sql = "SELECT id FROM users WHERE 1=1"
    sql += f" AND name = '{name}'"
    return con.execute(sql)  # seeded: RT-PY-SQL
