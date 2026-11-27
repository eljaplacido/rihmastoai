"""The Inbox cards of an enforced convention of Rihmasto's structure (FR-STR1, kernel/structure_policy.py).

A convention set to Enforce on a project, with something open, has one card of kind ``structure`` in the project's
Inbox: what is open, why it is asked, and two answers. **Will fix** records that the person takes it on; the card
stays answered while what it covers is the same. **Advise instead** sets the convention to Advise for this project,
signed with the person's name and reason, and the card's findings become suggestions.

A card covers what Rihmasto saw when it opened (``seen``, a fingerprint of the open items): when that changes the
open card is withdrawn and a new one asks again; a convention no longer enforced, or with nothing open, has its
card withdrawn. Nothing here writes to the project's repository.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from kernel import structure_policy as sp
from kernel.canon import Canon

KIND = "structure"


def seen_of(conv: str, items: list[dict[str, Any]]) -> str:
    raw = json.dumps([conv, sorted(str(i.get("id")) for i in items)], ensure_ascii=True)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()[:16]


def _cards(canon: Canon, conv: str, state: str | None) -> list[dict[str, Any]]:
    return [c for c in canon.cards(state=state, kind=KIND) if (c.get("refs") or {}).get("structure") == conv]


def _body(conv: str, items: list[dict[str, Any]]) -> str:
    c = sp.CONVENTION[conv]
    shown = "; ".join(str(i.get("title")) for i in items[:8]) + (" and more" if len(items) > 8 else "")
    return (f"{c['label']} is set to Enforce for this project: it asks that {c['asks']}. Open now: {shown}. "
            "Will fix: you take it on (the card stays answered while these stay the same). Advise instead: the "
            "convention becomes a suggestion for this project, not counted, signed with your name and reason.")


def sync(factory: Any, project: Any) -> dict[str, list[str]]:
    """Open, renew or withdraw each convention's card to match its level and what is open now."""
    canon = Canon(project)
    found = sp.findings(project)
    levels = sp.levels(factory, project)
    out: dict[str, list[str]] = {"opened": [], "withdrawn": []}
    for conv in sp.CONVENTIONS:
        _one(canon, conv, found[conv] if levels[conv] == "enforce" else [], out)
    if out["opened"] or out["withdrawn"]:
        project.log("structure_cards", out)
    return out


def _one(canon: Canon, conv: str, items: list[dict[str, Any]], out: dict[str, list[str]]) -> None:
    """One convention's card: withdrawn when nothing enforced is open, renewed when what is open changed."""
    seen = seen_of(conv, items)
    live = _cards(canon, conv, "open")
    stale = [c for c in live if not items or (c.get("payload") or {}).get("seen") != seen]
    for c in stale:
        canon.close(c["id"], "what it covers changed, or the convention is no longer enforced here")
        out["withdrawn"].append(c["id"])
    answered = [c for c in _cards(canon, conv, "decided") if (c.get("payload") or {}).get("seen") == seen
                and (c.get("decision") or {}).get("verdict") == "will_fix"]
    if not items or len(stale) < len(live) or answered:
        return
    label = sp.CONVENTION[conv]["label"]
    card = canon.card(KIND, f"{label}: {len(items)} open, enforced for this project", body=_body(conv, items),
                      refs={"structure": conv}, payload={"convention": conv, "count": len(items), "seen": seen,
                                                         "items": [i.get("id") for i in items[:50]]})
    out["opened"].append(card["id"])


def carry_out(factory: Any, project: Any, card: dict[str, Any], verdict: str, *, person: str, persona: str,
              reason: str = "") -> dict[str, Any]:
    """A decided card takes effect at once: Advise instead sets the convention to Advise for this project."""
    if card.get("kind") != KIND or verdict != "advise":
        return {}
    conv = (card.get("refs") or {}).get("structure")
    if conv not in sp.CONVENTION:
        return {}
    said = (reason or "").strip() or f"chose Advise instead on card {card['id']}"
    out = sp.set_levels(factory, project, {conv: "advise"}, person=person, persona=persona, reason=said)
    return {"structure": {"convention": conv, "level": "advise", "lines": out["lines"]}}
