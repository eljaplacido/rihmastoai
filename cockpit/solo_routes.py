"""Solo mode in the cockpit: a write signed with the persona it needs, and the Inbox through every persona
(D-0024 item 4, FR-PPL1, kernel/solo.py).

A write whose body says ``"as_needed": true`` (the page sends it while a person views "everything") is
signed with the persona that write needs among those the person holds: in solo mode every persona, in team
mode those granted on the project. ``NEEDS`` says, for **every** write route, which personas may make it, from
the same lists the kernel checks (tests/test_wiring_r3.py keeps it whole): ``HELD`` for a write any persona
makes, which keeps the persona sent when the person holds it (a change or a signal keeps its source's persona).
The persona chosen is the one sent when it fits, else the first of the list the person holds. A body that
names its persona without ``as_needed`` is never changed, and IT's access file keeps explicit personas.

``inbox`` is the Inbox with ``?persona=*``: every open card the person may decide in any persona they hold,
each with ``decide_as``, the persona its decision will be signed with.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

from kernel import adopt_stated, feedback, heal_fix, immune, role_evals
from kernel import agentobs as kobs
from kernel import automations as kau
from kernel import autonomy as kautonomy
from kernel import console as kconsole
from kernel import embeds as kembeds
from kernel import harness_enforcement as kenf
from kernel import enforcement as kenforcement
from kernel import evidence_pack as kevidence
from kernel import gnomon_evals as ge
from kernel import gnomon_evals_run as gr
from kernel import modules as kmodules
from kernel import outputs as koutputs
from kernel import posture as kposture
from kernel import project_material as kadded
from kernel import rewind as krewind
from kernel import solo as ksolo
from kernel import track as ktrack
from kernel.agentops_optimise import AUDITORS as AGENT_AUDITORS
from kernel.canon import CARD_DECIDERS, Canon, deciders_of
from kernel.checks import ENABLERS as CHECK_ENABLERS
from kernel.checks.store import check_of
from kernel.data_stores import CLEANERS
from kernel.delegation import delegations
from kernel.destinations_cli import DELIVERERS
from kernel.itdata_actions import CHECKERS as ITD_CHECKERS   # integrations and data (FR-ITD1)
from kernel.itdata_actions import DISABLERS as ITD_DISABLERS
from kernel.itdata_actions import REMINDERS as ITD_REMINDERS
from kernel.people import PERSONAS
from kernel.project_archive import ARCHIVERS
from kernel.publish import PUBLISHERS
from kernel.safestop import MAY_PAUSE
from kernel.team import ADMINS

Needs = Callable[[Any, dict[str, str], dict[str, Any]], tuple[str, ...]]


def _fixed(personas: tuple[str, ...]) -> Needs:
    return lambda factory, groups, body: tuple(personas)


def _held(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """Any persona may make this write: the one sent is kept when the person holds it."""
    return PERSONAS


HELD: Needs = _held
IT_ONLY = _fixed(("it",))
# Who reads a folder (kernel/source_guard.py READERS); IT first for allowing one, as IT's access file wants.
READERS = ("business_owner", "product_owner", "developer", "it")


def _card(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    try:
        return tuple(deciders_of(Canon(factory.project(groups["pid"])).get_card(groups["cid"])))
    except (KeyError, OSError, ValueError):
        return ()


def _question(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """A question put to a person through a card: that card's deciders; else anyone answers or assumes."""
    try:
        canon = Canon(factory.project(groups["pid"]))
        q = canon.question(groups["qid"])
        return tuple(deciders_of(canon.get_card(q["card"]))) if q.get("card") else CARD_DECIDERS["question"]
    except (KeyError, OSError, ValueError):
        return CARD_DECIDERS["question"]


def _revoke(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """A delegation is revoked by a persona that decides one of its kinds (kernel/delegation.py may_revoke)."""
    try:
        d = next(x for x in delegations(factory.project(groups["pid"])) if x["id"] == groups["did"])
    except (KeyError, OSError, ValueError, StopIteration):
        return PERSONAS
    return tuple(dict.fromkeys(p for k in d.get("kinds") or [] for p in CARD_DECIDERS.get(k, ())))


def _automation(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """The personas the automation's action allows (kernel/automations.py ACTIONS): the draft's, or the kept one's."""
    spec = body.get("automation") if isinstance(body.get("automation"), dict) else None
    try:
        spec = spec or kau.get(factory, groups["aid"])
        return tuple(kau.ACTIONS[spec["action"]["kind"]]["personas"])
    except (KeyError, OSError, TypeError, ValueError):
        return PERSONAS


def _console(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """The personas the project's console allows (kernel/console.py settings)."""
    try:
        return tuple(kconsole.settings(factory.project(groups["pid"]))["personas"])
    except (KeyError, OSError, ValueError):
        return kconsole.DEFAULT_PERSONAS


def _runs_code(factory: Any, groups: dict[str, str], runs_code: bool, enablers: tuple[str, ...]) -> tuple[str, ...]:
    return _console(factory, groups, {}) if runs_code else enablers


def _check(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """A check that runs code is the console's personas'; the others, the checks' enablers (kernel/checks)."""
    try:
        check, _ = check_of(unquote(groups.get("key") or str(body.get("key") or "")))
    except ValueError:
        return CHECK_ENABLERS
    return _runs_code(factory, groups, check.runs_code, CHECK_ENABLERS)


def _eval(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """A Gnomon audit that runs code is the console's personas'; the others, the evals' enablers."""
    try:
        ev = ge.find(groups["eid"])
    except (KeyError, ValueError):
        return gr.ENABLERS
    return _runs_code(factory, groups, ev.runs_code, gr.ENABLERS)


def _pull_request(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """Rihmasto's own repository: IT (or the solo person, kernel/heal_approval.py); a project's, its approvers."""
    try:
        target = heal_fix.get(factory, groups["fid"])["target"]
    except (KeyError, OSError, ValueError):
        return heal_fix.PROJECT_APPROVERS
    return heal_fix.RIHMASTO_APPROVERS if target == "rihmasto" else heal_fix.PROJECT_APPROVERS


NEEDS: dict[str, Needs] = {
    "post_decide": _card,
    "post_pause": _fixed(MAY_PAUSE), "post_resume": _fixed(MAY_PAUSE), "post_advance": _fixed(MAY_PAUSE),
    "post_autopilot_start": _fixed(MAY_PAUSE), "post_autopilot_stop": _fixed(MAY_PAUSE),
    "put_settings": _fixed(krewind.CHANGERS), "post_rewind": _fixed(krewind.CHANGERS),
    "post_settings_preview": _fixed(krewind.CHANGERS),
    "post_material": _fixed(kadded.ADDERS),
    "put_autonomy": _fixed(kautonomy.SETTERS), "put_project_autonomy": _fixed(kautonomy.SETTERS),
    "put_posture": _fixed(kposture.SETTERS), "post_posture_preview": _fixed(kposture.SETTERS),
    "post_evidence_export": _fixed(kevidence.EXPORTERS), "post_pack_build": _fixed(kevidence.EXPORTERS),
    "put_outputs": _fixed(koutputs.CHOOSERS), "post_outputs_build": _fixed(koutputs.BUILDERS),
    "post_embed": _fixed(kembeds.CREATORS), "post_embed_revoke": _fixed(kembeds.CREATORS),
    "post_comment_promote": _fixed(("product_owner", "business_owner")),
    "post_concept_edit": _fixed(CARD_DECIDERS["concept"]),
    "post_plan_requirement": _fixed(CARD_DECIDERS["approval"]),
    "put_tracking": _fixed(ktrack.SETTERS), "post_checkpoint_look": _fixed(ktrack.LOOKERS),
    "put_modules": _fixed(kmodules.SETTERS), "put_project_modules": _fixed(kmodules.SETTERS),
    "put_road": IT_ONLY, "put_project_road": IT_ONLY, "put_model": IT_ONLY, "post_model_remove": IT_ONLY,
    "post_models_use": IT_ONLY, "post_models_use_local": IT_ONLY, "post_model_test": IT_ONLY, "put_runner": IT_ONLY,
    # questions and assumptions, delegations (the earlier routes it missed)
    "post_answer": _question, "post_assume": _question, "post_settle": _fixed(CARD_DECIDERS["question"]),
    "post_delegation_revoke": _revoke,
    # automations (kernel/automations.py ACTIONS: each action names who may have it)
    **{name: _automation for name in ("post_automation", "put_automation", "post_automation_preview",
                                      "post_automation_pause", "post_automation_resume", "post_automation_remove",
                                      "post_automation_run", "post_automation_dry_run")},
    # folders, adoption and an adopted project's own commands
    "post_adopt": _fixed(READERS), "post_source_preview": _fixed(READERS), "post_source_scan": _fixed(READERS),
    "post_source_scan_cancel": _fixed(READERS),
    "post_source_root": _fixed(("it", *READERS[:3])), "post_source_root_remove": _fixed(("it", *READERS[:3])),
    "post_baseline_stated": _fixed(adopt_stated.RUNNERS),
    # checks, the console and Gnomon's audits (code that runs is the console's personas')
    "post_check_enable": _check, "post_check_disable": _check, "post_check_run": _check, "post_checks_enable": _check,
    "post_console_run": _console, "post_console_stop": _console, "post_console_terminal": _console,
    "put_console_settings": _fixed(kconsole.SETTERS),
    "post_eval_run": _eval, "post_role_evals_run": _fixed(role_evals.ENABLERS),
    # agent observability (FR-OBS1)
    "put_agent_observability": _fixed(kobs.SETTERS), "post_agent_sessions_map": _fixed(kobs.MAPPERS),
    "post_agent_sessions_snapshot": _fixed(kobs.MAPPERS),
    # self-healing (FR-HEAL1): approvals by those who may approve, or the solo person
    "post_fix_pr": _pull_request, "post_remedy_approve": _fixed(immune.APPROVERS),
    "post_remedy_retire": _fixed(immune.APPROVERS), "post_feedback_settle": _fixed(feedback.APPROVERS),
}
# Settings > People and access (cockpit/people_routes.py): only IT changes who works here.
NEEDS.update({name: _fixed(ADMINS) for name in (
    "post_people_mode", "post_people_user", "put_people_user", "post_people_link", "post_people_group",
    "post_people_role", "put_people_views", "put_people_idp", "post_people_keys", "post_people_test_token")})
# Writes any persona makes: the persona sent is kept (a change, a signal or a comment keeps its source's).
NEEDS.update({name: HELD for name in (
    "post_project", "post_profile_propose", "post_shape", "post_shape_say", "post_shape_attach", "post_shape_create",
    "put_shape_draft", "post_signal", "post_signal_triage", "post_change", "post_comment", "post_assistant",
    "put_layout", "post_link", "post_watch", "post_areas", "post_assessment", "post_assessment_changes",
    "post_repo_alignment_scan", "post_repo_alignment_decide", "put_project_tags", "post_review_done",
    "post_review_mark", "put_review_digest", "post_walkthrough", "post_walkthrough_reply", "post_walkthrough_confirm",
    "post_walkthrough_cancel", "post_channel", "post_channel_pause", "post_channel_resume", "post_channel_settle",
    "post_handoff", "post_agent_persona", "post_people_solo", "post_eval_finding_change", "post_incident",
    "post_incident_investigate", "post_incident_remedy", "post_incident_resolve", "post_incident_fix",
    "post_feedback")})


# The stable line's writes (merged): each signed with the persona its own kernel rule needs.

NEEDS.update({
    "post_data_apply": _fixed(CLEANERS), "post_data_cleanup": HELD, "post_destinations_check": _fixed(DELIVERERS),
    "post_destinations_deliver": _fixed(DELIVERERS), "post_publish": _fixed(PUBLISHERS),
    "post_project_archive": _fixed(ARCHIVERS), "post_project_restore": _fixed(ARCHIVERS),
    "post_project_remove": _fixed(ARCHIVERS), "post_project_setup": HELD,
    "post_itdata_check": _fixed(ITD_CHECKERS), "post_itdata_disable": _fixed(ITD_DISABLERS),
    "post_itdata_rotate": _fixed(ITD_REMINDERS),
    "post_suggestion_accept": NEEDS["post_automation"], "post_suggestion_dismiss": NEEDS["post_automation"],
    "post_automation_compose": NEEDS["post_automation"], "post_assessment_cancel": HELD, "post_journey_guide": HELD,
    "post_pick_cancel": HELD, "post_pick_native": HELD, "post_pick_recent": HELD, "put_graph_prefs": HELD,
    "put_view_layouts": HELD})
# Never lost and decision triage (FR-NVL1): a triage's confirm keeps the persona sent (each card is checked against
# who may decide it); Gnomon's enforcement is set by its setters.
NEEDS.update({"post_triage_assume": HELD, "put_harness_enforcement": _fixed(kenf.PLATFORM_SETTERS),
              "put_project_harness_enforcement": _fixed(kenf.PROJECT_SETTERS)})
# Agent operations (FR-AOP1): the AI architect first, or another persona that audits the agents.
NEEDS.update({"post_agent_ops_audit": _fixed(AGENT_AUDITORS), "post_agent_ops_change": _fixed(AGENT_AUDITORS)})
NEEDS["post_agent_ops_price"] = _fixed(AGENT_AUDITORS)     # a model's price (FR-AOP2)
NEEDS["post_dev_seen"] = HELD      # a person's look at the development briefing, in their own persona (FR-DEV1)
# Enforcement levels per environment (cockpit/enforcement_routes.py, FR-ENF1): those who may set a level.
NEEDS.update({name: _fixed(kenforcement.SETTERS) for name in (
    "put_enforcement", "put_project_enforcement", "post_enforcement_preview")})


def _hitl_answer(factory: Any, groups: dict[str, str], body: dict[str, Any]) -> tuple[str, ...]:
    """An ask is answered as the persona it is put to (kernel/hitl.py, FR-HITL1)."""
    from kernel import hitl

    try:
        return (hitl.get(factory.project(groups["pid"]), str(body.get("ask") or ""))["to"]["persona"],)
    except (KeyError, OSError, ValueError):
        return PERSONAS


# People in the loop (cockpit/hitl_routes.py, FR-HITL1): anyone asks, sends and nudges; the persona put to answers.
NEEDS.update({"post_hitl_ask": HELD, "post_hitl_send": HELD, "post_hitl_nudge": HELD, "post_hitl_answer": _hitl_answer,
              "post_hitl_link": _fixed(("product_owner", "business_owner", "it", "compliance")),
              "post_hitl_link_revoke": _fixed(("product_owner", "business_owner", "it", "compliance")),
              "put_hitl_enforcement": _fixed(("business_owner", "product_owner", "compliance", "it")),
              "put_hitl_channels": IT_ONLY})


def as_needed(api: Any, name: str, groups: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    """``body`` signed with the persona the write needs, when it asked for that; otherwise as sent."""
    if not body.pop("as_needed", False) or not ksolo.chooses(api.access):
        return body
    pid = groups.get("pid") or "_factory"
    holding = ksolo.held(api.access, api.identity, pid)
    needs = NEEDS.get(name, HELD)
    allowed = holding if needs is HELD else needs(api.factory, groups, body)
    chosen = ksolo.decide_as(allowed, holding, body.get("persona") if isinstance(body.get("persona"), str) else None)
    return body | {"persona": chosen} if chosen else body


def inbox(api: Any, pid: str | None = None) -> dict[str, Any]:
    """Every open card the person may decide in any persona they hold, across the projects they see (one
    project's, with ``pid``), each with the persona its decision will be signed with."""
    from cockpit.server import _factory_label

    projects = [api._project(pid)] if pid else api.factory.projects()
    cards = []
    for p in projects:
        canon = Canon(p)
        holding = ksolo.held(api.access, api.identity, p.pid)
        for c in canon.cards(state="open"):
            persona = ksolo.decide_as(deciders_of(c), holding)
            if persona is None:
                continue
            view = api._card_view(c, canon)
            view.update(project=p.pid, project_title=_factory_label(p.pid, p.meta.get("title", p.pid)),
                        decide_as=persona)
            cards.append(view)
    return {"persona": ksolo.EVERY, "cards": cards, "count": len(cards)}
