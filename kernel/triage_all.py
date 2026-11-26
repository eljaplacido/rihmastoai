"""Decision triage across every project (FR-NVL2): the owner's "I got 50 decisions" is rarely one project's.

The owner (2026-11-25): "I got 50 decisions. Can you prioritize those that block work? And assume me the answers."

By rule, from each project's own triage (kernel/triage.py), for the persona asking:

- **Blocking work, most first**, ranked across projects by the same order a project's triage uses (an incident, a
  stuck task, a plan to approve, a go-ahead, a blocking question ...), each naming its project and why;
- **one proposal** that assumes the rest in every project at once: per project the cards the persona may decide,
  and what stays with the person or with someone else. Confirming it confirms each project's proposal through that
  project's own route (``POST /api/projects/<pid>/triage/assume``), each signed and recorded in its own ledger.
"""

from __future__ import annotations

from typing import Any

from kernel.triage import BLOCKS, triage

ASSUMPTION_RANK = 8


def _order(row: dict[str, Any]) -> tuple[int, str, int]:
    rank = ASSUMPTION_RANK if row["kind"] == "assumption" else BLOCKS.get(row["kind"], (9, ""))[0]
    return rank, str(row["project_title"]).lower(), int(row["rank"])


def _per_project(factory: Any, persona: str | None) -> list[dict[str, Any]]:
    out = []
    for p in factory.projects():
        try:
            t = triage(p, persona)
        except (OSError, ValueError, KeyError):      # a project whose records cannot be read is left out, not fatal
            continue
        if t["total"] or t["blocking"]:
            out.append(t)
    return out


def _plural(n: int, word: str) -> str:
    return " ".join((str(n), word if n == 1 else word + "s"))


def _said(per: list[dict[str, Any]], blocking: list[dict[str, Any]], proposal: dict[str, Any]) -> str:
    total = sum(t["total"] for t in per)
    if not total and not blocking:
        return "No decision is open in any project."
    head = f"Across {_plural(len(per), 'project')}, {_plural(total, 'decision')} {'is' if total == 1 else 'are'} open"
    if blocking:
        b = blocking[0]
        head += (f"; {len(blocking)} block{'s' if len(blocking) == 1 else ''} work. First: {b['project_title']} "
                 f"{b['card'] or b.get('assumption')}, because {b['why']}.")
    else:
        head += ", and none blocks work."
    if proposal["count"]:
        head += (f" I propose to assume the other {proposal['count']} across "
                 f"{_plural(len(proposal['projects']), 'project')}: each is recorded as your delegated choice in its "
                 "project and stays open to a real answer later.")
    if proposal["stays"]:
        n = proposal["stays"]
        head += f" {n} stay{'s' if n == 1 else ''} with you or with someone else: nothing can be assumed for you there."
    return head


def across(factory: Any, persona: str | None = None) -> dict[str, Any]:
    """Every project's open decisions: the blocking ones ranked across projects, and one proposal for the rest."""
    per = _per_project(factory, persona)
    blocking = sorted((b | {"project": t["project"], "project_title": t["title"]} for t in per for b in t["blocking"]),
                      key=_order)
    blocking = [b | {"rank": i} for i, b in enumerate(blocking, 1)]
    parts = [{"project": t["project"], "title": t["title"], "cards": t["proposal"]["cards"],
              "count": t["proposal"]["count"], "assumed": t["proposal"]["assumed"],
              "deferred": t["proposal"]["deferred"]} for t in per if t["proposal"]["count"]]
    proposal = {"count": sum(p["count"] for p in parts), "projects": parts,
                "stays": sum(t["proposal"]["stays"] for t in per)}
    return {"persona": persona, "projects": [{"project": t["project"], "title": t["title"], "total": t["total"],
                                              "blocking": len(t["blocking"])} for t in per],
            "total": sum(t["total"] for t in per), "blocking": blocking, "proposal": proposal,
            "grew": [g | {"project": t["project"], "project_title": t["title"]} for t in per for g in t["grew"]],
            "said": _said(per, blocking, proposal)}
