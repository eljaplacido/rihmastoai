"""The developer briefing (FR-DEV1): what happened since the person last looked, and the next development step.

The owner (2026-11-25): "when I click in that [developer] role that I want to advance the project, I want insights
about the latest sessions, whether inside Rihmasto with Gnomon or in Claude Code ... and it would tell me, this
would be the next step in development". Read from the records, by rule (no model):

It shows on the project's Board, and when a developer presses Advance (FR-DEV2, cockpit/static/devadvance.js).

- **since**: the person's last look, Got it on the briefing (kernel/devsessions.py ``last_look``), else the last
  7 days;
- **sessions**: the latest sessions in any harness since then: the builder cell's runs (Gnomon or another runner),
  outside sessions the hooks recorded (Claude Code, Cursor), agents' posts and hand-offs in the channel, MCP writes;
- **changed**: gate rounds passed and failed, tasks merged, the tests of the newest gate round, and whether the
  requirements were compiled again;
- **next**: one development step with why, from the board (kernel/devboard.py) in a fixed order: a decision that
  blocks a task, a session still open, work in progress, a gate round that failed, the first task ready to start,
  then what is left when everything is merged;
- **blocking**: only the decisions that block that step (solo by default: nothing else nudges the person).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from kernel.devboard import _d, _l, board
from kernel.devsessions import last_look
from kernel.devtrace import since_of, trace

DEFAULT_WINDOW = "7d"
SESSION_KINDS = ("cell_ran", "dev_session_recorded", "mcp_write", "workspace_opened")
SHOWN = 10


def _since(project: Any, person: str | None) -> tuple[str | None, str]:
    looked = last_look(project, person)
    if looked:
        return looked, "your last look"
    return since_of(DEFAULT_WINDOW, project.factory.clock.now()), "the last 7 days"


def _is_session(item: dict[str, Any]) -> bool:
    who = item["who"]
    return item["kind"] in SESSION_KINDS or (item["source"] == "channel" and who.get("kind") == "agent")


def _sessions(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = [i for i in items if _is_session(i)]
    by: dict[str, int] = {}
    for i in rows:
        key = str(i["who"].get("harness") or i["who"].get("name") or "agent")
        by[key] = by.get(key, 0) + 1
    shown = [{"at": i["at"], "harness": i["who"].get("harness"), "what": i["what"], "task": i.get("task"),
              "who": i["who"].get("operator") or i["who"].get("name"), "ref": i["id"]} for i in rows[:SHOWN]]
    return shown, by


def _native_tests(project: Any, task: Any, rnd: Any) -> dict[str, Any]:
    """What the tests signal of one recorded round said natively (its test names and how each ended)."""
    rounds = _l(_d(_d(project.read("tasks.json", {})).get(task)).get("rounds"))
    for r in rounds:
        if _d(r).get("round") != rnd:
            continue
        for s in _l(_d(r.get("gate")).get("signals")):
            if _d(s).get("name") == "tests":
                return _d(s.get("native"))
    return {}


def _newest_tests(project: Any, gates: list[dict[str, Any]]) -> dict[str, Any]:
    """The tests of the newest gate round since the look, from the task's recorded round."""
    if not gates:
        return {"measured": False, "why": "no gate round ran since then",
                "how": "a builder cell's round or a submitted workspace runs the tests"}
    pl = gates[0]["record"]["payload"]
    native = _native_tests(project, pl.get("task"), pl.get("round"))
    results = _d(native.get("tests"))
    failed = sorted(n for n, v in results.items() if v != "ok")
    return {"measured": bool(results), "task": pl.get("task"), "round": pl.get("round"), "ran": native.get("ran"),
            "failed": failed[:10], "verdict": (pl.get("signals") or {}).get("tests"),
            **({} if results else {"why": "the round recorded no test names", "how": "open the task's rounds"})}


def _changed(project: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
    gates = [i for i in items if i["kind"] == "gate"]
    verdicts = [(i["record"]["payload"] or {}).get("verdict") for i in gates]
    return {"gates": {"passed": verdicts.count("passed"), "failed": len(verdicts) - verdicts.count("passed"),
                      "items": [{"at": i["at"], "what": i["what"], "task": i.get("task")} for i in gates[:6]]},
            "merged": [i.get("task") for i in items if i["kind"] == "merged"],
            "tests": _newest_tests(project, gates),
            "criteria_changed": any(i["kind"] in ("contract_compiled", "spec_written") for i in items),
            "decisions": len([i for i in items if i["kind"] == "decision"])}


# -- the next step ---------------------------------------------------------------------------------------------

def _step(title: str, why: str, *, task: str | None = None, route: str, label: str,
          control: str | None = None) -> dict[str, Any]:
    return {"title": title, "why": why, "task": task, "action": {"label": label, "route": route, "control": control}}


def _blocked_step(pid: str, c: dict[str, Any]) -> dict[str, Any]:
    w = c["waits_on"]
    return _step(f"Decide {w['card']} so {c['id']} can go on", f"{c['why']}: {w['what']}", task=c["id"],
                 route=f"#/p/{pid}/inbox/{w['card']}", label="Decide it", control="decide")


def _progress_step(pid: str, c: dict[str, Any]) -> dict[str, Any]:
    if c["kind"] == "session":
        return _step(f"Finish the {c['title']}", "it started and has not ended: its commits reach the gate when "
                     "you submit them", route=f"#/p/{pid}/trace", label="See the trace")
    return _step(f"Follow {c['id']}: {c['title']}", c["why"], task=c["id"] if c["kind"] == "task" else None,
                 route=c.get("open") or f"#/p/{pid}/tasks", label="Open it")


def _review_step(pid: str, c: dict[str, Any]) -> dict[str, Any]:
    last = (c.get("gates") or [{}])[-1]
    return _step(f"Fix what the gate found on {c['id']}", f"{c['why']} with {last.get('objections', 0)} objections; "
                 "change the code or the test so the next round passes", task=c["id"],
                 route=f"#/p/{pid}/tasks/{c['id']}", label="See the objections")


def _start_step(pid: str, c: dict[str, Any]) -> dict[str, Any]:
    crit = ", ".join(x["id"] for x in c.get("criteria") or []) or "its criteria"
    return _step(f"Start {c['id']}: {c['title']}", f"{c['why']}: no work on it yet; it is done when {crit} "
                 "pass at the gate", task=c["id"], route=f"#/p/{pid}/agents", label="Hand it to an agent",
                 control="handoff")


def _first(cards: list[dict[str, Any]], lane: str, kind: str | None = None) -> dict[str, Any] | None:
    return next((c for c in cards if c["lane"] == lane and (kind is None or c["kind"] == kind)), None)


def _when_none(pid: str, b: dict[str, Any]) -> dict[str, Any]:
    if b.get("no_tasks"):
        return _step("Get the requirements compiled into tasks", b["no_tasks"]["why"] + "; " + b["no_tasks"]["how"],
                     route=f"#/p/{pid}/overview", label="See what it waits for", control="next_step")
    change = _first(b["cards"], "planned", "change")
    if change:
        return _step(f"Decide the change {change['id']}, then build it", "every task is merged; the next work is "
                     "a change people asked for", route=f"#/p/{pid}/inbox/{change['id']}", label="Decide it",
                     control="decide")
    return _step("Every task is merged: release it or take the next change", "nothing is planned, running or in "
                 "review", route=f"#/p/{pid}/releases", label="Open releases")


def next_step(b: dict[str, Any]) -> dict[str, Any]:
    """The next development step on board ``b``, with why, by rule."""
    pid, cards = b["project"], b["cards"]
    tasks = [c for c in cards if c["kind"] == "task"]
    found = _first(tasks, "blocked")
    if found:
        return _blocked_step(pid, found)
    found = _first(cards, "in_progress", "session") or _first(tasks, "in_progress")
    if found:
        return _progress_step(pid, found)
    found = _first(tasks, "review")
    if found:
        return _review_step(pid, found)
    found = next((c for c in tasks if c["lane"] == "planned" and c["why"] == "ready to start"), None)
    return _start_step(pid, found) if found else _when_none(pid, b)


def blocking(b: dict[str, Any], step: dict[str, Any]) -> list[dict[str, Any]]:
    """Only the decisions that block the step: its task's card, its dependencies', and cards that block all work."""
    task = next((c for c in b["cards"] if c["id"] == step.get("task")), None)
    path = {step.get("task"), *((task or {}).get("depends_on") or [])}
    out = []
    for c in b["cards"]:
        w = c.get("waits_on")
        if w and c["lane"] == "blocked" and (c["id"] in path or c["kind"] != "task"):
            out.append({"card": w["card"], "kind": w["kind"], "what": w["what"], "who": w["who"],
                        "for": c["id"], "route": f"#/p/{b['project']}/inbox/{w['card']}"})
    return out


def briefing(project: Any, *, person: str | None = None) -> dict[str, Any]:
    """The developer briefing of ``project`` for ``person``."""
    since, basis = _since(project, person)
    items = trace(project, window=since, limit=2000)["items"]
    shown, by = _sessions(items)
    b = board(project)
    step = next_step(b)
    return {"project": project.pid, "title": b["title"], "person": person, "since": since, "since_basis": basis,
            "sessions": shown, "by_harness": by, "changed": _changed(project, items), "next": step,
            "blocking": blocking(b, step), "counts": b["counts"], "events": len(items),
            "at": project.factory.clock.stamp()}


def yesterday(now: dt.datetime) -> str:
    return (now - dt.timedelta(days=1)).isoformat().replace("+00:00", "Z")


__all__ = ["blocking", "briefing", "next_step", "yesterday"]
