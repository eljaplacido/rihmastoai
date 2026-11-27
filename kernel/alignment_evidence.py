"""What the project's own evidence and the person's decisions say about each alignment item (FR-ORG2,
docs/guides/alignment.md).

An independent check of FR-ORG1 found the triage promising what could not happen and the view disagreeing with it.
The rules here keep them to one reading of the latest scan and the decisions, writing nothing:

- **checked by current tests**: a requirement, criterion or task the project's tests still check (a trace that is not
  weak and not rejected, to it, to its requirement or to what a task serves) is not "may be an old plan", however old
  its file: the code went on with it, not without it;
- **closed**: a gap about an item a person rejected is closed, as the measured state already counts it;
- **counted**: a test counts against a criterion only when both its trace and the criterion are in the contract;
- **dangling**: a test trace to a rejected criterion is never accepted with the current sources;
- **what the suggestions are about**: what nobody rejected, so a suggestion never asks for work on a rejected item;
- **the filters**: each counts the rows it shows.
"""

from __future__ import annotations

from typing import Any

from kernel import alignment_origin as org

Items = list[dict[str, Any]]
Book = dict[str, dict[str, Any]]


def rejected(decided: Book) -> set[str]:
    return {k for k, d in decided.items() if d["verdict"] == "reject"}


def accepted(decided: Book) -> set[str]:
    return {k for k, d in decided.items() if d["verdict"] == "accept"}


def checked_by(items: Items, decided: Book) -> dict[str, list[str]]:
    """The current tests that check each requirement, criterion and task: a criterion's own traces, else its
    requirement's (a criterion of a requirement the code tests is part of the current plan), a requirement's through
    its criteria, a task's through what it serves. Weak and rejected traces are no evidence."""
    own = _own_traces(items, rejected(decided))
    out: dict[str, list[str]] = {}
    for r in (i for i in items if i["group"] == "requirements"):
        tests = list(dict.fromkeys(x for c in r["children"] for x in own.get(c, [])))
        out[r["id"]] = tests
        out.update({c: own.get(c) or tests for c in r["children"]})
    for task in (i for i in items if i["group"] == "tasks"):
        out[task["id"]] = list(dict.fromkeys(x for g in task["proposal"].get("targets", []) for x in out.get(g, [])))
    return {k: v for k, v in out.items() if v}


def _own_traces(items: Items, no: set[str]) -> dict[str, list[str]]:
    """Each criterion's own tests: its traces that are not weak and not rejected."""
    own: dict[str, list[str]] = {}
    for t in (i for i in items if i["group"] == "trace" and not i.get("weak") and i["id"] not in no):
        own.setdefault(t["proposal"]["criterion"], []).append(t["proposal"]["test"])
    return own


def origins(items: Items, structure: dict[str, Any], decided: Book) -> dict[str, dict[str, Any]]:
    """Each item's origin with the evidence of the current tests."""
    dates, newest = org.file_dates(structure), org.code_newest(structure)
    checked = checked_by(items, decided)
    return {i["id"]: org.of_item(i, dates, newest, checked) for i in items}


def closed_by(gap: dict[str, Any], index: dict[str, dict[str, Any]], no: set[str]) -> list[str]:
    """The rejected items a gap is about, by their ids in the project ([] when the gap is still open)."""
    if gap["group"] != "gaps":
        return []
    return [(index[r]["proposal"].get("id") or index[r]["title"]) if r in index else r
            for r in gap["proposal"]["refs"] if r in no]


def counted(items: Items, acc: set[str]) -> int:
    """The tests the gate counts against a criterion: the trace and its criterion both accepted."""
    return sum(1 for i in items if i["group"] == "trace" and i["id"] in acc and i["proposal"]["criterion"] in acc)


def about_kept(items: Items, decided: Book) -> Items:
    """The items a suggested change may be about: none rejected, no gap closed by a rejection, no trace to a rejected
    criterion."""
    no = rejected(decided)
    index = {i["id"]: i for i in items}
    return [i for i in items if i["id"] not in no and not closed_by(i, index, no)
            and not (i["group"] == "trace" and i["proposal"]["criterion"] in no)]


def suggestion_files(s: dict[str, Any], items: Items) -> list[str]:
    """The files a suggested change edits when it is not a patch: the specs a stale-spec or restate suggestion is
    about."""
    index = {i["id"]: i for i in items}
    if s.get("kind") not in ("stale_spec", "testable"):
        return []
    return sorted({p for r in s.get("refs") or [] if (p := ((index.get(r) or {}).get("source") or {}).get("path"))})


FILTERS = ("project", "old", "convention", "deferred")


def row_tags(item: dict[str, Any]) -> list[str]:
    """The words a row of the view is filtered by (cockpit/static/alignment_triage.js rowTags)."""
    return (item.get("origin_tags", "") + (" deferred" if item.get("deferred") else "")).split()


def filters(items: Items) -> dict[str, int]:
    """How many rows each filter shows: every row with its tag, whatever its status."""
    rows = [row_tags(i) for i in items]
    return {"all": len(rows)} | {f: sum(1 for r in rows if f in r) for f in FILTERS}


def names(index: dict[str, dict[str, Any]], ids: list[str], n: int = 4) -> str:
    """Items by the id the project knows them by (a requirement's or criterion's), else their title."""
    said = [(index[i]["proposal"].get("id") or index[i]["title"][:48]) if i in index else i for i in ids]
    return ", ".join(said[:n]) + (f" and {len(said) - n} more" if len(said) > n else "")
