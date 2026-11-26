"""Nudges (FR-HITL1): the persona responsible for each open ask is reminded, escalating as it ages.

Steps, by the age of an open ask:

- **nudge** after a day: the persona it is put to is reminded through their channels;
- **escalate** after three days: reminded again, and the escalation persona too (the business owner; for an ask
  put to the business owner, the product owner);
- **overdue** after a week: both once more, and the view marks it overdue.

Each step is sent once per ask, and counts as sent only once it reached someone: a step with no channel stays due
and the answer says what IT adds (FR-HITL2). Solo by default: while one person holds every persona (solo mode,
kernel/solo.py) only what blocks work nudges the owner, that is an open ask of a required family (kernel/hitl.py);
the others wait quietly in the view. A person outside the system the owner chose to ask is nudged all the same: on
a person's Nudge they get a new one-use link by their channel (the old one ends), and when it did not reach them by
a channel its address is shown once to pass on. A withdrawn link's asks are the persona's again: nobody makes the
withdrawn person a new link. The relay's round (kernel/relay.py) sends the steps due to people inside, as "the
relay".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kernel import hitl, hitl_links, hitl_send
from kernel.people import is_person
from kernel.store import Factory, Project

STEPS = (("overdue", 168), ("escalate", 72), ("nudge", 24))     # hours, the latest step first
ESCALATE_TO = {"business_owner": "product_owner"}               # else the business owner
RELAY = "the relay"


def _solo(factory: Factory) -> bool:
    from kernel import access as kaccess
    from kernel.solo import holds_all

    try:
        return holds_all(kaccess.load(factory))
    except (OSError, ValueError):
        return True


def step_of(hours: float) -> str | None:
    return next((name for name, after in STEPS if hours >= after), None)


def escalation(persona: str) -> str:
    return ESCALATE_TO.get(persona, "business_owner")


def _live_links(project: Project) -> set[str]:
    """The links that still stand (not withdrawn): an ask on a withdrawn link is the persona's again."""
    return {r["id"] for r in hitl_links.links(project.factory, project.pid) if r.get("state") != "revoked"}


def due(project: Project, *, solo: bool | None = None) -> list[dict[str, Any]]:
    """Every open ask with its step now, who it goes to, and whether that step is still to be sent. Solo, only what
    blocks work nudges the owner; a person outside the owner chose to ask is nudged all the same (FR-HITL2)."""
    solo = _solo(project.factory) if solo is None else solo
    live = _live_links(project)
    rows = []
    for a in hitl.asks(project, state="open"):
        hours = hitl.age_hours(project, a)
        step = step_of(hours)
        required = hitl.level(project, a["family"])[0] == "require"
        external = bool(a["to"].get("external")) and a["to"].get("link") in live
        to = [a["to"]["persona"]] + ([escalation(a["to"]["persona"])] if step in ("escalate", "overdue") else [])
        quiet = solo and not required and not external
        rows.append({"ask": a["id"], "step": step, "hours": round(hours, 1), "to": to, "required": required,
                     "external": external, "link": a["to"].get("link") if external else None, "quiet": quiet,
                     "person": a["to"].get("person") if external else None,
                     "to_send": bool(step) and step not in (a.get("nudged") or {}) and not quiet})
    return rows


def _internal(project: Project, row: dict[str, Any], env: Mapping[str, str], post: Any, send: Any) -> list[Any]:
    item = hitl.get(project, row["ask"])
    rnd = hitl_send._round(project.factory, env, post, send)
    head = (f"{'Overdue' if row['step'] == 'overdue' else 'Waiting'} {round(row['hours'] / 24, 1)} days: "
            f"{hitl.FAMILY_LABEL[item['family']].lower()} {item['kind']} {item['id']}, {item['text'][:120]}")
    notice = hitl_send._notice(project, item, hitl_send._view_link(rnd, project), head=head,
                               detail=f"Put to the {item['to']['persona'].replace('_', ' ')} by {item['by']}"
                                      + (". Delivery waits on it." if row["required"] else "."), n=row["step"])
    return hitl_send._to_subs(rnd, project, row["to"], notice)


def _external(project: Project, row: dict[str, Any], person: str, persona: str, base: str, env: Mapping[str, str],
              post: Any, send: Any) -> list[Any]:
    """A fresh link for the person outside; its address is shown once whenever it did not reach them by their
    channel (copy, or a send that failed), so the old link never ends without a new one in hand (FR-HITL2)."""
    fresh = hitl_links.again(project, row["link"], person=person, persona=persona)
    address = hitl_links.url(base, fresh["token"])
    sent = hitl_send.send_link(project, fresh, address, environ=env, post=post, send=send)
    shown = sent.get("outcome") != "delivered"
    return [{"link": fresh["id"], "name": fresh["name"], **{k: v for k, v in sent.items() if k != "said"},
             "said": sent["said"], **({"url": address} if shown else {})}]


def _undelivered(row: dict[str, Any], results: list[dict[str, Any]]) -> str:
    """Where a reminder went nowhere, and what IT adds so it goes."""
    if not results:
        return f"{row['ask']}: " + hitl_send._nowhere(row["to"][0])
    return f"{row['ask']}: " + hitl_send._said(results, row["to"][0])


def _said(sent: list[dict[str, Any]], once: list[dict[str, Any]], missed: list[str], warn: bool) -> str:
    went = sum(any(r.get("outcome") == "delivered" for r in s["results"]) for s in sent)
    parts = [f"{went} nudge(s) sent."] if went else []
    parts += [f"A new link for {o['name']} ({o['link']}) is shown once to copy: pass it on, the old one no longer "
              "opens." for o in once]
    if warn and once:
        parts.append(hitl_links.LOCAL_WARNING)
    if missed:
        parts.append("Not sent, so still due: " + "; ".join(missed) + ".")
    return " ".join(parts) or "Nothing to nudge: no open ask is due a reminder now."


def _one(project: Project, row: dict[str, Any], who: tuple[str, str, bool], base: str, env: Mapping[str, str],
         post: Any, send: Any) -> list[Any] | None:
    person, persona, by_person = who
    if row["external"]:
        if not by_person or persona not in hitl_links.CREATORS:
            return None            # a new link is a person's act: the view says it waits on one
        return _external(project, row, person, persona, base, env, post, send)
    return _internal(project, row, env, post, send)


def nudge(project: Project, *, person: str, persona: str, base: str, environ: Mapping[str, str] | None = None,
          post: Any = None, send: Any = None, solo: bool | None = None) -> dict[str, Any]:
    """Send every step due now (person: who pressed Nudge, or RELAY for the relay's round). A step that reached
    nobody stays due, and the answer says where nothing went and what IT adds (FR-HITL2)."""
    import os

    env = os.environ if environ is None else environ
    by_person = person != RELAY
    if by_person and not is_person(person):
        from kernel.canon import DecisionRefused

        raise DecisionRefused(f"{person!r} is not a person: a nudge is signed by a named person")
    sent, once, missed = [], [], []
    for row in due(project, solo=solo):
        results = _one(project, row, (person, persona, by_person), base, env, post, send) if row["to_send"] else None
        if results is None:
            continue
        reached = row["external"] or any(r.get("outcome") == "delivered" for r in results)
        if not reached:
            missed.append(_undelivered(row, results))
            continue
        hitl.mark_nudged(project, row["ask"], row["step"])
        project.log("hitl_nudged", {"ask": row["ask"], "step": row["step"], "to": row["to"],
                                    "delivered": sum(r.get("outcome") == "delivered" for r in results),
                                    **({"person": person, "persona": persona} if by_person else {"by": RELAY})})
        sent.append({**row, "results": results})
        once += _shown(results)
    if by_person:              # a person's Nudge is on the record, whether or not anything was due
        project.log("hitl_nudge_asked", {"sent": len(sent), "not_sent": len(missed), "person": person,
                                         "persona": persona})
    return _result(sent, once, missed, base)


def _shown(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The fresh links to show once: those that did not reach their person by a channel."""
    return [{"link": r["link"], "name": r["name"], "url": r["url"], "said": r["said"]} for r in results if r.get("url")]


def _result(sent: list[Any], once: list[Any], missed: list[str], base: str) -> dict[str, Any]:
    warn = bool(once) and hitl_links.local_only(base)
    return {"nudged": sent, "count": len(sent), "once": once, "not_sent": missed,
            "said": _said(sent, once, missed, warn), **({"warning": hitl_links.LOCAL_WARNING} if warn else {})}


def relay_round(factory: Factory, *, environ: Mapping[str, str], post: Any, send: Any) -> int:
    """The steps due to people inside, for every project, sent as the relay (kernel/relay.py calls it)."""
    total = 0
    for project in factory.projects():
        if project.path(hitl.FILE).exists() and not project.meta.get("archived"):
            total += nudge(project, person=RELAY, persona="", base="", environ=environ, post=post, send=send)["count"]
    return total
