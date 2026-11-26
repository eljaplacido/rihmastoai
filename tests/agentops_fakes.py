"""Agent runs with neutral, made-up figures for Agent operations' tests (FR-AOP1): what the ledgers hold after
Rihma's roles, Gnomon's builder cells and a coding agent ran, and a Gnomon audit trail with timed tool calls.

Nothing here is a real model's measurement: the models are named ``example-large`` and ``example-small`` and the
figures are chosen so each rule of the Optimise audit has something to find.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from kernel.store import FixedClock

PRICES = {"currency": "USD", "models": {"example-large": {"input": 3.0, "output": 15.0, "cached": 0.3},
                                        "example-small": {"input": 0.25, "output": 1.25}}}
SESSION = "sess-aop-0001"
TOOLS = [("read_file", 120), ("run_tests", 4200), ("run_tests", 3900), ("run_tests", 5100), ("search", 300)]


def _cost(model: str, t_in: int, t_out: int) -> dict[str, Any]:
    p = PRICES["models"][model]
    return {"measured": True, "kind": "cloud", "amount": round((t_in * p["input"] + t_out * p["output"]) / 1e6, 6),
            "currency": "USD"}


def model_run(role: str, model: str, t_in: int, t_out: int, seconds: float, *, task: str | None = None,
              verdict: str = "passed", cached: int | None = None) -> dict[str, Any]:
    """A ``model_run`` as kernel/model_usage.py writes it."""
    return {"run": None, "task": task, "role": role, "model": model, "endpoint": "example-endpoint",
            "runner": "gnomon", "tokens": {"in": t_in, "out": t_out, "cached": cached, "calls": 2},
            "cost": _cost(model, t_in, t_out), "context": {"window": 200000, "trims": {"pre_call": 1, "dropped": 0}},
            "seconds": seconds, "verdict": verdict}


def gnomon_run(task: str, rnd: int, t_in: int, t_out: int, *, run: str | None = None) -> dict[str, Any]:
    """A builder cell's ``gnomon_run`` as adapters/gnomon_ingest.py writes it (its chain counts the tool calls)."""
    return {"run": run or f"sess-{task}-{rnd}", "task": task, "round": rnd, "role": "builder",
            "model": "example-large", "endpoint": "example-endpoint", "harness": "gnomon",
            "chain": {"intact": True, "kinds": {"tool_call": 5, "model_call": 3}},
            "tokens": {"in": t_in, "out": t_out, "cached": 0, "calls": 3}, "context": {"window": 200000},
            "cost": _cost("example-large", t_in, t_out), "verdict": "failed" if rnd < 2 else "passed"}


def harness_run(t_in: int, t_out: int, usd: float, seconds: float) -> dict[str, Any]:
    """A coding agent's run through its harness, as kernel/harness_model.py ``record_run`` writes it."""
    return {"role": "verifier", "harness": "claude-code", "label": "Claude Code", "version": "1.0.0",
            "model": "example-large", "family": "example", "tokens": {"input": t_in, "output": t_out, "cache_read": 0},
            "cost_usd": usd, "seconds": seconds, "ok": True, "stop_reason": "end_turn", "assurance": "reported",
            "task": "T-001"}


def seed(project: Any, *, days: int = 6) -> None:
    """Agent runs spread over ``days`` days before the factory's clock, then the clock as it was."""
    factory = project.factory
    keep = factory.clock
    now = keep.now()
    factory.clock = FixedClock((now - dt.timedelta(days=days)).isoformat().replace("+00:00", "Z"))
    try:
        for d in range(days):
            factory.clock.advance(days=1)
            project.log("model_run", model_run("analyst", "example-large", 9000 + 800 * d, 1400, 11.5 + d))
            project.log("model_run", model_run("verifier", "example-large", 6000, 700, 7.0, task="T-001"))
            project.log("model_run", model_run("assistant", "example-small", 3000 + 200 * d, 300, 1.8))
        for rnd, t_in in enumerate((18000, 21000, 23000)):
            project.log("gnomon_run", gnomon_run("T-009", rnd, t_in, 2500, run=SESSION if rnd == 0 else None))
        project.log("model_run", harness_run(12000, 900, 0.06, 42.0))
    finally:
        factory.clock = keep


def trail(lanes: Path) -> Path:
    """A Gnomon audit trail for the first builder run, with timed tool calls (``GF_LANES`` points at ``lanes``)."""
    path = lanes / "lane-aop" / ".gnomon-audit" / f"{SESSION}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    recs = [{"seq": i, "kind": "tool_call", "tool": name, "duration_ms": ms, "ok": True}
            for i, (name, ms) in enumerate(TOOLS)]
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return path


def write_rows(case: Any, w: dict) -> list:
    """Agent operations' signed writes (cockpit/agentops_routes.py), for tests/test_brief_ln.py and test_access.py:
    the Optimise audit recorded on the built project, then its first proposal filed as a change, then a model
    priced."""
    b = w["built"]
    if not any((r["event"]["payload"] or {}).get("task") == "T-009" for r in b.ledger().of_kind("gnomon_run")):
        seed(b)
    return [
        ("post_agent_ops_audit", "POST", "/api/agent-ops/audit",
         lambda who, got: {"project": b.pid, "window": "all", "person": who, "persona": "developer"}),
        ("post_agent_ops_change", "POST",
         lambda got: f"/api/projects/{b.pid}/agent-ops/proposals/{got['post_agent_ops_audit']['proposals'][0]['id']}"
                     "/change",
         lambda who, got: {"window": "all", "person": who, "persona": "developer"}),
        # a model's price, kept in the home and recorded in Rihmasto's own ledger (FR-AOP2)
        ("post_agent_ops_price", "POST", "/api/agent-ops/prices",
         lambda who, got: {"model": "example-new", "input": 1, "output": 2, "person": who, "persona": "developer"}),
    ]
