"""Read models over the ledgers for the Cell and Floor views (FR-M3).

- **Cell:** every Gnomon run of a project. Each row has its id, role, model, verdict with its
  native values, surface hash, audit chain status and priced cost.
- **Floor:** runs counted by phase (the project's stage) and verdict. The pass rate is over
  measured runs only. Not-measured runs and apparatus failures are counted beside it, never
  averaged in.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from kernel.metrics import pass_rate
from kernel.pricing import spend
from kernel.store import STAGES


def cell(project) -> list:
    rows = []
    for rec in project.ledger().of_kind("gnomon_run"):
        p = rec["event"]["payload"]
        rows.append({"run": p.get("run"), "task": p.get("task"), "round": p.get("round"), "role": p.get("role"),
                     "model": p.get("model"), "verdict": p.get("verdict"), "native": p.get("native"),
                     "apparatus_failure": p.get("apparatus_failure"), "tampered": p.get("tampered"),
                     "surface_hash": p.get("surface_hash"), "chain": p.get("chain"), "cost": p.get("cost"),
                     "tokens": p.get("tokens"), "at": rec["event"].get("at")})
    return rows


def gates(project) -> dict:
    """The factory's own judgement of the work, from the gate records: rounds judged and passed,
    the first-round pass rate over tasks whose first gate was measured, merges and escalations.
    A first round the gate could not measure (a verifier with no usable answer) is counted beside
    the rate, never in it, as a pass rate over runs leaves out what was not measured. This, not a
    Gnomon run's harness outcome, says whether the work was good."""
    rounds = passed = 0
    first: dict[str, str] = {}
    for rec in project.ledger().of_kind("gate"):
        pl = rec["event"]["payload"]
        rounds += 1
        passed += 1 if pl.get("verdict") == "passed" else 0
        # the task's very first round: a retry after an escalation numbers its rounds from 0 again, and that
        # later round 0 is not a first round (kernel/track.py counts the same way)
        if pl.get("round") == 0 and pl.get("task") not in first:
            first[pl["task"]] = pl.get("verdict") or "not measured"
    merged = {r["event"]["payload"]["task"] for r in project.ledger().of_kind("merged")}
    escalated = len(project.ledger().of_kind("escalated"))
    measured = [v for v in first.values() if v != "not measured"]
    n_passed = sum(1 for v in measured if v == "passed")
    return {"rounds": rounds, "rounds_passed": passed, "tasks_gated": len(measured),
            "first_round_passed": n_passed,
            "first_round_rate": (n_passed / len(measured)) if measured else None,
            "first_round_not_measured": len(first) - len(measured),
            "merged": len(merged), "escalated": escalated}


def floor(factory) -> dict:
    by_phase: defaultdict[str, Counter[str]] = defaultdict(Counter)
    runs, costs = [], []
    projects = []
    totals: Counter[str] = Counter()
    for project in factory.projects():
        if project.pid.startswith("_"):
            continue
        stage = project.meta.get("stage", 1)
        rows = cell(project)
        for r in rows:
            by_phase[f"{stage} {STAGES[stage]}"][r["verdict"]] += 1
        runs += rows
        costs += [r["cost"] for r in rows]
        g = gates(project)
        for k in ("rounds", "rounds_passed", "tasks_gated", "first_round_passed", "first_round_not_measured",
                  "merged", "escalated"):
            totals[k] += g[k]
        projects.append({"id": project.pid, "title": project.meta.get("title"), "stage": stage, "runs": len(rows),
                         "cells": len(project.ledger().of_kind("cell_ran")), "gates": g, **pass_rate(rows)})
    gate_total: dict[str, Any] = dict(totals)
    gate_total["first_round_rate"] = (totals["first_round_passed"] / totals["tasks_gated"]) if totals["tasks_gated"] else None
    return {"gates": gate_total, "by_phase": {k: dict(v) for k, v in sorted(by_phase.items())},
            "overall": pass_rate(runs), "harness_note": "harness outcomes of each Gnomon run: a builder cell in a "
            "grant-free lane has no verify of its own, so its outcome is not measured; the gate judges the work",
            "spend": spend(costs), "projects": projects}
