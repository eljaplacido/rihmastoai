"""Security only and evidence only for an attached repository (FR-MOD3): Rihmasto's own static scan into
the security gate, and a repository's existing releases recorded for its evidence packs.

`scan` runs the red team's static layer (kernel/redteam/static.py, D-0014) over a committed revision of
the attached repository, in a temporary clone, and hands its SARIF 2.1.0 to the security gate exactly
as `rihmasto security ingest` does (adapters/sarif.py): findings by fingerprint, so a person's risk
acceptance follows a finding when lines move. A scan that measured nothing writes no SARIF and is
recorded as not measured, never as a clean pass.

`record_releases` records the repository's own releases, its git tags: each tag, the commit it names and
its date as git states them (a claim of the repository, not something Rihmasto saw happen), signed by the
person who recorded it. With ``check`` the kernel also runs, at each release's commit, the repository's
test suite and, with a contract, the trace of every visible criterion to a test that ran; that is what
the kernel itself saw; while access is enforced those tests run only through IT's isolation runner
(`attach.outside_code`), and without one ``check`` is refused. The records go into `repo_releases.json` and the ledger, and `rihmasto evidence`
puts them in the evidence pack (`repository-releases.json`).
"""

from __future__ import annotations

import contextlib
from typing import Any

from kernel.attach import AttachRefused, check_signer, checkout, commit_of, git, outside_code, repository
from kernel.store import Project

RELEASES_FILE = "repo_releases.json"


def scan(project: Project, *, person: str, persona: str, revision: str | None = None,
         exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    """The static scan of a committed revision (default: the repository's HEAD), into the security gate."""
    from adapters.sarif import ingest
    from kernel.redteam.report import NothingMeasured, write_sarif
    from kernel.redteam.static import scan as static_scan
    from kernel.security import summary

    check_signer(person, persona)
    sha = commit_of(project, revision)
    with checkout(project, sha) as work:
        report = static_scan([work], root=work, exclude=exclude)
        target = project.path("security", "attached", f"static-{sha[:12]}.sarif")
        try:
            write_sarif(target, report)
        except NothingMeasured as exc:
            project.log("security_not_measured", {"revision": sha, "why": str(exc), "person": person,
                                                  "persona": persona, "tool": "static"})
            return {"project": project.pid, "revision": sha, "verdict": "not measured", "why": str(exc),
                    "gate": summary(project)}
    scanned = ingest(project, target, person=person, persona=persona)
    project.log("repo_scanned", {"revision": sha, "scan": scanned["scan"], "verdict": report.verdict,
                                 "counts": scanned["counts"], "person": person, "persona": persona})
    return {"project": project.pid, "revision": sha, "scan": scanned["scan"], "verdict": report.verdict,
            "counts": scanned["counts"], "coverage": [c.to_dict() | {"verdict": c.verdict(report.findings)}
                                                      for c in report.coverage],
            "gate": summary(project)}


# -- a repository's own releases ------------------------------------------------------------------------

def tags(project: Project) -> list[dict[str, str]]:
    """The repository's tags with the commit each names and its date, as git states them."""
    out = git(repository(project), "for-each-ref", "--sort=creatordate", "refs/tags",
              "--format=%(refname:short)%09%(objectname)%09%(*objectname)%09%(creatordate:iso-strict)")
    rows = []
    for line in out.splitlines():
        name, obj, peeled, date = (line.split("\t") + ["", "", "", ""])[:4]
        rows.append({"tag": name, "commit": peeled or obj, "date": date})
    return rows


def _checks(project: Project, sha: str) -> dict[str, Any]:
    """What the kernel saw at a release's commit: the suite, and the trace of the contract's criteria."""
    from kernel.gate import run_suite, signal_tests, signal_trace

    contract = project.read("contract.json")
    with checkout(project, sha) as work:
        run = run_suite(work)
        tests = signal_tests(work, run=run)
        out: dict[str, Any] = {"tests": {"verdict": tests.verdict, "detail": tests.detail}}
        if contract:
            traces = [signal_trace(work, contract, t["id"], run=run) for t in contract["tasks"]]
            unnamed = sorted({c for s in traces for c in s.native.get("unnamed", [])})
            unrun = sorted({c for s in traces for c in s.native.get("not_run", {})})
            verdict = "failed" if unnamed else "not measured" if unrun else "passed"
            out["trace"] = {"verdict": verdict, "contract": contract.get("revision"), "unnamed": unnamed,
                            "not_run": unrun}
        else:
            out["trace"] = {"verdict": "not measured", "detail": "no contract: no criterion to trace"}
    return out


def _wanted(project: Project, only: list[str] | None) -> list[dict[str, str]]:
    found = tags(project)
    if not only:
        return found
    missing = sorted(set(only) - {t["tag"] for t in found})
    if missing:
        raise AttachRefused(f"no tag {', '.join(missing)} in {repository(project)}")
    return [t for t in found if t["tag"] in set(only)]


def _row(project: Project, tag: dict[str, str], before: dict[str, Any] | None, *, person: str, persona: str,
         check: bool) -> dict[str, Any]:
    """One release as recorded: git's claims marked as such, who recorded it, and what the kernel saw."""
    row: dict[str, Any] = {**tag, "recorded_by": person, "persona": persona,
                           "recorded_at": project.factory.clock.stamp(), "claimed_by_git": ["commit", "date"]}
    if before and before["commit"] != tag["commit"]:
        row["moved_from"] = before["commit"]
    if check:
        row["checks"] = _checks(project, commit_of(project, tag["commit"]))
    return row


def record_releases(project: Project, *, person: str, persona: str, only: list[str] | None = None,
                    check: bool = False) -> dict[str, Any]:
    """Record the repository's releases (its tags, or the ``only`` ones). A tag already recorded at the
    same commit is kept as it is, unless ``check`` adds the kernel's checks it did not have; a tag that
    now names another commit is recorded again, saying so."""
    check_signer(person, persona)
    with outside_code(project) if check else contextlib.nullcontext():   # the tests run isolated, or not at all
        return _record(project, person=person, persona=persona, only=only, check=check)


def _record(project: Project, *, person: str, persona: str, only: list[str] | None, check: bool) -> dict[str, Any]:
    kept: list[dict[str, Any]] = list(project.read(RELEASES_FILE) or [])
    recorded: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for t in _wanted(project, only):
        before = next((r for r in kept if r["tag"] == t["tag"]), None)
        if before and before["commit"] == t["commit"] and (not check or before.get("checks")):
            unchanged.append(t["tag"])
            continue
        row = _row(project, t, before, person=person, persona=persona, check=check)
        kept = [r for r in kept if r["tag"] != t["tag"]] + [row]
        checks: dict[str, Any] = row.get("checks") or {}
        project.log("repo_release_recorded", {k: row.get(k) for k in ("tag", "commit", "date", "moved_from")}
                    | {"checks": {k: v["verdict"] for k, v in checks.items()}, "person": person, "persona": persona})
        recorded.append(row)
    project.write(RELEASES_FILE, kept)
    return {"project": project.pid, "recorded": recorded, "unchanged": unchanged, "releases": len(kept)}


def evidence_files(project: Project) -> dict[str, Any]:
    """The evidence pack's file for a repository's releases (kernel/evidence_pack.py), when there are any."""
    releases = project.read(RELEASES_FILE)
    return {"repository-releases.json": releases} if releases else {}
