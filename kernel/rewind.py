"""Go back a step (FR-CHG1): a project runs one of its steps again, and nothing it had is deleted.

The owner's words: "I don't want to see stupid mistakes like me choosing a template for the project or me
generating a spec, then I'm getting stuck somewhere because Rihmasto assumed the project template wrong. I
want all that to be able to change."

The steps, earliest first, and what going back to each sets aside:

- ``material``: the request itself. The material, the panel's readings and every open question are set
  aside with the spec and the plan; the project waits for material again (kernel/project_material.py).
- ``questions``: the panel's questions. Open questions are withdrawn (their cards decided as withdrawn,
  with the reason); answers people gave are kept; the intake runs again over the same material at the next
  Advance, and asks only what is not settled.
- ``spec``: the spec is kept as a superseded version and written again from the brief.
- ``plan``: the contract is kept as a superseded version and compiled again from the spec; where a person
  approves the plan, they approve it again.

Whatever is set aside moves under ``superseded/<n>-<step>/`` in the project folder, listed in
``superseded/index.json``; the ledger records ``rewound`` with the person, the persona and the reason. A
project with a release is never rewound: a released project changes through the change loop.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from kernel.canon import Canon, DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import Project, updating_json

STEPS = ("material", "questions", "spec", "plan")
UNDOES = {
    "material": "the request itself: the material, the panel's readings, every open question, the spec and the "
                "plan are set aside; add the material again and the intake runs from it",
    "questions": "the panel's questions: open ones are withdrawn and the intake runs again over the same "
                 "material, asking only what is not settled; answers people gave are kept; the spec and the plan "
                 "are set aside",
    "spec": "the spec: it is kept as a superseded version and written again from the brief at the next Advance; "
            "the plan is set aside with it",
    "plan": "the plan: the contract is kept as a superseded version and compiled again from the spec, and a "
            "person approves it again where the plan needs approval",
}
# The stage a project is at once it went back to each step (kernel/store.py STAGES).
STAGE_AFTER = {"material": 1, "questions": 1, "spec": 2, "plan": 4}
# What each step's work left in the project folder: set aside (moved, never deleted) when it runs again.
FILES = {"material": ("source.json", "inputs.json", "readings.json", "material.json"), "questions": (),
         "spec": ("spec.json", "spec.md"), "plan": ("contract.json", "checkplan.json", "tasks.json", "repo.git")}
# Who changes what was set for a project, or sends it back a step.
CHANGERS = ("business_owner", "product_owner", "developer")
NOT_REWOUND = ("adopted", "attached")    # projects with no intake of their own (kernel/adopt.py, kernel/attach.py)


class RewindRefused(ValueError):
    """A step the project cannot go back to: past a release, before its first run, or not a step."""


def check_signer(project: Project, person: str, persona: str, reason: str, *, who: tuple[str, ...] = CHANGERS) -> None:
    """The signer of a change to what was set: a named person, a persona that may, granted on the project
    (kernel.access.require, with access enforced), and a reason."""
    from kernel.access import require

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a change is signed by a named person")
    if persona not in PERSONAS or persona not in who:
        raise DecisionRefused(f"a {persona} may not change this (may: {', '.join(who)})")
    if not str(reason or "").strip():
        raise ValueError("give a reason: it is recorded with your name")
    require(project, person, persona)


def releases(project: Project) -> list[int]:
    """The numbers of the project's releases, as kernel/deliver.py keeps them."""
    folder = project.path("releases")
    return sorted(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit()) if folder.exists() else []


def reached(project: Project) -> list[str]:
    """The steps a project has done, so may go back to: the material once it has a request, the questions
    once the intake ran, the spec and the plan once a spec is written."""
    done = []
    if project.path("source.json").exists() or project.path("material.json").exists():
        done += ["material", "questions"]
    if project.path("spec.json").exists():
        done += ["spec", "plan"]
    return done


def refusal(project: Project, to: str) -> str | None:
    """Why the project cannot go back to ``to``, or None when it can."""
    if to not in STEPS:
        return f"go back to one of {', '.join(STEPS)}, not {to!r}"
    meta = project.meta
    if meta.get("source_kind") in NOT_REWOUND:
        return (f"{project.pid} was {meta['source_kind']}, with no intake of its own: change it through the "
                "change loop")
    out = releases(project)
    if out:
        return (f"release {out[-1]} of {project.pid} is out: a released project changes through the change loop "
                f"(the Changes view, or `rihmasto change {project.pid} \"...\"`), never by going back a step")
    if to not in reached(project):
        return f"{project.pid} has not reached the {to} step yet: there is nothing to go back to"
    return None


def _from(to: str) -> tuple[str, ...]:
    """The steps going back to ``to`` runs again: it and every later one."""
    return STEPS[STEPS.index(to):]


def open_questions(project: Project) -> list[dict[str, Any]]:
    return Canon(project).questions("open")


def _plan_cards(canon: Canon) -> list[dict[str, Any]]:
    """The open cards of the plan and the build: an approval of the plan, an escalation of a task."""
    return [c for c in canon.cards(state="open") if (c["kind"] == "approval" and (c.get("refs") or {}).get("scope")
                                                     == "plan") or c["kind"] == "escalation"]


def preview(project: Project, to: str) -> dict[str, Any]:
    """What going back to ``to`` would do, writing nothing: what it sets aside, withdraws and keeps."""
    why = refusal(project, to)
    steps = _from(to) if to in STEPS else ()
    files = [n for s in steps for n in FILES[s] if project.path(n).exists()]
    canon = Canon(project)
    qs = [q["id"] for q in open_questions(project)] if to in ("material", "questions") else []
    cards = [c["id"] for c in _plan_cards(canon)] if steps else []
    kept = len(canon.questions("answered")) + len(canon.questions("assumed"))
    return {"to": to, "refused": why, "undoes": UNDOES.get(to, ""), "sets_aside": files, "withdraws": qs + cards,
            "keeps": f"{kept} settled question(s) and every decision on record are kept",
            "steps": [{"id": s, "undoes": UNDOES[s], "possible": refusal(project, s) is None} for s in STEPS]}


def withdraw_questions(project: Project, qids: list[str], why: str) -> list[str]:
    """Withdraw open questions that no longer apply: each question's status becomes withdrawn with the reason,
    and its card is closed as withdrawn. Nothing is deleted. Returns the ids withdrawn."""
    canon = Canon(project)
    stamp = project.factory.clock.stamp()
    done = []
    with updating_json(canon.dir / "questions.json", [], lock=canon.lock) as qs:
        for q in qs:
            if q["id"] in qids and q["status"] == "open":
                q["status"], q["withdrawn"] = "withdrawn", {"why": why, "at": stamp}
                done.append(q)
    for q in done:
        if q.get("card") and canon.get_card(q["card"])["state"] == "open":
            canon.close(q["card"], why)
        project.log("question_withdrawn", {"id": q["id"], "card": q.get("card"), "why": why})
    return [q["id"] for q in done]


def _set_aside(project: Project, to: str, folder: Path) -> list[str]:
    """Move the files of ``to`` and the later steps into ``folder``; returns their names."""
    moved = []
    for name in (n for s in _from(to) for n in FILES[s]):
        src = project.path(name)
        if src.exists():
            folder.mkdir(parents=True, exist_ok=True)
            os.replace(src, folder / name)
            moved.append(name)
    return moved


def _retire(project: Project, folder: Path, n: int) -> list[str]:
    """A contract set aside takes its holdouts out of the runs (kept in the custody, never shown)."""
    from kernel.compile import retire_holdouts
    from kernel.store import read_json

    plan = read_json(folder / "checkplan.json", {}) or {}
    held = [r["criterion"] for r in plan.get("checks", []) if r.get("custody") == "holdout"]
    return retire_holdouts(project, held, because=f"rewind-{n:03d}") if held else []


def _next_number(project: Project) -> int:
    folder = project.path("superseded")
    taken = [int(p.name.split("-")[0]) for p in folder.iterdir() if p.name.split("-")[0].isdigit()] \
        if folder.exists() else []
    return max(taken, default=0) + 1


def _meta_after(project: Project, to: str) -> dict[str, Any]:
    """What project.json says once the project went back to ``to``: the stage, and the next tick runs it."""
    meta = project.meta
    changes: dict[str, Any] = {"stage": STAGE_AFTER[to], "built": False, "contract_revision": None,
                               "plan_approved": None, "halted": False, "redo_intake": to == "questions"}
    if to in ("material", "questions"):     # the intake reads every material again, or none is left to read
        changes["reintake_pending"] = []
    if project.path("spec.json").exists():
        changes["spec_version"] = int(meta.get("spec_version", 1)) + 1    # a new plan is approved again
    return changes


def rewind(project: Project, *, to: str, person: str, persona: str, reason: str) -> dict[str, Any]:
    """Send the project back to step ``to`` so it runs again (see the module's docstring)."""
    check_signer(project, person, persona, reason)
    why = refusal(project, to)
    if why:
        raise RewindRefused(why)
    reason = reason.strip()
    said = f"went back to the {to} step: {reason} ({person})"
    n = _next_number(project)
    folder = project.path("superseded", f"{n:03d}-{to}")
    withdrawn = withdraw_questions(project, [q["id"] for q in open_questions(project)], said) \
        if to in ("material", "questions") else []
    canon = Canon(project)
    for c in _plan_cards(canon):
        canon.close(c["id"], said)
        withdrawn.append(c["id"])
    meta_changes = _meta_after(project, to)
    moved = _set_aside(project, to, folder)
    retired = _retire(project, folder, n) if "checkplan.json" in moved else []
    project.update_meta(**meta_changes)
    entry = {"n": n, "to": to, "folder": folder.relative_to(project.dir).as_posix(), "files": moved,
             "withdrawn": withdrawn, "by": person, "persona": persona, "reason": reason,
             "at": project.factory.clock.stamp()}
    with updating_json(project.path("superseded", "index.json"), []) as index:
        index.append(entry)
    project.log("rewound", {"to": to, "person": person, "persona": persona, "reason": reason, "superseded": moved,
                            "folder": entry["folder"], "withdrawn": withdrawn, "holdouts_retired": retired})
    _rebrief(project)
    return {**entry, "holdouts_retired": retired, "stage": meta_changes["stage"],
            "then": "the next Advance runs the intake again" if to == "questions" else
            "add the material again" if to == "material" else f"the next Advance runs the {to} step again"}


def _rebrief(project: Project) -> None:
    """The brief says what stands now: withdrawn questions leave its open list."""
    from kernel.intake import render_brief

    render_brief(project)


def rerun_intake(project: Project, *, model: Any) -> dict[str, Any]:
    """The intake again over the material the project keeps (after going back to the questions): the panel
    asks only what is not settled, and the brief and its questions are new; called by the pipeline."""
    from kernel.intake import intake

    source = project.read("source.json") or {}
    out: dict[str, Any] = intake(project, str(source.get("text") or ""), model=model, literal=True,
                                 requested_by=source.get("requested_by"), kind=source.get("kind"))
    project.update_meta(redo_intake=False)
    project.log("intake_rerun", {"questions": out["questions"], "asked": len(out["asked"]),
                                 "assumed": len(out["assumed"])})
    return out


def superseded(project: Project) -> list[dict[str, Any]]:
    """Every rewind's record of what it set aside, oldest first."""
    from kernel.store import read_json

    out: list[dict[str, Any]] = read_json(project.path("superseded", "index.json"), []) or []
    return out
