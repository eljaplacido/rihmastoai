"""The security gate: open findings at a blocking level block; a person may accept a risk until a date.

Findings come from SARIF scans (`adapters/sarif.py`). What counts is the latest scan of each tool
and scope (the run's category and extensions: CodeQL for Python and CodeQL for JavaScript are two
scopes), so a clean scan of one target never hides the open errors of another. A finding the tool
no longer reports in that scope is gone. A finding is

- **open**, or
- **accepted**: a named person with the `it` or `compliance` persona accepted it as a risk, with
  a reason and an expiry date. The acceptance follows the finding (by its fingerprint) into later
  scans. When the date passes, or the tool reports the finding at a more severe level than the
  one accepted, the finding is open again.

`security_gate` blocks while any open finding sits at a blocking level (`error` by default) and
records its verdict. With no scan at all it says "not measured: no security scan", never "passed".
The capability pack and the evidence pack name the latest scan through `summary`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import is_person

ACCEPTORS = ("it", "compliance")
LEVELS = ("error", "warning", "note", "none")
NO_SCAN = "not measured: no security scan"


def scans(project: Any) -> list:
    folder = project.path("security")
    if not folder.exists():
        return []
    numbers = sorted(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit())
    return [project.read(f"security/{n}.json") for n in numbers]


def tool_key(tool: dict) -> tuple[str, str]:
    """A tool's scans are told apart by its name and scope (empty when the run gives none)."""
    return str(tool["name"]), str(tool.get("scope") or "")


def latest(project: Any) -> dict:
    """Each tool's latest scan, by (tool name, scope). A scan stored before scopes were recorded
    (no `keyed_by`) gives way to any later scan of the same tool, as it did then."""
    out: dict[tuple[str, str], dict] = {}
    unscoped: set[tuple[str, str]] = set()
    for scan in scans(project):
        for tool in scan.get("tools", []):
            for old in [k for k in unscoped if k[0] == tool["name"]]:
                out.pop(old, None)
                unscoped.discard(old)
            key = tool_key(tool)
            out[key] = scan
            if not scan.get("keyed_by"):
                unscoped.add(key)
    return out


def acceptances(project: Any) -> list:
    return project.read("security/acceptances.json", []) or []


def _today(project: Any) -> dt.date:
    return project.factory.clock.today()


def _acceptance_for(finding: dict, items: list) -> dict | None:
    hits = [a for a in items if a["fingerprint"] == finding["fingerprint"]]
    return hits[-1] if hits else None


def _more_severe(level: object, accepted: object) -> bool:
    """Whether ``level`` is more severe than the level a person accepted (an unknown one is)."""
    if level not in LEVELS or accepted not in LEVELS:
        return True
    return LEVELS.index(str(level)) < LEVELS.index(str(accepted))


def _judged(row: dict, acc: dict | None, today: dt.date) -> dict:
    """The row with its state: accepted only while the acceptance runs and covers the level."""
    row["acceptance"] = acc
    row["state"] = "open"
    if acc is None:
        return row
    if dt.date.fromisoformat(acc["expires"]) < today:
        row["acceptance_expired"] = True
    elif _more_severe(row["level"], acc.get("level")):
        row["acceptance_level_exceeded"] = True
    else:
        row["state"] = "accepted"
    return row


def findings(project: Any, *, state: str | None = None) -> list:
    """The current findings (each tool's latest scan per scope), each with its state and acceptance."""
    items, today, out = acceptances(project), _today(project), []
    for key, scan in sorted(latest(project).items()):
        for f in scan.get("findings", []):
            if tool_key(f["tool"]) != key:
                continue
            row = _judged(dict(f, scan=scan["scan"]), _acceptance_for(f, items), today)
            if state is None or row["state"] == state:
                out.append(row)
    return out


def accept_risk(project: Any, finding: str, *, person: str, persona: str, reason: str, expires: Any) -> dict:
    """A person accepts an open finding as a risk until ``expires`` (an ISO date). Recorded."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person; accepting a risk is a person's decision")
    if persona not in ACCEPTORS:
        raise DecisionRefused(f"a {persona} may not accept a security risk; {', '.join(ACCEPTORS)} may")
    if not str(reason or "").strip():
        raise DecisionRefused("accepting a risk needs a reason")
    try:
        until = expires if isinstance(expires, dt.date) else dt.date.fromisoformat(str(expires))
    except ValueError as exc:
        raise DecisionRefused(f"the expiry must be a date (YYYY-MM-DD), got {expires!r}") from exc
    if until <= _today(project):
        raise DecisionRefused(f"the expiry {until.isoformat()} is not after today: "
                              "an acceptance must end in the future")
    from kernel.posture_rules import not_a_risk

    current, required = findings(project), not_a_risk(finding)
    if required:   # what a posture requires (POSTURE-*) is not a finding
        raise DecisionRefused(required)
    f = next((x for x in current if finding in (x["id"], x["fingerprint"])), None)
    if f is None:
        raise KeyError(f"no current finding {finding!r}")
    items = acceptances(project)
    acc = {"id": f"RA-{len(items) + 1:03d}", "finding": f["id"], "fingerprint": f["fingerprint"], "rule": f["rule"],
           "level": f["level"], "tool": f["tool"], "location": f["location"], "person": person, "persona": persona,
           "reason": str(reason).strip(), "expires": until.isoformat(), "at": project.factory.clock.stamp()}
    items.append(acc)
    project.write("security/acceptances.json", items)
    project.log("risk_accepted", {k: acc[k] for k in ("id", "finding", "fingerprint", "rule", "level", "person",
                                                       "persona", "reason", "expires")} | {"tool": f["tool"]["name"]})
    return acc


def _brief(f: dict) -> dict:
    loc = f.get("location") or {}
    return {"id": f["id"], "rule": f["rule"], "level": f["level"], "tool": f["tool"]["name"],
            "where": f"{loc.get('uri')}:{loc.get('line')}" if loc.get("uri") else None, "cwe": f.get("cwe", [])}


def _reopened(f: dict) -> dict:
    """A finding whose acceptance no longer holds, and why."""
    acc = f["acceptance"]
    out = _brief(f) | {"accepted_by": acc["person"]}
    if f.get("acceptance_expired"):
        return out | {"expired": acc["expires"], "why": f"the acceptance expired on {acc['expires']}"}
    return out | {"accepted_level": acc.get("level"),
                  "why": f"accepted at level {acc.get('level')}, now reported at {f['level']}"}


def _scan_ref(key: tuple[str, str], scan: dict) -> dict:
    """The tool (and its scope, when it has one) and the scan that counts for it."""
    return {"tool": key[0], "scan": scan["scan"], "sha256": scan["sha256"]} | ({"scope": key[1]} if key[1] else {})


def _record_expiries(project: Any) -> None:
    """Record each acceptance whose date passed, once, saying what its end means: the finding is
    open again only when this was its current acceptance and a scan still reports it."""
    items, today = acceptances(project), _today(project)
    due = [a for a in items if dt.date.fromisoformat(a["expires"]) < today and not a.get("expiry_recorded")]
    if not due:
        return
    reported = {f["fingerprint"] for f in findings(project)}
    groups: dict[str, list[str]] = {}
    for a in due:
        a["expiry_recorded"] = project.factory.clock.stamp()
        replaced = _acceptance_for(a, items) is not a
        if replaced:
            why = "the expiry passed; a later acceptance of the same finding replaced this one"
        elif a["fingerprint"] not in reported:
            why = "the expiry passed; no current scan reports the finding"
        else:
            why = "the expiry passed: the finding is open again"
        groups.setdefault(why, []).append(a["id"])
    project.write("security/acceptances.json", items)
    for why, ids in groups.items():
        project.log("risk_acceptance_expired", {"acceptances": ids, "why": why})


def _measured(project: Any, block_on: tuple, newest: dict) -> dict:
    """The gate's verdict over the current findings: failed while one is open at a blocking level."""
    rows = findings(project)
    blocking = [_brief(f) for f in rows if f["state"] == "open" and f["level"] in block_on]
    reopened = [_reopened(f) for f in rows if f.get("acceptance_expired") or f.get("acceptance_level_exceeded")]
    accepted = [_brief(f) | {"until": f["acceptance"]["expires"], "by": f["acceptance"]["person"]}
                for f in rows if f["state"] == "accepted"]
    return {"verdict": "failed" if blocking else "passed", "blocked": bool(blocking), "block_on": list(block_on),
            "reason": (f"{len(blocking)} open finding(s) at {', '.join(block_on)}" if blocking
                       else f"no open finding at {', '.join(block_on)}"),
            "blocking": blocking, "accepted": accepted, "reopened": reopened,
            "scans": [_scan_ref(k, s) for k, s in sorted(newest.items())]}


def security_gate(project: Any, *, block_on: Any = None, record: bool = True, posture: bool = True) -> dict:
    """passed, failed (open findings at a blocking level), or not measured (no scan). ``block_on`` left
    out is the project's posture's levels, else errors; what the posture requires and is missing (a scan,
    a red-team layer, an evidence pack before production) blocks too (kernel/posture_rules.py), unless
    ``posture`` is False (a pack's summary of the findings)."""
    from kernel.posture_rules import block_on as posture_levels
    from kernel.posture_rules import gate_requirements

    block_on = tuple(block_on or posture_levels(project) or ("error",))
    unknown = [lvl for lvl in block_on if lvl not in LEVELS]
    if unknown:
        raise ValueError(f"block_on takes {', '.join(LEVELS)}, got {unknown}")
    newest = latest(project)
    result: dict[str, Any]
    if not newest:
        result = {"verdict": "not measured", "reason": NO_SCAN, "blocked": False, "block_on": list(block_on),
                  "blocking": [], "accepted": [], "reopened": [], "scans": []}
    else:
        result = _measured(project, block_on, newest)
    if posture:
        result = gate_requirements(project, result)
    if record:
        _record_expiries(project)
        project.log("security_gate", {"verdict": result["verdict"], "block_on": list(block_on),
                                      "blocking": [b["id"] for b in result["blocking"]],
                                      "accepted": [a["id"] for a in result["accepted"]],
                                      "reopened": [r["id"] for r in result["reopened"]],
                                      "scans": result["scans"]})
    return result


def _scan_line(key: tuple[str, str], scan: dict) -> dict:
    """One tool's latest scan in a pack: its version, file, hash and counts by level."""
    mine = [f for f in scan["findings"] if tool_key(f["tool"]) == key]
    return (_scan_ref(key, scan)
            | {"version": next((x["version"] for x in scan["tools"] if tool_key(x) == key), None),
               "file": scan["file"], "at": scan["at"],
               "counts": {lvl: sum(1 for f in mine if f["level"] == lvl) for lvl in LEVELS}})


def summary(project: Any) -> dict:
    """What a pack says about security: the latest scan per tool with its counts, the accepted risks,
    and the default gate's verdict. Not measured when there is no scan."""
    newest = latest(project)
    if not newest:
        return {"verdict": "not measured", "note": NO_SCAN, "scans": [], "accepted_risks": [], "open": {}}
    gate = security_gate(project, record=False, posture=False)
    rows = findings(project)
    return {"verdict": gate["verdict"], "note": gate["reason"], "block_on": gate["block_on"],
            "scans": [_scan_line(k, s) for k, s in sorted(newest.items())],
            "open": {lvl: sum(1 for f in rows if f["state"] == "open" and f["level"] == lvl) for lvl in LEVELS},
            "accepted_risks": [{"finding": f["id"], "rule": f["rule"], "level": f["level"], "tool": f["tool"]["name"],
                                "person": f["acceptance"]["person"], "persona": f["acceptance"]["persona"],
                                "reason": f["acceptance"]["reason"], "expires": f["acceptance"]["expires"]}
                               for f in rows if f["state"] == "accepted"],
            "reopened": gate["reopened"]}
