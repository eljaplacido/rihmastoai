"""What a move to another team changes in how a project reads (D-0027, FR-TM5): the words, and how much of the
project reads differently. A project's own words stay with it; the team it joins brings its words and the team it leaves
takes its own away. The preview names each word that would read differently and counts the records and nodes behind
them, as a change of words does (kernel/vocab_edit.py). It records nothing and rewrites nothing."""

from __future__ import annotations

from typing import Any

from kernel import vocab
from kernel.enforcement import count

SHOWN = 6                      # words named in a line; the rest are counted


def _said(row: dict[str, Any]) -> str:
    return "hidden" if row["hidden"] else str(row["label"])


def changed(factory: Any, project: Any, to: str) -> list[dict[str, Any]]:
    """The terms whose word, or whether they are hidden, would differ for the project in the team ``to``."""
    now = vocab.effective(factory, project)["terms"]
    then = vocab.effective(factory, project, to)["terms"]
    return [{"term": t, "type": t.split(":")[0], "from": _said(now[t]), "to": _said(then[t]),
             "means": then[t]["means"] or now[t]["means"]}
            for t in then if t in now and (_said(now[t]), now[t]["hidden"]) != (_said(then[t]), then[t]["hidden"])]


def lines(factory: Any, project: Any, to: str, to_name: str) -> tuple[list[str], dict[str, Any]]:
    """The preview's lines about the words, and what they name (``words``, ``records``, ``nodes``)."""
    from kernel.vocab_edit import _counts

    words = changed(factory, project, to)
    if not words:
        return ["No word changes: the project reads as it does now."], {"words": [], "records": 0, "nodes": 0}
    records = nodes = 0
    for w in words:
        r, n = _counts([project], w["term"], w["means"])
        records, nodes = records + r, nodes + n
    named = "; ".join(f"{w['from']} would read as {w['to']}" for w in words[:SHOWN])
    more = f" and {len(words) - SHOWN} more" if len(words) > SHOWN else ""
    return ([f"In {to_name}'s words: {named}{more}.",
             f"{count(records, 'record')} and {count(nodes, 'node')} read differently; nothing stored is rewritten."],
            {"words": words, "records": records, "nodes": nodes})
