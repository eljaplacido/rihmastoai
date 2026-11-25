"""Rihma's agents answer in a project's agent channel (FR-CHN1, kernel/agent_channel.py).

An external agent's question addressed to Rihma ("what does criterion FR-X-AC-2 mean", "why did the gate fail",
"what should I build next", "is this assumption still open") is answered by a Rihma agent:

- **from the records, by rule, where it can** (``by_rule``): a criterion's given, when and then from the contract;
  the last gate's verdict, its failing signals and objections; what the project waits for and the tasks not yet
  merged; an open question's or assumption's status; the contract's requirements. Each answer names its sources;
- **else through Gnomon** in the matching role: ``verifier`` when the question points at a commit or a diff,
  ``analyst`` otherwise. The answer's trace keeps the run behind it (role, model, tokens, tool calls when Gnomon's
  record has them, and how long it took). A confidential project uses only a local or private model; with a hosted
  one Rihma answers by rule, or says plainly it cannot and how to fix that in Models setup;
- **within limits**, so two agents cannot loop: at most ``REPLIES_PER_HOUR`` Rihma replies per thread an hour, and
  the same question asked again in a thread within the hour gets one pointer to the first answer, then nothing.

A Rihma agent never decides a card and never answers a person's question for them; it never sees holdouts.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any

from kernel import agent_channel as ch

REPLIES_PER_HOUR = 6
CRITERION = re.compile(r"\b([A-Z]{1,6}(?:-[A-Z0-9]{1,8}){1,3}-AC-\d{1,3})\b")
REQUIREMENT = re.compile(r"\b((?:FR|NFR|R|INT)(?:-[A-Z0-9]{1,8}){1,2})\b")
QA_ID = re.compile(r"\b([QA]-\d{3,6})\b")
NO_MODEL = ("I could not answer that from the records, and no model is set up for Rihma's agents here. Ask about a "
            "criterion, the gate, the next step or an open question, or set the analyst role up in Models setup "
            "(Settings, Models).")


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9åäö]+", text.lower()))


def _from_a_person(msg: dict[str, Any]) -> bool:
    """A person writing in the channel gets Rihma's answer unless they wrote to another agent: nobody is left talking
    to an empty room."""
    to_others = [t for t in msg.get("to") or [] if t not in (*ch.RIHMA_ROLES, "rihma")]
    return msg["author"]["kind"] == "person" and not to_others


def _asks_rihma(msg: dict[str, Any], named: list[str]) -> bool:
    """An agent's question is answered only when it asks Rihma (by name, or with Ask Rihma)."""
    return msg["kind"] == "question" and bool(named or msg.get("ask"))


def addressed(msg: dict[str, Any]) -> str | None:
    """The Rihma role a message asks, or None: rihma_ask_rihma, or a question naming @rihma, @analyst, @verifier."""
    if msg.get("held") or msg["author"]["kind"] == "rihma":
        return None
    named = [t for t in msg.get("to") or [] if t in (*ch.RIHMA_ROLES, "rihma")]
    if not (_from_a_person(msg) or _asks_rihma(msg, named)):
        return None
    role = next((t for t in named if t in ch.RIHMA_ROLES), None)
    return role or ("verifier" if (msg.get("refs") or {}).get("commits") else "analyst")


# -- by rule ----------------------------------------------------------------------------------------------

def _criterion(project: Any, cid: str) -> tuple[str, list[str]] | None:
    contract = project.read("contract.json") or {}
    for r in contract.get("requirements", []):
        for c in r.get("acceptance", []):
            if c["id"] == cid:
                return (f"{cid} ({r['id']}: {r['statement']}) Given {c.get('given')}, when {c.get('when')}, then "
                        f"{c.get('then')}.", [cid, r["id"]])
        if r["id"] == cid:
            return f"{cid}: {r['statement']} Criteria: {', '.join(c['id'] for c in r.get('acceptance', []))}.", [cid]
    return None


def _gate(project: Any) -> tuple[str, list[str]] | None:
    recs = project.ledger().of_kind("gate")
    if not recs:
        return "No gate has run on this project yet.", []
    g = recs[-1]["event"]["payload"]
    failing = [f"{k}: {v}" for k, v in (g.get("signals") or {}).items() if v not in ("passed", "pass", True)]
    objections = [str(o)[:300] for o in g.get("objections") or []][:5]
    said = f"The last gate ({g.get('task')}, round {g.get('round')}) said {g.get('verdict')}."
    if failing:
        said += " Signals not passed: " + "; ".join(failing) + "."
    if objections:
        said += " Objections: " + " | ".join(objections)
    return said, [str(g.get("task"))]


def _next(project: Any) -> tuple[str, list[str]]:
    from kernel.next_step import next_step

    nxt = next_step(project)
    tasks = project.read("tasks.json", {}) or {}
    todo = [t for t, s in tasks.items() if s.get("status") not in ("merged", "done")]
    said = f"It waits for {nxt.get('waits_for')}."
    if todo:
        said += f" Tasks not merged yet: {', '.join(todo[:8])}."
    acts = [a["label"] for a in nxt.get("actions") or [] if a.get("label")][:3]
    if acts:
        said += " Next: " + "; ".join(acts) + "."
    return said, todo[:8]


def _open_items(project: Any, text: str) -> tuple[str, list[str]]:
    from kernel.canon import Canon

    canon = Canon(project)
    ids = QA_ID.findall(text.upper())
    if ids:
        out = []
        for i in ids:
            try:
                item = canon.question(i) if i.startswith("Q") else next(a for a in canon.assumptions() if a["id"] == i)
            except (KeyError, StopIteration):
                out.append(f"There is no {i}.")
                continue
            out.append(f"{i} is {item.get('status')}: {item['text'][:200]}")
        return " ".join(out), ids
    qs, asm = canon.questions("open"), canon.assumptions("open")
    said = f"{len(qs)} open question(s) and {len(asm)} open assumption(s)."
    if qs:
        said += " Questions: " + "; ".join(f"{q['id']} {q['text'][:120]}" for q in qs[:5]) + "."
    if asm:
        said += " Assumptions: " + "; ".join(f"{a['id']} {a['text'][:120]}" for a in asm[:5]) + "."
    return said, [q["id"] for q in qs[:5]] + [a["id"] for a in asm[:5]]


def _contract(project: Any) -> tuple[str, list[str]]:
    contract = project.read("contract.json") or {}
    reqs = contract.get("requirements") or []
    if not reqs:
        return "There is no contract yet: criteria come with it.", []
    return ("The contract's requirements: " + "; ".join(f"{r['id']} {r['statement'][:120]}" for r in reqs[:10])
            + "."), [r["id"] for r in reqs[:10]]


def by_rule(project: Any, text: str) -> tuple[str, list[str], str] | None:
    """An answer from the records, its sources and what it rests on; None when the rules cannot answer."""
    low = text.lower()
    cid = CRITERION.search(text) or REQUIREMENT.search(text)
    if cid:
        found = _criterion(project, cid.group(1))
        if found:
            return found[0], found[1], "the contract"
    if "gate" in low and re.search(r"\b(fail|why|result|verdict|pass|portti)", low):
        found = _gate(project)
        if found:
            return found[0], found[1], "the ledger's gate records"
    if re.search(r"\b(next|build next|what should i (?:build|do)|seuraavaksi|waits? for)\b", low):
        said, src = _next(project)
        return said, src, "what the project waits for (kernel/next_step.py)"
    if re.search(r"\b(assumption|question|still open|oletus|kysymys)", low) or QA_ID.search(text.upper()):
        said, src = _open_items(project, text)
        return said, src, "the canon's questions and assumptions"
    if re.search(r"\b(criteria|contract|requirements|vaatimukset)\b", low):
        said, src = _contract(project)
        return said, src, "the contract"
    return None


# -- the limits -------------------------------------------------------------------------------------------

def _within_hour(project: Any, m: dict[str, Any]) -> bool:
    at = ch._when(m["at"])
    return at is not None and project.factory.clock.now() - at <= dt.timedelta(hours=1)


def _note_once(project: Any, msg: dict[str, Any], said: bool, ref: str, text: str) -> dict[str, Any] | bool:
    """The limit's note, once: False (silence) when it was said already this hour."""
    if said:
        return False
    return ch.post(project, author=ch.SYSTEM, kind="note", thread=msg["thread"], refs={"message": ref}, text=text)


def _last_hour(project: Any, msg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """The thread's last hour before ``msg``: the system's notes, the same question asked, Rihma's replies."""
    hour = [m for m in ch.messages(project, thread=msg["thread"], limit=100000)
            if m["id"] != msg["id"] and _within_hour(project, m)]
    notes = [m for m in hour if m["author"]["kind"] == "system" and m["kind"] == "note"]
    same = [m for m in hour if m["kind"] == "question" and _norm(m["text"]) == _norm(msg["text"])]
    return notes, same, len([m for m in hour if m["author"]["kind"] == "rihma"])


def _limited(project: Any, msg: dict[str, Any]) -> dict[str, Any] | None | bool:
    """A system note when Rihma must not answer, False when it stays silent, None when it may answer."""
    notes, same, replies = _last_hour(project, msg)
    if same:
        first = same[0]["id"]
        return _note_once(project, msg, any((m.get("refs") or {}).get("message") == first for m in notes), first,
                          f"The same question again: {first} has it. Rihma does not answer a question twice in an "
                          "hour, so two agents cannot keep each other going.")
    if replies >= REPLIES_PER_HOUR:
        return _note_once(project, msg, any("capped" in m["text"] for m in notes), msg["id"],
                          f"Rihma's replies in this thread are capped at {REPLIES_PER_HOUR} an hour: it is capped "
                          "now. A person may still answer, or ask again in an hour.")
    return None


# -- the model ----------------------------------------------------------------------------------------------

def _records_prompt(project: Any, msg: dict[str, Any], role: str) -> str:
    said, _ = _contract(project)
    nxt, _ = _next(project)
    items, _ = _open_items(project, "")
    look = ("Review what the question points at against the contract's criteria, as an independent verifier."
            if role == "verifier" else "Explain from the spec and the contract, as the project's analyst.")
    return (f"You are Rihma's {role} in the agent channel of the project {project.meta.get('title')}. A coding agent "
            f"asks a question. {look} Answer in at most five sentences, only from what follows; say what you cannot "
            "see. You decide nothing and answer no person's question for them.\n\n"
            f"{said}\n{nxt}\n{items}\nThe records the question names: {msg.get('refs')}\n\n"
            f"The question:\n<<<\n{msg['text']}\n>>>\n")


def _trace(model: Any, role: str, started: float) -> dict[str, Any]:
    rec = getattr(model, "last_record", None) or {}
    usage = rec.get("usage") if isinstance(rec.get("usage"), dict) else {}
    calls = rec.get("tool_calls")
    return {"basis": "model", "role": role, "model": rec.get("model") or getattr(model, "name", None)
            or type(model).__name__, "tokens": usage.get("total_tokens") or rec.get("tokens"),
            "tool_calls": len(calls) if isinstance(calls, list) else calls, "run": rec.get("run_id") or rec.get("id"),
            "duration_ms": int((time.monotonic() - started) * 1000)}


def _model_answer(project: Any, msg: dict[str, Any], role: str, model: Any) -> tuple[str, dict[str, Any]] | str:
    from kernel.confidential import confidential, refusal
    from kernel.model import ModelError

    if confidential(project) and refusal([role]):
        return ("This project is confidential and the model for Rihma's agents is hosted, so nothing was sent. I "
                "answer such projects from the records only: set the analyst and verifier roles to a local or private "
                "endpoint in Models setup (Settings, Models) to let a model answer here.")
    from kernel import model_usage

    started = time.monotonic()
    try:
        with model_usage.for_project(project, task="channel"):   # its run as model_run: Insights' usage counts it
            text = str(model.ask(_records_prompt(project, msg, role), role=role) or "").strip()
    except (ModelError, OSError, RuntimeError, ValueError) as exc:
        return f"The model for Rihma's agents gave no answer ({type(exc).__name__}). {NO_MODEL}"
    if not text:
        return NO_MODEL
    from kernel.assistant_rules import honest

    return honest(text, [], [])[0], _trace(model, role, started)


def reply(project: Any, msg: dict[str, Any], *, model: Any = None) -> dict[str, Any] | None:
    """Rihma's answer to a message addressed to it, posted in its thread; a system note at a limit; or None."""
    role = addressed(msg)
    if role is None or ch.read(project).get("paused"):
        return None
    stop = _limited(project, msg)
    if stop is False:
        return None
    if isinstance(stop, dict):
        return stop
    ruled = by_rule(project, msg["text"])
    if ruled is not None:
        text, sources, basis = ruled
        trace = {"basis": "rule", "rests_on": basis, "sources": sources}
        return ch.post(project, author=ch.rihma(role), kind="answer", text=text, thread=msg["thread"],
                       refs={"message": msg["id"]}, trace=trace)
    if model is None:
        return ch.post(project, author=ch.rihma(role), kind="answer", text=NO_MODEL, thread=msg["thread"],
                       refs={"message": msg["id"]}, trace={"basis": "none"})
    got = _model_answer(project, msg, role, model)
    text, trace = (got, {"basis": "rule", "rests_on": "nothing: no model was asked"}) if isinstance(got, str) else got
    return ch.post(project, author=ch.rihma(role), kind="answer", text=text, thread=msg["thread"],
                   refs={"message": msg["id"]}, trace=trace)
