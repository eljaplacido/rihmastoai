"""Brownfield assessment: what an existing system should fix, from every perspective (docs/brownfield.md).

    rihmasto assess <pid> --person Aino --persona developer [--with-model] [--ref main]
    rihmasto assessment show <pid> [--version AS-2] | list <pid> | compare <pid> [--from AS-1] [--to AS-2]
    rihmasto assessment change <pid> F-2 P-1 --person Aino --persona developer [--as new_requirement]

An assessment reads one revision of the project's own mirror (`repo.git`: `main`, what the factory
holds, unless another ref is named) from git's objects, never a checkout (kernel/assess_repo.py), and
judges it from five perspectives:

- **CI/CD governance** (kernel/assess_delivery.py): a pipeline, the tests in it, pull-request triggers,
  pinned actions, token permissions, a release process. Required checks and a protected main are set
  in the hosting service, not the files: "not measured".
- **Maintenance** (kernel/assess_delivery.py): the test suite and the adoption's characterisation
  baseline, coverage configured, dependencies pinned and when they last moved, an update bot, the
  README, code owners.
- **Security** (kernel/assess_trust.py): the red team's static layer over the revision (code, secrets,
  Dockerfiles, Actions) and what it read, a SECURITY.md, environment files kept out of git.
- **Compliance** (kernel/assess_trust.py): a licence, a NOTICE for vendored code, personal data and
  whether its handling is written down, an audit trail, what the factory's own records could attest.
- **Architecture and operations** (kernel/assess_ops.py): entry points, a health endpoint,
  configuration from the environment, logging, the container and its .dockerignore.

- **Rules first, and they decide.** Each check is passed, failed, not applicable or not measured, and
  names its evidence: a file and a line (masked as the red team masks it) or a measured fact. A failed
  check is a finding, with a severity, its perspective and a suggested change. What the files cannot show
  is "not measured", with the reason, never passed.
- **The panel proposes.** With a model, each perspective of the intake panel reads the inventory and the
  rules' results and proposes further findings (kernel/assess_panel.py). They stay apart as
  `model_proposed`: never a fact, never counted with the rules' findings, and what each rests on is
  checked against the record.
- **A record.** Each assessment is a version, `AS-<n>` in `assessments/`, with the red team's SARIF
  beside it. Its sha256 is in the ledger (`assessment_recorded`) with the trace every path writes
  (D-0017): who asked, what decided (the rules) and what was delegated to whom (the panel's model, by the
  person who asked), what was assumed (each check that could not know), and what proves it (the
  revision, and the record's and the SARIF's sha256). A record is intact only while it hashes to the
  sha256 the ledger's hash chain holds: the index beside it is a plain file and is not trusted alone.
- **Comparable over time.** A check keeps its key from version to version: each version says what is
  new, resolved, still open or no longer measured since the one before, and `compare` takes any two.
- **Into the change loop.** A person turns chosen findings into change cards (origin "assessment"),
  triaged by rule like any change, as a new requirement unless the person says otherwise, so a business
  decision comes first and the system is developed further through the factory. A finding whose card is
  still open is not filed twice.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel.adopt import VENDORED, _git_read, detect_tests, dockerfiles, endpoints, is_adopted, languages, readme
from kernel.assess_delivery import CICD, MAINTENANCE
from kernel.assess_ops import ARCHITECTURE
from kernel.assess_panel import propose
from kernel.assess_repo import PERSPECTIVES, SEVERITIES, Repo, result, snapshot
from kernel.assess_trust import COMPLIANCE, SECURITY, redteam, scan_coverage
from kernel.people import PERSONAS, is_person
from kernel.store import read_json, updating_json, write_json, write_text

SCHEMA = "rihmasto.assessment/1"
FOLDER = "assessments"
Rule = Callable[[Repo], dict[str, Any]]
RULES: tuple[tuple[str, Rule], ...] = (
    *(("cicd", r) for r in CICD), *(("maintenance", r) for r in MAINTENANCE), *(("security", r) for r in SECURITY),
    *(("compliance", r) for r in COMPLIANCE), *(("architecture", r) for r in ARCHITECTURE))
VERDICTS = ("failed", "not measured", "passed", "not applicable")
DECIDED_BY = "rule: kernel/assess.py and the red team's static layer, no model"
CLASS_DEFAULT = "new_requirement"
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,200}")
_ORDER = {p: i for i, p in enumerate(PERSPECTIVES)} | {v: i for i, v in enumerate(VERDICTS)} \
    | {s: i for i, s in enumerate(SEVERITIES)}


class AssessmentRefused(ValueError):
    """An assessment cannot be made or used as asked: not a person, no repository, an unknown finding."""


# -- reading the revision ----------------------------------------------------------------------------

def _check_asker(person: str, persona: str) -> None:
    if not is_person(person):
        raise AssessmentRefused(f"{person!r} is not a person: an assessment is asked for by a named person")
    if persona not in PERSONAS:
        raise AssessmentRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")


def mirror(project: Any) -> Path:
    """The project's mirror, or a refusal that says how a project gets one."""
    bare = project.path("repo.git")
    if not bare.is_dir():
        raise AssessmentRefused(f"{project.pid} has no repository yet: adopt a system (rihmasto adopt) first")
    return bare


def _resolve(bare: Path, ref: str) -> tuple[str, str]:
    """The commit ``ref`` names in the mirror, and its commit date."""
    if not _REF.fullmatch(ref) or ".." in ref:
        raise AssessmentRefused(f"{ref!r} is not a branch, a ref or a revision")
    try:
        revision = _git_read(bare, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
        return revision, _git_read(bare, "log", "-1", "--format=%cI", revision)
    except RuntimeError as exc:
        raise AssessmentRefused(f"{ref} names no commit of the mirror") from exc


def _inventory(root: Path, files: list[str]) -> dict[str, Any]:
    """The inventory of the assessed revision, by the adoption's own rules; every route is looked for. The
    team's own conventions for its AI tools are read too (kernel/agent_context.py): a test command they
    state comes first, and the panel is told what they settle."""
    from kernel.agent_context import from_folder
    from kernel.agent_context_use import apply_stated

    kept = [f for f in files if not f.startswith(VENDORED) and "/node_modules/" not in f]
    docker = dockerfiles(kept)
    inv = {"by": "rule (kernel/adopt.py), no model", "files": len(kept), "languages": languages(kept),
           "tests": detect_tests(root, kept), "readme": readme(root, kept), "routes": endpoints(root, kept),
           "dockerfile": {"present": bool(docker), "files": docker}}
    conventions = from_folder(root)
    if conventions["found"]:
        inv["conventions"] = conventions
        apply_stated(inv, conventions)
        inv.pop("test_command", None)
    return inv


def _factory(project: Any) -> dict[str, Any]:
    """What the factory's own records of the project hold: the ledger, decisions, controls and scans."""
    from kernel.canon import Canon
    from kernel.evidence_pack import CONTROLS
    from kernel.security import summary

    ledger = project.ledger()
    return {"records": len(ledger.records()), "intact": ledger.verify().intact,
            "decisions": len(Canon(project).decisions()),
            "controls": [{k: c[k] for k in ("control", "topic", "status")} for c in CONTROLS],
            "scans": summary(project).get("scans") or []}


def _run_rules(repo: Repo) -> list[dict[str, Any]]:
    """Every rule's result. A rule that cannot read what it needs is not measured, and says why."""
    out = []
    for perspective, rule in RULES:
        try:
            out.append(rule(repo))
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, IndexError, RecursionError) as exc:
            out.append(result(f"{perspective}.{rule.__name__}", perspective, rule.__name__.replace("_", " "),
                              "not measured", reason=f"the rule could not read the repository: "
                                                     f"{type(exc).__name__}: {str(exc)[:200]}"))
    return out


def _scan(root: Path, gaps: list[str], which: Callable[[str], str | None]) -> tuple[list[dict[str, Any]], Any]:
    """The red team's static layer over the revision: each finding, and what it read."""
    from kernel.redteam.static import LIMITS, scan

    report = scan([root], root=root, which=which)
    return [*redteam(report), scan_coverage(report, gaps, report.notes[len(LIMITS):])], report


def _ordered(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """By perspective, verdict, severity and key; each finding numbered F-1 on in that order."""
    checks.sort(key=lambda c: (_ORDER[c["perspective"]], _ORDER.get(c["verdict"], 9),
                               _ORDER.get(c.get("severity") or "", 9), c["key"]))
    for n, c in enumerate((c for c in checks if c["verdict"] == "failed"), 1):
        c["id"] = f"F-{n}"
    return checks


def _examine(project: Any, bare: Path, root: Path, revision: str, committed: str,
             which: Callable[[str], str | None]) -> dict[str, Any]:
    snap = snapshot(bare, revision, root)
    inv = _inventory(root, snap.files)
    repo = Repo(root=root, files=snap.files, bare=bare, revision=revision, committed=committed,
                records={"inventory": inv, "baseline": project.read("baseline.json"), "factory": _factory(project)},
                notes=snap.notes)
    scanned, report = _scan(root, snap.notes, which)
    return {"checks": _ordered(_run_rules(repo) + scanned), "inventory": inv, "files": snap.files,
            "notes": snap.notes, "report": report}


# -- the record --------------------------------------------------------------------------------------

def digest(record: dict[str, Any]) -> str:
    """The sha256 of a record, as canonical JSON: what the ledger and the index hold for it."""
    text = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _counts(checks: list[dict[str, Any]], proposals: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [c for c in checks if c["verdict"] == "failed"]
    return {"checks": len(checks), "findings": len(failed), "proposed": len(proposals),
            "by_severity": {s: sum(1 for c in failed if c["severity"] == s) for s in SEVERITIES},
            "by_verdict": {v: sum(1 for c in checks if c["verdict"] == v) for v in VERDICTS},
            "by_perspective": {p: {v: sum(1 for c in checks if c["perspective"] == p and c["verdict"] == v)
                                   for v in VERDICTS} for p in PERSPECTIVES}}


def _gone(key: str, verdicts: dict[str, str]) -> bool:
    """Whether a finding no longer failing was resolved, rather than no longer measured: its check passed
    (or no longer applies), or the red team read the whole revision and no longer finds it."""
    now = verdicts.get(key)
    if now in ("passed", "not applicable"):
        return True
    return now is None and key.startswith("security.RT-") and verdicts.get("security.scan_coverage") == "passed"


def diff(older: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any]:
    """What changed between two records, by key: findings new, resolved, still open and no longer measured,
    checks whose verdict moved, and the panel's proposals new and gone."""
    was = {c["key"]: c for c in older.get("checks") or [] if c["verdict"] == "failed"}
    now = {c["key"]: c for c in newer.get("checks") or [] if c["verdict"] == "failed"}
    before = {c["key"]: c["verdict"] for c in older.get("checks") or []}
    after = {c["key"]: c["verdict"] for c in newer.get("checks") or []}
    left = sorted(was.keys() - now.keys())
    proposed = ({p["key"] for p in older.get("proposals") or []}, {p["key"] for p in newer.get("proposals") or []})
    return {"new": sorted(now.keys() - was.keys()), "resolved": [k for k in left if _gone(k, after)],
            "unmeasured": [k for k in left if not _gone(k, after)], "still": sorted(was.keys() & now.keys()),
            "severity_changed": sorted(k for k in was.keys() & now.keys() if was[k]["severity"] != now[k]["severity"]),
            "verdict_changed": [{"key": k, "from": before[k], "to": after[k]}
                                for k in sorted(before.keys() & after.keys()) if before[k] != after[k]],
            "proposals_new": sorted(proposed[1] - proposed[0]), "proposals_gone": sorted(proposed[0] - proposed[1])}


def _sarif(folder: Path, aid: str, report: Any) -> dict[str, Any]:
    """The red team's SARIF beside the record, to ingest into the security gate; none when it measured nothing."""
    from kernel.redteam.report import NothingMeasured, to_sarif, tool_name

    out = {"tool": tool_name(report.kind), "version": report.tool_version, "verdict": report.verdict,
           "counts": report.counts(), "sarif": None, "sarif_sha256": None}
    try:
        doc = to_sarif(report.findings, report.coverage, report.tool_version, canaries=report.canaries,
                       kind=report.kind)
    except NothingMeasured as exc:
        return out | {"note": f"no SARIF: {exc}"}
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    write_text(folder / f"{aid}.sarif", text)
    return out | {"sarif": f"{FOLDER}/{aid}.sarif", "sarif_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def _trace(person: str, persona: str, checks: list[dict[str, Any]], panel: dict[str, Any],
           revision: str, scan: dict[str, Any]) -> dict[str, Any]:
    """The trace every path writes (D-0017): who asked, who decided and to whom a part was delegated,
    what was assumed, what proves it."""
    delegated = ({"role": panel["role"], "perspectives": panel["answered"], "models": panel.get("models") or {},
                  "by": {"person": person, "persona": persona}, "kept_as": "model_proposed"}
                 if panel.get("used") else None)
    return {"asked_by": {"person": person, "persona": persona}, "decided_by": DECIDED_BY, "delegated_to": delegated,
            "assumed": [{"key": c["key"], "reason": c.get("reason")} for c in checks if c["verdict"] == "not measured"],
            "proves": {"revision": revision, "sarif_sha256": scan.get("sarif_sha256")}}


def _record(project: Any, body: dict[str, Any], *, person: str, persona: str, ref: str, revision: str,
            committed: str, proposals: list[dict[str, Any]], panel: dict[str, Any]) -> dict[str, Any]:
    folder = project.path(FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    with updating_json(folder / "index.json", []) as index:
        n = len(index) + 1
        aid, previous = f"AS-{n}", read_json(folder / f"AS-{n - 1}.json") if n > 1 else None
        checks = body["checks"]
        scan = _sarif(folder, aid, body["report"])
        record = {"schema": SCHEMA, "id": aid, "version": n, "project": project.pid, "ref": ref,
                  "revision": revision, "committed": committed, "at": project.factory.clock.stamp(),
                  "asked_by": {"person": person, "persona": persona}, "inventory": body["inventory"],
                  "checks": checks, "proposals": proposals, "panel": panel, "counts": _counts(checks, proposals),
                  "since": {"previous": previous["id"], **diff(previous, {"checks": checks, "proposals": proposals})}
                  if previous else None, "scan": scan, "notes": body["notes"],
                  "trace": _trace(person, persona, checks, panel, revision, scan)}
        sha = digest(record)
        write_json(folder / f"{aid}.json", record)
        index.append({"id": aid, "version": n, "at": record["at"], "ref": ref, "revision": revision, "sha256": sha,
                      "asked_by": record["asked_by"], "panel": bool(panel.get("used")),
                      "counts": {k: record["counts"][k] for k in ("findings", "proposed", "by_severity")}})
        _log(project, record, sha)
    return record


def _log(project: Any, record: dict[str, Any], sha: str) -> None:
    trace, since = record["trace"], record["since"] or {}
    project.log("assessment_recorded", {
        "id": record["id"], "version": record["version"], "ref": record["ref"], "revision": record["revision"],
        "person": trace["asked_by"]["person"], "persona": trace["asked_by"]["persona"],
        "file": f"{FOLDER}/{record['id']}.json", "sha256": sha, "sarif_sha256": record["scan"]["sarif_sha256"],
        "findings": record["counts"]["findings"], "by_severity": record["counts"]["by_severity"],
        "proposed": record["counts"]["proposed"], "decided_by": trace["decided_by"],
        "delegated_to": trace["delegated_to"], "assumed": [a["key"] for a in trace["assumed"]][:40],
        "since": {"previous": since.get("previous"), "new": len(since.get("new") or []),
                  "resolved": len(since.get("resolved") or [])} if since else None})


def assess(project: Any, *, person: str, persona: str, model: Any = None, ref: str = "main",
           which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    """Assess the project's repository at ``ref`` and record the assessment as its next version. With
    ``model``, the panel's perspectives propose further findings, kept apart as model_proposed."""
    _check_asker(person, persona)
    bare = mirror(project)
    revision, committed = _resolve(bare, ref)
    with tempfile.TemporaryDirectory(prefix="rihmasto-assess-", ignore_cleanup_errors=True) as tmp:
        body = _examine(project, bare, Path(tmp), revision, committed, which)
    proposals: list[dict[str, Any]]
    if model is None:
        proposals, panel = [], {"used": False, "reason": "no model was given: the rules' findings only"}
    else:
        proposals, panel = propose(model, body["inventory"], body["checks"], body["files"])
    return _record(project, body, person=person, persona=persona, ref=ref, revision=revision, committed=committed,
                   proposals=proposals, panel=panel)


# -- reading records ----------------------------------------------------------------------------------

def history(project: Any) -> list[dict[str, Any]]:
    """Every version, oldest first, as the index holds it (with each record's sha256)."""
    index = read_json(project.path(FOLDER, "index.json"), [])
    return index if isinstance(index, list) else []


def _version(version: int | str | None, latest: int) -> int:
    if version is None:
        if not latest:
            raise LookupError("no assessment yet: run rihmasto assess first")
        return latest
    text = str(version).strip().upper().removeprefix("AS-")
    if not text.isdigit() or not 1 <= int(text) <= latest:
        raise LookupError(f"no assessment {version}" + (f": AS-1 to AS-{latest} exist" if latest else ""))
    return int(text)


def load(project: Any, version: int | str | None = None) -> dict[str, Any]:
    """One version (the latest by default); a LookupError when there is none."""
    n = _version(version, len(history(project)))
    record = read_json(project.path(FOLDER, f"AS-{n}.json"))
    if not isinstance(record, dict):
        raise LookupError(f"assessment AS-{n} could not be read")
    return record


def ledgered(project: Any) -> dict[str, str]:
    """Each version's sha256 as the hash-chained ledger recorded it (`assessment_recorded`)."""
    out = {}
    for r in project.ledger().records():
        event = r.get("event") or {}
        payload = event.get("payload") if event.get("kind") == "assessment_recorded" else None
        if isinstance(payload, dict) and payload.get("id"):
            out[str(payload["id"])] = str(payload.get("sha256"))
    return out


def intact(project: Any, entry: dict[str, Any], logged: dict[str, str] | None = None) -> bool:
    """Whether a version's record still hashes to the sha256 the ledger recorded for it, and its index
    entry agrees. The index is a plain file beside the records: the ledger's hash chain is what is trusted."""
    logged = ledgered(project) if logged is None else logged
    record = read_json(project.path(FOLDER, f"{entry.get('id')}.json"))
    return isinstance(record, dict) and digest(record) == logged.get(str(entry.get("id"))) == entry.get("sha256")


def checked(project: Any) -> list[dict[str, Any]]:
    """Every version, oldest first, each with whether its record is intact against the ledger."""
    logged = ledgered(project)
    return [dict(e, intact=intact(project, e, logged)) for e in history(project)]


def compare(project: Any, older: int | str | None = None, newer: int | str | None = None) -> dict[str, Any]:
    """What changed between two versions (by default the latest and the one before it)."""
    latest = len(history(project))
    b = _version(newer, latest)
    a = _version(older, latest) if older is not None else b - 1
    if a < 1:
        raise LookupError("one assessment only: there is nothing to compare it with yet")
    first, second = load(project, a), load(project, b)
    titles = {c["key"]: c["title"] for c in [*first["checks"], *second["checks"], *first.get("proposals", []),
                                             *second.get("proposals", [])]}
    ends = ("id", "revision", "at")
    return {"from": {k: first[k] for k in ends}, "to": {k: second[k] for k in ends}, **diff(first, second),
            "titles": titles}


def _where(e: dict[str, Any]) -> str:
    if e.get("line"):
        return f"{e['file']}:{e['line']}: {e.get('text', '')}"
    return f"{e['file']}: {e.get('fact', '')}" if e.get("file") else str(e.get("fact", ""))


def _rests(r: dict[str, Any]) -> str:
    return f"{r['ref']} ({'found' if r['found'] else 'not found in the repository'})"


def finding_line(c: dict[str, Any]) -> dict[str, Any]:
    """A finding (a rule's or the panel's) in short: what a person scans."""
    keys = ("id", "key", "perspective", "severity", "title", "summary", "suggestion", "by", "panel", "why")
    evidence = [_where(e) for e in c.get("evidence") or []] + [_rests(r) for r in c.get("rests_on") or []]
    return {k: c[k] for k in keys if c.get(k) is not None} | {"evidence": evidence}


def summary(record: dict[str, Any]) -> dict[str, Any]:
    """A record in short: its counts, the findings, the panel's proposals and what was not measured."""
    return {k: record.get(k) for k in ("id", "version", "ref", "revision", "committed", "at", "asked_by", "counts",
                                       "since", "scan", "panel")} | {
        "findings": [finding_line(c) for c in record["checks"] if c["verdict"] == "failed"],
        "proposals": [finding_line(p) for p in record.get("proposals") or []],
        "not_measured": [{"key": c["key"], "title": c["title"], "reason": c.get("reason")}
                         for c in record["checks"] if c["verdict"] == "not measured"]}


__all__ = ["CLASS_DEFAULT", "FOLDER", "RULES", "SCHEMA", "AssessmentRefused", "assess", "checked", "compare", "diff",
           "digest", "finding_line", "history", "intact", "is_adopted", "ledgered", "load", "mirror", "summary"]
