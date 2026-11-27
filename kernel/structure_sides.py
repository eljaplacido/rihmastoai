"""What each Alignment item is to the project, and how old its source is (FR-STR2).

The owner (2026-11-26): "how much rihmasto is able / trying to ingest existing structures of project versus are
the tasks highlighted about enforcing rihmasto's own structure? ... Do I just spend accepting changes that forces
project to rihmasto structure or actually moving the needle with dev."

One answer for every view, so the Alignment and Where the work went never disagree:

- ``take_in``: a requirement, criterion, task, decision or API contract read from the project's own files. Taking
  it in is the project's own structure, kept as it is: neither development nor conformance to Rihmasto's;
- ``fact``: a fact about the project's own files (a spec older than its code, CI that does not run the tests);
- ``convention``: a trace link or gap of one of Rihmasto's own conventions (kernel/structure_policy.py): work on it
  is conformance to Rihmasto's structure.

Each item also says how old its source is against the newest code, from git's own dates of the scan: a planning
file weeks older than the code may no longer hold. The IDE text and the headline follow the levels too.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from kernel import structure_policy as sp

SIDES = ("take_in", "fact", "convention")
SIDE_SAID = {"take_in": "the project's own record, taken in as it is: neither development nor conformance to "
                        "Rihmasto's structure",
             "fact": "a fact about the project's own files: neither development nor conformance",
             "convention": "one of Rihmasto's own conventions: work on it is conformance to Rihmasto's structure"}
STALE_DAYS = 14                     # a source this much older than the newest code is flagged
DAY = 86400
TAKEN_WORDS = (("requirements", "requirement", "requirements"), ("criteria", "criterion", "criteria"),
               ("tasks", "task", "tasks"), ("decisions", "decision", "decisions"),
               ("contracts", "API contract", "API contracts"))


def side_of(item: dict[str, Any]) -> str:
    """What an Alignment item is to the project: the project's own record, a fact, or Rihmasto's convention."""
    if sp.convention_of(item):
        return "convention"
    return "take_in" if item.get("group") in sp.TAKE_IN else "fact"


# -- how old a source is -----------------------------------------------------------------------------------

def dates_of(structure: dict[str, Any]) -> dict[str, int]:
    """Each source file's last commit time (seconds), as the scan read it from git."""
    sections = [(structure.get(k) or [], "date") for k in ("specs", "tasks", "contracts")]
    sections += [(structure.get("decisions") or [], "date_committed"),
                 ((structure.get("tests") or {}).get("files") or [], "date")]
    pairs = [(x.get("path"), x.get(field)) for found, field in sections for x in found]
    return {path: at for path, at in pairs if path and isinstance(at, int) and at > 0}


def _day(at: int) -> str:
    return dt.datetime.fromtimestamp(at, dt.UTC).date().isoformat()


def age_of(item: dict[str, Any], dates: dict[str, int], newest: int | None) -> dict[str, Any] | None:
    """How much older an item's source is than the newest code; None when git gave no date."""
    path = (item.get("source") or {}).get("path")
    at = dates.get(path or "")
    if not at or not newest:
        return None
    days = max(0, (newest - at) // DAY)
    older = days >= STALE_DAYS
    said = (f"{path} was last changed {_day(at)}, {days} days before the newest code ({_day(newest)}): check it "
            "still holds before accepting" if older else f"{path} was last changed {_day(at)}, as recent as the "
            "code")
    return {"path": path, "source_at": _day(at), "code_at": _day(newest), "days": days, "older": older,
            "said": said}


def annotate(project: Any, view: dict[str, Any]) -> int:
    """Each item of the view with what it counts as and how old its source is. Returns how many open items of the
    project's own (records and facts) come from a source older than the newest code."""
    from kernel import alignment_records as ar

    structure = (project.read(ar.SCAN) or {}).get("structure") or {}
    dates = dates_of(structure)
    newest = (structure.get("code") or {}).get("newest")
    older = 0
    for g in view.get("groups") or []:
        for i in g["items"]:
            side = side_of(i)
            i["counts_as"], i["counts_as_said"] = side, SIDE_SAID[side]
            i["age"] = age_of(i, dates, newest)
            if side != "convention" and (i["age"] or {}).get("older") and i["status"] in ("open", "changed"):
                older += 1
    return older


# -- the headline ------------------------------------------------------------------------------------------

def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def headline(view: dict[str, Any], test_trace: str) -> None:
    """Rihmasto's own measure (tests tracing to criteria) leads only where that convention is enforced; elsewhere
    the headline is what was taken in from the project's own files, with the measure said as a suggestion."""
    summary = dict(view.get("summary") or {})
    measure = str(summary.get("text") or "")
    summary["measure"] = measure
    if test_trace != "enforce":
        found = {g["id"]: len(g["items"]) for g in view.get("groups") or []}
        taken = [_plural(found.get(gid, 0), one, many) for gid, one, many in TAKEN_WORDS if found.get(gid)]
        level = "Off here" if test_trace == "off" else "Advise here"
        traced = measure.split(";")[0] if measure else ""
        summary["text"] = ("Taken in from the project's own files: " + (", ".join(taken) or "nothing yet")
                           + f". Tests tracing to criteria: {level}"
                           + (f" ({traced})" if traced and test_trace == "advise" else "") + ".")
    view["summary"] = summary


# -- what an IDE agent is asked --------------------------------------------------------------------------

def ide_gaps(factory: Any, project: Any, gaps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """The open gaps an IDE agent is asked to close: the facts and the gaps of an enforced convention. The count
    of those left out (a convention at Advise or Off) comes with them."""
    levels = sp.levels(factory, project)
    kept = [g for g in gaps if (c := sp.convention_of(g)) is None or levels[c] == "enforce"]
    return kept, len(gaps) - len(kept)


def ide_naming(factory: Any, project: Any) -> str:
    """What an IDE agent is told about naming tests: asked only where tests trace to requirements is enforced."""
    if sp.row(factory, project, "test_trace")["level"] == "enforce":
        return "name new tests test_<criterion id>_..."
    return "keep the project's own test names (naming tests test_<criterion id>_ is not asked here)"
