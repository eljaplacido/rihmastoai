"""A persona given to an agent, by explicit delegation (D-0024 item 4, FR-PPL1).

A person who acts as a persona can give that persona to an agent on one project: which kinds of card it may
decide, with which verdicts and how many, until when (at most a week, as every delegation). It is a
delegation (kernel/delegation.py), kept in the same file with the same record, so revoking it, its expiry
and its ledger entries work as for any other, and with access in force each decision is checked again as
the delegating person's identity:

- a **Rihma agent** (``rihma``) decides by the factory's own rules for those kinds, when the pipeline would
  wait on the card (``delegation.consult``); a kind no rule decides cannot be given to it;
- a **named agent** through the bridge (``bridge``: Claude Code, Codex, an ops agent of the team's own)
  decides a card itself with ``decide`` (``rihmasto access agent-decide``), within the delegation's kinds,
  verdicts and count.

Neither ever decides a card the delegation does not cover: another kind, another verdict, a card its
persona may not decide on this project, a kind that is never delegated (the deploy gate, trust, a holdout
ruling, a connector, a road, a runner, a concept), after the delegation ended or was revoked. Each refusal
is recorded once (``delegation_declined``). Shown as "operations: delegated to ops-agent until <date>".
"""

from __future__ import annotations

from typing import Any

from kernel import delegation as dl
from kernel.agent_channel import NAME
from kernel.canon import CARD_DECIDERS, CARD_VERDICTS, Canon, DecisionRefused, deciders_of
from kernel.people import PERSONAS, SIGNER, is_person
from kernel.store import Factory, Project, updating_json

KINDS = ("rihma", "bridge")
MAX_DECISIONS = 1000
RECORD = "agent_persona_assigned"


def _agent(kind: str, name: str) -> dict[str, str]:
    name = str(name or "").strip().lower()
    if kind not in KINDS:
        raise ValueError(f"an agent is a Rihma agent (rihma) or a named agent through the bridge (bridge), "
                         f"not {kind!r}")
    if not NAME.match(name):
        raise ValueError("an agent's name is lower-case letters, digits, dots, dashes or underscores, "
                         "such as ops-agent")
    return {"kind": kind, "name": name}


def _refusal(kind: str, persona: str, agent: dict[str, str]) -> str | None:
    if kind not in CARD_VERDICTS:
        return f"{kind!r} is not a kind of card"
    if kind in dl.NEVER:
        return f"a {kind} card is never delegated: {dl.NEVER[kind]}"
    if persona not in CARD_DECIDERS[kind]:
        return f"a {persona} does not decide a {kind} card, so cannot give one to an agent"
    if agent["kind"] == "rihma" and kind not in dl.RULES:
        return f"a Rihma agent decides by the factory's rules, and no rule decides a {kind} card: name an agent"
    return None


def _verdicts(kinds: list[str], verdicts: Any) -> list[str]:
    allowed = [v for k in kinds for v in CARD_VERDICTS[k]]
    chosen = list(dict.fromkeys(verdicts or allowed))
    bad = [v for v in chosen if v not in allowed]
    if bad:
        raise ValueError(f"{bad[0]!r} is not a verdict of {', '.join(kinds)} "
                         f"(they take {', '.join(dict.fromkeys(allowed))})")
    return chosen


def _checked(kinds: list[str], who: dict[str, str], persona: str, verdicts: Any,
             max_decisions: int | None) -> tuple[list[str], dict[str, Any]]:
    """The kinds an agent may be given, and its limits; refused with every reason when it may not."""
    if persona not in PERSONAS:
        raise DecisionRefused(f"name the persona to give: one of {', '.join(PERSONAS)}")
    kinds = list(dict.fromkeys(k.strip() for k in kinds if k and k.strip()))
    if not kinds:
        raise ValueError("name the kinds of card the agent may decide")
    refused = [why for why in (_refusal(k, persona, who) for k in kinds) if why]
    if refused:
        raise DecisionRefused("; ".join(refused))
    if max_decisions is not None and not 0 < int(max_decisions) <= MAX_DECISIONS:
        raise ValueError(f"the most decisions is a number from 1 to {MAX_DECISIONS}")
    return kinds, {"verdicts": _verdicts(kinds, verdicts) if who["kind"] == "bridge" else None,
                   "max": int(max_decisions) if max_decisions else None}


def assign(project: Project, kinds: list[str], *, agent_kind: str, agent: str, until: object, person: str,
           persona: str, verdicts: Any = None, max_decisions: int | None = None, reason: str = "") -> dict[str, Any]:
    """Give ``persona`` (one the person acts as) to an agent on this project, for ``kinds`` until ``until``."""
    from kernel.access import require

    who = _agent(agent_kind, agent)
    kinds, limits = _checked(kinds, who, persona, verdicts, max_decisions)
    if who["kind"] == "rihma":
        d = dl.grant(project, kinds, person=person, persona=persona, until=until, reason=reason)
        with updating_json(project.path(dl.FILE), []) as items:
            entry = next(x for x in items if x["id"] == d["id"])
            entry.update(agent=who, **limits)
    else:
        entry = _bridge_entry(project, kinds, who, limits, person=person, persona=persona, until=until, reason=reason,
                              require=require)
    project.log(RECORD, {"id": entry["id"], "persona": persona, "agent": who, "kinds": kinds, **limits,
                         "person": person, "until": entry["until"]})
    out = dl.view(entry, project.factory.clock.now())
    return out | {"words": describe(out)}


def _bridge_entry(project: Project, kinds: list[str], who: dict[str, str], limits: dict[str, Any], *, person: str,
                  persona: str, until: object, reason: str, require: Any) -> dict[str, Any]:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a delegation names the person who delegates")
    now = project.factory.clock.now()
    end = dl.until_of(until, now)
    require(project, person, persona)
    signer = SIGNER.get()
    with updating_json(project.path(dl.FILE), []) as items:
        entry: dict[str, Any] = {"id": f"DL-{len(items) + 1:03d}", "kinds": kinds, "rules": {}, "person": person,
                                 "persona": persona, "reason": str(reason or "").strip()[:2000], "at": dl.stamp(now),
                                 "until": dl.stamp(end), "run": None, "revoked": None, "agent": who, **limits}
        if signer is not None and signer.name == person:
            entry.update(identity=signer.id, groups=list(signer.groups))
        items.append(entry)
    project.log("delegation_granted", {k: entry[k] for k in ("id", "kinds", "person", "persona", "until", "reason")}
                | {"agent": who["name"]})
    return entry


def describe(d: dict[str, Any]) -> str:
    """"operations: delegated to ops-agent until 2026-11-30 08:00 UTC (incident cards)", with its state."""
    agent = d.get("agent") or {"name": "the factory's rules"}
    state = d.get("state", "active")
    ended = "" if state == "active" else f" ({state})"
    return (f"{d['persona'].replace('_', ' ')}: delegated to {agent['name']} until {d['until'][:16].replace('T', ' ')} "
            f"UTC ({', '.join(k.replace('_', ' ') for k in d['kinds'])} cards){ended}")


def for_kind(project: Project, kind: str) -> list[dict[str, Any]]:
    """The delegations to agents in force on this project that cover ``kind``."""
    return [d for d in dl.delegations(project) if d.get("agent") and kind in d["kinds"] and d["state"] == "active"]


def listed(factory: Factory) -> list[dict[str, Any]]:
    """Every persona given to an agent, on every project, with its state and words."""
    out = []
    for p in factory.projects():
        for d in dl.delegations(p):
            if d.get("agent"):
                out.append(d | {"project": p.pid, "project_title": p.meta.get("title", p.pid), "words": describe(d)})
    return out


def _refuse(project: Project, d: dict[str, Any], card: dict[str, Any], why: str) -> DecisionRefused:
    dl._declined(project, d, card, "agent", why, {"agent": (d.get("agent") or {}).get("name")})
    return DecisionRefused(why)


def _why_not(project: Project, d: dict[str, Any], card: dict[str, Any], verdict: str) -> str | None:
    if card["state"] != "open":
        return f"{card['id']} is not open"
    if card["kind"] not in d["kinds"]:
        return f"{d['id']} covers {', '.join(d['kinds'])} cards, not a {card['kind']} card"
    if d["persona"] not in deciders_of(card):
        return f"a {d['persona']} may not decide {card['id']} on this project"
    if verdict not in CARD_VERDICTS[card["kind"]] or verdict not in (d.get("verdicts") or []):
        return f"{d['id']} lets the agent say {', '.join(d.get('verdicts') or [])}, not {verdict!r}"
    if d.get("max") and len(dl.decided_under(project, d["id"])) >= d["max"]:
        return f"{d['id']} allowed {d['max']} decisions, and they are made"
    return None


def decide(project: Project, did: str, card_id: str, verdict: str, *, agent: str, reason: str = "") -> dict[str, Any]:
    """A named agent decides a card under its delegation: in the delegating person's name and persona, the
    record naming the agent and the delegation. Anything the delegation does not cover is refused."""
    now = project.factory.clock.now()
    d = next((x for x in project.read(dl.FILE, []) or [] if x["id"] == did), None)
    if d is None or (d.get("agent") or {}).get("kind") != "bridge":
        raise DecisionRefused(f"{did} is not a persona given to a named agent on {project.pid}")
    if d["agent"]["name"] != str(agent or "").strip().lower():
        raise DecisionRefused(f"{did} is given to {d['agent']['name']}, not {agent!r}")
    if dl.state_of(d, now) != "active":
        raise DecisionRefused(f"{did} is {dl.state_of(d, now)}: the card waits for a person")
    card = Canon(project).get_card(card_id)
    why = _why_not(project, d, card, verdict)
    if why:
        raise _refuse(project, d, card, why)
    with dl.acting_for(d):
        dec = Canon(project).decide(card_id, verdict, person=d["person"], persona=d["persona"],
                                    reason=f"by {d['agent']['name']} under delegation {did}: {str(reason)[:1000]}")
    out = {"card": card_id, "kind": card["kind"], "verdict": verdict, "delegation": did, "rule": "agent",
           "agent": d["agent"]["name"], "decision": dec.get("id"), "person": d["person"], "persona": d["persona"],
           "why": str(reason)[:500]}
    project.log("delegated_decision", out | {"basis": {"agent": d["agent"]["name"]}})
    return out
