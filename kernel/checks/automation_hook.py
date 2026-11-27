"""The ``run_check`` action for automations (FR-CHK1 with FR-AUT1), kept apart so it plugs into the
automations' allow-list with one call wherever the automations are (``register``):

    from kernel.checks import automation_hook
    automation_hook.register(kernel.automations, kernel.automations_actions)

It adds ``run_check`` to the allow-list (``ACTIONS``) with the personas that may set checks, its field (the
check's key, such as ``dependencies`` or ``probe:prod``) and its handler: the check runs on the project the
firing names through the checks' own path (kernel/checks/store.py), signed by the automation's owner, and
its result is recorded like any other run (``check_ran``, via the automation). A check not enabled on that
project does nothing and says so; an automation never enables one by itself.
"""

from __future__ import annotations

from typing import Any

from kernel.checks import ENABLERS
from kernel.checks import store as cstore

ACTION = {"run_check": {"label": "run a check (Health)", "personas": ENABLERS, "per_project": True}}


def fields(factory: Any, a: dict[str, Any]) -> dict[str, Any]:
    """The action's field: the check's key, checked against the catalogue."""
    _, key = cstore.check_of(str(a.get("check") or ""))
    return {"check": key}


def handle(factory: Any, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    """Run the check on the firing's project with the owner's rights; the outcome for the automation's history."""
    if not f.get("project"):
        raise ValueError("run_check acts on a project, and the firing names none")
    project = factory.project(f["project"])
    key = a["action"]["check"]
    if key not in cstore.enabled(project):
        return {"outcome": "nothing", "detail": f"{key} is not enabled on {project.pid}"}
    owner = a["owner"]
    row = cstore.run(project, key, person=owner["person"], persona=owner["persona"], via=f"automation {a['id']}")
    return {"outcome": "done", "verdict": row["verdict"], "detail": f"{key}: {row['summary']}"[:300],
            "refs": {"check": key}}


def register(automations: Any, actions: Any) -> None:
    """Add run_check to the automations' allow-list, fields and handlers (idempotent)."""
    automations.ACTIONS.update(ACTION)
    automations._ACTION_FIELDS["run_check"] = fields
    actions.HANDLERS["run_check"] = handle
