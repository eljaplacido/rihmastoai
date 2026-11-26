"""An assessment's plan and words for its live progress (kernel/assess.py, kernel/progress.py, FR-PRG1).

The plan has four groups, each step named as a person reads it:

- **Reading the code**: the revision, read from the mirror's objects; the inventory (languages, tests, routes).
- **Rule checks**: one step per area the rules cover (CI/CD governance, maintenance, security, compliance,
  architecture and operations), and the red team's static scan of the code, secrets, Dockerfiles and Actions.
- **The panel** (only when a model is given): one step per perspective that answers (business, end user, IT and
  security, operations, delivery), each with the model that answers it.
- **The record**: the version written and its sha256 put in the ledger.

A step that is done carries its verdicts: passed, findings, not measured, not applicable; a panel step what it
proposed. Nothing here decides anything: the rules and the record are kernel/assess.py's.
"""

from __future__ import annotations

from typing import Any

from kernel.assess_repo import PERSPECTIVES
from kernel.canon import PERSPECTIVES as PANEL
from kernel.progress import group, step

KIND = "assessment"
PANEL_LABELS = {"business": "Business", "end_user": "End user", "it_security": "IT and security",
                "operations": "Operations", "delivery": "Delivery"}
REDTEAM = "rules.redteam"
RECORD = "record.write"


def model_name(model: Any) -> str:
    """The model that answers the panel, as far as can be known before it answers: the model's own name, its
    harness's route, else the analyst role's routed model."""
    route = getattr(model, "route", None)
    named = getattr(model, "name", None) or (route.get("model") or route.get("label") if isinstance(route, dict)
                                              else None)
    if isinstance(named, str) and named.strip():
        return named.strip()[:120]
    try:
        from kernel.lanes import read_routing

        role = ((read_routing() or {}).get("roles") or {}).get("analyst") or {}
    except (OSError, ValueError):
        role = {}
    return str(role.get("model") or "the analyst role's model")[:120]


def plan(rules: dict[str, int], model: Any = None) -> list[dict[str, Any]]:
    """The groups and steps of one assessment; ``rules`` is how many rules each area has."""
    groups = [
        group("read", "Reading the code", [step("read.mirror", "The revision"),
                                           step("read.inventory", "The inventory")]),
        group("rules", "Rule checks", [*(step(f"rules.{p}", label) for p, label in PERSPECTIVES.items()),
                                       step(REDTEAM, "Security scan")]),
    ]
    if model is not None:
        by = model_name(model)
        groups.append(group("panel", "The panel", [step(f"panel.{p}", PANEL_LABELS.get(p, p), by=by)
                                                    for p in PANEL]))
    groups.append(group("record", "The record", [step(RECORD, "Recorded")]))
    return groups


def verdicts(checks: list[dict[str, Any]]) -> dict[str, int]:
    """A step's counts: passed, findings, not measured and not applicable."""
    names = {"passed": "passed", "failed": "findings", "not measured": "not_measured",
             "not applicable": "not_applicable"}
    out = dict.fromkeys(names.values(), 0)
    for c in checks:
        if c.get("verdict") in names:
            out[names[c["verdict"]]] += 1
    return out


def area_said(perspective: str, rules: int) -> str:
    label = PERSPECTIVES[perspective]
    label = label if label[1:2].isupper() else label[:1].lower() + label[1:]     # "CI/CD" stays as it is
    return f"Checking {label}: {rules} rule{'s' if rules != 1 else ''}"


def inventory_said(inv: dict[str, Any]) -> str:
    """The inventory in one line: languages, test runners and routes found."""
    langs = ", ".join(x["language"] for x in (inv.get("languages") or [])[:3]) or "no language found"
    tests = len(inv.get("tests") or [])
    routes = len(inv.get("routes") or [])
    return f"{langs}; {tests} test runner{'s' if tests != 1 else ''}, {routes} route{'s' if routes != 1 else ''}"


def panel_said(perspective: str, by: str) -> str:
    label = PANEL_LABELS.get(perspective, perspective)
    label = label if perspective == "it_security" else label.lower()
    return f"The {label} perspective is reading the inventory and the rules' results with {by}"


__all__ = ["KIND", "PANEL_LABELS", "RECORD", "REDTEAM", "area_said", "inventory_said", "model_name", "panel_said",
           "plan", "verdicts"]
