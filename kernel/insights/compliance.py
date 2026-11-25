"""Compliance: whether each project keeps its posture and has what its posture requires, and what is proven.

- **Posture** is the project's chosen posture (kernel/posture.py): whether the run keeps it (its maturity and
  mode), and what it requires that is missing now (a security scan, a red-team layer, an evidence pack:
  kernel/posture_rules.py, the same rule the security gate applies).
- **Evidence coverage** is each criterion's evidence state (kernel/status.py): verified or held out against
  claimed, failing and not measured.
- **Accepted risks** are ``security/acceptances.json``: a named IT or compliance person's acceptance, until
  its date. An acceptance whose date passed is recorded as ``risk_acceptance_expired``.
- **Overdue assumptions** are the canon's open assumptions past their due date.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

from kernel.insights.base import Scope, answer, chart, first, gap, share, tile
from kernel.insights.lines import count

STATES = ("verified", "held_out", "claimed", "failing", "not_measured")
STATE_WORDS = {"verified": "Verified", "held_out": "Held out", "claimed": "Claimed", "failing": "Failing",
               "not_measured": "Not measured"}
HOW_POSTURE = "choose a posture for the project (rihmasto posture set <pid> <posture> --reason ...)"
NO_POSTURE = "no project in this scope has a posture"
Row = dict[str, Any]


def _posture(p: Any) -> Row | None:
    from kernel.posture import of, track_posture
    from kernel.posture_rules import _missing
    from kernel.security import _scan_ref, latest

    eff = of(p)
    if eff is None:
        return None
    scans = [_scan_ref(k, s) for k, s in latest(p).items()]
    missing = _missing(p, eff, scans)
    return {"project": p, "posture": eff["posture"], "keeps": track_posture(p).get("keeps"),
            "missing": missing, "scan_required": bool(eff["gate"].get("scan")), "scanned": bool(scans)}


def _evidence(p: Any) -> Counter[str]:
    from kernel.status import evidence

    if not p.path("contract.json").exists():
        return Counter()
    return Counter(e["state"] for e in evidence(p))


def _risks(scope: Scope) -> tuple[list[Row], bool]:
    from kernel.security import acceptances, scans

    today = scope.now.date()
    active, any_scan = [], False
    for p in scope.projects:
        any_scan = any_scan or bool(scans(p))
        for a in acceptances(p):
            until = dt.date.fromisoformat(a["expires"])
            if until >= today:
                active.append({"project": p, "id": a["id"], "rule": a.get("rule"), "days": (until - today).days,
                               "expires": a["expires"]})
    return sorted(active, key=lambda a: a["days"]), any_scan


def _context(scope: Scope) -> Row:
    from kernel.canon import Canon

    postures = [x for p in scope.projects if (x := _posture(p)) is not None]
    evidence = {p.pid: _evidence(p) for p in scope.projects}
    risks, any_scan = _risks(scope)
    overdue = [(p, a) for p in scope.projects for a in Canon(p).overdue(scope.now.date())]
    return {"scope": scope, "postures": postures, "evidence": evidence, "risks": risks, "any_scan": any_scan,
            "overdue": overdue, "expired": sum(1 for _ in scope.events("risk_acceptance_expired"))}


def _t_kept(c: Row) -> Row:
    ps = c["postures"]
    kept = sum(1 for x in ps if x["keeps"])
    drift = [x for x in ps if x["keeps"] is False]
    line = (f"{c['scope'].title(drift[0]['project'])} runs looser than its {drift[0]['posture']} posture." if drift
            else f"Every project with a posture keeps it ({kept} of {len(ps)}).")
    return tile("posture_kept", "Posture kept", kept if ps else None, sub=f"of {count(len(ps), 'project')}",
                basis="kernel.posture.track_posture: the maturity and mode the posture runs at",
                status="warning" if drift else "good", line=line, why=NO_POSTURE, how=HOW_POSTURE)


def _t_unmet(c: Row) -> Row:
    ps = c["postures"]
    unmet = [(x["project"], why) for x in ps for _, why in x["missing"]]
    line = (f"{c['scope'].title(unmet[0][0])} still needs {unmet[0][1].split(' (')[0]}." if unmet
            else "Every posture's requirements are there.")
    return tile("posture_unmet", "Posture requirements unmet", len(unmet) if ps else None,
                basis="kernel.posture_rules: a scan, the red-team layers and an evidence pack the posture requires",
                status="critical" if unmet else "good", line=line, why=NO_POSTURE, how=HOW_POSTURE,
                href=f"#/p/{unmet[0][0].pid}/overview" if unmet else None)


def _t_coverage(c: Row) -> Row:
    total: Counter[str] = Counter()
    for counts in c["evidence"].values():
        total.update(counts)
    n = sum(total.values())
    proven = total["verified"] + total["held_out"]
    return tile("coverage", "Criteria proven", share(proven, n), unit="%",
                sub=f"{proven} of {count(n, 'criterion', 'criteria')}",
                basis="kernel.status.evidence: verified or held out, over every criterion",
                line=f"{proven} of {n} criteria are proven; {total['not_measured']} are not measured yet.",
                why="no project in this scope has a compiled contract",
                how="compile the spec into a contract (rihmasto compile <pid>)")


def _t_scans(c: Row) -> Row:
    need = [x for x in c["postures"] if x["scan_required"]]
    have = sum(1 for x in need if x["scanned"])
    line = (f"{have} of {count(len(need), 'project')} whose posture requires a security scan have one." if need
            else "")
    return tile("scans_present", "Required scans present", have if need else None, sub=f"of {len(need)}",
                basis="security/<n>.json scans, for projects whose posture requires one",
                status="good" if have == len(need) else "critical", line=line,
                why="no posture in this scope requires a security scan",
                how="the production and regulated postures require one: rihmasto security ingest <pid> SARIF")


def _t_risks(c: Row) -> Row:
    risks = c["risks"]
    line = (f"{count(len(risks), 'accepted risk')} in force; {first(risks, 'id')} ends in {first(risks, 'days')} days."
            if risks else "No risk is accepted: every finding counts.")
    return tile("accepted_risks", "Accepted risks", len(risks) if c["any_scan"] else None, line=line,
                sub=f"{c['expired']} expired in the window" if c["expired"] else None,
                basis="security/acceptances.json, in force today; risk_acceptance_expired in the window",
                status="warning" if first(risks, "days", 99) < 14 else "good",
                why="no security scan in this scope, so no finding to accept",
                how="ingest a scan (rihmasto security ingest <pid> SARIF); IT or compliance may accept a finding")


def _t_overdue(c: Row) -> Row:
    od = c["overdue"]
    line = (f"{count(len(od), 'assumption')} past due; {od[0][1]['id']} was due {od[0][1]['due']}." if od
            else "No assumption is past its due date.")
    return tile("assumptions_overdue", "Assumptions overdue", len(od) if c["scope"].projects else None,
                basis="the canon's open assumptions past their due date", status="warning" if od else "good", line=line,
                href=f"#/p/{od[0][0].pid}/assumptions/{od[0][1]['id']}" if od else None,
                why="no project in this scope yet", how="create a project (rihmasto new)")


def _charts(c: Row, tiles: list[Row]) -> list[Row]:
    scope = c["scope"]
    rows = [{"label": scope.title(p), "href": f"#/p/{p.pid}/evidence", "values": dict(c["evidence"][p.pid])}
            for p in scope.projects if c["evidence"][p.pid]]
    need = Counter(why.split(" (")[0] for x in c["postures"] for _, why in x["missing"])
    need_rows = [{"label": k, "value": v} for k, v in need.most_common()]
    risk_rows = [{"label": f"{r['id']} · {r['rule'] or 'finding'}", "value": r["days"],
                  "sub": scope.title(r["project"]), "href": f"#/p/{r['project'].pid}/evidence"}
                 for r in c["risks"][:10]]
    return [
        chart("coverage", "Evidence per project" if scope.pid is None else "Evidence per criterion state", "stack100",
              rows=rows, unit="criteria", line=tiles[2]["line"],
              series=[{"key": k, "label": STATE_WORDS[k], "status": {"verified": "good", "held_out": "good",
                                                                     "failing": "critical"}.get(k),
                       "hatch": k == "not_measured", "neutral": k == "claimed"} for k in STATES],
              basis="kernel.status.evidence", why="no project in this scope has a compiled contract",
              how="compile the spec into a contract (rihmasto compile <pid>)"),
        chart("unmet", "What postures still require", "bars", rows=need_rows, unit="projects", line=tiles[1]["line"],
              basis="kernel.posture_rules",
              why=NO_POSTURE if not c["postures"] else "nothing a posture requires is missing",
              how=HOW_POSTURE if not c["postures"] else "nothing to do"),
        chart("risks", "Accepted risks by days left", "bars", rows=risk_rows, unit="days", line=tiles[5]["line"],
              basis="security/acceptances.json", why="no accepted risk is in force",
              how="IT or compliance accepts a finding with a reason and a date (rihmasto security accept)"),
    ]


def read(scope: Scope) -> dict[str, Any]:
    c = _context(scope)
    tiles = [_t_kept(c), _t_unmet(c), _t_coverage(c), _t_scans(c), _t_overdue(c), _t_risks(c)]
    gaps = [gap("Controls mapped to a regulation", "Rihmasto records the evidence a reviewer judges and claims no "
                "conformity (kernel/evidence_pack.py)", "export an evidence pack (rihmasto evidence <pid> --out DIR) "
                "and map its control table in your own compliance tool")]
    return answer(scope, "compliance", tiles, _charts(c, tiles), gaps)
