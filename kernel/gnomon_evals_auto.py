"""The ``run_eval`` action for automations (FR-EVL1 with FR-AUT1), and the template "Weekly Gnomon audit of this
repository", plugged into the automations' allow-list by kernel/automations_more.py (``register``).

The action runs one of Gnomon's audits (kernel/gnomon_evals.py) on the project the firing names, signed by the
automation's owner and with the owner's rights (the same rules as a person's run, kernel/gnomon_evals_run.py),
recorded as ``eval_ran`` with ``via`` naming the automation. It decides nothing: what it finds shows in Health,
Insights and Review, and a finding becomes a change only when a person makes it one.
"""

from __future__ import annotations

from typing import Any

from kernel.gnomon_evals_run import ENABLERS

ACTION = {"run_eval": {"label": "run a Gnomon audit or eval (Audits & evals)", "personas": ENABLERS,
                       "per_project": True}}
TEMPLATE: dict[str, Any] = {
    "id": "weekly_gnomon_audit", "label": "Weekly Gnomon audit of this repository", "needs": ["project"],
    "about": "Every Monday, run Gnomon's security posture audit on the project's repository: its result, trend and "
             "new findings show under Audits & evals on Health, in Insights and in Review.",
    "draft": {"name": "Weekly Gnomon audit", "trigger": {"kind": "schedule", "weekly": "mon 03:00"},
              "action": {"kind": "run_eval", "eval": "security"}, "scope": {"kind": "project", "projects": []}}}


def fields(factory: Any, a: dict[str, Any]) -> dict[str, Any]:
    from kernel.gnomon_evals import find

    return {"eval": find(str(a.get("eval") or "security")).id}      # the security posture unless one is named


def handle(factory: Any, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel import gnomon_evals_run as gr

    if not f.get("project"):
        raise ValueError("run_eval acts on a project, and the firing names none")
    project = factory.project(f["project"])
    owner = a["owner"]
    row = gr.run(project, a["action"]["eval"], person=owner["person"], persona=owner["persona"],
                 via=f"automation {a['id']}")
    return {"outcome": "done", "verdict": row["verdict"], "detail": f"{row['label']}: {row['summary']}"[:300],
            "refs": {"eval": row["eval"]}}


def register(automations: Any, actions: Any) -> None:
    """Add run_eval to the allow-list, its field and its handler (idempotent)."""
    automations.ACTIONS.update(ACTION)
    automations._ACTION_FIELDS["run_eval"] = fields
    if hasattr(actions, "HANDLERS"):
        actions.HANDLERS["run_eval"] = handle
