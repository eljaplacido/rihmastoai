"""Shell commands that carry no data, or carry it quoted for the shell."""

import os
import shlex
import subprocess

CMD = "uptime"


def quoted(path):
    os.system("tar czf backup.tgz " + shlex.quote(path))


def joined(argv):
    subprocess.run(shlex.join(argv), shell=True, check=True)


def fixed_in_every_branch(verbose):
    if verbose:
        cmd = "uptime -p"
    else:
        cmd = "uptime"
    return subprocess.check_output(cmd, shell=True)


def constant(flag):
    subprocess.run(CMD, shell=True)


def no_shell(branch):
    subprocess.run(["git", "checkout", branch], shell=False, check=True)
    subprocess.run(f"git checkout {branch}".split(), check=True)


def exec_program(branch):
    os.execlp("git", "git", "checkout", branch)


def shell_fixed_script():
    subprocess.run(["bash", "-c", "make clean && make"], check=True)
