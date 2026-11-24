"""Where each cell runner is on this machine, and its version (FR-HRN1).

A runner's command is, in this order: ``$RIHMASTO_RUNNER_<NAME>`` (for example ``RIHMASTO_RUNNER_CLAUDE_CODE``), as a
JSON list or split as a POSIX shell would; the command a choice names; the runner's binary on PATH. Gnomon's is the
kernel's own (``kernel.model.gnomon_cmd``). The version is what ``<command> --version`` prints; a command a team names
is pinned by its first word's version and the digest of its whole command line, so a changed line is a new version.
A runner that is not found says so, with what to do.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from typing import Any

from kernel.runners import RUNNERS, RunnerRefused, label_of

ENV_PREFIX = "RIHMASTO_RUNNER_"
VERSION_TIMEOUT = 20
_VERSION = re.compile(r"(\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.]+)?)")


def env_name(name: str) -> str:
    return ENV_PREFIX + re.sub(r"[^A-Z0-9]", "_", name.upper())


def split(text: str) -> list[str]:
    """A command line: a JSON list of words, or words split as a POSIX shell would."""
    text = text.strip()
    if text.startswith("["):
        words = json.loads(text)
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise RunnerRefused("a command given as JSON is a list of strings")
        return list(words)
    return shlex.split(text)


def command_of(name: str, choice: dict[str, Any] | None = None) -> list[str]:
    """The words that start runner ``name`` (without its arguments). Empty when nothing names one."""
    if name not in RUNNERS:
        raise RunnerRefused(f"there is no runner {name!r}; the runners are {', '.join(RUNNERS)}")
    named = os.environ.get(env_name(name))
    if named:
        return split(named)
    if name == "gnomon":
        from kernel.model import gnomon_cmd

        return gnomon_cmd()
    given = (choice or {}).get("binary")
    if isinstance(given, list) and given:
        return [str(w) for w in given]
    if name == "command":
        template = (choice or {}).get("command")
        return split(template)[:1] if isinstance(template, str) and template.strip() else []
    found = shutil.which(str(RUNNERS[name]["binary"]))
    return [found] if found else []


def parse_version(text: str) -> str | None:
    m = _VERSION.search(text or "")
    return m.group(1) if m else None


def _ask_version(cmd: list[str]) -> tuple[str | None, str]:
    try:
        proc = subprocess.run([*cmd, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT,
                              encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    raw = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return parse_version(raw), raw.splitlines()[0][:200] if raw else ""


def _missing(name: str) -> str:
    if name == "command":
        return "no command is named: give the command line, with {prompt_file} and {workdir} where they go"
    if name == "gnomon":
        return "Gnomon was not found: install it or set GNOMON_CMD (rihmasto doctor says more)"
    binary = RUNNERS[name]["binary"]
    return (f"{label_of(name)} was not found: `{binary}` is not on PATH; install it, or name its command in "
            f"{env_name(name)}")


def _present(cmd: list[str]) -> bool:
    """Whether a command can start: an interpreter and its script, or one program that exists or is on PATH."""
    return bool(cmd) and (len(cmd) > 1 or os.path.exists(cmd[0]) or shutil.which(cmd[0]) is not None)


def detect(name: str, choice: dict[str, Any] | None = None) -> dict[str, Any]:
    """Whether runner ``name`` is on this machine, its command and its version, or why not."""
    out: dict[str, Any] = {"runner": name, "label": label_of(name), "found": False, "version": None,
                           "command": None, "why": ""}
    line = str((choice or {}).get("command") or "").strip()
    try:
        cmd = command_of(name, choice) if line or name != "command" else []   # a command runner is its line
    except (RunnerRefused, ValueError) as exc:
        return out | {"why": str(exc)}
    if not _present(cmd):
        return out | {"why": _missing(name)}
    version, raw = _ask_version(cmd)
    out |= {"found": True, "command": os.path.basename(cmd[-1] if len(cmd) > 1 else cmd[0]), "raw": raw}
    if name == "command":
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()[:12]
        return out | {"version": f"{version or 'unversioned'}+cmd.{digest}"}
    if version is None:
        return out | {"found": False, "why": f"{label_of(name)} answered `--version` with no version: {raw or '-'}"}
    return out | {"version": version}

