"""An enforcement card covers what its reviewer saw, and says who decides it and where (D-0026, FR-ENF2).

The guard (kernel/enforcement_guard.py) opens a card of kind ``enforcement`` when a cell asks for a person. A card
is tied to what Rihmasto saw when it opened: the environment, the family, the subject, the level and the findings
(``seen``, a short fingerprint of them). So:

- an approval clears that subject only while Rihmasto sees the same thing; a new finding on an approved release
  opens a new card;
- an open card whose subject now shows something else is withdrawn and a new card asks again, with what is new;
- a subject that recurs (an automation's firings, ``once``) is cleared by one approval for one go: the approval is
  spent by the firing it lets through, and the next firing asks again;
- a refusal holds what was seen: the work stays held and the words say who refused it, why, and what lets it on
  (the findings change, or a person changes the level).

Who decides is the cell's reviewer persona. A person working alone holds every persona, so the words name both
places to decide: the Inbox (seen as that persona, or as everything) and the project's Enforcement view.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from kernel.canon import Canon
from kernel.enforcement_places import WHERE


def seen_of(c: dict[str, Any], items: list[str]) -> str:
    """The fingerprint of what Rihmasto saw: the level and the findings, in any order."""
    raw = json.dumps([c["level"], sorted(str(i) for i in items)], ensure_ascii=True)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()[:16]


def _number(card: dict[str, Any]) -> int:
    return int(str(card["id"]).split("-")[-1])


def _mine(canon: Canon, key: str) -> list[dict[str, Any]]:
    cards = [c for c in canon.cards(state=None, kind="enforcement") if (c.get("refs") or {}).get("enforcement") == key
             and c["state"] in ("open", "decided")]
    return sorted(cards, key=_number, reverse=True)          # the newest first


def _verdict(card: dict[str, Any]) -> str | None:
    return (card.get("decision") or {}).get("verdict") if card["state"] == "decided" else None


def _answers(card: dict[str, Any], seen: str, once: bool) -> bool | None:
    """True: this card answers the look; False: skip it; None: no older card answers either."""
    pay = card.get("payload") or {}
    if pay.get("seen") != seen:
        return False
    if not once:
        return True
    if _verdict(card) == "approve" and not pay.get("spent_at"):
        return True
    return None                    # spent, or refused: that go was answered; the next one asks again


def card_for(canon: Canon, key: str, seen: str, *, once: bool) -> dict[str, Any] | None:
    """The card that answers this look, or None (a new card opens). An open card that saw something else is
    withdrawn, so a reviewer never approves what they were not shown."""
    for card in _mine(canon, key):
        if card["state"] == "open" and (card.get("payload") or {}).get("seen") != seen:
            canon.close(card["id"], "what Rihmasto sees changed: a new card asks again with what is new")
            continue
        if card["state"] == "open":
            return card
        answers = _answers(card, seen, once)
        if answers is None:
            return None
        if answers:
            return card
    return None


def open_card(project: Any, c: dict[str, Any], key: str, items: list[str], source: str, subject: str,
              seen: str, once: bool) -> dict[str, Any]:
    blocking = c["level"] == "enforce"
    body = ("It waits until you decide. Approve lets it go on (recorded as an override with your name and your "
            "reason); Refuse keeps it held." if blocking
            else "The work goes on; your review is owed. Approve or Refuse records your look.")
    if once:
        body += " An approval lets this one go through; the next time it asks again."
    found = "; ".join(items[:5]) or "the change itself"
    canon = Canon(project)
    where = WHERE[c["env"]]
    card = canon.card("enforcement", f"Look at {subject} before it goes on in {where} ({c['family']})",
                      body=f"{body}\n\nWhat Rihmasto saw: {found}.", refs={"enforcement": key},
                      payload={"env": c["env"], "family": c["family"], "level": c["level"], "subject": subject,
                               "source": source, "items": items[:10], "reviewer": c["reviewer"], "seen": seen,
                               "once": once}, blocking=blocking)
    with canon.edit_card(card["id"]) as kept:
        kept["deciders"] = [c["reviewer"]]
    return dict(card, deciders=[c["reviewer"]])


def outcome(level: str, card: dict[str, Any] | None) -> str:
    if level in ("off", "advise") or card is None:
        return {"off": "passed", "advise": "noted", "require_review": "review", "enforce": "refused"}[level]
    if _verdict(card) == "approve":
        return "cleared"
    return "refused" if level == "enforce" else "review"


def spend(project: Any, card: dict[str, Any]) -> None:
    """An approval of a recurring subject is used by the go it let through."""
    canon = Canon(project)
    with canon.edit_card(card["id"]) as kept:
        kept.setdefault("payload", {})["spent_at"] = canon.clock.stamp()


def who(persona: str) -> str:
    return {"it": "IT"}.get(persona, persona.replace("_", " "))


def held_words(x: dict[str, Any], card: dict[str, Any] | None) -> str:
    """What holds ``x`` (a refused row of the guard) and what lets it on, in one sentence or two."""
    where, reviewer = WHERE[x["env"]], who(x["reviewer"])
    decision = (card or {}).get("decision") or {}
    if _verdict(card or {"state": "open"}) == "refuse":
        why = f" ({decision['reason']})" if decision.get("reason") else ""
        return (f"Held in {where} by the {x['family']} level: {x['card']} was refused by {decision.get('person')} "
                f"as {who(decision.get('persona') or x['reviewer'])}{why}. It stays held while Rihmasto sees the "
                "same thing; a new finding or a fix opens a new review, and a person may change the level in the "
                "Enforcement view.")
    the = reviewer if reviewer == "IT" else f"the {reviewer}"
    return (f"Held in {where} by the {x['family']} level: {x['card']} waits for {the} to decide. "
            f"Decide it as {reviewer} in the Inbox (working alone, view as everything or switch to {reviewer}) or on "
            "the project's Enforcement view; Approve, with your reason, lets it go on.")
