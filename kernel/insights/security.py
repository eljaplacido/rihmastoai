"""Security: findings by severity and state, what the gate blocked, secrets, the red team and confidential work.

- **Findings** are each tool's latest SARIF scan per scope (kernel/security.py), open or accepted; over time,
  what each ``security_scan`` found by level.
- **Gate blocks** are the ledger's ``security_gate`` records whose verdict failed.
- **Secrets** are open findings whose rule names a secret, credential, password, key or token (the red team's
  secret scan, kernel/redteam/secretscan.py, or any scanner's).
- **The red team** is Rihmasto's own static and agentic layers, ingested as SARIF (``Rihmasto red team (...)``).
- **Confidential work** is a project kept on local models (kernel/confidential.py): refusals of a hosted call
  (``confidential_refused``) and roles worked by rule because their endpoint is hosted (``confidential_by_rule``).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from kernel.insights.base import Scope, answer, chart, gap, series_rows, tile, unit_of
from kernel.insights.lines import count, top

LEVELS = ("error", "warning", "note")
LEVEL_STATUS = {"error": "critical", "warning": "serious", "note": "warning"}
LEVEL_WORDS = {"error": "Error", "warning": "Warning", "note": "Note"}
SECRET = re.compile(r"secret|credential|password|api[-_ ]?key|private[-_ ]?key|token", re.I)
REDTEAM = "Rihmasto red team"
HOW_SCAN = "ingest a SARIF scan (rihmasto security ingest <pid> FILE), or run the red team's static layer " \
           "(python -m kernel.redteam static <source> --sarif OUT)"
NO_SCAN = "no security scan in this scope"
Row = dict[str, Any]


def _findings(scope: Scope) -> list[Row]:
    from kernel.security import findings

    return [dict(f, project=p) for p in scope.projects for f in findings(p)]


def _tool(f: Row) -> str:
    return str((f.get("tool") or {}).get("name") or "")


def _context(scope: Scope) -> Row:
    from kernel.confidential import confidential
    from kernel.security import scans

    scanned = [p for p in scope.projects if scans(p)]
    found = _findings(scope)
    return {"scope": scope, "scanned": scanned, "findings": found, "open": [f for f in found if f["state"] == "open"],
            "blocks": [pl for _, _, pl, _ in scope.events("security_gate") if pl.get("verdict") == "failed"],
            "gates": sum(1 for _ in scope.events("security_gate")),
            "scan_events": [(t, pl) for _, t, pl, _ in scope.events("security_scan")],
            "confidential": [p for p in scope.projects if confidential(p)],
            "refused": sum(1 for _ in scope.events("confidential_refused")),
            "by_rule": sum(1 for _ in scope.events("confidential_by_rule"))}


def _t_open(c: Row) -> Row:
    op = c["open"]
    errors = sum(1 for f in op if f.get("level") == "error")
    verb = "blocks" if errors == 1 else "block"
    line = (f"{count(errors, 'open error')} {verb} a landing; {count(len(op), 'finding')} open in all." if errors
            else f"No open error; {count(len(op), 'finding')} open at lower levels." if op else "No open finding.")
    return tile("open_findings", "Open findings", len(op) if c["scanned"] else None, sub=f"{errors} at error",
                basis="each tool's latest scan per scope (kernel/security.findings)",
                status="critical" if errors else "warning" if op else "good", line=line, why=NO_SCAN, how=HOW_SCAN)


def _t_blocks(c: Row) -> Row:
    n = len(c["blocks"])
    line = (f"The security gate blocked {count(n, 'time')} in the window." if n
            else "The security gate blocked nothing in the window.")
    return tile("gate_blocks", "Gate blocks", n if c["gates"] else None, sub=f"of {count(c['gates'], 'verdict')}",
                basis="ledger security_gate records with a failed verdict", status="warning" if n else "good",
                line=line, why="the security gate gave no verdict in the window",
                how="the gate runs before every landing on staging or production, and where a posture requires a scan")


def _t_secrets(c: Row) -> Row:
    hits = [f for f in c["open"] if SECRET.search(str(f.get("rule") or ""))]
    line = "No open finding names a secret."
    if hits:
        verb = "names" if len(hits) == 1 else "name"
        line = f"{count(len(hits), 'open finding')} {verb} a secret; the first is {hits[0]['id']} ({hits[0].get('rule')})."
    return tile("secret_hits", "Secret findings", len(hits) if c["scanned"] else None, line=line,
                basis="open findings whose rule names a secret, credential, password, key or token",
                status="critical" if hits else "good", why=NO_SCAN, how=HOW_SCAN)


def _t_redteam(c: Row) -> Row:
    rt = [f for f in c["findings"] if _tool(f).startswith(REDTEAM)]
    ran = any(_tool(f).startswith(REDTEAM) for f in c["findings"]) or _redteam_scans(c)
    open_rt = [f for f in rt if f["state"] == "open"]
    return tile("redteam", "Red-team findings open", len(open_rt) if ran else None,
                basis="findings from the red team's own SARIF (static and agentic layers)",
                status="critical" if open_rt else "good",
                line=f"The red team has {count(len(open_rt), 'open finding')} of {len(rt)} it reported.",
                why="the red team has not been run and ingested here",
                how="python -m kernel.redteam static <source> --sarif OUT, then rihmasto security ingest <pid> OUT")


def _redteam_scans(c: Row) -> bool:
    return any(str(t).startswith(REDTEAM) for _, pl in c["scan_events"] for t in [pl.get("tool")])


def _t_confidential(c: Row) -> Row:
    conf = c["confidential"]
    line = (f"{count(len(conf), 'confidential project')}: {c['refused']} hosted call(s) refused, "
            f"{c['by_rule']} role(s) worked by rule." if conf else "No project here is confidential.")
    return tile("confidential", "Confidential projects", len(conf), sub=f"{c['refused']} refused in the window",
                basis="project.json confidential; ledger confidential_refused and confidential_by_rule",
                status="warning" if c["refused"] else None, line=line)


def _level_rows(c: Row) -> list[Row]:
    rows = []
    for lvl in LEVELS:
        states = Counter(f["state"] for f in c["findings"] if f.get("level") == lvl)
        if states:
            rows.append({"label": LEVEL_WORDS[lvl], "values": {"open": states.get("open", 0),
                                                               "accepted": states.get("accepted", 0)}})
    return rows


def _charts(c: Row, tiles: list[Row]) -> list[Row]:
    scope = c["scope"]
    points = [(t, lvl, n) for t, pl in c["scan_events"] for lvl, n in (pl.get("counts") or {}).items()
              if lvl in LEVELS and isinstance(n, int) and n]
    rules = Counter(str(f.get("rule") or "unnamed") for f in c["open"])
    rule_rows = [{"label": k, "value": v} for k, v in rules.most_common(10)]
    return [
        chart("by_level", "Findings by severity and state", "stack100", rows=_level_rows(c), unit="findings",
              series=[{"key": "open", "label": "Open", "status": "critical"},
                      {"key": "accepted", "label": "Accepted as a risk", "neutral": True}],
              basis="each tool's latest scan per scope", line=tiles[0]["line"], why=NO_SCAN, how=HOW_SCAN),
        chart("over_time", "What each scan found", "columns", rows=series_rows(scope, points), unit="findings",
              series=[{"key": lvl, "label": LEVEL_WORDS[lvl], "status": LEVEL_STATUS[lvl]} for lvl in LEVELS],
              basis="ledger security_scan counts by level, per " + unit_of(scope.window),
              line=f"{count(len(c['scan_events']), 'scan')} in the window.", why="no scan was ingested in the window",
              how=HOW_SCAN),
        chart("rules", "Open findings by rule", "bars", rows=rule_rows, unit="findings",
              line=top("the open findings", rule_rows), basis="the open findings' rule ids",
              why="no open finding" if c["scanned"] else NO_SCAN,
              how=HOW_SCAN if not c["scanned"] else "nothing to do"),
    ]


def read(scope: Scope) -> dict[str, Any]:
    c = _context(scope)
    tiles = [_t_open(c), _t_blocks(c), _t_secrets(c), _t_redteam(c), _t_confidential(c)]
    gaps = [gap("Runtime attacks on what runs", "Rihmasto probes a release against its criteria; it is not a "
                "runtime security monitor (D-0017, D-0023)", "send your service's logs to your SIEM; its alerts come "
                "back as signals (rihmasto signal log) that become incidents")]
    return answer(scope, "security", tiles, _charts(c, tiles), gaps)
