"""Which assessment findings to fix first, and why (FR-AS1; the owner, 2026-11-25: "in the assessment I should be
able to ask Rihma what fixes to prioritise and why").

By rule, with no model, from the latest assessment's open findings (the rules' findings; the panel's proposals
are opinions and come after them): severity first, then the perspective's weight (security and compliance before
CI/CD, operations and maintenance), a finding still open since the version before ranks above a new one of the
same weight, and a finding with a suggested change is a quicker win. A finding already filed as an open change
is left out: it is in hand. Each item says why it is where it is.
"""

from __future__ import annotations

import re
from typing import Any

SEVERITY_WEIGHT = {"critical": 50, "high": 40, "medium": 25, "low": 10, "info": 2}
PERSPECTIVE_WEIGHT = {"security": 8, "compliance": 7, "cicd": 5, "architecture": 4, "maintenance": 3}
ASKS = re.compile(
    r"\b(priori[tsz]\w*|fix first|first to fix|most important|what (should|do) i fix|which (fixes|findings)"
    r"|where (do|should) i start fixing|tärke\w*|ensin korja\w*|mitä korja\w*)\b", re.IGNORECASE)


def asks_priorities(question: str) -> bool:
    """Whether a question asks which fixes or findings come first."""
    return bool(ASKS.search(question or ""))


def _why(f: dict[str, Any], still: bool, labels: dict[str, str]) -> str:
    parts = [f"{f.get('severity') or 'unrated'} severity", f"{labels.get(f.get('perspective', ''), 'other')}"]
    if still:
        parts.append("still open since the version before")
    if f.get("suggestion"):
        parts.append("a suggested change is ready (a quick win)")
    if f.get("by") == "model_proposed":
        parts.append("the panel's opinion, not a rule's finding")
    return "; ".join(parts)


def suggest_class(f: dict[str, Any]) -> tuple[str, str]:
    """The kind of change a finding is best filed as, and why, by rule; the person may choose another."""
    sev, persp = f.get("severity") or "", f.get("perspective") or ""
    if f.get("by") == "model_proposed":
        return "new_requirement", "the panel's opinion, so a business decision comes first"
    if persp == "security" and sev in ("critical", "high"):
        return "defect", "a serious security weakness is a fault to fix, not a wish"
    if persp == "compliance":
        return "new_requirement", "an obligation or policy the business decides on first"
    if persp == "architecture":
        return "infra_change", "operations and hosting: IT decides how it runs"
    if persp == "maintenance" and sev in ("critical", "high"):
        return "defect", "it already breaks or blocks upkeep"
    return "change_request", "an improvement to the repository's own code, pipeline or files"


def _score(f: dict[str, Any], open_before: bool) -> int:
    """How much a finding matters: severity, then perspective, then still open, a ready fix, a rule over an opinion."""
    return (SEVERITY_WEIGHT.get(f.get("severity") or "", 5) + PERSPECTIVE_WEIGHT.get(f.get("perspective") or "", 2)
            + (4 if open_before else 0) + (2 if f.get("suggestion") else 0)
            - (15 if f.get("by") == "model_proposed" else 0))


def ranked(view: dict[str, Any]) -> list[dict[str, Any]]:
    """The open, unfiled findings of the latest assessment, most important first, each with its score and why."""
    latest = view.get("latest") or {}
    filed = view.get("filed") or {}
    still = set((latest.get("since") or {}).get("still") or [])
    labels = view.get("perspectives") or {}
    found = [c for c in latest.get("checks") or [] if c.get("verdict") == "failed"]
    found += [dict(p, by="model_proposed") for p in latest.get("proposals") or []]
    out = []
    for f in found:
        x = filed.get(f.get("key", ""))
        if x and x.get("state") == "open":
            continue
        open_before = f.get("id") in still or f.get("key") in still
        score = _score(f, open_before)
        kind, kind_why = suggest_class(f)
        out.append({"id": f.get("id"), "title": f.get("title"), "severity": f.get("severity"),
                    "perspective": f.get("perspective"), "score": score, "why": _why(f, open_before, labels),
                    "suggested": kind, "suggested_why": kind_why})
    return sorted(out, key=lambda r: (-r["score"], str(r["id"])))


def answer(project: Any) -> dict[str, Any]:
    """Ask Rihma's answer: the top findings to fix and why, with Take me there to the assessment."""
    from kernel.assess_cards import view

    rows = ranked(view(project))
    nav = {"route": f"#/p/{project.pid}/assessment", "control": "assessment_changes"}
    base = {"navigate": nav, "propose": [], "dropped": [], "sources": [], "by": "rule", "matches": []}
    if not (view(project).get("latest")):
        return base | {"answer": f"{project.meta.get('title')} has not been assessed yet: run the assessment first "
                                 f"(Assessment > Assess now, or rihmasto assess {project.pid}); then ask again."}
    if not rows:
        return base | {"answer": "Nothing is left to prioritise: every finding of the latest assessment is fixed or "
                                 "already filed as an open change."}
    top = rows[:5]
    lines = [f"{i}. {r['id']} {r['title']}: {r['why']}." for i, r in enumerate(top, 1)]
    more = f" {len(rows) - len(top)} more follow in the same order." if len(rows) > len(top) else ""
    return base | {"answer": "Fix these first, by rule (severity, then security and compliance before the rest, then "
                             "what stayed open since the version before):\n" + "\n".join(lines) + more
                             + f"\nIn the Assessment view, \"Select the top {len(top)}\" ticks them; "
                             "then file them as changes.",
                   "matches": [r["id"] for r in top]}
