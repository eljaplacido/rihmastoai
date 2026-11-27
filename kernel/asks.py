"""Asks between agents and machines (FR-XAG1): a question to a named agent, carried there and answered back.

The owner (2026-11-27): "this back and forth that I'm now doing and copy pasting from a place to another will be
helped by Rihmasto"; "when these situations occur in the future, whether it's in terminal or chat or moving back and
forth, this should happen in Rihmasto, not going elsewhere."

An ask is a question a named person puts to a named agent (``claude-code``), optionally on a named machine
(kernel/machines.py), about one project: its words, why it is asked and the answer expected. It is a question in the
project's agent channel addressed to that agent (``@claude-code …``), so the channel shows it and its answer in one
thread, and a record here (``asks.json``) with its id (``AK-0001``), the channel message, whom it is to, its state
and how it was delivered. Its state is read from the channel, never kept twice:

- **open**: put, not yet answered (an agent on this machine sees it in the channel over MCP); **delivered** once
  the person copied it for the other agent, or its reply link was opened;
- **answered**: a reply to its message (``reply_to`` / refs.message) from the agent, filed by the agent over MCP,
  through its reply link, or pasted back by the person;
- **expired** past its expiry (7 days unless said, at most 30), **withdrawn** by a person.

It reaches the agent three ways, all ending in the same thread:

1. an agent on this machine reads it over MCP (``rihma_channel_read`` lists it under ``asked_agents``) and answers
   with ``rihma_channel_post`` and ``reply_to``;
2. an agent elsewhere gets a **reply link** the person makes (one per ask, shown once, only its sha256 kept, expiring,
   one answer): ``POST /x/api/ask`` reads the ask, ``POST /x/api/answer`` files the answer (kernel/ask_page.py). It
   reaches this machine only through the cockpit's one trusted https front (``--public-origin``); without one, the
   link works on this machine only, and says so;
3. always: **Copy for the other agent** gives one self-contained message (what to do, why, how to answer, the ask's
   id), and **Paste the answer** files what came back.

Every write is signed by a named person; the ledger records ids, whom and how, never the words.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets
from typing import Any

from kernel import agent_channel as ch
from kernel import machines
from kernel.canon import DecisionRefused
from kernel.learn import FACTORY_PID, factory_project
from kernel.people import PERSONAS, is_person
from kernel.store import read_json, updating_json

FILE = "asks.json"
LINKS = "ask_links.json"              # factory-wide: a reply link is found by its hash alone
LINK_PATH = "/x/"
DEFAULT_DAYS = 7
MAX_DAYS = 30
LINK_HOURS = 24
MAX_LINK_HOURS = 24 * 7
MAX_OPEN = 20                         # open asks in one project: more waits until some are answered or withdrawn
WHY_LIMIT, EXPECTS_LIMIT, TEXT_LIMIT = 300, 300, 4000
STATES = ("open", "delivered", "answered", "expired", "withdrawn")
HOW = ("copy", "link")
_TOKEN = re.compile(r"xa_[A-Za-z0-9_-]{20,80}\Z")


class AskRefused(ValueError):
    """An ask, or a change to one, that is not taken, with the reason."""


def _now(factory: Any) -> dt.datetime:
    return dt.datetime.fromisoformat(factory.clock.stamp().replace("Z", "+00:00"))


def _stamp(at: dt.datetime) -> str:
    return at.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _when(stamp: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) if stamp else None
    except ValueError:
        return None


def _signed(person: str, persona: str, what: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: {what} is signed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"{persona!r} is not a persona")


def _records(project: Any) -> list[dict[str, Any]]:
    return read_json(project.path(FILE), {"asks": []}).get("asks") or []


def _answers(project: Any) -> dict[str, dict[str, Any]]:
    """The channel's replies, by the message they answer: the first reply from an agent wins."""
    out: dict[str, dict[str, Any]] = {}
    for m in ch.read(project).get("messages") or []:
        ref = (m.get("refs") or {}).get("message")
        if m["author"]["kind"] == "agent" and isinstance(ref, str) and ref not in out:
            out[ref] = m
    return out


def state_of(project: Any, rec: dict[str, Any], answers: dict[str, dict[str, Any]] | None = None) -> str:
    answers = _answers(project) if answers is None else answers
    if rec["message"] in answers:
        return "answered"
    if rec.get("withdrawn"):
        return "withdrawn"
    until = _when(rec.get("expires"))
    if until is not None and _now(project.factory) >= until:
        return "expired"
    return "delivered" if rec.get("delivered") else "open"


def _view(project: Any, rec: dict[str, Any], msgs: dict[str, dict[str, Any]],
          answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    msg = msgs.get(rec["message"]) or {}
    ans = answers.get(rec["message"])
    out = {k: rec.get(k) for k in ("id", "message", "to", "machine", "why", "expects", "by", "persona", "at",
                                   "expires", "source")}
    out.update({"project": project.pid, "title": project.meta.get("title") or project.pid,
                "text": _question(msg.get("text") or "", rec["to"]), "state": state_of(project, rec, answers),
                "delivered": rec.get("delivered") or [], "link": _link_public(rec.get("link"))})
    if ans:
        out["answer"] = {"id": ans["id"], "at": ans["at"], "text": ans["text"],
                         "via": (ans.get("trace") or {}).get("via") or "mcp"}
    return out


def _question(text: str, to: str) -> str:
    return re.sub(rf"^@{re.escape(to)}\s+", "", text.strip())


def _link_public(link: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"id": link["id"], "expires": link["expires"]} if link else None


def listed(project: Any, *, state: str | None = None) -> list[dict[str, Any]]:
    """The project's asks, newest first, each with its state and (once answered) the answer."""
    msgs = {m["id"]: m for m in ch.read(project).get("messages") or []}
    answers = _answers(project)
    rows = [_view(project, r, msgs, answers) for r in _records(project)]
    rows = [r for r in rows if state is None or r["state"] == state]
    return sorted(rows, key=lambda r: r["at"], reverse=True)


def get(project: Any, aid: str) -> dict[str, Any]:
    row = next((r for r in listed(project) if r["id"] == str(aid).strip().upper()), None)
    if row is None:
        raise AskRefused(f"{project.pid} has no ask {aid!r}")
    return row


def waiting(factory: Any) -> list[dict[str, Any]]:
    """What the person waits on from other agents, across projects: the asks open or delivered, oldest first."""
    rows = [r for p in factory.projects() if p.pid != FACTORY_PID
            for r in listed(p) if r["state"] in ("open", "delivered")]
    return sorted(rows, key=lambda r: r["at"])


def summary(factory: Any) -> dict[str, Any]:
    rows = waiting(factory)
    said = ("Nothing waits on another agent." if not rows else
            f"{len(rows)} ask(s) wait on other agents: " + "; ".join(
                f"{r['id']} to {r['to']}{' on ' + r['machine'] if r.get('machine') else ''} ({r['title']}, "
                f"{r['state']})" for r in rows[:5]) + ("" if len(rows) <= 5 else f"; and {len(rows) - 5} more"))
    return {"asks": rows, "said": said}


# -- writes ---------------------------------------------------------------------------------------------------

def _clean(value: Any, limit: int, what: str, *, required: bool = False) -> str:
    text = " ".join(str(value or "").split()) if what != "text" else str(value or "").strip()
    if required and not text:
        raise AskRefused(f"an ask needs its {what}")
    if len(text) > limit:
        raise AskRefused(f"an ask's {what} is at most {limit} characters")
    return text


def create(project: Any, *, to: str, text: str, why: str = "", expects: str = "", machine: str | None = None,
           days: int | None = None, source: dict[str, Any] | None = None, person: str, persona: str
           ) -> dict[str, Any]:
    """Put a question to a named agent (on a named machine), signed: it is posted in the project's agent channel."""
    _signed(person, persona, "an ask")
    agent = str(to or "").strip().lower()
    if not ch.NAME.match(agent):
        raise AskRefused("an ask is to a named agent (claude-code, codex, cursor, or a name you give it)")
    words = _clean(text, TEXT_LIMIT, "text", required=True)
    place = None
    if machine:
        m = machines.get(project.factory, machine)
        if m is None:
            raise AskRefused(f"there is no machine {machine!r}: add it in Settings > Machines first")
        place = m["name"]
    life = int(days or DEFAULT_DAYS)
    if not 1 <= life <= MAX_DAYS:
        raise AskRefused(f"an ask stays open 1 to {MAX_DAYS} days")
    if sum(1 for r in listed(project) if r["state"] in ("open", "delivered")) >= MAX_OPEN:
        raise AskRefused(f"{project.pid} already has {MAX_OPEN} asks waiting: settle some first")
    msg = ch.post(project, author=ch.person(person, persona), kind="question", text=f"@{agent} {words}", ask=True)
    now = _now(project.factory)
    rec = {"message": msg["id"], "to": agent, "machine": place, "why": _clean(why, WHY_LIMIT, "why"),
           "expects": _clean(expects, EXPECTS_LIMIT, "expected answer"), "by": person, "persona": persona,
           "at": _stamp(now), "expires": _stamp(now + dt.timedelta(days=life)),
           "source": source if isinstance(source, dict) else None, "delivered": []}
    with updating_json(project.path(FILE), {"asks": []}) as doc:
        rows = doc.setdefault("asks", [])
        rec["id"] = f"AK-{len(rows) + 1:04d}"
        rows.append(rec)
    project.log("ask_created", {"ask": rec["id"], "message": msg["id"], "to": agent, "machine": place,
                                "person": person, "persona": persona})
    return {"ask": get(project, rec["id"]),
            "said": f"{rec['id']} asked {agent}{' on ' + place if place else ''}. It waits in the agent channel; "
                    f"an agent here reads it over MCP, or copy it for the other agent."}


def _update(project: Any, aid: str, change: Any) -> dict[str, Any]:
    key = str(aid).strip().upper()
    with updating_json(project.path(FILE), {"asks": []}) as doc:
        rec = next((r for r in doc.setdefault("asks", []) if r["id"] == key), None)
        if rec is None:
            raise AskRefused(f"{project.pid} has no ask {aid!r}")
        change(rec)
        return dict(rec)


def _settled(project: Any, aid: str) -> dict[str, Any]:
    row = get(project, aid)
    if row["state"] in ("answered", "expired", "withdrawn"):
        raise AskRefused(f"{row['id']} is {row['state']}: it takes nothing more")
    return row


def mark_delivered(project: Any, aid: str, how: str, *, by: str | None = None) -> None:
    if how not in HOW:
        raise AskRefused(f"delivered by one of {', '.join(HOW)}")
    stamp = project.factory.clock.stamp()

    def note(rec: dict[str, Any]) -> None:
        if not any(d.get("how") == how for d in rec.setdefault("delivered", [])):
            rec["delivered"].append({"how": how, "at": stamp, **({"by": by} if by else {})})
    _update(project, aid, note)
    project.log("ask_delivered", {"ask": str(aid).upper(), "how": how, **({"person": by} if by else {})})


def copy_text(project: Any, aid: str, *, person: str, persona: str, base: str | None = None) -> dict[str, Any]:
    """One self-contained message for the other agent, and the ask counted as delivered by copy."""
    _signed(person, persona, "copying an ask")
    row = _settled(project, aid)
    how = (f"Answer with your result in one message. The person pastes it into Rihmasto under {row['id']} "
           f"(Paste the answer).")
    lines = [f"Rihmasto ask {row['id']} from {row['by']} about the project {row['title']}"
             + (f", for the agent on {row['machine']}" if row.get("machine") else "") + ":", "", row["text"], ""]
    if row.get("why"):
        lines.append(f"Why: {row['why']}")
    if row.get("expects"):
        lines.append(f"Answer with: {row['expects']}")
    lines.append(f"How to answer: {how}")
    mark_delivered(project, row["id"], "copy", by=person)
    return {"ask": row["id"], "text": "\n".join(lines), "said": f"{row['id']} copied: paste it to the other agent."}


def answer(project: Any, aid: str, text: str, *, person: str, persona: str, via: str = "paste") -> dict[str, Any]:
    """File the answer that came back for an ask (pasted by the person, or through its reply link): a reply in the
    channel from the agent asked, which the person vouches for, marked with how it came."""
    _signed(person, persona, "filing an answer")
    row = _settled(project, aid)
    words = _clean(text, ch.MAX_TEXT, "text", required=True)
    author = ch.agent(row["to"], person, persona, harness=f"{row['to']} ({'pasted' if via == 'paste' else via})")
    msg = ch.post(project, author=author, kind="answer", text=words, refs={"message": row["message"]},
                  trace={"via": via, "ask": row["id"]})
    project.log("ask_answered", {"ask": row["id"], "message": msg["id"], "via": via, "person": person,
                                 "persona": persona})
    return {"ask": get(project, row["id"]), "said": f"{row['id']} answered ({via}); it is in the agent channel."}


def withdraw(project: Any, aid: str, *, person: str, persona: str, why: str = "") -> dict[str, Any]:
    _signed(person, persona, "withdrawing an ask")
    row = _settled(project, aid)
    stamp = project.factory.clock.stamp()
    _update(project, row["id"], lambda r: r.update(withdrawn={"by": person, "at": stamp}, link=None))
    _drop_link(project.factory, row["id"], project.pid)
    project.log("ask_withdrawn", {"ask": row["id"], "person": person, "persona": persona})
    return {"ask": get(project, row["id"]), "said": f"{row['id']} withdrawn."}


# -- reply links ----------------------------------------------------------------------------------------------

def _links_path(factory: Any) -> Any:
    return factory_project(factory).path(LINKS)


def _drop_link(factory: Any, aid: str, pid: str) -> None:
    with updating_json(_links_path(factory), {"links": []}) as doc:
        doc["links"] = [x for x in doc.setdefault("links", []) if not (x["ask"] == aid and x["project"] == pid)]


def reply_link(project: Any, aid: str, *, person: str, persona: str, base: str, hours: int | None = None,
               local: bool = True) -> dict[str, Any]:
    """A link the agent elsewhere answers through: shown once, only its sha256 kept, one answer, expiring."""
    _signed(person, persona, "a reply link")
    row = _settled(project, aid)
    life = int(hours or LINK_HOURS)
    if not 1 <= life <= MAX_LINK_HOURS:
        raise AskRefused(f"a reply link lasts 1 to {MAX_LINK_HOURS} hours")
    token = "xa_" + secrets.token_urlsafe(32)
    expires = _stamp(_now(project.factory) + dt.timedelta(hours=life))
    link = {"id": f"XL-{secrets.token_hex(3)}", "expires": expires}
    _drop_link(project.factory, row["id"], project.pid)
    with updating_json(_links_path(project.factory), {"links": []}) as doc:
        doc.setdefault("links", []).append({"sha": hashlib.sha256(token.encode()).hexdigest(), "project": project.pid,
                                            "ask": row["id"], "expires": expires, "id": link["id"]})
    _update(project, row["id"], lambda r: r.update(link=link))
    project.log("ask_link_made", {"ask": row["id"], "link": link["id"], "hours": life, "person": person,
                                  "persona": persona})
    url = base.rstrip("/") + LINK_PATH
    how = (f"curl -s -X POST {url}api/ask -H 'Content-Type: application/json' -d '{{\"token\": \"{token}\"}}'\n"
           f"curl -s -X POST {url}api/answer -H 'Content-Type: application/json' "
           f"-d '{{\"token\": \"{token}\", \"answer\": \"<your answer>\"}}'")
    return {"ask": row["id"], "link": link, "token": token, "url": url, "how": how, "local_only": local,
            "said": (f"Reply link for {row['id']} made; it is shown once and lasts {life} hours."
                     + (" It points at this computer only: set the cockpit's trusted https front "
                        "(--public-origin) so an agent elsewhere can reach it." if local else ""))}


def redeem(factory: Any, token: str) -> tuple[Any, dict[str, Any]]:
    """The project and the ask a reply link's token opens, or AskRefused. Comparing hashes in constant time."""
    if not _TOKEN.match(str(token or "")):
        raise AskRefused("this reply link is not valid")
    want = hashlib.sha256(token.encode()).hexdigest()
    rows = read_json(_links_path(factory), {"links": []}).get("links") or []
    link = next((x for x in rows if hmac.compare_digest(x["sha"], want)), None)
    if link is None:
        raise AskRefused("this reply link is not valid, or its ask is settled: ask the person for a new one")
    until = _when(link["expires"])
    if until is None or _now(factory) >= until:
        raise AskRefused("this reply link has expired: ask the person for a new one")
    project = factory.project(link["project"])
    row = get(project, link["ask"])
    if row["state"] in ("answered", "expired", "withdrawn"):
        raise AskRefused(f"{row['id']} is {row['state']}: this link takes nothing more")
    return project, row


def read_by_link(factory: Any, token: str) -> dict[str, Any]:
    project, row = redeem(factory, token)
    mark_delivered(project, row["id"], "link")
    return {"ask": row["id"], "project": row["title"], "to": row["to"], "machine": row.get("machine"),
            "text": row["text"], "why": row.get("why"), "expects": row.get("expects"), "from": row["by"],
            "how": "POST your answer as JSON {\"token\": ..., \"answer\": ...} to api/answer beside this address; "
                   "one answer per link."}


def answer_by_link(factory: Any, token: str, text: str) -> dict[str, Any]:
    project, row = redeem(factory, token)
    rec = next(r for r in _records(project) if r["id"] == row["id"])
    answer(project, row["id"], text, person=rec["by"], persona=rec["persona"], via="link")
    _drop_link(factory, row["id"], project.pid)
    _update(project, row["id"], lambda r: r.update(link=None))
    return {"ask": row["id"], "said": f"Thank you: {row['id']} is answered."}
