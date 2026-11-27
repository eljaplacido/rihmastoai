"""Ask Rihma on an alignment's items, by rule (FR-ORG1; kernel/assistant.py asks ``answer`` before any model).

"What should I do with these?" on the Alignment view (the code plan), or "which of the alignment's items are
Rihmasto's own structure?" anywhere in an adopted project, gets the same triage the view's head shows
(kernel/alignment_triage.py): how many items come from the project and how many from Rihmasto's convention, which may
be from an old plan, the recommendation, and each triage action as a proposal the person confirms, with its impact.
Confirm sends the same signed request as the view's buttons (``OPS``, kernel/assistant_ops.py).
"""

from __future__ import annotations

import re
from typing import Any

# The triage's write, offered as an operation of Ask Rihma: (label, method, path, needs, sends, the map's control).
OPS: dict[str, tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]] = {
    "align_triage": ("Act on the alignment's triage", "POST", "/api/projects/{pid}/repo-alignment/triage", ("do",),
                     ("do", "items"), "align_triage"),
}
_ABOUT = re.compile(r"\b(?:code plan|alignment|align|aligned|aligning|conventions?|old plan|stale|gaps?|to decide|"
                    r"rihmasto(?:'?s)? (?:own )?(?:structure|rules?|conventions?)|(?:existing|own) structures?|"
                    r"structures? of (?:my|our|the) project)\b", re.I)
# The owner's own phrasings (FR-ORG2): "enforcing", "which of these are stale?", "what happens if I accept all gaps?"
_ASK = re.compile(r"\bwhat (?:should|shall|do|can|must) (?:i|we) do\b|\bwhat to do\b|\bhow do (?:i|we) know\b|"
                  r"\bwhere (?:do|should) (?:i|we) start\b|\btriage\b|\bimpact\b|"
                  r"\bwhich (?:of (?:these|them|the \w+) )?(?:ones? )?(?:should|to|are|is|do|can)\b|"
                  r"\b(?:en)?forc\w*\b.*\bstructure|\bingest\w*\b|\b(?:move|moving) the needle\b|\bblindly\b|"
                  r"\bwhat (?:happens|would happen|changes|does it do|would it do) if\b|"
                  r"\bshould (?:i|we) (?:accept|reject|defer)\b|"
                  r"\bfrom (?:my|the|our) project\b|\b(?:is|are) (?:this|these|they) (?:from|rihmasto)", re.I)


def asked(question: str, view: str | None) -> bool:
    """A question about what to do with the alignment's items: on the Alignment view any such question is about
    them; elsewhere it must name them (FR-ORG2)."""
    if not _ASK.search(question):
        return False
    return view == "align" or bool(_ABOUT.search(question))


def _shape(answer: str, route: str | None, propose: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    nav = {"route": route, "control": "align_triage"} if route else None
    return {"answer": answer, "navigate": nav, "by": "rule", "propose": propose, "dropped": [], "sources": [],
            **extra}


def _lead(project: Any, view: dict[str, Any], question: str) -> tuple[str | None, list[dict[str, Any]]]:
    """What the question asks first (FR-ORG2): the impact of a what-if, or the development line for "am I moving
    the needle"; and the advice without the line already said."""
    from kernel import alignment_advice as adv
    from kernel import alignment_impact as imp

    advice = view["triage"]["advice"]
    asked_if = adv.whatif(question)
    if asked_if:
        verb, kind, part = asked_if
        ids = adv.whatif_items(view, kind, part)
        return adv.whatif_said(verb, kind, part, ids, imp.impact(project, ids, verb) if ids else None), advice
    if adv.NEEDLE.search(question):
        dev = [a for a in advice if a.get("about") == "development"]
        return (dev[0]["text"] if dev else None), [a for a in advice if a.get("about") != "development"]
    return None, advice


def triage_answer(factory: Any, project: Any, persona: str | None = None, question: str = "") -> dict[str, Any]:
    """The alignment's triage in words, with each action as a proposal to confirm."""
    from kernel import alignment_records as ar
    from kernel import assistant_ops as ops

    if project is None:
        return _shape("Open the adopted project and ask again: the alignment's items are that project's.", "#/projects",
                      [])
    route = f"#/p/{project.pid}/align"
    view = ar.view(project)
    if not view.get("applies"):
        return _shape(f"Alignment does not apply here: {view.get('why')}.", None, [])
    if not view.get("scanned"):
        p = ops.proposal(factory, "align_scan", {}, persona=persona or "developer", project=project)
        return _shape("Nothing to decide yet: the repository has not been read. Read it first; every item then says "
                      "whether it is taken from your project or Rihmasto's convention.", route, [p] if p else [])
    t = view["triage"]
    # each proposal carries the items its impact was said for: confirmed later, it takes only those still to take
    offered = [ops.proposal(factory, "align_triage", {"do": a["do"], "items": a["items"]},
                            persona=persona or "developer", project=project,
                            summary=f"{a['label']} ({a['count']}): {a['impact']}")
               for a in t["actions"]]
    proposals = [p for p in offered if p]
    tail = (" Nothing is done yet: what I propose below runs only when you confirm it, signed with your name."
            if proposals else "")
    lead, advice = _lead(project, view, question)
    text = " ".join([*([lead] if lead else []), t["said"], *(a["text"] for a in advice)]) + tail
    return _shape(text, route, proposals, align_triage=t)


def answer(factory: Any, project: Any, question: str, view: str | None = None,
           persona: str | None = None) -> dict[str, Any] | None:
    """The triage when the question asks what to do with an adopted project's alignment items; else None."""
    if project is None or project.meta.get("source_kind") not in ("adopted", "attached") or not asked(question, view):
        return None
    return triage_answer(factory, project, persona, question)
