"""A record of what the hub showed for a project, made by a person or an automation (FR-OBS1).

The view reads the hub and keeps nothing. When a developer or IT presses *Record what the hub shows* (or
`rihmasto agentobs snapshot`, or an automation's ``agent_snapshot`` action), the figures that matter for
decisions go into the project's ledger as ``agent_sessions_observed``: the hub project, the sessions per harness,
the sessions with an unrecovered failure (their ids), the files at or above the hub's rework threshold (their
paths and edit counts), the share of sessions that read the contract first, and the chain's verdict. Counts and
ids only: never a step, a command or anything a session said.

Two records follow when something new appears since the last snapshot, so an automation can react to them
(kernel/automations_events.py names any record kind): ``agent_failure_unrecovered`` (sessions with an unrecovered
failure not seen before) and ``agent_rework_heavy`` (files newly at or above the threshold, or edited more).
"""

from __future__ import annotations

from typing import Any

from kernel.agentobs import MAPPERS, MODULE, SEES, module_on
from kernel.agentobs.client import Hub
from kernel.agentobs.view import build
from kernel.canon import DecisionRefused
from kernel.people import is_person

KIND = "agent_sessions_observed"


def summary(v: dict[str, Any]) -> dict[str, Any]:
    """The figures of a view worth a record."""
    sec = v.get("sections") or {}
    measured = bool((sec.get("sessions") or {}).get("measured"))
    out: dict[str, Any] = {"hub_project": ((v.get("mapping") or {}).get("current") or {}).get("hub_project"),
                           "measured": measured}
    if not measured:
        out["why"] = (sec.get("sessions") or {}).get("why")
        return out
    return out | _figures(sec)


def _measured(sec: dict[str, Any], key: str, field: str) -> Any:
    part = sec.get(key) or {}
    return part.get(field) if part.get("measured") else None


def _figures(sec: dict[str, Any]) -> dict[str, Any]:
    rw = sec.get("rework") or {}
    threshold = rw.get("threshold") or 3
    stuck = (sec.get("failures") or {}).get("unrecovered_sessions") or []
    return {"sessions": sec["sessions"]["count"], "by_harness": sec["sessions"]["totals"],
            "unrecovered_sessions": [r["session_id"] for r in stuck],
            "rework_heavy": [{"file": f.get("file"), "edits": f.get("edits")} for f in rw.get("files") or []
                             if (f.get("edits") or 0) >= threshold],
            "contract_first_rate": _measured(sec, "governance", "contract_engagement_rate"),
            "chain_valid": _measured(sec, "chain", "valid"), "chain_attests": _measured(sec, "chain", "attests")}


def _new(before: dict[str, Any], now: dict[str, Any]) -> dict[str, Any]:
    """What appeared since the last record: sessions newly stuck, files newly (or more) reworked."""
    if not now["measured"]:
        return {}
    new: dict[str, Any] = {}
    seen = set(before.get("unrecovered_sessions") or [])
    fresh = [s for s in now["unrecovered_sessions"] if s not in seen]
    if fresh:
        new["agent_failure_unrecovered"] = {"hub_project": now["hub_project"], "sessions": fresh}
    edits = {f["file"]: f["edits"] for f in before.get("rework_heavy") or []}
    heavier = [f for f in now["rework_heavy"] if (f["edits"] or 0) > (edits.get(f["file"]) or 0)]
    if heavier:
        new["agent_rework_heavy"] = {"hub_project": now["hub_project"], "files": heavier}
    return new


def _last(project: Any) -> dict[str, Any]:
    found = project.ledger().of_kind(KIND)
    return found[-1]["event"]["payload"] if found else {}


def record(factory: Any, project: Any, *, person: str, persona: str, via: str | None = None,
           hub: Hub | None = None) -> dict[str, Any]:
    """Read the hub for the project and record its figures, and what is new since the last record."""
    from kernel.modules import ModuleOff, enable_hint

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a snapshot is recorded by a named person")
    if persona not in MAPPERS:
        raise DecisionRefused(f"a {persona} may not record a snapshot of the hub; a developer or IT does")
    if not module_on(project):
        raise ModuleOff(f"Agent observability is not enabled for project {project.pid}: "
                        f"{enable_hint(MODULE, project)}")
    before = _last(project)
    now = summary(build(factory, project, persona=SEES[0], hub=hub))
    signer = {"person": person, **({"via": via} if via else {})}
    project.log(KIND, now | signer | {"persona": persona})
    new = _new(before, now)
    for kind, payload in new.items():
        project.log(kind, payload | signer)
    return now | {"new": sorted(new)}
