"""What an assessment of an adopted project measures against, and what it says first (FR-ASP1).

The owner (2026-11-26): "when I jump into [an adopted project] its not clear what should I do". An adopted project's
own sources are often not where the factory first looks: each Python package keeps its own test root, its real
tests run by a tool of its own on another machine, its plans live in documents nobody has touched for weeks.
By rule, with no model:

- **Test roots.** `python_roots` finds each package's own test root (a folder with its own pytest or package
  configuration and tests under it). kernel/adopt.py runs pytest once per root, never only from the repository's
  root, when the root itself sets no pytest configuration.
- **The project's own runner, mapped.** A person maps the command the project runs its tests with and the results
  file it writes (JUnit XML, or JSON counts), signed (`assessments/runner.json`, `assessment_runner_mapped` in the
  ledger). The check `maintenance.tests_measured` reads that file at the assessed revision as the test run. Until
  then a project whose tests another tool runs reads "not measured by Rihmasto yet: map its runner", with where
  the project states its command, never "0 %" or "could not run".
- **Plans from documents, dated.** Each requirement and task imported from a document (accepted into the contract
  or still waiting in Alignment) carries the document's path and its last commit date at the assessed revision;
  one whose document is older than the code by `STALE_DAYS` or more is flagged before it is accepted: "this plan is
  from <date>; the code moved on since".
- **The two lines first.** `headline` says what is worth acting on now and what is probably noise, and why, from
  the latest assessment as people judged it (kernel/assess_precise.py).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shlex
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Any

from kernel import assess_sources
from kernel.assess_repo import Repo, fact, result

against_roots = assess_sources.against_roots      # only the test roots a run starts in (FR-ASP2)

RUNNER = "assessments/runner.json"
RUNNER_SETTERS = ("developer", "it", "operations", "product_owner")
STALE_DAYS = 14
MAX_PLANS = 60
MAX_RESULTS = 4 * 1024 * 1024
PY_CONFIG = ("pyproject.toml", "setup.cfg", "setup.py", "pytest.ini", "tox.ini")
ROOT_PYTEST = (("pytest.ini", ""), ("pyproject.toml", "[tool.pytest"), ("setup.cfg", "[tool:pytest]"),
               ("tox.ini", "[pytest]"), ("conftest.py", ""))
_PY_TEST = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
_SHELL = re.compile(r"[;&|<>`$\n]")      # kept, never run: still no shell syntax in a record people copy
_DOCS = (":(exclude)*.md", ":(exclude)*.rst", ":(exclude)*.txt", ":(exclude)*.adoc", ":(exclude)docs")
NOT_YET = "not measured by Rihmasto yet: map its runner"


class RunnerRefused(ValueError):
    """A runner map the kernel will not keep: not a person, shell syntax, a results path outside the repository."""


# -- test roots ---------------------------------------------------------------------------------------

def _root_sets_pytest(files: list[str], read: Any) -> bool:
    names = set(files)
    return any(name in names and (not marker or marker in read(name)) for name, marker in ROOT_PYTEST)


def python_roots(files: list[str], read: Any) -> list[str]:
    """Each folder pytest is started in: the repository's root ("") when it sets pytest up itself or holds the only
    tests; else each package folder with its own configuration and tests under it, and the root for tests outside
    every such folder. ``read(rel)`` gives a file's text."""
    tests = [f for f in files if _PY_TEST.search(f)]
    if not tests or _root_sets_pytest(files, read):
        return [""]
    roots = _package_roots(files, tests)
    if not roots:
        return [""]
    outside = [t for t in tests if not _under(t, roots)]
    return ([""] if outside else []) + roots


def _under(rel: str, roots: list[str]) -> bool:
    return any(rel.startswith(r + "/") for r in roots)


def _package_roots(files: list[str], tests: list[str]) -> list[str]:
    """The outermost folders that hold a package's own configuration and tests under it."""
    found = sorted({str(PurePosixPath(f).parent) for f in files if "/" in f and PurePosixPath(f).name in PY_CONFIG})
    found = [r for r in found if _under_any(tests, r)]
    return [r for r in found if not any(r != o and r.startswith(o + "/") for o in found)]


def _under_any(tests: list[str], root: str) -> bool:
    return any(t.startswith(root + "/") for t in tests)


# -- the runner a person maps ---------------------------------------------------------------------------

def runner(project: Any) -> dict[str, Any] | None:
    got = project.read(RUNNER)
    return got if isinstance(got, dict) and got.get("command") else None


def _clean_path(path: str) -> str:
    rel = str(path or "").strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    if rel and (rel.startswith("/") or ".." in rel.split("/") or ":" in rel or len(rel) > 300):
        raise RunnerRefused("the results file is a path inside the repository, such as build/test-results.xml")
    return rel


def map_runner(project: Any, *, command: str, results: str | None, note: str | None, person: str,
               persona: str) -> dict[str, Any]:
    """Keep the command the project runs its own tests with, and where it writes its results, signed."""
    from kernel.assess import _check_asker

    _check_asker(person, persona)
    if persona not in RUNNER_SETTERS:
        raise RunnerRefused(f"a runner is mapped by a {', '.join(RUNNER_SETTERS)}, not {persona}")
    words = " ".join(str(command or "").split())
    if not 2 <= len(words) <= 300 or _SHELL.search(words):
        raise RunnerRefused("the command is the project's own, in plain words (no ;, &&, |, $ or redirection)")
    try:
        shlex.split(words)
    except ValueError as exc:
        raise RunnerRefused(f"the command could not be read: {exc}") from None
    kept = {"command": words, "results": _clean_path(results or ""),
            "note": " ".join(str(note or "").split())[:300], "person": person, "persona": persona,
            "at": project.factory.clock.stamp(),
            "runs": "where the project runs it (its own machine or pipeline): Rihmasto reads its results, "
                    "never runs it"}
    project.write(RUNNER, kept)
    project.log("assessment_runner_mapped", {k: kept[k] for k in ("command", "results", "note", "person", "persona")})
    return kept


def _junit(text: str) -> dict[str, int] | None:
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):      # a results file declares no entities
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite") if root.tag == "testsuites" else []
    if not suites:
        return None
    if root.tag == "testsuites" and root.get("tests"):
        suites = [root]
    n = lambda key: sum(int(s.get(key) or 0) for s in suites)    # noqa: E731
    total, failed, errors, skipped = n("tests"), n("failures"), n("errors"), n("skipped")
    return {"passed": max(0, total - failed - errors - skipped), "failed": failed, "errors": errors,
            "skipped": skipped}


def _json_counts(text: str) -> dict[str, int] | None:
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if isinstance(doc, dict) and any(isinstance(doc.get(k), int) for k in ("passed", "failed")):
        return {k: int(doc.get(k) or 0) for k in ("passed", "failed", "errors", "skipped")}
    rows = doc.get("tests") if isinstance(doc, dict) else doc
    if not isinstance(rows, list) or not rows:
        return None
    out = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for r in rows:
        key = _state(r)
        if key in out:
            out[key] += 1
    return out if sum(out.values()) else None


_STATES = {"pass": "passed", "ok": "passed", "fail": "failed", "error": "errors", "skip": "skipped"}


def _state(row: Any) -> str:
    """One test's state in a JSON list: its status, outcome or passed flag."""
    if not isinstance(row, dict):
        return ""
    if isinstance(row.get("passed"), bool):
        return "passed" if row["passed"] else "failed"
    state = str(row.get("status") or row.get("outcome") or "").lower()
    return _STATES.get(state, state)


def read_results(text: str) -> dict[str, int] | None:
    """Counts from a results file: JUnit XML, JSON counts, or a JSON list of tests with their status."""
    text = text[:MAX_RESULTS]
    return _junit(text) if text.lstrip().startswith("<") else _json_counts(text)


def _stated(repo: Repo) -> list[dict[str, Any]]:
    stated = ((repo.records.get("inventory") or {}).get("stated_tests") or {}).get("not_used") or []
    return [s for s in stated if "not a test runner the kernel runs" in str(s.get("not_run", ""))]


def _care(title: str, verdict: str, **kw: Any) -> dict[str, Any]:
    return result("maintenance.tests_measured", "maintenance", title, verdict, **kw)


def tests_measured(repo: Repo) -> dict[str, Any]:
    """Whether Rihmasto measures the project's own tests, and against what: the mapped runner's results at this
    revision, the kernel's own run at adoption, or not yet, with what to do."""
    roots = (repo.records.get("inventory") or {}).get("test_roots") or []
    where = [fact(f"each package's own test root: {', '.join(r or '(the root)' for r in roots)}")] if roots else []
    mapped = repo.records.get("runner")
    return _mapped(repo, mapped, where) if mapped else _unmapped(repo, where)


TITLE = "Rihmasto measures this project's own tests"


def _mapped(repo: Repo, mapped: dict[str, Any], where: list[dict[str, Any]]) -> dict[str, Any]:
    """The mapped runner's results file, read at the assessed revision as the project's test run."""
    said = fact(f"mapped by {mapped.get('person')}: `{mapped['command']}`, results in "
                f"{mapped.get('results') or '(no results file named)'}")
    rel = mapped.get("results") or ""
    got = (repo.text(rel), {}) if rel in repo.files else assess_sources.results_upstream(repo, rel)
    if got is None:              # not in main, nor in the synced upstream's head (FR-ASP2)
        return _care(TITLE, "not measured", evidence=[said, *where],
                     reason=assess_sources.missing_said(repo, rel, mapped["command"]))
    text, read_at = got
    if read_at:                  # read from the upstream's head, which a sync never merges into main
        said = fact(said["fact"] + "; " + read_at["fact"])
    counts = read_results(text)
    if counts is None:
        return _care(TITLE, "not measured", evidence=[said, {"file": rel, "fact": "unreadable"}],
                     reason=f"{rel} is not JUnit XML or JSON counts Rihmasto reads")
    line = {"file": rel, "fact": ", ".join(f"{v} {k}" for k, v in counts.items() if v) or "no test"}
    failing = counts["failed"] + counts["errors"]
    if failing:
        return _care(TITLE, "failed", severity="medium", evidence=[said, line],
                     summary=f"the project's own runner reports {failing} failing",
                     suggestion=f"Open {rel} and fix or record the failing tests before the system is changed.")
    if not counts["passed"]:
        return _care(TITLE, "not measured", evidence=[said, line], reason=f"{rel} records no test that passed")
    return _care(TITLE, "passed", evidence=[said, line], summary=f"{counts['passed']} passed, read from {rel}")


def _unmapped(repo: Repo, where: list[dict[str, Any]]) -> dict[str, Any]:
    """No runner mapped: the stated command to map, the kernel's own passing run, or not yet, with what to do."""
    stated = _stated(repo)
    if stated:
        places = [{"file": s["where"].split(" (line")[0].removeprefix("stated in "),
                   "fact": f"`{s['command']}`: {s['not_run']}"} for s in stated[:4]]
        return _care(TITLE, "not measured", evidence=places + where,
                     reason=f"{NOT_YET}. The project states its own test command, which Rihmasto does not run: map "
                            "it, and the results file it writes, so its results count as this project's test runs")
    base = repo.records.get("baseline") or {}
    if base.get("verdict") == "passed" and base.get("revision") == repo.revision:
        return _care(TITLE, "passed", evidence=where or [fact("run by the kernel at adoption")],
                     summary="run by the kernel at this revision (the characterisation baseline)")
    found = (repo.records.get("inventory") or {}).get("tests") or []
    why = assess_sources.kernel_run_said(base, repo.revision, bool(found))    # as it was (FR-ASP2)
    return _care(TITLE, "not measured", evidence=where or [fact(why)],
                 reason=f"{NOT_YET}: {why}. If another tool runs this project's tests (on another machine, in its "
                        "own pipeline), map that runner and its results file")


# -- plans imported from documents -------------------------------------------------------------------

def _date(iso: str | None) -> dt.date | None:
    try:
        return dt.datetime.fromisoformat(str(iso)).date() if iso else None
    except ValueError:
        return None


def _code_after(repo: Repo, since: str) -> tuple[int, str | None]:
    """The commits that changed code (not documents) after ``since``, and the last one's date."""
    from kernel.adopt import KERNEL_HELD, _git_read

    spec = (".", *_DOCS, *(f":(exclude){k}" for k in KERNEL_HELD))      # nor the kernel's own surface on main
    try:
        last = _git_read(repo.bare, "log", "-1", "--format=%cI", repo.revision, "--", *spec) or None
        count = _git_read(repo.bare, "rev-list", "--count", f"--since={since}", repo.revision, "--", *spec)
        return int(count or 0), last
    except (RuntimeError, ValueError):
        return 0, None


def _imported(project: Any) -> list[dict[str, Any]]:
    """Requirements and tasks taken from the repository's documents: accepted (the contract, the alignment's
    decisions) or still open in Alignment."""
    out = _accepted(project)
    taken = {o["id"] for o in out}
    decided = project.read("alignment/decisions.json", {}) or {}
    items = ((project.read("alignment/scan.json") or {}).get("proposal") or {}).get("items") or []
    for i in items:
        row = _open_item(i, decided.get(i.get("id")) or {})
        if row and not (row["kind"] == "requirement" and row["id"] in taken):
            out.append(row)
    return out[:MAX_PLANS]


def _accepted(project: Any) -> list[dict[str, Any]]:
    """The contract's requirements imported from a document."""
    reqs = (project.read("contract.json") or {}).get("requirements") or []
    return [{"kind": "requirement", "id": r["id"], "title": r.get("statement", "")[:160],
             "path": r["imported"]["path"], "status": "accepted"}
            for r in reqs if (r.get("imported") or {}).get("path")]


def _open_item(i: dict[str, Any], d: dict[str, Any]) -> dict[str, Any] | None:
    """An alignment item from a document (a requirement or a task), unless it was rejected."""
    if i.get("group") not in ("requirements", "tasks") or not (i.get("source") or {}).get("path"):
        return None
    status = {"accept": "accepted", "reject": "rejected"}.get(str(d.get("verdict")), "open")
    if status == "rejected":
        return None
    return {"kind": "requirement" if i["group"] == "requirements" else "task",
            "id": (i.get("proposal") or {}).get("id") or i["id"], "item": i["id"],
            "title": str(i.get("title", ""))[:160], "path": i["source"]["path"], "status": status}


def _dated(repo: Repo, path: str) -> dict[str, Any]:
    """A document's last commit date, the code's commits after it, and whether the plan is old."""
    try:
        last = repo.last_change(path)
    except RuntimeError:
        last = None
    commits, code = _code_after(repo, last) if last else (0, None)
    day, code_day = _date(last), _date(code)
    stale = bool(day and code_day and commits and (code_day - day).days >= STALE_DAYS)
    said = None
    if stale and day and code_day:
        said = (f"this plan is from {day.isoformat()}; the code moved on since ({commits} commit"
                f"{'s' if commits != 1 else ''}, the last on {code_day.isoformat()})")
    return {"committed": last, "code_last": code, "code_commits_since": commits, "stale": stale, "said": said}


def plans(project: Any, repo: Repo) -> dict[str, Any]:
    """Each imported requirement and task with its document's path and last commit date at the assessed
    revision, and whether the code moved on since by ``STALE_DAYS`` or more (flagged before it is accepted)."""
    items = _imported(project)
    dated = {path: _dated(repo, path) for path in sorted({i["path"] for i in items})}
    rows = [i | dated[i["path"]] for i in items]
    return {"items": rows, "stale_days": STALE_DAYS, "stale": sum(1 for r in rows if r.get("stale")),
            "stale_open": sum(1 for r in rows if r.get("stale") and r["status"] == "open"),
            "documents": [{"path": p, **d} for p, d in dated.items()]}


def stale_items(project: Any) -> dict[str, str]:
    """Alignment's item id -> the stale line, from the latest assessment: shown on an item before it is accepted."""
    from kernel.assess import history, load

    if not history(project):
        return {}
    try:
        got = (load(project).get("precise") or {}).get("plans") or {}
    except LookupError:
        return {}
    return {r["item"]: r["said"] for r in got.get("items") or [] if r.get("item") and r.get("stale")}


def extra(project: Any, repo: Repo) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The checks this module adds to an assessment, and what it keeps beside them in the record."""
    from kernel.assess_context import project_kind

    repo.records["runner"] = runner(project)
    repo.records["upstream"] = assess_sources.upstream(project)       # where a mapped runner's results wait (FR-ASP2)
    inv = repo.records.setdefault("inventory", {})
    roots = against_roots(inv.get("tests") or [], python_roots(repo.files, repo.text))   # only roots a run uses
    inv["test_roots"] = roots
    check = tests_measured(repo)
    return [check, *assess_sources.issue_checks(repo)], {
        "test_roots": roots, "runner": repo.records["runner"], "plans": plans(project, repo),
        "measured_against": against(repo, check), "kind": project_kind(project, repo.files, inv)}


def against(repo: Repo, check: dict[str, Any]) -> str:
    """What the test counts of this assessment are measured against, in one line."""
    inv = repo.records.get("inventory") or {}
    found = ", ".join(dict.fromkeys(t["runner"] for t in inv.get("tests") or [])) or "no runner found by rule"
    roots = inv.get("test_roots") or []
    return (f"tests: {found}" + (f", in {len(roots)} test roots of their own" if roots else "")
            + f"; the project's own runner: {'mapped' if repo.records.get('runner') else 'not mapped'}"
            + f" ({check['verdict']})")


__all__ = ["NOT_YET", "RUNNER", "RUNNER_SETTERS", "STALE_DAYS", "RunnerRefused", "against", "against_roots", "extra",
           "map_runner",
           "plans", "python_roots", "read_results", "runner", "stale_items", "tests_measured"]
