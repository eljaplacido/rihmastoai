"""Agent operations' tools, overhead and context (FR-AOP1, kernel/agentops.py).

- **tools**: each tool an agent called, from Gnomon's own hash-chained audit trails in the lanes
  (``<lane>/.gnomon-audit/<session>.jsonl``, found by the run's session id as Insights finds them): calls, failures
  and, when the trail records a duration on a ``tool_call`` record, its latency. A run whose trail is gone counts its
  tool calls (the ledger's kinds) but not which tools; a trail without durations leaves latency not measured;
- **overhead**: what the harness adds to every call of a role. Gnomon's lane gives each role a system prompt
  before its context pack (kernel/context_parts.py ``system_part``): its share of what the role is given, with the
  model calls per run, the share served from the prompt cache and Gnomon's trims, from the runs;
- **context**: each role's context pack with its budget, the compression audit's findings (kernel/context_audit.py,
  without running commands) and the latest of Gnomon's own ``context_cost`` and ``metrics`` evals per project, with
  the role evals' scores per model (kernel/role_evals.py) that the Optimise rules read.

Only metadata is read: tool names, counts and durations, never a prompt, an answer or a tool's input.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from kernel.agentops import number, quantile
from kernel.insights import gnomon_records as gr
from kernel.insights.base import Scope

DURATION_MS = ("duration_ms", "elapsed_ms", "latency_ms", "ms")
DURATION_S = ("seconds", "duration_s", "elapsed_s")
GNOMON_EVALS = ("context_cost", "metrics")
MAX_AUDITED = 12
HOW_TRAILS = ("Gnomon keeps a tamper-evident audit trail of each run in the working lane Rihmasto prepares for it "
              "(turned on for every lane); a run's tools are read from it while the lane keeps it")
HOW_TOOL_TIME = ("Gnomon writes how long a tool call took into its trail when the coding agent reports it; once "
                 "it does, tool latency is measured here")
Row = dict[str, Any]


def _ms(rec: dict[str, Any]) -> float | None:
    for key in DURATION_MS:
        if (n := number(rec.get(key))) is not None:
            return n
    for key in DURATION_S:
        if (n := number(rec.get(key))) is not None:
            return n * 1000
    return None


def _failed(rec: dict[str, Any]) -> bool:
    return rec.get("ok") is False or bool(rec.get("error")) or rec.get("status") in ("error", "failed")


def _record(line: str) -> dict[str, Any] | None:
    try:
        rec = json.loads(line)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) and rec.get("kind") == "tool_call" else None


def read_tools(path: Path) -> dict[str, Row]:
    """One trail's tool calls by tool: calls, failures and the durations it recorded."""
    try:
        if path.stat().st_size > gr.MAX_TRAIL_BYTES:
            return {}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    out: dict[str, Row] = {}
    for line in lines:
        rec = _record(line)
        if rec is None:
            continue
        t = out.setdefault(str(rec.get("tool") or "unnamed")[:60], {"calls": 0, "failed": 0, "ms": []})
        t["calls"] += 1
        t["failed"] += int(_failed(rec))
        if (ms := _ms(rec)) is not None:
            t["ms"].append(ms)
    return out


def _tool_row(name: str, t: Row) -> Row:
    return {"tool": name, "calls": t["calls"], "failed": t["failed"], "runs": len(t["runs"]), "timed": len(t["ms"]),
            "median_ms": quantile(t["ms"], 0.5), "p90_ms": quantile(t["ms"], 0.9),
            "total_ms": round(sum(t["ms"]), 1) if t["ms"] else None, "run_ids": t["runs"][-50:]}


def _no_trail(r: Row) -> tuple[int, int]:
    """A run with tool calls whose trail is not found: (gone from the lanes, never had one: no session id)."""
    if not r.get("tools"):
        return 0, 0
    return (1, 0) if r.get("run") else (0, 1)


def tools(rows: list[Row], root: Path | None = None) -> Row:
    """Every tool the runs in the window called, from their trails; the runs whose trail is gone are counted."""
    by_tool: dict[str, Row] = {}
    missing = read = untrailed = 0
    for r in rows:
        path = gr.find_trail(r.get("run"), root) if r.get("run") else None
        if path is None:
            gone, never = _no_trail(r)
            missing, untrailed = missing + gone, untrailed + never
            continue
        read += 1
        for name, t in read_tools(path).items():
            acc = by_tool.setdefault(name, {"calls": 0, "failed": 0, "ms": [], "runs": []})
            acc["calls"] += t["calls"]
            acc["failed"] += t["failed"]
            acc["ms"] += t["ms"]
            acc["runs"].append(r["id"])
    out = sorted((_tool_row(k, v) for k, v in by_tool.items()), key=lambda x: -(x["median_ms"] or -1))
    calls = sum(n for r in rows if (n := r.get("tools")) is not None) if rows else 0
    return {"measured": bool(out), "tools": out, "trails_read": read, "trails_missing": missing,
            "untrailed": untrailed, "tool_calls": calls or None, "timed": any(t["timed"] for t in out)}


def tool_gaps(t: Row) -> list[Row]:
    if not t["measured"]:
        why = (f"{t['trails_missing']} runs called tools but their trails are gone from the lanes"
               if t["trails_missing"] else
               f"the tool calls of {t['untrailed']} runs are counted, but not which tools: no Gnomon audit trail "
               "names them (another runner or a stand-in ran them)" if t.get("untrailed") else
               "no Gnomon audit trail of a run in the window is in the lanes")
        return [{"what": "tools", "why": why, "how": HOW_TRAILS}]
    if not t["timed"]:
        return [{"what": "tool latency", "why": "the trails record no duration for a tool call", "how": HOW_TOOL_TIME}]
    return []


# -- the context packs and the compression audit ---------------------------------------------------------------

def _audited(scope: Scope, rows: list[Row]) -> list[Any]:
    """The products whose packs are read: one project's always; across the platform, those whose agents ran in the
    window, the busiest first (building every pack of every project would make the view slow)."""
    products = [p for p in scope.projects if not p.pid.startswith("_")]
    if scope.pid is not None:
        return products
    runs: dict[str, int] = defaultdict(int)
    for r in rows:
        runs[r["project"]] += 1
    return sorted((p for p in products if runs[p.pid]), key=lambda p: -runs[p.pid])[:MAX_AUDITED]


def audit(factory: Any, scope: Scope, rows: list[Row]) -> Row | None:
    """The compression audit of each product in the scope, with each pack kept for the Optimise rules. Building a
    pack writes nothing and asks no model; a project whose packs cannot be built is left out and said. A project's
    audit is kept while its files and main are unchanged (kernel/agentops_cache.py): the period does not change
    what a role is given, so switching it reads nothing again."""
    from kernel import agentops_cache as cache
    from kernel import context_audit as ca

    audits, skipped, chosen = [], [], _audited(scope, rows)
    for p in chosen:
        try:
            audits.append(cache.project_audit(factory, p))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            skipped.append({"project": p.pid, "why": f"{type(exc).__name__}: {str(exc)[:200]}"})
    return {"audits": audits, "skipped": skipped, "health": ca.health(audits) if audits else [],
            "read": [p.pid for p in chosen], "platform": scope.pid is None}


def packs(a: Row | None) -> list[Row]:
    """Every pack built, as (project, pack) rows with the system prompt's tokens beside the pack's own."""
    out = []
    for pa in (a or {}).get("audits") or []:
        for p in pa["_packs"]:
            system = p["with_system"]["tokens"] - p["tokens"]
            out.append({"project": pa["project"], "title": pa.get("title") or pa["project"], "pack": p["id"],
                        "label": p["label"], "role": p["role"], "tokens": p["tokens"], "system": system,
                        "with_system": p["with_system"]["tokens"], "budget": p["budget"]["tokens"],
                        "over_budget": p["over_budget"], "prefix_ratio": p["prefix"]["ratio"],
                        "shared_ratio": p["shared"]["ratio"]})
    return out


def overhead(rows: list[Row], a: Row | None) -> Row:
    """Per role: the system prompt's share of what it is given (the harness's own part), model calls per run, the
    share served from the cache and Gnomon's trims."""
    from kernel.agentops import aggregate

    by_role: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_role[r["role"]].append(r)
    given: dict[str, list[Row]] = defaultdict(list)
    for p in packs(a):
        if p["role"]:
            given[p["role"]].append(p)
    out = []
    for role in sorted(set(by_role) | set(given)):
        g, runs = given.get(role, []), by_role.get(role, [])
        agg = aggregate(runs)
        system = sum(p["system"] for p in g)
        whole = sum(p["with_system"] for p in g)
        out.append({"role": role, "runs": len(runs), "packs": len(g),
                    "system_tokens": round(system / len(g)) if g else None,
                    "system_share": round(system / whole * 100, 1) if whole else None,
                    "calls_per_run": round(agg["calls"] / len(runs), 2) if runs and agg["calls"] is not None else None,
                    "cached_share": agg["cached_share"], "trims": agg["trims"]})
    return {"roles": out, "measured": bool(out),
            "why": None if out else "no run and no context pack to measure in the window",
            "how": "build a project's request and spec, or run its agents: each role's pack and runs are read"}


def _eval_rows(scope: Scope) -> list[Row]:
    from kernel import gnomon_evals_run as ger

    out = []
    for p in scope.projects:
        try:
            latest = ger.latest(p)
        except (OSError, ValueError):
            continue
        for eid in GNOMON_EVALS:
            row = latest.get(eid)
            if row:
                out.append({"project": p.pid, "title": scope.title(p), "eval": eid, "label": row.get("label"),
                            "verdict": row.get("verdict"), "summary": row.get("summary"), "at": row.get("at"),
                            "scores": row.get("scores") or {}})
    return out


def role_scores(factory: Any) -> list[Row]:
    """The role evals' latest score per set and candidate (kernel/role_evals.py)."""
    from kernel import role_evals

    try:
        return [r for r in role_evals.latest(factory) if r.get("score_pct") is not None]
    except (OSError, ValueError, KeyError):
        return []


def context(factory: Any, scope: Scope, a: Row | None) -> Row:
    """The packs per role against their budgets, the audit's findings and Gnomon's own context evals."""
    if a is None:
        return {"measured": False, "why": "the context packs were not read for this view",
                "how": "open the Context view of a project", "packs": [], "findings": [], "evals": _eval_rows(scope),
                "roles": role_scores(factory)}
    findings = [f for pa in a["audits"] for f in pa["findings"]]
    counts: dict[str, int] = defaultdict(int)
    for f in findings:
        counts[f["kind"]] += 1
    rows = packs(a)
    return {"measured": bool(rows), "packs": rows, "health": a["health"], "findings": findings[:60],
            "counts": dict(counts), "skipped": a["skipped"], "evals": _eval_rows(scope),
            "roles": role_scores(factory), "read": a["read"], "platform": a["platform"],
            "why": None if rows else (
                "no agent ran in the window, so no project's packs were read" if a["platform"] and not a["read"]
                else "no context pack can be built yet: a project has no request or spec"),
            "how": "describe a project's request and write its spec: each role's pack is then built as it would be "
                   "sent; across the platform, the packs of the projects whose agents ran in the window are read"}
