"""Feedback from destinations (FR-DST1): probe where the capability runs, and bring what changed back.

One round (`check`), from the cockpit's Check now, `rihmasto destinations <pid> --check`, or the `destinations`
check on its schedule (kernel/checks/destinations.py):

1. Every environment where a release runs is probed (kernel/operate.py `probe`: `/health` and the probe
   scenarios, or a scheduled job's executions), and the result is kept in `ops/probes.jsonl` as any probe.
2. Every destination is read again (kernel/destinations.py) and compared with the last round
   (`ops/destinations.json`).
3. A destination that **became failing** is brought back to the people and agents who work on the project:
   - an incident card (kernel/operate.py `open_incident`: one per release and environment, a repeat adds an
     occurrence), which the Inbox, the Review ("An incident opened") and Home show;
   - a post in the project's agent channel (thread `destinations`, by the system), so a coding agent working on
     the project sees it with the incident's card;
   - `destination_failing` in the ledger: the Review lists it under what went wrong, and an automation's event
     trigger `destination_failing` reacts to it (kernel/automations_events.py).
   A destination that was failing and is not any more records `destination_recovered`.
4. The round is recorded (`destinations_checked`) with who asked, and what is failing.

Nothing here decides a card or rolls anything back: the delivery's canary and rollback stay where they are.
"""

from __future__ import annotations

from typing import Any

from kernel import destinations as dmod
from kernel.roads import ENVIRONMENTS, slot_state

THREAD = "destinations"


def _probe_all(project: Any) -> list[dict[str, Any]]:
    from kernel import operate

    out = []
    for env in ENVIRONMENTS:
        if not slot_state(project, env, "current"):
            continue
        try:
            res = operate.probe(project, env)
            out.append({"environment": env, "verdict": res.get("verdict"), "at": res.get("at")})
        except Exception as exc:  # a probe that cannot run is said, never the end of the round
            out.append({"environment": env, "verdict": "not measured", "why": f"{type(exc).__name__}: {exc}"})
    return out


def _why(d: dict[str, Any]) -> str:
    return str((d.get("health") or {}).get("why") or d.get("note") or "it failed")


def _incident(project: Any, d: dict[str, Any]) -> dict[str, Any]:
    from kernel import operate

    if d.get("details", {}).get("incident"):
        return {"card": d["details"]["incident"], "new": False}
    slot = slot_state(project, d["environment"], "current") if d["group"] == "deployed" and d["environment"] else None
    release = (slot or {}).get("release") or (d.get("last_delivery") or {}).get("release") or 0
    where = d["environment"] if d["group"] == "deployed" else d["id"]
    return operate.open_incident(project, release=release, env=str(where),
                                 title=f"Destination {d['label']} is failing",
                                 body=f"{_why(d)}\n\nFound by the destinations round; see the project's Destinations.",
                                 payload={"destination": d["id"], "health": d.get("health")})


def _post(project: Any, d: dict[str, Any], card: str | None) -> str | None:
    from kernel import agent_channel

    text = (f"Destination {d['label']}" + (f" ({d['environment']})" if d.get("environment") else "")
            + f" is failing: {_why(d)}" + (f". Incident {card}." if card else "."))
    try:
        msg = agent_channel.post(project, author=agent_channel.SYSTEM, kind="check_result", text=text[:2000],
                                 thread=THREAD, refs={"cards": [card]} if card else None)
    except agent_channel.ChannelRefused:
        return None
    return str(msg["id"])


def _flatten(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [d for g in dmod.GROUPS for d in view["groups"][g]]


def _signs(person: str | None, persona: str | None, via: str) -> None:
    """A round a person asks for is signed; the check's schedule runs it as whoever enabled the check."""
    if person is None and via == "check":
        return
    from kernel.canon import DecisionRefused
    from kernel.people import PERSONAS, is_person

    if not is_person(str(person or "")) or persona not in PERSONAS:
        raise DecisionRefused(f"{person!r} is not a person with a persona: a feedback round is signed")


def _changed(project: Any, d: dict[str, Any], was: str | None, who: dict[str, Any]) -> dict[str, Any] | None:
    """What one destination's change since the last round brings back, recorded; None when it did not change."""
    if d["state"] == "failing" and was != "failing":
        inc = _incident(project, d)
        mid = _post(project, d, inc.get("card"))
        project.log("destination_failing", {"destination": d["id"], "label": d["label"], "group": d["group"],
                                            "environment": d["environment"], "why": _why(d)[:300],
                                            "card": inc.get("card"), "message": mid, **who})
        return {"destination": d["id"], "became": "failing", "card": inc.get("card"), "message": mid}
    if was == "failing" and d["state"] != "failing":
        project.log("destination_recovered", {"destination": d["id"], "label": d["label"],
                                              "environment": d["environment"], "state": d["state"], **who})
        return {"destination": d["id"], "became": d["state"]}
    return None


def check(project: Any, *, person: str | None = None, persona: str | None = None, via: str = "person",
          probe: bool = True) -> dict[str, Any]:
    """One feedback round: probe, read every destination again, bring back what became failing. Asked by a
    person, it is signed; the check's schedule runs it with the rights of whoever enabled the check."""
    _signs(person, persona, via)
    before = dmod.feedback(project).get("destinations") or {}
    probes = _probe_all(project) if probe else []
    view = dmod.view(project)
    who = {"by": person or via, "persona": persona}
    now, changes = {}, []
    for d in _flatten(view):
        now[d["id"]] = {"state": d["state"], "label": d["label"], "environment": d["environment"],
                        "health": d.get("health")}
        change = _changed(project, d, (before.get(d["id"]) or {}).get("state"), who)
        if change is not None:
            changes.append(change)
    at = project.factory.clock.stamp()
    project.write("/".join(dmod.FEEDBACK), {"at": at, "by": person or via, "destinations": now})
    failing = view["summary"]["failing"]
    project.log("destinations_checked", {"by": person or via, "persona": persona, "via": via, "probed": len(probes),
                                         "failing": failing[:20], "counts": view["summary"]["counts"]})
    said, tone = said_of(view)
    return {"project": project.pid, "at": at, "probes": probes, "changes": changes, "failing": failing,
            "summary": view["summary"], "view": view, "said": said, "tone": tone}


def said_of(view: dict[str, Any]) -> tuple[str, str]:
    """What a round found, in words: failing, not measured when nothing runs (never "nothing is failing"), or not."""
    failing = view["summary"]["failing"]
    if failing:
        return f"{len(failing)} failing: {', '.join(failing)}", "warning"
    live = [d for d in view["groups"]["deployed"] if d["state"] in dmod.LIVE]
    if not live:
        return ("Not measured: it runs nowhere yet, so there was nothing to probe. Deliver it, or start it on its "
                "road, then check again."), "warning"
    return f"Checked: nothing is failing ({', '.join(d['label'] for d in live)}).", "good"
