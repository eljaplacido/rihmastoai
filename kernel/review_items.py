"""The review's items (FR-REV1): their shape, who did each, and the two groups read from the canon.

An item is one thing a person may want to look at: an id that names its record (``<pid>/<kind>/<ref>``), a
group, a title, when it happened, who or what did it (``by``: a person, a persona, a Rihma agent's role, a
runner or harness, an automation, a delegation or an autopilot run), links to its record in the cockpit, and
the actions the person can take on it in place. Every action goes through a route that already exists and is
signed (deciding a card, answering, settling an assumption, revoking a delegation, reporting a change), or
through ``review_marked`` (kernel/review_marks.py). Nothing here writes.

- **Waiting on you:** the open Inbox cards the persona may decide, with their age; questions, approvals and
  go-ahead cards among them.
- **Decided for you:** the decisions a delegation or an autopilot run made in the person's name, and the
  assumptions the factory made, each with its due date, so the person can overturn them.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import quote

from kernel.canon import Canon

# The verdict "approve" (a) and "decline" (d) give on each kind of card; None: decide it in the Inbox.
APPROVE = {"approval": "approve", "validation": "accept", "deploy_gate": "approve", "change": "accept",
           "escalation": "retry", "concept": "validate", "update": "trial", "connector": "enable",
           "road": "configured", "trust": "granted", "incident": "acknowledge"}
DECLINE = {"approval": "reject", "deploy_gate": "refuse", "change": "reject", "escalation": "stop",
           "concept": "park", "update": "decline", "connector": "decline", "road": "declined", "trust": "declined"}
NEEDS_REASON = {("concept", "park")}
# What waits longest on people, and what stops the most, comes first.
CARD_RANK = {"incident": 0, "escalation": 1, "deploy_gate": 2, "approval": 3, "holdout_ruling": 4, "validation": 5,
             "change": 6, "trust": 7, "road": 7, "connector": 7, "update": 8, "concept": 8, "question": 9}
PERSON_KEYS = ("person", "by", "chosen_by", "requested_by", "stopped_by", "accepted_as_is_by")
VERDICT_DONE = {"assume": "Assumed", "approve": "Approved", "retry": "Retried"}


def href(pid: str, view: str, focus: str | None = None) -> str:
    """A cockpit address: a project's view, and the record in it."""
    return f"#/p/{quote(pid, safe='')}/{view}" + (f"/{quote(focus, safe='')}" if focus else "")


def action(do: str, label: str, *, key: str | None = None, path: str | None = None, body: dict | None = None,
           needs: str | None = None, prefill: str | None = None, link: str | None = None) -> dict[str, Any]:
    """One thing the person can do on an item: the route it posts to, what it sends, what it asks first."""
    out: dict[str, Any] = {"do": do, "label": label}
    for name, value in (("key", key), ("path", path), ("body", body), ("needs", needs), ("prefill", prefill),
                        ("href", link)):
        if value is not None:
            out[name] = value
    return out


def item(iid: str, group: str, kind: str, title: str, project: Any, *, at: str | None, by: dict[str, Any],
         rank: float, links: list[dict[str, Any]] | None = None, record: dict[str, Any] | None = None,
         actions: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    pid = project.pid if project is not None else None
    title_of = (project.meta.get("title") or pid) if project is not None else None
    return {"id": iid, "group": group, "kind": kind, "title": title, "project": pid, "project_title": title_of,
            "at": at, "by": by, "rank": rank, "links": links or [], "record": record or {}, "actions": actions or [],
            **extra}


def _person(pl: dict[str, Any]) -> dict[str, Any] | None:
    """The person a record names as its signer (or its author's), with the persona and their own agent."""
    raw = pl.get("author")
    author: dict[str, Any] = raw if isinstance(raw, dict) else {}
    for key in PERSON_KEYS:
        name = pl.get(key) or author.get(key)
        if isinstance(name, str) and name.strip().lower() not in ("", "factory", "kernel", "the kernel"):
            out = {"type": "person", "name": name, "persona": pl.get("persona") or author.get("persona")}
            return out | ({"agent": author["agent"]} if author.get("agent") else {})
    return None


def actor(kind: str, pl: dict[str, Any]) -> dict[str, Any]:
    """Who or what made a record: an automation, a delegation, a person (with the persona), an agent's role
    (with its model and its runner or harness when recorded), or the kernel's own rule."""
    if pl.get("automation"):
        return {"type": "automation", "name": str(pl["automation"]), "persona": pl.get("persona")}
    if pl.get("delegation") and kind in ("delegated_decision", "decision"):
        return {"type": "delegation", "name": str(pl["delegation"]), "person": pl.get("person"),
                "persona": pl.get("persona"), "rule": pl.get("rule")}
    person = _person(pl)
    if person is not None:
        return person
    if pl.get("role"):
        return {"type": "agent", "name": str(pl["role"]).replace("_", " "), "role": pl["role"],
                "model": pl.get("model"), "runner": pl.get("runner") or pl.get("harness")}
    return {"type": "kernel", "name": "the kernel"}


def hours_between(earlier: str | None, now: dt.datetime) -> float | None:
    if not earlier:
        return None
    try:
        then = dt.datetime.fromisoformat(earlier.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((now - then).total_seconds() / 3600, 1)


# -- waiting on you --------------------------------------------------------------------------------

def _card_label(card: dict[str, Any]) -> str:
    scope = (card.get("refs") or {}).get("scope")
    if card["kind"] == "approval" and scope == "go_ahead":
        return "go-ahead"
    if card["kind"] == "approval" and scope == "plan":
        return "plan approval"
    return card["kind"].replace("_", " ")


def _card_actions(project: Any, canon: Canon, card: dict[str, Any]) -> list[dict[str, Any]]:
    pid, cid = project.pid, card["id"]
    decide = f"/api/projects/{quote(pid, safe='')}/cards/{cid}/decide"
    out: list[dict[str, Any]] = []
    qid = (card.get("refs") or {}).get("question")
    if card["kind"] == "question" and qid:
        base = f"/api/projects/{quote(pid, safe='')}/questions/{qid}"
        out.append(action("answer", "Answer", key="a", path=base + "/answer", needs="text"))
        try:
            q = canon.question(qid)
        except KeyError:
            q = {}
        if str((q.get("opinions") or {}).get(q.get("perspective")) or "").strip():
            out.append(action("assume", "Let Rihma assume", path=base + "/assume", body={}))
    for verdict, key, word in ((APPROVE.get(card["kind"]), "a", "approve"),
                               (DECLINE.get(card["kind"]), "d", "decline")):
        if verdict:
            needs = "reason" if (card["kind"], verdict) in NEEDS_REASON else None
            out.append(action("decide", verdict.replace("_", " ").capitalize(), key=key, path=decide,
                              body={"verdict": verdict}, needs=needs) | {"meaning": word})
    out.append(action("open", "Open in the Inbox", key="o", link=href(pid, "inbox", cid)))
    return out


def _card_by(card: dict[str, Any]) -> dict[str, Any]:
    pl = card.get("payload") or {}
    if card["kind"] == "question":
        return {"type": "agent", "name": "the panel", "role": "analyst"}
    if card["kind"] == "escalation":
        return {"type": "kernel", "name": "the gate"}
    if card["kind"] in ("change", "concept") and isinstance(pl.get("person"), str):
        return {"type": "person", "name": pl["person"], "persona": pl.get("source")}
    return {"type": "kernel", "name": "the kernel"}


def waiting(project: Any, persona: str, now: dt.datetime, start: str, *, strict: bool = False) -> list[dict[str, Any]]:
    """The open cards ``persona`` may decide on this project (the factory's own canon too), oldest and most
    pressing first; ``new`` says whether a card came since the person last looked (after it, when ``strict``)."""
    if not persona:
        return []
    canon = Canon(project)
    out = []
    for c in canon.cards(state="open", persona=persona):
        title = (c.get("payload") or {}).get("title") if c["kind"] == "concept" else None
        age = hours_between(c.get("created"), now)
        out.append(item(f"{project.pid}/card/{c['id']}", "waiting", "card", str(title or c["title"]), project,
                        at=c.get("created"), by=_card_by(c), rank=CARD_RANK.get(c["kind"], 9) * 10_000 - (age or 0),
                        links=[{"label": "Card", "href": href(project.pid, "inbox", c["id"])}],
                        record={"project": project.pid, "card": c["id"]}, actions=_card_actions(project, canon, c),
                        card=c["id"], card_kind=c["kind"], label=_card_label(c), age_hours=age,
                        new=bool(c.get("created") and (c["created"] > start if strict else c["created"] >= start)),
                        blocking=bool(c.get("blocking"))))
    return out


# -- decided for you -------------------------------------------------------------------------------

def active_delegations(project: Any) -> set[str]:
    from kernel.delegation import delegations

    return {d["id"] for d in delegations(project) if d.get("state") == "active"}


def _settle_actions(pid: str, aid: str) -> list[dict[str, Any]]:
    path = f"/api/projects/{quote(pid, safe='')}/assumptions/{aid}/settle"
    return [action("settle", "Confirm", key="a", path=path, body={"confirmed": True}),
            action("settle", "Overturn", key="d", path=path, body={"confirmed": False}, needs="correction")]


def _assumed(canon: Canon, pl: dict[str, Any]) -> str | None:
    """The assumption a delegated "assume" made, or None."""
    qid = (pl.get("basis") or {}).get("question")
    if pl.get("kind") != "question" or pl.get("verdict") != "assume" or not qid:
        return None
    try:
        found = (canon.question(qid).get("answer") or {}).get("assumption")
    except KeyError:
        return None
    return str(found) if found else None


def delegated(project: Any, pl: dict[str, Any], *, at: str, seq: int, autopilots: dict[str, str],
              canon: Canon, active: set[str]) -> dict[str, Any]:
    """A decision a delegation (or an autopilot run's delegation) made in a person's name."""
    pid, did = project.pid, str(pl.get("delegation"))
    by: dict[str, Any] = {"type": "autopilot" if did in autopilots else "delegation",
                          "name": autopilots.get(did, did), "delegation": did, "rule": pl.get("rule"),
                          "person": pl.get("person"), "persona": pl.get("persona")}
    aid = _assumed(canon, pl)
    open_aid = aid if aid and any(a["id"] == aid for a in canon.assumptions("open")) else None
    acts = _settle_actions(pid, open_aid) if open_aid else [
        action("change", "Overturn", key="d", path=f"/api/projects/{quote(pid, safe='')}/changes",
               prefill=f"Overturn {pl.get('decision')} ({pl.get('verdict')} on {pl.get('card')}, "
                       f"by delegation {did}): ")]
    if did in active:
        acts.append(action("revoke", "Stop the delegation", body={},
                           path=f"/api/projects/{quote(pid, safe='')}/delegations/{did}/revoke"))
    acts.append(action("open", "Open the record", key="o", link=href(pid, "ledger", pl.get("decision"))))
    try:
        about = str(canon.get_card(str(pl.get("card")))["title"])
    except KeyError:
        about = str(pl.get("kind") or "").replace("_", " ")
    title = f"{VERDICT_DONE.get(str(pl.get('verdict')), str(pl.get('verdict')))} {pl.get('card')}: {about}"
    return item(f"{pid}/ledger/{seq}", "decided", "delegated_decision", title, project, at=at, by=by, rank=-seq,
                links=[{"label": "Decision", "href": href(pid, "ledger", pl.get("decision"))},
                       {"label": "Card", "href": href(pid, "inbox", pl.get("card"))}],
                record={"project": pid, "seq": seq, "kind": "delegated_decision"}, actions=acts,
                detail=str(pl.get("why") or ""), decision=pl.get("decision"), card=pl.get("card"),
                decided=pl.get("verdict"), assumption=aid)


def assumptions(project: Any, canon: Canon, start: str, end: str, today: dt.date,
                skip: set[str], *, strict: bool = False) -> list[dict[str, Any]]:
    """The open assumptions the factory made in the period (after its start, when ``strict``), and every open
    one now overdue, with due dates; ``new`` says which were made in the period."""
    chosen = {(q.get("answer") or {}).get("assumption"): (q.get("answer") or {}).get("chosen_by")
              for q in canon.questions() if isinstance(q.get("answer"), dict)}
    out = []
    for a in canon.assumptions("open"):
        overdue = dt.date.fromisoformat(a["due"]) < today
        made = a.get("created") or ""
        new = (start < made if strict else start <= made) and made <= end
        if a["id"] in skip or not (overdue or new):
            continue
        person = chosen.get(a["id"])
        by = {"type": "person", "name": person, "persona": None, "note": "let the factory assume"} if person else \
            {"type": "agent", "name": "the factory", "role": "analyst"}
        out.append(item(f"{project.pid}/assumption/{a['id']}", "decided", "assumption", f"Assumed: {a['text']}",
                        project, at=made or None, by=by, rank=0,
                        links=[{"label": "Assumption", "href": href(project.pid, "assumptions", a["id"])}],
                        record={"project": project.pid, "assumption": a["id"]},
                        actions=_settle_actions(project.pid, a["id"]) + [
                            action("open", "Open the assumption", key="o", link=href(project.pid, "assumptions",
                                                                                     a["id"]))],
                        due=a["due"], overdue=overdue, perspective=a.get("perspective"), assumption=a["id"], new=new))
    out.sort(key=lambda i: (not i["overdue"], i["due"]))
    for n, i in enumerate(out):
        i["rank"] = n
    return out
