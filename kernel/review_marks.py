"""A person's review, recorded (FR-REV1): "I looked at this" and "I looked at all of it", each signed.

- ``mark`` records ``review_marked`` in the item's project ledger, per item: a task a builder cell merged, a
  release, an output, a commit gated from an IDE, or any other record of the review (a failure seen, a
  delegated decision let stand). The record shows a human looked; it decides nothing and approves nothing.
- ``done`` records ``review_done``, with the period and how many items each group held: in the factory's
  ledger for a review across projects, in a project's ledger for that project's review. Its ``until`` is the
  person's marker: their next review starts there (kernel/review.py).

A card is decided, not marked (its own signed route does that), and a job is not a record. Each write is
signed by a named person and persona and, while access is enforced, by an identity granted that persona where
it acts (``kernel.access.require``).
"""

from __future__ import annotations

import re
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person

ITEM = re.compile(r"(?P<pid>[a-z0-9_][a-z0-9-]{0,80})/(?P<kind>task|release|ledger|gate|assumption|card)/"
                  r"(?P<ref>[A-Za-z0-9_.-]{1,64})\Z")
MARKABLE = ("task", "release", "ledger", "gate", "assumption")
MAX_ITEMS = 200


def parse_item(text: str) -> tuple[str, str, str]:
    """(project, kind, ref) of an item id such as ``orders-1a2b3c/task/T-001``."""
    m = ITEM.match(str(text or "").strip())
    if not m:
        raise ValueError(f"an item is <project>/<task|release|ledger|gate|assumption>/<id>, such as "
                         f"orders-1a2b3c/task/T-001, not {str(text)[:80]!r}")
    return m.group("pid"), m.group("kind"), m.group("ref")


def _signer(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a review is signed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"persona must be one of {', '.join(PERSONAS)}")


def _task(project: Any, ref: str) -> dict[str, Any]:
    merged = [r for r in project.ledger().of_kind("merged") if r["event"]["payload"].get("task") == ref]
    if not merged:
        raise ValueError(f"{ref} was not merged on {project.pid}: only shipped work is marked reviewed")
    return {"task": ref, "revision": merged[-1]["event"]["payload"].get("revision"), "of_seq": merged[-1]["seq"]}


def _release(project: Any, ref: str) -> dict[str, Any]:
    from kernel.deliver import releases

    rel = next((r for r in releases(project) if str(r.get("release")) == ref), None)
    if rel is None:
        raise ValueError(f"{project.pid} has no release {ref}")
    return {"release": rel["release"], "revision": rel.get("revision"), "state": rel.get("state")}


def _assumption(project: Any, ref: str) -> dict[str, Any]:
    from kernel.canon import Canon

    if not any(a["id"] == ref for a in Canon(project).assumptions()):
        raise ValueError(f"{project.pid} has no assumption {ref}")
    return {"assumption": ref}


def _record(project: Any, ref: str) -> dict[str, Any]:
    if not ref.isdigit():
        raise ValueError(f"an item names a ledger record by its number, not {ref!r}")
    rec = next((r for r in project.ledger().records() if isinstance(r, dict) and r.get("seq") == int(ref)), None)
    if rec is None or rec["event"].get("kind") in ("review_marked", "review_done", "cockpit_write"):
        raise ValueError(f"{project.pid} has no record {ref} to review")
    return {"of_seq": int(ref), "of_kind": rec["event"].get("kind")}


TARGETS = {"task": _task, "release": _release, "assumption": _assumption, "ledger": _record, "gate": _record}


def _target(project: Any, kind: str, ref: str) -> dict[str, Any]:
    """What the item names, from the records, or ValueError: a review marks only what happened."""
    return TARGETS[kind](project, ref)


def mark(factory: Any, items: list[str], *, person: str, persona: str, note: str = "") -> list[dict[str, Any]]:
    """Record that ``person`` reviewed each item: every item is checked first, so a bad one records none."""
    from kernel.access import require

    _signer(person, persona)
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        raise ValueError(f"name one to {MAX_ITEMS} items to mark reviewed")
    planned = []
    for text in dict.fromkeys(items):
        pid, kind, ref = parse_item(text)
        if kind == "card":
            raise ValueError("a card is decided, not marked: approve or decline it, or open it in the Inbox")
        if kind not in MARKABLE:
            raise ValueError(f"a {kind} item is not marked reviewed")
        try:
            project = factory.project(pid)
        except KeyError:
            raise ValueError(f"no project {pid}") from None
        require(project, person, persona)             # with access enforced: granted there, or refused
        planned.append((project, text, kind, _target(project, kind, ref)))
    out = []
    for project, text, kind, target in planned:
        rec = project.log("review_marked", {"item": text, "kind": kind, **target, "person": person, "persona": persona,
                                            **({"note": note[:500]} if note else {})})
        out.append({"item": text, "project": project.pid, "seq": rec["seq"], "person": person, "persona": persona,
                    "at": rec["event"].get("at")})
    return out


def done(factory: Any, *, person: str, persona: str, project: str | None = None,
         since: str | None = None, jobs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Record that ``person`` reviewed everything up to now: the period, each group's count, and the marker."""
    from kernel.access import require
    from kernel.learn import FACTORY_PID, factory_project
    from kernel.review import heads_of, review
    from kernel.store import Project

    _signer(person, persona)
    target = factory.project(project) if project else factory_project(factory, create=False)
    require(target if target is not None else Project(factory, FACTORY_PID), person, persona)
    heads = heads_of(factory, project)          # taken first: a record that lands meanwhile shows next time
    seen = review(factory, person=person, persona=persona, project=project, since=since, jobs=jobs, diffs=False)
    target = target or factory_project(factory)
    counts = dict(seen["counts"])
    rec = target.log("review_done", {"scope": project or "all", "since": seen["since"], "until": seen["until"],
                                     "counts": counts, "heads": heads, "person": person, "persona": persona})
    return {"scope": project or "all", "since": seen["since"], "until": seen["until"], "counts": counts,
            "headline": seen["headline"], "seq": rec["seq"], "ledger": target.pid, "person": person,
            "persona": persona}
