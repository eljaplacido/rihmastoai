"""Ask Rihma about the IDE agents' sessions (FR-OBS1), by rule and without a model, as the project status is.

A question that names the agent sessions, the IDE agents, rework hotspots, unrecovered failures or agent
observability is answered from the records and the hub, with Take me there to the Agent sessions view:

- with the module off for the project: what it would add, and a proposal to turn it on for this project
  (``agentobs_enable``), which the person confirms in the cockpit, signed with their name;
- not yet mapped: the hub project that matches the repository, and a proposal to map it (``agentobs_map``);
- mapped: the figures in one paragraph (sessions by harness, rework, unrecovered failures, contract read before
  edit, the chain's verdict), each "not measured" when the hub has nothing;
- for a persona the view is not for: who it is for.

The assistant itself writes nothing; a proposal runs only when a person confirms it (cockpit/static/agentobs.js).
"""

from __future__ import annotations

import re
from typing import Any

from kernel.agentobs import MAPPERS, SEES, VIEW, module_on
from kernel.agentobs.client import HubError, HubUnreachable, from_settings
from kernel.agentobs.mapping import candidates, current, suggest
from kernel.agentobs.view import build

PHRASES = ("agent session", "ide agent", "coding agent", "agent observability", "agentobs", "rework hotspot",
           "agent failure", "unrecovered agent", "contract read before edit", "claude code session",
           "cursor session", "opencode session", "observability hub", "agent trajector",
           "agenttien istun")
_WORD = re.compile(r"\s+")


def asks(question: str) -> bool:
    """Whether the question is about the IDE agents' sessions."""
    low = _WORD.sub(" ", question.lower())
    return any(p in low for p in PHRASES)


def _out(answer: str, route: str | None, *, control: str | None = None, propose: list | None = None) -> dict:
    return {"answer": answer, "navigate": {"route": route, "control": control} if route else None,
            "propose": propose or [], "dropped": [], "sources": [], "by": "map", "matches": [VIEW]}


def _proposal(action: str, project: Any, persona: str, why: str, **args: Any) -> dict[str, Any]:
    return {"action": action, "args": {"project": project.pid, **args}, "why": why, "persona": persona,
            "project": project.pid}


def answer(factory: Any, question: str, project: Any, persona: str,
           holding: tuple[str, ...] | None = None) -> dict | None:
    """The answer, or None when the question is not about the IDE agents' sessions. ``holding``: the personas
    of a person viewing "everything" (FR-PPL1); one the view is for answers when the persona named is not."""
    if not asks(question):
        return None
    if persona not in SEES and holding:
        persona = next((p for p in SEES if p in holding), persona)
    if project is None:
        return _out("Agent sessions is a view of each project, for developers and IT: what the IDE agents (Claude "
                    "Code, Cursor, OpenCode) did in its repository, read from your agent observability hub. Open a "
                    "project to see it, or to turn Agent observability on for it (it is off by default).",
                    "#/projects")
    route = f"#/p/{project.pid}/{VIEW}"
    if not module_on(project):
        why = ("it shows what the IDE agents did in this project's repository: sessions by harness, rework hotspots, "
               "failures and whether they were recovered, contract read before edit, and the hub's chain check")
        may = persona in ("business_owner", "product_owner", "it", "developer", "compliance")
        return _out(f"Agent sessions is part of Agent observability, which is off for {project.meta.get('title')} "
                    f"(it is off until a person turns it on). Turned on, {why}. "
                    + ("I can propose turning it on for this project; you confirm it, signed with your name."
                       if may else "A developer or IT turns it on in Settings, Modules."),
                    "#/settings", control="modules",
                    propose=[_proposal("agentobs_enable", project, persona, why)] if may else [])
    if persona not in SEES:
        return _out("The Agent sessions view is for developers and IT: switch persona in the person menu to see it.",
                    None)
    return _mapped(factory, project, persona, route) if current(project) else _unmapped(factory, project, persona,
                                                                                         route)


def _unmapped(factory: Any, project: Any, persona: str, route: str) -> dict:
    hub = from_settings(factory, timeout=2.0)
    if hub is None:
        return _out("No agent observability hub is set yet: IT sets its address in Settings, Agent observability. "
                    "Then the project is mapped to the hub's project for its repository.", "#/settings",
                    control="agent_observability_settings")
    try:
        found = suggest(candidates(project), hub.projects())
    except (HubUnreachable, HubError) as exc:
        return _out(f"The hub did not answer ({exc}); once it runs, map this project on its Agent sessions view.",
                    route, control="agent_sessions_map")
    if found is None or persona not in MAPPERS:
        return _out("This project is not mapped to a project of the hub yet: choose one on its Agent sessions view.",
                    route, control="agent_sessions_map")
    return _out(f"The hub knows this repository as {found['id']} (by {found['from']}). I can propose mapping the "
                "project to it; you confirm it, signed with your name.", route, control="agent_sessions_map",
                propose=[_proposal("agentobs_map", project, persona, f"matched by {found['from']}",
                                   hub_project=found["id"])])


def _figure(sec: dict[str, Any], text: str) -> str:
    return text if sec.get("measured") else "not measured"


def _mapped(factory: Any, project: Any, persona: str, route: str) -> dict:
    v = build(factory, project, persona=persona)
    sec = v.get("sections") or {}
    ses = sec.get("sessions") or {}
    if not ses.get("measured"):
        return _out(f"Agent sessions for {project.meta.get('title')}: not measured: {ses.get('why')}. "
                    f"How: {ses.get('how')}.", route)
    rw, fl, gov, ch = (sec.get(k) or {} for k in ("rework", "failures", "governance", "chain"))
    harnesses = ", ".join(f"{h} {n}" for h, n in sorted((ses.get("totals") or {}).items()))
    top = (rw.get("files") or [{}])[0]
    rate = gov.get("contract_engagement_rate")
    parts = [f"{ses['count']} sessions ({harnesses})",
             "rework hotspots: " + _figure(rw, f"{rw.get('files_above_threshold')} files at or above "
                                                f"{rw.get('threshold')} edits, the most {top.get('file')} "
                                                f"({top.get('edits')})"),
             "unrecovered failures: " + _figure(fl, f"{len(fl.get('unrecovered_sessions') or [])} sessions"),
             "contract read before edit: " + _figure(gov, f"{round((rate or 0) * 100)}% of the sessions that "
                                                          "touched code"),
             "the hub's chain: " + _figure(ch, ("intact" if ch.get("valid") else "BROKEN")
                                           + f" ({ch.get('attests') or 'what it attests is not said'})")]
    return _out(f"Agent sessions for {project.meta.get('title')}: " + "; ".join(parts) + ".", route)
