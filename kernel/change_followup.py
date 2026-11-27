"""A change's follow-up question goes with the change (FR-DF3).

A defect whose triage named no requirement asks a person which one it breaks (kernel/change.py,
``_ask_requirement``). When a person rejects or defers that change, the question has nothing left to
decide: its card is withdrawn with why, so it never stays alone in the Inbox. The question itself keeps
its record; deciding the change again later asks it again.
"""

from __future__ import annotations

from typing import Any


def close_followup(canon: Any, card: dict[str, Any], verdict: str) -> dict[str, Any] | None:
    """Withdraw the open card of ``card``'s which-requirement question once the change is rejected or deferred."""
    if card.get("kind") != "change" or verdict not in ("reject", "defer"):
        return None
    asked = ((card.get("payload") or {}).get("triage") or {}).get("needs_requirement") or {}
    qcard = asked.get("card")
    if not qcard:
        return None
    try:
        if canon.get_card(qcard)["state"] != "open":
            return None
    except KeyError:
        return None
    word = "rejected" if verdict == "reject" else "deferred"
    return canon.close(qcard, f"its change {card['id']} was {word}, so which requirement it breaks waits with it")
