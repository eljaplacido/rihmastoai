"""Ask Rihma about epics, by rule (FR-S2, UI and chat parity): the same tree the Board shows, and an epic made or
linked through the same signed route as the Board's New epic.

- "show the epics", "which epics are there?", "epics and their stories": each epic with whether it qualifies, its
  requirements and their tasks (lane, commits, tests), and the requirements under no epic; Take me there opens the
  Board's Epics;
- "create an epic <title> with R-1, R-2, owned by <name>, done when <words>": a proposal (``act`` create_epic) the
  person confirms, signed; offered to a business owner or product owner only, as the route allows;
- "link R-3 to E-1" ("put R-3 under E-1"): a proposal (``act`` link_epic) with E-1's requirements and R-3.

It writes nothing; the route behind the proposal checks everything again.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import epics as kepics

SHOW = re.compile(r"\bepics?\b")
CREATE = re.compile(r"\b(create|add|new|make|start)\b.{0,12}\bepic\b")
LINK = re.compile(r"\b(link|put|move|add)\b.*\b(R-[\w-]+)\b.*\b(to|under|into)\b.*\b(E-\d+)\b", re.I)
REQ = re.compile(r"\bR-\d+[\w-]*\b", re.I)
OWNER = re.compile(r"\b(?:owned by|owner(?: is)?)\s+([A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3})")
DONE = re.compile(r"\b(?:done when|criterion(?: is)?|accepted when)\s+(.+?)(?:[.;]|$)", re.I)


TITLE = re.compile(r"\bepic\b\s*(?:called|named|titled|:)?\s*[\"“']?(.+?)[\"”']?"
                   r"(?=\s+(?:with|owned by|owner|done when|for)\b|[.;]|$)", re.I)


def _said(pattern: re.Pattern[str], question: str) -> str:
    m = pattern.search(question)
    return m.group(1).strip() if m else ""


def _title(question: str) -> str:
    return _said(TITLE, question)[:200]


def _out(text: str, pid: str, *, propose: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"answer": text, "navigate": {"route": f"#/p/{pid}/board", "control": "epics"},
            "propose": propose or [], "dropped": [], "sources": [], "by": "map", "matches": ["epics"]}


def tree_text(t: dict[str, Any]) -> str:
    """The tree in sentences: epic, qualification, requirements with their tasks and lanes."""
    if not t["epics"]:
        return ("This project has no epic yet. An epic is a customer's wish with a named owner and a criterion in the "
                "owner's words; a business owner or product owner creates it and puts requirements under it "
                f"({len(t['unlinked'])} requirement(s) are under no epic now).")
    parts = []
    for e in t["epics"]:
        reqs = "; ".join(f"{r['id']}: " + (", ".join(f"{x['id']} {x['lane'].replace('_', ' ')}" for x in r["tasks"])
                                           or "no task yet") for r in e["requirements"]) or "no requirement yet"
        q = "qualifies" if e["qualified"] else "does not qualify yet (missing " + "; ".join(e["missing"]) + ")"
        parts.append(f"{e['id']} {e['title']} {q}: {reqs}")
    loose = [r["id"] for r in t["unlinked"]]
    return ("Epics: " + ". ".join(parts) + "." + (f" Under no epic: {', '.join(loose)}." if loose else ""))


def _create(factory: Any, project: Any, question: str, persona: str) -> dict[str, Any]:
    title = _title(question)
    owner, done = _said(OWNER, question), _said(DONE, question)
    reqs = sorted({r.upper() for r in REQ.findall(question)})
    if persona not in kepics.DECIDERS:
        return _out(f"As {persona.replace('_', ' ')} you cannot create an epic: a business owner or product owner "
                    "does, on the Board's Epics (New epic).", project.pid)
    if not title:
        return _out("Say the epic's title, for example: create an epic \"Stock is always right\" with R-1, R-2, owned "
                    "by Aino, done when the counts match the warehouse. Or press New epic on the Board.", project.pid)
    from kernel.assistant_ops import proposal

    args = {"title": title, "owner": owner, "criterion": done, "requirements": reqs, "questions": []}
    made = proposal(factory, "create_epic", args, persona=persona, project=project,
                    summary=f"Create the epic \"{title}\"" + (f" with {', '.join(reqs)}" if reqs else ""))
    return _out(f"Confirm to create the epic \"{title}\"" + (f" with {', '.join(reqs)}" if reqs else "")
                + (f", owned by {owner}" if owner else ", with no owner named yet")
                + (f", done when {done}" if done else "") + ": it is signed with your name.", project.pid,
                propose=[made] if made else [])


def _link(factory: Any, project: Any, m: re.Match[str], persona: str) -> dict[str, Any]:
    eid, rid = m.group(4).upper(), m.group(2).upper()
    found = next((e for e in kepics.epics(project) if e["id"] == eid), None)
    if found is None:
        return _out(f"There is no epic {eid} in this project.", project.pid)
    if persona not in kepics.DECIDERS:
        return _out("A business owner or product owner links requirements to an epic.", project.pid)
    from kernel.assistant_ops import proposal

    reqs = sorted({*found.get("requirements", []), rid})
    made = proposal(factory, "link_epic", {"epic": eid, "requirements": reqs}, persona=persona, project=project,
                    summary=f"Put {rid} under {eid}")
    return _out(f"Confirm to put {rid} under {eid} ({found['title']}): signed with your name.", project.pid,
                propose=[made] if made else [])


def answer(factory: Any, project: Any, question: str, persona: str) -> dict[str, Any] | None:
    """The answer, or None when the question is not about epics or no project is open."""
    if project is None or project.pid.startswith("_"):
        return None
    link = LINK.search(question)
    if link is None and not SHOW.search(question.lower()):
        return None
    if link:
        return _link(factory, project, link, persona)
    if CREATE.search(question.lower()):
        return _create(factory, project, question, persona)
    return _out(tree_text(kepics.tree(project)) + " Take me there opens the Board's Epics.", project.pid)


__all__ = ["answer", "tree_text"]
