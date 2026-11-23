"""Shell commands passed in ways a literal `shell=True` test does not see."""

import asyncio
import os
import subprocess

OPTS = {"shell": True}
USE_SHELL = True


def sh(*args, **kwargs):
    return subprocess.run(*args, shell=True, check=True, **kwargs)  # seeded: RT-PY-SHELL


def grep(q):
    subprocess.run("grep -r " + q, **OPTS)  # seeded: RT-PY-SHELL


def checkout(branch):
    subprocess.run(f"git checkout {branch} && make", shell=USE_SHELL)  # seeded: RT-PY-SHELL


def computed(branch):
    subprocess.run(f"git checkout {branch}", shell=bool(1))  # seeded: RT-PY-SHELL


def argv(branch):
    subprocess.run(["bash", "-c", f"git checkout {branch} && make"])  # seeded: RT-PY-SHELL


async def convert(name):
    await asyncio.create_subprocess_shell(f"convert {name} out.png")  # seeded: RT-PY-SHELL


def exec_shell(host):
    os.execlp("sh", "sh", "-c", "ping -c 1 " + host)  # seeded: RT-PY-SHELL
