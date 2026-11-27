"""Where each alignment proposal comes from: the project's own files, or a convention of Rihmasto's (FR-ORG1,
docs/guides/alignment.md).

The owner (2026-11-26): "how much rihmasto is able / trying to ingest existing structures of project versus are the
tasks highlighted about enforcing rihmasto's own structure?" Rihmasto is a middle layer: it takes a project's
structure as given and enforces its own only where the owner chooses. So every proposal says which it is, by rule:

- **taken from your project**: a requirement, criterion, task, decision, API contract or test trace read from a
  file of the repository, with the file, the line and the file's last commit. A planning file (a spec, a task list)
  committed long before the code last moved is marked **may be an old plan**: the code went on without it.
- **Rihmasto's convention**: a gap, a criterion Rihmasto derived, a suggested change for the repository, an
  assessment's rule. Each names the rule it comes from ("every test traces to a requirement"), so a person can tell
  a gap in their project from a difference with how Rihmasto would keep it.

Nothing here reads the repository or writes anything: it reads the scan kept in the project.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

PROJECT, CONVENTION = "project", "convention"
LABEL = {PROJECT: "Taken from your project", CONVENTION: "Rihmasto's convention"}
OLD_DAYS = 21                     # a plan this many days older than the code's latest change may be an old plan
PLAN_GROUPS = ("requirements", "criteria", "tasks")      # what a planning file proposes; it can go out of date

# Rihmasto's conventions, by the gap kind (or the derived criterion, or the suggestion) that applies them.
RULES: dict[str, tuple[str, str]] = {
    "no_requirement": ("every_test_traces", "every test traces to a requirement"),
    "no_test": ("every_requirement_tested", "every requirement has a test that checks it"),
    "untestable": ("criteria_observable", "every criterion says something a test can observe"),
    "no_criteria": ("every_requirement_has_criteria", "every requirement has an acceptance criterion"),
    "derived": ("every_requirement_has_criteria", "every requirement has an acceptance criterion"),
    "stale_spec": ("specs_current", "a spec is kept as new as the code it describes"),
    "ci_no_tests": ("ci_runs_tests", "the CI runs the tests"),
    "rename_tests": ("test_names_carry_ids", "a test's name carries the criterion it checks"),
    "tasks_entry": ("every_requirement_tasked", "every requirement is served by a task"),
    "ci_tests": ("ci_runs_tests", "the CI runs the tests"),
    "write_tests": ("every_requirement_tested", "every requirement has a test that checks it"),
    "testable": ("criteria_observable", "every criterion says something a test can observe"),
    "assessment": ("assessment_rule", "an assessment rule of Rihmasto's"),
}


# The conventions that can also be a real risk in the project, not only Rihmasto's bookkeeping (FR-ORG2): deferring
# them unseen could hide a problem, so the triage names them and never defers them in bulk.
RISK: dict[str, str] = {
    "ci_no_tests": "your tests may never run before a change is merged",
    "untestable": "no test can tell whether it holds, so nobody can check it",
}
FOUND = "found"                   # an assessment finding that is a problem in the project's files (FR-ORG2)
LABEL[FOUND] = "Found in your project"
# Findings about something present in the project (a secret, failing tests, personal data), not a missing practice.
FOUND_KEYS = ("maintenance.baseline", "compliance.personal_data", "compliance.factory_evidence")


def day(stamp: int | None) -> str | None:
    return dt.datetime.fromtimestamp(stamp, dt.UTC).date().isoformat() if stamp else None


def code_newest(structure: dict[str, Any]) -> int | None:
    """The code's latest change: its newest code file, else its newest test file."""
    newest = (structure.get("code") or {}).get("newest")
    tests = [f.get("date") or 0 for f in (structure.get("tests") or {}).get("files", [])]
    return newest or max(tests, default=0) or None


def file_dates(structure: dict[str, Any]) -> dict[str, int]:
    """Each file's last commit, as the scan read it (older scans: from the specs, tests and decisions)."""
    out: dict[str, int] = {}
    out.update({s["path"]: s["date"] for s in structure.get("specs", []) if s.get("date")})
    out.update({f["path"]: f["date"] for f in (structure.get("tests") or {}).get("files", []) if f.get("date")})
    out.update({d["path"]: d["date_committed"] for d in structure.get("decisions", []) if d.get("date_committed")})
    out.update({k: v for k, v in (structure.get("dates") or {}).items() if v})
    return out


def convention(rule_key: str, about: str | None = None) -> dict[str, Any]:
    rid, said = RULES.get(rule_key, RULES["assessment"])
    risk = RISK.get(rule_key)
    return {"kind": CONVENTION, "label": LABEL[CONVENTION], "rule": rid, "rule_said": said, "path": about,
            "risk": risk, "said": f"Rihmasto's convention: {said}" + (f" (about {about})" if about else "")
            + (f"; it may be a real risk in your project: {risk}" if risk else "")}


def taken(path: str, line: int | None, stamp: int | None, newest: int | None, *, plan: bool,
          inferred: str | None = None, checked: list[str] | None = None) -> dict[str, Any]:
    """An item read from a file of the project: where, its last commit, and whether it may be an old plan. A plan
    that current tests check (``checked``, FR-ORG2) is not an old plan, however old its file."""
    behind = (newest - stamp) // 86400 if plan and stamp and newest and newest > stamp else 0
    old = behind >= OLD_DAYS and not checked
    where = f"{path}:{line}" if line else path
    said = f"Taken from your project: {where}" + (f", last committed {day(stamp)}" if stamp else
                                                    ", its commit date not known")
    if old:
        said += (f"; may be an old plan: {behind} days older than the code's latest change ({day(newest)})")
    elif behind >= OLD_DAYS:
        names = ", ".join((checked or [])[:3]) + (" and more" if len(checked or []) > 3 else "")
        said += (f"; its file is {behind} days older than the code's latest change, but current tests check it "
                 f"({names}): not an old plan")
    if inferred:
        said += f"; the link is Rihmasto's reading ({inferred})"
    return {"kind": PROJECT, "label": LABEL[PROJECT], "path": path, "line": line, "date": day(stamp),
            "old": old, "days_behind": behind, "code_date": day(newest), "inferred": inferred,
            "checked_by": list(checked or [])[:5], "said": said}


def of_item(item: dict[str, Any], dates: dict[str, int], newest: int | None,
            checked: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """An alignment item's origin, by rule; ``checked`` names the current tests that check each item
    (kernel/alignment_evidence.py)."""
    src = item.get("source") or {}
    group = item["group"]
    if group == "gaps":
        return convention(item.get("kind") or item["proposal"].get("kind"), src.get("path"))
    if group == "criteria" and item.get("derived"):
        return convention("derived", src.get("path"))
    path = src.get("path") or ""
    line = (src.get("lines") or [None])[0]
    inferred = item.get("basis") if group == "trace" else None
    return taken(path, line, dates.get(path), newest, plan=group in PLAN_GROUPS, inferred=inferred,
                 checked=(checked or {}).get(item["id"]))


def of_suggestion(s: dict[str, Any]) -> dict[str, Any]:
    return convention(s.get("kind") or "assessment", s.get("path"))


def of_finding(f: dict[str, Any]) -> dict[str, Any]:
    """An assessment finding's origin: a rule of Rihmasto's (named by its key), or the panel's opinion, about the
    project's own files."""
    by = "the panel's model, an opinion" if f.get("by") != "rule" or f.get("panel") else "a rule"
    said = f"{f.get('title') or f.get('key')} ({by}, key {f.get('key')})"
    files = finding_files(f)
    kind = FOUND if found_in_project(f) else CONVENTION
    return {"kind": kind, "label": LABEL[kind], "rule": f.get("key"), "rule_said": said,
            "files": files, "said": f"{LABEL[kind]}: {said}"
            + (f"; evidence from your project: {', '.join(files)}" if files else "")}


def found_in_project(f: dict[str, Any]) -> bool:
    """A finding about something present in the project's files (a committed secret, a scan's finding at a path,
    failing tests, personal data) or a critical one: a problem of the project, not a practice Rihmasto would add."""
    key = str(f.get("key") or "")
    return f.get("severity") == "critical" or key in FOUND_KEYS or bool(re.match(r"security\.[^.:\s]+:", key))


_EVIDENCE_FILE = re.compile(r"((?:[A-Za-z]:[\\/])?[^:]+):\d+")


def finding_files(f: dict[str, Any]) -> list[str]:
    """The project's files a finding's evidence names (a record's {file, line} or a short line's "file:line: ...",
    a Windows drive letter included)."""
    out = []
    for e in f.get("evidence") or []:
        if isinstance(e, dict):
            out.append(e.get("file"))
        elif m := _EVIDENCE_FILE.match(str(e)):
            out.append(m.group(1))
        elif ":" in str(e):
            out.append(str(e).split(":", 1)[0])
    return sorted({x for x in out if x})[:5]


def counts(items: list[dict[str, Any]]) -> dict[str, int]:
    """How many items are from the project (and of those, maybe an old plan) and how many Rihmasto's convention."""
    o = [i["origin"] for i in items]
    return {"project": sum(1 for x in o if x["kind"] == PROJECT),
            "convention": sum(1 for x in o if x["kind"] == CONVENTION), "old": sum(1 for x in o if x.get("old"))}


def tags(origin: dict[str, Any]) -> str:
    """The words a filter matches an item by: its origin, and old when it may be an old plan."""
    return origin["kind"] + (" old" if origin.get("old") else " current" if origin["kind"] == PROJECT else "")
