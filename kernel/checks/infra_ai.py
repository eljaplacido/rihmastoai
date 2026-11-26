"""Infrastructure checks of a project's models and agents (FR-ITO1 with FR-CHK1).

- **ml**: the latest result of each Gnomon eval set that ran on the project (kernel/gnomon_evals_run.py; ``evals``
  narrows them) and its drift: the main score of the latest run against the median of the runs before it. Failed
  when the latest run failed, or the score moved the wrong way by more than ``drift_pct`` (10: points for a
  percentage, else per cent of the earlier figure). Not measured until an eval set has run;
- **agent**: the project's agent runs in the window (``window``, 7d; kernel/agentops.py reads the same
  ``model_run``, ``gnomon_run`` and ``runner_run`` records): the share of tool calls that failed, the cost per run
  and the share of runs that ended refused, each against its limit (``max_tool_error_pct`` 10, ``max_refusal_pct``
  10, ``max_cost_per_run`` when given). A figure no record carries is said not recorded, never zero.
"""

from __future__ import annotations

import statistics
from typing import Any

from kernel.checks import Check, Ctx, infra, not_measured, result
from kernel.checks import infra_targets as tg

REFUSED = ("refused", "refusal", "content_filter")


def _drift(ev: Any, rows: list[dict[str, Any]], limit: int) -> tuple[str | None, str]:
    key = ev.score
    figures = [r["scores"].get(key) for r in rows if isinstance((r.get("scores") or {}).get(key), (int, float))]
    if len(figures) < 2:
        return None, f"{ev.label}: {len(figures)} scored run(s), too few for drift"
    latest, earlier = float(figures[-1]), statistics.median(float(f) for f in figures[-6:-1])
    moved = latest - earlier if ev.unit == "%" else ((latest - earlier) * 100 / earlier if earlier else 0.0)
    worse = -moved if ev.higher_is_better else moved
    unit = " points" if ev.unit == "%" else "%"
    line = f"{ev.label}: {ev.score_label} {latest:g}{ev.unit} against {earlier:g}{ev.unit} before ({moved:+.1f}{unit})"
    return (f"{ev.label} drifted {worse:.1f}{unit} the wrong way (over {limit})" if worse > limit else None), line


def ml(ctx: Ctx) -> dict[str, Any]:
    from kernel import gnomon_evals as ge
    from kernel import gnomon_evals_run as gr

    wanted = tg.as_list(ctx.config.get("evals"))
    limit = infra.number(ctx, "drift_pct", 10)
    problems, lines, ran = [], [], []
    for ev in ge.CATALOGUE:
        if wanted and ev.id not in wanted:
            continue
        rows = gr.results(ctx.project, ev.id, 20)
        if not rows:
            continue
        ran.append(ev.id)
        last = rows[-1]
        lines.append(f"{ev.label}: latest {last.get('verdict')} at {last.get('at')}: {str(last.get('summary'))[:120]}")
        if last.get("verdict") == "failed":
            problems.append(f"{ev.label} failed its latest run")
        drifted, line = _drift(ev, rows, limit)
        lines.append(line)
        if drifted:
            problems.append(drifted)
    if not ran:
        return not_measured("no Gnomon eval set has run on this project yet: enable one under Eval sets and run it",
                            lines)
    if problems:
        return result("failed", "; ".join(problems), lines, evals=ran, remedy="ml")
    return result("passed", f"{len(ran)} eval set(s): latest results hold, no drift over {limit}", lines, evals=ran)


def _refused(payload: dict[str, Any]) -> bool:
    said = " ".join(str(payload.get(k) or "") for k in ("verdict", "stop_reason", "outcome", "refused")).lower()
    return bool(payload.get("refused")) or any(w in said for w in REFUSED)


def _tool_errors(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    calls, errors = payload.get("tool_calls"), payload.get("tool_errors")
    kinds = (payload.get("chain") or {}).get("kinds") if isinstance(payload.get("chain"), dict) else None
    if not isinstance(calls, int) and isinstance(kinds, dict):
        calls = int(kinds.get("tool_call") or 0)
        errors = int(kinds.get("tool_error") or 0) + int(kinds.get("tool_denied") or 0)
    ok = isinstance(calls, int) and not isinstance(calls, bool)
    return (calls, int(errors or 0)) if ok else (None, None)


def _tally(ctx: Ctx, window: str) -> dict[str, Any]:
    """The project's agent runs in the window: how many, tool calls and errors, refusals, and each priced cost."""
    from kernel import agentops_prices
    from kernel.insights import gnomon_records as gnr
    from kernel.insights.base import Scope

    scope = Scope(ctx.project.factory, pid=ctx.project.pid, window=window)
    prices = agentops_prices.load(ctx.project.factory)
    out: dict[str, Any] = {"runs": 0, "calls": 0, "errors": 0, "refused": 0, "costs": []}
    for p, t, payload, rec in scope.events(*gnr.RUN_KINDS):
        out["runs"] += 1
        c, e = _tool_errors(payload)
        out["calls"] += c or 0
        out["errors"] += e or 0
        out["refused"] += 1 if _refused(payload) else 0
        row = gnr.run_of(p, t, payload, rec["event"]["kind"], prices)
        agentops_prices.reprice(row, prices)
        if row.get("cost") is not None:
            out["costs"].append(float(row["cost"]))
    return out


def _cost_lines(ctx: Ctx, costs: list[float]) -> tuple[float | None, list[str], list[str]]:
    """The cost per run, its evidence and its problem against ``max_cost_per_run``."""
    per_run = round(sum(costs) / len(costs), 4) if costs else None
    cap = ctx.config.get("max_cost_per_run")
    if per_run is None:
        return None, ["cost per run: not recorded (give each model its price on Agent operations)"], []
    line = f"cost per run: {per_run} over {len(costs)} priced run(s)" + (f" (at most {cap})" if cap else "")
    try:
        over = cap not in (None, "") and per_run > float(str(cap))
    except ValueError:
        return per_run, [line, f"max_cost_per_run {cap!r} is not a number"], []
    return per_run, [line], [f"a run costs {per_run} on average (over {cap})"] if over else []


def agent(ctx: Ctx) -> dict[str, Any]:
    window = str(ctx.config.get("window") or "7d")
    n = _tally(ctx, window)
    runs, calls, errors, refused = n["runs"], n["calls"], n["errors"], n["refused"]
    if not runs:
        return not_measured(f"no agent run on this project in {window}: its agents have not run")
    max_err, max_ref = infra.number(ctx, "max_tool_error_pct", 10), infra.number(ctx, "max_refusal_pct", 10)
    lines, problems = [f"{runs} agent run(s) in {window}"], []
    pct = errors * 100 / calls if calls else None
    lines.append(f"tool errors: {errors} of {calls} tool calls ({pct:.1f}%, at most {max_err}%)" if pct is not None
                 else "tool errors: not recorded (no run kept its tool calls)")
    problems += [f"{pct:.0f}% of tool calls failed (over {max_err}%)"] if pct is not None and pct > max_err else []
    ref_pct = refused * 100 / runs
    lines.append(f"refusals: {refused} of {runs} runs ({ref_pct:.1f}%, at most {max_ref}%)")
    problems += [f"{ref_pct:.0f}% of runs were refused (over {max_ref}%)"] if ref_pct > max_ref else []
    per_run, cost_lines, cost_problems = _cost_lines(ctx, n["costs"])
    lines, problems = lines + cost_lines, problems + cost_problems
    data = {"runs": runs, "tool_calls": calls or None, "tool_errors": errors if calls else None,
            "refused": refused, "cost_per_run": per_run}
    if problems:
        return result("failed", "; ".join(problems), lines, remedy="agent", **data)
    return result("passed", f"{runs} run(s): tool errors, refusals and cost within limits", lines, **data)


CHECKS = (
    Check("ml", "Model evals and drift", "the latest result of each Gnomon eval set and its drift against the runs "
          "before", ml, options=("evals", "drift_pct"), every="7d"),
    Check("agent", "Agent runs", "the agents' tool-error rate, cost per run and refusals from their run records",
          agent, options=("window", "max_tool_error_pct", "max_refusal_pct", "max_cost_per_run"), every="1d"),
)
