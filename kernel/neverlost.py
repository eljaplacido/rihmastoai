"""Never lost (FR-NVL1): why a view, a figure or a step is empty, not measured or failing, and the step that fills it.

The owner (2026-11-25): "If I get some null results on any views ... if there is a missing KPI, missing
visualization, the agents of Rihmasto will always get me back on track."

Every empty state, every "not measured" value, every error box and every failed action in the cockpit carries
"Why? Ask Rihma". It opens Ask Rihma with its context (the view, the field, the project, the words on screen) and
Rihma answers **by rule**, no model asked, from three things:

1. the catalogue below, keyed by view (``VIEW_RULES``: the first rule whose condition holds for the project's own
   state) and by the field's words (``FIELD_RULES``: tokens, cost, tests, evals, releases ...);
2. the record's own basis strings, as the page showed them ("the run recorded no token counts"), quoted back;
3. for an error, its message, classified (``ERROR_RULES``: a persona not granted, no model, a paused project ...).

The answer says why in plain words and offers the step that fills it as a button (``fill``: a view and a control,
Take me there). The same answer comes from a typed question ("why is Insights empty?", ``chat_answer``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

KINDS = ("empty", "not_measured", "error")
Facts = dict[str, Any]
Step = tuple[str, str, str | None]          # label, view, control

_RUN = ("Go on with the project", "overview", "next_step")


def facts(project: Any) -> Facts:
    """What the rules look at: the project's stage, its questions, spec, tasks, releases and open cards."""
    if project is None:
        return {"project": False}
    from kernel.canon import Canon

    canon = Canon(project)
    spec = project.read("spec.json") or {}
    tasks = project.read("tasks.json") or {}
    open_q = canon.questions("open")
    kinds = [e["event"].get("kind") for e in project.ledger().of_kind("release_done", "model_run", "gate")]
    return {"project": True, "stage": int(project.meta.get("stage") or 1), "questions": len(canon.questions()),
            "open_questions": len(open_q), "blocking": sum(1 for q in open_q if q.get("blocking")),
            "requirements": len(spec.get("requirements") or []), "tasks": len(tasks),
            "merged": sum(1 for t in tasks.values() if (t or {}).get("status") == "merged"),
            "released": kinds.count("release_done"), "model_runs": kinds.count("model_run"),
            "gates": kinds.count("gate"), "cards": len(canon.cards(state="open")),
            "adopted": project.meta.get("source_kind") in ("adopted", "attached"),
            "assumptions": len(canon.assumptions())}


def _f(key: str, op: str = ">", n: int = 0) -> Callable[[Facts], bool]:
    ops = {">": lambda a: a > n, "==": lambda a: a == n, "<": lambda a: a < n}
    return lambda f: bool(f.get("project")) and ops[op](int(f.get(key) or 0))


def _no(key: str) -> Callable[[Facts], bool]:
    return _f(key, "==", 0)


ALWAYS: Callable[[Facts], bool] = lambda f: True     # noqa: E731
OUTSIDE: Callable[[Facts], bool] = lambda f: not f.get("project")     # noqa: E731

# view -> [(when, why, step)]: the first whose condition holds answers.
VIEW_RULES: dict[str, list[tuple[Callable[[Facts], bool], str, Step]]] = {
    "inbox": [(_no("cards"), "nothing waits on a decision: every card is decided, delegated or not opened yet",
               ("See what happens next", "overview", "next_step"))],
    "questions": [(_no("questions"), "the project has not been read yet, so it has asked nothing", _RUN),
                  (_no("open_questions"), "every question is answered or assumed", ("See the assumptions",
                                                                                     "assumptions", None))],
    "assumptions": [(_no("assumptions"), "no question was answered by Rihma itself: people answered them, or "
                                         "none was asked yet", ("Open the questions", "questions", "answer"))],
    "spec": [(_f("blocking"), "the requirements wait on questions that block them", ("Answer the questions",
                                                                                       "questions", "answer")),
             (_no("requirements"), "the requirements are written once the questions are settled", _RUN)],
    "plan": [(_f("blocking"), "the plan waits on questions that block it", ("Answer the questions", "questions",
                                                                              "answer")),
             (_no("requirements"), "there is no plan before the requirements are written", _RUN)],
    "tasks": [(_no("requirements"), "the work is cut into tasks after the plan is approved", ("Open the plan",
                                                                                               "plan", None)),
              (_no("tasks"), "the contract is compiled but no task has started", _RUN)],
    "cell": [(_no("tasks"), "no task has been built yet, so no build attempt is recorded", ("Open the tasks",
                                                                                             "tasks", None))],
    "releases": [(_no("merged"), "a release is cut once the work passed its quality checks; none has yet",
                  ("Open the tasks", "tasks", None)),
                 (_no("released"), "work is accepted but nothing has been released yet", ("Start a release",
                                                                                          "releases", "build_pack"))],
    "try": [(_no("released"), "there is nothing to try before a release", ("Open Releases", "releases", None))],
    "evidence": [(_no("gates"), "proof is recorded when work passes its quality check; nothing has yet",
                  ("Open the tasks", "tasks", None))],
    "insights": [(_no("model_runs"), "figures are computed from the runs, and no run is recorded here yet", _RUN)],
    "track": [(_no("tasks"), "progress is tracked against tasks, and there are none yet", ("Open the plan", "plan",
                                                                                            None))],
    "changes": [(ALWAYS, "no one has asked for a change to this project", ("Ask for a change", "changes", "report"))],
    "outputs": [(ALWAYS, "no place to deliver the results is chosen yet", ("Choose outputs", "outputs",
                                                                           "choose_outputs"))],
    "automations": [(ALWAYS, "no automation is set up for this project", ("Start from a template", "automations",
                                                                          "automations_template"))],
    "checks": [(ALWAYS, "no health check is switched on here", ("Open Health", "checks", "health_enable"))],
    "assessment": [(ALWAYS, "the code has not been assessed yet", ("Assess now", "assessment", "run_assessment"))],
    "align": [(ALWAYS, "the code has not been compared with the plan yet", ("Compare now", "align", "align_scan"))],
    "agents": [(ALWAYS, "no agent or person has posted on this project's channel yet", ("Hand the work to an agent",
                                                                                        "overview", "handoff"))],
    "incidents": [(ALWAYS, "nothing went wrong here: no incident is recorded", ("Open Overview", "overview", None))],
    "review": [(ALWAYS, "nothing happened since you last looked", ("Open Overview", "overview", None))],
    "console": [(ALWAYS, "no command was run in the project's folder yet", ("Open the console", "console",
                                                                            "console_run"))],
    "projects": [(ALWAYS, "no project exists yet", ("Start a new project", "projects", "new_project"))],
    "square": [(ALWAYS, "no need or signal has been logged yet", ("Log a signal", "square", "log_signal"))],
    "catalogue": [(ALWAYS, "nothing has been released yet, so nothing is listed as built", ("Open Projects",
                                                                                            "projects", None))],
    "jobs": [(lambda f: bool(f.get("interrupted")), "a run was interrupted when the cockpit restarted: Jobs lists it "
              "as interrupted, with Run it again", ("Open Jobs", "jobs", None)),
             (ALWAYS, "no job was started from this cockpit yet", ("Open Projects", "projects", None))],
    "automations_all": [(ALWAYS, "no automation is set up yet, for the platform or any project", (
        "Start from a template", "automations_all", "automations_template"))],
    "health_all": [(ALWAYS, "no check is enabled yet, so nothing is measured: enable one below", ("Enable a check",
                                                                                                   "health_all",
                                                                                                   "health_enable"))],
    "inbox_all": [(ALWAYS, "no card waits on your persona in any project", ("Open Projects", "projects", None))],
    "models": [(ALWAYS, "no model is set for that role yet", ("Set a model", "models", "models_set"))],
}


def _n(f: Facts, key: str, word: str) -> str:
    n = int(f.get(key) or 0)
    return f"{n} {word}{'' if n == 1 else 's'}"


# view -> what it shows when no rule above holds: its own records say it is not empty, so the answer says what is
# there instead of taking the question's premise ("why is Releases empty?" on a project with releases).
SHOWS: dict[str, Callable[[Facts], str]] = {
    "inbox": lambda f: _n(f, "cards", "open decision"),
    "questions": lambda f: f"{_n(f, 'questions', 'question')}, {int(f.get('open_questions') or 0)} still open",
    "assumptions": lambda f: _n(f, "assumptions", "assumption"),
    "spec": lambda f: _n(f, "requirements", "requirement"),
    "plan": lambda f: f"the plan for {_n(f, 'requirements', 'requirement')}",
    "tasks": lambda f: f"{_n(f, 'tasks', 'task')}, {int(f.get('merged') or 0)} accepted",
    "cell": lambda f: f"the build attempts of {_n(f, 'tasks', 'task')}",
    "releases": lambda f: _n(f, "released", "release"),
    "try": lambda f: f"what {_n(f, 'released', 'release')} delivered",
    "evidence": lambda f: f"the proof of {_n(f, 'gates', 'quality check')}",
    "insights": lambda f: f"figures from {_n(f, 'model_runs', 'recorded run')}",
    "track": lambda f: f"progress on {_n(f, 'tasks', 'task')}, {int(f.get('merged') or 0)} accepted",
}

# words of a field -> (why, step): a figure that is empty or not measured whatever view shows it.
FIELD_RULES: list[tuple[tuple[str, ...], str, Step]] = [
    (("token", "cost", "spend", "usage", "price", "€", "$"), "the runs recorded no token counts or prices: a model "
     "endpoint that reports usage fills it on the next run", ("Open Models setup", "models", "models_open")),
    (("eval", "audit"), "no eval has run for it yet", ("Run the evals", "checks", "evals_run")),
    (("test", "coverage", "suite", "pass rate"), "no test run is recorded for it yet", ("Run the checks", "checks",
                                                                                         "health_run")),
    (("release", "deploy", "production"), "nothing has been released yet", ("Open Releases", "releases",
                                                                                     None)),
    (("gate", "quality", "retries", "retry", "rounds"), "no work has passed through the quality check yet",
     ("Open the tasks", "tasks", None)),
    (("session", "agent", "ide", "hook"), "no coding agent reported to Rihmasto yet", ("Set up AI tools",
                                                                                         "overview", "ide_setup")),
    (("finding", "risk", "assessment"), "the code has not been assessed yet", ("Assess now", "assessment",
                                                                               "run_assessment")),
    (("check", "probe", "health"), "no health check is switched on here, so nothing has been checked yet",
     ("Open Health", "checks", "health_enable")),
    (("incident", "resolve", "resolved"), "no incident has been resolved here yet, so there is no time to measure",
     ("Open Incidents", "incidents", None)),
    (("time", "duration", "lead time"), "a time is measured from finished work, and none has finished yet", _RUN),
]

# an error's words -> (why, step)
ERROR_RULES: list[tuple[str, str, Step]] = [
    # the system's failures and damaged records first (FR-NVL3): the file is named in the message, never a bug
    (r"disk is full|no space left|enospc", "the disk is full, so nothing was recorded: free some space, then try again",
     ("Back to the view", "", None)),
    (r"read-only|permission denied|errno 13|in use by another program", "a file Rihmasto writes is read-only or held "
     "by another program, so nothing was recorded: make it writable (or close that program), then try again",
     ("Back to the view", "", None)),
    (r"cannot be read|not valid json|expecting value", "a record file is damaged and cannot be read (the message "
     "names it): restore it from a backup or an export, or ask IT to; everything else keeps working",
     ("Open Projects", "projects", None)),
    (r"was removed on", "the project was removed; its records are kept as an export file", ("Open Projects",
                                                                                             "projects", None)),
    (r"ended from outside|exit -1\b|4294967295|was killed", "the process was ended from outside (stopped by the "
     "system or a person), so it finished nothing: run it again", ("Open Jobs", "jobs", None)),
    (r"interrupted by a cockpit restart", "the cockpit restarted while it ran, so it never finished: run it again",
     ("Open Jobs", "jobs", None)),
    (r"not granted|may not|only (?:an? )?\w+ (?:may|decides)|not one of your", "your persona may not do this here",
     ("Switch persona", "home", "persona")),
    (r"no model|api.?key|not set up|gnomon was not found|no usable answer", "no model answers for this step yet",
     ("Open Models setup", "models", "models_open")),
    (r"paused", "the project is paused", ("Resume the project", "overview", "resume")),
    (r"not open|already|is (?:merged|closed|decided|settled)", "someone, or a rule, settled it a moment ago",
     ("Open the Inbox", "inbox", None)),
    (r"say why|reason|is empty|needs the|is required|must be", "a field it needs is empty or not in the form it "
     "takes: the message names it", ("Back to the view", "", None)),
    (r"confidential|local only|hosted", "the project is confidential: only a model on this machine may read it",
     ("Open Models setup", "models", "models_private")),
    (r"folder|outside|not allowed", "the folder is outside what the cockpit may read", ("Open Settings", "settings",
                                                                                       None)),
    (r"failed to fetch|network|timed? ?out|did not answer|unreachable", "the cockpit did not answer: it may have "
     "stopped or be busy", ("Open Health", "health_all", None)),
    (r"no project|not found|no card|no question|404", "it no longer exists or was never made",
     ("Open Projects", "projects", None)),
    (r"internal error|500|bug|exception", "Rihmasto hit a bug; it was opened as an incident", ("Open Incidents",
                                                                                              "incidents_all",
                                                                                              "investigate_incident")),
]
# a failure asked about with no message: nothing says which action failed, so the answer says where they are kept
NO_MESSAGE = ("no failure message came with the question, so Rihmasto cannot tell which action failed: every failed "
              "action that reached the cockpit is kept in Incidents with its message", ("Open Incidents",
                                                                                         "incidents_all", None))
# how the answer reads: the question's premise holds ("because"), the view is not empty ("shows"), or no rule knows
BECAUSE, SHOWN, UNKNOWN = "because", "shows", "unknown"
Reason = tuple[str, Step, str]
# words a page puts around a value that are not its name: the value's own state, buttons, its measuring hint
_NOISE = re.compile(r"why\? ask rihma|pin to home|open the records|[-—]?\s*not measured\b", re.I)
_HINT = re.compile(r"to measure it:?\s*([^.;]+)", re.I)
HINTED = "nothing has measured it yet: to measure it, "


def _route(view: str, project: Any) -> str | None:
    from kernel.assistant_rules import ui_map

    found = next((v for v in ui_map()["views"] if v["id"] == view), None)
    if found is None:
        return None
    route = str(found["route"])
    if "{pid}" in route:
        return route.replace("{pid}", project.pid) if project is not None else "#/projects"
    return route


def _label(view: str) -> str:
    from kernel.assistant_rules import ui_map

    found = next((v for v in ui_map()["views"] if v["id"] == view), None)
    return str(found["label"]) if found else view.replace("_", " ")


def _fill(step: Step, project: Any, here: str) -> dict[str, Any]:
    label, view, control = step
    view = view or here
    return {"label": label, "view": view, "route": _route(view, project), "control": control}


def _by_field(field: str) -> tuple[str, Step] | None:
    said = field.lower()
    for words, why, step in FIELD_RULES:
        if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?:s|es)?(?![a-z])", said) for w in words):
            return why, step
    return None


def _by_view(view: str, f: Facts) -> tuple[str, Step] | None:
    rules = VIEW_RULES.get(view) or (VIEW_RULES.get(view.removesuffix("_all"), []) if f.get("project") else [])
    for when, why, step in rules:
        if when(f):
            return why, step
    return None


def _by_hint(basis: str, field: str) -> tuple[str, Step] | None:
    """A value's own "To measure it: ..." line: the answer follows it, never a rule that contradicts it."""
    m = _HINT.search(basis)
    if not m:
        return None
    hint = m.group(1).strip()
    step = (_by_field(hint) or _by_field(field) or ("", ("Back to the view", "", None)))[1]
    return f"{HINTED}{hint}", step


def _by_error(message: str) -> tuple[str, Step]:
    if not message.strip():
        return NO_MESSAGE
    for pattern, why, step in ERROR_RULES:
        if re.search(pattern, message, re.I):
            return why, step
    return ("it is not one Rihmasto knows by rule yet", ("Investigate with Rihma", "incidents_all",
                                                          "investigate_incident"))


def view_named(field: str) -> str | None:
    """The view a field's words name ("Track", "releases"), when Rihmasto has rules for it."""
    from kernel.assistant_rules import ui_map

    said = field.lower().strip(" :")
    found = next((v["id"] for v in ui_map()["views"] if said and said in (v["id"], v["label"].lower())), None)
    return found if found in VIEW_RULES else None


def _shows(view: str, f: Facts) -> str | None:
    shows = SHOWS.get(view) or SHOWS.get(view.removesuffix("_all"))
    return shows(f) if shows is not None and f.get("project") else None


MODEL_UNUSABLE = ("the model gave no usable answer (the panel or the step asked it and could not use what came back), "
                  "so nothing was measured: check Models setup, then run it again")


def _reason(view: str, field: str, kind: str, basis: str, f: Facts) -> Reason:
    if re.search(r"no usable answer", f"{field} {basis}", re.I):     # the model is the reason, never the stage
        return MODEL_UNUSABLE, ("Open Models setup", "models", "models_open"), BECAUSE
    if kind == "error":
        return (*_by_error(f"{basis} {field}"), BECAUSE)
    named = view_named(field)          # a field that names a view ("Track: not measured") is that view's
    target = named or view
    hit = _by_rules(target, field, kind, basis, f, named is not None)
    if hit is not None:
        return (*hit, BECAUSE)
    return _no_rule(target, basis, f)


def _by_rules(target: str, field: str, kind: str, basis: str, f: Facts, named: bool) -> tuple[str, Step] | None:
    """The value's own hint, then the field's rule, then the view's; for a value not measured, its basis's words."""
    measured = kind == "not_measured"
    hit = (_by_hint(basis, field) if measured else None) or (_by_field(field) if field and not named else None)
    hit = hit or _by_view(target, f)
    return hit or (_by_field(basis) if measured and not named else None)


def _no_rule(target: str, basis: str, f: Facts) -> Reason:
    """No rule holds: what the view shows when its records have data, else the project's stage, else no premise."""
    shows = _shows(target, f)
    if shows is not None:              # its records say it is not empty: say what it shows, never a made-up reason
        return shows, (f"Open {_label(target)}", target, None), SHOWN
    if f.get("project") and int(f.get("stage") or 1) < 3:
        return ("the project is still early: most views fill once its questions are answered and the plan approved",
                _RUN, BECAUSE)
    if basis:                          # the page itself said it is empty: that premise holds
        return "nothing is recorded for it here yet", ("Ask Rihma what to do next", "overview", "next_step"), BECAUSE
    return "", ("Ask Rihma what to do next", "overview", "next_step"), UNKNOWN


def tidy(field: str, basis: str) -> tuple[str, str]:
    """A value's name without the words around it (its state, its buttons, its hint), the rest kept as its basis."""
    field = " ".join(str(field or "").split())[:200]
    basis = " ".join(str(basis or "").split())[:400]
    if field.startswith(":"):          # "Not measured: no task finished yet" sent as a name: it is the basis
        basis, field = basis or field.strip(" :"), ""
    hint = _HINT.search(field)
    if hint:
        basis = basis or field[hint.start():]
        field = field[:hint.start()]
    state = re.search(r"not measured", field, re.I)     # "Checks failing · Not measured: no check enabled"
    if state and field[:state.start()].strip(" :·—-"):
        basis = basis or _NOISE.sub(" ", field[state.end():]).strip(" :·—-")
        field = field[:state.start()]
    field = _NOISE.sub(" ", field)
    return " ".join(field.split()).strip(" :·—-"), basis


def _said(subject: str, kind: str, reason: str, mode: str) -> str:
    head = f"{subject[0].upper()}{subject[1:]}"
    if mode == SHOWN:
        state = "is not empty here" if kind == "empty" else "is measured here"
        return (f"{head} {state}: it shows {reason}. If one part of it shows nothing, press Why? Ask Rihma beside "
                "that part: it sends what is on screen and the answer names the step that fills it.")
    if mode == UNKNOWN:
        return (f"{head}: Rihmasto has no record that says it should show something here yet. If a part of it shows "
                "nothing, press Why? Ask Rihma beside that part: it sends what is on screen and the answer names the "
                "step that fills it.")
    what = {"empty": "is empty", "not_measured": "is not measured", "error": "failed"}[kind]
    return f"{head} {what} because {reason}."


def _scoped_view(view: str, project: Any) -> str:
    """The view as the person sees it: outside a project, a project view's all-projects page (Automations, not
    Automations (project))."""
    from kernel.assistant_rules import ui_map

    if not view:
        return "overview" if project is not None else "home"
    ids = {v["id"] for v in ui_map()["views"]}
    return f"{view}_all" if project is None and f"{view}_all" in ids else view


def _module_off(factory: Any, project: Any, view: str) -> Reason | None:
    """A page whose module is turned off is empty for that reason, whatever its records say (FR-NVL3)."""
    from kernel import modules

    target = project if project is not None else factory
    try:
        off = not modules.shown(target, "pages" if project is None else "views", view)
    except (OSError, ValueError, KeyError):
        return None
    if not off:
        return None
    return (f"its module is turned off in Settings, Modules: turn it on there to use {_label(view)}",
            ("Open Settings, Modules", "settings", "modules"), BECAUSE)


def _home_facts(factory: Any) -> Facts:
    from pathlib import Path

    from kernel.job_registry import interrupted

    home = getattr(factory, "home", None)
    return {"interrupted": len(interrupted(Path(home))) if home is not None else 0}


def why(factory: Any, project: Any, *, view: str, field: str = "", kind: str = "empty", basis: str = "",
        subject: str | None = None) -> dict:
    """Why ``view`` (or one ``field`` of it) is empty, not measured or failing here, and the step that fills it.
    ``subject`` names what the person asked about when it is not "<field> on <view>" (a typed question)."""
    kind = kind if kind in KINDS else "empty"
    view = _scoped_view(re.sub(r"[^a-z0-9_]", "", str(view or "").lower())[:40], project)
    field, basis = tidy(field, basis)
    if re.fullmatch(r"[\d\s.,%€$-]*", field):       # a value ("0") is never the name of what is not measured
        field = ""
    off = _module_off(factory, project, view)
    reason, step, mode = off or _reason(view, field, kind, basis, facts(project) | _home_facts(factory))
    fill = _fill(step, project, view)
    if not subject:
        subject = (field if view_named(field) else f"{field} on {_label(view)}") if field else _label(view)
    said = _said(subject, kind, reason, mode)
    quoted = _HINT.sub("", basis).strip(" .") if reason.startswith(HINTED) else basis   # the hint is said once
    if re.search(r"[A-Za-z]{3}", quoted) and kind != "error":       # never a stray ")" quoted
        said += f' The record says: "{quoted}".'
    elif basis:
        said += f' The message was: "{basis}".'
    said += (f" The step that fills it: {fill['label']}." if mode == BECAUSE else f" Next: {fill['label']}.")
    return {"answer": said, "navigate": {"route": fill["route"], "control": fill["control"]} if fill["route"] else None,
            "fill": fill, "by": "why", "propose": [], "dropped": [], "sources": [],
            "why": {"view": view, "field": field, "kind": kind, "basis": basis, "premise": mode}}


field_rule, view_label = _by_field, _label     # for the typed questions' reader (kernel/neverlost_ask.py)


def asked(question: str) -> bool:
    from kernel.neverlost_ask import asked as _asked

    return _asked(question)


def chat_answer(factory: Any, project: Any, question: str, view: str | None = None) -> dict[str, Any] | None:
    """A typed "why is ... empty / not measured / failing?" answered by the same rules (kernel/neverlost_ask.py)."""
    from kernel.neverlost_ask import answer

    return answer(factory, project, question, view)

