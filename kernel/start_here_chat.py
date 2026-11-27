"""Ask Rihma, by rule, for FR-LND1 (kernel/assistant.py calls ``answer`` before any model):

- "what should I do here?", "where do I start with this project?" (in a project also "where do I start?", "what
  now?", FR-LND2) -> the project's Start here: what Rihmasto
  understood it to be, the one to three steps to take now (each with Take me there), and what runs on its own
  meanwhile (kernel/start_here.py), the same panel the project's first view shows;
- "what about T-003?", "tell me about AL-2" -> the task's state, criteria, tests, history and what to do with it
  (kernel/task_detail.py), with the task's panel to open;
- "start T-003", "hand T-003 to Claude Code", "mark T-003 done: the suite passed at abc123" -> the same write the
  task's panel makes, proposed for the person to confirm (kernel/assistant_ops.py ``OPS``), never done unasked; a
  task that waits for another or for a decision says so instead (kernel/task_rules.py, FR-LND2);
- "how do I keep Claude Code in sync with this project and what should I monitor?" -> a sync plan
  (kernel/agent_sync_chat.py, FR-LND2).
"""

from __future__ import annotations

import re
from typing import Any

# op -> (label, method, path template, the arguments it needs, the arguments it sends, the map's control): the task
# panel's writes as Ask Rihma's operations (kernel/assistant_ops.py takes them in), {item} being the task's id.
OPS: dict[str, tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]] = {
    "start_task": ("Start the task", "POST", "/api/projects/{pid}/tasks/{item}/start", ("item",), ("note",),
                   "task_start"),
    "mark_task_done": ("Mark the task done, with its evidence", "POST", "/api/projects/{pid}/tasks/{item}/done",
                       ("item", "evidence"), ("evidence",), "task_done"),
    "hand_off_task": ("Hand the task to a coding agent", "POST", "/api/projects/{pid}/tasks/{item}/handoff",
                      ("item",), ("to",), "task_handoff"),
}
HERE = re.compile(
    r"\bwhat (?:should|do|can|must) (?:i|we) do (?:here|in this project|on this project|with this project|first)\b|"
    r"\bwhere (?:do|should|can) (?:i|we) (?:start|begin) (?:here|with this|in this|on this)\b|"
    r"\bstart here\b|\bwhat(?:'s| is) (?:there )?(?:for me )?to do here\b|\bwhat (?:do|should) i expect here\b|"
    r"\bmitä (?:minun )?(?:pitäisi |kannattaa )?tehdä tässä\b|\bmistä aloitan tässä\b", re.I)
# In a project, the bare forms ask the same (FR-LND2): "where do I start?", "what now?", "what now in this project?";
# outside one they stay the guided journeys' question.
HERE_IN_PROJECT = re.compile(
    r"^\W*(?:so |ok |okay |and )?(?:where (?:do|should|can) (?:i|we) (?:start|begin)|what now|now what|"
    r"what do (?:i|we) do now|what (?:should|do) (?:i|we) do first|where to (?:start|begin))"
    r"(?: (?:here|in this project|on this project|with this project|with it|first))?\W*$|"
    r"\bwhat now in this project\b|\bmistä aloitan\b|\bmitä nyt\b", re.I)
TASK = re.compile(r"\b((?:T|AL)-\d{1,5})\b", re.I)
_START = re.compile(r"^\W*(?:please |ok |okay )?(?:start|begin|pick up|take)\b", re.I)
# "hand T-003 to Claude Code" is the signed hand-off proposed here; "hand off T-003 ..." opens the hand-off dialog
# (kernel/handoff_chat.py), so a "hand off" is not this rule's
_HAND = re.compile(r"\b(?:hand(?![ -]?off)|give|send|pass)\b.{0,40}\b(?:to|over)\b", re.I)
_DONE = re.compile(r"\bmark\b.{0,30}\b(?:done|finished|complete)\b|\b(?:is|it's|its) done\b", re.I)
_ABOUT = re.compile(r"\b(?:what about|tell me about|status of|state of|show me|open|explain|what is|what's|"
                    r"how is|where is|details of|kerro)\b", re.I)
_AGENTS = (("claude-code", re.compile(r"\bclaude(?: code)?\b", re.I)), ("codex", re.compile(r"\bcodex\b", re.I)),
           ("cursor", re.compile(r"\bcursor\b", re.I)), ("opencode", re.compile(r"\bopen ?code\b", re.I)))
_EVIDENCE = re.compile(r"(?:\bbecause\b|\bevidence\b|\bwith\b|:)\s*(.+)$", re.I)


def _shape(answer: str, route: str | None, control: str | None, **extra: Any) -> dict[str, Any]:
    return {"answer": answer, "navigate": {"route": route, "control": control} if route else None, "by": "rule",
            "propose": [], "dropped": [], "sources": [], "matches": ["start_here"], **extra}


def asks_here(question: str, in_project: bool = False) -> bool:
    return bool(HERE.search(question or "") or (in_project and HERE_IN_PROJECT.search(question or "")))


def here_answer(factory: Any, project: Any, person: str | None = None) -> dict[str, Any]:
    """The Start here panel in words, its steps as Take me there."""
    from kernel import start_here

    if project is None:
        return _shape("Open a project and ask again: each project's first view starts with what Rihmasto understood "
                      "it to be and the one to three things to do there now. Across projects, the Inbox and Decide "
                      "what matters list what waits on you.", "#/projects", None, topic="start_here")
    p = start_here.panel(project, person=person)
    first = (p["steps"] or [None])[0]       # each step is its own button under the answer (starthere.js chatBlock)
    return _shape(p["said"], first["route"] if first else f"#/p/{project.pid}/overview",
                  first.get("control") if first else None, start_here=p, topic="start_here")


def _task_said(d: dict[str, Any]) -> str:
    crit = "; ".join(f"{c['id']} ({c['state'].replace('_', ' ')})" for c in d["criteria"][:6]) or "none"
    tests = "; ".join(f"{t['name']}: {t['result']}" for t in d["tests"][:5]) or "none found yet"
    last = d["history"][-1]["said"] if d["history"] else "nothing recorded yet"
    mark = d.get("mark") or {}
    done = mark.get("done")
    status = (f"done, marked by {done['person']} ({done['evidence']})" if d["status"] == "done" and done
              else d["status"])
    acts = ", ".join(a["label"] for a in d["actions"] if a["id"] != "ask")
    waits = f" It waits: {d['waits']['said']}." if d.get("waits") else ""      # FR-LND2
    return (f"{d['id']}: {str(d['title']).rstrip('.')}. Status: {status}; from {d['source_said']}.{waits} "
            f"Criteria: {crit}. Tests: {tests}. Last: {last}. You can: {acts}.")


def _wants(question: str) -> str | None:
    """What a question about a task asks: hand it off, mark it done, start it, or about it."""
    for name, rx in (("handoff", _HAND), ("done", _DONE), ("start", _START), ("about", _ABOUT)):
        if rx.search(question):
            return name
    return None


OP_OF = {"start": "start_task", "done": "mark_task_done", "handoff": "hand_off_task"}


def _args(wants: str, tid: str, rest: str, question: str) -> dict[str, Any] | None:
    """The operation's arguments from the words; None when a done names no evidence."""
    args: dict[str, Any] = {"item": tid}
    if wants == "handoff":
        args["to"] = next((k for k, rx in _AGENTS if rx.search(question)), "generic")
    if wants == "done":
        ev = _EVIDENCE.search(rest)
        if not ev or not ev.group(1).strip(" .?"):
            return None
        args["evidence"] = ev.group(1).strip()[:500]
    return args


def _waiting(wants: str, d: dict[str, Any], said: str) -> dict[str, Any] | None:
    """A start or a done the task is not ready for: what it waits for first, never a proposal (FR-LND2)."""
    w = d.get("waits") or {}
    if not ((wants == "start" and w) or (wants == "done" and w.get("kind") == "decision")):
        return None
    return _shape(f"{said} So it cannot be {'started' if wants == 'start' else 'marked done'} yet: {w['said']}.",
                  w["route"], "decide" if w.get("card") else "task_open", task=d)


def task_answer(factory: Any, project: Any, question: str, persona: str) -> dict[str, Any] | None:
    """A question or a request about one named task."""
    from kernel import assistant_ops, task_detail

    m = TASK.search(question or "")
    wants = _wants(question) if m is not None and project is not None else None
    if m is None or wants is None:
        return None
    tid = m.group(1).upper()
    try:
        d = task_detail.detail(project, tid)
    except task_detail.TaskRefused as exc:
        return _shape(f"{exc} Open Tasks to see the project's tasks and where each came from.",
                      f"#/p/{project.pid}/tasks", "task_open")
    said, route = _task_said(d), d["open"]
    if wants == "about":
        return _shape(said, route, "task_open", task=d)
    waiting = _waiting(wants, d, said)
    if waiting is not None:
        return waiting
    op, args = OP_OF[wants], _args(wants, tid, question[m.end():], question)
    if args is None:
        return _shape(f"{said} To mark it done, say what shows it is done: \"mark {tid} done: the suite passed "
                      "at <commit>\", or use Mark it done on the task's panel.", route, "task_done", task=d)
    prop = assistant_ops.proposal(factory, op, args, persona=persona, project=project)
    if prop is None:
        return _shape(said + " That cannot be proposed here: open the task to do it by hand.", route, "task_open",
                      task=d)
    return {**_shape(f"{said} Confirm below to {assistant_ops.label(op).lower()}; it is signed with your name.",
                     route, assistant_ops.control(op), task=d), "propose": [prop]}


def answer(factory: Any, project: Any, question: str, persona: str = "developer",
           person: str | None = None) -> dict[str, Any] | None:
    """Ask Rihma's answer by rule, or None when the question is not one of these."""
    if asks_here(question, project is not None):
        return here_answer(factory, project, person)
    from kernel import agent_sync_chat

    return (task_answer(factory, project, question, persona)
            or agent_sync_chat.answer(factory, project, question, person))   # a sync plan for a coding agent


__all__ = ["HERE", "answer", "asks_here", "here_answer", "task_answer"]
