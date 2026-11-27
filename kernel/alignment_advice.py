"""The triage's plain answers to the owner's own questions about an alignment (FR-ORG2, docs/guides/alignment.md).

The owner (2026-11-26): "Do I just spend accepting changes that forces project to rihmasto structure or actually
moving the needle with dev." The triage head (kernel/alignment_triage.py) and Ask Rihma
(kernel/alignment_triage_chat.py) answer it by rule, from the real state:

- **development**: none of these decisions is development work; where development does move (Tasks, Changes) and
  where it would start here (the requirements with no test, the risks);
- **risks**: the conventions that can also be a real risk in the project (the CI does not run the tests, a criterion
  no test can observe) are named one by one and never deferred in bulk;
- **dangling**: a test trace to a criterion the person rejected cannot be counted;
- **what if**: "what happens if I accept all gaps?" is the impact of exactly that, before anything is done.

Nothing here writes anything.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.alignment_impact import _plural

Items = list[dict[str, Any]]


DEVELOPMENT = ("None of these decisions is development work: accepting records what your project already says and "
               "sets what Rihmasto measures, rejecting and deferring clear the list, and your code does not change. "
               "Development moves in Tasks and Changes, where a change is built, tested and released through the gate")


def development(s: dict[str, Items]) -> list[dict[str, Any]]:
    """The line that answers "am I moving the needle": these decisions are bookkeeping, and where work would start."""
    untested = [i for i in s["open"] + s["deferred"] if i.get("kind") == "no_test"]
    start = []
    if untested:
        start.append(f"the {_plural(len(untested), 'requirement')} with no test (Write a test for each requirement "
                     "with none, under the suggested changes)")
    if s["risk"]:
        start.append(f"the {_plural(len(s['risk']), 'possible risk')} named next")
    return [{"do": None, "about": "development", "text": DEVELOPMENT
             + (f"; here, development would start with {' and '.join(start)}." if start else ".")}]


def risks(items: Items) -> list[dict[str, Any]]:
    """The conventions that may be a real risk in the project, each named with why."""
    if not items:
        return []
    one = len(items) == 1
    named = "; ".join(f"{i['title']} ({i['origin']['risk']})" for i in items[:4])
    return [{"do": None, "about": "risk", "items": [i["id"] for i in items], "text": (
        f"Look at {'this one' if one else f'these {len(items)}'} yourself before deferring anything: "
        f"{'it' if one else 'each'} may be a real risk in your project, not only Rihmasto's bookkeeping: {named}"
        + (f" and {len(items) - 4} more" if len(items) > 4 else "")
        + f". Accept {'it' if one else 'each'} to keep it open, or defer it one by one; Defer convention items "
          "leaves it in the list.")}]


def dangling(items: Items) -> list[dict[str, Any]]:
    """Test traces to criteria a person rejected: they cannot be counted."""
    if not items:
        return []
    crits = list(dict.fromkeys(i["proposal"]["criterion_id"] for i in items))
    one = len(items) == 1
    return [{"do": None, "about": "dangling", "items": [i["id"] for i in items], "text": (
        f"{_plural(len(items), 'test trace')} point{'s' if one else ''} to "
        f"{'a criterion' if len(crits) == 1 else 'criteria'} you rejected ({', '.join(crits[:4])}): "
        f"{'it' if one else 'they'} cannot be counted, so Accept from current sources leaves "
        f"{'it' if one else 'them'} out. Reject {'it' if one else 'them'}, or Edit each to the criterion it checks.")}]


# -- Ask Rihma -------------------------------------------------------------------------------------------

NEEDLE = re.compile(r"\b(?:move|moving|moves) the needle\b|\bdevelopment work\b|\bactual(?:ly)? (?:dev|develop)\w*|"
                    r"\breal work\b|\bwith dev\b", re.I)
_VERB = re.compile(r"\b(accept|reject|defer)\w*\b", re.I)
_WHATIF = re.compile(r"\bwhat (?:happens|would happen|changes|does it do|would it do) if\b|\bif i (?:accept|reject|"
                     r"defer)\b|\bimpact of (?:accepting|rejecting|deferring)\b", re.I)
# the words for a part of the alignment: a group, or a set of the triage
PARTS: tuple[tuple[str, str, str], ...] = (
    (r"\bgaps?\b", "group", "gaps"), (r"\brequirements?\b", "group", "requirements"),
    (r"\bcriteri(?:a|on)\b", "group", "criteria"), (r"\btasks?\b", "group", "tasks"),
    (r"\b(?:test )?traces?\b|\btests\b", "group", "trace"), (r"\bdecisions?\b|\badrs?\b", "group", "decisions"),
    (r"\b(?:api )?contracts?\b", "group", "contracts"), (r"\bstale\b|\bold plan\b", "set", "stale"),
    (r"\bconventions?\b", "set", "convention"), (r"\bcurrent\b", "set", "current"),
)
GROUP_WORDS = {"gaps": "gap", "requirements": "requirement", "criteria": "criterion", "tasks": "task",
               "trace": "test trace", "decisions": "decision", "contracts": "API contract"}


def whatif(question: str) -> tuple[str, str, str] | None:
    """(verb, part kind, part) when the question asks what deciding a part would do; else None."""
    if not _WHATIF.search(question):
        return None
    verb = _VERB.search(question)
    part = next(((kind, name) for pat, kind, name in PARTS if re.search(pat, question, re.I)), None)
    if not verb or not part:
        return None
    return verb.group(1).lower(), part[0], part[1]


def whatif_items(view: dict[str, Any], kind: str, part: str) -> list[str]:
    """The open, not deferred items of a group, or a triage set's items."""
    if kind == "set":
        do = {"stale": "reject_stale", "convention": "defer_convention", "current": "accept_current"}[part]
        return next((a["items"] for a in view["triage"]["actions"] if a["do"] == do), [])
    return [i["id"] for g in view["groups"] if g["id"] == part for i in g["items"]
            if i["status"] == "open" and not i.get("deferred")]


def whatif_said(verb: str, kind: str, part: str, ids: list[str], impact: dict[str, Any] | None) -> str:
    what = (f"the {_plural(len(ids), 'open ' + GROUP_WORDS[part])}" if kind == "group" else
            f"the {_plural(len(ids), part + ' item')}")
    if not ids or impact is None:
        return f"There is nothing open to {verb} there now."
    return f"If you {verb} {what}: {impact['said']}"
