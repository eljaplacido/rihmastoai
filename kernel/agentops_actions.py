"""Agent operations as the cockpit, Ask Rihma and the command line use it: the view with its Optimise audit, the
audit recorded, and a proposal filed as a change (FR-AOP1).

- ``read``: the read model of one project (or the platform) with the Optimise proposals and what they would save
  together; nothing is written;
- ``record``: the audit kept in the ledger as ``agent_ops_audited``, signed by a named person (the project's ledger,
  or Rihmasto's own canon for the platform): the window, the runs read, each proposal's id, kind and expected
  saving. An auditor reads later what was proposed and when;
- ``file_change``: one proposal as a change card in the Inbox of its project (Rihmasto's own canon for a
  platform-wide one), with its expected saving and the rule's evidence, recorded as ``agent_ops_change_filed``.
  A proposal filed before answers with its card and records nothing new.
"""

from __future__ import annotations

from typing import Any

from kernel import agentops
from kernel import agentops_optimise as opt
from kernel.canon import DecisionRefused
from kernel.insights.base import WINDOWS
from kernel.people import is_person
from kernel.store import updating_json

FILED = "agentops/changes.json"
MAX_RECORDED = 40
Row = dict[str, Any]


class OpsRefused(DecisionRefused):
    """An audit or a change refused: not a person, or a persona that does not audit agents."""


def window_of(value: Any) -> str:
    if value in (None, ""):
        return "30d"
    if value not in WINDOWS:
        raise ValueError(f"the window is one of {', '.join(WINDOWS)}")
    return str(value)


def _target(factory: Any, pid: str | None) -> Any:
    from kernel.learn import FACTORY_PID, factory_project

    return factory_project(factory) if pid in (None, FACTORY_PID) else factory.project(pid)


def _filed(target: Any) -> dict[str, str]:
    return dict(target.read(FILED, {}) or {})


def read(factory: Any, *, pid: str | None = None, window: str = "30d", context: bool = True) -> Row:
    """The view with its proposals, each saying whether it was filed as a change already."""
    view = agentops.build(factory, pid=pid, window=window, context=context)
    found = opt.proposals(view)
    filed: dict[str, str] = {}
    for p in {x["project"] for x in found} | {None}:
        try:
            filed |= _filed(_target(factory, p))
        except (KeyError, OSError, ValueError):
            continue
    for p in found:
        p["card"] = filed.get(p["id"])
    from kernel.agent_skills import overview

    return agentops.public(view) | {"proposals": found, "savings": opt.totals(found), "auditors": list(opt.AUDITORS),
                                    "skills": overview(factory, pid)}   # platform-wide and per project


def _check(person: str, persona: str) -> None:
    if not is_person(person):
        raise OpsRefused(f"{person!r} is not a person: an audit or a change is signed by a named person")
    if persona not in opt.AUDITORS:
        raise OpsRefused(f"a {persona} does not audit agent operations; one of {', '.join(opt.AUDITORS)} does")


def record(factory: Any, *, pid: str | None, window: str, person: str, persona: str) -> Row:
    """Run the Optimise audit and keep it in the ledger, signed."""
    _check(person, persona)
    out = read(factory, pid=pid, window=window)
    kept = [{"id": p["id"], "kind": p["kind"], "project": p["project"], "role": p["role"], "title": p["title"][:160],
             "tokens": p["saving"].get("tokens"), "cost": p["saving"].get("cost"),
             "seconds": p["saving"].get("seconds")} for p in out["proposals"][:MAX_RECORDED]]
    payload = {"scope": pid or "platform", "window": window, "runs": out["totals"]["runs"],
               "tokens": out["totals"]["tokens"], "cost": out["totals"]["cost"], "savings": out["savings"],
               "proposals": kept, "person": person, "persona": persona}
    rec = _target(factory, pid).log("agent_ops_audited", payload)
    return out | {"audit": {"seq": rec.get("seq"), **payload}}


def _text(p: Row) -> str:
    s = p["saving"]
    parts = [f"{s['tokens']:,} tokens" if s.get("tokens") is not None else None,
             f"{s['cost']:g} {s.get('currency') or 'USD'}" if s.get("cost") is not None else None,
             f"{s['seconds']:g} seconds" if s.get("seconds") is not None else None]
    said = ", ".join(x for x in parts if x) or "not measured"
    return (f"{p['title']}\n\n{p['detail']}\n\nExpected saving: {said} ({s.get('basis')}).\n"
            f"From the Agent operations audit, proposal {p['id']} ({p['kind']}).")


def file_change(factory: Any, *, pid: str, oid: str, person: str, persona: str, window: str = "30d") -> Row:
    """File one proposal of ``pid``'s scope (FACTORY_PID: the platform's) as a change card."""
    from kernel.change import submit
    from kernel.learn import FACTORY_PID

    _check(person, persona)
    scope = None if pid == FACTORY_PID else pid
    out = read(factory, pid=scope, window=window)
    found = next((p for p in out["proposals"] if p["id"] == oid), None)
    if found is None:
        raise KeyError(f"no proposal {oid} in the {window} audit of {pid}: it no longer applies")
    target = _target(factory, found["project"] or scope)
    if found.get("card"):
        return {"proposal": found, "card": {"id": found["card"]}, "already": True}
    card = submit(target, persona=persona, person=person, text=_text(found))
    with updating_json(target.path(*FILED.split("/")), {}) as kept:
        kept[oid] = card["id"]
    target.log("agent_ops_change_filed", {"proposal": oid, "kind": found["kind"], "card": card["id"],
                                          "saving": found["saving"], "person": person, "persona": persona})
    return {"proposal": found | {"card": card["id"]}, "card": card, "already": False}
