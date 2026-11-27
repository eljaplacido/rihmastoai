"""What the Agent sessions view works out from the hub's session rows, by rule (FR-OBS1).

The hub gives a project's figures whole (``/insight``, ``/intelligence``); the view also says them per session, from
each session's step strip (its most recent 200 steps; ``step_count`` is the whole). Each rule is the hub's own, as
its metrics contract states it, applied to the steps the hub returned:

- **a failure** is a ``tool.failed`` step. With no file it is *undetermined*; a later ``tool.completed`` of the same
  tool on the same file *recovered* it; otherwise it is *unrecovered* (the hub says "blocked");
- **read the contract first**: a read of a contract file (the hub's governance list of contract documents, and
  AGENTS.md, CLAUDE.md, a Cursor rules file or a contract.json) before the session's first edit; a session with no
  edit says nothing; a session whose strip was cut before its first edit says "not measured";
- **a trajectory** is the strip as step kinds: read, edit, run, fail, ask (a prompt), other.

Nothing here reaches the hub; ``view`` hands the rows in.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

WRITE_TOOLS = {"edit", "write", "multiedit", "notebookedit", "patch", "apply_patch", "str_replace_editor"}
READ_TOOLS = {"read", "grep", "glob", "ls", "list", "search", "codebase_search", "read_file", "view"}
RUN_TOOLS = {"bash", "shell", "run_terminal_cmd", "terminal", "exec"}
CONTRACT_NAMES = {"agents.md", "claude.md", ".cursorrules", "contract.json"}
MAX_DAYS = 30


def _base(path: Any) -> str:
    return str(path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()


def kind_of(step: dict[str, Any]) -> str:
    """read, edit, run, fail, ask or other."""
    event, tool = str(step.get("event_type") or ""), str(step.get("tool_name") or "").lower()
    if event == "tool.failed":
        return "fail"
    if event == "prompt.submitted":
        return "ask"
    if tool in WRITE_TOOLS or event == "file.changed":
        return "edit"
    if tool in READ_TOOLS:
        return "read"
    return "run" if tool in RUN_TOOLS else "other"


def _complete(session: dict[str, Any]) -> bool:
    steps = session.get("steps") or []
    return int(session.get("step_count") or len(steps)) <= len(steps)


def failures(session: dict[str, Any]) -> dict[str, Any]:
    """The session's failures: recovered, unrecovered and undetermined, with the unrecovered ones' tool and file."""
    steps = [s for s in session.get("steps") or [] if isinstance(s, dict)]
    out: dict[str, Any] = {"failures": 0, "recovered": 0, "unrecovered": 0, "undetermined": 0, "stuck": [],
                           "complete": _complete(session)}
    for i, s in enumerate(steps):
        if s.get("event_type") != "tool.failed":
            continue
        out["failures"] += 1
        if not s.get("file_path"):
            out["undetermined"] += 1
            continue
        healed = any(t.get("event_type") == "tool.completed" and t.get("tool_name") == s.get("tool_name")
                     and t.get("file_path") == s.get("file_path") for t in steps[i + 1:])
        out["recovered" if healed else "unrecovered"] += 1
        if not healed:
            out["stuck"].append({"tool": s.get("tool_name"), "file": s.get("file_path"), "at": s.get("occurred_at")})
    return out


def contract_first(session: dict[str, Any], contract_files: set[str]) -> bool | None:
    """Whether the session read a contract file before its first edit; None when it made no edit or when its
    strip was cut before the first edit (the hub returned only its most recent steps)."""
    names = {_base(f) for f in contract_files} | CONTRACT_NAMES
    steps = [s for s in session.get("steps") or [] if isinstance(s, dict)]
    first_edit = next((i for i, s in enumerate(steps) if kind_of(s) == "edit"), None)
    if first_edit is None or not _complete(session):
        return None
    return any(kind_of(s) == "read" and _base(s.get("file_path")) in names for s in steps[:first_edit])


def strip(session: dict[str, Any], limit: int = 60) -> list[str]:
    """The session's trajectory as step kinds, its most recent ``limit`` steps (a tool's start and its end are one
    step: the start is left out)."""
    steps = [s for s in session.get("steps") or [] if isinstance(s, dict) and s.get("event_type") != "tool.started"]
    return [kind_of(s) for s in steps[-limit:]]


def day(stamp: Any) -> str | None:
    """The UTC day of a hub timestamp (``2026-07-27T11:21:22.001Z``, or with an offset)."""
    try:
        t = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=dt.UTC)).astimezone(dt.UTC).date().isoformat()


def by_harness(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Sessions per day and harness over the most recent days that had any (at most 30), and per harness in all."""
    counts: dict[str, Counter[str]] = {}
    for s in sessions:
        d = day(s.get("started_at"))
        if d:
            counts.setdefault(d, Counter())[str(s.get("harness_name") or "unknown")] += 1
    days = sorted(counts)[-MAX_DAYS:]
    harnesses = sorted({h for c in counts.values() for h in c})
    total = Counter(str(s.get("harness_name") or "unknown") for s in sessions)
    return {"harnesses": harnesses, "rows": [{"day": d, "values": dict(counts[d])} for d in days],
            "totals": dict(total), "days_with_sessions": len(counts), "shown_days": len(days)}


def session_row(s: dict[str, Any], contract_files: set[str]) -> dict[str, Any]:
    """One session as the view lists it."""
    f = failures(s)
    return {"session_id": s.get("session_id"), "harness": s.get("harness_name"), "started_at": s.get("started_at"),
            "ended_at": s.get("ended_at"), "duration_ms": s.get("duration_ms"), "status": s.get("status"),
            "step_count": s.get("step_count"), "steps_shown": len(s.get("steps") or []),
            "files": len(s.get("files") or []), "touched": [str(x) for x in (s.get("files") or [])[:200]],
            "had_failure": bool(s.get("had_failure")), "failures": f,
            "contract_first": contract_first(s, contract_files), "strip": strip(s)}
