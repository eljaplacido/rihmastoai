"""The Knowledge graph read through the words in force (D-0027, FR-TM6): its legend, its relation labels, the text of
its issues, what a hidden kind left out and, across projects, which words it reads in.

A project's graph reads in that project's words (its team's, then its own). The graph across projects has one set of
words: the team every project shown shares, else Rihmasto's shipped ones, and it says so when some of the projects
it shows say some words differently, so a person is never left to wonder why a word differs from the project they
just left.
"""

from __future__ import annotations

from typing import Any

from kernel import graph_hide, vocab, vocab_say
from kernel.learn import FACTORY_PID


def _reading(eff: dict[str, Any]) -> frozenset[tuple[str, str, bool]]:
    return frozenset((t, str(r["label"]), bool(r["hidden"])) for t, r in eff["terms"].items()
                     if r["scope"] != "shipped")


def mixed(factory: Any, projects: list[Any], eff: dict[str, Any]) -> dict[str, Any] | None:
    """Which projects shown read in other words than the page does, in words (None when they all agree)."""
    here = _reading(eff)
    mine = [p for p in projects if p.pid != FACTORY_PID]            # Rihmasto's own records are in no team
    apart = [p for p in mine if _reading(vocab.effective(factory, p)) != here]
    if not apart:
        return None
    reading = "team" if eff["team"] and here else "shipped"
    whose = "this team's words" if reading == "team" else "Rihmasto's shipped words"
    titles = ", ".join(str(p.meta.get("title") or p.pid) for p in apart[:4]) + (", and more" if len(apart) > 4 else "")
    return {"count": len(apart), "projects": [p.pid for p in apart], "reading": reading,
            "note": f"Read in {whose}. {len(apart)} of these {len(mine)} projects say some words differently "
                    f"({titles}): open one to read it in its own words."}


def relabel(view: dict[str, Any], eff: dict[str, Any], *, factory: Any = None,
            projects: list[Any] | None = None) -> dict[str, Any]:
    """``vocab.relabel`` plus the issue text in the words in force and the note on what a hidden kind left out; with
    ``projects`` (the page across projects) the note on projects that read in other words."""
    view = vocab.relabel(view, eff)
    texts: dict[str, str] = {}
    for key in ("issue_kinds", "issues"):
        for item in view.get(key) or []:
            texts.setdefault(item["id"], vocab_say.say(eff, str(item["text"]), hidden=True))   # about hidden records
            item["text"] = vocab_say.say(eff, str(item["text"]))
    view["hidden"] = graph_hide.noted(view.get("hidden"), texts, lambda k: vocab.label(eff, f"kind:{k}"))
    if projects is not None:
        view["vocabulary"]["mixed"] = mixed(factory, projects, eff)
    return view
