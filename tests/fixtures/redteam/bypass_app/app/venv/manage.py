"""A product package that happens to be named like a virtual environment (it holds no pyvenv.cfg)."""

import os

from flask import request


def make_env():
    os.system("virtualenv " + request.args["name"])  # seeded: RT-PY-SHELL
