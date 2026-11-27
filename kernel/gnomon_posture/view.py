"""A project's Gnomon posture as the cockpit, the command line and Ask Rihma show it, and a suggestion filed (FR-GNP1).

``build`` reads the project's own Gnomon files now (kernel/gnomon_posture/read.py) and scores them (score.py):

- not measured, with why, when the project has no working copy or repository Rihmasto holds, or no `.gnomon`
  folder (then: Gnomon is not set up yet, and the first step is ``gnomon init``), never a score of zero;
- which files were read and from where (the working copy's folder, or Rihmasto's copy of the repository), and any
  file that could not be read as TOML;
- the total out of 100, the six dimensions with their checks, the weakest first, and the suggestions, high first,
  each with the file and the exact setting, its full path in the working copy when there is one, and the change
  card it became when it was filed.

``propose`` files one suggestion as a change card in the project's Inbox, signed, once per suggestion. Nothing is
applied and Gnomon is granted no trust or approval: the change is made in the project's own files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.gnomon_posture import FILE, FILERS, SEES, VIEW
from kernel.gnomon_posture.read import read
from kernel.gnomon_posture.score import score
from kernel.people import is_person
from kernel.store import updating_json


def filed(project: Any) -> dict[str, str]:
    """The suggestions filed as change cards: suggestion id -> card id."""
    doc = project.read(FILE, None)
    return {str(k): str(v) for k, v in ((doc or {}).get("filed") or {}).items()} if isinstance(doc, dict) else {}


def _place(file: str, folder: str | None) -> str:
    return str(Path(folder) / Path(file)) if folder else file


def build(factory: Any, project: Any, *, persona: str = "developer") -> dict[str, Any]:
    """The project's Gnomon posture, read from its own files now."""
    got = read(project)
    out: dict[str, Any] = {"project": project.pid, "view": VIEW, "for_personas": list(SEES),
                           "may_file": persona in FILERS}
    if not got["found"]:
        first = None if "no local working copy" in got["why"] else {
            "id": "GP-init", "severity": "high", "dimension": "freshness", "title": "Set Gnomon up for this project",
            "why": "there is no .gnomon folder, so Gnomon governs nothing here", "file": ".gnomon/",
            "setting": "gnomon init in the project's folder", "where": got.get("folder") or "the project's folder"}
        return out | {"measured": False, "why": got["why"], "suggestions": [first] if first else []}
    made = filed(project)
    posture = score(got)
    for s in posture["suggestions"]:
        s["where"] = _place(s["file"], got.get("folder"))
        s["card"] = made.get(s["id"])
    said = ("Read from " + (f"the working copy at {got['at']}" if got["source"] == "folder" else got["at"])
            + ": " + (", ".join(f".gnomon/{n}" for n in got["files"]) or "no config.toml or policy.toml") + ".")
    return out | {"measured": True, "source": got["source"], "at": got["at"], "read": sorted(got["files"]),
                  "problems": got["problems"], "said": said, **posture}


def propose(factory: Any, project: Any, suggestion: str, *, person: str, persona: str) -> dict[str, Any]:
    """File one suggestion (by its id) as a change card in the project's Inbox, signed; once per suggestion."""
    from kernel.change import submit

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a change is filed by a named person")
    if persona not in FILERS:
        raise DecisionRefused(f"a {persona} may not file a Gnomon posture suggestion; a developer or IT does")
    v = build(factory, project, persona=persona)
    found = next((s for s in v.get("suggestions") or [] if s["id"] == suggestion), None)
    if found is None:
        raise KeyError(f"no suggestion {suggestion} in {project.pid}'s Gnomon posture now "
                       f"({v.get('why') or 'the setting already holds'})")
    if found.get("card"):
        return {"suggestion": found, "card": {"id": found["card"]}, "already": True}
    text = (f"Gnomon posture: {found['title']}\n\nWhy ({found['severity']}, {found['dimension']}): {found['why']}.\n\n"
            f"Set in {found['where']}: {found['setting']}\n\nRihmasto applied nothing: the change is made in the "
            "project's own Gnomon files, and trusting or approving Gnomon stays the owner's act. "
            f"Suggestion {found['id']}, from the project's Gnomon posture.")
    card = submit(project, persona=persona, person=person, text=text)
    with updating_json(project.path(FILE), {}) as kept:
        kept["filed"] = dict(kept.get("filed") or {}) | {found["id"]: card["id"]}
    project.log("gnomon_posture_filed", {"suggestion": found["id"], "dimension": found["dimension"],
                                         "severity": found["severity"], "card": card["id"], "person": person,
                                         "persona": persona})
    return {"suggestion": found | {"card": card["id"]}, "card": card, "already": False}
