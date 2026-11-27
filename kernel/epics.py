"""Epics: the customer's wishes above the requirements, linked down to tasks, commits and tests (FR-S2).

docs/factory-overview.md: "Epics: the customer's wishes, each with goal, owner and criterion in the owner's words",
created by a person, and "an epic qualifies only with three things: a named business owner, an acceptance criterion
in the owner's words, and its blocking questions linked". Here:

- an epic lives in the project's canon (``canon/epics.json``), written only through ``add`` and ``link``, each signed
  by a named person as a business owner or product owner, and recorded in the ledger (``epic_created``,
  ``epic_linked``); an agent proposes one in the Inbox or the channel, never writes it;
- it holds the requirements it is made of (the stories and features, R-n in the spec), its owner, its criterion in
  the owner's words and the blocking questions linked to it;
- ``qualification`` says whether it qualifies, and what is missing when it does not: no named owner, no criterion,
  or an open blocking question linked to no epic;
- ``tree`` is the hierarchy read from the records: epic -> requirements -> the contract tasks whose criteria rest on
  them (each with its lane on the development board) -> each task's commits and tests; the requirements under no
  epic are listed too ("features without an epic"). Reading writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.canon import DecisionRefused
from kernel.graph_records import object_of as _d
from kernel.people import is_person
from kernel.store import read_json, updating_json

FILE = "canon/epics.json"
DECIDERS = ("business_owner", "product_owner")
EID = re.compile(r"\AE-\d{1,6}\Z")
MAX_TEXT = 2000


class EpicRefused(DecisionRefused):
    """An epic write refused for who makes it (not a person, a persona that does not write epics): 403."""


def epics(project: Any) -> list[dict[str, Any]]:
    return [e for e in read_json(project.path(FILE), []) or [] if isinstance(e, dict) and e.get("id")]


def _requirements(project: Any) -> list[dict[str, Any]]:
    spec = _d(project.read("spec.json", None))
    contract = _d(project.read("contract.json", None))
    reqs = spec.get("requirements") or contract.get("requirements") or []
    return [r for r in reqs if isinstance(r, dict) and r.get("id") and r.get("status") != "removed"]


def _questions(project: Any) -> list[dict[str, Any]]:
    return [q for q in read_json(project.path("canon/questions.json"), []) or [] if isinstance(q, dict)]


def _ids(values: Any) -> list[str]:
    return list(dict.fromkeys(str(v).strip().upper() for v in values or [] if str(v).strip()))


def _known(ids: list[str], known: set[str], what: str, where: str) -> list[str]:
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f"no {what} {', '.join(unknown)} in this project's {where}"
                         + (f": it has {', '.join(sorted(known))}" if known else ""))
    return ids


def _checked(project: Any, person: str, persona: str, requirements: Any, questions: Any) -> tuple[list[str], list[str]]:
    if not is_person(person):
        raise EpicRefused(f"{person!r} is not a person: a person creates and links epics, an agent proposes them")
    if persona not in DECIDERS:
        raise EpicRefused("an epic is the customer's wish: a business owner or a product owner writes it")
    reqs = _known(_ids(requirements), {r["id"] for r in _requirements(project)}, "requirement", "spec")
    return reqs, _known(_ids(questions), {q["id"] for q in _questions(project)}, "question", "canon")


def _text(value: Any, what: str, *, required: bool) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"an epic needs its {what}")
    if len(text) > MAX_TEXT:
        raise ValueError(f"the {what} is at most {MAX_TEXT} characters")
    return text


def add(project: Any, *, title: str, owner: str = "", criterion: str = "", goal: str = "",
        requirements: Any = (), questions: Any = (), person: str, persona: str) -> dict[str, Any]:
    """A new epic, signed by ``person`` as a business owner or product owner, recorded as ``epic_created``."""
    reqs, qs = _checked(project, person, persona, requirements, questions)
    epic = {"title": _text(title, "title", required=True), "owner": _text(owner, "owner", required=False),
            "criterion": _text(criterion, "criterion in the owner's words", required=False),
            "goal": _text(goal, "goal", required=False), "requirements": reqs, "questions": qs, "state": "open",
            "created": project.factory.clock.stamp(), "by": {"person": person, "persona": persona}}
    with updating_json(project.path(FILE), []) as items:
        epic = {"id": f"E-{len(items) + 1}", **epic}
        items.append(epic)
    project.log("epic_created", {"id": epic["id"], "title": epic["title"], "owner": epic["owner"] or None,
                                 "requirements": reqs, "questions": qs, "person": person, "persona": persona})
    return epic


def link(project: Any, eid: str, *, requirements: Any = None, questions: Any = None, owner: str | None = None,
         criterion: str | None = None, person: str, persona: str) -> dict[str, Any]:
    """Change what an epic holds: its requirements and questions (each list as a whole), its owner or criterion."""
    reqs, qs = _checked(project, person, persona, requirements, questions)
    changed: dict[str, Any] = {}
    with updating_json(project.path(FILE), []) as items:
        epic = next((e for e in items if isinstance(e, dict) and e.get("id") == eid), None)
        if epic is None:
            raise ValueError(f"no epic {eid} in this project")
        if requirements is not None:
            changed["requirements"] = epic["requirements"] = reqs
        if questions is not None:
            changed["questions"] = epic["questions"] = qs
        if owner is not None:
            changed["owner"] = epic["owner"] = _text(owner, "owner", required=False)
        if criterion is not None:
            changed["criterion"] = epic["criterion"] = _text(criterion, "criterion in the owner's words",
                                                             required=False)
        out = dict(epic)
    if not changed:
        raise ValueError("say what changes: requirements, questions, owner or criterion")
    project.log("epic_linked", {"id": eid, **changed, "person": person, "persona": persona})
    return out


def qualification(project: Any, epic: dict[str, Any], linked: set[str] | None = None) -> dict[str, Any]:
    """Whether the epic qualifies (a named owner, a criterion in the owner's words, blocking questions linked)."""
    if linked is None:
        linked = {q for e in epics(project) for q in e.get("questions") or []}
    missing = [said for said, ok in (("a named business owner", is_person(epic.get("owner"))),
                                     ("an acceptance criterion in the owner's words",
                                      bool(str(epic.get("criterion") or "").strip()))) if not ok]
    unlinked = [q["id"] for q in _questions(project)
                if q.get("blocking") and q.get("status") == "open" and q["id"] not in linked]
    if unlinked:
        missing.append("its blocking questions linked (" + ", ".join(unlinked) + " linked to no epic)")
    return {"qualified": not missing, "missing": missing}


def _task_rows(project: Any) -> dict[str, list[dict[str, Any]]]:
    """Each requirement's tasks as the development board shows them: lane, commits and tests."""
    from kernel.devboard import board

    out: dict[str, list[dict[str, Any]]] = {}
    for c in board(project)["cards"]:
        if c["kind"] != "task":
            continue
        row = {"id": c["id"], "title": c["title"], "lane": c["lane"], "status": c.get("status"),
               "commits": c.get("commits_total", 0), "tests": [{"name": t.get("name"), "result": t.get("result")}
                                                               for t in c.get("tests") or []][:12],
               "criteria": [x["id"] for x in c.get("criteria") or []], "open": c.get("open")}
        for rid in c.get("requirements") or []:
            out.setdefault(rid, []).append(row)
    return out


def _req_row(r: dict[str, Any], tasks: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"id": r["id"], "statement": str(r.get("statement") or "")[:300], "priority": r.get("priority"),
            "tasks": tasks.get(r["id"], [])}


def tree(project: Any) -> dict[str, Any]:
    """The hierarchy: each epic with its qualification, requirements, their tasks, commits and tests."""
    reqs = {r["id"]: r for r in _requirements(project)}
    tasks = _task_rows(project)
    found = epics(project)
    linked = {q for e in found for q in e.get("questions") or []}
    held = {rid for e in found for rid in e.get("requirements") or []}
    rows = []
    for e in found:
        rows.append({**e, **qualification(project, e, linked),
                     "requirements": [_req_row(reqs[rid], tasks) for rid in e.get("requirements") or []
                                      if rid in reqs]})
    return {"project": project.pid, "epics": rows,
            "unlinked": [_req_row(r, tasks) for rid, r in reqs.items() if rid not in held],
            "requirements": sorted(reqs), "deciders": list(DECIDERS)}


def epics_of_tasks(project: Any) -> dict[str, list[str]]:
    """Each task's epics (through its requirements), for the board's cards and filter."""
    contract = _d(project.read("contract.json", None))
    by_req: dict[str, list[str]] = {}
    for e in epics(project):
        for rid in e.get("requirements") or []:
            by_req.setdefault(rid, []).append(e["id"])
    out: dict[str, list[str]] = {}
    for t in contract.get("tasks") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        reqs = {str(c).rsplit("-AC-", 1)[0] for c in t.get("criteria") or []}
        found = sorted({eid for rid in reqs for eid in by_req.get(rid, [])})
        if found:
            out[t["id"]] = found
    return out


__all__ = ["EpicRefused", "add", "epics", "epics_of_tasks", "link", "qualification", "tree"]
