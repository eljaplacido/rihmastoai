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


def _handoff(pid: str) -> dict[str, Any]:
    """A ready project's useful next step can be in the person's own IDE, not another factory run."""
    return _act("handoff", "Hand off to Claude Code (or another coding agent)", EVERYONE, control="handoff",
                view="overview", to="claude-code", command=f"rihmasto handoff {pid} --to claude-code")


def _model_setup(pid: str) -> list[dict[str, Any]]:
    # Any persona sets a model (FR-MDL1), so anyone may open Models setup from here.
    return [_act("set_up_model", "Open Models setup", EVERYONE, page="models", command="rihmasto models list",
                 where="Models setup (Settings, Models) sets and tests each role's model and key, written to "
                       "kernel/routing.local.json over the shipped kernel/routing.json; `rihmasto doctor` says which "
                       "keys are set; docs/guides/local-models.md runs every role on your own hardware"),
            _advance(pid, "Run again")]


def _raise_cap(pid: str) -> dict[str, Any]:
    return _act("raise_autonomy", "Open the autonomy cap", ("business_owner", "it", "compliance"), control="autonomy",
                view="overview", command=f"rihmasto autonomy set 3 --project {pid} --reason \"...\" --person ... "
                                     "--persona business_owner")


# -- from the records ----------------------------------------------------------------------------------------

def _working(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    if not ctx["running"]:
        return None
    return _situation("working", "the job that runs for it now to end; the page says when it does",
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
    first = "Describe what to improve" if project.meta.get("intent") == "improve" else None
    asked = [q for q in ctx["canon"].questions("open") if q.get("card")]   # which kind of work it is (adopt_kind)
    if asked:
        return _situation("adopted", f"{len(asked)} question(s) answered first: " + asked[0]["text"],
                          [*_question_actions(pid, asked),
                           _settings(pid, "Choose the kind of work in Project settings")])
    return _situation("adopted", "a change, a workspace submission or a decision on an open card",
                      [*_card_actions(ctx["canon"], pid), {**_report(pid), **({"label": first} if first else {})},
                       _act("workspace", "Work on it in your own terminal", ("developer",),
                            command=f"rihmasto workspace open {pid} --person ... --persona developer --agent shell")])


def _halted(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    if not project.meta.get("halted"):
        return None
    pid = project.pid
    return _situation("stopped_by_person", "a person stopped the build: change the plan, or go back a step",
                      [_rewind(pid, "plan"), _settings(pid), _report(pid)])


def _no_material(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    if project.path("source.json").exists() or project.meta.get("source_kind") in ("adopted", "attached"):
        return None                    # an adopted or attached project's material is its repository
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


def _clip(text: str, limit: int = 90) -> str:
    """``text`` cut on a word boundary with an ellipsis, so a cut never leaves another real word ("again")."""
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


def _question_actions(pid: str, qs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for q in qs[:SHOWN]:
        out.append(_act("answer", f"Answer {q['id']}: {_clip(q['text'])}", CARD_DECIDERS["question"], control="answer",
                        view="questions", question=q["id"], card=q.get("card"),
                        command=f"rihmasto answer {pid} {q['id']} \"...\" --person ... --persona ..."))
        if str((q.get("opinions") or {}).get(q["perspective"]) or "").strip():
            out.append(_act("assume", f"Let Rihma assume an answer to {q['id']}", CARD_DECIDERS["question"],
                            control="assume", view="questions", question=q["id"], card=q.get("card"),
                            command=f"rihmasto assume {pid} {q['id']} --person ... --persona ..."))
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
    return [_act("decide", f"Decide {c['id']}: {_clip(c['title'])}", CARD_DECIDERS[c["kind"]], control="decide",
                 view="inbox", card=c["id"], kind=c["kind"],
                 command=f"rihmasto decide {pid} {c['id']} <verdict> --person ... --persona ...")
            for c in cards[:SHOWN]]


def _go_ahead(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    """The look at the spec before the first build (kernel/go_ahead.py): Go or Skip, one click either way."""
    from kernel.canon import deciders_of
    from kernel.go_ahead import open_card

    card = open_card(project)
    if card is None:
        return None
    pid, who = project.pid, deciders_of(card)
    say = {"go": "Go: build it", "skip": "Skip: build without my look"}
    return _situation("go_ahead", "a look at the spec before the first build: Go builds it, Skip builds it without "
                                  "the look", [_act("look_spec", "Look at the spec", EVERYONE, view="spec"),
                                               *[_act(f"go_ahead_{v}", say[v], who, control="go_ahead", card=card["id"],
                                                      verdict=v, command=f"rihmasto decide {pid} {card['id']} {v} "
                                                                         "--person ... --persona ...")
                                                 for v in ("go", "skip")],
                                               _settings(pid, "Build without waiting for me")])


def _cards(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    acts = _card_actions(ctx["canon"], project.pid)
    if not acts:
        return None
    if (ctx["last"] or {}).get("material_read"):     # a plan written before the material: going back is a choice too
        acts.append(_rewind(project.pid, "spec"))
    n = len(acts)
    return _situation("decisions", f"{n} decision{'s' if n != 1 else ''}, made by you or another approver", acts)


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
    if last.get("material_read"):
        return [*_question_actions(pid, [q for q in Canon(project).questions("open") if q.get("card")])[:2],
                _rewind(pid, "spec"), _advance(pid, "Go on with the spec as it is")]
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
                   [_raise_cap(pid), _advance(pid, "Run again once the cap allows")]),
        "failed": ("the step that failed, run again or changed: " + why, _failed(project, why)),
        "done": ("nothing: " + (why or "the last run finished"), [_report(pid), _handoff(pid)]),
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
                      [_report(pid), _handoff(pid)])


def _capped(project: Project, ctx: dict[str, Any]) -> dict[str, Any] | None:
    """A compiled plan the autonomy cap forbids the factory to build: the records say so, with or without the
    last run's result (the command line has none)."""
    from kernel import autonomy

    if not project.path("contract.json").exists() or kr.releases(project) or autonomy.cap_of(project) >= \
            autonomy.BUILD_LEVEL:
        return None
    cap = autonomy.cap_of(project)
    return _situation("capped", f"a higher autonomy cap, or a person to do this step: building needs autonomy level "
                                f"{autonomy.BUILD_LEVEL} ({autonomy.LEVELS[autonomy.BUILD_LEVEL]}); the cap is {cap} "
                                f"({autonomy.LEVELS[cap]})", [_raise_cap(project.pid), _report(project.pid)])


# What a person does to a project between runs: a run's result from before it no longer says what it waits for.
CHANGED_SINCE = ("rewound", "project_changed", "material_added")


def _stale(project: Project, last_started: str | None) -> bool:
    """True when a person went back a step, changed a setting or added material after the last run began."""
    if not last_started:
        return False
    return any(str(r["event"].get("at") or "") > last_started for r in project.ledger().of_kind(*CHANGED_SINCE))


def _paused_automations(project: Project) -> list[dict[str, Any]]:
    """An automation on this project that the circuit breaker paused: what it says, and Resume where it is."""
    from kernel import automations as au

    return [_act("automation_paused", f"Automation {a['id']} ({a['name']}) is paused: {a['paused_why']}",
                 ("it", a["owner"]["persona"]), control="automations_resume", view="automations",
                 command=f"rihmasto automations resume {a['id']} --person ... --persona ...")
            for a in au.automations(project.factory) if a["state"] == "paused" and a.get("paused_by") == "breaker"
            and au.in_scope(project, a["scope"])][:SHOWN]


def _runner_waiting(project: Project) -> list[dict[str, Any]]:
    """A cell runner chosen for this project, or for every project, that waits on IT's card in the factory's Inbox
    (kernel/runners/choice.py): IT approves or declines it on the Runners page. Until then Gnomon runs the cells."""
    from kernel.learn import factory_project

    fp = factory_project(project.factory, False)
    if fp is None or fp.pid == project.pid:
        return []
    cards = [c for c in Canon(fp).cards(kind="runner") if (c.get("refs") or {}).get("project") in (None, project.pid)]
    return [_act("runner_waiting", f"IT decides {c['id']}: {_clip(c['title'])}", CARD_DECIDERS["runner"],
                 control="runners_decide", page=f"runners/{project.pid}", card=c["id"], kind="runner",
                 command=f"rihmasto decide {fp.pid} {c['id']} approve|decline --person ... --persona it")
            for c in cards[:SHOWN]]


def next_step(project: Project, *, last: dict[str, Any] | None = None, running: bool = False,
              last_started: str | None = None) -> dict[str, Any]:
    """What the project waits for, who can act, and the actions that move it forward (see the docstring).
    ``last`` is the result of its last run when the caller has it (a cockpit job's outcome), started at
    ``last_started``: a person's change since then sets it aside. ``running`` says a job runs for it now.
    An automation on it that the circuit breaker paused is said too (kernel/automations.py), and a cell runner
    for it that waits on IT (kernel/runners/choice.py)."""
    from kernel.heal_wiring import next_actions  # an open incident, with its Incidents view (FR-HEAL1)

    out = _next_step(project, last=last, running=running, last_started=last_started)
    more = _paused_automations(project) + _runner_waiting(project) + next_actions(project)
    return dict(out, actions=out["actions"] + more) if more else out


def _next_step(project: Project, *, last: dict[str, Any] | None, running: bool,
               last_started: str | None) -> dict[str, Any]:
    canon = Canon(project)
    if last is not None and _stale(project, last_started):
        last = None
    ctx: dict[str, Any] = {"last": last, "running": running, "canon": canon}
    for read in (_working, _paused, _not_own, _halted, _no_material, _again, _questions, _go_ahead, _cards,
                 _model_down, _capped):
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
                      [_advance(pid), *_question_actions(pid, optional)[:2], _settings(pid), _handoff(pid)])
