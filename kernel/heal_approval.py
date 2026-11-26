"""Who approves what self-healing proposes, in solo and in team mode (FR-HEAL1 with FR-PPL1, D-0024 items 1 and 4).

A learned remedy, a wording, rule or prompt change from feedback, and a pull request from a fix are each approved
by a persona that may (kernel/immune.py ``APPROVERS``, kernel/feedback.py ``APPROVERS``, kernel/heal_fix.py
``PROJECT_APPROVERS`` and ``RIHMASTO_APPROVERS``: a pull request against Rihmasto's own repository is IT's).

- **Solo mode** (kernel/team.py): the one person of the home holds every persona, so the person named on the first
  visit approves whichever persona they look through: "IT, or the solo person".
- **Team mode**: approvals follow team roles. The persona must be one that may approve, and the cockpit signs only
  with a persona the person's user, groups or project roles grant (kernel/team_access.py).
- **IT's access file** governs as in team mode: the persona it grants, and only one that may approve.
"""

from __future__ import annotations

from typing import Any


def solo_person(factory: Any, person: str) -> bool:
    """Whether ``person`` is the one person of a solo home, as named on its first visit."""
    from kernel import team

    if team.mode(factory) != team.SOLO:
        return False
    name = team.solo_name(factory)
    return bool(name) and str(person or "").strip().casefold() == str(name).strip().casefold()


def may_approve(factory: Any, person: str, persona: str, allowed: tuple[str, ...]) -> bool:
    """A persona that may approve, or the solo person in whichever persona they look through."""
    return persona in allowed or solo_person(factory, person)


def approvers(allowed: tuple[str, ...]) -> str:
    """The words a refusal names: the personas that may approve, or the solo person."""
    return ", ".join(allowed) + ", or the solo person"
