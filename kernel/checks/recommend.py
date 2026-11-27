"""The checks a solution type starts from (FR-CHK1): what Health suggests first for the project's profile, the way
automations are suggested (kernel/automation_suggest.py). A suggestion is offered, never enabled on its own: the
person enables each one, signed, as any check.
"""

from __future__ import annotations

from typing import Any

# By profile (kernel/profiles.py): the kinds of check that type needs first, most useful first.
BY_PROFILE: dict[str, tuple[str, ...]] = {
    "web_service": ("tests", "probe", "ci", "dependencies", "secrets", "destinations"),
    "integration": ("tests", "probe", "destinations", "ci", "secrets", "dependencies"),
    "mobile_prototype": ("tests", "ci", "dependencies", "licences"),
    "ml_pipeline": ("tests", "executions", "dependencies", "licences", "secrets"),
    "agentic_workflow": ("tests", "secrets", "security_gate", "dependencies", "ci"),
    "harness_engineering": ("tests", "ci", "secrets", "security_gate"),
    "ops_agent": ("tests", "secrets", "security_gate", "ci"),
    "automation": ("tests", "executions", "secrets", "ci"),
}
DEFAULT = ("tests", "ci", "dependencies", "secrets")


def for_project(project: Any, enabled: Any = ()) -> dict[str, Any]:
    """The kinds suggested for the project's type, which of them are not enabled yet, and the type in words."""
    from kernel.checks import catalogue
    from kernel.profiles import PROFILES

    profile = str(project.meta.get("profile") or "")
    kinds = [k for k in BY_PROFILE.get(profile, DEFAULT) if k in catalogue()]
    on = {str(k).split(":")[0] for k in enabled}
    label = (PROFILES.get(profile) or {}).get("label") or "this kind of project"
    return {"profile": profile or None, "label": label, "kinds": kinds, "missing": [k for k in kinds if k not in on]}
