"""Assumption weights (FR-NVL1): an assumption grows in importance as work touches it.

The owner (2026-11-25): "if any of the assumptions grow in importance ... I would have to reprioritize."

An open assumption (kernel/canon.py: a question the factory answered for itself, with a due date) is about the
requirements that rest on its question (spec.json ``sources``). Its weight is counted by rule from the records,
never by a model:

- each requirement resting on it (+1), each task building on one of them (+1, +1 more once accepted), each test
  of one of them in the contract (+1);
- a change card triaged onto one of them (+2), a release that shipped one of them (+2), its review overdue (+2);
- a contradicting gate or finding: a failed gate or a stuck task on one of them (+3).

From ``GREW`` up it is resurfaced as "grew in importance: reconsider", with the trigger that weighed most. It moves
into Blocking only when it blocks the next step: the next task to build rests on it, or a go-live waits on a release
of it while its review is overdue.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

GREW = 4
POINTS = {"requirement": 1, "task": 1, "accepted": 1, "test": 1, "change": 2, "release": 2, "overdue": 2,
          "contradicted": 3}


def _rid(criterion: str) -> str:
    return str(criterion).rsplit("-AC-", 1)[0]


def _dicts(items: Any) -> list[dict[str, Any]]:
    return [x for x in items or [] if isinstance(x, dict)]


def _tests(contract: dict[str, Any]) -> dict[str, str]:
    """Each criterion the contract checks with a test, and the requirement it belongs to."""
    out = {}
    for r in _dicts(contract.get("requirements")):
        for ac in _dicts(r.get("acceptance")):
            if (ac.get("check") or {}).get("kind", "test") == "test":
                out[str(ac.get("id"))] = _rid(str(ac.get("id")))
    return out


def _failed(e: dict[str, Any]) -> bool:
    return e.get("kind") == "escalated" or (e.get("kind") == "gate" and e["payload"].get("verdict") != "passed")


class _Work:
    """The project's records an assumption's weight is counted from, read once."""

    def __init__(self, project: Any) -> None:
        contract = project.read("contract.json") or {}
        self.reqs = _dicts((project.read("spec.json") or {}).get("requirements"))
        self.tasks = _dicts(contract.get("tasks"))
        self.status = {k: (v or {}).get("status") for k, v in (project.read("tasks.json") or {}).items()}
        self.tests = _tests(contract)
        events = [r["event"] for r in _dicts(project.ledger().records()) if "event" in r]
        self.changes = [e["payload"] for e in events if e.get("kind") == "change_triaged"]
        self.failed = [e["payload"] for e in events if _failed(e)]
        self.released = any(e.get("kind") == "release_done" for e in events)

    def task_reqs(self, task: dict[str, Any]) -> set[str]:
        return {_rid(c) for c in task.get("criteria") or []}


def _requirements(work: _Work, qid: str | None) -> list[str]:
    return [str(r["id"]) for r in work.reqs if qid and qid in (r.get("sources") or [])]


def _task_triggers(work: _Work, rids: set[str]) -> list[dict[str, Any]]:
    out = []
    for t in work.tasks:
        if not work.task_reqs(t) & rids:
            continue
        out.append({"kind": "task", "said": f"{t['id']} builds on it"})
        if work.status.get(t["id"]) == "merged":
            out.append({"kind": "accepted", "said": f"{t['id']} was accepted resting on it"})
    return out


def _record_triggers(work: _Work, rids: set[str]) -> list[dict[str, Any]]:
    out = [{"kind": "test", "said": f"{cid} tests it"} for cid, rid in sorted(work.tests.items()) if rid in rids]
    for c in work.changes:
        hit = sorted(set(c.get("requirements") or []) & rids)
        if hit:
            out.append({"kind": "change", "said": f"{c.get('card')} changes {', '.join(hit)}, which rests on it"})
    touched = {t["id"] for t in work.tasks if work.task_reqs(t) & rids}
    for f in work.failed:
        if f.get("task") in touched:
            out.append({"kind": "contradicted", "said": f"a gate failed on {f.get('task')}, which builds on it"})
    if work.released and any(work.status.get(t) == "merged" for t in touched):
        out.append({"kind": "release", "said": "a release shipped what rests on it"})
    return out


def _next_task(work: _Work) -> dict[str, Any] | None:
    done = {k for k, v in work.status.items() if v == "merged"}
    for t in work.tasks:
        if t["id"] not in done and set(t.get("depends_on") or []) <= done:
            return t
    return None


def weigh(project: Any, a: dict[str, Any], work: _Work, today: dt.date) -> dict[str, Any]:
    """One assumption's weight, its triggers (the heaviest first) and whether it blocks the next step."""
    rids = _requirements(work, a.get("question"))
    triggers: list[dict[str, Any]] = [{"kind": "requirement", "said": f"{r} rests on it"} for r in rids]
    triggers += _task_triggers(work, set(rids)) + _record_triggers(work, set(rids))
    if dt.date.fromisoformat(str(a.get("due") or today.isoformat())) < today:
        triggers.append({"kind": "overdue", "said": f"its review was due on {a.get('due')}"})
    for t in triggers:
        t["points"] = POINTS[t["kind"]]
    weight = sum(t["points"] for t in triggers)
    triggers.sort(key=lambda t: (-t["points"], t["kind"] == "requirement"))   # what work did first, then the basis
    nxt = _next_task(work)
    blocks = (f"{nxt['id']}, the next task to build, rests on it" if nxt and work.task_reqs(nxt) & set(rids)
              else None)
    grew = weight >= GREW
    return {"id": a["id"], "text": a.get("text"), "question": a.get("question"), "due": a.get("due"),
            "requirements": rids, "weight": weight, "triggers": triggers, "grew": grew,
            "trigger": triggers[0]["said"] if triggers else None, "blocking": bool(grew and blocks),
            "blocks": blocks if grew else None,
            "said": (f"{a['id']} grew in importance: reconsider it ({triggers[0]['said']})" if grew and triggers
                     else f"{a['id']} weighs {weight}: nothing makes it urgent yet")}


def weights(project: Any, today: dt.date | None = None) -> list[dict[str, Any]]:
    """Every open assumption of the project, heaviest first."""
    from kernel.canon import Canon

    today = today or project.factory.clock.today()
    work = _Work(project)
    rows = [weigh(project, a, work, today) for a in Canon(project).assumptions("open")]
    return sorted(rows, key=lambda r: (-r["weight"], r["id"]))
