"""The agent runs Agent operations reads from a ledger, with the gate each fed (FR-AOP3, kernel/agentops.py).

A run is a ``gnomon_run`` (Gnomon's builder cell, ingested with its audit trail), a ``runner_run`` (another cell
runner) or a ``model_run`` (every other role). A builder round is also a ``cell_ran``: every round has one, whoever
ran it, and it names the model, the runner and the tool steps. A ``cell_ran`` with no ``gnomon_run`` or
``runner_run`` of its own (Gnomon's record was not ingested, another runner or a stand-in ran it) is the builder's
run, so the main agent is never missing from the view. Its tokens were not recorded and stay None.

Each run also carries the verdict of the gate its work fed (``gate``): a builder round the gate of that round, a
verifier's answer on a task the next gate on that task. The run's own ``verdict`` is the call's outcome (it
answered or it failed); the gate's is whether the work passed.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from kernel.insights import gnomon_records as gr

CELL = "cell_ran"
GATE = "gate"
SCRIPTED = "scripted"
Row = dict[str, Any]


def _runner_name(payload: Row) -> str:
    runner = payload.get("runner")
    name = runner.get("name") if isinstance(runner, dict) else runner
    return str(name or "gnomon")


def cell_payload(payload: Row) -> Row:
    """A ``cell_ran`` in the shape of a run record: the builder, its model, runner and tool steps; no tokens."""
    steps = payload.get("tool_steps")
    counted = isinstance(steps, int) and not isinstance(steps, bool) and steps >= 0
    return {"task": payload.get("task"), "round": payload.get("round"), "role": "builder",
            "model": payload.get("final_model") or payload.get("model"), "runner": _runner_name(payload),
            "chain": {"kinds": {"tool_call": steps}} if counted else {},
            "cost": {"measured": False, "why": "the run recorded no token counts"},
            "verdict": "failed" if payload.get("bucket") == "apparatus_failure" else "passed"}


def _key(payload: Row) -> tuple[str, int]:
    rnd = payload.get("round")
    return str(payload.get("task")), rnd if isinstance(rnd, int) and not isinstance(rnd, bool) else 0


def events(scope: Any) -> Iterator[tuple[Any, Any, Row, Row, str]]:
    """(project, time, payload, record, kind) of each run in the window, a ``cell_ran`` without its own run record
    read as the builder's run (kind ``cell_ran``)."""
    covered: dict[tuple[str, str, int], int] = {}
    for p, t, payload, rec in scope.events(*gr.RUN_KINDS, CELL):
        kind = rec["event"]["kind"]
        key = (p.pid, *_key(payload))
        if kind in ("gnomon_run", "runner_run"):
            covered[key] = covered.get(key, 0) + 1
        if kind != CELL:
            yield p, t, payload, rec, kind
        elif covered.get(key):
            covered[key] -= 1
        else:
            yield p, t, cell_payload(payload), rec, CELL


def gates(scope: Any) -> dict[tuple[str, int], str]:
    """The gate verdict each run fed, by (project, record seq): a builder round's own gate, a verifier's answer
    on a task the next gate on that task."""
    out: dict[tuple[str, int], str] = {}
    for p in scope.projects:
        builder: dict[tuple[str, int], list[int]] = {}
        verifier: dict[str, list[int]] = {}
        for rec in scope.records(p):
            ev = rec["event"]
            kind, payload = ev.get("kind"), ev.get("payload") or {}
            if kind in (CELL, "gnomon_run", "runner_run"):
                builder.setdefault(_key(payload), []).append(int(rec.get("seq") or 0))
            elif kind == "model_run" and payload.get("role") == "verifier" and payload.get("task"):
                verifier.setdefault(str(payload["task"]), []).append(int(rec.get("seq") or 0))
            elif kind == GATE and payload.get("verdict"):
                verdict, key = str(payload["verdict"]), _key(payload)
                for seq in builder.pop(key, []) + verifier.pop(key[0], []):
                    out[(p.pid, seq)] = verdict
    return out


def stand_in(run: Row) -> bool:
    """A run a scripted stand-in answered (a test's or the demo's): no model was called."""
    return str(run.get("runner") or "") == SCRIPTED
