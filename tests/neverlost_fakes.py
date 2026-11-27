"""The FR-NVL1 write routes for the cockpit's completeness tables (tests/test_brief_ln.py, tests/test_access.py): a
decision triage's confirm and Gnomon's enforcement for the platform and a project, each signed and recorded."""

from __future__ import annotations

from typing import Any


def write_routes(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    b = w["built"].pid
    return [
        ("post_triage_assume", "POST", f"/api/projects/{b}/triage/assume",
         lambda who, got: {"person": who, "persona": "product_owner"}),
        ("put_harness_enforcement", "PUT", "/api/harness-enforcement",
         lambda who, got: {"on": False, "reason": "a harness trial this week", "person": who, "persona": "it"}),
        ("put_project_harness_enforcement", "PUT", f"/api/projects/{b}/harness-enforcement",
         lambda who, got: {"on": True, "reason": "", "person": who, "persona": "developer"}),
    ]
