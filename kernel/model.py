"""Model calls. Every one goes through Gnomon: `gnomon task --role <role> --json` in a lane.

The factory never calls a model API itself. A role names a model and an endpoint in the
lane's surface, so which family answers is configuration, not code (D-0005). Tests use
`FakeModel`, which answers from a script.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

GNOMON_CMD_ENV = "GNOMON_CMD"


class ModelError(RuntimeError):
    """The model could not be asked, or its answer could not be used."""


def gnomon_cmd() -> list[str]:
    """The command that runs Gnomon, in this order:

    1. ``$GNOMON_CMD``, split as a POSIX shell would (on Windows, write paths with forward slashes);
    2. the source build in ``~/src/gnomonharness-master`` (D-0003 pinned `master` at fb458ea until
       a release read the `[verify]` keys; v0.6.6 is that release, so the owner may move back);
    3. ``gnomon`` on PATH, found as the shell finds it, so npm's ``gnomon.cmd`` shim works on
       Windows, where a bare "gnomon" does not start.

    `kernel/doctor.py` reports which one was found and its version (Rihma needs 0.6.5 or later;
    0.6.6 is recommended)."""
    import shutil

    cmd = os.environ.get(GNOMON_CMD_ENV)
    if cmd:
        return shlex.split(cmd)
    master = Path.home() / "src/gnomonharness-master/packages/gnomon-cli/gnomon.js"
    if master.exists():  # the pinned build (D-0003)
        node = shutil.which("node")
        if node is None:  # nvm's node is not on PATH in a non-login shell
            found = sorted(Path.home().glob(".nvm/versions/node/v22*/bin/node")) or \
                sorted(Path.home().glob(".nvm/versions/node/*/bin/node"))
            node = str(found[-1]) if found else "node"
        return [node, str(master)]
    return [shutil.which("gnomon") or "gnomon"]


class Model:
    """Ask a role a question and get its text answer."""

    last_record: dict | None = None

    def ask(self, prompt: str, *, role: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class GnomonModel(Model):
    """Runs `gnomon task` in ``lane_dir``. The lane's surface defines the roles and models.

    Only one gnomon run may work in a lane at a time (two runs flag each other's records as
    tampered), so calls take the lane's lock file.
    """

    def __init__(self, lane_dir: str | Path, *, timeout: int = 900, deadline: int | None = None):
        self.lane_dir = Path(lane_dir)
        self.timeout = timeout
        self.deadline = deadline
        self.records: list[dict] = []

    def ask(self, prompt: str, *, role: str) -> str:
        from kernel.lanes import lane_lock

        with lane_lock(self.lane_dir):
            record = run_gnomon_task(self.lane_dir, prompt, role=role, timeout=self.timeout,
                                     deadline=self.deadline)
        self.last_record = record
        self.records.append(record)
        if record.get("bucket") == "apparatus_failure":
            raise ModelError(f"gnomon apparatus failure for role {role}: {record.get('stop_reason')}")
        output = record.get("output")
        if not isinstance(output, str) or not output.strip():
            raise ModelError(f"gnomon task --role {role} answered nothing (stop: {record.get('stop_reason')})")
        return output


def run_gnomon_task(cwd: str | Path, prompt: str, *, role: str, timeout: int = 1800,
                    deadline: int | None = None, extra: tuple = ()) -> dict:
    """Run one `gnomon task` in ``cwd`` and return its JSON record. The caller holds the lane."""
    from kernel.access_isolation import cell, share

    cwd = Path(cwd)
    start = cell(gnomon_cmd(), cwd)     # access enforced: through IT's isolation runner, or refused (D-0016)
    tasks = cwd / ".factory-tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    fd, task_file = tempfile.mkstemp(prefix=f"{role}-", suffix=".md", dir=tasks)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(prompt)
    share(Path(task_file))              # a separate account reads it (mkstemp made it 0600)
    cmd = start + ["task", "--task-file", task_file, "--role", role, "--json", "--yes", *extra]
    if deadline:
        cmd += ["--deadline", str(deadline)]
    from kernel.models_setup import gnomon_env  # a key stored in Models setup reaches Gnomon in its variable

    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                              env=gnomon_env())
    except subprocess.TimeoutExpired as exc:
        raise ModelError(f"gnomon task --role {role} did not finish in {timeout}s") from exc
    except OSError as exc:  # not installed, or not startable: the apparatus, not the work (FR-C6)
        raise ModelError(f"gnomon could not be started ({cmd[0]}): {exc}; run `python -m kernel.cli doctor`") from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(task_file)
    try:
        record = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise ModelError(f"gnomon task --role {role} exit {proc.returncode}: no JSON record; {tail}") from exc
    record.setdefault("_exit", proc.returncode)
    return record


class FakeModel(Model):
    """Answers from a script. ``script`` is a function (prompt, role) -> text, or a dict from
    role to a list of answers handed out in order."""

    def __init__(self, script):
        self.script = script
        self.calls: list[tuple[str, str]] = []

    def ask(self, prompt: str, *, role: str) -> str:
        self.calls.append((role, prompt))
        if callable(self.script):
            return self.script(prompt, role)
        answers = self.script.get(role)
        if not answers:
            raise ModelError(f"FakeModel has no answer left for role {role!r}")
        return answers.pop(0)


_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def extract_json(text: str):
    """Pull one JSON value out of a model's answer: a fenced ```json block if there is one,
    else the first balanced {...} or [...]."""
    for block in _FENCE.findall(text or ""):
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            continue
    text = text or ""
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(opener, start + 1)
    raise ModelError("the answer holds no JSON value")
