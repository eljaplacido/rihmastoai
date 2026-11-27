"""The persona a decision needs, chosen for the person who holds it (D-0024 item 4, FR-PPL1).

In solo mode one person holds every persona; in team mode a member holds the personas their user, groups
and project roles grant. Neither should have to switch persona to decide: a write sent "as needed" is
signed with the persona it needs among those the person holds, the one they look through first when it
fits, and the record names it ("decided by Aino as IT"). An explicit persona is never changed: only a
write that asks for it is (the cockpit's "Viewing as: everything"). IT's own access file keeps its
explicit personas.
"""

from __future__ import annotations

from collections.abc import Iterable

from kernel.accessfile import Access
from kernel.people import PERSONAS, Identity

EVERY = "*"                    # the Inbox through every persona the person holds


def holds_all(access: Access) -> bool:
    """Solo (or a single operator): every persona is the person's own."""
    return not access.enforced


def chooses(access: Access) -> bool:
    """Whether a write may ask for the persona it needs: solo, or Rihmasto's team mode."""
    return not access.enforced or access.source == "team"


def held(access: Access, ident: Identity | None, pid: str | None) -> tuple[str, ...]:
    """The personas the person holds on ``pid`` (None: anywhere)."""
    if holds_all(access):
        return PERSONAS
    if ident is None or access.error is not None:
        return ()
    from kernel.access import personas

    return tuple(personas(access, ident, pid))


def decide_as(needed: Iterable[str], holding: Iterable[str], preferred: str | None = None) -> str | None:
    """The persona to sign with: ``preferred`` when it fits, else the first needed one the person holds."""
    need, have = list(needed), set(holding)
    if preferred in need and preferred in have:
        return preferred
    return next((p for p in need if p in have), None)
