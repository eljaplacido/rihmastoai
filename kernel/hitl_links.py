"""A reviewer outside the system (FR-HITL1): a one-use link to a page with only the asks put to them.

The owner (2026-11-25): "Even the ones who are outside the system could have just one chat and feed coming from
Rihmasto for them to simply just answer the questions and feedback ... temporary login links."

A person inside (a product owner, a business owner, IT or compliance) gives a named person outside a **link** for
some of a project's open asks, with the persona their answers are recorded as (a compliance reviewer, say) and a
role in words ("External legal counsel"). The link:

- is shown once: only its sha256 is kept, with an expiry (72 hours unless said, at most 30 days);
- is **one use**: opening it exchanges it for a session that lasts until the link's expiry, kept in that browser
  tab only. Opened again, it is refused, and the page says to ask for a new one (a nudge sends one);
- carries its token after ``#``: a browser never sends that part to a server, a log or a link preview;
- opens a page (kernel/hitl_page.py) that shows only those asks: their words, options and the asker's name. No
  other ask, no other project, no project record;
- records every answer signed with the person's name and the recorded persona, marked as from outside and
  naming the link (kernel/hitl.py ``answer``);
- is revoked with one call; a revoke ends its session at once.

Links are kept factory-wide (``_factory/hitl_links.json``) so the public page finds one by its hash alone; each
names its project, and nothing of another project is reachable from it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets
from typing import Any

from kernel import hitl
from kernel.canon import DecisionRefused
from kernel.learn import FACTORY_PID
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, Project, read_json, updating_json

CREATORS = ("product_owner", "business_owner", "it", "compliance")
DEFAULT_HOURS = 72
MAX_HOURS = 24 * 30
CHANNELS = ("copy", "email", "whatsapp", "teams", "slack")
FILE = "hitl_links.json"
PAGE_PATH = "/r/"
_TOKEN = re.compile(r"r[vs]_[A-Za-z0-9_-]{20,80}\Z")
_PHONE = re.compile(r"\+[1-9]\d{6,14}\Z")
_MAIL = re.compile(r"[^@\s<>,]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}\Z")


class LinkRefused(PermissionError):
    """A link or a session the page does not take: the words say what to do instead."""


def _path(factory: Factory) -> Any:
    return factory.projects_dir / FACTORY_PID / FILE


def links(factory: Factory, project: str | None = None) -> list[dict[str, Any]]:
    rows = read_json(_path(factory), None) or []
    return [r for r in rows if project is None or r.get("project") == project]


def _sha(token: str) -> str:
    """A link's or a session's hash: the only form either is kept in."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _now(factory: Factory) -> dt.datetime:
    return factory.clock.now()


def _stamp(at: dt.datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _expired(factory: Factory, link: dict[str, Any]) -> bool:
    try:
        ends = dt.datetime.fromisoformat(str(link["expires"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return True
    return _now(factory) >= ends


def state_of(factory: Factory, link: dict[str, Any]) -> str:
    """active (not opened yet), opened, revoked or expired."""
    if link.get("state") == "revoked":
        return "revoked"
    return "expired" if _expired(factory, link) else str(link.get("state") or "active")


def public(factory: Factory, link: dict[str, Any]) -> dict[str, Any]:
    """A link as the cockpit shows it: never its hash, its session or its contact's address."""
    keep = ("id", "project", "asks", "name", "persona", "role", "expires", "created_by", "created_persona", "at",
            "opened_at", "context")
    return {k: link.get(k) for k in keep} | {"state": state_of(factory, link),
                                              "channel": (link.get("contact") or {}).get("channel", "copy")}


def _contact(channel: str, address: str | None) -> dict[str, Any]:
    if channel not in CHANNELS:
        raise ValueError(f"a link is sent by {', '.join(CHANNELS)}")
    address = str(address or "").strip()
    if channel == "whatsapp" and not _PHONE.match(address):
        raise ValueError("a WhatsApp number is written in full with its country code, like +358401234567")
    if channel == "email" and not _MAIL.match(address):
        raise ValueError("an email link needs the person's address, like name@example.org")
    if channel in ("teams", "slack") and not re.fullmatch(r"SUB-\d{3,6}", address):
        raise ValueError(f"a {channel} link names the relay subscription it goes through (SUB-001)")
    return {"channel": channel, "address": address or None}


def _checked(project: Project, name: str, persona: str, ask_ids: list[str]) -> list[str]:
    if not is_person(name):
        raise ValueError("name the person outside the system: their answers are signed with that name")
    if persona not in PERSONAS:
        raise ValueError(f"the persona their answers are recorded as is one of {', '.join(PERSONAS)}")
    open_asks = {a["id"]: a for a in hitl.asks(project, state="open")}
    ids = list(dict.fromkeys(str(a) for a in ask_ids or []))
    if not ids:
        raise ValueError("choose at least one open ask for them to answer")
    missing = [a for a in ids if a not in open_asks]
    if missing:
        raise ValueError(f"not open in {project.pid}: {', '.join(missing)} (only open asks go on a link)")
    other = [a for a in ids if open_asks[a]["to"]["persona"] != persona]
    if other:
        raise ValueError(f"{', '.join(other)} is put to another persona: a link for a {persona.replace('_', ' ')} "
                         "carries only the asks put to that persona")
    return ids


def persona_for(project: Project, ask_ids: list[str]) -> str | None:
    """The persona the first of these asks is put to: a link records its answers as that persona."""
    found = {a["id"]: a for a in hitl.asks(project)}
    first = next((found[a] for a in ask_ids or [] if a in found), None)
    return first["to"]["persona"] if first else None


def create(project: Project, *, name: str, persona: str, asks: list[str], person: str, creator_persona: str,
           role: str = "", hours: int = DEFAULT_HOURS, channel: str = "copy", address: str | None = None,
           context: str = "") -> dict[str, Any]:
    """A one-use link for a named person outside. Returns the record with ``token``, never kept or shown again."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a link is given by a named person")
    if creator_persona not in CREATORS:
        raise DecisionRefused(f"a {creator_persona} does not give links to people outside: {', '.join(CREATORS)} do")
    name = str(name or "").strip()[:120]
    ids = _checked(project, name, persona, asks)
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"a link lasts 1 to {MAX_HOURS} hours")
    contact = _contact(channel, address)
    token = "rv_" + secrets.token_urlsafe(32)
    factory = project.factory
    with updating_json(_path(factory), []) as rows:
        n = max([int(r["id"].split("-")[1]) for r in rows], default=0) + 1
        link: dict[str, Any] = {
            "id": f"RL-{n:03d}", "project": project.pid, "asks": ids, "name": name, "persona": persona,
            "role": str(role or "").strip()[:120], "context": str(context or "").strip()[:120], "contact": contact,
            "link_sha256": _sha(token), "session_sha256": None, "state": "active",
            "expires": _stamp(_now(factory) + dt.timedelta(hours=hours)), "created_by": person,
            "created_persona": creator_persona, "at": factory.clock.stamp(), "opened_at": None}
        rows.append(link)
    hitl.address(project, ids, name=name, link_id=link["id"])
    project.log("hitl_link_given", {"link": link["id"], "asks": ids, "to_person": name, "to_persona": persona,
                                    "channel": contact["channel"], "expires": link["expires"], "person": person,
                                    "persona": creator_persona})
    return {**link, "token": token}


def revoke(project: Project, link_id: str, *, person: str, persona: str, why: str = "revoked") -> dict[str, Any]:
    """End a link and its session at once."""
    if not is_person(person) or persona not in CREATORS:
        raise DecisionRefused(f"a link is revoked by a named {', '.join(CREATORS)}")
    with updating_json(_path(project.factory), []) as rows:
        link = next((r for r in rows if r["id"] == link_id and r["project"] == project.pid), None)
        if link is None:
            raise KeyError(f"no link {link_id} in {project.pid}")
        link.update(state="revoked", revoked_by=person, revoked_at=project.factory.clock.stamp())   # its session ends
    back = hitl.unaddress(project, link_id)      # the asks go back to the persona inside: a withdrawal sticks
    project.log("hitl_link_revoked", {"link": link_id, "why": why[:200], "asks_back": back, "person": person,
                                      "persona": persona})
    return public(project.factory, link)


def again(project: Project, link_id: str, *, person: str, persona: str) -> dict[str, Any]:
    """A fresh link for the same person and the asks still open on the old one (a nudge sends it); the old one ends."""
    old = next((r for r in links(project.factory, project.pid) if r["id"] == link_id), None)
    if old is None:
        raise KeyError(f"no link {link_id} in {project.pid}")
    still = [a["id"] for a in hitl.asks(project, state="open") if a["id"] in old["asks"]]
    if not still:
        raise ValueError(f"every ask on {link_id} is answered: no new link is needed")
    revoke(project, link_id, person=person, persona=persona, why="a new link was sent")
    contact = old.get("contact") or {}
    return create(project, name=old["name"], persona=old["persona"], asks=still, person=person,
                  creator_persona=persona, role=old.get("role", ""), channel=contact.get("channel", "copy"),
                  address=contact.get("address"), context=old.get("context", ""))


def url(base: str, token: str) -> str:
    """The address the person opens: the token after #, so no server, log or preview ever receives it."""
    return base.rstrip("/") + PAGE_PATH + "#" + token


def local_only(base: str) -> bool:
    """Whether links made on this base point at this machine only (127.0.0.1, localhost, ::1): nobody outside
    reaches them (FR-HITL2)."""
    from urllib.parse import urlsplit

    host = (urlsplit(str(base or "")).hostname or "").lower()
    return host in ("localhost", "::1", "0.0.0.0", "") or host.startswith("127.") or host.endswith(".localhost")


LOCAL_WARNING = ("This link points at this computer only, so nobody outside can open it. IT sets where outside "
                 "links point in People in the loop, Channels (Where outside links point), for example the embed "
                 "server's public address behind TLS.")


# -- the page's side: open once, then a session -----------------------------------------------------------

def _find(rows: list[dict[str, Any]], key: str, token: str) -> dict[str, Any] | None:
    if not _TOKEN.match(str(token or "")):
        return None
    digest = _sha(token)
    return next((r for r in rows if r.get(key) and hmac.compare_digest(str(r[key]), digest)), None)


def redeem(factory: Factory, token: str) -> dict[str, Any]:
    """Open a link: once. Returns {session, expires, link id}; LinkRefused says why not and what to do."""
    session = "rs_" + secrets.token_urlsafe(32)
    with updating_json(_path(factory), []) as rows:
        link = _find(rows, "link_sha256", token)
        if link is None:
            raise LinkRefused("This link is not valid. Ask the person who sent it for a new one.")
        why = _closed(factory, link)
        if why is None and link.get("state") == "opened":
            why = "This link was already opened. Links open once: ask " + link["created_by"] + " for a new one."
        if why:
            raise LinkRefused(why)
        link.update(state="opened", session_sha256=_sha(session), opened_at=factory.clock.stamp())
    factory.project(link["project"]).log("hitl_link_opened", {"link": link["id"], "to_person": link["name"]})
    return {"session": session, "expires": link["expires"], "link": link["id"]}


def _closed(factory: Factory, link: dict[str, Any]) -> str | None:
    state = state_of(factory, link)
    if state == "revoked":
        return f"This link was withdrawn by {link.get('revoked_by') or link['created_by']}. Ask them if you still " \
               "need to answer."
    if state == "expired":
        return f"This link has expired. Ask {link['created_by']} for a new one."
    return None


def session(factory: Factory, token: str) -> dict[str, Any]:
    """The link a page session belongs to, while it is open; LinkRefused otherwise."""
    link = _find(links(factory), "session_sha256", token)
    if link is None:
        raise LinkRefused("Your session has ended. Open the newest link you were sent, or ask for a new one.")
    why = _closed(factory, link)
    if why:
        raise LinkRefused(why)
    return link


def items(factory: Factory, link: dict[str, Any]) -> dict[str, Any]:
    """What the page shows: the asks on this link only, in their own words, and nothing else of the project."""
    project = factory.project(link["project"])
    mine = [a for a in hitl.asks(project) if a["id"] in link["asks"]]
    shown = [{"id": a["id"], "kind": a["kind"], "family": a["family"], "family_label": hitl.FAMILY_LABEL[a["family"]],
              "text": a["text"], "options": a["options"], "state": a["state"], "asked_by": a["by"],
              "answer": next((x["answer"] for x in a["answers"] if x.get("via") == link["id"]), None)}
             for a in mine]
    return {"name": link["name"], "role": link.get("role") or "", "context": link.get("context") or "",
            "from": link["created_by"], "expires": link["expires"], "items": shown,
            "open": sum(1 for i in shown if i["state"] == "open")}


def answer(factory: Factory, link: dict[str, Any], ask_id: str, said: str, comment: str = "") -> dict[str, Any]:
    """An answer from the page, signed as the link's person and persona; only an ask on this link."""
    if ask_id not in link["asks"]:
        raise LinkRefused("That question is not one of yours.")
    project = factory.project(link["project"])
    hitl.answer(project, ask_id, answer=said, comment=comment, person=link["name"], persona=link["persona"],
                external=True, via=link["id"])
    return items(factory, link)
