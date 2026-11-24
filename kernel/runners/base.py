"""The runner interface: a task envelope and a working copy in, a diff and a run record out (FR-HRN1).

What every harness is given is the same: the envelope the factory writes for the task (kernel/dispatch.py), its
write scope and protected paths said plainly, and the project's own conventions (AGENTS.md, CLAUDE.md, rules files)
when the working copy has them. Holdouts are never in it: they stay in their custody, outside every working copy.

A harness other than Gnomon runs as a child process in the working copy, never a shell. Its environment leaves out
where the factory keeps its home, its lanes and its stored keys, so nothing in the run is pointed at the holdout
custody. Its prompt is a file under ``.factory-tasks/`` (never committed) and, where the harness reads it, standard
input. What it did is read from its own output: the tool calls when it shows them, its model, its answer.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kernel.runners import RUNNERS, RunnerRefused, assurance_of, label_of

TOOL_CALLS_KEPT = 200
# Where the factory keeps what no harness needs: its home (and so the holdout custody), its lanes, stored keys.
HIDDEN_ENV = ("RIHMASTO_HOME", "RIHMA_HOME", "GNOMONFACTORY_HOME", "GF_LANES", "RIHMASTO_SECRETS_FILE",
              "RIHMA_ACCESS_FILE", "GNOMON_CMD")


@dataclass
class Envelope:
    """What a runner is given for one task (the holdouts never are)."""

    task: str
    prompt: str
    write_scope: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    conventions: str = ""
    tests: list[str] = field(default_factory=list)
    role: str = "builder"


@dataclass
class RunResult:
    """A run's record and the diff it left in the working copy (staged, against the working copy's HEAD)."""

    record: dict[str, Any]
    diff: str = ""
    changed: list[str] = field(default_factory=list)


def conventions(workdir: Path, scope: list[str] | None = None, *, prompt: str = "") -> str:
    """The project's own instructions for an agent (AGENTS.md, CLAUDE.md, Cursor and Copilot rules) that apply to
    the files a task may write, recognised and matched exactly as a Gnomon builder's envelope matches them
    (kernel/agent_context_use.py), so either runner is given the same rules. A verifier, which writes nothing, is
    given those that apply anywhere. "" when there are none, or when ``prompt`` (the factory's envelope, which
    holds them for an adopted project) already says them."""
    from kernel.agent_context import from_folder
    from kernel.agent_context_use import HEADING, builder_lines

    if HEADING in prompt:
        return ""
    try:
        ctx = from_folder(workdir, keep_text=True)
    except OSError:
        return ""
    return "\n".join(builder_lines(ctx, list(scope or ["**"]))).strip()


def _with_conventions(lines: list[str], env: Envelope) -> list[str]:
    return lines + (["", env.conventions] if env.conventions else [])


def compose_prompt(env: Envelope) -> str:
    """The envelope as a harness other than Gnomon reads it: the factory's envelope, then what is checked after the
    run, then the project's conventions. A verifier reads and writes nothing."""
    if env.role != "builder":
        lines = [env.prompt.rstrip(), "", "## How you work here", "",
                 "- Read only: change no file and run nothing but read-only git (diff, log, show)."]
        return "\n".join(_with_conventions(lines, env)) + "\n"
    lines = [env.prompt.rstrip(), "", "## Checked after you finish (whatever you report)", "",
             "- Write only inside: " + (", ".join(env.write_scope) or "nothing") + ".",
             "- Never touch: " + (", ".join(env.protected) or "-") + ".",
             "- Each criterion's tests must fail before your change and pass after it"
             + (f": {', '.join(env.tests)}." if env.tests else "."),
             "- An independent verifier on another model family, and scenarios you never see, check the result.",
             "- Work only in this folder. Run no git command that commits, pushes or rewrites history."]
    if env.conventions:
        lines += ["", "## This project's own conventions", "", env.conventions]
    return "\n".join(lines) + "\n"


def harness_env() -> dict[str, str]:
    """The environment a harness runs in: this one, less where the factory keeps its home, lanes and keys."""
    return {k: v for k, v in os.environ.items() if k not in HIDDEN_ENV}


def staged_diff(workdir: Path, lane: Any = None) -> tuple[str, list[str]]:
    """What the run changed, staged and read through the kernel's guarded git: the diff and the paths. A working
    copy that holds a repository of its own is read no further (git would run that repository's filters); the
    commit that follows refuses it, as it refuses any cell's."""
    from kernel import git_guard
    from kernel.lanes import Lane

    held = lane or Lane(Path(workdir))
    git_guard.scrub(held.path, held.origin)
    if git_guard.nested(held.path, held.base):
        return "", []
    git = held.git
    git("add", "-A")
    listed = git("-c", "core.quotePath=false", "diff", "--cached", "--name-only", "--no-renames")
    names = [n for n in listed.splitlines() if n.strip()]
    return git("diff", "--cached", "--no-renames", "--no-color", "--no-ext-diff"), names


class Runner:
    """One harness. A subclass says how it is started and how its output is read."""

    name = "command"
    stdin = True

    def __init__(self, choice: dict[str, Any] | None = None):
        self.choice = dict(choice or {})

    # -- what a subclass says -----------------------------------------------------------------------------

    def argv(self, cmd: list[str], prompt_file: Path, workdir: Path, role: str) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def parse(self, stdout: str) -> dict[str, Any]:
        """The tool calls, the model and the answer a run's output shows."""
        return {"tool_calls": [], "output": stdout.strip()[-20000:], "model": self.choice.get("model")}

    def extra_env(self, role: str) -> dict[str, str]:
        return {}

    # -- the run ------------------------------------------------------------------------------------------

    def info(self, version: str | None) -> dict[str, Any]:
        sandbox = self.choice.get("sandbox") or "off"
        return {"name": self.name, "label": label_of(self.name), "version": version, **assurance_of(self.name),
                "sandbox": sandbox, "family": self.choice.get("family") or RUNNERS[self.name].get("family")}

    def refusal(self, found: dict[str, Any]) -> str | None:
        """Why this runner may not run now: not found, or not the version IT pinned."""
        if not found["found"]:
            return found["why"]
        pinned = self.choice.get("version")
        if pinned and found["version"] != pinned:
            return (f"{label_of(self.name)} is {found['version']} on this machine; IT pinned {pinned}. Nothing ran: "
                    "IT approves the new version on a card (rihmasto runners set) or the old one is put back")
        return None

    def run(self, env: Envelope, workdir: Path, *, timeout: int = 1800, lane: Any = None) -> RunResult:
        from kernel.runners.detect import command_of, detect

        found = detect(self.name, self.choice)
        record: dict[str, Any] = {"runner": self.info(found.get("version")), "role": env.role}
        why = self.refusal(found)
        if why:
            return RunResult(record | {"bucket": "apparatus_failure", "stop_reason": why, "code": None})
        workdir = Path(workdir)
        tasks = workdir / ".factory-tasks"
        tasks.mkdir(parents=True, exist_ok=True)
        text = compose_prompt(env)
        fd, name = tempfile.mkstemp(prefix=f"{env.role}-", suffix=".md", dir=tasks)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        try:
            record |= self._started(command_of(self.name, self.choice), Path(name), workdir, env.role, text, timeout)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name)
        diff, changed = staged_diff(workdir, lane) if env.role == "builder" else ("", [])
        record["changed"] = changed[:TOOL_CALLS_KEPT]
        return RunResult(record, diff, changed)

    def _started(self, cmd: list[str], prompt_file: Path, workdir: Path, role: str, text: str,
                 timeout: int) -> dict[str, Any]:
        from kernel.runners.sandbox import sandboxed

        started, clock = time.time(), time.monotonic()
        extra = self.extra_env(role)
        try:
            with sandboxed(self.argv(cmd, prompt_file, workdir, role), workdir, self.choice | {"runner": self.name},
                           env_names=tuple(extra)) as argv:
                proc = subprocess.run(argv, cwd=workdir, input=text if self.stdin else None, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=timeout,
                                      env=harness_env() | extra, stdin=None if self.stdin else subprocess.DEVNULL)
        except RunnerRefused as exc:
            return {"bucket": "apparatus_failure", "stop_reason": str(exc), "code": None, "started": started,
                    "seconds": 0.0, "refused": True}
        except subprocess.TimeoutExpired:
            return {"bucket": "apparatus_failure", "stop_reason": f"{label_of(self.name)} did not finish in {timeout}s",
                    "code": None, "started": started, "seconds": round(time.monotonic() - clock, 3)}
        except OSError as exc:
            return {"bucket": "apparatus_failure", "code": None, "started": started, "seconds": 0.0,
                    "stop_reason": f"{label_of(self.name)} could not be started: {exc}"}
        seen = self.parse(proc.stdout or "")
        calls = seen.get("tool_calls") or []
        tail = " ".join((proc.stderr or "").strip().splitlines()[-3:])[:500]
        out = {"code": proc.returncode, "exit": proc.returncode, "started": started,
               "seconds": round(time.monotonic() - clock, 3), "tool_steps": len(calls),
               "tool_calls": calls[:TOOL_CALLS_KEPT], "model": seen.get("model"), "output": seen.get("output") or "",
               "bucket": "result", "stop_reason": seen.get("stop_reason") or "answered"}
        if proc.returncode != 0:
            out |= {"bucket": "apparatus_failure", "stop_reason": f"{label_of(self.name)} exit {proc.returncode}: "
                                                                  f"{tail or seen.get('stop_reason') or 'no message'}"}
        return out
