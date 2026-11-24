"""Change what was set when a project was made (FR-CHG1): its title, its kind of work, its mode and maturity.

Nothing set at creation is final. A person with a reason changes any of them; the ledger records
``project_changed`` with what it was before and after, and the change says what it means for the work
already done (its impact): questions asked for another kind of work, a spec written for another maturity,
a plan compiled before. Nothing is deleted. Where the work no longer fits, the change offers to go back to
the right step (kernel/rewind.py), and with ``redo`` it goes:

- a new **kind** of work goes back to the questions (the panel asks what this kind needs);
- a new **maturity** goes back to the spec once one is written (its size and the plan's approval follow it);
- a new **mode** settles the open questions as the new mode would: under ``assume`` the factory assumes
  each one that has a proposed answer, under ``mixed`` the ones that do not block, in the name of the
  person who changed it.

A released project keeps its releases: its kind and maturity still change, and what it does changes
through the change loop. The posture (prototype, balanced, production, regulated) has its own change flow
(kernel/posture_change.py) and is not changed here, but a new maturity or mode is judged by its rules: the
impact says when the change also loosens or tightens what the project runs by, a maturity or mode the
posture does not take is refused, and loosening a posture needs a persona that may loosen one.
"""

from __future__ import annotations

from typing import Any

from kernel import rewind as kr
from kernel.canon import Canon, DecisionRefused
from kernel.intake import QUESTIONS_PER_PERSPECTIVE, render_brief
from kernel.profiles import DEFAULT_PROFILE, PROFILE_QUESTION, PROFILES, choose
from kernel.store import MATURITIES, MODES, Project

FIELDS = ("title", "kind", "mode", "maturity")
MAX_TITLE = 200


def current(project: Project) -> dict[str, Any]:
    """The settings as they stand, with the choices for each."""
    meta = project.meta
    return {"title": meta.get("title"), "kind": meta.get("profile") or DEFAULT_PROFILE, "mode": meta.get("mode"),
            "maturity": meta.get("maturity"), "kinds": list(PROFILES), "modes": list(MODES),
            "maturities": list(MATURITIES)}


def _label(kind: str) -> str:
    return str(PROFILES.get(kind, {}).get("label") or kind)


def wanted(project: Project, given: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """The fields a person changes, as {field: (before, after)}: only those that differ. A value no field
    takes is a ValueError that says which values it takes."""
    now = current(project)
    out: dict[str, tuple[Any, Any]] = {}
    for field in FIELDS:
        value = given.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        value = str(value).strip()
        allowed = {"kind": PROFILES, "mode": MODES, "maturity": MATURITIES}.get(field)
        if allowed is not None and value not in allowed:
            raise ValueError(f"{field} must be one of {', '.join(allowed)}, got {value!r}")
        if field == "title" and len(value) > MAX_TITLE:
            raise ValueError(f"a title is at most {MAX_TITLE} characters")
        if value != now[field]:
            out[field] = (now[field], value)
    return out


def _done(project: Project) -> dict[str, Any]:
    meta = project.meta
    canon = Canon(project)
    return {"intake": project.path("source.json").exists(), "spec": project.path("spec.json").exists(),
            "plan": project.path("contract.json").exists(), "built": bool(meta.get("built")),
            "released": kr.releases(project), "open": canon.questions("open"),
            "settled": len(canon.questions("answered")) + len(canon.questions("assumed"))}


def _row(what: str, says: str, step: str | None = None) -> dict[str, Any]:
    return {"what": what, "says": says, "rewind": step}


def _kind_impact(done: dict[str, Any], before: str, after: str) -> list[dict[str, Any]]:
    old, new = _label(before), _label(after)
    if not done["intake"]:
        return [_row("questions", f"Nothing was asked yet: the intake asks what “{new}” needs.")]
    rows = [_row("questions", f"The questions were asked for “{old}”: {len(done['open'])} open question(s) no longer "
                              f"fit and are withdrawn when the questions run again for “{new}”; {done['settled']} "
                              "settled answer(s) are kept.", "questions")]
    if done["spec"]:
        rows.append(_row("spec", f"The spec was written for “{old}”: it is kept as a superseded version and "
                                 "written again.", "questions"))
    if done["plan"]:
        rows.append(_row("plan", f"The plan was compiled for “{old}”: it is set aside and compiled again"
                                 + (", and what was built is built again from it." if done["built"] else "."),
                         "questions"))
    return rows


def _maturity_impact(done: dict[str, Any], before: str, after: str) -> list[dict[str, Any]]:
    from kernel.plan import NEEDS_APPROVAL
    from kernel.spec import MAX_REQUIREMENTS

    rows = []
    asks = QUESTIONS_PER_PERSPECTIVE
    if done["intake"]:
        rows.append(_row("questions", f"The questions were asked for {before} maturity ({asks[before]} per "
                                      f"perspective; {after} asks up to {asks[after]}). They stand; go back to the "
                                      f"questions to ask them again for {after}."))
    if done["spec"]:
        rows.append(_row("spec", f"The spec was written for {before} maturity (up to {MAX_REQUIREMENTS[before]} "
                                 f"requirements; {after} allows {MAX_REQUIREMENTS[after]}): write it again.", "spec"))
    if NEEDS_APPROVAL[before] != NEEDS_APPROVAL[after]:
        rows.append(_row("plan", f"At {after} maturity a person " + ("approves" if NEEDS_APPROVAL[after] else
                                 "no longer needs to approve") + " the plan before anything is built.",
                         "plan" if done["spec"] else None))
    return rows or [_row("questions", f"Nothing was asked yet: the intake asks at {after} maturity.")]


def _mode_impact(project: Project, done: dict[str, Any], after: str) -> list[dict[str, Any]]:
    settle = _to_assume(project, after)
    rows = []
    if settle:
        rows.append(_row("questions", f"{len(settle)} open question(s) wait on a person; under {after} the factory "
                                      "may assume them. Apply the change to the work to assume them now, in your "
                                      "name, with due dates."))
    elif done["open"]:
        rows.append(_row("questions", f"{len(done['open'])} open question(s) still wait on a person under {after}."))
    assumed = len(Canon(project).questions("assumed"))
    if after == "socratic" and assumed:
        rows.append(_row("questions", f"{assumed} question(s) were assumed by the factory: they stay as assumptions "
                                      "with due dates. Challenge one in Assumptions, or go back to the questions "
                                      "to put them all to people.", "questions"))
    return rows or [_row("questions", f"New questions are settled the {after} way.")]


def _to_assume(project: Project, mode: str) -> list[dict[str, Any]]:
    """The open questions the new mode lets the factory assume: each with a proposed answer, and under mixed
    only those that do not block."""
    if mode == "socratic":
        return []
    return [q for q in Canon(project).questions("open") if str((q.get("opinions") or {}).get(q["perspective"]) or "")
            .strip() and q["text"] != PROFILE_QUESTION and (mode == "assume" or not q["blocking"])]


def posture_effect(project: Project, changes: dict[str, tuple[Any, Any]]) -> dict[str, Any] | None:
    """What a new maturity or mode does to the project's posture, by kernel/posture_change.py's rules: what
    it loosens and what it tightens, what that does now and later, and ``refused`` when the posture does not
    take it. None for a project without a posture, or when neither the maturity nor the mode changes."""
    from kernel.posture import LOOSENERS, baseline, effects, record_of
    from kernel.posture_change import consequences, loosens

    rec = record_of(project)
    if rec is None or not {"maturity", "mode"} & set(changes):
        return None
    before = baseline(project)
    maturity, mode = (changes[f][1] if f in changes else before[f] for f in ("maturity", "mode"))
    label = f"the {before['label']} posture"
    try:
        after = effects(rec["name"], rec.get("weights"), maturity=maturity, mode=mode, screens=before.get("screens", True))
    except ValueError as exc:
        return {"label": label, "refused": f"The {before['label']} posture does not take this: {exc}. Change the "
                                          "posture first (Posture)", "loosens": [], "tightens": [], "lines": []}
    said = consequences(project, before, after)
    return {"label": label, "refused": None, "loosens": loosens(before, after), "tightens": _tightens(before, after),
            "lines": said["now"] + said["later"], "looseners": list(LOOSENERS)}


def _tightens(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """What the change makes stricter, in the words kernel/posture_change.py uses for loosening, turned
    around: a lower autonomy, a stricter mode, a higher maturity, or a check it adds."""
    import re

    from kernel.posture_change import _dropped_checks, _looser_rungs

    rungs = [re.sub(r"^(\w+) (\S+) to (\S+)$", r"\1 \3 to \2", x) for x in _looser_rungs(after, before)]
    checks = [re.sub(r"^evidence (\S+) to (\S+)$", r"evidence \2 to \1", x).replace(" no longer ", " ")
              .removeprefix("no ") for x in _dropped_checks(after, before)]
    return rungs + checks


def _keep_to_posture(project: Project, changes: dict[str, tuple[Any, Any]], persona: str) -> None:
    """A change the project's posture does not take is refused, and one that loosens it needs a persona
    that may loosen a posture (kernel/posture_change.py)."""
    effect = posture_effect(project, changes)
    if effect and effect["refused"]:
        raise ValueError(effect["refused"])
    if effect and effect["loosens"] and persona not in effect["looseners"]:
        raise DecisionRefused(f"the change loosens {effect['label']} ({'; '.join(effect['loosens'])}): a "
                              f"{', '.join(effect['looseners'][:-1])} or {effect['looseners'][-1]} may, not a {persona}")


def _posture_rows(effect: dict[str, Any] | None) -> list[dict[str, Any]]:
    if effect is None:
        return []
    if effect["refused"]:
        return [_row("posture", effect["refused"] + ".")]
    then = f" Then: {'; '.join(effect['lines'])}." if effect["lines"] else ""
    who = f" Only a {', '.join(effect['looseners'][:-1])} or {effect['looseners'][-1]} may make it." \
        if effect["loosens"] and effect["looseners"] else ""
    if effect["loosens"]:
        return [_row("posture", f"This also loosens {effect['label']}: {'; '.join(effect['loosens'])}.{who}{then}")]
    if effect["tightens"]:
        return [_row("posture", f"This also tightens {effect['label']}: {'; '.join(effect['tightens'])}.{then}")]
    return []


def impact(project: Project, changes: dict[str, tuple[Any, Any]]) -> list[dict[str, Any]]:
    """What a change means for the work already done: a row per thing it touches, with the step to go
    back to where the work no longer fits (or None)."""
    done = _done(project)
    rows: list[dict[str, Any]] = []
    if "title" in changes:
        rows.append(_row("title", "The brief and every heading use the new title; the ledger keeps the old one."))
    if "kind" in changes:
        rows += _kind_impact(done, *changes["kind"])
    if "maturity" in changes:
        rows += _maturity_impact(done, *changes["maturity"])
    if "mode" in changes:
        rows += _mode_impact(project, done, changes["mode"][1])
    rows += _posture_rows(posture_effect(project, changes))
    if done["released"] and ({"kind", "maturity"} & set(changes)):
        rows.append(_row("release", f"Release {done['released'][-1]} is out: it keeps what it was. Change what it "
                                    "does through the change loop (Changes)."))
        for row in rows:
            row["rewind"] = None
    return rows


def suggested(project: Project, rows: list[dict[str, Any]]) -> str | None:
    """The earliest step the impact goes back to, when the project can go back to it."""
    steps = [r["rewind"] for r in rows if r.get("rewind")]
    step = min(steps, key=kr.STEPS.index) if steps else None
    return step if step and kr.refusal(project, step) is None else None


def preview(project: Project, **given: Any) -> dict[str, Any]:
    """What a change would do, writing nothing: the fields that change, the impact, the step it goes back to."""
    changes = wanted(project, given)
    rows = impact(project, changes) if changes else []
    step = suggested(project, rows)
    return {"current": current(project), "changes": {f: {"from": a, "to": b} for f, (a, b) in changes.items()},
            "impact": rows, "rewind": step, "undoes": kr.UNDOES.get(step or "", ""),
            "posture": posture_effect(project, changes),
            "assumes": [q["id"] for q in _to_assume(project, changes["mode"][1])] if "mode" in changes else []}


def change(project: Project, *, person: str, persona: str, reason: str, redo: bool = False,
           **given: Any) -> dict[str, Any]:
    """Change the project's settings, signed, with a reason; with ``redo`` also carry the change into the
    work (go back to the step the impact names, or settle open questions the new mode's way)."""
    kr.check_signer(project, person, persona, reason)
    changes = wanted(project, given)
    if not changes:
        raise ValueError("nothing to change: every value given is the one the project has")
    _keep_to_posture(project, changes, persona)
    rows = impact(project, changes)
    step = suggested(project, rows)
    _apply(project, changes, person, persona, reason.strip())
    project.log("project_changed", {"person": person, "persona": persona, "reason": reason.strip(),
                                    "before": {f: a for f, (a, _) in changes.items()},
                                    "after": {f: b for f, (_, b) in changes.items()},
                                    "impact": [r["says"] for r in rows], "redo": redo, "offers": step})
    out: dict[str, Any] = {"changed": {f: {"from": a, "to": b} for f, (a, b) in changes.items()}, "impact": rows,
                           "offers": step, "rewound": None, "assumed": []}
    if redo and "mode" in changes:
        out["assumed"] = _settle_by_mode(project, changes["mode"][1], person, persona)
    if redo and step:
        out["rewound"] = kr.rewind(project, to=step, person=person, persona=persona,
                                   reason=f"the project's settings changed: {reason.strip()}")
    elif project.path("source.json").exists():
        render_brief(project)          # its first line says the maturity and the mode
    return out


def _apply(project: Project, changes: dict[str, tuple[Any, Any]], person: str, persona: str, reason: str) -> None:
    """Write the new values: the kind through the profile's own choice (it records profile_chosen), and an
    open question about the kind of work is withdrawn, since a person has now said which it is."""
    plain = {f: b for f, (_, b) in changes.items() if f in ("title", "mode", "maturity")}
    if plain:
        project.update_meta(**plain)
    if "kind" in changes:
        choose(project, changes["kind"][1], basis={"by": person, "persona": persona, "reason": reason,
                                                   "changed_from": changes["kind"][0]})
        asked = [q["id"] for q in Canon(project).questions("open") if q["text"] == PROFILE_QUESTION]
        if asked:
            kr.withdraw_questions(project, asked, f"{person} chose the kind of work: {_label(changes['kind'][1])}")


def _settle_by_mode(project: Project, mode: str, person: str, persona: str) -> list[str]:
    """Assume the open questions the new mode lets the factory assume, chosen by the person who changed it."""
    canon = Canon(project)
    done = []
    for q in _to_assume(project, mode):
        proposed = str(q["opinions"][q["perspective"]]).strip()
        done.append(canon.assume(q["id"], proposed, chosen_by=person, persona=persona)["id"])
    if done:
        render_brief(project)
    return done
