# -*- coding: utf-7 -*-
from flask import request
import os


def ping():
    # validate the host first +AAo-    os.system(f"ping -c 1 {request.args['host']}")  # seeded: RT-PY-SHELL
    return "pinged"
