"""Ask Rihma about a project's Gnomon posture (FR-GNP1), by rule and without a model, as the project status is.

A question about how well Gnomon governs the project, what to tighten first or its Gnomon score is answered from the
project's own Gnomon files, read now, with Take me there to the Gnomon posture view: the total, the weakest
dimensions and the first settings to tighten (each one a person may file as a change card on the view), or, when
there is nothing to read, why and the first step. The assistant itself writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.gnomon_posture import VIEW
from kernel.gnomon_posture.view import build

PHRASES = ("gnomon posture", "gnomon safety", "gnomon score", "gnomon governance", "gnomon governing",
           "governed by gnomon", "gnomon govern", "how well does gnomon", "how well is gnomon", "tighten first",
           "what should i tighten", "gnomon settings", "gnomonin pisteet")
_ASKS = re.compile("|".join(re.escape(p).replace(r"\ ", " ").replace(" ", r"\s+") for p in PHRASES), re.IGNORECASE)


def asks(question: str) -> bool:
    """Whether the question is about a project's Gnomon posture (any spacing, any case)."""
    return _ASKS.search(question or "") is not None


def _out(answer: str, route: str | None, control: str | None = None) -> dict[str, Any]:
    return {"answer": answer, "navigate": {"route": route, "control": control} if route else None, "propose": [],
            "dropped": [], "sources": [], "by": "map", "matches": [VIEW]}


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """The answer, or None when the question is not about the Gnomon posture."""
    if not asks(question):
        return None
    if project is None:
        return _out("Gnomon safety is a view of each project, for developers and IT: how well Gnomon governs it and "
                    "what to tighten first, from the project's own Gnomon files. Open a project to see it.",
                    "#/projects")
    route = f"#/p/{project.pid}/{VIEW}"
    v = build(factory, project, persona=persona)
    title = project.meta.get("title")
    if not v["measured"]:
        first = (v.get("suggestions") or [{}])[0]
        return _out(f"Gnomon posture for {title}: not measured: {v['why']}."
                    + (f" First: {first['setting']}." if first.get("setting") else ""), route, "gnomon_posture_card")
    tighten = [s for s in v["suggestions"] if s["severity"] == "high"] or v["suggestions"]
    weakest = ", ".join(f"{d['label']} {round(d['pct'])}%" for d in v["dimensions"][:3])
    first = "; ".join(f"{s['title']} ({s['setting']} in {s['file']})" for s in tighten[:3])
    more = len(v["suggestions"]) - min(3, len(tighten))
    return _out(f"Gnomon governs {title} at {v['total']}/100, from its own Gnomon files. Weakest: {weakest}. "
                + (f"Tighten first: {first}." if first else "Every setting checked holds.")
                + (f" {more} more on the view;" if more > 0 else "")
                + " each can be filed as a change card you decide. " + v["said"], route, "gnomon_posture_card")
