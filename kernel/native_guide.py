"""What a project's own sources lead to next, said truly (FR-SRC2; kernel/native_apply.py draws the panel).

- **Read again on a new commit** is said only when it happens: an adopted project's commit-read sources are read on
  a new commit once its watch is set up; until then they say "not watched yet" and the next steps offer Set up the
  watch. An attached repository is read where it is, on Read again.
- **Review in Alignment.** Mapped requirements and tasks reach the contract and the Board when a person accepts
  them in Alignment; until then a next step says how many wait (``Review 4 requirements and 6 tasks to import``)
  and opens it.
- **Stopped sources** stay listed, with who stopped them and why, and Resume; what they read is not offered again
  as found.
- **Its own tests** replace the root-level baseline wherever a project's state is said (the header, Its state, the
  suggested automation), once its own test roots or imported results have run; an automation that runs its tests
  runs each mapped root.
- **Its own findings** show in Health beside the audits' findings, each at its place in the code when it says one.
"""

from __future__ import annotations

from typing import Any

from kernel import native_sources as ns
from kernel import native_tests as nt

CLOSED = ("closed", "fixed", "resolved", "done", "wontfix")
MAX_FINDINGS = 50


# -- read again on a new commit, truly -------------------------------------------------------------------

def watched(project: Any) -> bool | None:
    """Whether new commits reach this project's sources: True when watched, False when an adopted project is not
    watched yet, None for an attached repository (read where it is)."""
    from kernel import adopt_watch

    if project.meta.get("source_kind") != "adopted":
        return None
    return bool(adopt_watch.view(project).get("watching"))


def every_said(project: Any, mapped: list[dict[str, Any]]) -> bool | None:
    """Each commit-read source says how it is read in truth; returns ``watched``."""
    w = watched(project)
    for s in mapped:
        if s.get("every") != "commit" or s.get("state") != "mapped":
            continue
        if w is False:
            s["every_said"] = "on a new commit once watched (not watched yet)"
        elif w is None:
            s["every_said"] = "by hand: an attached repository is read where it is, on Read again"
    return w


def watch_step(w: bool | None, mapped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if w is not False or not any(s.get("every") == "commit" and s.get("state") == "mapped" for s in mapped):
        return []
    return [{"label": "Set up the watch", "do": {"kind": "watch"},
             "why": "new commits reach Rihmasto only through the watch: until it is set up, its sources are read "
                    "again only when you press Read again"}]


# -- review in Alignment ---------------------------------------------------------------------------------

def _at(x: dict[str, Any]) -> tuple[str, int]:
    src = x.get("source") or {}
    return str(src.get("path")), int((src.get("lines") or [0])[0] or 0)


def pending_review(project: Any) -> dict[str, int]:
    """How many requirements and tasks read from the project's own sources wait to be accepted in Alignment: those
    open in the latest scan, and those read since that no scan has proposed yet."""
    from kernel import alignment_records as kalign

    kinds = {s["kind"] for s in ns.active(project)}
    last = ns.latest_read(project)
    scan = project.read(kalign.SCAN, None) or {}
    items = (scan.get("proposal") or {}).get("items") or []
    decided = kalign.decisions(project)
    out = {}
    for group in ("requirements", "tasks"):
        if group not in kinds:
            out[group] = 0
            continue
        read = {(r["path"], int(r["line"])) for r in last.get(group) or []}
        mine = [i for i in items if i["group"] == group and _at(i) in read]
        seen = {_at(i) for i in mine}
        out[group] = sum(1 for i in mine if i["id"] not in decided) + len(read - seen)
    return out


def align_step(project: Any) -> list[dict[str, Any]]:
    n = pending_review(project)
    if not (n["requirements"] or n["tasks"]):
        return []
    said = " and ".join(f"{k} {w}{'' if k == 1 else 's'}" for k, w in ((n["requirements"], "requirement"),
                                                                       (n["tasks"], "task")) if k)
    return [{"label": f"Review {said} to import", "do": {"kind": "align"}, "counts": n,
             "why": "what the mapped sources hold reaches the contract and the Board once you accept it in Alignment: "
                    "Read the repository there, then Accept"}]


# -- stopped sources -------------------------------------------------------------------------------------

def stopped(book: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": s["id"], "kind": s["kind"], "kind_label": ns.KINDS[s["kind"]], "glob": s["glob"],
             "stopped": s.get("stopped") or {}} for s in book["sources"] if s.get("state") == "stopped"]


def not_stopped(proposals: list[dict[str, Any]], book: dict[str, Any]) -> list[dict[str, Any]]:
    """Found sources, without those a person stopped reading (they are listed as stopped, with Resume)."""
    gone = {(s["kind"], s["glob"]) for s in book["sources"] if s.get("state") == "stopped"}
    return [p for p in proposals if (p["kind"], p["glob"]) not in gone]


# -- its own tests, where its state is said --------------------------------------------------------------

def _root_said(root: str | None) -> str:
    return root or "the repository's root"


def _imported_said(r: dict[str, Any]) -> str:
    name = r.get("name") or "imported results"
    said = name if "import" in name.lower() else f"{name} (imported)"
    return f"{said}{' from ' + r['machine'] if r.get('machine') else ''} {r['verdict']}"


def _overall(latest: dict[str, dict[str, Any]], roots: list[dict[str, Any]]) -> str:
    verdicts = [r["verdict"] for r in latest.values()]
    if "failed" in verdicts:
        return "failed"
    every = all(v == "passed" for v in verdicts) and all(r["root"] in latest for r in roots)
    return "passed" if every else "partly run"


def own_tests(project: Any) -> dict[str, Any] | None:
    """Its own tests' latest verdicts, by mapped root and imported results; None when none has run."""
    latest = nt.latest(project) if ns.applies(project) else {}
    if not latest:
        return None
    roots = ns.mapped_roots(project)
    names = {x["root"] for x in roots}
    parts = [f"{_root_said(r['root'])} {latest[r['root']]['verdict'] if r['root'] in latest else 'not run yet'}"
             for r in roots]
    parts += [_imported_said(r) for k, r in latest.items() if r.get("from") == "imported" and k not in names]
    return {"line": "its own tests: " + "; ".join(parts), "verdict": _overall(latest, roots),
            "commands": [f"{r['command']} in {_root_said(r['root'])}" for r in roots]}


def own_command_line(project: Any) -> str | None:
    """The mapped roots' commands, as a suggested automation names them."""
    roots = ns.mapped_roots(project) if ns.applies(project) else []
    return "; ".join(f"{r['command']} in {_root_said(r['root'])}" for r in roots)[:200] or None


def run_own_roots(project: Any, *, person: str, persona: str, timeout: int | None = None) -> dict[str, Any] | None:
    """An automation's test run: each mapped root's own command (the automation is its owner's yes); None when no
    root is mapped, so the suite found at the root runs as before."""
    roots = ns.mapped_roots(project) if ns.applies(project) else []
    if not roots:
        return None
    got = [nt.run(project, r["root"], person=person, persona=persona, confirmed=True, timeout=timeout) for r in roots]
    verdicts = [g["verdict"] for g in got]
    verdict = "failed" if "failed" in verdicts else "passed" if all(v == "passed" for v in verdicts) else "not measured"
    return {"outcome": "done", "verdict": verdict,
            "detail": "the project's own tests: " + "; ".join(f"{_root_said(g['root'])} {g['verdict']}" for g in got)}


# -- its own findings, in Health -------------------------------------------------------------------------

def finding_place(f: dict[str, Any]) -> str:
    """Where a finding is: its place in the code when it says one, with the line of the file that keeps it."""
    kept = f"{f['path']}:{f['line']}"
    return f"{f['where']} ({kept})" if f.get("where") else kept


def health_findings(project: Any) -> dict[str, Any]:
    """The open findings of the project's own findings file(s), for Health."""
    if not ns.applies(project):
        return {"applies": False, "findings": [], "sources": []}
    srcs = [s for s in ns.active(project) if s["kind"] == "findings"]
    last = ns.latest_read(project)
    rows = [f for f in last.get("findings") or [] if f.get("status") not in CLOSED]
    shown = [{"id": f["id"], "title": f["title"], "severity": f["severity"], "status": f["status"],
              "where": finding_place(f), "source": f.get("source")} for f in rows[:MAX_FINDINGS]]
    return {"applies": True, "sources": [{"id": s["id"], "glob": s["glob"]} for s in srcs], "read_at": last.get("at"),
            "open": len(rows), "findings": shown}
