"""Usage: tokens, cost, tool calls, skills and memory of a project's agentic work, from the records.

Every figure comes from Gnomon's runs as the ledger holds them (``gnomon_run``, and a ``runner_run`` or
``model_run`` when a build records one) and from Gnomon's own trails in the lanes. A run without token counts
is not counted as zero tokens; a cost the price table cannot price makes the cost total not measured, with the
priced part said beside it (kernel/pricing.py's rule).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from kernel.insights import gnomon_records as gr
from kernel.insights.base import (
    PREVIOUS_WORDS,
    Scope,
    answer,
    chart,
    compact,
    delta,
    gap,
    series_rows,
    share,
    tile,
    unit_of,
)
from kernel.insights.lines import change, count, join, top

ROLES = ("analyst", "builder", "verifier", "holdout_author", "assistant")
ROLE_WORDS = {"holdout_author": "holdout author"}
HOW_RUNS = ("build a task (rihmasto build <pid>, or the pipeline): each builder cell's Gnomon run is ingested "
            "into the project's ledger with its tokens and priced cost")
NO_RUNS = "no model run in the window"
WHY_ROLES = ("no run of these roles was recorded in the window: builder cells are ingested as gnomon_run "
             "(kernel/dispatch.py), the analyst's, verifier's, holdout author's and assistant's runs as model_run "
             "(kernel/model_usage.py)")
HOW_ROLES = ("run the intake, the spec, the holdouts, a gate or Ask Rihma on the project: each run is recorded in its "
             "ledger with its role, model, tokens and duration, and counted here")
HOW_KINDS = "Gnomon's audit trail ([audit] enabled, chain = true, compiled into every lane) is counted at ingest"
HOW_FACES = ("serve a released capability (rihmasto capability serve <pid> --face mcp|http); calls to a running face "
             "are counted by your own gateway or observability tools, not here (D-0017)")
GROWTH = ("rose", "doubled", "-fold", "from none")
Row = dict[str, Any]


def _sum(rows: list[Row], key: str) -> int | None:
    vals = [r[key] for r in rows if r[key] is not None]
    return sum(vals) if vals else None


def _tokens(r: Row) -> int | None:
    return None if r["in"] is None and r["out"] is None else (r["in"] or 0) + (r["out"] or 0)


def _total(rows: list[Row]) -> int | None:
    vals = [t for r in rows if (t := _tokens(r)) is not None]
    return sum(vals) if vals else None


def _by(rows: list[Row], key: str, href: Any = None, names: dict[str, str] | None = None) -> list[Row]:
    """Tokens summed per value of ``key``, largest first; a group whose runs counted no tokens says so."""
    totals: dict[str, int] = defaultdict(int)
    runs: Counter[str] = Counter()
    for r in rows:
        name = str(r[key] or "not recorded")
        runs[name] += 1
        t = _tokens(r)
        if t is not None:
            totals[name] += t
    out = [{"label": (names or {}).get(k) or ROLE_WORDS.get(k, k), "value": totals.get(k), "sub": count(runs[k], "run"),
            "href": href(k) if href else None, "why": None if k in totals else "its runs recorded no token counts"}
           for k in runs]
    return sorted(out, key=lambda r: -(r["value"] if r["value"] is not None else -1))


def _many_rounds(rows: list[Row], at_least: int = 5) -> int:
    rounds: dict[tuple, int] = {}
    for r in rows:
        if r["task"] and isinstance(r["round"], int):
            key = (r["project"], r["task"])
            rounds[key] = max(rounds.get(key, 0), r["round"] + 1)
    return sum(1 for v in rounds.values() if v >= at_least)


def _context(scope: Scope) -> dict[str, Any]:
    rows, before = gr.runs(scope), gr.runs(scope, previous=True)
    return {"scope": scope, "rows": rows, "before": before, "period": PREVIOUS_WORDS.get(scope.window, ""),
            "why": "no model run recorded token counts in the window" if rows else NO_RUNS}


def _tokens_line(c: dict[str, Any], total: int | None, b_total: int | None) -> str | None:
    window = c["scope"].window
    builder = [r for r in c["rows"] if r["role"] == "builder"]
    builder_before = [r for r in c["before"] if r["role"] == "builder"]
    rose = change("Builder prompt tokens", _sum(builder, "in"), _sum(builder_before, "in"), window)
    many = _many_rounds(builder)
    if rose and many and any(w in rose for w in GROWTH):
        return join(rose, f"{count(many, 'task')} needed 5 or more rounds")
    plain = f"{compact(total)} tokens over {count(len(c['rows']), 'model run')}." if total is not None else None
    return rose or change("Tokens", total, b_total, window) or plain


def _t_tokens(c: dict[str, Any]) -> Row:
    total, b_total = _total(c["rows"]), _total(c["before"])
    return tile("tokens", "Tokens", total, unit="tokens",
                basis="ledger gnomon_run and model_run tokens.in + tokens.out", delta=delta(total, b_total, c["period"]), line=_tokens_line(c, total, b_total), why=c["why"],
                how=HOW_RUNS)


def _t_side(c: dict[str, Any], key: str, side: str, label: str) -> Row:
    now, before = _sum(c["rows"], side), _sum(c["before"], side)
    plain = f"{compact(now)} {label.lower()} over {count(len(c['rows']), 'model run')}."
    return tile(key, label, now, unit="tokens", basis=f"ledger gnomon_run and model_run tokens.{side}",
                delta=delta(now, before, c["period"]), line=change(label, now, before, c["scope"].window) or plain,
                why=c["why"], how=HOW_RUNS)


def _local_share(rows: list[Row]) -> float | None:
    total = _total(rows)
    local = _total([r for r in rows if r["hosting"] == "local"]) or 0
    return share(local, total) if total else None


def _t_local(c: dict[str, Any]) -> Row:
    value = _local_share(c["rows"])
    return tile("local_share", "On local models", value, unit="%",
                basis="tokens of runs priced as local (kernel/prices.json)",
                line=f"{value}% of the tokens ran on local models, which cost no API money.",
                why="no run with token counts, or none whose model the price table knows",
                how="name each model in kernel/prices.json, local ones with \"local\": true")


def _cost(rows: list[Row]) -> tuple[float | None, float, int, str]:
    """The cloud cost: None while any run has no price; the priced part, the unpriced runs and the currency."""
    priced = [r for r in rows if r["cost"] is not None]
    part = round(sum(r["cost"] for r in priced), 6)
    currency = next((r["currency"] for r in priced if r["currency"]), None) or "USD"
    unpriced = len(rows) - len(priced)
    return (None if unpriced or not rows else part), part, unpriced, currency


def _t_cost(c: dict[str, Any]) -> Row:
    cloud, part, unpriced, cur = _cost(c["rows"])
    bcloud = _cost(c["before"])[0]
    why = f"{count(unpriced, 'run')} had no price (the priced part is {part} {cur})" if c["rows"] else NO_RUNS
    how = "add each hosted model's input and output prices per million tokens to kernel/prices.json"
    plain = f"Cloud models cost {cloud:.4f} {cur} over {count(len(c['rows']), 'run')}." if cloud is not None else None
    return tile("cost", "Cloud cost", cloud, unit=cur, display=f"{cloud:.4f} {cur}" if cloud is not None else None,
                basis="ledger gnomon_run and model_run cost.amount, priced from kernel/prices.json",
                delta=delta(cloud, bcloud, c["period"]),
                line=change("Cloud cost", cloud, bcloud, c["scope"].window, cur) or plain,
                why=why, how=how if c["rows"] else HOW_RUNS)


def _t_runs(c: dict[str, Any]) -> Row:
    n, b = len(c["rows"]), len(c["before"])
    return tile("runs", "Model runs", n or None, basis="ledger gnomon_run and model_run events",
                delta=delta(n, b or None, c["period"]),
                line=change("Model runs", n, b or None, c["scope"].window) or f"{count(n, 'model run')} in the window.",
                why=NO_RUNS, how=HOW_RUNS)


def _kind_tile(c: dict[str, Any], key: str, label: str, kinds: tuple, basis: str, words: str) -> Row:
    counted = [n for r in c["rows"] if (n := gr.kind_count(r, *kinds)) is not None]
    value = sum(counted) if counted else None
    return tile(key, label, value, basis=basis, line=f"{compact(value)} {words} over {count(len(counted), 'run')}.",
                why="no run in the window recorded its audit kinds" if c["rows"] else NO_RUNS, how=HOW_KINDS)


def _t_skills(c: dict[str, Any]) -> Row:
    found = [s for p in c["scope"].projects if (s := gr.skills_on_main(p)) is not None]
    notes = sum(len(s) for s in found) if found else None
    return tile("skills_accepted", "Accepted skills", notes,
                basis="the .gnomon/skills/*.md files on each product's main",
                line=f"{count(notes or 0, 'learned note')} accepted on main across {count(len(found), 'product')}.",
                why="no product repository in this scope yet",
                how="compile and build a project: its repository holds the .gnomon/ surface Gnomon reads skills from")


def _tiles(c: dict[str, Any]) -> list[Row]:
    return [_t_tokens(c), _t_side(c, "prompt_tokens", "in", "Prompt tokens"),
            _t_side(c, "completion_tokens", "out", "Completion tokens"), _t_local(c), _t_cost(c), _t_runs(c),
            _kind_tile(c, "tool_calls", "Tool calls", ("tool_call",), "audit kind tool_call, counted at ingest",
                       "tool calls"),
            _kind_tile(c, "skills_used", "Skills used", ("skill_use",), "audit kind skill_use (Gnomon 0.6.6)",
                       "uses of learned skills"),
            _kind_tile(c, "compactions", "Compactions", gr.COMPACTION_KINDS, "audit kinds context_mask and checkpoint",
                       "context compactions and checkpoints"),
            _t_skills(c), _t_channel(c)]


def _t_channel(c: dict[str, Any]) -> Row:
    """Rihma's answers in the agent channel (kernel/channel_rihma.py): their runs and tokens."""
    rows = [r for r in c["rows"] if r.get("task") == "channel"]
    total = _total(rows)
    return tile("channel_tokens", "Rihma's channel answers", len(rows) or None, unit="answers",
                sub=f"{total} tokens" if total is not None else "tokens not recorded",
                basis="ledger model_run with task channel: Rihma answering agents",
                line=f"Rihma answered agents in the channel {count(len(rows), 'time')}"
                     + (f", with {total} tokens." if total is not None else "; no token counts were recorded."),
                why="Rihma answered no agent in the channel with a model in the window",
                how="ask @analyst or @verifier in a project's agent channel with a model set for those roles")


def _bars(c: dict[str, Any], key: str, title: str, field: str, basis: str, **kw: Any) -> Row:
    rows = _by(c["rows"], field, **kw)[:12]
    return chart(key, title, "bars", rows=rows, unit="tokens", basis=basis,
                 line=top("the " + title[0].lower() + title[1:], rows, "tokens"), why=NO_RUNS, how=HOW_RUNS)


def _over_time(c: dict[str, Any], line: str | None) -> Row:
    rows = c["rows"]
    points = [(r["at"], "prompt", r["in"]) for r in rows if r["in"] is not None]
    points += [(r["at"], "completion", r["out"]) for r in rows if r["out"] is not None]
    series = [{"key": "prompt", "label": "Prompt (input)"}, {"key": "completion", "label": "Completion (output)"}]
    return chart("tokens_over_time", "Tokens over time", "columns", rows=series_rows(c["scope"], points), unit="tokens",
                 series=series,
                 basis="ledger gnomon_run and model_run tokens, summed per " + unit_of(c["scope"].window), line=line,
                 why=c["why"], how=HOW_RUNS)


def _hosting(c: dict[str, Any], line: str | None) -> Row:
    split: Counter[str] = Counter()
    for r in c["rows"]:
        t = _tokens(r)
        if t is not None:
            split[r["hosting"] or "not in the price table"] += t
    keys = [k for k in ("local", "hosted", "mixed", "not in the price table") if k in split]
    return chart("hosting", "Local and hosted tokens", "stack100", unit="tokens",
                 rows=[{"label": "All runs", "values": dict(split)}] if split else [],
                 series=[{"key": k, "label": k.capitalize()} for k in keys],
                 basis="each run's cost kind, else the price table's local flag", line=line, why=c["why"], how=HOW_RUNS)


def _tools(c: dict[str, Any], found: dict[str, Any]) -> Row:
    tools: Counter[str] = Counter()
    for t in found["by_run"].values():
        tools.update(t["tools"] or {})
    rows = [{"label": k, "value": v} for k, v in tools.most_common(12)]
    return chart("tools", "Tool calls by tool", "bars", rows=rows, unit="calls",
                 basis="tool_call records in each run's own Gnomon trail (<lane>/.gnomon-audit/<session>.jsonl)",
                 line=top("the tool calls", rows, "calls"),
                 why="no run in the window has its Gnomon trail in the lanes" if c["rows"] else NO_RUNS,
                 how="keep the lanes' .gnomon-audit folders" if c["rows"] else HOW_RUNS)


def _served(scope: Scope) -> Row:
    faces: Counter[str] = Counter(str(pl.get("face") or "unnamed") for _, _, pl, _ in scope.events("capability_served"))
    rows = [{"label": k, "value": v} for k, v in faces.most_common()]
    return chart("faces", "Capability faces started", "bars", rows=rows, unit="starts",
                 basis="ledger capability_served: each time a capability's MCP, HTTP or embed face was started",
                 line=top("the faces started", rows), why="no capability face was started in the window",
                 how=HOW_FACES)


def _scoped(c: dict[str, Any]) -> Row:
    scope = c["scope"]
    if scope.pid is None:
        names = {p.pid: scope.title(p) for p in scope.projects}
        return _bars(c, "by_project", "Tokens by project", "project", "ledger gnomon_run and model_run per project",
                     href=lambda pid: f"#/p/{pid}/cell", names=names)
    return _bars(c, "by_task", "Tokens by task", "task", "ledger gnomon_run and model_run per task",
                 href=lambda t: f"#/p/{scope.pid}/tasks/{t}")


def _gaps(c: dict[str, Any], found: dict[str, Any]) -> list[Row]:
    seen = {r["role"] for r in c["rows"]}
    missing = [ROLE_WORDS.get(r, r) for r in ROLES if r not in seen]
    out = []
    if missing:
        out.append(gap("Tokens of the " + ", ".join(missing) + " role" + ("s" if len(missing) > 1 else ""),
                       WHY_ROLES, HOW_ROLES))
    if found["missing"]:
        out.append(gap(f"Which tools {count(found['missing'], 'run')} called",
                       "their Gnomon trails are no longer in the lanes (a lane keeps its trails across leases, "
                       "not forever)",
                       "keep the lanes' .gnomon-audit folders, or export each run's trail with gnomon audit show"))
    out.append(gap("Proposed skills (Gnomon's skills/proposed)",
                   "a proposal waits in the lane where the run wrote it, and a lane names no project",
                   "review proposals with gnomon skill list in the lane; an accepted one is counted on the "
                   "product's main"))
    out.append(gap("Calls to a running capability's MCP or API face",
                   "a face answers outside the ledger (it records that it was started, with its proof, not each call)",
                   "send the face's or your gateway's own metrics to your observability tools; the gateway's audit "
                   "(gateway/audit.py) counts each request it routed"))
    return out


def read(scope: Scope) -> dict[str, Any]:
    c = _context(scope)
    tiles = _tiles(c)
    found = gr.trails(c["rows"])
    charts = [_over_time(c, tiles[0]["line"]), _scoped(c),
              _bars(c, "by_role", "Tokens by role", "role", "ledger gnomon_run and model_run role"),
              _bars(c, "by_model", "Tokens by model", "model", "ledger gnomon_run and model_run model"),
              _bars(c, "by_endpoint", "Tokens by endpoint", "endpoint", "ledger gnomon_run and model_run endpoint"),
              _bars(c, "by_runner", "Tokens by runner", "runner",
                    "the run record's runner (Gnomon for a gnomon_run; another harness's runner_run names its own)"),
              _hosting(c, tiles[3]["line"]), _tools(c, found), _served(scope)]
    return answer(scope, "usage", tiles, charts, _gaps(c, found))
