"""Gnomon's audits and evals in Insights (FR-EVL1): a tile per eval in the dimension it measures (QA, Governance,
Context drift), from the ledger's ``eval_ran`` records (kernel/gnomon_evals_run.py).

A tile's figure is the eval's main score on its latest run in the window (for the factory, the mean of each
project's latest), its delta against the window before, and its trend: the last runs' verdicts. A dimension where
no audit ran in the window has one tile, not measured, that says how to run one. Nothing is estimated.
"""

from __future__ import annotations

from typing import Any

from kernel.insights.base import PREVIOUS_WORDS, Scope, delta, level, tile

HOW = ("run one under a project's Health, Audits & evals, or `rihmasto evals run <pid> --eval <id>`; enable it as a "
       "check to run it weekly")


def _latest(rows: list[tuple[Any, Any, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    last: dict[str, dict[str, Any]] = {}
    for p, t, pl in rows:
        if t is not None and (p.pid not in last or t >= last[p.pid]["t"]):
            last[p.pid] = {"t": t, "pl": pl}
    return last


def _mean(last: dict[str, dict[str, Any]], key: str) -> float | None:
    vals = [v["pl"].get("scores", {}).get(key) for v in last.values()]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 1) if vals else None


def _status(ev: Any, value: float | None, verdict: Any) -> str | None:
    if value is not None and ev.unit == "%":
        return level(value, 90, 60, higher_is_better=ev.higher_is_better)
    return {"passed": "good", "failed": "critical"}.get(str(verdict))


def _tile(scope: Scope, ev: Any, rows: list, before: list) -> dict[str, Any]:
    """One eval's tile: its score on the latest run (the mean of each project's latest), delta and last verdicts."""
    last = _latest(rows)
    value, prior = _mean(last, ev.score), _mean(_latest(before), ev.score)
    newest = rows[-1]
    verdict, said = newest[2].get("verdict"), newest[2].get("summary")
    line = (f"Gnomon {ev.label}: {said}." if scope.pid else
            f"Gnomon {ev.label} on {len(last)} project(s); the latest: {said}.")
    return tile(f"gnomon_{ev.id}", f"Gnomon: {ev.score_label}", value, unit=ev.unit if ev.unit == "%" else "",
                basis=f"ledger eval_ran: {ev.label} ({'latest run' if scope.pid else 'mean of each latest'})",
                delta=delta(value, prior, PREVIOUS_WORDS.get(scope.window, "")), status=_status(ev, value, verdict),
                sub="last runs: " + ", ".join(str(x[2].get("verdict")) for x in rows[-5:]), line=line,
                href=scope.href(newest[0], "checks"),
                why=f"the {ev.label}'s last run in the window measured no {ev.score_label.lower()} ({verdict})",
                how=HOW)


def tiles(scope: Scope, dimension: str) -> list[dict[str, Any]]:
    """The tiles of the evals measuring ``dimension`` that ran in the window."""
    from kernel import gnomon_evals as ge

    now = [(p, t, pl) for p, t, pl, _ in scope.events("eval_ran") if pl.get("dimension") == dimension]
    before = [(p, t, pl) for p, t, pl, _ in scope.events("eval_ran", previous=True) if pl.get("dimension") == dimension]
    out = []
    for ev in ge.CATALOGUE:
        rows = sorted((x for x in now if x[2].get("eval") == ev.id), key=lambda x: x[1].isoformat() if x[1] else "")
        if rows:
            out.append(_tile(scope, ev, rows, [x for x in before if x[2].get("eval") == ev.id]))
    if not out:
        out.append(tile(f"gnomon_{dimension}", "Gnomon audits", None, basis="ledger eval_ran",
                        why="no Gnomon audit of this kind ran in the window", how=HOW))
    return out
