"""Teams and their words (FR-TM1, FR-TM2): the signed write routes for the cockpit's completeness tables
(tests/test_brief_ln.py, tests/test_access.py). Each is signed and recorded: a team's in the factory's ledger, a
project's own words and its move in its ledger too. The previews record nothing."""

from __future__ import annotations

from typing import Any


def write_rows(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    b = w["built"].pid
    tid = lambda got: got["post_team"]["team"]["id"]                              # noqa: E731
    return [
        ("post_team", "POST", "/api/teams",
         lambda who, got: {"name": "Platform", "members": ["Cleo Example"], "person": who, "persona": "it"}),
        ("put_team", "PUT", lambda got: f"/api/teams/{tid(got)}",
         lambda who, got: {"add": ["Dee Example"], "person": who, "persona": "it"}),
        ("post_project_team", "POST", f"/api/projects/{b}/team",
         lambda who, got: {"team": tid(got), "reason": "the platform team owns it", "person": who, "persona": "it"}),
        ("put_team_vocabulary", "PUT", lambda got: f"/api/teams/{tid(got)}/vocabulary",
         lambda who, got: {"term": "kind:task", "label": "Work item", "reason": "our board's word", "person": who,
                           "persona": "it"}),
        ("put_project_vocabulary", "PUT", f"/api/projects/{b}/vocabulary",
         lambda who, got: {"term": "kind:criterion", "label": "Check", "reason": "this project says check",
                           "person": who, "persona": "it"}),
        ("post_vocabulary_undo", "POST", "/api/vocabulary/undo",
         lambda who, got: {"project": b, "person": who, "persona": "it"}),
        ("post_team_undo", "POST", "/api/teams/undo",
         lambda who, got: {"project": b, "person": who, "persona": "it"}),
    ]


def preview_rows(w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The previews (they record nothing) for tests/test_access.py's enforced table."""
    b = w["built"].pid
    return [
        ("post_teams_preview", "POST", "/api/teams/preview",
         lambda who, got: {"team": "team-solo", "name": "Our team", "person": who, "persona": "it"}),
        ("post_vocabulary_preview", "POST", "/api/vocabulary/preview",
         lambda who, got: {"project": b, "term": "kind:request", "label": "Ask", "person": who, "persona": "it"}),
    ]
