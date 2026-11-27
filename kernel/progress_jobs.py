"""Live progress for jobs that report in lines or counters (kernel/progress.py, FR-PRG1).

Not every long job runs in the cockpit's own process. An adoption runs the command line as a job and prints
its steps as lines (`adopt: fetching the code`, kernel/material_cli.py); a folder scan counts files as it goes
(kernel/material.py `Progress`). These adapters map what such a job already says onto a plan, so the cockpit
shows them with the same view as an assessment:

- `from_lines(...)` is the general adapter: a plan, the lines the job printed and which line starts which step.
  Each line starts its step and ends the one before; a step the job passed by is skipped ("not needed for this
  one"); when the job ended, its last step ends with it, done or failed. A gate round, a delivery or a Gnomon
  audit that prints its steps the same way gets its view by giving its plan and its lines.
- `adoption(...)` is that adapter with an adoption's plan and lines.
- `scan(...)` maps a folder scan's counters (files looked at, files opened, the folder it is in).

Lines carry no times, so these views have no estimate, and say so.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from kernel.progress import Reporter, group, step

ENDED = {"done": "done", "failed": "failed", "capped": "failed", "lost": "failed", "cancelled": "cancelled"}
NO_ESTIMATE = {"runs": 0, "left_s": None, "unknown_steps": 0,
               "said": "No estimate: this job reports its steps, not their times."}

ADOPTION_PLAN = [
    group("take", "Taking the code", [step("adopt.copy", "Copying the folder"),
                                      step("adopt.fetch", "Fetching the code")]),
    group("read", "Reading", [step("adopt.read", "The code and the documents")]),
    group("baseline", "The baseline", [step("adopt.tests", "Its own tests, once")]),
    group("record", "The record", [step("adopt.record", "Baseline, as-is spec, contract")]),
]
ADOPTION_LINES = {
    "copying the folder into a baseline repository": "adopt.copy",
    "fetching the code": "adopt.fetch",
    "reading the code and the documents": "adopt.read",
    "running its own tests once for a baseline": "adopt.tests",
    "recording the baseline, the as-is spec and the contract": "adopt.record",
}
SCAN_PLAN = [group("scan", "Scanning the folder", [step("scan.walk", "Looking through the folder"),
                                                   step("scan.read", "Opening what matters"),
                                                   step("scan.map", "The material map")])]


def _order(groups: list[dict[str, Any]]) -> list[str]:
    return [s["id"] for g in groups for s in g["steps"]]


def _walk(rep: Reporter, order: list[str], reached: list[tuple[str, str]]) -> str | None:
    """Start each reached step, ending the one before and skipping the steps passed by; the last one started."""
    current: str | None = None
    for sid, line in reached:
        if current is not None and current != sid:
            rep.done(current)
        here = order.index(sid)
        for passed in order[(order.index(current) + 1 if current else 0):here]:
            if rep.steps[passed]["state"] == "waiting":
                rep.skip(passed, "not needed for this one")
        if rep.steps[sid]["state"] == "waiting":
            rep.start(sid, line)
        current = sid
    return current


def _end(rep: Reporter, order: list[str], current: str | None, state: str, why: str) -> None:
    """How the job ended, when it did: its last step ends with it, and steps it never reached are skipped."""
    end = ENDED.get(state)
    if end is None:
        return
    if current is not None and end == "done":
        rep.done(current)
    for sid in order:
        if rep.steps[sid]["state"] == "waiting":
            rep.skip(sid, "not reached" if end != "done" else "not needed for this one")
    rep.finish(end, why or ("" if end == "done" else f"the job ended {state}"))


def from_lines(kind: str, title: str, groups: list[dict[str, Any]], lines: Iterable[str], starts: dict[str, str],
               *, state: str = "running", why: str = "", elapsed_s: float | None = None) -> dict[str, Any]:
    """A job's progress view (as kernel.progress.Reporter.since(0) gives it) from the step lines it printed;
    ``starts`` maps a line (after any "kind: " prefix) to the step it starts."""
    rep = Reporter(kind, title, clock=lambda: 0.0)
    rep.plan(groups)
    order = _order(rep.groups)
    reached = []
    for raw in lines:
        line = str(raw).strip().removeprefix(f"{kind}: ").strip()
        if line in starts and starts[line] in rep.steps:
            reached.append((starts[line], line))
    current = _walk(rep, order, reached)
    _end(rep, order, current, state, why)
    out = rep.since(0) | {"estimate": NO_ESTIMATE}
    if elapsed_s is not None:
        out["elapsed_s"] = round(float(elapsed_s), 1)
    return out


def adoption(lines: Iterable[str], state: str = "running", *, title: str = "", why: str = "",
             elapsed_s: float | None = None) -> dict[str, Any]:
    """An adoption's progress from the ``adopt:`` lines its job printed."""
    return from_lines("adopt", title, ADOPTION_PLAN, lines, ADOPTION_LINES, state=state, why=why,
                      elapsed_s=elapsed_s)


def _scan_said(seen: dict[str, Any], what: str) -> str:
    where = f", in {seen['folder']}" if seen.get("folder") else ""
    return f"{seen.get(what) or 0} file{'s' if (seen.get(what) or 0) != 1 else ''} " \
           f"{'looked at' if what == 'files' else 'opened'}{where}"


def scan(seen: dict[str, Any], state: str = "running", why: str = "") -> dict[str, Any]:
    """A folder scan's progress from its counters (kernel/material.py Progress.view) and how its job stands."""
    rep = Reporter("scan", "Scanning the folder", clock=lambda: 0.0)
    rep.plan(SCAN_PLAN)
    rep.start("scan.walk", _scan_said(seen, "files"))
    if seen.get("phase") == "reading" or state != "running":
        rep.done("scan.walk", counts={"files": int(seen.get("files") or 0)})
        rep.start("scan.read", _scan_said(seen, "read"))
    if state == "done":
        rep.done("scan.read", counts={"opened": int(seen.get("read") or 0)})
        rep.start("scan.map")
        rep.done("scan.map")
    if state != "running":
        rep.finish(ENDED.get(state, "failed"), why)
    return rep.since(0) | {"estimate": NO_ESTIMATE, "elapsed_s": seen.get("elapsed_s") or 0}


__all__ = ["ADOPTION_LINES", "ADOPTION_PLAN", "NO_ESTIMATE", "SCAN_PLAN", "adoption", "from_lines", "scan"]
