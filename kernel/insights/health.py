"""Health: where each project stands, how long it has gone without a step, what failed, and whether what runs answers.

- **State** is kernel/status.py's health per project (on track, at risk, off track, with each reason) and the
  pipeline's stage.
- **Idle time** is how long ago a project's ledger last recorded a step, for a project that is not paused.
- **Failures** are the ledger's failure records in the window: an endpoint that failed (``apparatus_failure``), a
  release that stopped, a probe that failed, a run that could not be ingested, a refused scan or sync.
- **Checks** are each enabled check's last result (kernel/checks, FR-CHK1: what its ``check_ran`` recorded, read
  through ``kernel.checks.last_results``): failed counts as failing, not measured is said apart; not measured
  before a check ran.
- **Probes** are the latest probe of what runs: ``ops/tick.json`` (kernel/operate.py) and an adopted service's
  ``probed`` record.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

from kernel.insights.base import Scope, answer, chart, first, gap, hours, series_rows, tile, unit_of, when
from kernel.insights.lines import count, top
from kernel.store import STAGES

FAILURE_KINDS = {"apparatus_failure": "endpoint failed", "release_failed": "release stopped",
                 "probe_failed": "probe failed", "gnomon_run_not_ingested": "run not ingested",
                 "security_scan_refused": "scan refused", "upstream_sync_failed": "sync failed",
                 "embed_triage_failed": "embed triage failed", "merge_rejected": "merge rejected"}
CHECK_KINDS = ("check_ran",)
IDLE_HOURS = 48
STATE_WORDS = {"on_track": "On track", "at_risk": "At risk", "off_track": "Off track"}
NO_PROJECT = "no project in this scope yet"
Row = dict[str, Any]


def _last(scope: Scope, project: Any) -> dt.datetime | None:
    times = [t for r in scope.records(project) if (t := when(r["event"].get("at"))) is not None]
    return max(times) if times else None


def _state(scope: Scope, p: Any) -> Row:
    from kernel.status import health

    try:
        h = health(p)
    except Exception as exc:  # noqa: BLE001 - one project's unreadable record never hides the others
        h = {"status": None, "reasons": [f"could not be read: {type(exc).__name__}"]}
    return {"project": p, "status": h.get("status"), "reasons": h.get("reasons") or [], "stage": p.meta.get("stage", 1),
            "paused": bool(p.meta.get("pause")), "idle": hours(_last(scope, p), scope.now)}


def _checks(scope: Scope) -> tuple[list[Row], str]:
    """Each enabled check's last result (kernel/checks, FR-CHK1): the result its ``check_ran`` recorded."""
    from kernel.checks import last_results

    found: list[Row] = []
    for p in scope.projects:
        try:
            found += [dict(r, project=p.pid, name=r["check"]) for r in last_results(p)]
        except (OSError, ValueError, KeyError):   # one project's unreadable checks never hide the others
            continue
    return found, "kernel.checks.last_results: each enabled check's last " + CHECK_KINDS[0]


def _probe(scope: Scope, p: Any) -> Row | None:
    tick = p.read("ops/tick.json") or {}
    latest = None
    for res in tick.get("probes") or []:
        # a scheduled job's probe is its latest finished execution (kernel/roads_gcp_ops.py): one still running,
        # or none finished yet, is not measured and not counted as answering
        if isinstance(res, dict) and res.get("verdict") not in ("not applicable", "not measured"):
            latest = {"project": p, "ok": bool(res.get("ok")), "at": when(tick.get("at"))}
    adopted = [(t, pl) for q, t, pl, _ in scope.every("probed") if q.pid == p.pid]
    if adopted:
        t, pl = adopted[-1]
        if latest is None or (t and latest["at"] and t > latest["at"]):
            latest = {"project": p, "ok": pl.get("verdict") == "passed", "at": t}
    return latest


def _context(scope: Scope) -> Row:
    states = [_state(scope, p) for p in scope.projects]
    checks, basis = _checks(scope)
    return {"scope": scope, "states": states, "counts": Counter(s["status"] for s in states),
            "risky": [s for s in states if s["status"] in ("at_risk", "off_track")],
            "idle": sorted((s for s in states if not s["paused"] and s["idle"] is not None), key=lambda s: -s["idle"]),
            "failures": [(t, rec["event"]["kind"]) for _, t, _, rec in scope.events(*FAILURE_KINDS)],
            "checks": checks, "check_basis": basis,
            "probes": [x for p in scope.projects if (x := _probe(scope, p)) is not None]}


def _t_risk(c: Row) -> Row:
    risky, states = c["risky"], c["states"]
    line = "Every project is on track."
    if risky:
        r = risky[0]
        why = r["reasons"][0] if r["reasons"] else "see its health"
        line = f"{c['scope'].title(r['project'])} is {STATE_WORDS[r['status']].lower()}: {why}."
    status = "good" if not risky else "critical" if c["counts"].get("off_track") else "warning"
    href = f"#/p/{risky[0]['project'].pid}/overview" if risky else None
    return tile("at_risk", "At risk or off track", len(risky) if states else None,
                sub=f"of {count(len(states), 'project')}", basis="kernel.status.health per project", status=status,
                line=line, why=NO_PROJECT, href=href, how="create a project (rihmasto new)")


def _t_idle(c: Row) -> Row:
    idle = c["idle"]
    most = first(idle, "idle")
    line = f"Every running project recorded a step within {IDLE_HOURS} hours."
    if idle and most >= IDLE_HOURS:
        line = f"{c['scope'].title(idle[0]['project'])} has had no recorded step for {most} hours."
    return tile("idle", "Longest without a step", most, unit="h",
                status="warning" if (most or 0) >= IDLE_HOURS else "good",
                basis="hours since the project's ledger last recorded a step (paused projects left out)", line=line,
                href=f"#/p/{idle[0]['project'].pid}/overview" if idle else None,
                why="no running project has a ledger record", how="create a project and let the pipeline run")


def _t_failures(c: Row) -> Row:
    fails = c["failures"]
    rows = [{"label": FAILURE_KINDS[k], "value": v} for k, v in Counter(k for _, k in fails).items()]
    return tile("failures", "Failures", len(fails) if c["states"] else None, status="warning" if fails else "good",
                basis="ledger failure records in the window: " + ", ".join(FAILURE_KINDS),
                line=top("the failures", rows) or "Nothing failed in the window.", why=NO_PROJECT,
                how="create a project (rihmasto new)")


def _t_checks(c: Row) -> Row:
    checks = c["checks"]
    failing = [x for x in checks if x.get("verdict") == "failed"]
    unmeasured = [x for x in checks if x.get("verdict") == "not measured"]
    line = (f"{count(len(failing), 'check')} failed its last run." if failing
            else f"{count(len(unmeasured), 'check')} could not measure on its last run." if unmeasured
            else f"Every check passed its last run ({len(checks)}).")
    sub = f"of {count(len(checks), 'check')}" + (f", {len(unmeasured)} not measured" if unmeasured else "")
    return tile("checks", "Checks failing", len(failing) if checks else None, sub=sub,
                basis=c["check_basis"], status="critical" if failing else "warning" if unmeasured else "good",
                line=line, why="no check enabled here has run yet",
                how="enable a check on a project's Health tab (rihmasto checks enable <pid> <check>): its last "
                    "result shows here", href="#/health" if checks else None)


def _t_probes(c: Row) -> Row:
    probes = c["probes"]
    ok = sum(1 for x in probes if x["ok"])
    return tile("probes", "Probes answering", ok if probes else None, sub=f"of {count(len(probes), 'release')}",
                basis="ops/tick.json probes and probed records: the latest per project",
                status="good" if ok == len(probes) else "critical",
                line=f"{ok} of {count(len(probes), 'probed release')} answer their probes.",
                why="nothing deployed here has been probed",
                how="deliver a release to production and run operations (rihmasto operate <pid>), or adopt a running "
                    "service")


def _charts(c: Row, tiles: list[Row]) -> list[Row]:
    scope, states = c["scope"], c["states"]
    stages = Counter(s["stage"] for s in states)
    stage_rows = [{"label": f"{n} {STAGES[n]}", "value": stages.get(n, 0)} for n in STAGES] if states else []
    state_rows = [{"label": "All projects", "values": {k: c["counts"].get(k, 0) for k in STATE_WORDS}}]
    state_rows = state_rows if states else []
    idle_rows = [{"label": scope.title(s["project"]), "value": s["idle"], "href": f"#/p/{s['project'].pid}/ledger"}
                 for s in c["idle"][:10]]
    return [
        chart("state", "Projects by health", "stack100", unit="projects",
              rows=state_rows,
              series=[{"key": "on_track", "label": "On track", "status": "good"},
                      {"key": "at_risk", "label": "At risk", "status": "warning"},
                      {"key": "off_track", "label": "Off track", "status": "critical"}],
              basis="kernel.status.health per project", line=tiles[0]["line"], why=NO_PROJECT, how="create a project"),
        chart("stages", "Projects by stage", "bars", unit="projects", rows=stage_rows,
              basis="each project's current stage (project.json)", line=top("the stages", stage_rows, "projects"),
              why=NO_PROJECT, how="create a project"),
        chart("idle", "Time without a recorded step", "bars", unit="hours", rows=idle_rows,
              basis="hours since each project's last ledger record", line=tiles[1]["line"],
              why="no running project has a ledger record", how="create a project and let the pipeline run"),
        chart("failures", "Failures over time", "columns", unit="failures",
              rows=series_rows(scope, [(t, "failures", 1) for t, _ in c["failures"]]),
              series=[{"key": "failures", "label": "Failures", "status": "critical"}],
              basis="ledger failure records per " + unit_of(scope.window), line=tiles[2]["line"],
              why="nothing failed in the window", how="nothing to do: a failure record appears here when one happens"),
    ]


def read(scope: Scope) -> dict[str, Any]:
    c = _context(scope)
    from kernel.heal_wiring import tiles as heal_tiles  # incidents, time to resolve, remedies used (FR-HEAL1)

    tiles = [_t_risk(c), _t_idle(c), _t_failures(c), _t_checks(c), _t_probes(c), *heal_tiles(c["scope"])]
    gaps = [gap("Background jobs started from the cockpit", "they are kept in the cockpit's memory while it runs and "
                "not written to a ledger", "see them on the Jobs page while the cockpit runs")]
    return answer(scope, "health", tiles, _charts(c, tiles), gaps)
