"""A factory home with records for Insights (FR-INS1), built in the test: two products, Gnomon runs with
chained audit trails in a lanes folder, gate rounds, decisions, a delegation's decision, a security scan and an
accepted risk, spread over time so that the windows cut them apart. One product has no record at all, so every
dimension also has figures that are not measured.

``build`` returns what the tests compare with: the tokens, costs and counts it wrote, so a test never re-derives
an expected number from the code under test.
"""

from __future__ import annotations

import json
from pathlib import Path

from adapters.gnomon_ingest import _hash, ingest
from kernel.canon import Canon

PRICES = {"currency": "USD", "models": {"hosted-large": {"input": 2.0, "output": 6.0}, "local-small": {"local": True}}}
SARIF = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Rihmasto red team (static)", "version": "1",
                                                           "rules": [{"id": "PY-SECRET-001"}, {"id": "PY-SQL-002"}]}},
                                       "results": [
    {"ruleId": "PY-SECRET-001", "level": "error", "message": {"text": "a hard-coded secret"},
     "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app/settings.py"}, "region": {"startLine": 3}}}]},
    {"ruleId": "PY-SQL-002", "level": "warning", "message": {"text": "string-built SQL"},
     "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app/db.py"}, "region": {"startLine": 9}}}]}]}]}


def trail(path: Path, records: list[dict]) -> Path:
    """A Gnomon audit trail, hash-chained as Gnomon chains it (adapters/gnomon_ingest.py verifies it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prev, lines = None, []
    for seq, rec in enumerate(records):
        body = dict(rec, seq=seq, prev=prev)
        body["hash"] = _hash(body)
        prev = body["hash"]
        lines.append(json.dumps(body))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def run(project, lanes: Path, session: str, *, model: str, endpoint: str, tokens: tuple[int, int], task: str,
        round_no: int, tools: list[str], window: int = 32768, trims: int = 0, peak: int = 1000,
        skills: int = 0, masks: int = 0, passed: bool = True) -> dict:
    """One builder run: its trail in a lane and its record ingested into the project's ledger."""
    recs = [{"kind": "session_start", "role": "builder"}, {"kind": "model_call", "model": model, "prompt_tokens": peak}]
    recs += [{"kind": "tool_call", "role": "builder", "tool": t, "target": "app"} for t in tools]
    recs += [{"kind": "skill_use", "skill": "lint-first"}] * skills + [{"kind": "context_mask", "dropped": 2}] * masks
    recs.append({"kind": "session_end", "turns": 1})
    path = trail(lanes / "lane-1" / ".gnomon-audit" / f"{session}.jsonl", recs)
    record = {"session": session, "role": "builder", "model": model, "endpoint": endpoint, "harness": "0.6.6",
              "bucket": "result", "code": 0, "stop_reason": "answered", "verify": "passed" if passed else "failed",
              "volatile": {"tokens_in": tokens[0], "tokens_out": tokens[1], "requests": 1},
              "counters": {"model_calls": {"window": window, "trims": {"leg": trims, "overflow": 0, "pre_call": 0,
                                                                      "dropped": trims}}}}
    return ingest(project, record, path, task=task, round_no=round_no, prices=PRICES)


def gate(project, task: str, round_no: int, verdict: str, *, tests: str = "passed", verifier: str = "passed",
         fail_first: str = "passed") -> None:
    project.log("gate", {"task": task, "round": round_no, "head": "abc", "verdict": verdict, "objections": [],
                         "signals": {"tests": tests, "trace": "passed", "fail_first": fail_first, "verifier": verifier}})


def build(factory, clock, lanes: Path) -> dict:
    """The home's records, written while the clock moves: ten days ago, three days ago, and the last hours."""
    clock.advance(days=-10)                 # the week before the 7-day window
    loans = factory.new_project("Equipment loans", mode="mixed", maturity="demo")
    quiet = factory.new_project("Quiet idea", mode="mixed", maturity="demo")
    run(loans, lanes, "task-old-1", model="hosted-large", endpoint="zen", tokens=(1000, 200), task="T-001",
        round_no=0, tools=["read"])
    gate(loans, "T-001", 0, "passed")
    clock.advance(days=7)                   # three days ago: inside 7d, outside 24h
    run(loans, lanes, "task-mid-1", model="hosted-large", endpoint="zen", tokens=(2000, 400), task="T-002",
        round_no=0, tools=["read", "bash", "bash"], trims=1, peak=30000, masks=1)
    gate(loans, "T-002", 0, "failed", tests="failed", verifier="passed", fail_first="failed")
    run(loans, lanes, "task-mid-2", model="local-small", endpoint="local", tokens=(3000, 600), task="T-002",
        round_no=1, tools=["write"], skills=2)
    gate(loans, "T-002", 1, "passed")
    loans.log("reflex_retry", {"task": "T-002", "round": 1, "why": "stall", "attempt": 2, "pause_seconds": 0})
    canon = Canon(loans)
    card = canon.card("approval", "Approve the plan", refs={"scope": "plan"})
    clock.advance(hours=5)
    canon.decide(card["id"], "approve", person="Aino Virtanen", persona="business_owner", reason="fits")
    clock.advance(days=2, hours=14)         # the last ten hours
    run(loans, lanes, "task-new-1", model="hosted-large", endpoint="zen", tokens=(4000, 800), task="T-003",
        round_no=0, tools=["read", "grep"])
    gate(loans, "T-003", 0, "passed", tests="passed", verifier="failed")
    canon.card("escalation", "T-003 needs a person", refs={"task": "T-003"})
    clock.advance(hours=2)
    from adapters import sarif
    from kernel.security import accept_risk

    path = factory.home / "scan.sarif"
    path.write_text(json.dumps(SARIF), encoding="utf-8")
    sarif.ingest(loans, path, person="Ilkka IT", persona="it")
    warning = next(f for f in __import__("kernel.security", fromlist=["findings"]).findings(loans)
                   if f["level"] == "warning")
    accept_risk(loans, warning["id"], person="Ilkka IT", persona="it", reason="internal only", expires="2026-12-20")
    return {"loans": loans, "quiet": quiet,
            # tokens in/out per window (the old run is ten days ago, the mid runs three days ago, the new one now)
            "tokens_24h": (4000, 800), "tokens_7d": (9000, 1800), "tokens_all": (10000, 2000),
            "cost_7d": round((2000 * 2 + 400 * 6 + 4000 * 2 + 800 * 6) / 1_000_000, 6),
            "cost_before_7d": round((1000 * 2 + 200 * 6) / 1_000_000, 6),
            "tools_7d": {"read": 2, "bash": 2, "write": 1, "grep": 1}, "gates_7d": 3, "passed_7d": 2}
