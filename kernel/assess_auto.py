"""The ``run_assessment`` action for automations (FR-AUT1 with the assessment, kernel/assess.py), plugged into the
automations' allow-list by kernel/automations_more.py (``register``).

"Every Monday run the assessment again": the project's repository is assessed by the rules (no model), signed by
the automation's owner, and recorded as the assessment's next version, as a person's Assess does. It decides
nothing: its findings show on the Assessment view for a person to act on.
"""

from __future__ import annotations

from typing import Any

from kernel.people import PERSONAS

ACTION = {"run_assessment": {"label": "assess the project's repository again (by the rules; Assessment)",
                             "personas": tuple(PERSONAS), "per_project": True}}


def handle(factory: Any, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel import assess

    if not f.get("project"):
        raise ValueError("run_assessment acts on a project, and the firing names none")
    project = factory.project(f["project"])
    if not project.path("repo.git").is_dir():
        return {"outcome": "refused", "detail": f"{project.pid} has no repository to assess yet"}
    owner = a["owner"]
    rec = assess.assess(project, person=owner["person"], persona=owner["persona"])
    counts = rec.get("counts") or {}
    return {"outcome": "done", "detail": f"assessment {rec['id']}: {counts.get('findings', 0)} finding(s)"[:300],
            "refs": {"assessment": rec["id"]}}


def register(automations: Any, actions: Any) -> None:
    """Add run_assessment to the allow-list, its (empty) fields and its handler (idempotent)."""
    automations.ACTIONS.update(ACTION)
    automations._ACTION_FIELDS["run_assessment"] = lambda factory, a: {}
    if hasattr(actions, "HANDLERS"):
        actions.HANDLERS["run_assessment"] = handle
