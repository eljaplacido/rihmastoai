"""The FR-LND1 write routes for the cockpit's completeness tables (tests/test_brief_ln.py, tests/test_access.py):
Start here hidden for a person, and a task started, marked done with its evidence and handed to a coding agent, each
signed and recorded."""

from __future__ import annotations

from typing import Any


def open_task(project: Any) -> str:
    """A task of the project neither the gate merged nor a cell builds now, read when the write runs."""
    states = project.read("tasks.json", {}) or {}
    tasks = (project.read("contract.json", None) or {}).get("tasks") or []
    return next(t["id"] for t in tasks if (states.get(t["id"]) or {}).get("status", "pending")
                not in ("merged", "building"))


def write_routes(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    built = w["built"]
    b = built.pid
    dev = {"persona": "developer"}
    return [
        ("post_start_here", "POST", f"/api/projects/{b}/start-here",
         lambda who, got: {"hide": True, "person": who, **dev}),
        ("post_task_start", "POST", lambda got: f"/api/projects/{b}/tasks/{open_task(built)}/start",
         lambda who, got: {"note": "picking it up", "person": who, **dev}),
        ("post_task_done", "POST", lambda got: f"/api/projects/{b}/tasks/{open_task(built)}/done",
         lambda who, got: {"evidence": "the suite passed at abc1234", "person": who, **dev}),
        ("post_task_handoff", "POST", lambda got: f"/api/projects/{b}/tasks/{open_task(built)}/handoff",
         lambda who, got: {"to": "claude-code", "person": who, **dev}),
    ]
