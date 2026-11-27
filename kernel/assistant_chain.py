"""The by-rule answerers Ask Rihma tries first, in order, before the map of areas (kernel/assistant.py ask).

Each answerer returns an answer when the question is its own, or None. Kept here so the assistant's ask() stays
small as features add answerers: a new one is a line in ``first``.

Two answerers take the owner's "consult Claude Code on how to sync with Rihmasto and what to monitor": the agent
channel (FR-CHN2) posts a request to a coding agent, and the sync plan (FR-LND2) says from the records how to keep
that agent in sync and what to watch. In Ask Rihma, a question that names a coding agent and asks both how to sync
and what to monitor is the plan's: Rihma has that answer itself, each step a button, and nothing is written. Any
other request to a coding agent ("ask Claude Code how we should sync") is posted to it; in the channel panel every
request goes to the agent.
"""
from __future__ import annotations

import re
from typing import Any

from kernel import agent_sync_chat as sync_plan_q
from kernel import agentops_chat as agentops_q
from kernel import (
    alignment_triage_chat,
    health_chat,
    hitl_chat,
    models_chat,
    neverlost_chat,
    observe_chat,
    start_here_chat,
)
from kernel import asks_chat as asks_q
from kernel import assess_headline as assess_q
from kernel import channel_consult_chat as consult_q
from kernel import devask as dev_q
from kernel import epic_chat as epic_q
from kernel import handoff_chat as handoff_q
from kernel import itdata_chat as itdata_q
from kernel import itops_chat as itops_q
from kernel import native_chat as native_q
from kernel import structure_chat as structure_q
from kernel import teams_chat as teams_q
from kernel import wip_chat as wip_q
from kernel.agentobs import ask as agentobs_q
from kernel.gnomon_posture import ask as gnomon_posture_q

MONITOR = re.compile(r"\b(?:monitor\w*|what to watch|keep track)\b", re.IGNORECASE)


def sync_plan(factory: Any, question: str, project: Any) -> dict | None:
    """The sync plan when the question names a coding agent and asks how to sync it and what to monitor."""
    if not MONITOR.search(question or ""):
        return None
    return sync_plan_q.answer(factory, project, question)


def first(factory: Any, question: str, project: Any, persona: str, view: str | None,
          holding: tuple[str, ...] | None = None) -> dict | None:
    """The first by-rule answer to the question, or None when none of these answerers takes it. An alignment item's
    triage (FR-ORG1) answers whatever is asked on the Alignment view; elsewhere it is beside the answer it shares."""
    triage = alignment_triage_chat.answer(factory, project, question, view, persona)   # alignment items (FR-ORG1)
    if triage and view == "align":
        return triage
    own = _own(factory, question, project, persona, view, holding)
    if own and triage and "align_triage" in triage:     # both read it: its answer, the triage's proposals beside
        return own | {"align_triage": triage["align_triage"], "propose": [*own.get("propose", []), *triage["propose"]]}
    return own or triage


def by_area(factory: Any, project: Any, question: str, view: str | None, persona: str,
            person: str | None) -> dict | None:
    """Ask Rihma's answers by rule for a coding agent as the model, observer links, never lost, Start here, development
    and people in the loop, in that order."""
    return (models_chat.answer(question, persona)   # "use Claude Code as the model": Models setup (FR-SET1)
            or health_chat.answer(factory, question, project, persona)   # health, failures, checks (FR-CHK1)
            or observe_chat.answer(factory, question, project, persona, person)   # observer links (FR-SHR1)
            or neverlost_chat.answer(factory, project, question, view, persona)   # why, triage, who (FR-NVL1)
            or start_here_chat.answer(factory, project, question, persona, person)   # start here, a task (FR-LND1)
            or handoff_q.answer(project, question)   # "hand off ...": the hand-off dialog, their place (FR-BRG1)
            or dev_q.answer(factory, project, question, person=person, persona=persona)   # development (FR-DEV1)
            or epic_q.answer(factory, project, question, persona)   # epics and what they hold (FR-S2)
            or hitl_chat.answer(factory, question, project, persona))   # people in the loop (FR-HITL1)


def agentops_first(factory: Any, question: str, project: Any, persona: str,
                   holding: tuple[str, ...] | None) -> dict | None:
    """Agent operations before a goal plan takes "run the optimise audit" (FR-AOP3); a question about the IDE agents'
    sessions is still the agent observability hub's first."""
    return None if agentobs_q.asks(question) else agentops_q.answer(factory, question, project, persona,
                                                                    holding=holding)


def _own(factory: Any, question: str, project: Any, persona: str, view: str | None,
         holding: tuple[str, ...] | None) -> dict | None:
    answerers = (
        lambda: gnomon_posture_q.answer(factory, question, project, persona),   # Gnomon posture (FR-GNP1)
        lambda: assess_q.answer(factory, question, project, persona, view=view),   # the assessment (FR-ASP1)
        lambda: sync_plan(factory, question, project),   # how to sync a named agent and what to monitor (FR-LND2)
        lambda: asks_q.answer(factory, question, project, persona),   # agents on machines, reach (XAG1)
        lambda: consult_q.answer(factory, project, question, persona),   # ask a coding agent, sync (FR-CHN2)
        lambda: agentops_first(factory, question, project, persona, holding),   # the optimise audit (FR-AOP3)
        lambda: itdata_q.answer(factory, question, project, persona),   # integrations and data (FR-ITD1)
        lambda: itops_q.answer(factory, question, project, persona),   # what IT checks (FR-ITO1)
        lambda: native_q.answer(factory, question, project, persona),   # its own sources (FR-SRC1)
        lambda: wip_q.answer(factory, question, project, persona),   # its work in progress (FR-WIP1)
        lambda: structure_q.answer(factory, question, project, persona, holding=holding),   # its structure (FR-STR1)
        lambda: teams_q.answer(factory, question, project, persona, holding=holding),   # teams, words, scope (FR-TM1)
    )
    for answer in answerers:
        about = answer()
        if about:   # the same test as ``about or ...`` in ask()
            return about
    return None
