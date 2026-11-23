"""Rates that do not lie (FR-C6, FR-M3-AC-2).

A pass rate counts runs that were measured. Apparatus failures, where the harness broke rather
than the work, are left out of both numerator and denominator and reported separately. So are
runs that were not measured. A rate with nothing measured is None, never zero or one.
"""

from __future__ import annotations

from collections import Counter


def pass_rate(runs) -> dict:
    runs = list(runs)
    apparatus = sum(1 for r in runs if r.get("apparatus_failure"))
    not_measured = sum(1 for r in runs if not r.get("apparatus_failure") and r.get("verdict") == "not measured")
    measured = [r for r in runs if not r.get("apparatus_failure") and r.get("verdict") != "not measured"]
    passed = sum(1 for r in measured if r.get("verdict") == "passed")
    return {"rate": (passed / len(measured)) if measured else None, "passed": passed, "measured": len(measured),
            "apparatus_failures": apparatus, "not_measured": not_measured, "runs": len(runs),
            "verdicts": dict(Counter(r.get("verdict") for r in runs))}
