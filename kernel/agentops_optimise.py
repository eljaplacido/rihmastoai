"""The Optimise audit of agent operations: concrete savings, by rule, from the records (FR-AOP1).

Each rule reads the Agent operations read model (kernel/agentops.py) and proposes one change with its expected
saving, what it rests on, and the place to make it (Take me there) or a change to file:

- ``context_cut``: a role's context pack is over its budget, says a long line twice, or carries the project's
  conventions to a role that does not need them. Saves the tokens cut per call, times the role's runs;
- ``reorder``: a part that changes often sits before parts that change less (kernel/context_parts.py
  ``violations``). Saves the tokens a prompt cache could reuse per call, times the runs;
- ``cache_prefix``: a role ran 3 or more times with under 20% of its input served from the cache while half or
  more of what it is given is a stable prefix. Saves the input tokens that prefix would have served from the cache;
- ``cheaper_model``: the role evals score a cheaper model within 2 points of the role's current one
  (kernel/role_evals.py). Saves the role's priced cost times the price difference;
- ``slow_tool``: a tool's median latency is 2 seconds or more over 3 or more timed calls. Saves the seconds above
  one second per call;
- ``retries``: a builder task needed 3 or more rounds. Saves the tokens of every round after the first.

A cost saving needs priced runs (kernel/prices.json): without them it is not measured, and the tokens saving stands
alone. Nothing here asks a model. Filing a proposal as a change (``file_change``) puts a change card in the
project's Inbox (the factory's own for a platform-wide one); recording the audit (``record``) keeps its proposals
and expected savings in the ledger, signed by the person who ran it.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from kernel.agentops import NOT_RECORDED, number

SLOW_MS = 2000
FAST_MS = 1000
MIN_RUNS = 3
CACHE_LOW = 20.0
PREFIX_HIGH = 0.5
NEAR_SCORE = 2.0
MANY_ROUNDS = 3
CACHED_WHY = "what a cached token saves is the endpoint's cached price, which the price table does not give"
KINDS = ("context_cut", "reorder", "cache_prefix", "cheaper_model", "slow_tool", "retries")
AUDITORS = ("ai_architect", "developer", "it", "operations", "compliance", "product_owner", "business_owner")
Row = dict[str, Any]


def _id(*parts: Any) -> str:
    return "OPT-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def _per_token(rows: list[Row]) -> float | None:
    priced = [r for r in rows if r.get("cost") is not None and r.get("tokens")]
    tokens = sum(r["tokens"] for r in priced)
    return sum(r["cost"] for r in priced) / tokens if tokens else None


def _saving(tokens: float | None, per_token: float | None, basis: str, **more: Any) -> Row:
    cost = round(tokens * per_token, 6) if tokens is not None and per_token is not None else None
    why = CACHED_WHY if more.get("cacheable") else "the role's runs are not priced"
    return {"tokens": round(tokens) if tokens is not None else None, "cost": cost, "basis": basis,
            "cost_why": None if cost is not None or tokens is None else why, **more}


def _proposal(kind: str, key: str, title: str, detail: str, saving: Row, act: Row, *, project: str | None = None,
              role: str | None = None, drill: Row | None = None) -> Row:
    return {"id": _id(kind, project, key), "kind": kind, "title": title, "detail": detail, "project": project,
            "role": role, "saving": saving, "act": act, "drill": drill or {}}


def _context_act(pid: str) -> Row:
    return {"route": f"#/p/{pid}/context", "control": "context_pack", "label": "Open the context pack"}


def _runs(rows: list[Row], pid: str, role: str | None) -> list[Row]:
    return [r for r in rows if r["project"] == pid and r["role"] == role]


def _cut_per_call(p: Row) -> list[tuple[str, int, str]]:
    """What can be cut from one pack per call: (why, tokens, how)."""
    from kernel import context_audit as ca
    from kernel import context_parts as cp

    out = []
    if p["over_budget"]:
        out.append(("over_budget", p["with_system"]["tokens"] - p["budget"]["tokens"], ca.PROPOSALS["over_budget"]))
    twice = sum(t["chars"] for t in ca.said_twice(p))
    if twice:
        out.append(("said_twice", cp.tokens(twice), ca.PROPOSALS["said_twice"]))
    if p["id"] not in ca.NEEDS_CONVENTIONS:
        conv = sum(x["chars"] for x in p["parts"] if x["kind"] == "conventions")
        if conv:
            out.append(("conventions_unneeded", cp.tokens(conv), ca.PROPOSALS["conventions_unneeded"]))
    return out


WHY_WORDS = {"over_budget": "is over its budget", "said_twice": "says long lines twice",
             "conventions_unneeded": "carries the project's conventions to a role that does not need them"}


def _one_pack(pid: str, p: Row, runs: list[Row]) -> list[Row]:
    """A pack's cuts and reorderings; the saving is per call times the role's runs (at most: not every run of the
    role sends this pack)."""
    from kernel import context_parts as cp

    n, ppt, out = len(runs), _per_token(runs), []
    where = {"project": pid, "role": p["role"], "drill": {"project": pid, "role": p["role"]}}
    for why, per_call, how in _cut_per_call(p):
        out.append(_proposal(
            "context_cut", f"{p['id']}:{why}", f"Cut the {p['label']} pack: it {WHY_WORDS[why]}",
            f"{per_call:,} tokens per call can go: {how}.",
            _saving(per_call * n if n else None, ppt, f"{per_call:,} tokens per call x {n} runs of its role, at most",
                    per_call=per_call), _context_act(pid), **where))
    for v in p["violations"]:
        per_call = cp.tokens(v["chars_behind"])
        out.append(_proposal(
            "reorder", f"{p['id']}:{v['part']}", f"Reorder the {p['label']} pack: move {v['part']} after "
            f"{', '.join(v['before'][:3])}", f"{v['part']} changes more often than the {len(v['before'])} part(s) "
            f"after it, so a prompt cache cannot reuse {per_call:,} tokens of each call.",
            _saving(per_call * n if n else None, None,
                    f"{per_call:,} cacheable tokens per call x {n} runs of its role, at most", per_call=per_call,
                    cacheable=True), _context_act(pid), **where))
    return out


def _pack_rules(view: Row) -> list[Row]:
    out = []
    for pa in (view.get("_audit") or {}).get("audits") or []:
        for p in pa["_packs"]:
            out += _one_pack(pa["project"], p, _runs(view["_rows"], pa["project"], p["role"]))
    return out


def _cache_rule(view: Row) -> list[Row]:
    from kernel.agentops import aggregate
    from kernel.agentops_more import packs

    # one proposal per project and role: the role's packs, their stable prefix weighted by their size
    given: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for p in packs(view.get("_audit")):
        if p["role"]:
            given[(p["project"], p["role"])].append(p)
    out = []
    for (pid, role), ps in given.items():
        weight = max(sum(p["with_system"] for p in ps), 1)
        ratio = round(sum(p["prefix_ratio"] * p["with_system"] for p in ps) / weight, 3)
        runs = _runs(view["_rows"], pid, role)
        agg = aggregate(runs)
        low = agg["cached_share"] is None or agg["cached_share"] < CACHE_LOW
        if len(runs) < MIN_RUNS or not agg["in"] or not low or ratio < PREFIX_HIGH:
            continue
        tokens = agg["in"] * ratio - (agg["cached"] or 0)
        if tokens <= 0:
            continue
        out.append(_proposal(
            "cache_prefix", role, f"Serve the {role}'s stable prefix from the prompt cache",
            f"{round(ratio * 100)}% of what the {role} is given (its {len(ps)} pack{'' if len(ps) == 1 else 's'}) "
            "is a stable prefix, but "
            f"{agg['cached_share'] or 0:g}% of its input came from the cache over {len(runs)} runs. Turn on prompt "
            "caching for its endpoint (Models), or keep the prefix byte-identical between calls.",
            _saving(tokens, None, f"{agg['in']:,.0f} input tokens x {ratio:g} prefix share, less what was cached",
                    cacheable=True), {"route": "#/models", "control": "models_set", "label": "Open Models"},
            project=pid, role=role, drill={"project": pid, "role": role}))
    return out


def _price(model: str, prices: Row) -> float | None:
    entry = (prices.get("models") or {}).get(model)
    if not isinstance(entry, dict):
        return None
    if entry.get("local"):
        return 0.0
    p_in, p_out = number(entry.get("input")), number(entry.get("output"))
    return (p_in + p_out) / 2 if p_in is not None and p_out is not None else None


def _best_score(scores: list[Row], role: str, model: str) -> float | None:
    got = [s["score_pct"] for s in scores if s["role"] == role and s["model"] == model]
    return max(got) if got else None


def _cheaper(scores: list[Row], role: str, model: str, prices: Row) -> Row | None:
    """The cheapest model the role evals score within NEAR_SCORE of the current one, when it is cheaper."""
    cur, cur_price = _best_score(scores, role, model), _price(model, prices)
    if cur is None or cur_price is None:
        return None
    found = []
    for s in scores:
        price = _price(s["model"], prices) if s["role"] == role and s["model"] != model else None
        if price is not None and price < cur_price and s["score_pct"] >= cur - NEAR_SCORE:
            found.append((price, -s["score_pct"], s))
    if not found:
        return None
    price, _, best = min(found, key=lambda x: (x[0], x[1]))
    return best | {"price": price, "current": cur, "current_price": cur_price}


def _model_rule(view: Row) -> list[Row]:
    from kernel.pricing import load_prices

    scores = (view.get("context") or {}).get("roles") or []
    prices = view.get("_prices") or load_prices()       # with the prices set in the cockpit (FR-AOP2)
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in view["_rows"]:
        if r["model"] != NOT_RECORDED:
            groups[(r["role"], r["model"])].append(r)
    out = []
    for (role, model), runs in groups.items():
        c = _cheaper(scores, role, model, prices)
        if c is None:
            continue
        cost = sum(r["cost"] for r in runs if r.get("cost") is not None) or None
        factor = 1 - c["price"] / c["current_price"]
        out.append(_proposal(
            "cheaper_model", f"{role}:{model}", f"Use {c['model']} for the {role}",
            f"On the role evals {c['model']} ({c['endpoint']}) scores {c['score_pct']:g}% against {model}'s "
            f"{c['current']:g}%, at {round(factor * 100)}% less per token.",
            {"tokens": None, "cost": round(cost * factor, 6) if cost else None, "currency": "USD",
             "basis": f"{len(runs)} runs' priced cost x {round(factor * 100)}% lower price",
             "cost_why": None if cost else "the role's runs are not priced"},
            {"route": "#/models", "control": "models_set", "label": "Set the role's model"},
            project=view.get("project"), role=role, drill={"role": role, "model": model}))
    return out


def _tool_rule(view: Row) -> list[Row]:
    out = []
    for t in (view.get("tools") or {}).get("tools") or []:
        if t["timed"] < MIN_RUNS or (t["median_ms"] or 0) < SLOW_MS:
            continue
        seconds = round((t["median_ms"] - FAST_MS) * t["timed"] / 1000, 1)
        out.append(_proposal(
            "slow_tool", t["tool"], f"{t['tool']} is slow: {t['median_ms'] / 1000:.1f} s per call",
            f"Its median is {t['median_ms'] / 1000:.1f} s (90th percentile {(t['p90_ms'] or 0) / 1000:.1f} s) over "
            f"{t['timed']} timed calls in {t['runs']} runs. Cache its answer, narrow what it reads, or replace it.",
            {"tokens": None, "cost": None, "seconds": seconds, "basis": "the seconds above one second per timed call",
             "cost_why": "a tool's time is not priced"},
            {"route": None, "control": "agent_ops_drill", "label": "See the runs"},
            project=view.get("project"), drill={"tool": t["tool"]}))
    return out


def _retry_rule(view: Row) -> list[Row]:
    tasks: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r in view["_rows"]:
        if r["role"] == "builder" and r.get("task") and isinstance(r.get("round"), int):
            tasks[(r["project"], r["task"])].append(r)
    out = []
    for (pid, task), runs in tasks.items():
        later = [r for r in runs if r["round"] > 0]
        if max(r["round"] for r in runs) + 1 < MANY_ROUNDS or not later:
            continue
        tokens = sum(r["tokens"] for r in later if r["tokens"] is not None) or None
        out.append(_proposal(
            "retries", f"{task}", f"{task} needed {max(r['round'] for r in runs) + 1} rounds",
            f"Every round after the first sent the builder the task again. Sharpen its acceptance criteria, split "
            f"it, or give the builder what the gate objected to up front; {len(later)} later rounds ran.",
            _saving(tokens, _per_token(later), f"the tokens of {len(later)} rounds after the first"),
            {"route": f"#/p/{pid}/tasks", "control": None, "label": "Open the task"},
            project=pid, role="builder", drill={"project": pid, "task": task}))
    return out


def _rank(p: Row) -> tuple:
    s = p["saving"]
    return (-(s.get("cost") or 0), -(s.get("tokens") or 0), -(s.get("seconds") or 0))


def proposals(view: Row) -> list[Row]:
    """Every rule's proposals for the view's scope, the largest expected saving first."""
    found = (_pack_rules(view) + _cache_rule(view) + _model_rule(view) + _tool_rule(view) + _retry_rule(view))
    titles = {p["project"]: p["title"] for p in view.get("projects") or []}
    for p in found:
        p["project_title"] = titles.get(p["project"]) if p["project"] else None
    return sorted(found, key=_rank)


def _total(found: list[Row], key: str) -> float | None:
    vals = [p["saving"].get(key) for p in found if p["saving"].get(key) is not None]
    return round(sum(vals), 6) if vals else None


def totals(found: list[Row]) -> Row:
    """What the proposals would save together, each kind of figure on its own (never mixed)."""
    kinds: dict[str, int] = defaultdict(int)
    for p in found:
        kinds[p["kind"]] += 1
    return {"proposals": len(found), "tokens": _total(found, "tokens"), "cost": _total(found, "cost"),
            "seconds": _total(found, "seconds"), "by_kind": dict(kinds)}
