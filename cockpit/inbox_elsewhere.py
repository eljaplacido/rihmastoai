"""Decisions that hold work and wait on another role the person holds (FR-ENF2).

A person working alone holds every persona (kernel/solo.py); in team mode a member holds what is granted. Seen
through one persona, the Inbox lists only that persona's cards, so a card that holds work for another role the same
person holds (an enforcement card for IT, while they look as business owner) would wait unseen. ``elsewhere``
lists those cards, each with the persona its decision would be signed with, so the Inbox (one project's and all
projects') can say they wait and offer to show every role. It reads only.
"""

from __future__ import annotations

from typing import Any

from kernel import solo as ksolo
from kernel.canon import Canon, deciders_of

LIMIT = 20


def _holds_work(card: dict[str, Any]) -> bool:
    return bool(card.get("blocking"))


def elsewhere(api: Any, projects: list[Any], persona: str) -> list[dict[str, Any]]:
    """Open cards that hold work, which ``persona`` may not decide but another persona the person holds may."""
    from cockpit.server import _factory_label

    out: list[dict[str, Any]] = []
    for p in projects:
        holding = ksolo.held(api.access, api.identity, p.pid)
        for c in Canon(p).cards(state="open"):
            who = deciders_of(c)
            if persona in who or not _holds_work(c):
                continue
            as_ = ksolo.decide_as(who, holding)
            if as_ is not None:
                out.append({"id": c["id"], "kind": c["kind"], "title": c["title"], "project": p.pid,
                            "project_title": _factory_label(p.pid, p.meta.get("title", p.pid)),
                            "decide_as": as_, "deciders": list(who)})
    return out[:LIMIT]
