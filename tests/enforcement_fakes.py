"""Stand-ins for enforcement levels per environment (FR-ENF1): the signed write routes for the cockpit's
completeness tables (tests/test_brief_ln.py, tests/test_access.py) and a GitHub CLI that answers from fixtures.

The GitHub stand-in answers ``gh api -X GET <path>`` for a neutral repository ``acme/orders``: its default
branch, two deployment environments (staging without a reviewer, production with one) and the main line's
protection (one required review, one required check). Nothing reaches GitHub; a write is refused outright.
"""

from __future__ import annotations

import json
from typing import Any

REPO = "acme/orders"
ENVIRONMENTS = {"environments": [
    {"name": "staging", "protection_rules": [{"type": "wait_timer", "wait_timer": 5}],
     "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}},
    {"name": "production", "protection_rules": [{"type": "required_reviewers",
                                                 "reviewers": [{"type": "User", "reviewer": {"login": "owner"}}]}],
     "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}}]}
PROTECTION = {"required_pull_request_reviews": {"required_approving_review_count": 1},
              "required_status_checks": {"contexts": ["tests"]}, "enforce_admins": {"enabled": False}}


# A repository ruleset on main (FR-ENF2): a pull request without a required review, and two required checks.
RULES = [{"type": "deletion", "ruleset_source_type": "Repository", "ruleset_source": REPO, "ruleset_id": 42},
         {"type": "pull_request", "ruleset_id": 42, "parameters": {"required_approving_review_count": 0,
                                                                    "dismiss_stale_reviews_on_push": False}},
         {"type": "required_status_checks", "ruleset_id": 42,
          "parameters": {"required_status_checks": [{"context": "ci"}, {"context": "lint"}]}}]
RULESETS = [{"id": 42, "name": "Protect main", "target": "branch", "enforcement": "active"}]


class FakeGh:
    """``gh`` for kernel/enforcement_pipeline.py: GET answers from the fixtures above, every call kept. With
    ``rulesets`` main is held by a repository ruleset; ``protected`` False leaves classic protection off."""

    def __init__(self, *, signed_in: bool = True, protected: bool = True, rulesets: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.signed_in, self.protected, self.rulesets = signed_in, protected, rulesets

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(args))
        if args[:3] != ["api", "-X", "GET"]:
            return 2, "", "only GET requests are answered here"
        if not self.signed_in:
            return 4, "", "To get started with GitHub CLI, please run:  gh auth login"
        path = args[3]
        if path == f"repos/{REPO}":
            return 0, json.dumps({"full_name": REPO, "default_branch": "main"}), ""
        if path == f"repos/{REPO}/environments":
            return 0, json.dumps(ENVIRONMENTS), ""
        if path == f"repos/{REPO}/branches/main/protection":
            return (0, json.dumps(PROTECTION), "") if self.protected else (1, "", "gh: Branch not protected (HTTP 404)")
        if path == f"repos/{REPO}/rules/branches/main":
            return 0, json.dumps(RULES if self.rulesets else []), ""
        if path == f"repos/{REPO}/rulesets":
            return 0, json.dumps(RULESETS if self.rulesets else []), ""
        return 1, "", "gh: Not Found (HTTP 404)"


def write_rows(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The enforcement write routes (FR-ENF1), each signed and recorded: the platform's levels in the factory's
    ledger, a project's own levels in its ledger."""
    b = w["built"].pid
    return [
        ("put_enforcement", "PUT", "/api/enforcement",
         lambda who, got: {"levels": {"prod": {"security": "enforce"}}, "person": who, "persona": "it"}),
        ("put_project_enforcement", "PUT", f"/api/projects/{b}/enforcement",
         lambda who, got: {"levels": {"test": {"governance": "require_review"}}, "person": who,
                           "persona": "compliance"}),
    ]


def preview_row(w: dict[str, Any]) -> tuple[Any, ...]:
    """The preview (records nothing) for tests/test_access.py's enforced table."""
    b = w["built"].pid
    return ("post_enforcement_preview", "POST", "/api/enforcement/preview",
            lambda who, got: {"project": b, "preset": "split", "person": who, "persona": "it"})
