"""Saying a text in the words in force (D-0027, FR-TM6): where Rihmasto's own text names a kind of record, it uses
the word the team or the project gave it.

The owner (2026-11-27): the word is used wherever a kind's name appears. The Knowledge graph's legend and the
glossary read the overlay (kernel/vocab.py); this carries it to the sentences that name a kind in passing: a graph
issue ("No test checks this requirement"), Ask Rihma's answers from the map ("requirements and criteria"), a
capsule. ``say`` replaces each shipped name of a kind that reads differently here, singular and plural, keeping the
capital letter; a hidden kind, a relation, an attribute and a custom term are left as they are. All names are
replaced in one pass, so a team that says "task" for one kind and "story" for another is never read twice. Nothing
stored is rewritten: only the text on its way out. The browser does the same for what it draws
(cockpit/static/wordsapply.js), over the same rows.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable
from typing import Any, ParamSpec

P = ParamSpec("P")


def _plural(word: str) -> str:
    if word.endswith("y") and not word.endswith(("ay", "ey", "oy", "uy")):
        return word[:-1] + "ies"
    return word + ("es" if word.endswith(("s", "x", "ch", "sh")) else "s")


def pairs(eff: dict[str, Any], hidden: bool = False) -> dict[str, str]:
    """Shipped name (lower case, singular and plural) -> the name in force, for each kind that reads differently here.
    A hidden kind keeps its shipped name unless ``hidden`` (a line about the records it left out names them as the
    person does)."""
    out: dict[str, str] = {}
    for tid, row in eff["terms"].items():
        old = str(((row.get("shipped") or {}).get("label")) or "").strip()
        new = str(row["label"]).strip()
        if tid.startswith("kind:") and old and new and (hidden or not row["hidden"]) and old.lower() != new.lower():
            out[old.lower()], out[_plural(old.lower())] = new, _plural(new)
    return out


def _case(found: str, new: str) -> str:
    if found.isupper() and len(found) > 1:
        return new.upper()
    if found[:1].isupper():
        return new[:1].upper() + new[1:]
    return new if new[1:] != new[1:].lower() else new.lower()        # a name with its own capitals (QA item) stays


def say(eff: dict[str, Any], text: str, hidden: bool = False) -> str:
    """``text`` with each kind named in the word in force; unchanged when no kind is redefined here."""
    swap = pairs(eff, hidden)
    if not swap or not text:
        return text
    names = "|".join(re.escape(n) for n in sorted(swap, key=len, reverse=True))
    return re.sub(rf"(?<![\w./-])(?:{names})(?![\w-]|\.\w)",
                  lambda m: _case(m.group(0), swap[m.group(0).lower()]), text, flags=re.IGNORECASE)


def in_words(factory: Any, out: dict[str, Any], project_id: str | None) -> dict[str, Any]:
    """An assistant answer from the map said in the words in force for the project it was asked in; the answers of a
    model, and the rule answers that quote a term's own line, are left as they are."""
    if out.get("by") != "map" or not out.get("answer"):
        return out
    try:
        project = factory.project(project_id) if project_id else None
    except KeyError:
        project = None
    return {**out, "answer": for_project(factory, project, str(out["answer"]))}


def in_words_of(ask: Callable[P, dict[str, Any]]) -> Callable[P, dict[str, Any]]:
    """The assistant's ``ask``, its answer from the map said in the words in force for the project it was asked in."""
    @functools.wraps(ask)
    def said(*args: P.args, **kw: P.kwargs) -> dict[str, Any]:
        return in_words(args[0], ask(*args, **kw), kw.get("project_id"))     # type: ignore[arg-type]
    return said


def for_project(factory: Any, project: Any, text: str) -> str:
    """``text`` in the words of the project's team and its own, or across projects those of the one team they share."""
    from kernel import vocab

    if factory is None:
        return text
    return say(vocab.effective(factory, project) if project is not None
               else vocab.context(factory, None, factory.projects()), text)
