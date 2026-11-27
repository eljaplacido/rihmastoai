"""The whole log of a run (FR-LND1): a background job's output, or the steps of the cell building a task, read from
where they are kept, followed as they grow, and what a finished run changed.

The owner (2026-11-26): "Last action is also small terminal view". The cockpit's small boxes (a job's last lines, the
running cell's last action) open the whole log from here:

- ``job_text(path, start)``: a job's log file from byte ``start`` (the first read takes the last ``FIRST`` bytes,
  and says what it left out), with ``next``, the offset to follow from;
- ``cell_steps(project, start)``: every tool step of the cell that holds the project's lane now (or held it last),
  from Gnomon's own audit trail, as numbered lines, from step ``start``;
- ``changed(project, since, until)``: what the records gained while the run ran: tasks, cards, gates, merges and
  releases, each with the place that shows it.

Reading changes nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FIRST = 256 * 1024        # the first read of a log: its last 256 KiB
MORE = 512 * 1024         # each later read: at most this much more
MAX_STEPS = 2000
SHOWN = {"cell_ran": ("a builder cell ran", "tasks"), "gate": ("the gate judged", "tasks"),
         "merged": ("merged", "tasks"), "escalated": ("sent to a person", "inbox"),
         "card_opened": ("a card opened", "inbox"), "decided": ("a decision", "inbox"),
         "change_submitted": ("a change filed", "changes"), "question_added": ("a question asked", "questions"),
         "spec_written": ("the spec written", "spec"), "contract_compiled": ("the contract compiled", "tasks"),
         "intake_done": ("the intake finished", "questions"), "release_done": ("a release done", "releases"),
         "delivered": ("delivered", "releases"), "assessment_done": ("an assessment recorded", "assessment"),
         "alignment_scanned": ("its repository read for alignment", "align"),
         "upstream_change_opened": ("an upstream change opened", "inbox"),
         "inventory_taken": ("its files inventoried", "overview"), "characterised": ("its own tests run", "overview"),
         "adoption_tasks": ("its as-is tasks recorded", "tasks"), "check_ran": ("a check ran", "checks"),
         "task_started": ("a task started", "tasks"), "task_marked_done": ("a task marked done", "tasks")}


def job_text(path: Path, start: int = -1) -> dict[str, Any]:
    """The log from byte ``start`` (-1: its last ``FIRST`` bytes), with the offset to read on from."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return {"text": "", "next": 0, "size": 0, "skipped": 0, "exists": False,
                "why": "the log file is not there: the job wrote nothing yet, or its log was cleaned up"}
    begin = max(0, size - FIRST) if start < 0 else min(max(0, start), size)
    with open(path, "rb") as fh:
        fh.seek(begin)
        data = fh.read(MORE if start >= 0 else FIRST)
    if begin and start < 0:                 # start on a whole line
        cut = data.find(b"\n")
        data, begin = (data[cut + 1:], begin + cut + 1) if cut >= 0 else (data, begin)
    end = begin + len(data)
    if end < size and b"\n" in data:        # stop on a whole line, the rest comes next
        last = data.rfind(b"\n") + 1
        data, end = data[:last], begin + last
    return {"text": data.decode("utf-8", errors="replace"), "next": end, "size": size,
            "skipped": begin if start < 0 else 0, "exists": True}


def _trail(project: Any) -> tuple[Path | None, dict[str, Any]]:
    """The audit trail of the cell that holds the project's lane now, else the newest one it left."""
    from kernel import status as kstatus
    from kernel.lanes import lanes_root

    try:
        lv = kstatus.live(project)
    except (OSError, ValueError):
        lv = {"running": False}
    root = Path(lanes_root())
    if lv.get("running") and lv.get("lane"):
        audit = root / lv["lane"] / ".gnomon-audit"
        trails = sorted(audit.glob("task-*.jsonl"), key=lambda p: p.stat().st_mtime) if audit.is_dir() else []
        return (trails[-1] if trails else None), lv
    return _left(project, root, lv)


SESSION = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,120}\Z")


def _left(project: Any, root: Path, lv: dict[str, Any]) -> tuple[Path | None, dict[str, Any]]:
    """The newest trail the project's cell left (FR-LND2): the run its last ``gnomon_run`` names, found in whichever
    lane kept it (a lane keeps its trails across leases)."""
    runs = [r["event"] for r in project.ledger().records()
            if isinstance(r, dict) and isinstance(r.get("event"), dict) and r["event"].get("kind") == "gnomon_run"]
    after = None                                    # the next run's start: this run's changes end there
    for ev in reversed(runs):
        pl = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        session = str(pl.get("run") or "")
        found = (next(iter(sorted(root.glob(f"*/.gnomon-audit/{session}.jsonl"))), None)
                 if SESSION.match(session) and root.is_dir() else None)
        if found is not None:
            return found, lv | {"left": {"task": pl.get("task"), "round": pl.get("round"), "at": ev.get("at"),
                                         "until": after, "lane": found.parent.parent.name}}
        after = ev.get("at")
    return None, lv


def _finished(project: Any, path: Path, left: dict[str, Any], start: int) -> dict[str, Any]:
    """The whole log of the cell that ran last, and what its round changed for its task."""
    out: dict[str, Any] = {"running": False, "finished": True, "task": left.get("task"), "round": left.get("round"),
                           "lane": left.get("lane"), "role": None, "model": None, "lines": [], "steps": 0,
                           "ended": False, "at": left.get("at")}
    _read(path, out, start)
    task = left.get("task")
    changed_rows = [c for c in changed(project, left.get("at"), left.get("until"))
                    if c.get("task") == task][:50] if task else []
    return out | {"next": start + len(out["lines"]), "changed": changed_rows,
                  "why": f"the cell that built {task} last has stopped: this is its whole log"}


def _read(path: Path, out: dict[str, Any], start: int) -> None:
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict):
            _fold(out, rec, start)


def cell_steps(project: Any, start: int = 0) -> dict[str, Any]:
    """Every tool step of the running cell, numbered, from step ``start``; once it stopped, of the one it left."""
    path, lv = _trail(project)
    if not lv.get("running"):
        if path is not None and lv.get("left"):
            return _finished(project, path, lv["left"], start)
        return {"running": False, "finished": False, "lines": [], "next": 0, "task": None,
                "why": "no cell is building a task of this project now, and no cell run under Gnomon left a log "
                       "here yet: each step shows here while one does, and stays once it stops"}
    out: dict[str, Any] = {"running": True, "task": lv.get("task"), "lane": lv.get("lane"), "role": None,
                           "model": None, "lines": [], "steps": 0, "ended": False}
    if path is None:
        return out | {"next": start, "why": "the cell has not written its audit trail yet"}
    _read(path, out, start)
    return out | {"next": start + len(out["lines"])}


def _fold(out: dict[str, Any], rec: dict[str, Any], start: int) -> None:
    """One record of the trail into the log: who and which model, each tool step from ``start``, the end."""
    kind = rec.get("kind")
    if kind == "session_start":
        out["role"] = rec.get("role")
    elif kind == "model_call":
        out["model"] = rec.get("model") or out["model"]
    elif kind == "session_end":
        out["ended"] = True
    elif kind == "tool_call":
        out["steps"] += 1
        if out["steps"] > start and len(out["lines"]) < MAX_STEPS:
            target = str(rec.get("target") or "")[:300]
            out["lines"].append(f"{out['steps']:>4}  {str(rec.get('ts') or '')[11:19]}  {rec.get('tool') or '?'}"
                                + (f"  {target}" if target else ""))


def _event(rec: Any, since: str, until: str | None) -> dict[str, Any] | None:
    """A ledger record's event when it falls between ``since`` and ``until`` and is one the log shows."""
    ev = rec.get("event") if isinstance(rec, dict) else None
    if not isinstance(ev, dict) or str(ev.get("kind")) not in SHOWN:
        return None
    at = str(ev.get("at") or "")
    return ev if at >= since and (not until or at <= until) else None


def _said(pid: str, ev: dict[str, Any]) -> dict[str, Any]:
    kind = str(ev.get("kind"))
    pl = ev["payload"] if isinstance(ev.get("payload"), dict) else {}
    said, view = SHOWN[kind]
    ref = pl.get("task") or pl.get("card") or pl.get("id")
    ref = ref if isinstance(ref, str) else None
    if kind == "gate" and pl.get("verdict"):
        said += f" {pl.get('task')}: {pl['verdict']}"
    elif ref:
        said += f": {ref}"
    focus = f"/{ref}" if ref and view in ("tasks", "inbox") else ""
    task = pl.get("task") if isinstance(pl.get("task"), str) else None
    return {"kind": kind, "at": ev.get("at"), "said": said, "route": f"#/p/{pid}/{view}{focus}", "task": task}


def changed(project: Any, since: str | None, until: str | None = None) -> list[dict[str, Any]]:
    """What the project's records gained from ``since`` to ``until``: each with where it shows."""
    if not since:
        return []
    events = (_event(rec, since, until) for rec in project.ledger().records())
    return [_said(project.pid, ev) for ev in events if ev is not None][-50:]


__all__ = ["FIRST", "cell_steps", "changed", "job_text"]
