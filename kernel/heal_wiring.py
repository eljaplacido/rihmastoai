"""Where self-healing shows up beyond its own pages (FR-HEAL1, D-0024 item 1, docs/guides/self-healing.md):

- ``sweep``: the failures the kernel already records (a check that failed or could not measure, an automation that
  failed or was refused, a model endpoint that failed, a refused confidential step, a cell runner refused, a
  release or a probe that failed, a sync that failed, an IDE agent's failure the observability hub saw it not
  recover from, with the hub project and the session ids) become incidents, once each. The cockpit's scheduler runs it
  every tick; it reads ledgers and opens incidents, nothing else;
- ``next_actions``: an open incident is a "What's next" action on its project (kernel/next_step.py);
- ``snapshot_part``: open incidents with their remedies, and the assistant rules people approved from their
  feedback, for Ask Rihma's snapshot (kernel/assistant_snapshot.py), so it can open, explain and investigate;
- ``tiles``: Insights' figures (kernel/insights/health.py): incidents open, the median time to resolve, learned
  remedies used.
"""

from __future__ import annotations

import statistics
from typing import Any

from kernel import incidents as inc


def _itops_heal() -> Any:
    from kernel import itops_heal

    return itops_heal

# ledger kind -> (incident kind, a test on the payload: None takes every record)
SWEPT: dict[str, tuple[str, Any]] = {
    # an infrastructure check that had nothing to measure is no failure (kernel/itops_heal.py, FR-ITO2)
    "check_ran": ("check_failed", lambda p: _itops_heal().swept(p)),
    "automation_ran": ("automation_failed", lambda p: p.get("outcome") in ("failed", "refused", "error")),
    "apparatus_failure": ("runner_failed", None),
    "runner_refused": ("runner_failed", None),
    "confidential_refused": ("confidential_refused", None),
    "release_failed": ("product_not_running", None),
    "probe_failed": ("product_not_running", None),
    "upstream_sync_failed": ("job_failed", None),
    # an IDE agent's failure the observability hub saw it not recover from (kernel/agentobs/snapshot.py, FR-OBS1)
    "agent_failure_unrecovered": ("agent_failed", None),
}
# What an incident keeps of a swept record's payload, beside the record itself (ids and counts, never a step).
DETAIL = {"agent_failure_unrecovered": ("hub_project", "sessions")}


def _message(kind: str, p: dict[str, Any]) -> tuple[str, str]:
    """(where, message) of a swept record."""
    if kind == "check_ran":
        return f"check:{p.get('check')}", f"{p.get('verdict')}: {p.get('summary') or ''}"
    if kind == "automation_ran":
        return f"automation:{p.get('action')}", f"{p.get('outcome')}: {p.get('detail') or ''}"
    if kind == "agent_failure_unrecovered":
        return (f"agent:{p.get('hub_project')}",
                f"unrecovered: {len(p.get('sessions') or [])} IDE agent session(s) failed and did not recover")
    if kind == "confidential_refused":
        return f"confidential:{p.get('where')}", "refused: confidential, the role is hosted; nothing was sent"
    return kind.replace("_", " "), str(p.get("error") or p.get("why") or p.get("reason") or kind)


def sweep(factory: Any) -> list[str]:
    """Open an incident for every failure record not swept yet. Returns the incidents opened or counted."""
    from kernel.store import read_json, write_json

    seen_path = inc.heal_dir(factory) / "swept.json"
    seen: dict[str, int] = dict(read_json(seen_path, {}) or {})
    before = dict(seen)
    touched: list[str] = []
    for project in factory.projects():
        try:
            records = [r for r in project.ledger().records() if isinstance(r, dict) and isinstance(r.get("seq"), int)]
        except (OSError, ValueError):
            continue
        last = seen.get(project.pid, -1)
        touched += [_swept(factory, project, r) for r in records
                    if r["seq"] > last and _failure(r) and not _copied(project, r)]
        if records:
            seen[project.pid] = records[-1]["seq"]
    if seen != before:
        write_json(seen_path, seen)
    return touched


def _copied(project: Any, record: dict[str, Any]) -> bool:
    """An automation's run on a project is recorded in the factory's ledger and in the project's: one incident,
    from the project's own record."""
    ev = record.get("event") or {}
    return (project.pid.startswith("_") and ev.get("kind") == "automation_ran"
            and bool((ev.get("payload") or {}).get("project")))


def _failure(record: dict[str, Any]) -> bool:
    ev = record.get("event") or {}
    rule = SWEPT.get(str(ev.get("kind")))
    if rule is None:
        return False
    test = rule[1]
    return test is None or bool(test(ev.get("payload") or {}))


def _swept(factory: Any, project: Any, record: dict[str, Any]) -> str:
    ev = record["event"]
    payload = ev.get("payload") or {}
    where, message = _message(ev["kind"], payload)
    doc = inc.open_incident(factory, kind=SWEPT[ev["kind"]][0], where=where, message=message,
                            project=None if project.pid.startswith("_") else project.pid, by="the ledger sweep",
                            context={"records": [{"seq": record["seq"], "kind": ev["kind"], "at": ev.get("at")}],
                                     "persona": payload.get("persona"),
                                     **{k: payload.get(k) for k in DETAIL.get(ev["kind"], ())}})
    return str(doc["id"])


def next_actions(project: Any) -> list[dict[str, Any]]:
    """Each open incident of the project as a "What's next" action that opens its Incidents view."""
    rows = [i for i in inc.incidents(project.factory, pid=project.pid) if i["state"] not in inc.DONE][:3]
    return [{"id": f"incident:{i['id']}", "label": f"Incident {i['id']}: {i['summary'][:90]}",
             "personas": ["business_owner", "product_owner", "developer", "it", "operations", "compliance"],
             "control": "incidents_open", "view": "incidents", "focus": i["id"]} for i in rows]


def snapshot_part(factory: Any, project: Any) -> dict[str, Any] | None:
    """Open incidents (with their remedies) and the approved assistant rules, for Ask Rihma; None when neither."""
    from kernel import feedback, immune

    pid = project.pid if project is not None else None
    rows = [i for i in inc.incidents(factory, pid=pid) if i["state"] not in inc.DONE][:8]
    rules = [c["to"] for c in feedback.applied(factory, "assistant_rule") if c.get("to")][:10]
    if not rows and not rules:
        return None
    out: dict[str, Any] = {}
    if rows:
        out["incidents"] = [{"id": i["id"], "project": i.get("project"), "state": i["state"], "summary": i["summary"],
                             "class": i.get("class"), "count": i.get("count"),
                             "remedies": [r["label"] for r in immune.offered(factory, i)["remedies"]],
                             "seen_before": immune.offered(factory, i)["seen_before"]} for i in rows]
    if rules:
        out["rules_people_approved"] = rules
    return out


def _resolve_hours(scope: Any, rows: list[dict[str, Any]]) -> list[float]:
    """Hours from opening to resolution, of the incidents resolved in the scope's window."""
    from kernel.insights.base import when

    pairs = [(when(i.get("opened")), when((i.get("resolution") or {}).get("at"))) for i in rows]
    return [round((b - a).total_seconds() / 3600, 1) for a, b in pairs if a and b and scope.inside(b)]


def tiles(scope: Any) -> list[dict[str, Any]]:
    """Insights' self-healing figures for a scope (kernel/insights/base.py ``Scope``)."""
    from kernel import immune
    from kernel.insights.base import tile, when

    rows = inc.incidents(scope.factory, pid=scope.pid, limit=10_000)
    in_window = [i for i in rows if scope.inside(when(i.get("opened")))]
    open_now = [i for i in rows if i["state"] not in inc.DONE]
    hours = _resolve_hours(scope, rows)
    used = sum(1 for r in immune.learned_list(scope.factory, pid=scope.pid) for t in r.get("used_at") or []
               if scope.inside(when(t)))
    href = f"#/p/{scope.pid}/incidents" if scope.pid else "#/incidents"
    return [
        tile("incidents", "Incidents open", len(open_now), sub=f"{len(in_window)} opened in the window",
             basis="heal/incidents: every error, failed job, broken view and report", href=href,
             status="warning" if open_now else "good",
             line=f"{len(open_now)} open: the oldest is {open_now[-1]['id']}." if open_now else "No incident is open."),
        tile("time_to_resolve", "Median time to resolve", statistics.median(hours) if hours else None, unit="h",
             basis="hours from an incident's opening to its resolution, resolved in the window", href=href,
             line=f"{len(hours)} resolved in the window.", why="no incident was resolved in the window",
             how="resolve an incident on the Incidents page: what fixed it is learned"),
        tile("remedies_used", "Learned remedies used", used, basis="uses of approved remedies (heal/remedies.json)",
             href=href, line=f"{used} uses of what Rihmasto learned, in the window."),
    ]
