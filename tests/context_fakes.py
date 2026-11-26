"""The data and context layer's write routes and signed commands (FR-CTX1), for the completeness tables
(tests/test_brief_ln.py, tests/test_access.py): each signed, each recorded in Rihma's own ledger."""

from __future__ import annotations

from typing import Any


def write_routes(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """A clean-up proposed, then applied, each by IT (cockpit/context_routes.py). Nothing here is old enough to
    clean, so the proposal holds no item and applying it removes nothing; both are still signed and recorded."""
    return [
        ("post_data_cleanup", "POST", "/api/data/cleanup", lambda who, got: {"person": who, "persona": "it"}),
        ("post_data_apply", "POST", lambda got: f"/api/data/cleanup/{got['post_data_cleanup']['proposal']['id']}/apply",
         lambda who, got: {"person": who, "persona": "it"}),
    ]


def cli_writes(person: str) -> dict[str, list[str]]:
    """`rihmasto data cleanup` and `rihmasto data apply`, signed by ``person`` as IT."""
    who = ["--person", person, "--persona", "it"]
    return {"data cleanup": ["data", "cleanup", *who], "data apply": ["data", "apply", "CU-0001", *who]}
