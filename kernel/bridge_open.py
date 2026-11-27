"""What a hand-off brief hands on (FR-BRG1, kernel/agent_bridge.py): only feedback that is still open, and a task as
the scope on its own.

The developer acceptance test (2026-11-26): a brief told the agent to fix T-002's failed gate rounds and escalation and
"the security gate said not measured", although T-002 was retried and merged and the security gate later passed.
Here, by rule:

- a failed gate round is resolved once its task is merged or a later round of it passed;
- a Review item about a task's round or escalation is resolved once the task is merged, and a security gate's
  verdict once a later security gate passed;
- "hand off T-002" makes the contract task T-002 the brief's scope: its title, status and the requirements its
  criteria rest on.
"""

from __future__ import annotations

import re
from typing import Any

PASSED = ("passed", "warranted", "pass")


def merged_tasks(project: Any) -> set[str]:
    return {t for t, st in (project.read("tasks.json", {}) or {}).items()
            if isinstance(st, dict) and st.get("status") == "merged"}


def _last_pass(rounds: list[dict[str, Any]]) -> dict[Any, str]:
    out: dict[Any, str] = {}
    for e in rounds:
        if (e["payload"] or {}).get("verdict") in PASSED:
            out[e["payload"].get("task")] = str(e.get("at") or "")
    return out


def _gate_row(g: dict[str, Any], at: str) -> dict[str, Any]:
    return {"task": g.get("task"), "round": g.get("round"), "verdict": g.get("verdict"), "at": at,
            "failing": [k for k, v in (g.get("signals") or {}).items() if v not in ("passed", "pass")],
            "objections": [str(o)[:300] for o in g.get("objections") or []][:3]}


def failed_gates(project: Any, since: str | None = None) -> list[dict[str, Any]]:
    """Gate rounds that failed and are still open (``since``: only rounds after it), the newest five."""
    rounds = [r["event"] for r in project.ledger().of_kind("gate")]
    merged, passed = merged_tasks(project), _last_pass(rounds)
    out = []
    for e in rounds:
        g, at = e["payload"], str(e.get("at") or "")
        resolved = g.get("task") in merged or passed.get(g.get("task"), "") >= at > ""
        if not (since and at <= since) and not resolved and g.get("verdict") not in PASSED:
            out.append(_gate_row(g, at))
    return out[-5:]


def still_open(project: Any) -> Any:
    """Whether a Review item is still open feedback (see the module's docstring)."""
    merged = merged_tasks(project)
    passed = [str(r["event"].get("at") or "") for r in project.ledger().of_kind("security_gate")
              if (r["event"]["payload"] or {}).get("verdict") == "passed"]

    def still(it: dict[str, Any]) -> bool:
        task = re.match(r"(T-\d+)\b", str(it.get("title") or ""))
        if it.get("kind") in ("gate", "escalated", "escalation") and task and task.group(1) in merged:
            return False
        return not (it.get("kind") == "security_gate" and any(at > str(it.get("at") or "") for at in passed))

    return still


def task_scope(project: Any, tid: str) -> dict[str, Any]:
    """A contract task as the brief's scope: its title, status and the requirements its criteria rest on."""
    tasks = (project.read("contract.json") or {}).get("tasks") or []
    task = next((t for t in tasks if isinstance(t, dict) and t.get("id") == tid), None)
    if task is None:
        raise ValueError(f"No task {tid} in this project's contract: give one of its task ids, or a change's")
    status = _status(project, tid)
    crit = [str(c) for c in task.get("criteria") or []]
    title = str(task.get("title") or tid)
    return {"id": tid, "kind": "task", "title": title, "state": "decided", "verdict": None,
            "status": status, "deciders": [], "requirements": sorted({c.rsplit("-AC-", 1)[0] for c in crit}),
            "text": f"{tid}: {title} (status {status}); done when {', '.join(crit) or 'its criteria'} pass at the "
                    "gate."}


def _status(project: Any, tid: str) -> str:
    state = (project.read("tasks.json", {}) or {}).get(tid)
    return str((state if isinstance(state, dict) else {}).get("status") or "pending")


__all__ = ["failed_gates", "merged_tasks", "still_open", "task_scope"]
