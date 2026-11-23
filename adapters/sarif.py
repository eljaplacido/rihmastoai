"""SARIF 2.1.0 in: security findings from any scanner become a project's findings.

Any tool that writes SARIF 2.1.0 works the same: bandit, semgrep, trivy, ZAP, CodeQL, or Rihmasto's
own scanner. This module downloads nothing; a person, a pipeline or the factory hands it the file.

Each result becomes a finding with its rule id, level, message, location, CWE tags (when the tool
gives them) and the tool's name and version. A scan is stored as `security/<n>.json`, and the
ledger records `security_scan` with the counts by level, the tool and the file's sha256. Results
of kind `pass` or `notApplicable` are not findings. A result the tool marks as suppressed stays a
finding, flagged: a suppression in the source is not a person's recorded acceptance
(`kernel/security.py` holds those).

What is refused (`SarifError`, and `security_scan_refused` in the ledger), never read as a clean
scan or a lower level:

- a run that did not complete: `results` absent or not an array (SARIF 2.1.0: no results were
  produced), or an invocation whose `executionSuccessful` is not true. A tool that measured
  nothing has not passed;
- a run that names no tool (`tool.driver.name` is required);
- a level that is not `error`, `warning`, `note` or `none`, and a result whose level cannot be
  known (it has none, and the rule it names is not in the log);
- a start line or column that is not a whole number;
- anything else malformed, too deep or too large, and a value the store cannot write as JSON in
  UTF-8 (a lone surrogate). The refusal records the file's sha256 and a reason cut to
  `REASON_CHARS`, with what the file said escaped, so recording it never fails.

A rule is found in the tool component the result names (`rule.toolComponent`: the driver, or one
of `tool.extensions`, where CodeQL keeps its query packs' rules). A finding's fingerprint always
includes its file: a tool's own fingerprints are part of an identity, not all of it. Two findings
of one scan never share a fingerprint, so one acceptance never covers two results.

A tool's scan has a scope: the run's category (`automationDetails.id` up to its last `/`, as GitHub
code scanning reads it) and the names of its extensions (a CodeQL language's query packs). Each
tool and scope has its own latest scan (`kernel/security.py`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person

SARIF_VERSION = "2.1.0"
LEVELS = ("error", "warning", "note", "none")
NOT_FINDINGS = ("pass", "notApplicable")
MAX_BYTES = 256 * 1024 * 1024
REASON_CHARS = 500
_CWE = re.compile(r"\bcwe[-_/: ]{0,2}(\d{1,5})\b", re.IGNORECASE)
_MALFORMED = (AttributeError, TypeError, KeyError, IndexError, ValueError, RecursionError)


class SarifError(ValueError):
    """The file is not SARIF 2.1.0 the factory can read: nothing is ingested."""


def _hash(basis: object) -> str:
    return hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]


def _cwe(values: Iterable[object]) -> list[str]:
    out: set[str] = set()
    for v in values:
        if isinstance(v, str):
            out.update(f"CWE-{int(n)}" for n in _CWE.findall(v))
    return sorted(out, key=lambda c: int(c[4:]))


def _tags(obj: dict | None) -> list:
    props = (obj or {}).get("properties") or {}
    out = [t for t in (props.get("tags") or []) if isinstance(t, str)]
    for key in ("cwe", "CWE", "cwe_id"):
        value = props.get(key)
        for x in value if isinstance(value, list) else ([] if value is None else [value]):
            out.append(f"CWE-{x}" if str(x).isdigit() else str(x))
    return out


def _index(value: object, size: int) -> int | None:
    """A valid array index, or None when ``value`` is not one."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < size:
        return value
    return None


def _taxa(items: Any, components: list[str]) -> list:
    """Ids of taxa or relationship targets that belong to the CWE taxonomy."""
    out = []
    for t in items or []:
        if not isinstance(t, dict):
            continue
        raw_target = t.get("target")
        target = raw_target if isinstance(raw_target, dict) else t
        comp = target.get("toolComponent") or {}
        at = _index(comp.get("index"), len(components))
        name = comp.get("name") or (components[at] if at is not None else "")
        tid = str(target.get("id") or "")
        if "cwe" in str(name).lower() and tid:
            out.append(tid if tid.upper().startswith("CWE") else f"CWE-{tid}")
    return out


def _message(res: dict, rule: dict | None) -> str:
    msg = res.get("message") or {}
    if msg.get("text"):
        return str(msg["text"])
    rule = rule or {}
    strings = rule.get("messageStrings") or {}
    if msg.get("id") in strings:
        return str(strings[msg["id"]].get("text", ""))
    for key in ("shortDescription", "fullDescription"):
        if (rule.get(key) or {}).get("text"):
            return str(rule[key]["text"])
    return ""


def _position(region: dict, key: str) -> int | None:
    """A region's start line or column: a whole number, or None when the tool gives none. Anything
    else is refused, never stored as the log gave it (a value nested deeper than JSON can be written
    back would crash the store)."""
    value = region.get(key)
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise SarifError(f"region.{key} is a {type(value).__name__}, not an integer")


def _location(res: dict) -> dict:
    for loc in res.get("locations") or []:
        phys = (loc or {}).get("physicalLocation") or {}
        art = phys.get("artifactLocation") or {}
        region = phys.get("region") or {}
        if art.get("uri"):
            return {"uri": str(art["uri"]), "line": _position(region, "startLine"),
                    "column": _position(region, "startColumn")}
    return {"uri": None, "line": None, "column": None}


def _fingerprint(res: dict, tool: str, rule_id: str, loc: dict, message: str) -> str:
    """The same finding in the next scan has the same fingerprint, so a person's acceptance follows
    it. The tool's own fingerprint counts (a full one before a partial one), always with the file:
    a partial fingerprint such as a line hash is the same for the same line in another file. A
    fingerprint with nothing in it (gitleaks without git) counts for nothing; then the tool, rule,
    place and message decide."""
    for key in ("fingerprints", "partialFingerprints"):
        fp = res.get(key)
        if isinstance(fp, dict) and any(str(v).strip() for v in fp.values()):
            return _hash({key: fp, "tool": tool, "rule": rule_id, "uri": loc.get("uri")})
    return _hash([tool, rule_id, loc.get("uri"), loc.get("line"), message])


def _distinct(findings: list[dict]) -> None:
    """Two findings of one scan never share a fingerprint: those that do are told apart by their
    line and column, then by their order, so one acceptance never covers a result nobody saw."""
    groups: dict[str, list[dict]] = {}
    for f in findings:
        groups.setdefault(f["fingerprint"], []).append(f)
    for fp, group in groups.items():
        if len(group) < 2:
            continue
        seen: dict[str, int] = {}
        for f in group:
            base = _hash([fp, f["location"].get("line"), f["location"].get("column")])
            seen[base] = seen.get(base, 0) + 1
            f["fingerprint"] = base if seen[base] == 1 else _hash([base, seen[base]])


class _Rules:
    """The rules of one run, in the driver and in each extension, by position and by id."""

    def __init__(self, driver: dict, extensions: list[dict]) -> None:
        self.components = [driver, *extensions]          # 0 is the driver, 1 + i is extensions[i]
        self.rules: list[list] = []
        for comp in self.components:
            rules = comp.get("rules") or []
            if not isinstance(rules, list):
                raise SarifError(f"the rules of tool component {comp.get('name')!r} are not an array")
            self.rules.append(rules)
        self.by_id: dict[str, dict] = {}
        for rules in self.rules:
            for r in rules:
                if isinstance(r, dict) and isinstance(r.get("id"), str):
                    self.by_id.setdefault(r["id"], r)
        self.declared = any(self.rules)

    def component(self, ref: object) -> int:
        """The position of the tool component a result's rule reference names (the driver when none)."""
        if ref is None:
            return 0
        if not isinstance(ref, dict):
            raise SarifError("a result's rule.toolComponent is not an object")
        if ref.get("index") is not None:
            at = _index(ref["index"], len(self.components) - 1)
            if at is None:
                raise SarifError(f"a result names tool extension {ref['index']!r}, which the run does not hold")
            return at + 1
        for key in ("guid", "name"):
            if ref.get(key) is not None:
                hit = next((i for i, c in enumerate(self.components) if c.get(key) == ref[key]), None)
                if hit is None:
                    raise SarifError(f"a result names tool component {ref[key]!r}, which the run does not hold")
                return hit
        return 0

    def resolve(self, res: dict, rule_id: object) -> dict | None:
        """The rule a result names: by id in its component, by index there, then by id anywhere."""
        ref = res.get("rule") or {}
        rules = self.rules[self.component(ref.get("toolComponent"))]
        own = next((r for r in rules if isinstance(r, dict) and r.get("id") == rule_id), None) if rule_id else None
        idx = res.get("ruleIndex", ref.get("index"))
        if own is None and idx is not None and idx != -1:
            at = _index(idx, len(rules))
            if at is None:
                raise SarifError(f"a result names rule index {idx!r}, which its tool component does not hold")
            own = rules[at] if isinstance(rules[at], dict) else None
        if own is None and isinstance(rule_id, str):
            own = self.by_id.get(rule_id)
        return own


def _level(res: dict, rule: dict | None, rule_id: str, declared: bool) -> str:
    """The result's level, else its rule's default, else SARIF's default `warning`. A level outside
    SARIF's four is refused, never lowered; so is a missing one whose rule the log does not hold."""
    level = res.get("level")
    if level is None:
        level = ((rule or {}).get("defaultConfiguration") or {}).get("level")
    if level is None and rule is None and declared:
        raise SarifError(f"a result of rule {rule_id!r} has no level, and its rule is not in the log: "
                         "its level cannot be known")
    if level is None:
        return "warning"
    if level not in LEVELS:
        raise SarifError(f"level {level!r} is not a SARIF level ({', '.join(LEVELS)})")
    return str(level)


def _finding(res: object, rules: _Rules, tool: dict, components: list[str]) -> dict | None:
    """One result as a finding, or None for a result that is not one (a pass, not applicable)."""
    if not isinstance(res, dict):
        raise SarifError("a result is not an object")
    if res.get("kind") in NOT_FINDINGS:
        return None
    if res.get("ruleId") is not None and not isinstance(res["ruleId"], str):
        raise SarifError(f"a result's ruleId {res['ruleId']!r} is not a string")
    ref = res.get("rule") or {}
    rule = rules.resolve(res, res.get("ruleId") or ref.get("id"))
    rule_id = str(res.get("ruleId") or ref.get("id") or (rule or {}).get("id") or "unknown-rule")
    level = _level(res, rule, rule_id, rules.declared)
    message = _message(res, rule)
    loc = _location(res)
    cwe = _cwe(_tags(rule) + _tags(res) + _taxa((rule or {}).get("relationships"), components)
               + _taxa(res.get("taxa"), components))
    return {"rule": rule_id, "level": level, "message": message[:2000], "location": loc, "cwe": cwe,
            "tool": tool, "fingerprint": _fingerprint(res, tool["name"], rule_id, loc, message),
            "suppressed_in_source": bool(res.get("suppressions"))}


def _tool(run: dict, n: int) -> tuple[dict, list[dict]]:
    """The run's driver (it must have a name) and its extensions."""
    tool = run.get("tool")
    tool = tool if isinstance(tool, dict) else {}
    driver = tool.get("driver")
    if not isinstance(driver, dict) or not isinstance(driver.get("name"), str) or not driver["name"].strip():
        raise SarifError(f"run {n} does not name its tool (tool.driver.name is required)")
    extensions = tool.get("extensions") or []
    if not isinstance(extensions, list) or not all(isinstance(e, dict) for e in extensions):
        raise SarifError(f"run {n}: tool.extensions is not an array of tool components")
    return driver, extensions


def _completed(run: dict, name: str) -> None:
    """A run that did not complete is refused: it never replaces the tool's last scan as a clean one."""
    if not isinstance(run.get("results"), list):
        raise SarifError(f"{name} produced no results array: its analysis did not run or did not complete "
                         "(not measured)")
    invocations = run.get("invocations")
    if invocations is not None and not isinstance(invocations, list):
        raise SarifError(f"{name}: invocations is not an array")
    for inv in invocations or []:
        if not isinstance(inv, dict) or inv.get("executionSuccessful", True) is not True:
            raise SarifError(f"{name} reports that its run did not succeed (executionSuccessful is not true): "
                             "not measured")


def _scope(run: dict, extensions: list[dict]) -> str:
    """What tells this tool's scans apart: the run's category and its extensions' names."""
    auto = run.get("automationDetails")
    if auto is not None and not isinstance(auto, dict):
        raise SarifError("automationDetails is not an object")
    aid = (auto or {}).get("id")
    category = aid.rsplit("/", 1)[0] if isinstance(aid, str) and "/" in aid else ""
    names = sorted({str(e["name"]) for e in extensions if e.get("name")})
    parts = ([f"category {category}"] if category else []) + ([f"extensions {', '.join(names)}"] if names else [])
    return "; ".join(parts)


def _run(run: object, n: int) -> tuple[dict, list[dict]]:
    """One run's tool and findings."""
    if not isinstance(run, dict):
        raise SarifError(f"run {n} is not an object")
    driver, extensions = _tool(run, n)
    name = str(driver["name"])
    _completed(run, name)
    tool = {"name": name, "version": str(driver.get("semanticVersion") or driver.get("version") or "not stated")}
    scope = _scope(run, extensions)
    if scope:
        tool["scope"] = scope
    rules = _Rules(driver, extensions)
    components = [str((t or {}).get("name", "")) for t in (run.get("taxonomies") or [])]
    found = [_finding(res, rules, tool, components) for res in run["results"]]
    return tool, [f for f in found if f is not None]


def _parse(doc: object) -> dict:
    if not isinstance(doc, dict):
        raise SarifError("a SARIF log is a JSON object")
    if doc.get("version") != SARIF_VERSION:
        raise SarifError(f"SARIF version {doc.get('version')!r} is not read; the factory reads {SARIF_VERSION}")
    runs = doc.get("runs")
    if not isinstance(runs, list) or not runs:
        raise SarifError("the log holds no runs")
    tools: list[dict] = []
    findings: list[dict] = []
    for n, run in enumerate(runs, 1):
        tool, found = _run(run, n)
        if tool not in tools:
            tools.append(tool)
        findings.extend(found)
    _distinct(findings)
    return {"tools": tools, "findings": findings}


def parse(doc: object) -> dict:
    """The findings and tools of one SARIF 2.1.0 log. Raises SarifError for anything else,
    a malformed log included."""
    try:
        return _parse(doc)
    except SarifError:
        raise
    except _MALFORMED as exc:
        raise SarifError(f"malformed SARIF: {type(exc).__name__}: {str(exc)[:200]}") from exc


def _scan_numbers(project: Any) -> list:
    folder = project.path("security")
    if not folder.exists():
        return []
    return sorted(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit())


def _signer(person: str | None, persona: str | None) -> None:
    """Who hands in the file: nobody (a pipeline), or a named person acting as one of the personas."""
    if person is None and persona is None:
        return
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a scan handed in by someone is signed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"{persona!r} is not a persona; one of {', '.join(PERSONAS)} hands in a scan")


def _said(text: str, limit: int = REASON_CHARS) -> str:
    """Text a file gave, as the store and the ledger can hold it: cut to ``limit`` characters, and a
    character UTF-8 cannot encode (a lone surrogate) written as its escape."""
    return text[:limit].encode("utf-8", "backslashreplace").decode("utf-8")


def _refuse(project: Any, path: Path, reason: str, **facts: object) -> None:
    """Record that a file was refused, and why. What the file said is cut and escaped first, so
    recording a refusal never fails on it."""
    project.log("security_scan_refused", {"file": _said(path.name), **facts, "reason": _said(reason)})


def _read(project: Any, path: Path) -> tuple[object, str]:
    """The file's JSON and sha256. A file too large or not JSON is refused, and the refusal recorded."""
    size = path.stat().st_size
    if size > MAX_BYTES:
        _refuse(project, path, f"larger than {MAX_BYTES} bytes", bytes=size)
        raise SarifError(f"{path.name} is {size} bytes; the factory reads SARIF up to {MAX_BYTES}")
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        return json.loads(raw.decode("utf-8-sig")), sha
    except (ValueError, RecursionError) as exc:
        reason = f"not JSON: {type(exc).__name__}: {exc}"[:200]
        _refuse(project, path, reason, sha256=sha)
        raise SarifError(f"{path.name} is {reason}") from exc


def _store(project: Any, path: Path, sha: str, scan: dict) -> None:
    """Write the scan. A value the store cannot write as JSON in UTF-8 is refused and recorded,
    never a crash between reading the file and recording it."""
    try:
        project.write(f"security/{scan['scan']}.json", scan)
    except (ValueError, RecursionError) as exc:
        reason = f"cannot be stored: {type(exc).__name__}: {_said(str(exc), 200)}"
        _refuse(project, path, reason, sha256=sha)
        raise SarifError(f"{_said(path.name)} {reason}") from exc


def ingest(project: Any, path: str | Path, *, person: str | None = None, persona: str | None = None) -> dict:
    """Read a SARIF file into the project: `security/<n>.json` and a `security_scan` record.

    ``person`` and ``persona`` sign the scan when someone hands it in; both or neither."""
    _signer(person, persona)
    path = Path(path)
    doc, sha = _read(project, path)
    try:
        parsed = parse(doc)
    except SarifError as exc:
        _refuse(project, path, str(exc), sha256=sha)
        raise
    n = (_scan_numbers(project) or [0])[-1] + 1
    for k, f in enumerate(parsed["findings"], 1):
        f["id"] = f"SEC-{n}-{k}"
    counts = {lvl: sum(1 for f in parsed["findings"] if f["level"] == lvl) for lvl in LEVELS}
    scan = {"scan": n, "file": _said(path.name), "sha256": sha, "sarif_version": SARIF_VERSION,
            "at": project.factory.clock.stamp(), "tools": parsed["tools"], "keyed_by": ["tool", "scope"],
            "counts": counts,
            "findings": [{"id": f.pop("id"), **f} for f in parsed["findings"]],
            "ingested_by": {"person": person, "persona": persona} if person else None}
    _store(project, path, sha, scan)
    project.log("security_scan", {"scan": n, "file": scan["file"], "sha256": sha, "tool": parsed["tools"][0],
                                  "tools": parsed["tools"], "counts": counts, "findings": len(scan["findings"]),
                                  "by": person, "persona": persona})
    return scan
