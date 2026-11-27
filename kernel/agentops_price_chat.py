"""Ask Rihma prices a model, by rule (FR-AOP2): the chat path of Agent operations' Price a model.

- "set the price of <model> to 3 and 15 per million tokens" (in, then out; a third figure after "cached" is the
  cached price) and "mark <model> as local" are offered as the ``set_model_price`` operation, for the person to
  confirm (kernel/assistant_ops.py): Rihma itself writes nothing;
- "how do I price a model?" says how, with Take me there to the Prices card.

A persona that may not price a model is told who may.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import agentops_prices as prices

MODEL = r"(?P<model>[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,99})"
NUM = r"\d+(?:\.\d+)?"
SET = re.compile(r"\bprice (?:of|for) " + MODEL + r" (?:to|at|as|=)\b(?P<rest>.*)", re.I)
TOKENS = re.compile(r"\b(?:models?|tokens?|per million|million|mtok)\b|/ ?1?m\b", re.I)   # a model's price, not any
LOCAL = re.compile(r"\bmark " + MODEL + r" as (?:a )?local\b", re.I)
HOW = re.compile(r"\bhow (?:do|can|to) (?:i |we )?(?:price|set (?:the |a )?price (?:of|for)|add (?:a |the )?price "
                 r"(?:of|for|to))\b|\bprice (?:a|my|our) models?\b|\bwhere (?:do|can) (?:i|we) (?:set|add) "
                 r"(?:the |a )?(?:model )?prices?\b", re.I)


def parse(question: str) -> dict[str, Any] | None:
    """The price a question sets ({model, input, output, cached?} or {model, local}), "how", or None."""
    q = " ".join(question.split()).rstrip("?.! ")
    if m := LOCAL.search(q):
        return {"model": m["model"], "local": True}
    if (m := SET.search(q)) and TOKENS.search(q):
        figures = re.findall(NUM, m["rest"])
        if len(figures) < 2:
            return {"model": m["model"], "missing": True}
        out = {"model": m["model"], "input": float(figures[0]), "output": float(figures[1])}
        if len(figures) > 2 and re.search(r"\bcached?\b", m["rest"], re.I):
            out["cached"] = float(figures[2])
        return out
    return {"how": True} if HOW.search(q) else None


def _out(answer: str, *, propose: list | None = None) -> dict[str, Any]:
    return {"answer": answer, "navigate": {"route": "#/agentops", "control": "agent_ops_price"},
            "propose": propose or [], "dropped": [], "sources": [], "by": "map", "matches": ["agentops_all"]}


def _said(got: dict[str, Any], currency: str) -> str:
    if got.get("local"):
        return f"{got['model']} runs on your own machine: it costs no API money"
    cached = f", {got['cached']:g} cached" if got.get("cached") is not None else ""
    return (f"{got['model']} costs {got['input']:g} {currency} per million tokens in and {got['output']:g} out"
            f"{cached}")


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """The answer by rule, or None when the question does not price a model."""
    from kernel import assistant_ops
    from kernel.agentops_optimise import AUDITORS

    got = parse(question)
    if got is None:
        return None
    if got.get("how"):
        return _out("Price a model on Agent operations, in the Prices card: its price per million tokens in and "
                    "out, or mark it as running on your own machine. Or ask me: \"set the price of <model> to <in> "
                    "and <out> per million tokens\". Its runs' cost is then measured.")
    if got.get("missing"):
        return _out(f"Give {got['model']}'s price per million tokens in and out, for example \"set the price of "
                    f"{got['model']} to 3 and 15 per million tokens\", or say \"mark {got['model']} as local\".")
    try:
        prices.entry_of(local=bool(got.get("local")), input=got.get("input"), output=got.get("output"),
                        cached=got.get("cached"))
    except ValueError as exc:
        return _out(f"That price cannot be set: {exc}.")
    currency = prices.load(factory)["currency"]
    if persona not in AUDITORS:
        return _out(f"As {persona} you may not price a model; one of {', '.join(AUDITORS)} may. "
                    f"What it would say: {_said(got, currency)}.")
    args = {k: v for k, v in got.items() if k in ("model", "input", "output", "cached", "local")}
    op = assistant_ops.proposal(factory, "set_model_price", args, persona=persona, project=project,
                                summary=f"Set the price: {_said(got, currency)}")
    return _out(f"I can set this price: {_said(got, currency)}. Confirm below; it is kept for every project and "
                "the cost of its runs is measured from then on.", propose=[op] if op else [])
