"""What an Inbox card asks, in one plain line (FR-UXO1).

The owner (2026-11-24): "Inbox is very unclear, it's not clear where it's asking for comments." A card's
own title is written for the record ("T-003 did not pass its gate after 3 round(s)"); the person deciding
needs the question in plain words with its choices: "The task 'Show overdue loans first' failed its checks
3 times: retry it, accept it as it is, or stop it". ``plain(card, project)`` reads the facts the line needs
from the project's records (a task's title from its contract, a release's number from the card) and says
which choices the card offers. Reading it changes nothing; the cockpit shows it above the choices and keeps
the card's own title and refs under Details.
"""

from __future__ import annotations

import re
from typing import Any

# Each verdict as a verb phrase, so a line can end with its choices ("retry it, accept it as it is, or stop it").
VERBS = {
    "answer": "answer it", "assume": "let Rihma assume an answer", "approve": "approve it", "reject": "reject it",
    "accept": "accept it", "fix": "ask for a fix", "change": "ask for a change", "keep": "keep it as it is",
    "refuse": "refuse it", "acknowledge": "acknowledge it", "rollback": "roll back", "open_defect": "open a defect",
    "defer": "defer it", "retry": "retry it", "accept_as_is": "accept it as it is", "stop": "stop it",
    "configured": "say it is configured", "declined": "decline it", "granted": "grant it", "validate": "validate it",
    "park": "park it", "trial": "try it", "decline": "decline it", "product_defect": "say the product is wrong",
    "scenario_defect": "say the check is wrong", "go": "let it build", "skip": "build without your look",
    "enable": "turn it on",
}
_ROUNDS = re.compile(r"after (\d+) round")


def choices(verdicts: list[str]) -> str:
    """"retry it, accept it as it is, or stop it": the card's verdicts as one clause."""
    words = [VERBS.get(v, v.replace("_", " ")) for v in verdicts]
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " or " + words[-1]


def _task_title(project: Any, task_id: str) -> str:
    try:
        tasks = (project.read("contract.json") or {}).get("tasks") or []
    except (OSError, ValueError):
        return ""
    return next((str(t.get("title") or "") for t in tasks if isinstance(t, dict) and t.get("id") == task_id), "")


def _escalation(title: str, refs: dict[str, Any], project: Any) -> str:
    task = str(refs.get("task") or "")
    name = _task_title(project, task) if project is not None and task else ""
    m = _ROUNDS.search(title)
    times = f"{m.group(1)} time{'s' if m.group(1) != '1' else ''}" if m else "more than once"
    return f"The task '{name or task or 'this task'}' failed its checks {times}"


def _approval(title: str, refs: dict[str, Any]) -> str:
    if refs.get("scope") == "plan":
        return "The plan is ready, and nothing is built until a person approves it"
    if refs.get("scope") == "go_ahead":
        return f"{title.removeprefix('Go ahead: ') or 'This step'} waits for your go-ahead"
    return title


def _holdouts(title: str, refs: dict[str, Any]) -> str:
    n, rel = len(refs.get("criteria") or []), refs.get("release")
    if not rel:
        return title
    return f"{n} hidden check{'s' if n != 1 else ''} failed on release {rel}: is the product wrong, or the check"


# A release card: (with its number, without one).
_RELEASE = {"validation": ("Release {rel} is ready to try", "A release is ready to try"),
            "deploy_gate": ("Release {rel} waits to go live", "{title} waits to go live")}
# The kinds said by a pattern over their title; any other kind is its title.
_SAID = {"go_ahead": "The spec is written: have a look before it is built, or let it build",
         "incident": "Something went wrong in production: {title}", "change": "A change was asked: '{title}'",
         "concept": "A new need arrived: '{title}'"}


def _what(card: dict[str, Any], project: Any) -> str:
    kind, title = card.get("kind"), str(card.get("title") or "").strip()
    refs, payload = card.get("refs") or {}, card.get("payload") or {}
    if kind == "escalation":
        return _escalation(title, refs, project)
    if kind == "approval":
        return _approval(title, refs)
    if kind == "holdout_ruling":
        return _holdouts(title, refs)
    if kind in _RELEASE:
        rel = payload.get("release") or refs.get("release")
        return _RELEASE[kind][0 if rel else 1].format(rel=rel, title=title)
    return _SAID.get(str(kind), "{title}").format(title=title) or "A decision waits"


def plain(card: dict[str, Any], project: Any = None) -> str:
    """The card's question in one plain line with its choices, for the person who decides it."""
    verdicts = [str(v) for v in card.get("verdicts") or []]
    what = _what(card, project).rstrip(" .:")
    if card.get("kind") == "holdout_ruling" or not verdicts:
        return what + ("?" if card.get("kind") == "holdout_ruling" and not what.endswith("?") else "")
    if what.endswith("?"):      # a question already asks: its choices follow as their own sentence
        said = choices(verdicts)
        return f"{what} {said[:1].upper()}{said[1:]}."
    return f"{what}: {choices(verdicts)}"
