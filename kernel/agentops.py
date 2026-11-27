"""Agent operations: what each agent role costs, how fast it answers and how much it is given (FR-AOP1).

The owner (2026-11-25): "one clear view would also have to be like not developer but AI architect ... observe the
performance of agents ... token usage, context drift, latency in tool usage, the harness overhead and whatever we
measure by Gnomon ... run audits for the agentic operations in a platform and per project context to assess ways to
optimize context, tool usage, token usage efficiency, costs".

Read from the records only, for one project or for every project the person sees (Rihmasto's own canon too), over
a window:

- **runs**: each agent run the ledgers hold (Gnomon's builder cells ``gnomon_run``, another runner's ``runner_run``,
  every other role's ``model_run``, a coding agent's run through its harness), read as Insights reads them
  (kernel/insights/gnomon_records.py): role, harness, model, tokens in, out and cached, priced cost, seconds and
  tool calls;
- **by role** (with harness and model), **by project**, **role x project** (the heatmap) and **per day**;
- **tools**: each tool's calls, failures and latency from Gnomon's own audit trails in the lanes
  (kernel/agentops_more.py);
- **overhead**: what the harness adds to every call (the lane's system prompt in each role's context pack), the
  model calls per run, the share served from the prompt cache and Gnomon's trims;
- **context**: each role's context pack against its budget with the compression audit's findings
  (kernel/context_audit.py), and Gnomon's own context cost and metrics evals when they ran;
- **drift**: how fresh what each role was last given is, against the records written since it ran;
- **hub**: the agent observability hub's figures a person recorded (``agent_sessions_observed``, FR-OBS1).

A figure with nothing behind it is None, with why and how to measure it, never zero. Reading writes nothing.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from kernel.insights import gnomon_records as gr
from kernel.insights.base import WINDOW_WORDS, Scope, obj, share, stamp, when

SCHEMA = "rihmasto.agent-ops/1"
MAX_RUNS = 400
NOT_RECORDED = "not recorded"
ROLE_WORDS = {"holdout_author": "holdout author", NOT_RECORDED: NOT_RECORDED}
# What changes what an agent is given: a role that ran before these were written works from an older picture.
CHANGE_KINDS = ("spec_written", "contract_compiled", "card_decided", "question_answered", "assumption_made",
                "change_submitted", "merged", "material_added", "alignment_accepted")
HOW_RUNS = ("build a task, run the intake, a gate or Ask Rihma on a project: every agent run is recorded in its "
            "ledger with its role, harness, model, tokens and time, and counted here")
# What a person reads (FR-AOP2): what to do, in the cockpit or by asking Rihma, never a file of the installation.
HOW_PRICE = ("give each model its price per million tokens with Price a model on Agent operations, or ask Rihma "
             "\"set the price of <model> to <in> and <out> per million tokens\" (a model that runs on your own "
             "machine is marked local and costs no API money); a coding agent's run is priced by the cost the "
             "coding agent reports")
HOW_SECONDS = ("a run through Rihma's roles or a coding agent records how long it took; Gnomon's builder runs are "
               "timed once Rihmasto keeps the duration Gnomon reports for each run")
HOW_HUB = ("turn on Agent observability for a project (Settings, Modules) and press Record what the hub shows on its "
           "Agent sessions view, or let the agent_snapshot automation record it")
Row = dict[str, Any]


def number(value: Any) -> float | None:
    """A count or an amount, or None: never a bool, never negative."""
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    return float(value) if ok else None


def _seconds(payload: dict[str, Any]) -> float | None:
    """How long the run took; a duration of zero is not a measurement (a stand-in that called no model records
    0.0 s), so it is None, never 0 ms (FR-AOP3)."""
    s = number(payload.get("seconds"))
    if s is None:
        ms = number(payload.get("duration_ms")) or number(obj(payload.get("volatile")).get("duration_ms"))
        s = ms / 1000 if ms is not None else None
    return round(s, 3) if s else None


def _harness(payload: dict[str, Any], run: Row) -> str:
    h = payload.get("harness")
    if isinstance(h, dict):
        h = h.get("name")
    return str(h) if isinstance(h, str) and h else str(run.get("runner") or NOT_RECORDED)


def _tokens(run: Row) -> int | None:
    return None if run["in"] is None and run["out"] is None else (run["in"] or 0) + (run["out"] or 0)


def run_rows(scope: Scope, prices: Row | None = None) -> list[Row]:
    """Each agent run in the window, newest last, as the view and its drill-down read it. A run recorded without a
    price is priced from the table as it is now (kernel/agentops_prices.py)."""
    from kernel import agentops_prices
    from kernel import agentops_runs as ar

    prices, out = prices or agentops_prices.load(scope.factory), []
    gates = ar.gates(scope)
    for p, t, payload, rec, kind in ar.events(scope):
        r = gr.run_of(p, t, payload, kind, prices)
        agentops_prices.reprice(r, prices)
        r.update(id=f"{p.pid}:{rec.get('seq')}", at=stamp(t), title=scope.title(p), seconds=_seconds(payload),
                 harness=_harness(payload, r), tools=gr.kind_count(r, "tool_call"), tokens=_tokens(r),
                 role=r["role"] or NOT_RECORDED, model=r["model"] or NOT_RECORDED,
                 gate=gates.get((p.pid, int(rec.get("seq") or 0))), stand_in=ar.stand_in(r))
        r.pop("kinds", None)
        out.append(r)
    return out


def _sum(rows: list[Row], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals), 6) if vals else None


def quantile(values: list[float], q: float) -> float | None:
    vs = sorted(values)
    return round(vs[min(len(vs) - 1, int(round(q * (len(vs) - 1))))], 3) if vs else None


def _cost(rows: list[Row]) -> Row:
    """Priced runs summed; one run without a price makes the total not measured, with the priced part beside it."""
    priced = [r["cost"] for r in rows if r.get("cost") is not None]
    unpriced = len(rows) - len(priced)
    part = round(sum(priced), 6) if priced else None
    currency = next((r["currency"] for r in rows if r.get("currency")), "USD")
    untokened = sum(1 for r in rows if r.get("cost") is None and r.get("tokens") is None)
    return {"cost": part if rows and not unpriced else None, "cost_priced": part, "unpriced": unpriced,
            "untokened": untokened, "currency": currency}


def aggregate(rows: list[Row]) -> Row:
    """The figures of a set of runs: tokens, cost, latency, tool calls, failures and the cache's share."""
    secs = [r["seconds"] for r in rows if r.get("seconds") is not None]
    cached, given = _sum(rows, "cached"), _sum(rows, "in")
    return {"runs": len(rows), "in": _sum(rows, "in"), "out": _sum(rows, "out"), "cached": cached,
            "tokens": _sum(rows, "tokens"), **_cost(rows), "seconds_median": quantile(secs, 0.5),
            "seconds_p90": quantile(secs, 0.9), "timed": len(secs),
            "failed": sum(1 for r in rows if r.get("verdict") == "failed"), "tool_calls": _sum(rows, "tools"),
            "gate_failed": sum(1 for r in rows if r.get("gate") == "failed"),
            "gated": sum(1 for r in rows if r.get("gate")),
            "calls": _sum(rows, "calls"), "trims": _sum(rows, "trims"),
            "cached_share": share(cached, given) if cached is not None and given else None}


def grouped(rows: list[Row], *keys: str) -> list[Row]:
    """The runs grouped by ``keys``, each group with its figures, the most tokens first."""
    groups: dict[tuple, list[Row]] = defaultdict(list)
    for r in rows:
        groups[tuple(r.get(k) or NOT_RECORDED for k in keys)].append(r)
    out = [dict(zip(keys, k, strict=True)) | aggregate(g) for k, g in groups.items()]
    for row in out:
        if "project" in row:
            row["title"] = next((r["title"] for r in groups[tuple(row[k] for k in keys)]), row["project"])
    return sorted(out, key=lambda r: (-(r["tokens"] or -1), -r["runs"]))


def heatmap(rows: list[Row], scope: Scope) -> Row:
    """Tokens and runs per role and project (one project: per role and day), for the heatmap and its table."""
    col_key = "project" if scope.pid is None else "day"
    for r in rows:
        r["day"] = (r["at"] or "")[:10] or NOT_RECORDED
    cells = grouped(rows, "role", col_key)
    cols = sorted({c[col_key] for c in cells})
    titles = {r["project"]: r["title"] for r in rows}
    return {"by": col_key, "rows": sorted({c["role"] for c in cells}),
            "cols": [{"key": c, "label": titles.get(c, c) if col_key == "project" else c[5:]} for c in cols],
            "cells": [{"role": c["role"], "col": c[col_key], "tokens": c["tokens"], "runs": c["runs"],
                       "cost": c["cost"], "seconds_median": c["seconds_median"]} for c in cells]}


def _bucket_of(axis: list, t: Any) -> int | None:
    return next((n for n, (a, b, _) in enumerate(axis) if t is not None and a <= t < b), None)


def trend(scope: Scope, rows: list[Row]) -> Row:
    """Per bucket of the window: tokens by role, the priced cost, and the median seconds of a run."""
    axis = scope.buckets()
    tokens: list[dict[str, float]] = [{} for _ in axis]
    cost: list[float | None] = [None] * len(axis)
    secs: list[list[float]] = [[] for _ in axis]
    for r in rows:
        i = _bucket_of(axis, when(r["at"]))
        if i is None:
            continue
        if r["tokens"] is not None:
            tokens[i][r["role"]] = tokens[i].get(r["role"], 0) + r["tokens"]
        if r.get("cost") is not None:
            cost[i] = round((cost[i] or 0) + r["cost"], 6)
        if r.get("seconds") is not None:
            secs[i].append(r["seconds"])
    roles = sorted({k for b in tokens for k in b})
    return {"roles": roles, "measured": bool(roles),
            "points": [{"at": stamp(a), "label": label, "tokens": tokens[i], "cost": cost[i],
                        "seconds_median": quantile(secs[i], 0.5)} for i, (a, _, label) in enumerate(axis)]}


def _changes(scope: Scope) -> dict[str, list[tuple[Any, str]]]:
    out: dict[str, list[tuple[Any, str]]] = defaultdict(list)
    for p, t, _, rec in scope.every(*CHANGE_KINDS):
        if t is not None:
            out[p.pid].append((t, rec["event"]["kind"]))
    return out


def _keep_latest(last: dict[tuple[str, str], tuple[Any, str]], key: tuple[str, str], t: Any, title: str) -> None:
    if t is not None and (key not in last or t > last[key][0]):
        last[key] = (t, title)


def _last_given(scope: Scope) -> dict[tuple[str, str], tuple[Any, str]]:
    """When each role last ran in each project, and when each coding agent was last handed the work."""
    last: dict[tuple[str, str], tuple[Any, str]] = {}
    for p, t, payload, rec in scope.every(*gr.RUN_KINDS, "cell_ran"):
        role = payload.get("role") or ("builder" if rec["event"]["kind"] == "cell_ran" else NOT_RECORDED)
        _keep_latest(last, (p.pid, str(role)), t, scope.title(p))
    for p, t, payload, _ in scope.every("agent_handoff"):
        _keep_latest(last, (p.pid, "handoff:" + str(payload.get("to") or "agent")), t, scope.title(p))
    return last


def drift(scope: Scope, rows: list[Row]) -> list[Row]:
    """Per project and role: when it last ran, and what was written since that it was not given."""
    changes, out = _changes(scope), []
    for (pid, role), (t, title) in _last_given(scope).items():
        since = [k for at, k in changes.get(pid, []) if at > t]
        kinds: dict[str, int] = defaultdict(int)
        for k in since:
            kinds[k] += 1
        out.append({"project": pid, "title": title, "role": role, "last_run": stamp(t),
                    "hours": round((scope.now - t).total_seconds() / 3600, 1), "changes_since": len(since),
                    "kinds": dict(kinds), "state": "behind" if since else "fresh"})
    return sorted(out, key=lambda r: (-r["changes_since"], -r["hours"]))


def hub(scope: Scope) -> Row:
    """The hub's figures a person last recorded for each project (FR-OBS1); not measured when none was."""
    latest: dict[str, Row] = {}
    for p, t, payload, _ in scope.every("agent_sessions_observed"):
        if payload.get("measured"):
            latest[p.pid] = {"project": p.pid, "title": scope.title(p), "at": stamp(t), **payload}
    if not latest:
        return {"measured": False, "why": "no figures of the agent observability hub were recorded", "how": HOW_HUB}
    by_harness: dict[str, float] = defaultdict(float)
    for s in latest.values():
        for k, n in obj(s.get("by_harness")).items():
            by_harness[k] += number(n) or 0
    rows = [{"project": s["project"], "title": s["title"], "at": s["at"], "sessions": s.get("sessions"),
             "unrecovered": len(s.get("unrecovered_sessions") or []), "rework_files": len(s.get("rework_heavy") or []),
             "contract_first_rate": s.get("contract_first_rate"), "chain_valid": s.get("chain_valid")}
            for s in latest.values()]
    return {"measured": True, "by_harness": dict(by_harness), "projects": rows,
            "sessions": sum(number(r["sessions"]) or 0 for r in rows),
            "unrecovered": sum(r["unrecovered"] for r in rows), "rework_files": sum(r["rework_files"] for r in rows)}


def _unpriced_why(totals: Row) -> str:
    """Why runs have no cost: a model without a price, or runs that recorded no tokens (no price would help)."""
    blind, n = totals.get("untokened") or 0, totals["unpriced"]
    if blind >= n:
        return f"{n} of {totals['runs']} runs recorded no token counts, so no price can measure their cost"
    if blind:
        return (f"{n - blind} of {totals['runs']} runs have no price for their model, and {blind} recorded no token "
                "counts")
    return f"{n} of {totals['runs']} runs have no price: their model is not in the price table"


def _gaps(totals: Row) -> list[Row]:
    gaps = []
    if not totals["runs"]:
        return [{"what": "agent runs", "why": "no agent run was recorded in the window", "how": HOW_RUNS}]
    if totals["unpriced"]:
        gaps.append({"what": "cost", "why": _unpriced_why(totals), "how": HOW_PRICE})
    if totals["timed"] < totals["runs"]:
        gaps.append({"what": "latency", "why": f"{totals['runs'] - totals['timed']} of {totals['runs']} runs did not "
                     "record how long they took (a stand-in's zero seconds is not a measurement)",
                     "how": HOW_SECONDS})
    if totals["tokens"] is None:
        gaps.append({"what": "tokens", "why": "no run in the window recorded token counts", "how": HOW_RUNS})
    return gaps


def scope_of(factory: Any, pid: str | None, window: str) -> Scope:
    """The read's scope: one project, or every project the person sees with Rihmasto's own canon."""
    from kernel.learn import factory_project

    scope = Scope(factory, pid=pid, window=window)
    if pid is None:
        own = factory_project(factory, create=False)
        if own is not None and own.path("project.json").exists():
            scope.projects.append(own)
    return scope


def build(factory: Any, *, pid: str | None = None, window: str = "30d", context: bool = True) -> Row:
    """The Agent operations read model of one project or of the platform."""
    from kernel import agentops_more as more
    from kernel import agentops_prices

    scope = scope_of(factory, pid, window)
    prices = agentops_prices.load(factory)
    rows = run_rows(scope, prices)
    totals = aggregate(rows)
    audit = more.audit(factory, scope, rows) if context else None
    tools = more.tools(rows)
    return {"schema": SCHEMA, "scope": scope.scope, "project": pid, "window": window,
            "window_words": WINDOW_WORDS[window], "since": stamp(scope.since), "until": stamp(scope.now),
            "projects": [{"project": p.pid, "title": scope.title(p)} for p in scope.projects],
            "totals": totals, "gaps": _gaps(totals) + more.tool_gaps(tools), "how_runs": HOW_RUNS,
            "by_role": grouped(rows, "role", "harness", "model"), "by_project": grouped(rows, "project"),
            "heatmap": heatmap(rows, scope), "trend": trend(scope, rows), "tools": tools,
            "overhead": more.overhead(rows, audit), "context": more.context(factory, scope, audit),
            "drift": drift(scope, rows), "hub": hub(scope), "runs": list(reversed(rows))[:MAX_RUNS],
            "runs_total": len(rows), "pricing": agentops_prices.summary(factory, rows, prices),
            "_audit": audit, "_rows": rows, "_prices": prices}


def public(view: Row) -> Row:
    """The read model without what only the audit's rules read."""
    return {k: v for k, v in view.items() if not k.startswith("_")}
