"""Never stuck (FR-CHG1): what a project waits for, who can act, and the actions that move it forward.

``next_step(project)`` reads the project's records (and, when the caller has it, the result of its last
run) and answers for any state: a decision card to decide, a question to answer or let the factory
assume, a run that failed with a retry, a step whose input is missing with "add material" or "change
settings", a model endpoint that is not set up with where to set it. Every state the pipeline returns
(``PIPELINE_STATES``, kernel/pipeline.py) maps to at least one action; ``from_run`` maps one result.

Each action names the cockpit control that carries it out (``control``, cockpit/ui_map.json), the
project view it is on, the personas who may take it, and the command line where there is one. Reading
it changes nothing.
"""

from __future__ import annotations

from typing import Any

from kernel import rewind as kr
from kernel.canon import CARD_DECIDERS, Canon
from kernel.people import PERSONAS
from kernel.store import Project

# Every state kernel/pipeline.py (and the holds it asks: kernel/track.py, kernel/autopilot.py,
# kernel/attach.py, kernel/modules.py) returns. A test reads those files and checks the list is whole.
PIPELINE_STATES = ("waiting", "stopped", "apparatus_failure", "progress", "paused", "capped", "failed", "done",
                   "monitoring", "refused")
ADVANCERS = ("business_owner", "product_owner", "developer", "operations", "it")    # kernel/safestop.py MAY_PAUSE
SETTING_UP = ("it", "developer")
LOOKERS = ("business_owner", "product_owner", "developer", "it", "operations", "compliance")  # kernel/track.py
EVERYONE = tuple(PERSONAS)
# The ledger records that show where a run got to; the last of them says whether a model endpoint failed.
PROGRESS = ("apparatus_failure", "intake_done", "intake_rerun", "spec_written", "contract_compiled", "cell_ran",
            "delivered", "release_done", "rewound", "project_changed", "material_added")
SHOWN = 4      # actions of one kind listed, at most


def _act(aid: str, label: str, personas: tuple[str, ...] | list[str], **extra: Any) -> dict[str, Any]:
    return {"id": aid, "label": label, "personas": list(personas), **{k: v for k, v in extra.items() if v is not None}}


def _situation(state: str, waits_for: str, actions: list[dict[str, Any]], basis: str = "records") -> dict[str, Any]:
    who = sorted({p for a in actions for p in a["personas"]}) or ["the factory"]
    return {"state": state, "waits_for": waits_for, "who": who, "actions": actions, "basis": basis}


def _advance(pid: str, label: str = "Advance the project") -> dict[str, Any]:
    return _act("advance", label, ADVANCERS, control="advance", view="overview", command=f"rihmasto run {pid}")


def _settings(pid: str, why: str = "Change the project settings") -> dict[str, Any]:
    return _act("change_settings", why, kr.CHANGERS, control="project_settings", view="overview",
                command=f"rihmasto settings {pid} --kind ... --reason \"...\" --person ... --persona ...")


def _add_material(pid: str) -> dict[str, Any]:
    from kernel.project_material import ADDERS

    return _act("add_material", "Add material", ADDERS, control="add_material", view="overview",
                command=f"rihmasto material add {pid} --text \"...\" --reintake --person ... --persona ...")


def _rewind(pid: str, step: str) -> dict[str, Any]:
    return _act("rewind", f"Go back to the {step} step", kr.CHANGERS, control="rewind_project", view="overview",
                step=step, command=f"rihmasto rewind {pid} --to {step} --reason \"...\" --person ... --persona ...")


def _report(pid: str) -> dict[str, Any]:
    return _act("file_change", "Report a change or a defect", EVERYONE, control="report", view="changes",
                command=f"rihmasto change {pid} \"...\" --person ... --persona ...")


def _model_setup(pid: str) -> list[dict[str, Any]]:
    return [_act("set_up_model", "Set up the model endpoints", SETTING_UP, command="rihmasto doctor",
                 where="`rihmasto doctor` says which endpoint keys are set; kernel/routing.json names each role's "
                       "endpoint; docs/guides/local-models.md runs every role on your own hardware"),
            _advance(pid, "Run again")]


# -- from the records ----------------------------------------------------------------------------------------

def _working(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    if not ctx["running"]:
        return None
    return _situation("working", "a job runs for it now; the page says when it ends",
                      [_act("watch", "Watch the work", EVERYONE, view="tasks"),
                       _act("pause", "Pause at the next safe point", ADVANCERS, control="pause", view="overview")])


def _paused(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    pause = project.meta.get("pause")
    if not pause:
        return None
    return _situation("paused", f"a person to resume it (paused by {pause.get('requested_by')})",
                      [_act("resume", "Resume", ADVANCERS, control="resume", view="overview",
                            command=f"rihmasto resume {project.pid}")])


def _not_own(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    kind, pid = project.meta.get("source_kind"), project.pid
    if kind == "attached":
        return _situation("attached", "a person's command: Rihmasto never builds an attached repository",
                          [_act("repo_gate", "Gate a change", ("developer",), command=f"rihmasto repo gate {pid}"),
                           *_card_actions(ctx["canon"], pid)])
    if kind != "adopted" or project.ledger().of_kind("change_applied"):
        return None
    return _situation("adopted", "a change, a workspace submission or a decision on an open card",
                      [*_card_actions(ctx["canon"], pid), _report(pid)])


def _halted(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    if not project.meta.get("halted"):
        return None
    pid = project.pid
    return _situation("stopped_by_person", "a person stopped the build: change the plan, or go back a step",
                      [_rewind(pid, "plan"), _settings(pid), _report(pid)])


def _no_material(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    if project.path("source.json").exists():
        return None
    pid = project.pid
    if project.read("need.json"):
        return _situation("ready", "its intake, from the need a person validated", [_advance(pid, "Run the intake")])
    return _situation("needs_material", "material: the request, a spec or a folder to read",
                      [_add_material(pid), _settings(pid)])


def _again(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    meta, pid = project.meta, project.pid
    if meta.get("redo_intake"):
        return _situation("intake_again", "its intake to run again over its material",
                          [_advance(pid, "Run the intake again"), _add_material(pid), _settings(pid)])
    if meta.get("reintake_pending"):
        return _situation("intake_again", "the panel to read the material added",
                          [_advance(pid, "Let the panel read the added material"), _settings(pid)])
    return None


def _model_down(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    last = ctx["last"] or {}
    failed = last.get("state") == "apparatus_failure"
    if not failed and not ctx["last"]:
        recs = project.ledger().of_kind(*PROGRESS)
        failed = bool(recs) and recs[-1]["event"]["kind"] == "apparatus_failure"
    if not failed:
        return None
    return _situation("model_not_set_up", "a model endpoint that answers: the last run could not reach one",
                      _model_setup(project.pid))


def _question_actions(pid: str, qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for q in qs[:SHOWN]:
        out.append(_act("answer", f"Answer {q['id']}: {q['text'][:90]}", CARD_DECIDERS["question"], control="answer",
                        view="questions", question=q["id"], card=q.get("card")))
        if str((q.get("opinions") or {}).get(q["perspective"]) or "").strip():
            out.append(_act("assume", f"Let the factory assume {q['id']}", CARD_DECIDERS["question"],
                            control="assume", view="questions", question=q["id"], card=q.get("card")))
    return out


def _questions(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    blocking = [q for q in ctx["canon"].questions("open") if q["blocking"] and q.get("card")]
    if not blocking:
        return None
    pid = project.pid
    return _situation("questions", f"{len(blocking)} blocking question(s) answered, or assumed by a person's choice",
                      [*_question_actions(pid, blocking),
                       _settings(pid, "The questions do not fit? Change the kind of work"),
                       _add_material(pid)])


def _card_actions(canon: Canon, pid: str) -> list[dict[str, Any]]:
    cards = [c for c in canon.cards() if c["kind"] != "question"
             and (c["kind"] != "change" or (c["payload"].get("triage") or {}).get("needs_decision", True))]
    return [_act("decide", f"Decide {c['id']}: {c['title'][:90]}", CARD_DECIDERS[c["kind"]], control="decide",
                 view="inbox", card=c["id"], kind=c["kind"]) for c in cards[:SHOWN]]


def _cards(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    acts = _card_actions(ctx["canon"], project.pid)
    if not acts:
        return None
    return _situation("decisions", f"{len(acts)} decision card(s) decided by the people who may", acts)


# -- from the last run's result --------------------------------------------------------------------------

def _failed(project: Project, why: str) -> list[dict[str, Any]]:
    pid = project.pid
    if "no intake" in why:
        return [_add_material(pid), _settings(pid)]
    if "stopped the build" in why:
        return [_rewind(pid, "plan"), _report(pid)]
    steps = [s for s in ("plan", "spec") if kr.refusal(project, s) is None]
    return [_advance(pid, "Retry"), *[_rewind(pid, s) for s in steps[:1]], _settings(pid), _report(pid)]


def _waiting(project: Project, last: dict[str, Any]) -> list[dict[str, Any]]:
    pid = project.pid
    if last.get("checkpoint"):
        stage = last["checkpoint"]
        return [_act("look_checkpoint", f"Look at the stage {stage} checkpoint", LOOKERS, control="checkpoint_look",
                     view="track", command=f"rihmasto tracking look {pid} {stage} --person ... --persona ...")]
    if last.get("blocked"):
        return [_act("accept_risk", "Fix the findings, or accept a risk until a date", ("it", "compliance"),
                     view="evidence", command=f"rihmasto security status {pid}"), _report(pid)]
    if last.get("sandbox"):
        return [_act("stop_autopilot", "Stop the autopilot, then deliver", ADVANCERS, control="autopilot_stop",
                     view="track")]
    if last.get("attached"):
        return [_act("repo_gate", "Gate a change", ("developer",), command=f"rihmasto repo gate {pid}")]
    return [_advance(pid, "Run on: what it waited on is decided")]


def from_run(project: Project, last: dict[str, Any]) -> dict[str, Any]:
    """What one pipeline result (``kernel.pipeline.advance``) waits for, and its actions."""
    pid, state, why = project.pid, str(last.get("state")), str(last.get("why") or "")
    table: dict[str, tuple[str, list[dict[str, Any]]]] = {
        "waiting": ("what the last run waited on: " + (why or "a person"), []),
        "stopped": ("a person to run it: " + (why or "its autopilot was stopped"), [_advance(pid, "Run it now")]),
        "apparatus_failure": ("a model endpoint that answers: " + why, _model_setup(pid)),
        "progress": ("another run: the last one went as far as one run goes", [_advance(pid, "Run on")]),
        "paused": ("a person to resume it", [_act("resume", "Resume", ADVANCERS, control="resume", view="overview")]),
        "capped": ("a higher autonomy cap, or a person to do this step: " + why,
                   [_act("raise_autonomy", "Open the autonomy cap", ("business_owner", "it", "compliance"),
                         control="autonomy", view="overview"), _advance(pid, "Run again once the cap allows")]),
        "failed": ("the step that failed, run again or changed: " + why, _failed(project, why)),
        "done": ("nothing: " + (why or "the last run finished"), [_report(pid)]),
        "refused": ("a local model for each role: the project is confidential and " + (why or "a role is hosted"),
                    _model_setup(pid) + [_settings(pid, "Change the project settings")]),
        "monitoring": ("its probes: " + why, [_act("watch", "Watch its releases", EVERYONE, view="releases"),
                                              _report(pid)]),
    }
    waits, actions = table.get(state, (f"a person to look at the last run ({state})", [_advance(pid, "Run again")]))
    if state == "waiting":
        actions = _waiting(project, last)
    if state == "done" and last.get("stopped_by_modules"):
        actions = [_act("turn_on_module", "Turn on the next module", ("it", "business_owner", "developer"),
                        control="modules", page="settings"), _report(pid)]
    return _situation(state if state in PIPELINE_STATES else "unknown", waits, actions, "last run")


def _released(project: Project) -> dict[str, Any] | None:
    rels = kr.releases(project)
    if not rels:
        return None
    pid = project.pid
    rel = project.read(f"releases/{rels[-1]}.json") or {}
    if rel.get("state") == "failed":
        return _situation("release_failed", f"release {rels[-1]} stopped: run it again, or change what it does",
                          [_advance(pid, "Retry the delivery"), _report(pid)])
    return _situation("live", f"nothing: release {rels[-1]} is out; a change goes round the change loop",
                      [_report(pid)])


def next_step(project: Project, *, last: dict[str, Any] | None = None, running: bool = False) -> dict[str, Any]:
    """What the project waits for, who can act, and the actions that move it forward (see the docstring).
    ``last`` is the result of its last run when the caller has it (a cockpit job's outcome); ``running``
    says a job runs for it now."""
    canon = Canon(project)
    ctx: dict[str, Any] = {"last": last, "running": running, "canon": canon}
    for read in (_working, _paused, _not_own, _halted, _no_material, _again, _questions, _cards, _model_down):
        found = read(project, ctx)
        if found is not None:
            return found
    if last and last.get("state") in PIPELINE_STATES and last.get("state") != "done":
        return from_run(project, last)
    released = _released(project)
    if released is not None:
        return released
    if last:
        return from_run(project, last)
    pid = project.pid
    optional = [q for q in canon.questions("open") if q.get("card")]
    return _situation("ready", "the next step: nothing waits on a person",
                      [_advance(pid), *_question_actions(pid, optional)[:2], _settings(pid)])
