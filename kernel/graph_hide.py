"""Hiding a kind of record in the Knowledge graph, whole (D-0027, FR-TM6): a team or a project may hide a term, and a
hidden kind then leaves the graph before anything is counted, so the counts, the issues and a focus agree with what is
drawn. Nothing stored is touched.

A warning is never lost silently: the governance warnings and critical findings that sit on hidden records are counted
and said (``hidden.issues``, ``hidden.note``) so a person who hid "requirement" is told that two requirements still have
no test, and a focus on a hidden record says it is hidden rather than that it is missing.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def hidden_kinds(eff: dict[str, Any]) -> set[str]:
    """The kinds (ontology ids, without ``kind:``) hidden in the words in force."""
    return {t[5:] for t, r in eff["terms"].items() if t.startswith("kind:") and r["hidden"]}


def _without(found: dict[str, Any], gone: set[str]) -> dict[str, Any]:
    """The collected graph with these nodes, the links that touch them and the names that pointed at them taken out."""
    return {**found, "nodes": {k: n for k, n in found["nodes"].items() if k not in gone},
            "edges": [e for e in found["edges"] if not {e["from"], e["to"]} & gone],
            "aliases": {a: k for a, k in found["aliases"].items() if k not in gone}}


def apply(found: dict[str, Any], hidden: set[str], focus: str = "") -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The collected graph without the hidden kinds, and what was left out (None when nothing was)."""
    gone = {k for k, n in found["nodes"].items() if n.get("kind") in hidden}
    if not gone:
        return found, None
    held = [found["nodes"][k] for k in gone]
    issues = Counter(i for n in held for i in n.get("issues") or [])
    return _without(found, gone), {"kinds": sorted({n["kind"] for n in held}), "nodes": len(gone),
                                   "issues": dict(issues),
                                   "focus_hidden": bool(focus) and found["aliases"].get(focus) in gone}


def noted(held: dict[str, Any] | None, texts: dict[str, str], word: Any) -> dict[str, Any] | None:
    """The left-out records in words: how many, and the warnings that still hold on them."""
    if held is None:
        return None
    warns = sum(held["issues"].values())
    said = [f"{n} · {texts[i]}" for i, n in held["issues"].items() if i in texts]
    n, kinds = held["nodes"], ", ".join(word(k) for k in held["kinds"])
    note = f"{n} record{'s' if n != 1 else ''} of a hidden kind ({kinds}) {'are' if n != 1 else 'is'} left out."
    if warns:
        note += f" {warns} warning{'s' if warns != 1 else ''} still hold{'' if warns != 1 else 's'} on them."
    return {**held, "warnings": warns, "said": said, "note": note}


def warnings_on(projects: list[Any], kinds: set[str]) -> int:
    """How many warnings and critical findings sit on records of these kinds in these projects, now."""
    from kernel import graph_view

    total = 0
    for p in projects:
        try:
            found = graph_view.collected(p)
        except (OSError, ValueError, KeyError):
            continue
        total += sum(len(n.get("issues") or []) for n in (found or {"nodes": {}})["nodes"].values()
                     if n.get("kind") in kinds)
    return total
