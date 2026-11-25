"""A baseline from the project's own stated test command (FR-RPJ1; docs/brownfield.md, Stated commands).

Adoption runs a stated test command only when it maps to a runner the kernel knows (kernel/agent_context_use.py).
A project's instructions often state their own: ``py -3 tools/pipeline/check.py test``, a make target of their
own, a script. Such a command is offered, not run: a person may run it as the baseline after saying yes,
because it runs the project's own code on this machine. It runs as a detected suite does (kernel/adopt.py
``run_baseline``): in a temporary checkout of the baseline, offline, stdin closed, with a time limit, and
through IT's isolation runner when access is enforced. Only a command the instructions state, in plain words,
is ever run: never shell syntax, never a command a person typed. The baseline records which command
produced it and who said yes.
"""

from __future__ import annotations

import shlex
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

RUNNERS = ("developer", "it", "operations", "product_owner")
NOT_A_RUNNER = "is not a test runner the kernel runs"
RUNS_CODE = ("It runs the project's own code on this machine (through IT's isolation runner when access is "
             "enforced), offline, with a time limit, in a temporary checkout of the baseline.")


class StatedRefused(PermissionError):
    """A stated command that may not be run, or not by this person, or not without their yes."""


def offers(project: Any) -> list[dict[str, Any]]:
    """The stated test commands adoption did not run because the kernel does not know their runner."""
    stated = (project.read("inventory.json") or {}).get("stated_tests") or {}
    return [{"command": s["command"], "where": s["where"], "why": s["not_run"], "runs_code": RUNS_CODE}
            for s in stated.get("not_used") or [] if str(s.get("not_run", "")).endswith(NOT_A_RUNNER)]


def run(project: Any, command: str, *, person: str, persona: str, confirmed: bool, timeout: int | None = None,
        which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    """Run a stated command as the baseline, signed and confirmed; record it as the project's baseline."""
    from kernel import adopt
    from kernel.people import is_person

    if not is_person(person) or persona not in RUNNERS:
        raise StatedRefused(f"refused: a stated command is run by a named {', '.join(RUNNERS)}")
    if command not in [o["command"] for o in offers(project)]:
        raise StatedRefused("refused: only a test command the project's instructions state is run, as stated")
    if not confirmed:
        raise StatedRefused("refused: say yes first. " + RUNS_CODE)
    words = shlex.split(command)
    test = {"ecosystem": "stated", "runner": "stated", "tool": words[0], "command": words}
    adopted = project.read("adopted.json") or {}
    baseline = adopted.get("baseline") or ""
    with tempfile.TemporaryDirectory(prefix="gf-stated-", ignore_cleanup_errors=True) as tmp:
        adopt._net(Path(tmp), "clone", "-q", "-c", "core.autocrlf=false", str(project.path("repo.git")), "w",
                   timeout=600)
        work = Path(tmp) / "w"
        adopt._git(work, "checkout", "-q", baseline)
        got = adopt.run_baseline(work, test, timeout=timeout or adopt.SUITE_TIMEOUT, which=which)
    earlier = project.read("baseline.json") or {}
    record = {"verdict": got["verdict"], "meaning": adopt.CHARACTERISATION, "runs": [got], "reason": got["reason"],
              "revision": baseline, "at": project.factory.clock.stamp(), "command": command, "stated": True,
              "confirmed_by": {"person": person, "persona": persona},
              "earlier": {k: earlier.get(k) for k in ("verdict", "reason", "at")}}
    project.write("baseline.json", record)
    project.log("baseline_stated_run", {"command": command, "verdict": got["verdict"], "reason": got["reason"],
                                        "counts": got.get("counts"), "exit": got.get("exit"), "person": person,
                                        "persona": persona, "confirmed": RUNS_CODE})
    return record
