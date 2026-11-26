"""A project's development board (FR-DEV1): the work as lanes, read from the records, never kept.

The owner (2026-11-25): "how to build up the Kanban workflows, especially from development point of view per
project". Each contract task is a card, placed in a lane by what the records say about it:

- **planned**: a task no cell, workspace or agent has started (with the tasks it still waits for), and a change
  a person asked for that waits for its decision before work starts;
- **in_progress**: a cell running it now, a person's open workspace, an agent it was handed to, a session in an
  outside tool (Claude Code, Cursor) still open;
- **review**: gate rounds ran and it is not merged yet, or an escalation was decided and it goes round again;
- **blocked**: what waits on a person: an open escalation or a blocking card (who may decide it, and which card);
- **done**: merged into main.

Every card carries what it rests on: its requirements, criteria (given, when, then) and the tests that name them,
the commits that carry its id or a head its rounds judged (read from the project's ``repo.git``), its gate rounds
and the agents and harnesses that worked on it (the builder cell's runner and model, a workspace's person and
agent, a hand-off, an outside session). Reading changes nothing.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from kernel import status as kstatus
from kernel.canon import Canon, deciders_of
from kernel.graph_records import object_of

LANES = ("planned", "in_progress", "review", "blocked", "done")
TASK = re.compile(r"\bT-\d{1,6}\b")
AC = re.compile(r"\A(?P<req>.+)-AC-\d+\Z")
MAX_COMMITS = 300
SHOWN_COMMITS = 12
BLOCKING_KINDS = ("escalation", "holdout_ruling", "trust", "deploy_gate")
GIT_TIMEOUT = 15


_d = object_of                # an object, or an empty one (kernel/graph_records.py)


def _l(value: Any) -> list[Any]:
    """A list's items (a copy), or none when the value is not a list."""
    return [*value] if isinstance(value, list) else []


def _git(repo: Any, *args: str) -> str | None:
    """A read of the bare repository, or None when it cannot be read."""
    try:
        done = subprocess.run(["git", "--git-dir", str(repo), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def commits(project: Any) -> dict[str, Any]:
    """The repository's commits, newest first, each marked whether main holds it; not measured without one."""
    repo = project.path("repo.git")
    if not repo.exists():
        return {"measured": False, "why": "this project has no repository yet",
                "how": "it gets one when its requirements are compiled, or when a repository is adopted",
                "items": []}
    raw = _git(repo, "log", "--all", f"-n{MAX_COMMITS}", "--format=%H%x1f%an%x1f%aI%x1f%s")
    if raw is None:
        return {"measured": False, "why": "the repository could not be read with git",
                "how": "check that git is installed and on the path of the cockpit's machine", "items": []}
    main = set((_git(repo, "rev-list", f"-n{MAX_COMMITS}", "main") or "").split())
    items = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            items.append({"sha": parts[0], "short": parts[0][:8], "author": parts[1], "at": parts[2],
                          "subject": parts[3][:200], "on_main": parts[0] in main,
                          "tasks": sorted(set(TASK.findall(parts[3])))})
    return {"measured": True, "items": items}


# -- the records, indexed by task --------------------------------------------------------------------------

def _empty_index() -> dict[str, Any]:
    return {"gates": [], "cells": [], "merged": None, "escalated": None, "agents": {}, "heads": set(), "last": None}


def _agent(ix: dict[str, Any], name: str, harness: str | None, via: str, role: str | None = None) -> None:
    key = f"{name}|{harness}|{via}"
    ix["agents"].setdefault(key, {"name": name, "harness": harness, "via": via, "role": role})


def _touch(ix: dict[str, Any], at: Any) -> None:
    if at and (ix["last"] is None or str(at) > ix["last"]):
        ix["last"] = str(at)


def _on_cell(ix: dict[str, Any], pl: dict[str, Any], at: Any) -> None:
    runner = _d(pl.get("runner"))
    ix["cells"].append({"round": pl.get("round"), "model": pl.get("final_model") or pl.get("model"), "at": at,
                        "runner": runner.get("label") or runner.get("name"), "steps": pl.get("tool_steps")})
    _agent(ix, runner.get("label") or "builder cell", runner.get("name") or "gnomon", "cell", pl.get("model"))
    if pl.get("head"):
        ix["heads"].add(pl["head"])


def _on_gate(ix: dict[str, Any], pl: dict[str, Any], at: Any) -> None:
    ix["gates"].append({"round": pl.get("round"), "verdict": pl.get("verdict"), "at": at,
                        "signals": _d(pl.get("signals")), "objections": len(_l(pl.get("objections"))),
                        "head": pl.get("head"), "author": pl.get("author")})
    if pl.get("head"):
        ix["heads"].add(pl["head"])
    author = _d(pl.get("author"))
    if author.get("name"):            # a person's workspace met the same gate (kernel/workspace.py)
        _agent(ix, str(author["name"]), "workspace", "workspace", author.get("persona"))


def _on_record(ix: dict[str, Any], kind: str, pl: dict[str, Any], at: Any) -> None:
    if kind == "cell_ran":
        _on_cell(ix, pl, at)
    elif kind == "gate":
        _on_gate(ix, pl, at)
    elif kind == "merged":
        ix["merged"] = {"at": at, "revision": pl.get("revision"), "permitted_by": pl.get("permitted_by")}
        if pl.get("revision"):
            ix["heads"].add(pl["revision"])
    elif kind == "escalated":
        ix["escalated"] = {"at": at, "card": pl.get("card")}
    elif kind == "dev_session_recorded":
        _agent(ix, str(pl.get("person") or "someone"), pl.get("harness"), "session")
    _touch(ix, at)


def index(project: Any) -> dict[str, dict[str, Any]]:
    """What the ledger says about each task: its cells, gate rounds, merge, escalation and agents."""
    out: dict[str, dict[str, Any]] = {}
    for rec in project.ledger().records():
        event = _d(_d(rec).get("event"))
        pl = _d(event.get("payload"))
        for tid in _l(pl.get("tasks")) or [pl.get("task")]:
            if isinstance(tid, str) and tid:
                _on_record(out.setdefault(tid, _empty_index()), str(event.get("kind")), pl, event.get("at"))
    return out


def _channel_agents(project: Any, ix: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Agents named in the channel: on the tasks they refer to; the hand-offs that name no task, returned."""
    from kernel import agent_channel as ch

    loose = []
    for m in ch.read(project)["messages"]:
        author = _d(m.get("author"))
        if author.get("kind") != "agent" and m.get("kind") != "handoff":
            continue
        tasks = _l(_d(m.get("refs")).get("tasks"))
        for tid in tasks:
            slot = ix.setdefault(tid, _empty_index())
            _agent(slot, str(author.get("name")), author.get("harness"),
                   "handoff" if m["kind"] == "handoff" else "channel")
            _touch(slot, m.get("at"))
        if m.get("kind") == "handoff" and not tasks:
            loose.append(m)
    return loose[-5:]


# -- the cards ---------------------------------------------------------------------------------------------

def _criteria(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for r in _l(contract.get("requirements")):
        for c in _l(_d(r).get("acceptance")):
            out[c.get("id")] = {"id": c.get("id"), "requirement": r.get("id"), "given": c.get("given"),
                                "when": c.get("when"), "then": c.get("then")}
    return out


def _tests(state: dict[str, Any], criteria: list[str]) -> list[dict[str, Any]]:
    """The tests the last gate round ran that name the task's criteria, with how each ended."""
    rounds = _l(state.get("rounds"))
    gate = _d(_d(rounds[-1]).get("gate")) if rounds else {}
    ran: dict[str, Any] = {}
    for sig in _l(gate.get("signals")):
        if _d(sig).get("name") == "tests":
            ran = _d(_d(sig.get("native")).get("tests"))
    tokens = [c.replace("-", "_") for c in criteria]
    return [{"name": name, "result": result} for name, result in sorted(ran.items())
            if any(t in name for t in tokens)]


def _open_cards(project: Any) -> list[dict[str, Any]]:
    try:
        return Canon(project).cards(state="open")
    except (OSError, ValueError):
        return []


def _waits(card: dict[str, Any]) -> dict[str, Any]:
    return {"card": card["id"], "kind": card["kind"], "who": list(deciders_of(card)),
            "what": str(card.get("title") or card["kind"])[:200]}


def _held(tid: str, state: dict[str, Any], ctx: dict[str, Any]) -> tuple[str, str] | None:
    """A task held by a person (a card, a stop) or being worked on now (a cell, a workspace)."""
    card = ctx["task_cards"].get(tid)
    if card is not None:
        return "blocked", f"waits on a person: {card['kind'].replace('_', ' ')} {card['id']}"
    if state.get("stopped_by"):
        return "blocked", f"stopped by {state['stopped_by']}"
    if ctx["running"] == tid:
        return "in_progress", "a builder cell runs it now"
    if tid in ctx["workspaces"]:
        return "in_progress", "open in " + str(ctx["workspaces"][tid]) + "'s workspace"
    return None


def _worked(ix: dict[str, Any], status: str) -> tuple[str, str] | None:
    """A task with gate rounds, an escalation decided, or an agent it was handed to."""
    if ix["gates"]:
        last = ix["gates"][-1]
        return "review", f"gate round {last.get('round')}: {last.get('verdict')}"
    if status == "escalated":
        return "review", "escalated, decided, waiting for its next round"
    if any(a["via"] in ("handoff", "session", "channel") for a in ix["agents"].values()):
        return "in_progress", "handed to an agent"
    return None


def _lane(task: dict[str, Any], state: dict[str, Any], ix: dict[str, Any], ctx: dict[str, Any]) -> tuple[str, str]:
    """The task's lane and why, from its records."""
    status = str(state.get("status", "pending"))
    if status == "merged":
        return "done", "merged into main"
    found = _held(task["id"], state, ctx) or _worked(ix, status)
    if found:
        return found
    waiting = [d for d in _l(task.get("depends_on")) if ctx["status"].get(d) != "merged"]
    return "planned", ("waits for " + ", ".join(waiting)) if waiting else "ready to start"


def _crit(task: dict[str, Any], ctx: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in _l(task.get("criteria")):
        m = AC.match(c)
        out.append(ctx["criteria"].get(c) or {"id": c, "requirement": m["req"] if m else None})
    return out


def _task_card(task: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    tid = task["id"]
    state = _d(ctx["states"].get(tid))
    ix = ctx["index"].get(tid) or _empty_index()
    lane, why = _lane(task, state, ix, ctx)
    crit = _crit(task, ctx)
    mine = [c for c in ctx["commits"] if tid in c["tasks"] or c["sha"] in ix["heads"]]
    card = ctx["task_cards"].get(tid)
    return {"id": tid, "kind": "task", "title": task.get("title") or tid, "lane": lane, "why": why,
            "status": state.get("status", "pending"), "criteria": crit,
            "requirements": sorted({c["requirement"] for c in crit if c.get("requirement")}),
            "tests": _tests(state, _l(task.get("criteria"))), "commits": mine[:SHOWN_COMMITS],
            "commits_total": len(mine), "gates": ix["gates"][-6:], "rounds": len(ix["gates"]),
            "cells": ix["cells"][-3:], "merged": ix["merged"], "agents": list(ix["agents"].values()),
            "depends_on": _l(task.get("depends_on")), "waits_on": _waits(card) if card is not None else None,
            "last": ix["last"], "open": f"#/p/{ctx['pid']}/tasks/{tid}"}


def _decision_card(c: dict[str, Any], pid: str) -> dict[str, Any]:
    lane = "planned" if c["kind"] == "change" and not c.get("blocking") else "blocked"
    why = "waits for a decision before work starts" if lane == "planned" else "waits for a decision: it blocks the work"
    return {"id": c["id"], "kind": c["kind"], "title": str(c.get("title") or c["kind"])[:300], "lane": lane,
            "why": why, "waits_on": _waits(c), "last": c.get("created"), "agents": [],
            "requirements": sorted(_l(_d(c.get("refs")).get("requirements"))), "open": f"#/p/{pid}/inbox/{c['id']}"}


def _decision_cards(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Changes waiting a decision, and cards that block the work, that are not a task's own."""
    keep = [c for c in ctx["open"] if _d(c.get("refs")).get("task") not in ctx["task_ids"]
            and (c["kind"] == "change" or c.get("blocking") or c["kind"] in BLOCKING_KINDS)]
    return [_decision_card(c, ctx["pid"]) for c in keep]


def _workspace_cards(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": w["branch"], "kind": "workspace", "title": f"{w.get('person')}'s workspace ({w.get('agent')})",
             "lane": "in_progress", "why": "a workspace is open on " + w["branch"],
             "agents": [{"name": w.get("person"), "harness": w.get("agent"), "via": "workspace"}],
             "last": w.get("opened"), "requirements": [], "open": f"#/p/{ctx['pid']}/console"}
            for w in ctx["registry"] if not w.get("submissions") and w.get("branch")]


def _handoff_cards(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in ctx["loose"]:
        author = _d(m.get("author"))
        out.append({"id": m["id"], "kind": "handoff", "title": "Handed to " + str(author.get("name") or "an agent"),
                    "lane": "in_progress", "why": "a hand-off that names no task", "last": m.get("at"),
                    "agents": [{"name": author.get("name"), "harness": author.get("harness"), "via": "handoff"}],
                    "requirements": [], "open": f"#/p/{ctx['pid']}/agents/{m['id']}"})
    return out


def _sessions_open(project: Any) -> list[dict[str, Any]]:
    from kernel.devsessions import open_sessions

    return [{"id": s["id"], "kind": "session", "title": f"{s.get('harness_label')} session by {s.get('person')}",
             "lane": "in_progress", "why": "an outside session started and has not ended",
             "agents": [{"name": s.get("person"), "harness": s.get("harness"), "via": "session"}],
             "last": s.get("at"), "requirements": [], "branch": s.get("branch"),
             "open": f"#/p/{project.pid}/trace"} for s in open_sessions(project)]


# -- the board ---------------------------------------------------------------------------------------------

def _running(project: Any) -> str | None:
    """The task a builder cell runs now, or None."""
    try:
        lv = kstatus.live(project)
    except (OSError, ValueError):
        return None
    return lv.get("task") if lv.get("running") and not lv.get("ended") else None


def _submitted(registry: list[dict[str, Any]]) -> dict[str, Any]:
    """The tasks a workspace submitted last without passing: still being worked on there."""
    out = {}
    for w in registry:
        last = _d((_l(w.get("submissions")) or [None])[-1])
        if last.get("task") and last.get("verdict") != "passed":
            out[last["task"]] = w.get("person")
    return out


def _context(project: Any) -> dict[str, Any]:
    contract = _d(project.read("contract.json", None))
    states = _d(project.read("tasks.json", {}))
    tasks = [t for t in _l(contract.get("tasks")) if isinstance(t, dict) and t.get("id")]
    opened = _open_cards(project)
    registry = [w for w in _l(project.read("workspaces.json", [])) if isinstance(w, dict)]
    ix = index(project)
    found = commits(project)
    return {"pid": project.pid, "contract": contract, "tasks": tasks, "states": states, "open": opened,
            "index": ix, "registry": registry, "criteria": _criteria(contract), "commits": found["items"],
            "commits_read": found, "running": _running(project), "loose": _channel_agents(project, ix),
            "task_ids": {t["id"] for t in tasks}, "workspaces": _submitted(registry),
            "status": {tid: _d(st).get("status") for tid, st in states.items()},
            "task_cards": {_d(c.get("refs")).get("task"): c for c in opened if _d(c.get("refs")).get("task")}}


def _filters(cards: list[dict[str, Any]]) -> dict[str, list[str]]:
    agents = sorted({str(a.get("harness") or a.get("name")) for c in cards for a in c.get("agents") or []})
    reqs = sorted({r for c in cards for r in c.get("requirements") or []})
    return {"lanes": list(LANES), "harnesses": agents, "requirements": reqs,
            "kinds": sorted({c["kind"] for c in cards})}


def board(project: Any) -> dict[str, Any]:
    """The development board of ``project``: its cards by lane, the filters and what was not measured."""
    ctx = _context(project)
    cards = ([_task_card(t, ctx) for t in ctx["tasks"]] + _decision_cards(ctx) + _workspace_cards(ctx)
             + _handoff_cards(ctx) + _sessions_open(project))
    counts = {lane: sum(1 for c in cards if c["lane"] == lane) for lane in LANES}
    found = ctx["commits_read"]
    out = {"project": project.pid, "title": project.meta.get("title") or project.pid, "lanes": list(LANES),
           "cards": cards, "counts": counts, "filters": _filters(cards),
           "commits": {k: v for k, v in found.items() if k != "items"} | {"count": len(found["items"])},
           "contract": {"revision": ctx["contract"].get("revision"), "tasks": len(ctx["tasks"])}}
    if not ctx["tasks"]:
        out["no_tasks"] = {"why": "the requirements are not compiled into tasks yet",
                           "how": "answer the questions that block it, then the factory compiles the "
                                  "requirements into tasks; or adopt a repository with its own tests"}
    return out


__all__ = ["LANES", "board", "commits", "index"]
