"""Context drift: how far the code, the contract, the canon and the agents' context have moved from what was agreed.

- **Spec age**: days since the spec was last written (``spec_written``) and the merges since then (``merged``):
  code that moved on while the spec stood still.
- **Requirements without a passing test**: no criterion of the requirement is verified or held out
  (kernel/status.py's evidence).
- **Contract revisions since the last release**: ``contract_compiled`` records with a new revision after the
  last ``release_started``.
- **Repository alignment**: the drift of each project's latest ``alignment_scanned`` (new, changed and removed
  items since the scan before, kernel/alignment_records.py), with the ``alignment_accepted`` and
  ``alignment_rejected`` decisions; not measured before a scan. **Contradictions** are the canon's own
  (kernel/insight.py's alignment).
- **Assumptions** settled against open.
- **Model context**: each run's context window and trims (Gnomon records a trim when the prompt would not fit),
  and the largest prompt its trail records against the window.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from kernel.insights import gnomon_records as gr
from kernel.insights.base import Scope, answer, chart, first, gap, hours, share, tile
from kernel.insights.lines import count

HOW_SPEC = "write the spec (rihmasto spec <pid>) and build its tasks"
NEAR = 80.0
Row = dict[str, Any]


def _spec(scope: Scope, p: Any) -> Row | None:
    specs = [t for q, t, _, _ in scope.every("spec_written") if q.pid == p.pid and t]
    if not specs:
        return None
    last = max(specs)
    merges = sum(1 for q, t, _, _ in scope.every("merged") if q.pid == p.pid and t and t > last)
    return {"project": p, "days": round((hours(last, scope.now) or 0) / 24, 1), "merges": merges}


def _untested(p: Any) -> list[str]:
    from kernel.status import evidence

    if not p.path("contract.json").exists():
        return []
    proven: dict[str, bool] = {}
    for e in evidence(p):
        proven[e["requirement"]] = proven.get(e["requirement"], False) or e["state"] in ("verified", "held_out")
    return sorted(r for r, ok in proven.items() if not ok)


def _revisions(scope: Scope, p: Any) -> int | None:
    starts = [rec["seq"] for q, _, _, rec in scope.every("release_started") if q.pid == p.pid]
    if not starts:
        return None
    revs = [pl.get("revision") for q, _, pl, rec in scope.every("contract_compiled") if q.pid == p.pid
            and rec["seq"] > starts[-1]]
    return len(set(revs))


ALIGNMENT_KINDS = ("alignment_scanned", "alignment_accepted", "alignment_rejected")


def _drift_of(value: Any) -> int:
    """A scan's drift as a number: the new, changed and removed items it counts (kernel/alignment_records.py)."""
    if isinstance(value, dict):
        return sum(len(v) if isinstance(v, list) else int(v or 0) for v in value.values())
    return len(value) if isinstance(value, list) else int(value or 0)


def _alignment(scope: Scope) -> tuple[int | None, str, Counter]:
    """The repository alignment's drift (FR-ALN1): the latest ``alignment_scanned`` of each project, with the
    decisions people recorded on it (``alignment_accepted``, ``alignment_rejected``). Not measured before a scan."""
    latest: dict[str, Any] = {}
    decided: Counter = Counter()
    for p, _, pl, rec in scope.every(*ALIGNMENT_KINDS):
        kind = rec["event"].get("kind")
        if kind == "alignment_scanned":
            latest[p.pid] = pl.get("drift")
        else:
            decided[kind.rsplit("_", 1)[1]] += len(pl.get("items") or pl.get("ids") or []) or 1
    basis = "ledger " + " / ".join(ALIGNMENT_KINDS) + ": the drift of each project's latest scan"
    if not latest:
        return None, basis, decided
    return sum(_drift_of(v) for v in latest.values()), basis, decided


def _context(scope: Scope) -> Row:
    from kernel.canon import Canon
    from kernel.insight import alignment

    runs = gr.runs(scope)
    found = gr.trails(runs)
    for r in runs:
        r["peak"] = (found["by_run"].get(r["run"]) or {}).get("peak")
    return {"scope": scope, "specs": [x for p in scope.projects if (x := _spec(scope, p))],
            "untested": {p.pid: _untested(p) for p in scope.projects},
            "revisions": {p.pid: n for p in scope.projects if (n := _revisions(scope, p)) is not None},
            "contradictions": sum(len(alignment(p)) for p in scope.projects),
            "assumptions": Counter(a["status"] for p in scope.projects for a in Canon(p).assumptions()),
            "runs": runs, "alignment": _alignment(scope)}


def _t_spec(c: Row) -> Row:
    specs = sorted(c["specs"], key=lambda s: -s["merges"])
    merges = sum(s["merges"] for s in specs)
    line = (f"{c['scope'].title(specs[0]['project'])} merged {count(specs[0]['merges'], 'change')} since its spec was "
            f"written {specs[0]['days']} days ago." if merges else "No code merged since the specs were written.")
    return tile("merges_since_spec", "Merges since the spec", merges if specs else None, line=line,
                sub=f"spec {first(specs, 'days')} days old" if specs else None,
                basis="merged records after each project's last spec_written",
                status="warning" if merges >= 10 else None,
                why="no project in this scope has a written spec", how=HOW_SPEC)


def _t_untested(c: Row) -> Row:
    rows = [(pid, r) for pid, reqs in c["untested"].items() for r in reqs]
    compiled = any(p.path("contract.json").exists() for p in c["scope"].projects)
    line = "Every requirement has a passing check."
    if rows:
        line = f"{count(len(rows), 'requirement')} have no verified or held-out criterion; the first is {rows[0][1]}."
    return tile("untested", "Requirements without a passing test", len(rows) if compiled else None, line=line,
                basis="kernel.status.evidence: no criterion of the requirement verified or held out",
                status="warning" if rows else "good", href=f"#/p/{rows[0][0]}/spec/{rows[0][1]}" if rows else None,
                why="no project in this scope has a compiled contract", how="compile the spec (rihmasto compile <pid>)")


def _t_revisions(c: Row) -> Row:
    revs = c["revisions"]
    n = sum(revs.values())
    return tile("revisions_since_release", "Contract revisions since release", n if revs else None,
                basis="contract_compiled revisions after the last release_started", status="warning" if n else "good",
                line=(f"The contract changed {count(n, 'time')} since the last release." if n
                      else "The contract has not changed since the last release."),
                why="no release has started in this scope", how="deliver a release (rihmasto deliver <pid>)")


def _t_alignment(c: Row) -> Row:
    n, basis, decided = c["alignment"]
    sub = f"{decided['accepted']} accepted, {decided['rejected']} rejected" if decided else None
    return tile("repo_drift", "Repository drift", n, basis=basis, status="warning" if n else "good", sub=sub,
                line=f"The latest alignment scan found {count(n or 0, 'item')} new, changed or removed since the "
                     "scan before.",
                why="no adopted or attached project in this scope has been aligned with its repository",
                how="read the repository on the project's Alignment tab (rihmasto align <pid> --scan)")


def _t_contradictions(c: Row) -> Row:
    n = c["contradictions"]
    return tile("contradictions", "Canon contradictions", n if c["scope"].projects else None,
                basis="kernel.insight.alignment: dissent, refuted or overdue assumptions, stale approvals",
                status="warning" if n else "good",
                line=f"The canon holds {count(n, 'contradiction')}." if n else "The canon holds no contradiction.",
                why="no project in this scope yet", how="create a project (rihmasto new)")


def _t_assumptions(c: Row) -> Row:
    a = c["assumptions"]
    total = sum(a.values())
    settled = a.get("confirmed", 0) + a.get("refuted", 0)
    return tile("assumptions_settled", "Assumptions settled", share(settled, total), unit="%",
                sub=f"{a.get('open', 0)} open", basis="the canon's assumptions: confirmed or refuted against open",
                line=f"{settled} of {count(total, 'assumption')} are settled by a person; "
                     f"{a.get('open', 0)} still open.",
                why="no assumption was made in this scope", how="the factory assumes an answer in assume or mixed mode")


def _t_context(c: Row) -> Row:
    sized = [r for r in c["runs"] if r["window"]]
    trimmed = [r for r in sized if r["trims"]]
    peaks = [r["peak"] / r["window"] * 100 for r in sized if r["peak"]]
    high = sum(1 for x in peaks if x >= NEAR)
    line = f"No run had to trim its context ({len(sized)} with a window recorded)."
    if trimmed or high:
        line = (f"{count(len(trimmed), 'run')} trimmed their context to fit the window; "
                f"{high} came within {NEAR:.0f}% of it.")
    return tile("context_trims", "Runs that trimmed context", len(trimmed) if sized else None, sub=f"of {len(sized)}",
                basis="each gnomon_run's context window and trims; the largest prompt in its trail",
                status="warning" if trimmed else "good", line=line,
                why="no run in the window recorded its context window (Gnomon 0.6.6 and later records it)",
                how="run Gnomon 0.6.6 or later in the lanes (rihmasto doctor names the version)")


def _charts(c: Row, tiles: list[Row]) -> list[Row]:
    scope = c["scope"]
    spec_rows = [{"label": scope.title(s["project"]), "value": s["merges"], "sub": f"spec {s['days']} days old",
                  "href": f"#/p/{s['project'].pid}/spec"} for s in sorted(c["specs"], key=lambda s: -s["merges"])[:10]]
    a = c["assumptions"]
    use = [{"label": f"{r['task'] or r['run']}", "value": round(r["peak"] / r["window"] * 100, 1),
            "sub": f"{r['peak']:,} of {r['window']:,} tokens", "href": f"#/p/{r['project']}/cell"}
           for r in c["runs"] if r["window"] and r["peak"]]
    use = sorted(use, key=lambda r: -r["value"])[:10]
    return [
        chart("spec_age", "Merges since each spec was written", "bars", rows=spec_rows, unit="merges",
              line=tiles[0]["line"], basis="merged records after the last spec_written",
              why="no project in this scope has a written spec", how=HOW_SPEC),
        chart("assumptions", "Assumptions settled and open", "stack100", unit="assumptions",
              rows=[{"label": "All assumptions", "values": dict(a)}] if a else [], line=tiles[5]["line"],
              series=[{"key": "confirmed", "label": "Confirmed", "status": "good"},
                      {"key": "refuted", "label": "Refuted", "status": "critical"},
                      {"key": "open", "label": "Open", "hatch": True}], basis="the canon's assumptions",
              why="no assumption was made in this scope", how="the factory assumes an answer in assume or mixed mode"),
        chart("context_use", "Largest prompt against the window", "bars", unit="%",
              rows=use, line=f"The largest prompt reached {first(use, 'value')}% of its window ({first(use, 'label')}).",
              basis="the largest model_call prompt in each run's trail, over its context window",
              why="no run in the window has both a window and its trail's prompt sizes",
              how="keep the lanes' .gnomon-audit folders; Gnomon 0.6.6 records the window"),
    ]


def read(scope: Scope) -> dict[str, Any]:
    c = _context(scope)
    tiles = [_t_spec(c), _t_untested(c), _t_revisions(c), _t_alignment(c), _t_contradictions(c), _t_assumptions(c),
             _t_context(c)]
    from kernel.insights.evals import tiles as gnomon_tiles  # Gnomon's audits (FR-EVL1)

    tiles += gnomon_tiles(scope, "drift")
    gaps = [gap("Which criteria changed since the last release", "a contract record names its revision and counts, "
                "not the criteria a revision changed", "compare the contracts with rihmasto contract export at each "
                "release, or read the change cards that amended them")]
    return answer(scope, "drift", tiles, _charts(c, tiles), gaps)
