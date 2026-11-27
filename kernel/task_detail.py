"""A task you can open (FR-LND1): its criteria, the tests that check it and how they last ended, the commits and agent
sessions that touched it, its status history and what a person can do with it next.

The owner (2026-11-26): "Tasks view is maybe too static? ... shouldnt I be able to open the tasks somehow". Every task
of a project's contract opens at ``#/p/<pid>/tasks/<id>``; the list says where each task came from (``source``: the
factory's plan, the repository's own spec through Alignment, or the existing code at adoption) and its status, with a
person's own marks over the factory's: started, or done with evidence.

Everything is read from the records (the contract, ``tasks.json``, the ledger, the agent channel, the repository's
commits through kernel/devboard.py, the evidence per criterion through kernel/status.py and the tests traced to its
criteria through Alignment). The writes are a person's, signed and in the ledger:

- ``start``: ``task_started``, the person working on it now (the factory's own cell is started by Advance);
- ``mark_done``: ``task_marked_done``, with the evidence the person gives (a test run, a commit, a link); it never
  claims the gate: the task shows "done, marked by <person>", apart from "merged" that only the gate gives;
- ``handoff``: the project's brief narrowed to the task, given to a coding agent, posted in the agent channel with the
  task in its references (so the board and the trace see who works on it) and ``agent_handoff`` in the ledger.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import task_rules  # what a task waits for, and its lane (FR-LND2)
from kernel.devboard import _l  # a list's items, or none (one helper for both readers of the records)
from kernel.graph_records import object_of
from kernel.people import PERSONAS, is_person

STARTED, DONE = "task_started", "task_marked_done"
WORKERS = ("developer", "product_owner", "business_owner", "it", "operations")
CLOSERS = ("developer", "product_owner", "business_owner")
SOURCES = {"plan": "the factory's plan (compiled from the spec)",
           "repository": "the repository's own spec, accepted in Alignment",
           "adopted": "the existing code at adoption (observed, not built by the factory)"}
STATUSES = ("pending", "started", "building", "merged", "done", "escalated", "stopped")
HISTORY_KINDS = {"cell_ran": "a builder cell ran it", "gate": "the gate judged it", "merged": "merged by the gate",
                 "escalated": "sent to a person", "task_reopened": "reopened", "task_stopped": "stopped",
                 STARTED: "started by a person", DONE: "marked done with evidence",
                 "agent_handoff": "handed to an agent", "dev_session_recorded": "an outside coding session touched it",
                 "model_run": "an AI model worked on it", "channel_posted": "the agent channel named it"}
TASK_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,39}\Z")
MAX_EVIDENCE = 2000


class TaskRefused(ValueError):
    """A start, a done or a hand-off the kernel does not take; ``status`` is the HTTP status it answers with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


_d = object_of                # an object, or an empty one (kernel/graph_records.py)


def _contract(project: Any) -> dict[str, Any]:
    return _d(project.read("contract.json", None))


def _states(project: Any) -> dict[str, Any]:
    return _d(project.read("tasks.json", {}))


def _requirements(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in _l(contract.get("requirements")) if isinstance(r, dict) and r.get("id")}


def _req_of(cid: str) -> str:
    return cid.rsplit("-AC-", 1)[0]


def source_of(task: dict[str, Any], state: dict[str, Any], reqs: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Where a task came from, and that in words with the file it was read from when there is one."""
    if state.get("adopted") is True:
        return "adopted", SOURCES["adopted"]
    for cid in _l(task.get("criteria")):
        notes = str(_d(reqs.get(_req_of(str(cid)))).get("notes") or "")
        if notes.startswith("imported from the repository"):
            where = notes.split("(", 1)[1].split(",", 1)[0] if "(" in notes else ""
            return "repository", SOURCES["repository"] + (f" ({where})" if where else "")
    if str(task.get("id") or "").startswith("AL-"):
        return "repository", SOURCES["repository"]
    return "plan", SOURCES["plan"]


def _marks(project: Any) -> dict[str, dict[str, Any]]:
    """A person's last start and done on each task, from the ledger."""
    out: dict[str, dict[str, Any]] = {}
    for rec in project.ledger().records():
        ev = _d(_d(rec).get("event"))
        if ev.get("kind") not in (STARTED, DONE):
            continue
        pl = _d(ev.get("payload"))
        slot = out.setdefault(str(pl.get("task")), {})
        slot["done" if ev["kind"] == DONE else "started"] = {
            "person": pl.get("person"), "persona": pl.get("persona"), "at": ev.get("at"),
            **({"evidence": pl.get("evidence")} if ev["kind"] == DONE else {})}
    return out


def effective(status: str, mark: dict[str, Any]) -> str:
    """The status a person reads: the gate's, with a person's done or start over a task the gate has not merged."""
    if status == "merged":
        return "merged"
    if mark.get("done"):
        return "done"
    if mark.get("started") and status == "pending":
        return "started"
    return status if status in STATUSES else "pending"


def enrich(project: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cockpit's task rows (cockpit/server.py ``_tasks``) with their source and a person's marks."""
    contract = _contract(project)
    reqs, states, marks = _requirements(contract), _states(project), _marks(project)
    for row in rows:
        src, said = source_of(row, _d(states.get(row["id"])), reqs)
        mark = marks.get(row["id"], {})
        row.update(source=src, source_said=said, mark=mark or None,
                   shown_status=effective(str(row.get("status") or "pending"), mark),
                   lane=task_rules.lane(str(row.get("status") or "pending"), mark))   # done: its own lane
    return rows


def _mark_sig(mark: dict[str, Any]) -> str:
    """A person's marks in the board's signature: a start or a done moves it even where the status stays."""
    return "".join(k[0] + str(_d(mark.get(k)).get("at") or "") for k in ("started", "done") if mark.get(k))


def rows(project: Any) -> dict[str, Any]:
    """Every task with its status and source, for the list's filters, and a signature that changes when one does."""
    contract = _contract(project)
    reqs, states, marks = _requirements(contract), _states(project), _marks(project)
    out = []
    for t in _l(contract.get("tasks")):
        if not isinstance(t, dict) or not t.get("id"):
            continue
        st = _d(states.get(t["id"]))
        src, said = source_of(t, st, reqs)
        mark = marks.get(t["id"], {})
        out.append({"id": t["id"], "title": t.get("title") or t["id"], "status": effective(st.get("status", "pending"),
                                                                                           mark),
                    "gate_status": st.get("status", "pending"), "rounds": len(_l(st.get("rounds"))), "source": src,
                    "source_said": said, "mark": mark or None, "open": f"#/p/{project.pid}/tasks/{t['id']}",
                    "lane": task_rules.lane(st.get("status", "pending"), mark), "marks": _mark_sig(mark)})
    from kernel import status as kstatus

    try:
        lv = kstatus.live(project)
    except (OSError, ValueError):
        lv = {}
    running = lv.get("task") if lv.get("running") and not lv.get("ended") else None
    sig = "|".join(f"{r['id']}:{r['status']}:{r['rounds']}:{r.pop('marks')}" for r in out) \
        + f"|live:{running}:{lv.get('steps')}"
    return {"project": project.pid, "tasks": out, "statuses": list(STATUSES), "sources": SOURCES,
            "running": running, "signature": sig,
            **({} if out else {"why": "the project has no tasks yet: they come from its compiled contract, or from "
                                      "its repository's own spec accepted in Alignment"})}


def _task(project: Any, tid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = _contract(project)
    task = next((t for t in _l(contract.get("tasks")) if isinstance(t, dict) and t.get("id") == tid), None)
    if task is None:
        raise TaskRefused(f"{project.pid} has no task {tid}", 404)
    return task, contract


def _criteria(task: dict[str, Any], contract: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> list[dict]:
    reqs = _requirements(contract)
    out = []
    for cid in _l(task.get("criteria")):
        req = _d(reqs.get(_req_of(cid)))
        c: dict[str, Any] = next((x for x in _l(req.get("acceptance")) if _d(x).get("id") == cid), {})
        ev = evidence.get(cid, {})
        out.append({"id": cid, "requirement": req.get("id"), "statement": str(req.get("statement") or "")[:400],
                    "given": c.get("given"), "when": c.get("when"), "then": c.get("then"),
                    "state": ev.get("state", "not_measured"), "evidence": _l(ev.get("evidence"))})
    return out


def _tests(project: Any, task: dict[str, Any], card: dict[str, Any], crits: list[dict]) -> list[dict[str, Any]]:
    """The tests that check the task: from its last gate round, from the names that carry its criteria on main,
    and from the repository's own tests traced to its criteria in Alignment; each with how it last ended."""
    out = [{"name": t["name"], "result": t["result"], "from": "the last gate round"} for t in card.get("tests") or []]
    seen = {t["name"] for t in out}
    for c in crits:
        for ev in c["evidence"]:
            for name in ev.get("tests") or []:
                if name not in seen:
                    seen.add(name)
                    result = "passed" if c["state"] == "verified" else "not run by the gate yet"
                    out.append({"name": name, "result": result, "from": f"named for {c['id']} on main"})
    from kernel import alignment_records

    wanted = {c["id"] for c in crits}
    for item in alignment_records.accepted(project, "trace"):
        p = _d(item.get("proposal"))
        if p.get("criterion_id") in wanted and p.get("test") not in seen:
            seen.add(p.get("test"))
            out.append({"name": f"{p.get('file')}::{p.get('test')}", "result": "not measured here",
                        "from": f"its repository, traced to {p.get('criterion_id')}",
                        "why": "Rihmasto has not run its own suite for this test; its own runner's results come in "
                               "through the project's checks"})
    return out


def history(project: Any, tid: str) -> list[dict[str, Any]]:
    """Every ledger record about the task, oldest first, in words."""
    out = []
    for rec in project.ledger().records():
        ev = _d(_d(rec).get("event"))
        pl, kind = _d(ev.get("payload")), str(ev.get("kind"))
        tasks = _l(pl.get("tasks")) or [pl.get("task")]
        as_is = kind == "adoption_tasks" and tid in _l(pl.get("as_is"))
        if tid not in tasks and not as_is:
            continue
        said = "taken as the existing code at adoption" if as_is else HISTORY_KINDS.get(kind, kind.replace("_", " "))
        if kind == "gate":
            said += f": {pl.get('verdict')} (round {pl.get('round')})"
        if kind == DONE and pl.get("evidence"):
            said += f": {str(pl['evidence'])[:200]}"
        who = pl.get("person") or (pl.get("role") and str(pl["role"]).replace("_", " "))
        out.append({"at": ev.get("at"), "kind": kind, "said": said, "who": who, "seq": _d(rec).get("seq")})
    return out


def actions(project: Any, tid: str, status: str, waits: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """What a person can do with the task now, each with the route and the control that does it; nothing it waits
    for first (kernel/task_rules.py)."""
    base = f"/api/projects/{project.pid}/tasks/{tid}"
    out = [{"id": "handoff", "label": "Hand it to a coding agent", "method": "POST", "path": base + "/handoff",
            "control": "task_handoff", "personas": list(WORKERS)}]
    if status in ("pending",) and waits is None:
        out.append({"id": "start", "label": "Start it", "method": "POST", "path": base + "/start",
                    "control": "task_start", "personas": list(WORKERS)})
    if status not in ("merged", "done") and (waits or {}).get("kind") != "decision":
        out.append({"id": "done", "label": "Mark it done, with evidence", "method": "POST", "path": base + "/done",
                    "control": "task_done", "personas": list(CLOSERS), "needs": ["evidence"]})
    out.append({"id": "ask", "label": "Ask Rihma about it", "control": "task_ask",
                "question": f"What about {tid}? What is left to do on it?"})
    return out


NO_COMMITS = "no commit names this task yet: a commit that carries its id in its message shows here"


def _board_card(project: Any, tid: str) -> dict[str, Any]:
    """What the development board says of the task (kernel/devboard.py): its lane and why, its commits (or why none
    show), the agents that worked on it, its gate rounds and the card it waits on."""
    from kernel import devboard

    board = devboard.board(project)
    card: dict[str, Any] = next((c for c in board["cards"] if c.get("kind") == "task" and c.get("id") == tid), {})
    commits = _l(card.get("commits"))
    why = None if commits else _d(board.get("commits")).get("why") or NO_COMMITS
    return {"lane": card.get("lane"), "why": card.get("why"), "commits": commits, "commits_why": why,
            "agents": _l(card.get("agents")), "rounds": _l(card.get("gates")), "waits_on": card.get("waits_on"),
            "tests": _l(card.get("tests"))}


def detail(project: Any, tid: str) -> dict[str, Any]:
    """Everything about one task, for its panel and for Ask Rihma."""
    from kernel import status as kstatus
    from kernel.devsessions import sessions

    if not TASK_ID.match(tid or ""):
        raise TaskRefused("a task is named by its id, such as T-001", 400)
    task, contract = _task(project, tid)
    card = _board_card(project, tid)
    crits = _criteria(task, contract, {r["criterion"]: r for r in kstatus.evidence(project)})
    st = _d(_states(project).get(tid))
    src, said = source_of(task, st, _requirements(contract))
    mark = _marks(project).get(tid, {})
    status = effective(st.get("status", "pending"), mark)
    touched = [s for s in sessions(project) if tid in _l(s.get("tasks"))][-10:]
    waits = task_rules.waits(project, tid) if status not in ("merged", "done") else None
    return {"project": project.pid, "id": tid, "title": task.get("title") or tid, "status": status, "waits": waits,
            "gate_status": st.get("status", "pending"), "source": src, "source_said": said, "mark": mark or None,
            "criteria": crits, "tests": _tests(project, task, card, crits), "sessions": touched,
            **{k: card[k] for k in ("lane", "why", "commits", "commits_why", "agents", "rounds", "waits_on")},
            "depends_on": _l(task.get("depends_on")),
            "history": history(project, tid), "actions": actions(project, tid, status, waits),
            "open": f"#/p/{project.pid}/tasks/{tid}", "by": "rule"}


# -- a person's writes ------------------------------------------------------------------------------------------

def _signed(person: str, persona: str, allowed: tuple[str, ...], what: str) -> None:
    if not is_person(person) or persona not in PERSONAS:
        raise TaskRefused(f"{what} is signed by a named person with their persona", 403)
    if persona not in allowed:
        raise TaskRefused(f"as {persona} you may not {what} (may: {', '.join(allowed)})", 403)


def start(project: Any, tid: str, *, person: str, persona: str, note: str = "") -> dict[str, Any]:
    """A person starts work on a task: recorded, and the list shows it started."""
    _signed(person, persona, WORKERS, "start a task")
    _task(project, tid)
    st = _d(_states(project).get(tid)).get("status", "pending")
    if st in ("merged", "building"):
        raise TaskRefused(f"{tid} is {st} already: nothing to start", 409)
    waits = task_rules.waits(project, tid)          # its dependencies, or the decision it is escalated to
    if waits is not None:
        raise TaskRefused(waits["said"], 409)
    rec = project.log(STARTED, {"task": tid, "person": person, "persona": persona, "note": str(note or "")[:500]})
    return {"task": tid, "status": "started", "at": rec["event"].get("at"), "person": person}


def mark_done(project: Any, tid: str, *, person: str, persona: str, evidence: str) -> dict[str, Any]:
    """A person marks a task done with the evidence they give. The gate's merge stays the gate's."""
    _signed(person, persona, CLOSERS, "mark a task done")
    _task(project, tid)
    evidence = " ".join(str(evidence or "").split())[:MAX_EVIDENCE]
    if not evidence:
        raise TaskRefused("say what shows it is done: a test run, a commit, a link or what you checked")
    if _d(_states(project).get(tid)).get("status") == "merged":
        raise TaskRefused(f"{tid} is merged by the gate already", 409)
    waits = task_rules.waits(project, tid)
    if waits is not None and waits["kind"] == "decision":   # the decision first, as Start here and its panel say
        raise TaskRefused(waits["said"], 409)
    rec = project.log(DONE, {"task": tid, "person": person, "persona": persona, "evidence": evidence,
                             "note": "marked by a person; the gate's merge is not claimed"})
    return {"task": tid, "status": "done", "at": rec["event"].get("at"), "person": person, "evidence": evidence}


def brief(project: Any, tid: str) -> dict[str, Any]:
    """The project's hand-off brief narrowed to one task."""
    from kernel import agent_bridge as bridge

    task, _ = _task(project, tid)
    b = bridge.brief(project, goal=f"Task {tid}: {task.get('title') or tid}")
    wanted = set(_l(task.get("criteria")))
    b["criteria"] = [c for c in b["criteria"] if c["id"] in wanted] or b["criteria"]
    b["plan"] = [t for t in b["plan"] if t.get("id") == tid] or b["plan"]
    return b


def handoff(project: Any, tid: str, *, to: str, person: str, persona: str, via: str = "copy") -> dict[str, Any]:
    """Give one task to a coding agent: its brief, a channel post that names the task, and the ledger's record."""
    from kernel import agent_bridge as bridge
    from kernel import agent_channel as ch

    _signed(person, persona, WORKERS, "hand a task to a coding agent")
    if to not in bridge.AGENTS or via not in ("copy", "download"):
        raise TaskRefused(f"to is one of {', '.join(bridge.AGENTS)}; via is copy or download")
    b = brief(project, tid)
    text = bridge.render(b)
    msg = ch.post(project, author=ch.person(person, persona), kind="handoff",
                  text=f"Handed {tid} to {bridge.AGENTS[to]} ({via}).",
                  refs={"tasks": [tid], "criteria": [c["id"] for c in b["criteria"]][:20]})
    project.log("agent_handoff", {"to": to, "via": via, "person": person, "persona": persona, "task": tid,
                                  "change": None, "sha256": bridge.digest(text), "message": msg["id"]})
    return {"task": tid, "message": msg, "markdown": text, "to": to,
            "use": bridge.for_agent(project.factory, project, b, to=to, operator=person, persona=persona)}


__all__ = ["CLOSERS", "SOURCES", "STATUSES", "TaskRefused", "WORKERS", "brief", "detail", "effective", "enrich",
           "handoff", "history", "mark_done", "rows", "source_of", "start"]
