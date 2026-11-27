"""Where an assessment of an adopted project reads its tests and the team's own issues from (FR-ASP2).

An independent check of FR-ASP1 found: a mapped runner could never be measured on an adopted project, since the
assessment reads the kernel's main and a sync never moves it, and nothing said how to get the results read; the
Tests card named test roots that no run used; the reason for an unmeasured suite said "the kernel's run did not pass
at this revision" when the kernel ran once, at adoption, and measured nothing; and the team's own issue log was
never read. By rule, no model, nothing run:

- **The runner's results from the synced upstream** (`results_upstream`): when the results file is not at the
  assessed revision, the upstream's head as last synced is read for it (never fetched here), and the evidence says
  so, with the drift card that brings it into main. When it is nowhere, the reason says what to do: commit it
  where the runner runs, Sync the upstream, assess again.
- **The kernel's own run, said as it was** (`kernel_run_said`): at adoption, at which revision, with what verdict.
- **Roots that ran** (`against_roots`): only the test roots a detected run starts in are said to be run.
- **The team's issue log** (`issue_checks`): each open issue of a JSON-lines issue log (`issues.jsonl`,
  `findings.jsonl`, `bugs.jsonl`) is a finding of one rule, `maintenance.issue_log`, with its severity and line;
  a closed one is none.
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from kernel.assess_repo import Repo, at, result

ISSUE_LOG = re.compile(r"(?i)(^|/)(issues?|findings|bugs|defects|problems)\.jsonl$")
CLOSED = ("closed", "done", "resolved", "fixed", "wontfix", "won't fix", "invalid", "duplicate", "rejected", "obsolete")
SEVERITY = {"critical": "critical", "blocker": "critical", "p0": "critical", "high": "high", "major": "high",
            "p1": "high", "medium": "medium", "moderate": "medium", "normal": "medium", "p2": "medium", "low": "low",
            "minor": "low", "trivial": "low", "p3": "low", "info": "info"}
MAX_ISSUES = 60
MAX_LOG = 2 * 1024 * 1024
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


# -- the runner's results ------------------------------------------------------------------------------

def upstream(project: Any) -> dict[str, Any] | None:
    """The upstream's head as last synced, and the drift card that sync opened, for an adopted project."""
    adopted = project.read("adopted.json") or {}
    head = adopted.get("last_upstream")
    return {"head": head, "card": (adopted.get("last_sync") or {}).get("card")} if head else None


def results_upstream(repo: Repo, rel: str) -> tuple[str, dict[str, Any]] | None:
    """The results file from the synced upstream's head when the assessed revision does not hold it: (text,
    evidence that says where it was read and what brings it into main), or None."""
    from kernel.adopt import _git_read

    up = repo.records.get("upstream") or {}
    head = up.get("head")
    if not head or head == repo.revision or not rel:
        return None
    try:
        if int(_git_read(repo.bare, "cat-file", "-s", f"{head}:{rel}") or 0) > MAX_LOG:
            return None
        text = _git_read(repo.bare, "show", f"{head}:{rel}")
    except (RuntimeError, ValueError):
        return None
    card = up.get("card")
    said = (f"read from the upstream's head {head[:12]} as last synced: {rel} is not in main yet"
            + (f"; merging {card} keeps it there" if card else ""))
    return text, {"file": rel, "fact": said}


def missing_said(repo: Repo, rel: str, command: str) -> str:
    """What to do when the mapped runner's results file is nowhere Rihmasto reads."""
    up = repo.records.get("upstream") or {}
    where = f"revision {repo.revision[:12]}" + (f" nor in the upstream's head {up['head'][:12]} as last synced"
                                                if up.get("head") and up["head"] != repo.revision else "")
    return (f"not measured by Rihmasto yet: the mapped runner's results ({rel or 'no file named'}) are not in {where}. "
            f"Run `{command}` where it runs and commit its results file to the repository, then Sync the upstream "
            "(the project's Overview) and assess again: Rihmasto reads it from the upstream's head"
            + (f"; merging {up['card']} keeps it in main" if up.get("card") else ""))


# -- the kernel's own run ------------------------------------------------------------------------------

def kernel_run_said(base: dict[str, Any], revision: str, found: bool) -> str:
    """The kernel's own run as it was: at adoption, at which revision, with what verdict and why."""
    if not found:
        return "no test command was found by rule"
    if not base:
        return "the kernel has not run the tests yet"
    rev = str(base.get("revision") or "")
    when = f"once, at adoption (revision {rev[:12]})" if rev else "once, at adoption"
    other = rev and rev != revision
    verdict = base.get("verdict") or "not measured"
    why = str(base.get("reason") or base.get("summary") or "").removeprefix("not measured: ")
    said = f"the kernel ran the tests {when}" + (", not at this revision" if other else "")
    return said + f", and it {'measured nothing' if verdict == 'not measured' else verdict}" + (f" ({why})" if why
                                                                                                else "")


def against_roots(tests: list[dict[str, Any]], roots: list[str]) -> list[str]:
    """The test roots a detected run starts in: only those are said to be run on their own."""
    used = {t.get("cwd") for t in tests if t.get("cwd")}
    return [r for r in roots if r and r in used]


def kernel_runs(project: Any) -> str | None:
    """How the kernel runs the adopted project's tests, from its inventory: for Alignment's line."""
    tests = (project.read("inventory.json") or {}).get("tests") or []
    if not tests:
        return None
    runners = ", ".join(dict.fromkeys(t["runner"] for t in tests if t.get("runner")))
    roots = [t["cwd"] for t in tests if t.get("cwd")]
    return f"the kernel runs them with {runners}" + (f" in {len(roots)} test roots of their own" if roots
                                                    else " from the repository's root")


# -- the team's own issue log ---------------------------------------------------------------------------

def _first(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    """The first of ``keys`` a row has a value for, as text."""
    return next((str(row[k]) for k in keys if row.get(k) not in (None, "")), "")


def _issue(row: dict[str, Any], n: int) -> dict[str, Any] | None:
    status = _first(row, ("status", "state")).strip().lower()
    if status in CLOSED or True in (row.get("closed"), row.get("resolved")):
        return None
    title = _first(row, ("title", "summary", "name", "text", "description"))
    if not title.strip():
        return None
    ref = _first(row, ("id", "key", "ref", "number")) or f"line-{n}"
    level = _first(row, ("severity", "priority", "level")).strip().lower()
    return {"id": _SAFE_ID.sub("-", ref)[:40].strip("-") or f"line-{n}", "title": " ".join(title.split()),
            "severity": SEVERITY.get(level, "medium"), "status": status or "open", "line": n}


def issues_in(text: str) -> list[dict[str, Any]]:
    """The open issues of a JSON-lines log, each with its id, title, severity and line."""
    out, seen = [], set()
    for n, line in enumerate(text[:MAX_LOG].splitlines(), 1):
        try:
            row = json.loads(line) if line.strip() else None
        except (ValueError, RecursionError):
            continue
        got = _issue(row, n) if isinstance(row, dict) else None
        if got and got["id"] not in seen:
            seen.add(got["id"])
            out.append(got)
    return out


def issue_checks(repo: Repo) -> list[dict[str, Any]]:
    """Each open issue of the team's own logs as a finding of maintenance.issue_log; a log with none open passes."""
    out: list[dict[str, Any]] = []
    logs = sorted(f for f in repo.files if ISSUE_LOG.search(f) and not f.startswith(("vendor/", "node_modules/")))
    for rel in logs:
        found = issues_in(repo.text(rel))
        for i in found[:MAX_ISSUES - len(out)]:
            ev = at(rel, i["line"], i["title"])
            out.append(result(f"maintenance.issue_log:{i['id']}", "maintenance", "An open issue of the team's own log",
                              "failed", severity=i["severity"], summary=f"{i['id']}: {ev['text']}", evidence=[ev],
                              suggestion=f"Fix it, or close it in {rel} once it is done; file it as a change to have "
                                         "it built."))
    if logs and not out:
        out.append(result("maintenance.issue_log", "maintenance", "The team's own issue log has no open issue",
                          "passed", summary="no open issue in " + ", ".join(PurePosixPath(r).as_posix()
                                                                            for r in logs[:3])))
    return out


__all__ = ["ISSUE_LOG", "against_roots", "issue_checks", "issues_in", "kernel_run_said", "kernel_runs",
           "missing_said", "results_upstream", "upstream"]
