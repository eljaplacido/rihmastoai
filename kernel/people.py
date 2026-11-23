"""Who may decide. A decision needs a named person; the factory and its models are not people.

This is the one definition of a person (FR-O8-AC-7). The kernel, the cockpit, the MCP server and
`tools/contract_check.py` (rule R-HUMAN) all use `is_person`, so the contract and the Inbox apply
the same test.

When access is enforced (D-0016, `kernel/access.py`), a person is also a verified identity: the
organisation's identity provider vouched for them through IT's proxy, or they are a local user the
access file names. ``SIGNER`` holds that identity while a surface carries out one of their writes,
so the record of the write can name it beside the person (``signed_identity``).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

NOT_A_PERSON: frozenset[str] = frozenset({
    "", "autopilot", "factory-autopilot", "factory", "model", "agent", "llm", "claude", "gnomon",
    "solution-factory", "solutionfactory", "assistant", "bot", "system", "kernel"})

PERSONAS = ("business_owner", "product_owner", "concept_evaluator", "end_user", "it",
            "developer", "operations", "stakeholder", "compliance")


def is_person(name: object) -> bool:
    """A named person: a string that is not blank and names none of the factory's own actors."""
    return isinstance(name, str) and name.strip().lower() not in NOT_A_PERSON


@dataclass(frozen=True)
class Identity:
    """A verified identity (D-0016): ``id`` is ``<issuer>#<subject>`` from IT's sign-in proxy, or
    ``local:<os user>`` on the operator's own machine; ``name`` is the person's display name."""

    id: str
    name: str
    groups: tuple[str, ...] = ()


# The verified identity signing the write being carried out now (kernel.access.signing), or None.
SIGNER: ContextVar[Identity | None] = ContextVar("rihmasto_signer", default=None)


def signed_identity(name: object) -> dict[str, str]:
    """``{"identity": <id>}`` when a verified identity signs the current write as ``name``, else {}."""
    signer = SIGNER.get()
    return {"identity": signer.id} if signer is not None and signer.name == name else {}
