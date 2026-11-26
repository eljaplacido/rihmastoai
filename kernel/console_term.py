"""Open a terminal here (FR-CON1): the operating system's own terminal in a project's workspace.

The cockpit runs on the person's own machine, on 127.0.0.1, so it can open a real terminal there: Windows
Terminal (else PowerShell in a console window of its own) on Windows; ``x-terminal-emulator``,
``gnome-terminal``, ``konsole`` or ``xterm`` on Linux; Terminal on macOS. It opens in the workspace
(kernel/console.py) with the project's routing environment: the model keys stored in Models setup in the
variables the routing names (``kernel.models_setup.gnomon_env``), Gnomon's folder first on PATH, and
``RIHMASTO_HOME`` and ``RIHMASTO_PROJECT``. No value of the environment is shown or recorded. Where Rihmasto
is not installed (no ``rihmasto`` on PATH), a ``rihmasto`` command in the factory home's ``bin`` folder runs this
checkout's command line with this Python, and is put first on the terminal's PATH, so the commands the cockpit
and Ask Rihma give work there as written.

``rihmasto shell <pid>`` does the same from the command line: an interactive subshell in the workspace,
which ends when the person leaves it. Both are recorded as ``console_opened`` (who, persona, workspace, how).

A full-screen program (an editor, ``top``, Gnomon's interactive loop) belongs here, never in the console,
whose output is line by line. What runs in a terminal is the person's own work on their own machine: it is
not isolated and not recorded command by command, so with access enforced (a cockpit behind IT's proxy,
the person elsewhere) the cockpit refuses to open one, and so does a request from an address other than
the loopback one (``--public-origin``).
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import console as kconsole
from kernel.store import Project

Launcher = Callable[[list[str], Path, dict[str, str]], Any]


SHIM_DIR = "bin"


def cli_installed(which: Callable[[str], str | None] = shutil.which) -> bool:
    """Whether the ``rihmasto`` command is on this machine's PATH (an installed Rihmasto)."""
    return bool(which("rihmasto"))


def cli_fallback(home: Path) -> str:
    """How to run Rihmasto's command line where ``rihmasto`` is not installed: this Python, from this checkout."""
    from kernel.store import REPO_ROOT

    return f'cd "{REPO_ROOT}"; & "{sys.executable}" -m kernel.cli --home "{Path(home).resolve()}"' if os.name == "nt" \
        else f'cd "{REPO_ROOT}" && "{sys.executable}" -m kernel.cli --home "{Path(home).resolve()}"'


def run_note(home: Path, which: Callable[[str], str | None] = shutil.which) -> str:
    """How the `rihmasto ...` commands the cockpit gives run as written in a terminal of one's own: where
    ``rihmasto`` is not installed, this checkout's command line with this factory's home in its place; where it
    is but this factory's home is not the default one, RIHMASTO_HOME set first. Empty when they run as given.
    Console, Open a terminal here sets both for its terminal."""
    from kernel.store import REPO_ROOT

    here = Path(home).resolve()
    if not cli_installed(which):
        return ("`rihmasto` is not installed on this machine's PATH: Console, Open a terminal here has it ready; in "
                f"any other terminal, put `{cli_fallback(here)}` in place of `rihmasto`.")
    if here == (REPO_ROOT / "var").resolve():
        return ""
    setting = f'$env:RIHMASTO_HOME = "{here}"' if os.name == "nt" else f'export RIHMASTO_HOME="{here}"'
    return (f"This factory's home is {here}: in a terminal of your own, run `{setting}` first (or put "
            f"`--home \"{here}\"` right after `rihmasto`); Open a terminal here sets it for you.")


def cli_shim(home: Path) -> Path:
    """A ``rihmasto`` command in the factory home's ``bin`` folder that runs this checkout's command line with
    this Python, for a terminal opened here when Rihmasto is not installed. Written again each time (the
    checkout or the Python may have moved); it names no secret."""
    from kernel.store import REPO_ROOT

    folder = Path(home) / SHIM_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "rihmasto.cmd").write_text(
        f'@setlocal\r\n@set "PYTHONPATH={REPO_ROOT};%PYTHONPATH%"\r\n@"{sys.executable}" -m kernel.cli %*\r\n',
        encoding="utf-8")
    sh = folder / "rihmasto"
    sh.write_text(f'#!/bin/sh\nPYTHONPATH="{REPO_ROOT}${{PYTHONPATH:+:$PYTHONPATH}}" exec "{sys.executable}" '
                  '-m kernel.cli "$@"\n', encoding="utf-8")
    with contextlib.suppress(OSError):
        sh.chmod(0o755)
    return folder


def environment(project: Project, *, which: Callable[[str], str | None] = shutil.which) -> dict[str, str]:
    """The terminal's environment: the routing's keys for Gnomon, Gnomon on PATH, the project named, and the
    ``rihmasto`` command on PATH (a shim in the factory home when Rihmasto is not installed)."""
    from kernel.model import gnomon_cmd

    env = kconsole._env(project, gnomon=True)
    if not cli_installed(which):         # first the shim, so Gnomon's own folder still comes first on PATH
        env["PATH"] = str(cli_shim(project.factory.home)) + os.pathsep + env.get("PATH", "")
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
    raise kconsole.ConsoleRefused(f"{NO_TERMINAL}: open one yourself in {where}")


NO_TERMINAL = "no terminal program was found on this machine (x-terminal-emulator, gnome-terminal, konsole, xterm)"


def terminal_for(launcher: Launcher, path: Path) -> list[str]:
    """The argv ``launcher`` opens in ``path``: the operating system's terminal (``terminal_argv``), unless the
    launcher stands for a terminal of its own and says which (``launcher.terminal_argv(path)``), as a test's
    stand-in that opens nothing does."""
    pick = getattr(launcher, "terminal_argv", None)
    return list(pick(path)) if callable(pick) else terminal_argv(path)


def missing_terminal(launcher: Launcher) -> str | None:
    """Why ``launcher`` cannot open a terminal on this machine (a Linux server without a desktop), or None."""
    try:
        terminal_for(launcher, Path.home())
    except kconsole.ConsoleRefused:
        return NO_TERMINAL
    return None


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
    argv = terminal_for(launcher, path)
    launcher(argv, path, environment(project))
    _opened(project, person=person, persona=persona, kind=kind, how="terminal")
    return {"opened": True, "workspace": kind, "path": str(path), "program": argv[0],
            "note": "a full-screen program, or Gnomon's interactive loop, runs there, and so does the rihmasto "
                    f"command for {project.pid}; it is your own terminal, not recorded command by command"}


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
