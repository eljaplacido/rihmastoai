"""Pricing every model call from a price table people keep (FR-L4).

A cloud model's cost is computed from its tokens and the table's prices. A local model costs
no API money; its tokens are counted as local spend, kept apart from cloud spend. A model
missing from the table, or a run without token counts, is **not measured**: its cost is None,
never zero, and sums that include it say so.
"""

from __future__ import annotations

from kernel.store import REPO_ROOT, read_json

PRICES_FILE = REPO_ROOT / "kernel" / "prices.json"


def load_prices(path=None) -> dict:
    return read_json(path or PRICES_FILE, {"models": {}}) or {"models": {}}


def price_run(model: str | None, tokens: dict, *, prices: dict | None = None) -> dict:
    table = (prices if prices is not None else load_prices()).get("models", {})
    entry = table.get(model) if model else None
    t_in, t_out = tokens.get("in"), tokens.get("out")
    if entry is None:
        return {"measured": False, "kind": None, "amount": None, "why": f"{model!r} is not in the price table"}
    if entry.get("local"):
        if t_in is None or t_out is None:
            return {"measured": False, "kind": "local", "amount": None, "why": "no token counts"}
        return {"measured": True, "kind": "local", "amount": 0.0, "local_tokens": t_in + t_out}
    p_in, p_out = entry.get("input"), entry.get("output")
    if p_in is None or p_out is None:
        return {"measured": False, "kind": "cloud", "amount": None, "why": f"{model!r} has no complete price"}
    if t_in is None or t_out is None:
        return {"measured": False, "kind": "cloud", "amount": None, "why": "no token counts"}
    cached = tokens.get("cached") or 0
    p_cached = entry.get("cached", p_in)
    amount = ((t_in - cached) * p_in + cached * p_cached + t_out * p_out) / 1_000_000
    return {"measured": True, "kind": "cloud", "amount": round(amount, 6),
            "currency": (prices or load_prices()).get("currency", "USD")}


def spend(costs) -> dict:
    """Sum run costs with local and cloud apart. Any unmeasured cloud run makes the cloud sum
    None (not measured); the count of unmeasured runs is reported beside it."""
    cloud, local_tokens, unmeasured = 0.0, 0, 0
    for c in costs:
        if not c or not c.get("measured"):
            unmeasured += 1
            continue
        if c["kind"] == "local":
            local_tokens += c.get("local_tokens", 0)
        else:
            cloud += c["amount"]
    return {"cloud": None if unmeasured else round(cloud, 6), "cloud_measured_part": round(cloud, 6),
            "local_tokens": local_tokens, "unmeasured_runs": unmeasured}
