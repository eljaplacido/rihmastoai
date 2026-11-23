"""Who may decide. A decision needs a named person; the factory and its models are not people.

This is the one definition of a person (FR-O8-AC-7). The kernel, the cockpit, the MCP server and
`tools/contract_check.py` (rule R-HUMAN) all use `is_person`, so the contract and the Inbox apply
the same test.
"""

from __future__ import annotations

NOT_A_PERSON: frozenset[str] = frozenset({
    "", "autopilot", "factory-autopilot", "factory", "model", "agent", "llm", "claude", "gnomon",
    "solution-factory", "solutionfactory", "assistant", "bot", "system", "kernel"})

PERSONAS = ("business_owner", "product_owner", "concept_evaluator", "end_user", "it",
            "developer", "operations", "stakeholder", "compliance")


def is_person(name: object) -> bool:
    """A named person: a string that is not blank and names none of the factory's own actors."""
    return isinstance(name, str) and name.strip().lower() not in NOT_A_PERSON
