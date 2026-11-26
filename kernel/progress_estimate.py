"""How long a job has left, from its earlier runs (kernel/progress.py, FR-PRG1).

Each step's expected duration is the median of the same step in the last few runs of the same kind on the
same project. What is left is the expected time of the steps not yet ended, less what a running step already
took (never below zero); steps that run at once count once, by the longest. A step never timed before is
counted as unknown and said, and a first run has no estimate at all: it says so, never a guess.
"""

from __future__ import annotations

from typing import Any

SLOWER = 1.5      # a running step past this many times its usual duration is said to take longer than before


def human(secs: float | None) -> str:
    """A duration in words: "under a minute", "about 3 min", "about 1 h 10 min"."""
    if secs is None:
        return "unknown"
    if secs < 60:
        return "under a minute"
    mins = round(secs / 60)
    return f"about {mins} min" if mins < 60 else f"about {mins // 60} h {mins % 60} min"


def _left_of(s: dict[str, Any], now: float) -> float | None:
    """What one step not yet ended has left, or None when it was never timed before."""
    exp = s.get("expected_s")
    if exp is None:
        return None
    ran = now - s["t0"] if s["state"] == "running" and s.get("t0") is not None else 0.0
    return max(float(exp) - ran, 0.0)


def _group_left(steps: list[dict[str, Any]], parallel: bool, now: float) -> tuple[float, int]:
    open_ = [s for s in steps if s["state"] in ("waiting", "running")]
    lefts = [_left_of(s, now) for s in open_]
    known = [x for x in lefts if x is not None]
    total = (max(known) if parallel else sum(known)) if known else 0.0
    return total, len(lefts) - len(known)


def _slow(rep: Any, now: float) -> bool:
    return any(s["state"] == "running" and s.get("expected_s") and s.get("t0") is not None
               and now - s["t0"] > SLOWER * float(s["expected_s"]) + 5 for s in rep.steps.values())


def estimate(rep: Any) -> dict[str, Any]:
    """The time left for ``rep`` (a kernel.progress.Reporter) and how it was reached, in numbers and words."""
    runs = rep.earlier
    if rep.state != "running":
        return {"runs": runs, "left_s": 0.0, "unknown_steps": 0, "said": ""}
    if not runs:
        return {"runs": 0, "left_s": None, "unknown_steps": len(rep.steps),
                "said": f"First {rep.kind} here: no estimate yet. The next run is timed from this one."}
    now = rep._now()
    left, unknown = 0.0, 0
    for g in rep.groups:
        steps = [rep.steps[s["id"]] for s in g["steps"]]
        part, missing = _group_left(steps, g["parallel"], now)
        left, unknown = left + part, unknown + missing
    said = f"{human(left)} left" if left >= 1 else "finishing"
    said += f", from {runs} earlier run{'s' if runs != 1 else ''}"
    if unknown:
        said += f"; {unknown} step{'s' if unknown != 1 else ''} never timed before"
    if _slow(rep, now):
        said += "; the step running now takes longer than before"
    return {"runs": runs, "left_s": round(left, 1), "unknown_steps": unknown, "said": said + "."}


__all__ = ["estimate", "human"]
