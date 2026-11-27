"""What the cockpit, the command line, Insights, Review and goal help read of Gnomon's audits and evals (FR-EVL1).

Read only: nothing here runs an eval or writes a file. Each eval on a project shows its last result (passed,
failed, or not measured with why: never passed when nothing was measured), its trend over the last runs, its
findings (new ones marked, each with a Make it a change action) and whether it runs as a scheduled check.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from kernel import gnomon_evals as ge
from kernel import gnomon_evals_run as gr
from kernel.store import Factory, Project

TREND = 10


def _scheduled(project: Project) -> dict[str, str | None]:
    from kernel.checks import store as cstore

    try:
        return {k.split(":")[0].removeprefix("gnomon_"): e.get("every") for k, e in cstore.enabled(project).items()
                if k.startswith("gnomon_")}
    except (OSError, ValueError):
        return {}


def _requests(project: Project) -> list[dict[str, Any]]:
    kept = project.read("evals/requests.json", {}) or {}
    return [{"request": k, **{f: v.get(f) for f in ("eval", "state", "at", "person")}} for k, v in kept.items()
            if v.get("state") in ("requested", "running")]


def project_view(project: Project) -> dict[str, Any]:
    scheduled = _scheduled(project)
    made = gr.changes(project)
    # asked and carried by a job: running from the press on (a request never carried stops counting after 2 hours)
    cut = (project.factory.clock.now() - dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    pending = {r["eval"] for r in _requests(project) if str(r.get("at") or "") >= cut}
    rows = []
    for entry in ge.public(project):
        trend = gr.results(project, entry["id"], TREND)
        last = trend[-1] if trend else None
        if last:
            last = dict(last, findings=[dict(f, card=made.get(f["id"])) for f in last.get("findings") or []])
        rows.append({**entry, "last": last, "state": last["verdict"] if last else "not run yet",
                     "running": gr.running(project, entry["id"]) or entry["id"] in pending,
                     "scheduled": entry["id"] in scheduled,
                     "every": scheduled.get(entry["id"], entry["every"]),
                     "trend": [{"verdict": r["verdict"], "at": r["at"], "score": r.get("scores", {}).get(
                         ge.BY_ID[entry["id"]].score)} for r in trend]})
    ran = [r for r in rows if r["last"]]
    new = sum(r["last"]["new_findings"] for r in ran)
    return {"project": project.pid, "title": project.meta.get("title"), "evals": rows, "gnomon": _gnomon(),
            "findings": gr.findings(project), "requests": _requests(project), "line": line(ran, new),
            "counts": counts(rows)}


def _gnomon() -> dict[str, Any]:
    seen = ge.detect()
    return {"found": seen["found"], "version": seen["version"], "source": str(ge.source_dir() or "") or None}


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many audits stand at each state: the checks' own count (kernel/checks/health.py)."""
    from kernel.checks.health import counts as by_state

    return by_state(rows)


def line(ran: list[dict[str, Any]], new: int) -> str:
    if not ran:
        return "no Gnomon audit has run here yet"
    failing = [r["label"] for r in ran if r["state"] == "failed"]
    said = f"{len(failing)} failing: {', '.join(failing)}" if failing else f"{len(ran)} audit(s) ran, none failing"
    return said + (f"; {new} new issue(s) in their latest runs" if new else "")


def factory_view(factory: Factory) -> dict[str, Any]:
    projects = []
    for p in factory.projects():
        if p.pid.startswith("_"):
            continue
        last = gr.latest(p)
        projects.append({"project": p.pid, "title": p.meta.get("title"), "line": line(
            [{"label": r.get("label"), "state": r["verdict"]} for r in last.values()],
            sum(r.get("new_findings", 0) for r in last.values())),
            "results": [{"eval": k, "label": r.get("label"), "verdict": r["verdict"], "summary": r["summary"],
                         "at": r["at"], "new_findings": r.get("new_findings", 0)} for k, r in sorted(last.items())]})
    return {"projects": projects, "catalogue": ge.public(), "gnomon": _gnomon()}


def history(project: Project, eid: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    if eid:
        ge.find(eid)
    rows = gr.results(project, ge.find(eid).id if eid else None, limit)
    return [{k: r.get(k) for k in ("eval", "at", "verdict", "summary", "scores", "issues", "new_findings", "resolved",
                                   "via", "by", "gnomon")} for r in rows]


def next_action(project: Project) -> dict[str, Any] | None:
    """For What's next: an audit's latest run found new issues."""
    found = [f for f in gr.findings(project) if f.get("new") and f["severity"] == "issue" and not f.get("card")]
    if not found:
        return None
    return {"id": "evals_new_issues", "label": f"An audit found {len(found)} new issue(s): {found[0]['title']}"[:200],
            "personas": list(gr.ENABLERS), "control": "evals_make_change", "view": "checks",
            "command": f"rihmasto evals findings {project.pid}"}
