"""The automations IT's context suggests (FR-ITO1 with FR-SET1): rules kernel/automation_suggest.py adds to its own.

From what the project runs and what was found (kernel/itops.py, kernel/checks/infra_targets.py):

- **TLS expiry weekly** when something it runs or reaches is https: the TLS check every Monday, a channel told
  when it fails;
- **nightly database probe** when it declares a database: the database check every night;
- **alert on a failing integration** when it declares an integration: when the integration check turns failed
  (``infra_check_failed`` with source ``integration``), tell a channel, or log a signal when none is set up;
- **weekly IT check set** when some of its IT checks are on: ``run_assessment`` of ``infra`` every Sunday;
- **weekly eval sets** when it is an ML pipeline or an agent: ``run_assessment`` of ``evalsets``, every eval set
  turned on for it, every week;
- **agent limits daily** when it is an agent or assistant: the agent check every morning, told when it fails.

Each one is a draft of kernel/automations.py checked against the allow-list like any suggestion, accepted in the
person's name, dismissed per project. One that runs a check or the eval sets is shown "not available here", with
what to turn on first, until that check or a set is on: set up before, it would run nothing (FR-ITO2).
``TEMPLATES`` add "Run an assessment on a schedule" and "TLS expiry weekly" to the automations' templates.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Facts = dict[str, Any]


def facts(project: Any) -> Facts:
    """What these rules read: the solution types, and whether https, a database or an integration was found."""
    from kernel import itops, itops_evals
    from kernel.checks import infra_targets as tg
    from kernel.checks import store as cstore

    try:
        types = itops.types_of(project)
        binds = tg.bindings(project)
        urls = [u["url"] for u in tg.urls(project)] + [r["endpoint"] for b in binds for r in b["environments"]]
        set_size = sum(1 for r in itops.check_set(project)["checks"] if r["enabled"])   # turned on
        kinds = sorted({str(e.get("kind")) for e in cstore.enabled(project).values()})
        evalsets = [r["label"] for r in itops_evals.sets(project) if r["enabled"]]
    except (OSError, ValueError, KeyError):
        return {"it_types": [], "https": False, "databases": [], "integrations": [], "it_set": 0, "checks_on": [],
                "evalsets_on": []}
    return {"it_types": sorted(types), "https": any(str(u).startswith("https://") for u in urls),
            "databases": [b["name"] for b in binds if b["family"] == "database"],
            "integrations": [b["name"] for b in binds if b["family"] != "database"], "it_set": set_size,
            "checks_on": kinds, "evalsets_on": evalsets}


def _needs_check(s: dict[str, Any], f: Facts, kind: str, label: str) -> dict[str, Any]:
    """A suggestion that runs one check is not set up before that check is on: it would run nothing (FR-ITO2)."""
    if kind not in (f.get("checks_on") or []):
        s["blocked"] = (f"the {label} check is not on for this project yet, so this would run nothing: turn it on "
                        "first (IT checks: Turn on), then set this up")
    return s


def _helpers() -> Any:
    from kernel import automation_suggest as s

    return s


def _tls_weekly(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f.get("https"):
        return None
    s = _helpers()
    draft = s._told({"name": "TLS expiry weekly", "trigger": {"kind": "schedule", "weekly": "mon 06:00"},
                     "action": {"kind": "run_check", "check": "tls"}, "scope": s._scope(f)}, sub)
    return _needs_check(s._s("it_tls_weekly", "Check certificate expiry every week",
                             "it serves or reaches https: an expired certificate stops it for everyone", draft),
                        f, "tls", "TLS")


def _db_nightly(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f.get("databases"):
        return None
    s = _helpers()
    draft = s._told({"name": "Nightly database probe", "trigger": {"kind": "schedule", "daily": "02:30"},
                     "action": {"kind": "run_check", "check": "database"}, "scope": s._scope(f)}, sub)
    return _needs_check(s._s("it_db_nightly", "Probe its database every night",
                             f"it declares {', '.join(f['databases'][:2])}: its round trip, backup and growth, checked "
                             "nightly", draft), f, "database", "Database")


def _integration_alert(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f.get("integrations"):
        return None
    s = _helpers()
    draft = {"name": "A failing integration", "trigger": {"kind": "event", "types": ["infra_check_failed"]},
             "guard": {"kind": "field", "key": "source", "equals": "integration"},
             "action": s._tell(f, sub, "An integration failed its check on {project}"), "scope": s._scope(f)}
    return s._s("it_integration_alert", "Alert when an integration fails its check",
                f"it connects {', '.join(f['integrations'][:3])}: a system that stops answering, an expiring "
                "credential or a spent quota should reach a person at once", draft)


def _infra_weekly(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f.get("it_set"):
        return None
    s = _helpers()
    draft = s._told({"name": "Weekly IT check set", "trigger": {"kind": "schedule", "weekly": "sun 05:00"},
                     "action": {"kind": "run_assessment", "target": "infra"}, "scope": s._scope(f)}, sub)
    return s._s("it_infra_weekly", "Run its IT check set every week",
                f"{f['it_set']} of its IT checks are on for what it runs ({', '.join(f['it_types'][:3])}): one weekly "
                "round over all of them, as an assessment", draft)


def _evals_weekly(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not set(f.get("it_types") or []) & {"ml", "agent"}:
        return None
    s = _helpers()
    draft = s._told({"name": "Weekly eval sets", "trigger": {"kind": "schedule", "weekly": "sat 04:00"},
                     "action": {"kind": "run_assessment", "target": "evalsets"}, "scope": s._scope(f)}, sub)
    on = f.get("evalsets_on") or []
    found = s._s("it_evals_weekly", "Run its eval sets every week",
                 "it is an ML pipeline or an agent: every eval set turned on for it runs weekly"
                 + (f" ({', '.join(on[:3])})" if on else ""), draft)
    if not on:
        found["blocked"] = ("no eval set is turned on for this project yet, so this would run nothing: turn one on "
                            "under Eval sets first, then set this up")
    return found


def _agent_daily(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if "agent" not in (f.get("it_types") or []):
        return None
    s = _helpers()
    draft = s._told({"name": "Agent limits daily", "trigger": {"kind": "schedule", "daily": "07:00"},
                     "action": {"kind": "run_check", "check": "agent"}, "scope": s._scope(f)}, sub)
    return _needs_check(s._s("it_agent_daily", "Check its agents' tool errors, cost and refusals every morning",
                             "it is an agent or assistant: a tool that starts failing or a cost that climbs shows "
                             "here first", draft), f, "agent", "Agent limits")


RULES: tuple[Callable[[Facts, str | None], dict[str, Any] | None], ...] = (
    _tls_weekly, _db_nightly, _integration_alert, _infra_weekly, _evals_weekly, _agent_daily)

TEMPLATES: list[dict[str, Any]] = [
    {"id": "scheduled_assessment", "label": "Run an assessment on a schedule", "needs": ["project"],
     "about": "Every week, run an assessment of any area on a project: the code assessment, a Gnomon audit or eval "
              "set, a check family, alignment, the Optimise audit or the IT check set (target).",
     "draft": {"name": "Weekly assessment", "trigger": {"kind": "schedule", "weekly": "sun 05:00"},
               "action": {"kind": "run_assessment", "target": "infra"}, "scope": {"kind": "project", "projects": []}}},
    {"id": "tls_expiry_weekly", "label": "TLS expiry weekly", "needs": ["project"],
     "about": "Every Monday, read each https certificate's expiry on a project (its TLS check, enabled first).",
     "draft": {"name": "TLS expiry weekly", "trigger": {"kind": "schedule", "weekly": "mon 06:00"},
               "action": {"kind": "run_check", "check": "tls"}, "scope": {"kind": "project", "projects": []}}},
]
