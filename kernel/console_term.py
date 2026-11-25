"""Open a terminal here (FR-CON1): the operating system's own terminal in a project's workspace.

The cockpit runs on the person's own machine, on 127.0.0.1, so it can open a real terminal there: Windows
Terminal (else PowerShell in a console window of its own) on Windows; ``x-terminal-emulator``,
``gnome-terminal``, ``konsole`` or ``xterm`` on Linux; Terminal on macOS. It opens in the workspace
(kernel/console.py) with the project's routing environment: the model keys stored in Models setup in the
variables the routing names (``kernel.models_setup.gnomon_env``), Gnomon's folder first on PATH, and
``RIHMASTO_HOME`` and ``RIHMASTO_PROJECT``. No value of the environment is shown or recorded.

``rihmasto shell <pid>`` does the same from the command line: an interactive subshell in the workspace,
which ends when the person leaves it. Both are recorded as ``console_opened`` (who, persona, workspace, how).

A full-screen program (an editor, ``top``, Gnomon's interactive loop) belongs here, never in the console,
whose output is line by line. What runs in a terminal is the person's own work on their own machine: it is
not isolated and not recorded command by command, so with access enforced (a cockpit behind IT's proxy,
the person elsewhere) the cockpit refuses to open one, and so does a request from an address other than
the loopback one (``--public-origin``).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import console as kconsole
from kernel.store import Project

Launcher = Callable[[list[str], Path, dict[str, str]], Any]


def environment(project: Project) -> dict[str, str]:
    """The terminal's environment: the routing's keys for Gnomon, Gnomon on PATH, the project named."""
    from kernel.model import gnomon_cmd

    env = kconsole._env(project, gnomon=True)
    first = gnomon_cmd()[0]
    folder = str(Path(first).parent) if os.sep in first or (os.altsep and os.altsep in first) else ""
    if folder and folder not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = folder + os.pathsep + env.get("PATH", "")
    return env


def terminal_argv(path: Path, *, system: str | None = None,
                  which: Callable[[str], str | None] = shutil.which) -> list[str]:
    """The argv that opens the operating system's terminal in ``path`` (run it with ``cwd=path``)."""
    system = system or platform.system()
    where = str(path)
    if system == "Windows":
        if which("wt.exe") or which("wt"):
            return ["wt.exe", "-d", where, "powershell.exe", "-NoLogo"]
        return ["powershell.exe", "-NoLogo", "-NoExit"]
    if system == "Darwin":
        return ["open", "-a", "Terminal", where]
    for name, args in (("x-terminal-emulator", []), ("gnome-terminal", [f"--working-directory={where}"]),
                       ("konsole", ["--workdir", where]), ("xterm", [])):
        if which(name):
            return [name, *args]
    raise kconsole.ConsoleRefused("no terminal program was found on this machine (x-terminal-emulator, "
                                  f"gnome-terminal, konsole, xterm): open one yourself in {where}")


def launch(argv: list[str], cwd: Path, env: dict[str, str]) -> Any:
    """Start the terminal, detached from the cockpit: it outlives the request and the server."""
    kwargs: dict[str, Any] = {"cwd": str(cwd), "env": env, "stdin": subprocess.DEVNULL,
                              "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def _opened(project: Project, *, person: str, persona: str, kind: str, how: str) -> None:
    project.log("console_opened", {"person": person, "persona": persona, "workspace": kind, "how": how})


def open_terminal(project: Project, *, person: str, persona: str, launcher: Launcher) -> dict[str, Any]:
    """Open the terminal in the project's workspace for a person the console allows; recorded."""
    kconsole.check_persona(project, person, persona)
    path, kind = kconsole.ensure_workspace(project, person)
    argv = terminal_argv(path)
    launcher(argv, path, environment(project))
    _opened(project, person=person, persona=persona, kind=kind, how="terminal")
    return {"opened": True, "workspace": kind, "path": str(path), "program": argv[0],
            "note": "a full-screen program, or Gnomon's interactive loop, runs there; it is your own terminal, "
                    "not recorded command by command"}


def shell_argv(system: str | None = None) -> list[str]:
    system = system or platform.system()
    if system == "Windows":
        return [shutil.which("powershell.exe") or os.environ.get("COMSPEC") or "cmd.exe"]
    return [os.environ.get("SHELL") or "/bin/sh"]


def subshell(project: Project, *, person: str, persona: str,
             call: Callable[..., int] | None = None) -> dict[str, Any]:
    """``rihmasto shell``: an interactive subshell in the workspace, with the terminal's environment."""
    kconsole.check_persona(project, person, persona)
    path, kind = kconsole.ensure_workspace(project, person)
    _opened(project, person=person, persona=persona, kind=kind, how="subshell")
    code = (call or subprocess.call)(shell_argv(), cwd=str(path), env=environment(project))
    return {"workspace": kind, "path": str(path), "exit": code}
