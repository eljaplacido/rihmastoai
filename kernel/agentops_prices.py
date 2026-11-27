"""Pricing a model from the cockpit or by asking Rihma (FR-AOP2).

"Cost not measured" turns into a figure once a model has a price per million tokens. The table shipped with
Rihmasto (kernel/pricing.py) is read first; the prices a person sets here are kept in the home
(``model_prices.json``) and win over it, so pricing a model never means editing the installation. Each one is
signed and recorded in Rihmasto's own ledger as ``model_price_set``.

A run recorded without a price is priced when it is read, from its tokens and the table as it is now (a harness's
own reported cost is kept as it is). A model that runs on the person's own machine is marked local: it costs no API
money, and its runs count as priced at zero.
"""

from __future__ import annotations

import math
import re
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import is_person
from kernel.store import read_json, updating_json

HOME_FILE = "model_prices.json"
MAX_PRICE = 10_000.0
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,99}\Z")
Row = dict[str, Any]


class PriceRefused(DecisionRefused):
    """A price refused: not a person, or a persona that does not audit agents."""


def _own(factory: Any) -> Row:
    got = read_json(factory.home / HOME_FILE, {}) if factory is not None else {}
    return got if isinstance(got, dict) else {}


def load(factory: Any) -> Row:
    """The price table: Rihmasto's own, with the prices set in this home over it."""
    from kernel import pricing

    base, own = pricing.load_prices(), _own(factory)
    models = dict(base.get("models") or {})
    models.update({k: v for k, v in (own.get("models") or {}).items() if isinstance(v, dict)})
    return {"currency": own.get("currency") or base.get("currency") or "USD", "models": models}


def reprice(run: Row, prices: Row) -> None:
    """Price a run read without a price, from its tokens and the table as it is now."""
    from kernel.pricing import price_run

    if run.get("cost") is not None or run.get("in") is None or run.get("out") is None:
        return
    got = price_run(run.get("model"), {"in": run["in"], "out": run["out"], "cached": run.get("cached")},
                    prices=prices)
    if got.get("measured"):
        run.update(cost=got["amount"], currency=got.get("currency") or prices.get("currency") or "USD",
                   cost_why=None, priced_now=True)


def _unpriced(runs: list[Row]) -> Row:
    """How many runs have no cost, and how many of them recorded no tokens (no price can measure those)."""
    unpriced = [r for r in runs if r.get("cost") is None]
    return {"unpriced": len(unpriced), "no_tokens": sum(1 for r in unpriced if r.get("tokens") is None)}


def summary(factory: Any, rows: list[Row], prices: Row) -> Row:
    """Every model the runs used and every model priced here: its price, and how many of its runs are unpriced."""
    from kernel.agentops import NOT_RECORDED
    from kernel.agentops_optimise import AUDITORS

    own = _own(factory).get("models") or {}
    used: dict[str, list[Row]] = {}
    for r in rows:
        if r.get("model") and r["model"] != NOT_RECORDED:
            used.setdefault(r["model"], []).append(r)
    out: list[Row] = []
    for model in sorted(set(used) | set(own)):
        entry = (prices.get("models") or {}).get(model) or {}
        runs = used.get(model, [])
        out.append({"model": model, "runs": len(runs), **_unpriced(runs),
                    "local": bool(entry.get("local")), "input": entry.get("input"), "output": entry.get("output"),
                    "cached": entry.get("cached"), "priced": bool(entry.get("local")) or (
                        entry.get("input") is not None and entry.get("output") is not None),
                    "set_by": (own.get(model) or {}).get("set_by"), "set_on": (own.get(model) or {}).get("set_on")})
    out.sort(key=lambda m: (-m["unpriced"], m["priced"], m["model"]))      # what needs a price first
    return {"models": out, "currency": prices.get("currency") or "USD", "who": list(AUDITORS)}


def _amount(value: Any, what: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"the {what} price is a number of the currency per million tokens") from None
    if isinstance(value, bool) or not math.isfinite(n) or n < 0 or n > MAX_PRICE:
        raise ValueError(f"the {what} price is between 0 and {MAX_PRICE:,.0f} per million tokens")
    return n


def entry_of(*, local: bool, input: Any, output: Any, cached: Any) -> Row:
    """The table's entry for what a person gave, checked."""
    if local:
        return {"local": True}
    p_in, p_out, p_cached = _amount(input, "input"), _amount(output, "output"), _amount(cached, "cached")
    if p_in is None or p_out is None:
        raise ValueError("a hosted model needs both its input and its output price per million tokens "
                         "(or mark it local)")
    return {"input": p_in, "output": p_out, **({"cached": p_cached} if p_cached is not None else {})}


def set_price(factory: Any, *, model: Any, person: str, persona: str, input: Any = None, output: Any = None,
              cached: Any = None, local: Any = False) -> Row:
    """Keep a model's price in the home, signed, and record it in Rihmasto's own ledger."""
    from kernel.agentops_optimise import AUDITORS
    from kernel.learn import factory_project

    if not is_person(person):
        raise PriceRefused(f"{person!r} is not a person: a price is set by a named person")
    if persona not in AUDITORS:
        raise PriceRefused(f"a {persona} does not price models; one of {', '.join(AUDITORS)} does")
    name = str(model or "").strip()
    if not _MODEL.match(name):
        raise ValueError("name the model as its runs name it (letters, digits and . _ : / @ + -)")
    entry = entry_of(local=local is True or str(local).lower() in ("true", "1", "yes"), input=input, output=output,
                     cached=cached)
    stamp = factory.clock.stamp()
    with updating_json(factory.home / HOME_FILE, {}) as kept:
        kept.setdefault("models", {})[name] = entry | {"set_by": person, "set_on": stamp}
    factory_project(factory).log("model_price_set", {"model": name, **entry, "person": person, "persona": persona})
    return {"model": name, "price": entry, "set_by": person, "set_on": stamp, "currency": load(factory)["currency"]}


def spend(factory: Any, window: str = "30d") -> Row:
    """Home's Spend from the same runs and price table as Agent operations (FR-AOP3): one run count and one price
    table across Home, Spend and Agent operations. A hosted run without a cost makes the cloud sum not measured."""
    from kernel import agentops

    prices = load(factory)
    rows = agentops.run_rows(agentops.scope_of(factory, None, window), prices)
    local = [r for r in rows if r.get("hosting") == "local"]
    cloud = [r for r in rows if r.get("hosting") != "local"]
    gaps = _unpriced(cloud)
    part = round(sum(r["cost"] or 0 for r in cloud), 6)
    return {"runs": len(rows), "cloud": None if gaps["unpriced"] or not rows else part, "cloud_measured_part": part,
            "unmeasured_runs": gaps["unpriced"], "untokened": gaps["no_tokens"],
            "local_tokens": sum(r["tokens"] or 0 for r in local) if rows else None,
            "currency": prices["currency"], "window": window, "window_words": agentops.WINDOW_WORDS[window]}
