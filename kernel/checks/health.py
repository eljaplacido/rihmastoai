"""Health (FR-CHK1): each enabled check's last result, its trend and when it last ran, per project and across
the factory; and what feeds What's next ("2 checks failing: Dependency audit, CI/CD status") and Home.

Read only: nothing here runs a check or writes a file. A check that never ran is "not run yet", and a
not measured result is shown as not measured with why, never as passed.
"""

from __future__ import annotations

from typing import Any

from kernel.checks import catalogue, public
from kernel.checks import store as cstore
from kernel.store import Factory, Project

TREND = 10


def _row(project: Project, key: str, entry: dict[str, Any]) -> dict[str, Any]:
    check = catalogue().get(entry.get("kind") or key.split(":")[0])
    rows = cstore.results(project, key, TREND)
    last = rows[-1] if rows else None
    name = key.split(":", 1)[1] if ":" in key else None
    return {"check": key, "kind": entry.get("kind"), "label": (check.label if check else key) + (f" ({name})" if name
                                                                                                 else ""),
            "what": check.what if check else "", "config": entry.get("config") or {}, "every": entry.get("every"),
            "on_fail": entry.get("on_fail") or [], "enabled_by": {k: entry.get("by", {}).get(k)
                                                                   for k in ("person", "persona", "at")},
            "runs_code": bool(check and check.runs_code), "running": cstore.running(project, key),
            "last": last, "state": last["verdict"] if last else "not run yet",
            "trend": [{"verdict": r["verdict"], "at": r["at"]} for r in rows]}


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out = {"passed": 0, "failed": 0, "not measured": 0, "not run yet": 0}
    for r in rows:
        out[r["state"]] = out.get(r["state"], 0) + 1
    return out


def project_health(project: Project) -> dict[str, Any]:
    from kernel.checks.recommend import for_project

    on = cstore.enabled(project)
    rows = [_row(project, key, entry) for key, entry in sorted(on.items())]
    failing = [r["label"] for r in rows if r["state"] == "failed"]
    return {"project": project.pid, "title": project.meta.get("title"), "checks": rows, "counts": counts(rows),
            "failing": failing, "line": line(rows), "catalogue": public(), "recommended": for_project(project, on)}


def line(rows: list[dict[str, Any]]) -> str:
    """One sentence for What's next and Home."""
    failing = [r["label"] for r in rows if r["state"] == "failed"]
    unmeasured = [r["label"] for r in rows if r["state"] == "not measured"]
    if failing:
        return f"{len(failing)} check{'s' if len(failing) != 1 else ''} failing: {', '.join(failing)}"
    if unmeasured:
        return f"{len(unmeasured)} check{'s' if len(unmeasured) != 1 else ''} not measured: {', '.join(unmeasured)}"
    if rows and all(r["state"] == "passed" for r in rows):
        return f"all {len(rows)} checks passing"
    return "no check has run yet" if rows else "no check enabled"


def factory_health(factory: Factory) -> dict[str, Any]:
    projects = []
    for project in factory.projects():
        if project.pid.startswith("_"):
            continue
        h = project_health(project)
        projects.append({k: h[k] for k in ("project", "title", "checks", "counts", "failing", "line")})
    rows = [r for p in projects for r in p["checks"]]
    failing = [f"{p['project']}: {label}" for p in projects for label in p["failing"]]
    return {"projects": projects, "counts": counts(rows), "failing": failing, "catalogue": public(),
            "line": (f"{len(failing)} check{'s' if len(failing) != 1 else ''} failing across the factory"
                     if failing else line(rows))}


def next_action(project: Project) -> dict[str, Any] | None:
    """The What's next action when checks fail on the project: open Health and run them again."""
    rows = project_health(project)["checks"]
    failing = [r for r in rows if r["state"] == "failed"]
    if not failing:
        return None
    return {"id": "checks_failing", "label": line(rows), "personas": list(cstore.ENABLERS), "control": "health_run",
            "view": "checks", "command": f"rihmasto checks run {project.pid} {failing[0]['check']} --person ... "
                                         "--persona ..."}


def with_failing(project: Project, nxt: dict[str, Any]) -> dict[str, Any]:
    """What's next (kernel/next_step.py) with the failing checks said, when there are any."""
    try:
        act = next_action(project)
    except (OSError, ValueError):
        return nxt
    return dict(nxt, actions=list(nxt.get("actions") or []) + [act]) if act else nxt
