"""Ask Rihma's "help" and "what should I do next?" on a project, for the persona asking (FR-JRN1, FR-DEV1).

The owner: Ask Rihma hand-holds with next steps from the real state, never describes the assistant to the person
already in it. Once a project's first journey is through, the answer is the persona's own, by rule:

- **what you can do now**: for a developer (or a person viewing everything) the development board's next step
  (kernel/devbrief.py), then the open cards this persona may decide;
- **who else must act**: the open cards only another persona decides, grouped by who decides them, once each;
- **Take me there**: the place for the first thing the person can do (the board, or the card in their Inbox).

One list of open cards gives every count, so the answer never says two different numbers. It writes nothing.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import Canon, deciders_of
from kernel.devbrief import may_decide, who_said

SHOWN = 4
BUILDERS = ("developer", "*")       # the personas whose next step is the development board's


def _label(persona: str | None) -> str:
    from kernel.assistant_rules import PERSONA_LABEL

    return "everything you hold" if persona in (None, "*") else PERSONA_LABEL.get(persona, persona)


def _card_said(c: dict[str, Any]) -> str:
    from kernel.card_words import plain

    try:
        said = plain(c)
    except (KeyError, TypeError, ValueError):
        said = str(c.get("title") or c["kind"])
    from kernel.start_here import SOURCE_TAG

    said = SOURCE_TAG.sub("", said)         # where it came from ("[embed E-001]") is the page's to say, not the line's
    said = said if len(said) <= 90 else said[:90].rsplit(" ", 1)[0].rstrip(" ,;:.") + "..."
    return f"{c['id']} ({said})"


def _others(cards: list[dict[str, Any]]) -> list[str]:
    """``C-0002 and C-0003 wait on the Business owner or Product owner``, one line per group of deciders."""
    groups: dict[tuple[str, ...], list[str]] = {}
    for c in cards:
        groups.setdefault(tuple(deciders_of(c)), []).append(c["id"])
    out = []
    for who, ids in groups.items():
        named = ", ".join(ids[:-1]) + " and " + ids[-1] if len(ids) > 1 else ids[0]
        out.append(f"{named} {'wait' if len(ids) > 1 else 'waits'} on {who_said(list(who))}")
    return out


def _dev_step(project: Any, persona: str | None) -> dict[str, Any] | None:
    if persona not in BUILDERS:
        return None
    from kernel.devboard import board
    from kernel.devbrief import next_step

    return next_step(board(project), persona)


def _now(step: dict[str, Any] | None, mine: list[dict[str, Any]]) -> list[str]:
    """What the person can do now: the board's step (unless it waits on someone else), then their own decisions."""
    now = [f"{step['title']} ({step['why']})"] if step is not None and not step.get("waits_for") else []
    if mine:
        more = f" and {len(mine) - SHOWN} more in your Inbox" if len(mine) > SHOWN else ""
        now.append("decide " + "; ".join(_card_said(c) for c in mine[:SHOWN]) + more)
    return now


def _route(pid: str, step: dict[str, Any] | None, mine: list[dict[str, Any]]) -> str:
    if step is not None and not step.get("waits_for"):
        return str(step["action"]["route"])
    if mine:
        return f"#/p/{pid}/inbox/{mine[0]['id']}"
    return f"#/p/{pid}/board" if step is not None else f"#/p/{pid}/inbox"


def guide(project: Any, persona: str | None) -> dict[str, Any]:
    """The answer: what ``persona`` can do now on ``project`` and who else must act, with Take me there."""
    cards = Canon(project).cards(state="open")
    mine = [c for c in cards if may_decide(persona, list(deciders_of(c)))]
    others = [c for c in cards if c not in mine]
    step = _dev_step(project, persona)
    now = _now(step, mine)
    title = project.meta.get("title") or project.pid
    text = f"As {_label(persona)} on {title}: " + (
        "you can " + "; then ".join(now) + "." if now else "nothing waits on you right now.")
    if others:
        text += (" Who else must act: " + "; ".join(_others(others)) + ". Nudge them, or switch persona in the "
                 "person menu if you work alone.")
    return {"answer": text, "navigate": {"route": _route(project.pid, step, mine), "control": None}, "propose": [],
            "dropped": [], "sources": [], "by": "map", "matches": ["next", "guide"],
            "guide": {"mine": [c["id"] for c in mine], "others": [c["id"] for c in others],
                      "step": step["title"] if step else None}}


__all__ = ["guide"]
