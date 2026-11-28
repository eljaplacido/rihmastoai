"""Set up this project (FR-SET1): a checklist of everything Rihmasto offers that applies to one project.

The owner (2026-11-24): "For all projects I want to see them populated with the entire features of Rihmasto, and
make sure that when you know how it happens I can also do it on a UIX level or by agent request on chat."

``checklist`` lists, for one project, each feature with its state:

- **set_up**: in use here (and what shows it);
- **offered**: it applies and is not in use yet, with **one click** that does it (``do``, signed) or opens the
  place where a person chooses (a dialog that needs their judgement, such as the posture);
- **not_applicable**: and why (no repository of its own to align, a part this build does not have yet...).

The items: checks and Health; watching and automations (the suggestions of kernel/automation_suggest.py);
alignment with its own specs and tests; Insights and Review; AI tools, the IDE hand-off and the agent channel;
the posture; the outputs; and destinations, agent observability and Gnomon audits when this build has them.

The checklist is on the project's overview (offered right after a project is fed in, until everything that
applies is set up), at ``rihmasto setup <pid> [--do ITEM]``, and in Ask Rihma ("set up this project"), whose
proposals the person confirms. Reading it writes nothing; ``do`` writes only through each feature's own path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel import automation_suggest as suggest
from kernel.alignment_suggest import plural
from kernel.store import Factory, Project

STATES = ("set_up", "offered", "not_applicable")
Item = dict[str, Any]
# Parts other streams add: the first module of each tuple this build has turns its item on.
OPTIONAL = {"destinations": ("kernel.destinations", "kernel.destination"),
            "agent_observability": ("kernel.agentobs", "kernel.agent_observability", "kernel.agent_observe"),
            "gnomon_audits": ("kernel.gnomon_evals", "kernel.gnomon_posture", "kernel.gnomon_audit")}
OPTIONAL_VIEW = {"destinations": "destinations", "agent_observability": "agent_sessions",
                 "gnomon_audits": "gnomon_posture"}


def _item(iid: str, label: str, state: str, why: str, action: dict[str, Any] | None = None) -> Item:
    return {"id": iid, "label": label, "state": state, "why": why, "action": action}


def _do(label: str) -> dict[str, Any]:
    """A one-click action carried out by ``do`` (the cockpit: POST /api/projects/<pid>/setup/<item>)."""
    return {"kind": "do", "label": label}


def _open(label: str, view: str | None, control: str | None, page: str | None = None) -> dict[str, Any]:
    """Open the place where a person chooses (a view of the project, or a page), with the control lit."""
    return {"kind": "open", "label": label, "view": view, "page": page, "control": control}


def _recommended_check(f: dict[str, Any]) -> str:
    return "tests" if f["tests"] else "secrets"


def _checks(project: Project, f: dict[str, Any]) -> Item:
    on = f["checks"]
    if on:
        return _item("checks", "Checks and Health", "set_up", f"{len(on)} check(s) enabled: {', '.join(on[:4])}",
                     _open("Open its checks", "checks", "health_run"))
    if not (f["repository"] or f["built"] or f["releases"]):
        return _item("checks", "Checks and Health", "not_applicable",
                     "checks read a repository or a built release, and it has neither yet")
    key = _recommended_check(f)
    return _item("checks", "Checks and Health", "offered",
                 f"no check runs on it yet: the {key} check, daily, is a good first one",
                 _do(f"Enable the {key} check"))


def _automations(factory: Factory, project: Project) -> Item:
    s = suggest.scan(factory, project.pid)
    done = [x for x in s["suggestions"] if x["state"] == "set_up"]
    offered = [x for x in s["suggestions"] if x["state"] == "offered"]
    if offered:
        first = offered[0]
        return _item("automations", "Watching and automations", "offered",
                     f"{plural(len(offered), 'automation')} suggested from its shape; first: {first['label']} "
                     f"({first['reason']})", _do(f"Set up: {first['label']}") | {"suggestion": first["id"]})
    if done:
        return _item("automations", "Watching and automations", "set_up",
                     f"{plural(len(done), 'suggested automation')} set up", _open("Open its automations", "automations",
                                                                         "automations_new"))
    return _item("automations", "Watching and automations", "set_up" if s["suggestions"] else "not_applicable",
                 "every suggestion was dismissed" if s["suggestions"] else "nothing in its shape asks for one yet",
                 _open("Open its automations", "automations", "automations_new"))


def _alignment(project: Project, kinds: set[str]) -> Item:
    from kernel.alignment_records import applies

    if not applies(project):
        return _item("alignment", "Alignment with its own specs and tests", "not_applicable",
                     "it has no repository of its own: its spec and tests are the ones Rihmasto keeps")
    if "alignment_scanned" in kinds:
        return _item("alignment", "Alignment with its own specs and tests", "set_up",
                     "its repository was read; what drifts shows on Alignment", _open("Open Alignment", "align",
                                                                                     "align_decide"))
    return _item("alignment", "Alignment with its own specs and tests", "offered",
                 "its repository has specs and tests of its own that Rihmasto has not read yet",
                 _do("Read the repository for alignment"))


def _insights(project: Project) -> Item:
    from kernel.modules import shown

    on = shown(project, "views", "insights") and shown(project, "views", "review")
    return _item("insights_review", "Insights and Review", "set_up" if on else "offered",
                 "its activity is counted in Insights and shown in Review since you last looked" if on
                 else "a module that shows them is off for this project",
                 _open("Open Review", "review", "review_mark") if on else _open("Open Modules", None, "modules",
                                                                                 "settings"))


def _agents(project: Project, f: dict[str, Any], kinds: set[str]) -> Item:
    if not (f["repository"] or f["built"]):
        return _item("ai_tools", "AI tools, IDE hand-off and the agent channel", "not_applicable",
                     "there is no code to work on from an IDE yet: it opens once the first build is in")
    used = kinds & {"workspace_opened", "workspace_launched", "agent_handoff", "channel_posted"}
    if used:
        return _item("ai_tools", "AI tools, IDE hand-off and the agent channel", "set_up",
                     "agents work on it: " + ", ".join(sorted(used)), _open("Open the agent channel", "agents",
                                                                            "channel_post"))
    return _item("ai_tools", "AI tools, IDE hand-off and the agent channel", "offered",
                 "work on it from your IDE or hand a task to a coding agent; their questions come back here",
                 _open("Work on it from your IDE", "overview", "ide_setup"))


def _posture(project: Project) -> Item:
    chosen = project.meta.get("posture")
    if chosen:
        return _item("posture", "Posture", "set_up", f"{chosen.get('name') or 'chosen'}: it sets how strict the "
                     "gates and the evidence are", _open("Change the posture", "overview", "posture"))
    return _item("posture", "Posture", "offered", "no posture chosen: prototype, balanced, production or regulated "
                 "sets how strict its gates and evidence are", _open("Choose a posture", "overview", "posture"))


def _outputs(project: Project) -> Item:
    from kernel.outputs import chosen

    picked = chosen(project)
    if picked:
        return _item("outputs", "Outputs", "set_up", "chosen: " + ", ".join(picked[:5]),
                     _open("Open its outputs", "outputs", "build_outputs"))
    return _item("outputs", "Outputs", "offered", "choose what each audience receives (a report, a deck, the docs)",
                 _open("Choose the outputs", "outputs", "choose_outputs"))


def _optional(iid: str, label: str) -> Item:
    from kernel.copilot_catalog import has

    found = next((m for m in OPTIONAL[iid] if has(m)), None)
    if found is None:
        return _item(iid, label, "not_applicable", "this build does not have it yet")
    return _item(iid, label, "offered", f"this build has it ({found}): open the project to set it up",
                 _open(f"Open {label}", OPTIONAL_VIEW.get(iid, "overview"), None))


def checklist(factory: Factory, pid: str) -> dict[str, Any]:
    """The project's checklist: every feature that applies, its state and its one-click action. Writes nothing."""
    project = factory.project(pid)
    if project.pid.startswith("_"):
        raise ValueError("Rihma's own proposals have no set-up of their own")
    f = suggest.facts(project)
    kinds = suggest._kinds(project)
    items = [_checks(project, f), _automations(factory, project), _alignment(project, kinds), _insights(project),
             _agents(project, f, kinds), _posture(project), _outputs(project),
             _optional("destinations", "Destinations"), _optional("agent_observability", "Agent observability"),
             _optional("gnomon_audits", "Gnomon audits")]
    counts = {s: sum(1 for i in items if i["state"] == s) for s in STATES}
    return {"project": project.pid, "title": f["title"], "items": items, "counts": counts,
            "done": counts["offered"] == 0, "line": _line(counts)}


def _line(counts: dict[str, int]) -> str:
    if not counts["offered"]:
        return f"Everything that applies is set up ({counts['set_up']})."
    return f"{counts['set_up']} set up, {counts['offered']} offered, {counts['not_applicable']} not applicable."


# -- one click -------------------------------------------------------------------------------------------------

def _enable_check(factory: Factory, project: Project, person: str, persona: str,
                  _suggestion: str | None = None) -> dict[str, Any]:
    from kernel.checks import store as cstore

    key = _recommended_check(suggest.facts(project))
    return {"enabled": cstore.enable(project, key, person=person, persona=persona, every="1d")}


def _accept_named(factory: Factory, project: Project, person: str, persona: str,
                  suggestion: str | None = None) -> dict[str, Any]:
    """Set up the suggestion the button named (its ``suggestion`` id), and only while it is still offered: the
    suggestions change as the project does, so the first one offered now may not be the one the person saw."""
    offered = [s for s in suggest.scan(factory, project.pid)["suggestions"] if s["state"] == "offered"]
    if not offered:
        raise ValueError("no automation is suggested for it now")
    chosen = offered[0] if suggestion is None else next((s for s in offered if s["id"] == suggestion), None)
    if chosen is None:
        raise ValueError(f"the suggestion {suggestion!r} is no longer offered for it: nothing was set up; the "
                         f"checklist now offers {offered[0]['label']}")
    return suggest.accept(factory, project.pid, chosen["id"], person=person, persona=persona)


def _align(factory: Factory, project: Project, person: str, persona: str,
           _suggestion: str | None = None) -> dict[str, Any]:
    from kernel import alignment_records as ar

    view = ar.scan(project, person=person, persona=persona)
    return {"scanned": True, "items": len(view.get("items") or [])}


DOERS: dict[str, Callable[[Factory, Project, str, str, str | None], dict[str, Any]]] = {
    "checks": _enable_check, "automations": _accept_named, "alignment": _align}


def do(factory: Factory, pid: str, item: str, *, person: str, persona: str,
       suggestion: str | None = None) -> dict[str, Any]:
    """Carry out an item's one click, signed, through the feature's own path; refused unless it is offered. For
    the automations, ``suggestion`` names the suggestion the click set up (the item's action carries it)."""
    from kernel.canon import DecisionRefused
    from kernel.people import is_person

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a set-up step is signed by a named person")
    found = next((i for i in checklist(factory, pid)["items"] if i["id"] == item), None)
    if found is None:
        raise KeyError(f"no set-up item {item!r}")
    if found["state"] != "offered":
        raise ValueError(f"{found['label']} is {found['state'].replace('_', ' ')} here: {found['why']}")
    if item not in DOERS:
        raise ValueError(f"{found['label']} is chosen in its own place: {found['action']['label']}")
    done = DOERS[item](factory, factory.project(pid), person, persona, suggestion)
    return {"item": item, "done": done, "checklist": checklist(factory, pid)}
