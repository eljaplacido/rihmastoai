"""A project's agent channel (FR-CHN1, docs/guides/agentic-help.md): one threaded conversation between the
people, Rihma's own agents and the coding agents working on the project in a terminal or an IDE.

The owner (2026-11-24): "per project, the Rihma agents should be able to do this back and forth with terminal or
IDE agents, and me being able to track it, in a chat window or some agent tracing / monitoring."

A message has an id (``M-0001``), a thread (``main`` unless named), when, its author and kind, its text, the records
it refers to (criteria, tasks, cards, questions, commits, checks, files), whom it names (``@analyst``, ``@verifier``,
``@<agent>``) and, for a proposal, its state. Authors are of five kinds (``AUTHOR_KINDS``):

- a **person**, signed with their name and persona;
- a **Rihma agent** in a role (``RIHMA_ROLES``: analyst, verifier, assistant). The holdout author never posts here,
  so no holdout content can reach the channel through it;
- an **external agent** (Claude Code, Codex, OpenCode, Cursor, a script), named, with its harness and the named
  person who operates it and signs for it;
- an **automation** (its id and its owner), and the **system** (gate and check results it was asked for).

Kept in the project's ``agent_channel.json``. Every post is in the ledger as ``channel_posted`` with its ids, author
and kind, never its text. A person may **pause** the channel: an external agent's posts then wait (held) and Rihma
answers none, until a person resumes it. A proposal (an answer an agent suggests to an open question) is never an
answer by itself: a person confirms or rejects it (``settle``), and confirming answers the question through the
same kernel path as the Questions view. Nothing here decides a card.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from kernel.people import PERSONAS, is_person
from kernel.store import updating_json

FILE = "agent_channel.json"
KINDS = ("question", "answer", "progress", "feedback", "plan", "handoff", "gate_result", "check_result", "proposal",
         "note")
AUTHOR_KINDS = ("person", "rihma", "agent", "automation", "system")
RIHMA_ROLES = ("analyst", "verifier", "assistant")
MAIN = "main"
MAX_TEXT = 8000
MAX_REFS = 40
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,40}\Z")
THREAD = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}\Z")
MENTION = re.compile(r"(?<![\w@])@([a-z0-9][a-z0-9._-]{0,40})", re.I)
REF_KEYS = ("criteria", "tasks", "cards", "questions", "assumptions", "commits", "checks", "files", "message", "gate")
STATES = ("open", "confirmed", "rejected")


class ChannelRefused(ValueError):
    """A post or a change the channel does not take, with the reason."""


def _blank() -> dict[str, Any]:
    return {"schema": "rihmasto.agent_channel/1", "messages": [], "paused": None}


def read(project: Any) -> dict[str, Any]:
    """The whole channel: its messages and whether it is paused."""
    found = project.read(FILE, None)
    return found if isinstance(found, dict) else _blank()


def _when(stamp: Any) -> dt.datetime | None:
    if not stamp:            # a message without a time sorts as unknown, never as now
        return None
    try:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def messages(project: Any, *, since: str | None = None, thread: str | None = None, held: bool = True,
             limit: int = 200) -> list[dict[str, Any]]:
    """The messages after ``since`` (a message id such as M-0007, or a time), in one thread or all, oldest first."""
    rows = read(project)["messages"]
    if thread:
        rows = [m for m in rows if m["thread"] == thread]
    if not held:
        rows = [m for m in rows if not m.get("held")]
    if since:
        if re.fullmatch(r"M-\d{1,9}", since):
            n = int(since[2:])
            rows = [m for m in rows if int(m["id"][2:]) > n]
        else:
            at = _when(since)
            if at is None:
                raise ChannelRefused(f"since is a message id (M-0007) or a time (2026-11-24T10:00:00Z), not {since!r}")
            rows = [m for m in rows if (_when(m["at"]) or at) > at]
    return rows[-limit:]


def get(project: Any, mid: str) -> dict[str, Any]:
    found = next((m for m in read(project)["messages"] if m["id"] == mid), None)
    if found is None:
        raise ChannelRefused(f"no message {mid} in the channel of {project.pid}")
    return found


# -- who posts ------------------------------------------------------------------------------------------

def person(name: str, persona: str) -> dict[str, Any]:
    return {"kind": "person", "name": name, "persona": persona}


def agent(name: str, operator: str, persona: str, harness: str | None = None) -> dict[str, Any]:
    return {"kind": "agent", "name": name, "operator": operator, "persona": persona, "harness": harness or name}


def rihma(role: str) -> dict[str, Any]:
    return {"kind": "rihma", "name": "Rihma", "role": role}


SYSTEM = {"kind": "system", "name": "Rihmasto"}


def _signs(a: dict[str, Any], key: str) -> bool:
    """Whether ``a[key]`` names a person and ``a`` a persona."""
    return is_person(str(a.get(key) or "")) and a.get("persona") in PERSONAS


# Each author kind's rule: None when it holds, else why not.
_AUTHOR_RULES = {
    "person": lambda a: None if _signs(a, "name") else
    f"{a.get('name')!r} is not a person with a persona: a post is signed by a named person",
    "agent": lambda a: ("an agent's name is lower-case letters, digits, dots and hyphens (claude-code)"
                        if not NAME.match(str(a.get("name") or "").lower()) else None if _signs(a, "operator") else
                        "an agent posts for a named operator, a person with a persona, who signs for it"),
    "rihma": lambda a: None if a.get("role") in RIHMA_ROLES else
    f"a Rihma agent posts in one of the roles {', '.join(RIHMA_ROLES)}; the holdout author never posts here",
    "automation": lambda a: None if is_person(str(a.get("operator") or "")) else
    "an automation posts for its owner, a named person",
    "system": lambda a: None,
}


def _checked_author(a: Any) -> dict[str, Any]:
    if not isinstance(a, dict) or a.get("kind") not in AUTHOR_KINDS:
        raise ChannelRefused(f"an author is one of {', '.join(AUTHOR_KINDS)}")
    why = _AUTHOR_RULES[a["kind"]](a)
    if why:
        raise ChannelRefused(why)
    return {k: v for k, v in a.items() if v is not None}


def _refs(refs: Any) -> dict[str, Any]:
    if refs is None:
        return {}
    if not isinstance(refs, dict) or set(refs) - set(REF_KEYS):
        raise ChannelRefused(f"refs is an object of {', '.join(REF_KEYS)}")
    out: dict[str, Any] = {}
    for k, v in refs.items():
        if k in ("message", "gate"):
            out[k] = str(v)[:200]
            continue
        items = v if isinstance(v, list) else [v]
        out[k] = [str(x)[:300] for x in items if str(x).strip()][:MAX_REFS]
    return out


def _signer(a: dict[str, Any]) -> dict[str, Any]:
    """What the ledger records of the author: who, never the text."""
    rec = {"author_kind": a["kind"], "author": a.get("name")}
    for k in ("operator", "persona", "role", "harness"):
        if a.get(k):
            rec[k] = a[k]
    person_name = a["name"] if a["kind"] == "person" else a.get("operator")
    return rec | ({"person": person_name} if person_name else {})


def _checked_post(kind: str, text: str, thread: str | None, state: str | None) -> tuple[str, str]:
    """The message's text and thread as kept, or why it is refused."""
    text = str(text or "").strip()
    thread = (thread or MAIN).strip().lower()
    why = (f"a message's kind is one of {', '.join(KINDS)}" if kind not in KINDS else
           "the message is empty" if not text else
           f"a message is at most {MAX_TEXT} characters" if len(text) > MAX_TEXT else
           "a thread is lower-case letters, digits and hyphens (main, drive-sync)" if not THREAD.match(thread) else
           f"a proposal's state is one of {', '.join(STATES)}" if state is not None and state not in STATES else None)
    if why:
        raise ChannelRefused(why)
    return text, thread


def post(project: Any, *, author: dict[str, Any], kind: str, text: str, thread: str | None = None,
         refs: dict[str, Any] | None = None, state: str | None = None, trace: dict[str, Any] | None = None,
         ask: bool = False, actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Add one message. An external agent's post waits (held) while a person has paused the channel. ``actions``:
    a Rihma answer's next steps as buttons (kernel/channel_consult.py)."""
    a = _checked_author(author)
    text, thread = _checked_post(kind, text, thread, state)
    acts = [x for x in actions or [] if isinstance(x, dict) and x.get("label")][:6] if a["kind"] == "rihma" else []
    extra = {k: v for k, v in (("state", state), ("trace", trace), ("ask", ask or None), ("actions", acts)) if v}
    with updating_json(project.path(FILE), _blank()) as doc:
        n = int(doc["messages"][-1]["id"][2:]) + 1 if doc["messages"] else 1
        held = {"held": True} if doc.get("paused") and a["kind"] == "agent" else {}
        msg = {"id": f"M-{n:04d}", "thread": thread, "at": project.factory.clock.stamp(), "author": a, "kind": kind,
               "text": text, "refs": _refs(refs), "to": sorted({m.lower() for m in MENTION.findall(text)}), **extra,
               **held}
        doc["messages"].append(msg)
    project.log("channel_posted", {"id": msg["id"], "thread": thread, "kind": kind, **_signer(a), **held})
    return msg


# -- a person steps in ----------------------------------------------------------------------------------

def _person_signs(name: str, persona: str) -> None:
    if not is_person(name) or persona not in PERSONAS:
        raise ChannelRefused(f"{name!r} is not a person with a persona: a person signs it")


def settle(project: Any, mid: str, *, verdict: str, person_name: str, persona: str, note: str = "") -> dict[str, Any]:
    """A person confirms or rejects a proposal in the channel. What confirming does (answering the question) is the
    caller's, through the kernel's own path, before this records the verdict."""
    _person_signs(person_name, persona)
    if verdict not in ("confirm", "reject"):
        raise ChannelRefused("a proposal is confirmed or rejected")
    with updating_json(project.path(FILE), _blank()) as doc:
        msg = next((m for m in doc["messages"] if m["id"] == mid), None)
        if msg is None or msg["kind"] != "proposal":
            raise ChannelRefused(f"{mid} is not a proposal in the channel")
        if msg.get("state") != "open":
            raise ChannelRefused(f"{mid} is already {msg.get('state')}")
        msg["state"] = "confirmed" if verdict == "confirm" else "rejected"
        msg["settled"] = {"person": person_name, "persona": persona, "at": project.factory.clock.stamp(),
                          "note": note[:500]}
    project.log("channel_settled", {"id": mid, "verdict": msg["state"], "person": person_name, "persona": persona})
    return msg


def pause(project: Any, *, person_name: str, persona: str, reason: str = "") -> dict[str, Any]:
    """Agents' posts wait, and Rihma answers none, until a person resumes the channel."""
    _person_signs(person_name, persona)
    with updating_json(project.path(FILE), _blank()) as doc:
        if doc.get("paused"):
            raise ChannelRefused(f"the channel is already paused by {doc['paused']['person']}")
        doc["paused"] = {"person": person_name, "persona": persona, "at": project.factory.clock.stamp(),
                         "reason": reason[:500]}
    project.log("channel_paused", {"person": person_name, "persona": persona, "reason": reason[:500]})
    return read(project)["paused"]


def resume(project: Any, *, person_name: str, persona: str) -> list[dict[str, Any]]:
    """Resume the channel: the posts that waited are let through, in order. Returns them."""
    _person_signs(person_name, persona)
    with updating_json(project.path(FILE), _blank()) as doc:
        if not doc.get("paused"):
            raise ChannelRefused("the channel is not paused")
        doc["paused"] = None
        released = [m for m in doc["messages"] if m.get("held")]
        for m in released:
            m.pop("held", None)
            m["released"] = project.factory.clock.stamp()
    project.log("channel_resumed", {"person": person_name, "persona": persona, "released": [m["id"] for m in released]})
    return released


# -- watching -------------------------------------------------------------------------------------------

def who(m: dict[str, Any]) -> str:
    """An author as the cockpit and the terminal show it: "claude-code for Aino", "Rihma (analyst)"."""
    a = m["author"]
    if a["kind"] == "agent":
        return f"{a['name']} for {a['operator']}"
    if a["kind"] == "rihma":
        return f"Rihma ({a['role']})"
    if a["kind"] == "automation":
        return f"{a.get('name')} for {a.get('operator')}"
    return str(a.get("name"))


def summary(project: Any) -> dict[str, Any] | None:
    """One project's line in the Agent activity monitor, or None when its channel is empty."""
    doc = read(project)
    rows = doc["messages"]
    if not rows:
        return None
    last = rows[-1]
    recent = rows[-50:]
    return {"project": project.pid, "title": project.meta.get("title"), "messages": len(rows),
            "last": {"id": last["id"], "at": last["at"], "who": who(last), "kind": last["kind"],
                     "text": last["text"][:160], "author_kind": last["author"]["kind"]},
            "talking": sorted({who(m) for m in recent if m["author"]["kind"] in ("agent", "rihma", "person")}),
            "agents": sorted({m["author"]["name"] for m in recent if m["author"]["kind"] == "agent"}),
            "proposals_waiting": [m["id"] for m in rows if m["kind"] == "proposal" and m.get("state") == "open"],
            "held": len([m for m in rows if m.get("held")]), "paused": doc.get("paused")}


def monitor(factory: Any) -> dict[str, Any]:
    """Every project whose channel has messages, the latest first: who is talking, the last message, what waits."""
    rows = [s for p in factory.projects() if not p.pid.startswith("_") for s in [summary(p)] if s]
    rows.sort(key=lambda s: s["last"]["at"], reverse=True)
    return {"channels": rows, "waiting": sum(len(s["proposals_waiting"]) for s in rows)}


def counts(factory: Any, pid: str | None = None, since: str | None = None) -> dict[str, Any]:
    """How much the channels carried, for Insights and Review: messages by author kind and by kind."""
    by_author: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    projects = [factory.project(pid)] if pid else [p for p in factory.projects() if not p.pid.startswith("_")]
    for p in projects:
        for m in messages(p, since=since, limit=100000):
            by_author[m["author"]["kind"]] = by_author.get(m["author"]["kind"], 0) + 1
            by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
    return {"by_author": by_author, "by_kind": by_kind, "total": sum(by_kind.values())}
