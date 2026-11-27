"""Goal help for "audit this project", "benchmark the context cost", "evaluate the agent" (FR-EVL1 with FR-CPL1).

``catalogue`` is what goal help's catalogue says of Gnomon's audits (kernel/copilot_catalog.py); ``steps`` the plan's
steps by rule (kernel/copilot.py): the audit the goal names (else the security posture), run now from Audits & evals,
as a weekly check, and the same as a command; and for "compare models", Rihma's role evals in Models setup.
"""

from __future__ import annotations

import re
from typing import Any

WORDS = re.compile(r"\b(audit|benchmark|evals?\b|evaluat|context cost|security posture|compliance map|data.?flow|"
                   r"attack corpus|claim check|degradation|chaos|gnomon|auditoi|arvioi|vertaa mallej|compare models)")
NAMED = (("context cost", "context_cost"), ("context-cost", "context_cost"), ("compliance", "compliance"),
         ("data flow", "dataflow"), ("dataflow", "dataflow"), ("attack", "security_test"), ("claim", "claim_check"),
         ("degradation", "degradation"), ("chaos", "chaos"), ("fault", "chaos"), ("doctor", "doctor"),
         ("metrics", "metrics"), ("trail", "audit_verify"), ("eval on", "eval"), ("own tasks", "eval"),
         ("change", "check"), ("security", "security"))


def catalogue() -> dict[str, Any]:
    from kernel import gnomon_evals as ge
    from kernel import role_evals as rv

    try:
        evals = [{"id": e["id"], "label": e["label"], "available": e["available"]} for e in ge.public()]
    except Exception:  # noqa: BLE001 - goal help never fails because Gnomon could not be asked
        evals = []
    return {"available": bool(evals), "evals": evals, "role_sets": list(rv.SETS)}


def check_proposal(project: Any, persona: str, args: dict[str, Any]) -> str | None:
    """Ask Rihma's ``run_eval`` proposal, checked as the run route checks it: None when it may be offered."""
    from kernel import gnomon_evals as ge
    from kernel.gnomon_evals_run import ENABLERS

    try:
        ev = ge.find(str(args.get("eval") or ""))
    except ValueError as exc:
        return str(exc)
    if project.pid.startswith("_"):
        return "Rihmasto itself has no repository to audit: open a project first"
    if ev.runs_code:
        from kernel.console import settings

        if persona not in settings(project)["personas"]:
            return f"the {ev.label} runs the project's own code, which the console here allows only to " \
                   + ", ".join(settings(project)["personas"])
    elif persona not in ENABLERS:
        return f"Gnomon audits are run by {', '.join(ENABLERS)}"
    ok, why = ge.availability(ev)
    return None if ok else why


def named(goal: str) -> str:
    said = goal.lower()
    return next((eid for word, eid in NAMED if word in said), "security")


def steps(cat: dict[str, Any], facts: dict[str, Any], views: set[str], goal: str) -> list[dict[str, Any]]:
    from kernel import gnomon_evals as ge
    from kernel.copilot_steps import step

    pid = facts["pid"]
    info = (cat.get("evals") or {"evals": []})
    known = {e["id"]: e for e in info.get("evals") or []}
    ev = ge.find(named(goal))
    ok = bool(known.get(ev.id, {}).get("available"))
    why = "Gnomon or this audit is not on this machine: Audits & evals on Health says what it needs"
    route = f"#/p/{pid}/checks" if "checks" in views else None
    out = [step(f"Run the Gnomon {ev.label} now", {"kind": "open", "route": route, "control": "evals_run"},
                f"{ev.measures}. Takes {ev.duration}; " + ("calls the lane's models" if ev.models == "roles"
                                                           else "calls no model") + ".",
                available=ok, why_not=why, doc="docs/guides/audits-and-evals.md"),
           step("Run it every week as a check", {"kind": "enable_check", "check": ev.check_kind, "route": route,
                                                  "control": "health_enable"},
                "Its result and trend show on Health, in Insights and in Review.", available=ok, why_not=why),
           step("Or from a terminal", {"kind": "command", "command": f"rihmasto evals run {pid} --eval {ev.id} "
                                                                    "--person ... --persona developer"},
                "The output streams as it comes; the result is recorded.")]
    if re.search(r"compare|model|vertaa", goal.lower()):
        out.append(step("Compare models on Rihma's own evals", {"kind": "open", "route": "#/models",
                                                                 "control": "evals_roles_run"},
                        "Each role's eval set against the configured model and its alternatives."))
    return out
