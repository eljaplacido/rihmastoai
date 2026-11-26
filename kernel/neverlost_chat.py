"""Ask Rihma, by rule, for FR-NVL1 (kernel/assistant.py ``ask`` calls ``answer`` before any model):

- "why is Insights empty?", "why is cost not measured?", "why did it fail?" -> kernel/neverlost.py;
- "I have 50 decisions: what blocks work? assume the rest" -> the triage, with its proposal to confirm, for the
  persona asking (only what it may decide); outside a project, every project's at once (kernel/triage_all.py);
- "which assumptions grew in importance?" -> the assumption weights and their triggers;
- "who acted?", "which model answered?", "local or hosted?" -> who acted on the project's runs;
- "if I change harness, does Gnomon still enforce?" -> what changing harness does to enforcement.

Each answer says where it came from (by rule, no model asked) and takes the person to the view that does the same by
hand (Take me there): the Decide what matters view, Who acted, Settings.
"""

from __future__ import annotations

import re
from typing import Any

_TRIAGE = re.compile(r"\btriage\b|\bassume the rest\b|\bprioriti[sz]\w*\b.*\bdecisions?\b|\bdecisions?\b.*"
                     r"\b(?:prioriti[sz]\w*|assume)\b|\bwhat blocks (?:my )?work\b", re.I)
# Only an assumption's weight as work touches it, never what an assumption is or why assumptions matter in general.
_GREW = re.compile(r"\bassumptions?\b.*\b(?:grew|grown|growing|gained|reconsider\w*|weight\w*)\b|"
                   r"\b(?:reconsider|weigh)\w*\b.*\bassumptions?\b|"
                   r"\b(?:which|what) assumptions\b.*\b(?:matter|important|importance)\b.*\b(?:now|most|more)\b", re.I)
_WHO = re.compile(r"\bwho acted\b|\bwho (?:answered|ran|built) (?:this|that|it|here|T-\d+)\b|\blocal or hosted\b|"
                  r"\bwhich (?:agent|harness|model) (?:acted|ran|built|answered) (?:this|that|it|here|on)\b", re.I)
# Gnomon's own enforcement and what a harness change does to it, never any rule enforced ("enforce a review").
_ENFORCE = re.compile(r"\bgnomon\b.*\benforc\w*|\benforc\w*\b.*\bgnomon\b|\bharness\b.*\benforc\w*|"
                      r"\benforc\w*\b.*\bharness\b|\b(?:change|switch) (?:the |my |a )?harness\b|"
                      r"\bgnomon'?s? structure\b|\bopt(?:ed)? out of (?:the )?enforcement\b", re.I)
_TASK = re.compile(r"\bT-\d{1,4}\b", re.I)


def _shape(answer: str, by: str, route: str | None, control: str | None = None, **extra: Any) -> dict[str, Any]:
    nav = {"route": route, "control": control} if route else None
    return {"answer": answer, "navigate": nav, "by": by, "propose": [], "dropped": [], "sources": [], **extra}


def _project_route(project: Any, view: str) -> str:
    return f"#/p/{project.pid}/{view}"


def triage_answer(factory: Any, project: Any, persona: str | None = None) -> dict[str, Any]:
    """A project's triage, or outside a project every project's at once (kernel/triage_all.py), for the persona."""
    from kernel import triage, triage_all

    if project is None:
        t = triage_all.across(factory, persona)
        return _shape(t["said"], "triage", "#/triage", "triage_assume", triage_all=t)
    t = triage.triage(project, persona)
    return _shape(t["said"], "triage", _project_route(project, "triage"), "triage_assume", triage=t)


def grew_answer(project: Any) -> dict[str, Any]:
    from kernel.assumption_weight import weights

    if project is None:
        return _shape("Open a project and ask again: an assumption's weight is counted from that project's work.",
                      "triage", "#/projects")
    rows = weights(project)
    grew = [w for w in rows if w["grew"]]
    if not rows:
        return _shape("No open assumption here: nothing was assumed, or every assumption is settled.", "triage",
                      _project_route(project, "assumptions"))
    if not grew:
        return _shape(f"{len(rows)} open assumption{'s' if len(rows) != 1 else ''}, none grown in importance yet: no "
                      "work touches them enough to reconsider.", "triage", _project_route(project, "assumptions"))
    lines = " ".join(f"{w['said']}{'; it blocks the next step: ' + w['blocks'] if w['blocking'] else ''}."
                     for w in grew[:5])
    return _shape(f"{len(grew)} grew in importance. {lines} Confirm or correct each in Assumptions.", "triage",
                  _project_route(project, "triage"), "assumption_grew", triage={"grew": grew, "blocking": [],
                                                                                 "rest": [], "proposal": None})


def _run_said(r: dict[str, Any]) -> str:
    return (f"{r['what']} by {r['agent']} ({r['role']}) through {r['harness']}, model {r['model']}, {r['where']}; "
            f"{r['gnomon']}.")


def who_answer(factory: Any, project: Any, question: str = "") -> dict[str, Any]:
    """Who acted on the project's runs: the latest, or every run on the task the question names ("on T-002")."""
    from kernel import who_acted

    if project is None:
        return _shape("Open a project and ask again: each run there says which agent, harness and model acted, and "
                      "whether Gnomon's structure applied. Ask Rihma's own answers say it under each answer.", "rule",
                      "#/projects")
    rows = who_acted.runs(factory, project)
    route = _project_route(project, "who")
    task = _TASK.search(question or "")
    if task:
        tid = task.group(0).upper()
        mine = [r for r in rows if r["id"].startswith(tid + "/") or r.get("task") == tid]
        if not mine:
            return _shape(f"No run is recorded on {tid} yet: it has not been built or answered on here.", "rule",
                          route, "who_acted")
        return _shape(f"{len(mine)} run{'s' if len(mine) != 1 else ''} on {tid}. "
                      + " ".join(_run_said(r) for r in mine[-3:]), "rule", route, "who_acted")
    if not rows:
        return _shape("No run is recorded on this project yet: nothing has been built or answered by a model here.",
                      "rule", route, "who_acted")
    return _shape(f"{len(rows)} run{'s' if len(rows) != 1 else ''} recorded. The latest: {_run_said(rows[-1])}", "rule",
                  route, "who_acted")


def enforcement_answer(factory: Any, project: Any) -> dict[str, Any]:
    from kernel import harness_enforcement as enforcement

    eff = enforcement.effects(factory, project)
    b = eff["roles"][0]
    other = next((o for o in b["others"] if o["harness"] != "gnomon"), b["others"][0] if b["others"] else None)
    said = (f"Gnomon's enforcement is {eff['state']['said']}. The builder is {b['label']} now: {b['enforced']}. "
            + (f"If you change it to {other['label']}: {other['then']}. " if other else "")
            + eff["summary"])
    route = _project_route(project, "who") if project is not None else "#/settings"
    return _shape(said, "rule", route, "harness_effects")


def answer(factory: Any, project: Any, question: str, view: str | None = None,
           persona: str | None = None) -> dict[str, Any] | None:
    """The FR-NVL1 answer the question asks for, or None."""
    from kernel import neverlost

    if neverlost.asked(question):
        return neverlost.chat_answer(factory, project, question, view)
    if _GREW.search(question):
        return grew_answer(project)
    if _TRIAGE.search(question):
        return triage_answer(factory, project, persona)
    if _WHO.search(question):
        return who_answer(factory, project, question)
    if _ENFORCE.search(question):
        return enforcement_answer(factory, project)
    return None
