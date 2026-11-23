"""Sinks reached through a local name, getattr, __import__ or a star import."""

import builtins
import os
import pickle
from subprocess import *

from flask import request

run = os.system
evaluate = eval
unpack = pickle.loads


def local_alias(host):
    run("ping -c 1 " + host)  # seeded: RT-PY-SHELL


def by_getattr(host):
    getattr(os, "system")("ping -c 1 " + host)  # seeded: RT-PY-SHELL


def by_import(host):
    __import__("os").system("ping -c 1 " + host)  # seeded: RT-PY-SHELL


def by_star(host):
    return check_output("ping -c 1 " + host, shell=True)  # seeded: RT-PY-SHELL


def renamed_eval():
    return evaluate(request.json["expr"])  # seeded: RT-PY-EVAL


def builtin_eval(expr):
    return getattr(builtins, "eval")(expr)  # seeded: RT-PY-EVAL


def renamed_loads(blob):
    return unpack(blob)  # seeded: RT-PY-DESER
