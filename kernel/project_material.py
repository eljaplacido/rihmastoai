"""Add material to a project later (FR-CHG1): more of the request, after the intake or before it.

A project keeps its original request. Material added later is appended to what the panel and the spec
read (``source.json``), under a heading that names it, and kept on its own in ``material.json`` with
its note, who added it and its sha256; the ledger records ``material_added``. Nothing already decided is
touched.

With re-intake the panel reads the new material only, told what was asked before: it asks about what is
new, a question already on record is never asked again, and every answer stands. The new questions are
settled by the project's mode, as at intake. A project with no request yet (new, or sent back to its
material) takes the material as its request, and its intake runs from it: at once with re-intake, else
at the next Advance.

A folder is read the way intake reads one, through the folder scanner (kernel/material.py, by way of
kernel/intake.py ``load_source``), so it is read, summarised, listed or skipped by the same rules.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from kernel import rewind as kr
from kernel.canon import PERSPECTIVES, Canon
from kernel.store import Project, updating_json

ADDERS = ("business_owner", "product_owner", "developer", "stakeholder", "concept_evaluator")
MAX_MATERIAL = 200_000
ADDED_HEADING = "## Added material"
REINTAKE_NOTE = ("\nThis is material ADDED to a request the panel already reviewed. Ask only about what this "
                 "addition says that changes what gets built; never ask again what was asked before.\n")


def _read_path(path: str) -> tuple[str, str]:
    """(kind, text) of a file or a folder on this machine: a folder through the scanner (kernel/material.py,
    by way of intake's load_source), so material added later is read as material given at the start."""
    from kernel.intake import load_source

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no file or folder at {path}")
    return load_source(str(p))


def read_material(text: str | None = None, path: str | None = None) -> tuple[str, str, str | None]:
    """(kind, text, path) of the material: typed text, or a file or folder named by its path."""
    if bool(text and text.strip()) == bool(path and path.strip()):
        raise ValueError("give the material as text or as a path, one of them")
    if path and path.strip():
        kind, body = _read_path(path.strip())
    else:
        kind, body = "idea", str(text)
    body = body.strip()
    if not body:
        raise ValueError("the material is empty")
    if len(body) > MAX_MATERIAL:
        raise ValueError(f"the material is longer than {MAX_MATERIAL:,} characters: add it in parts")
    return kind, body, (path.strip() if path else None)


def _appended(source: dict[str, Any], n: int, note: str, text: str) -> str:
    title = f"{ADDED_HEADING} {n}" + (f": {note}" if note else "")
    return f"{str(source.get('text') or '').rstrip()}\n\n{title}\n\n{text}"


def add_material(project: Project, *, person: str, persona: str, text: str | None = None, path: str | None = None,
                 note: str = "", reintake: bool = False, model: Any = None) -> dict[str, Any]:
    """Add material to the project, signed. With ``reintake`` the panel reads it: at once with ``model``,
    else at the next run of the pipeline (the cockpit starts one), which calls ``pending_intake``."""
    kr.check_signer(project, person, persona, note or "material added", who=ADDERS)
    if project.meta.get("source_kind") in kr.NOT_REWOUND:
        raise ValueError(f"{project.pid} was {project.meta['source_kind']}: file what it needs as a change")
    kind, body, where = read_material(text, path)
    note = note.strip()[:300]
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    source = project.read("source.json")
    stamp = project.factory.clock.stamp()
    # material.json may already hold a folder's material map (kernel/material.py): the added material is kept
    # beside it, under its own keys, and the map stays as it was.
    with updating_json(project.path("material.json"), {}) as kept:
        kept.setdefault("original", None)
        kept.setdefault("added", [])
        if kept["original"] is None and source:
            kept["original"] = {"kind": source.get("kind"), "text": source.get("text"),
                                "requested_by": source.get("requested_by")}
        n = len(kept["added"]) + 1
        kept["added"].append({"n": n, "kind": kind, "text": body, "note": note, "path": where, "chars": len(body),
                              "sha256": digest, "by": person, "persona": persona, "at": stamp})
    first = source is None
    if first:      # no request yet: this is the request, and the intake runs from it
        project.write("source.json", {"kind": kind, "text": body, "requested_by": person})
        project.update_meta(redo_intake=True, source_kind=kind)
    else:
        project.write("source.json", {**source, "text": _appended(source, n, note, body)})
    project.log("material_added", {"n": n, "person": person, "persona": persona, "note": note, "kind": kind,
                                   "chars": len(body), "sha256": digest, "path": where, "as_request": first})
    out: dict[str, Any] = {"n": n, "chars": len(body), "sha256": digest, "as_request": first,
                           "impact": impact(project, first), "reintake": None}
    if reintake and model is None:      # the pipeline's next run reads it (kernel/pipeline.py _shape)
        if not first:
            project.update_meta(reintake_pending=sorted({*project.meta.get("reintake_pending", []), n}))
        out["reintake"] = {"pending": True}
    elif reintake:
        out["reintake"] = kr.rerun_intake(project, model=model) if first else \
            reintake_new(project, body, n=n, model=model, person=person)
    if not first and not (reintake and model is not None):
        from kernel.intake import render_brief

        render_brief(project)
    return out


def pending_intake(project: Project, *, model: Any) -> str | None:
    """What the pipeline runs before anything else: the intake again for a project sent back to its
    questions (or given its request as material), then the panel over material added with re-intake.
    Returns what it did, for the run's history, or None when nothing waits."""
    meta = project.meta
    if not project.path("source.json").exists():
        return None
    if meta.get("redo_intake") or meta.get("panel_unusable"):     # a panel that got no usable answer runs again
        kr.rerun_intake(project, model=model)
        return "intake again over the project's material"
    pending = [n for n in meta.get("reintake_pending") or [] if isinstance(n, int)]
    if not pending:
        return None
    added = {a["n"]: a for a in material(project)["added"]}
    for n in pending:
        if n in added:
            reintake_new(project, added[n]["text"], n=n, model=model, person=str(added[n]["by"]))
    project.update_meta(reintake_pending=[])
    return f"the panel read the added material {', '.join(map(str, pending))}"


def impact(project: Project, first: bool) -> list[str]:
    """What added material means for the work already done."""
    if first:
        return ["This is the project's request: the intake runs from it (now with re-intake, else at the next "
                "Advance)."]
    rows = ["The panel has not read it yet: re-intake asks about what it adds; every answer stands."]
    if project.path("spec.json").exists():
        rows.append("The spec was written before this material: go back to the spec to write it again with it.")
    if kr.releases(project):
        rows.append("A release is out: what the material changes goes through the change loop.")
    return rows


def _ask(project: Project, text: str, model: Any, note: str) -> list[tuple[str, dict[str, Any]]]:
    """Each perspective's questions about the added material: (perspective, item) pairs."""
    from kernel.intake import QUESTIONS_PER_PERSPECTIVE, _ask_json, _perspective_prompt
    from kernel.model import ModelError
    from kernel.outputs import given_for_panel
    from kernel.profiles import profile_of

    maturity, profile, given = project.meta["maturity"], profile_of(project), given_for_panel(project)
    out = []
    for perspective in PERSPECTIVES:
        try:
            answer = _ask_json(model, _perspective_prompt(perspective, text, "added material", maturity, profile,
                                                          note, given, project.factory))
        except ModelError as exc:
            Canon(project).note("intake", f"perspective {perspective} gave no usable answer on added material: {exc}")
            continue
        items = answer.get("questions") if isinstance(answer, dict) else None
        out += [(perspective, i) for i in (items or [])[:QUESTIONS_PER_PERSPECTIVE[maturity]]
                if isinstance(i, dict) and str(i.get("text", "")).strip()]
    return out


def reintake_new(project: Project, text: str, *, n: int, model: Any, person: str) -> dict[str, Any]:
    """The panel reads only the added material: new questions for what is new, settled by the project's
    mode; a question on record (open or settled) is never added again, and every answer is kept."""
    from kernel.intake import KnownCanon, render_brief, settled_note

    canon = KnownCanon(project, keep_open=True)
    before = {q["id"] for q in canon.questions()}
    asked_before = "".join(f"- {q['text']}\n" for q in canon.questions() if q["status"] == "open")
    note = REINTAKE_NOTE + settled_note(canon) + (f"Already asked and still open:\n{asked_before}" if asked_before
                                                  else "")
    for perspective, item in _ask(project, text, model, note):
        _add(canon, perspective, item)
    new = [q for q in canon.questions("open") if q["id"] not in before]
    asked, assumed = _settle(project, canon, new)
    render_brief(project)
    project.log("reintake_done", {"material": n, "person": person, "questions": [q["id"] for q in new],
                                  "asked": asked, "assumed": assumed})
    return {"questions": [q["id"] for q in new], "asked": asked, "assumed": assumed}


def _add(canon: Canon, perspective: str, item: dict[str, Any]) -> None:
    """One question a perspective asked, with its proposed answer first among its options (kernel/intake.py)."""
    proposed = str(item.get("proposed_answer", "")).strip()
    others = [str(o).strip() for o in item.get("options") or [] if str(o).strip() and str(o).strip() != proposed]
    canon.add_question(str(item["text"]).strip(), perspective, blocking=bool(item.get("blocking")),
                       opinions={perspective: proposed} if proposed else {}, rationale=str(item.get("why", "")).strip(),
                       options=([proposed] if proposed else []) + others[:3])


def _settle(project: Project, canon: Canon, new: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Settle new questions by the project's mode, as intake does (kernel/intake.py)."""
    mode = project.meta["mode"]
    asked, assumed = [], []
    for q in new:
        proposed = q["opinions"].get(q["perspective"], "")
        if mode == "socratic" or (mode == "mixed" and q["blocking"]) or not proposed:
            asked.append(canon.ask(q["id"])["id"])
        else:
            assumed.append(canon.assume(q["id"], proposed)["id"])
    return asked, assumed


def material(project: Project) -> dict[str, Any]:
    """The original request and what was added, as kept (beside a folder's material map, when it has one)."""
    kept = project.read("material.json") or {}
    kept = kept if isinstance(kept, dict) else {}
    return {"original": kept.get("original"), "added": list(kept.get("added") or [])}
