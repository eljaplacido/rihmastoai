"""Ask Rihma what the Alignment's items are and what to do with them, by rule and from the real state (FR-STR2).

The owner's own words (2026-11-26): "Code plan highlights 124 to decide, how do I know what should I do with these
results?" and "are the tasks highlighted about enforcing rihmasto's own structure?". The answer is never a
description of the view: it is the project's own split (what is taken in from its files, what are facts about them,
what are Rihmasto's conventions at their levels, what is left to decide, what comes from files older than the
code) and the next steps in order, each opening the control it names. The assistant writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import structure_policy as sp
from kernel import structure_sides as sides
from kernel.insights.lines import count as _n

VIEW = "Code and plan match (Alignment)"
_DECIDE = re.compile(r"\bto decide\b")
_DECIDE_ABOUT = ("code plan", "code and plan", "alignment", "align", "highlight", "these results", "the results")
_HIGHLIGHT = re.compile(r"\bhighlight(?:s|ed|ing)?\b")
_HIGHLIGHT_ABOUT = ("task", "item", "decide", "structure", "rihma", "requirement", "gap")
_INGEST = re.compile(r"\b(?:ingest(?:s|ing|ed)?|tak(?:e|es|ing|en) in)\b")
_ENFORCING = re.compile(r"\benforc\w*\s+(?:the\s+)?rihmasto'?s?\s+(?:own\s+)?(?:structure|conventions?|way)\b")
_RESULTS = ("what should i do with these", "what do i do with these", "what should i do with the results",
            "what to do with these results")


def asks(low: str) -> bool:
    """Whether the question is about what the Alignment's items are, or what to do with them."""
    if _DECIDE.search(low) and any(w in low for w in _DECIDE_ABOUT):
        return True
    if _HIGHLIGHT.search(low) and any(w in low for w in _HIGHLIGHT_ABOUT):
        return True
    if _INGEST.search(low) and "structure" in low:
        return True
    return bool(_ENFORCING.search(low)) or any(w in low for w in _RESULTS)


def _out(answer: str, steps: list[dict[str, Any]], nav: dict[str, Any] | None) -> dict[str, Any]:
    return {"answer": answer, "steps": steps, "navigate": nav, "propose": [], "dropped": [], "sources": [],
            "by": "rule", "matches": ["structure_policy"]}


def _step(text: str, pid: str, control: str) -> dict[str, Any]:
    return {"text": text + " (Take me there opens it).", "action": "navigate", "route": f"#/p/{pid}/align",
            "control": control}


def answer(factory: Any, project: Any) -> dict[str, Any]:
    """The split and the next steps for a project's Alignment; where it does not apply, what to do instead."""
    from kernel import alignment_records as ar

    if project is None:
        return _out(f"Open a project first: {VIEW} is per project. It then says which items are taken in from the "
                    "project's own files and which are Rihmasto's own conventions.",
                    [{"text": "Open the project, then ask again: I answer from what its scan found."}], None)
    pid, title = project.pid, project.meta.get("title") or project.pid
    if not ar.applies(project):
        return _out(f"{title} is built by Rihmasto: its requirements, tasks and checks are its own structure, so "
                    f"nothing is taken in and {VIEW} does not apply. Its decisions wait in the Inbox.",
                    [{"text": "Ask 'where did the work go?' to see whether the time goes to development."}],
                    {"route": f"#/p/{pid}/overview", "control": "work_balance"})
    view = sp.follow_alignment(factory, project, ar.view(project))
    if not view.get("scanned"):
        return _out(f"Read the code first: {VIEW} has not read {title}'s repository yet, so nothing is found and "
                    "nothing waits on you. Reading it writes nothing there.",
                    [_step("Read the repository on " + VIEW, pid, "align_scan")],
                    {"route": f"#/p/{pid}/align", "control": "align_scan"})
    return _split(view, pid, title)


def _open(view: dict[str, Any], side: str) -> list[dict[str, Any]]:
    return [i for g in view["groups"] for i in g["items"] if i.get("counts_as") == side and not i.get("folded")
            and i["status"] in ("open", "changed")]


def _split(view: dict[str, Any], pid: str, title: str) -> dict[str, Any]:
    pol = view["policy"]
    taken = _open(view, "take_in")
    facts = _open(view, "fact")
    by_group = {gid: sum(1 for i in taken if i["group"] == gid) for gid, _, _ in sides.TAKEN_WORDS}
    said = ", ".join(_n(by_group[gid], one, many) for gid, one, many in sides.TAKEN_WORDS if by_group[gid])
    b = pol["by_level"]
    text = (f"On {VIEW} for {title}: {pol['line']} "
            + (f"The {said} are the project's own, read from its own files: taking them in keeps its structure as "
               "it is, not Rihmasto's structure. " if said else "")
            + (f"Rihmasto's own conventions are the trace links and gaps: {b['enforce']} enforced, {b['advise']} "
               f"advised as suggestions, {b['off']} hidden." if pol["split"]["conform"] else
               "None of what is open is one of Rihmasto's own conventions."))
    return _out(text, _steps(view, pid, taken, facts), {"route": f"#/p/{pid}/align",
                                                       "control": "align_bulk" if taken else "structure_policy"})


def _steps(view: dict[str, Any], pid: str, taken: list[dict[str, Any]], facts: list[dict[str, Any]]
           ) -> list[dict[str, Any]]:
    """The next steps in order, from what is open now: the project's own first, then Rihmasto's conventions."""
    return _own_steps(view, pid, taken, facts) + _convention_steps(view["policy"]["by_level"], pid) + [
        {"text": "Ask 'where did the work go?' to see whether your time goes to development or to Rihmasto's "
                 "structure."}]


def _own_steps(view: dict[str, Any], pid: str, taken: list[dict[str, Any]], facts: list[dict[str, Any]]
               ) -> list[dict[str, Any]]:
    """Older files first, then what is taken in, then the facts about the project's own files."""
    steps = []
    old = [i for i in taken + facts if (i.get("age") or {}).get("older")]
    if old:
        oldest = max(old, key=lambda i: i["age"]["days"])
        steps.append(_step(f"{_n(len(old), 'item')} of the project's own {'comes' if len(old) == 1 else 'come'} "
                           f"from files older than the newest code (the oldest, {oldest['age']['path']}, "
                           f"{oldest['age']['days']} days older): read those first and reject what no longer holds",
                           pid, "align_decide"))
    if taken:
        groups = [g for g in view["groups"] if any(i in g["items"] for i in taken)]
        big = max(groups, key=lambda g: sum(1 for i in taken if i in g["items"]))
        steps.append(_step(f"Accept what still holds of the {_n(len(taken), 'item')} taken in from the project's "
                           f"own files: Accept all open in a group at once, starting with {big['label']}", pid,
                           "align_bulk"))
    if facts:
        steps.append(_step(f"{_n(len(facts), 'fact')} about its own files ("
                           + "; ".join(i["title"] for i in facts[:3]) + "): accept to keep each as a gap, or "
                           "reject it", pid, "align_decide"))
    return steps


def _convention_steps(b: dict[str, int], pid: str) -> list[dict[str, Any]]:
    """Rihmasto's conventions by level: enforced ones to decide, advised and hidden ones need nothing."""
    steps = []
    if b["enforce"]:
        verb = "is" if b["enforce"] == 1 else "are"
        steps.append(_step(f"{_n(b['enforce'], 'item')} of Rihmasto's conventions {verb} enforced here: decide them "
                           "and their Inbox card, or set the convention to Advise in Rihmasto's structure", pid,
                           "structure_policy"))
    if b["advise"]:
        need = "needs" if b["advise"] == 1 else "need"
        steps.append({"text": f"{_n(b['advise'], 'suggestion')} of Rihmasto's conventions at Advise {need} nothing "
                              "from you: they are folded and never counted."})
    if b["off"]:
        steps.append({"text": f"{b['off']} hidden by Off: each group says who set it and why."})
    return steps
