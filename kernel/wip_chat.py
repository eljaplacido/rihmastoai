"""Ask Rihma about a project's work in progress (FR-WIP1), by rule and without a model, with Take me there.

"What am I in the middle of?", "what's uncommitted?", "what have I not committed?", "show my work in progress": what
the project's working copy holds that is not committed yet, by area, the oldest change, the branch against its
remote, and what to do about it (kernel/wip.py). Reading only; nothing is proposed that writes.
"""

from __future__ import annotations

import re
from typing import Any

ASKS = re.compile(r"\bin the middle of\b|\bwork[- ]in[- ]progress\b|\bwip\b|\buncommitted\b|\bnot (?:yet )?committed\b"
                  r"|\b(?:haven'?t|have not|didn'?t|did not) (?:yet )?commit|\bunstaged\b|\blocal changes\b"
                  r"|\bworking (?:copy|tree)\b", re.IGNORECASE)
CONTROL = "wip_card"


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """The project's work in progress, by rule; None when the words ask something else."""
    if ASKS.search(question or "") is None:     # uncommitted work, not committing in general ("how do I commit?")
        return None
    if project is None or project.pid.startswith("_"):
        return _out(None, "Work in progress is read from a project's own working copy: open an adopted or attached "
                          "project and ask there.")
    from kernel import wip

    r = wip.read(project)
    said = r["said"]
    if r.get("measured") and r["areas"]:
        top = "; ".join(f"{a['area']} {a['total']}" for a in r["areas"][:5])
        said += f" By area: {top}."
    return _out(project, said)


def _out(project: Any, answer: str) -> dict[str, Any]:
    route = f"#/p/{project.pid}/overview" if project is not None else "#/projects"
    open_it = {"action": "open", "args": {"route": route}, "why": "See the work in progress on the Overview",
               "project": project.pid if project else None}
    return {"answer": answer, "navigate": {"route": route, "control": CONTROL}, "propose": [open_it], "dropped": [],
            "sources": [], "by": "rule", "matches": [CONTROL]}
