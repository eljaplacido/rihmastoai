"""Rihmasto's structure per project (FR-STR1): its signed write routes for the cockpit's completeness tables
(tests/test_brief_ln.py, tests/test_access.py), and a repository change dated inside the test clock's window."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alignment_fixture import git, write

RECENT = "2026-11-20T10:00:00+00:00"       # two days before the test clock's now (kernel/store.py FixedClock)


def write_rows(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The structure write routes, each signed and recorded: the platform's levels in the factory's ledger, a
    project's own in its ledger."""
    b = w["built"].pid
    return [
        ("put_structure", "PUT", "/api/structure",
         lambda who, got: {"levels": {"layout": "off"}, "kind": "own", "reason": "our layout is our own",
                           "person": who, "persona": "it"}),
        ("put_project_structure", "PUT", f"/api/projects/{b}/structure",
         lambda who, got: {"levels": {"commit_hygiene": "advise"}, "reason": "commits are squashed on merge",
                           "person": who, "persona": "developer"}),
    ]


def preview_row(w: dict[str, Any]) -> tuple[Any, ...]:
    """The preview (records nothing) for tests/test_access.py's enforced table."""
    b = w["built"].pid
    return ("post_structure_preview", "POST", "/api/structure/preview",
            lambda who, got: {"project": b, "levels": {"test_trace": "off"}, "person": who, "persona": "developer"})


def recent_work(repo: Path) -> None:
    """Code and a test changed two days before the test clock's now: development in the window."""
    write(repo, {"src/loans.py": "def overdue(days):\n    return days > 14\n",
                 "tests/test_overdue.py": "from src.loans import overdue\n\n\ndef test_overdue():\n"
                                          "    assert overdue(15)\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Flag overdue loans", when=RECENT)
