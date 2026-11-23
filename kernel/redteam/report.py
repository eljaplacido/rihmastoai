"""Findings, coverage per layer, SARIF 2.1.0 for the security gate, and a summary a person reads.

A **finding** names its rule, title, severity and SARIF level, CWE and OWASP Top 10 2025 ids, the
layer that found it, where (`path:line`), a trimmed piece of evidence with every secret masked,
and how to fix it.

**Coverage** is said per layer, never assumed:
- `measured`: every file of the layer was read and checked;
- `partial`: some were not (a file that does not parse, a file too large), and the reason says which;
- `not measured`: nothing was checked, and the reason says why. A layer with no files of its kind
  is `not measured` and not applicable ("no Dockerfile in the tree"): it neither passes nor fails.

The verdict follows the factory's precedence (`kernel/verdicts.py`): a finding makes a layer
`failed`; a measured layer with none is `passed`; a partial layer with none is `not measured`,
because what was not read was not checked. Nothing unmeasured is reported as passed.

**SARIF**: `to_sarif` writes a log `adapters/sarif.py` reads like any scanner's. A coverage gap
travels with it as a result of kind `open` ("the tool could not tell pass from fail"; level `none`,
as SARIF requires for a result that is not a failure), so the gap is in the ledger beside the
findings. A scan that measured nothing writes no SARIF at all
(`NothingMeasured`): an empty log would read as "no findings", which is a pass. The tool is named
per kind of scan (`Rihmasto red team (static)`): the security gate keeps each tool's latest scan,
so a later dynamic run must not replace the static findings, and does not.

**Canaries**: a secret on a line marked `redteam: canary` in a test suite is planted on purpose
(tests, exfiltration checks). It is not a failure, but every marker is listed in the summary, and
each planted secret reaches the gate as a SARIF result of kind `review`, level `note`, suppressed in
the source (rule `RT-CANARY`), so a marker cannot hide a real secret from the gate. Outside a test
suite a marker silences nothing: the secret is a finding as usual.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kernel.redteam import TOOL_NAME, TOOL_VERSION
from kernel.redteam.masking import evidence as clean_evidence
from kernel.redteam.rules import KNOWN, OWASP_2025, SEVERITY_SCORE, Rule
from kernel.verdicts import combine_verdicts

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
STATES = ("measured", "partial", "not measured")
COVERAGE_RULE = "RT-COVERAGE"
CANARY_RULE = "RT-CANARY"
FINGERPRINT_KEY = "rihmastoFinding/v1"
IDLE_MARKER = "marker without a secret"
IGNORED = "marker ignored outside a test suite"


class NothingMeasured(ValueError):
    """No layer measured anything: there is no result to hand the gate, not even an empty one."""


class _Located:
    path: str
    line: int

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Finding(_Located):
    rule: str
    title: str
    severity: str
    level: str
    cwe: str
    owasp: str
    layer: str
    path: str
    line: int
    evidence: str
    fix: str

    @classmethod
    def of(cls, rule: Rule, path: str, line: int, snippet: str) -> Finding:
        """A finding of ``rule`` at ``path:line``; the snippet is masked and trimmed here, once."""
        return cls(rule.id, rule.title, rule.severity, rule.level, rule.cwe, rule.owasp, rule.layer,
                   path, max(int(line), 1), clean_evidence(snippet), rule.fix)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"location": self.location}


@dataclass
class Coverage:
    """What one layer measured. ``applicable`` is False when the tree holds nothing of its kind."""

    layer: str
    state: str
    reason: str
    files: int = 0
    gaps: list[str] = field(default_factory=list)
    applicable: bool = True

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"a layer is {', '.join(STATES)}, not {self.state!r}")

    def verdict(self, findings: Iterable[Finding]) -> str:
        if any(f.layer == self.layer for f in findings):
            return "failed"
        if not self.applicable:
            return "not applicable"
        return "passed" if self.state == "measured" else "not measured"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Canary(_Located):
    """A planted secret on a line marked `redteam: canary`: listed, never a finding."""

    path: str
    line: int
    kind: str
    evidence: str


def tool_name(kind: str) -> str:
    """The tool's name in SARIF for one kind of scan: the gate keeps each tool's latest scan apart."""
    return f"{TOOL_NAME} ({kind})"


@dataclass
class Report:
    target: str
    findings: list[Finding]
    coverage: list[Coverage]
    canaries: list[Canary] = field(default_factory=list)
    tool_version: str = TOOL_VERSION
    notes: list[str] = field(default_factory=list)
    kind: str = "static"

    @property
    def verdict(self) -> str:
        return verdict(self.findings, self.coverage)

    def counts(self) -> dict[str, int]:
        levels = Counter(f.level for f in self.findings)
        return {lvl: levels.get(lvl, 0) for lvl in ("error", "warning", "note")}

    def to_dict(self) -> dict[str, Any]:
        return {"tool": {"name": tool_name(self.kind), "version": self.tool_version}, "target": self.target,
                "verdict": self.verdict, "counts": self.counts(),
                "coverage": [c.to_dict() | {"verdict": c.verdict(self.findings)} for c in self.coverage],
                "findings": [f.to_dict() for f in self.findings],
                "canaries": [asdict(c) | {"location": c.location} for c in self.canaries], "notes": self.notes}


def verdict(findings: Sequence[Finding], coverage: Sequence[Coverage]) -> str:
    """The scan's verdict: failed with any finding; passed only when everything applicable was measured."""
    measured = [c for c in coverage if c.applicable and c.state != "not measured"]
    if not measured and not findings:
        return "not measured"
    return combine_verdicts([c.verdict(findings) for c in coverage] or ["not measured"])


def fingerprints(findings: Sequence[Finding]) -> list[str]:
    """A fingerprint per finding that survives lines moving: rule, file and evidence, with a count
    for the same evidence twice in one file. A person's risk acceptance follows it (kernel/security.py)."""
    seen: Counter[tuple[str, str, str]] = Counter()
    out = []
    for f in findings:
        key = (f.rule, f.path, f.evidence)
        seen[key] += 1
        basis = json.dumps([*key, seen[key]], ensure_ascii=False)
        out.append(hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32])
    return out


# -- SARIF 2.1.0 -----------------------------------------------------------------------------------

def _sarif_rule(rule: Rule) -> dict[str, Any]:
    return {"id": rule.id, "name": rule.id, "shortDescription": {"text": rule.title},
            "fullDescription": {"text": f"{rule.title} ({rule.cwe}; OWASP {rule.owasp} {OWASP_2025[rule.owasp]})."},
            "help": {"text": rule.fix}, "defaultConfiguration": {"level": rule.level},
            "properties": {"tags": ["security", rule.cwe, f"OWASP-{rule.owasp}"], "layer": rule.layer,
                           "severity": rule.severity, "security-severity": SEVERITY_SCORE[rule.severity]}}


_COVERAGE_DESCRIPTOR = {
    "id": COVERAGE_RULE, "name": COVERAGE_RULE, "shortDescription": {"text": "Part of the product was not scanned"},
    "fullDescription": {"text": "A layer of the scan was partial or not measured: what it did not read, it did "
                                "not check. This is a coverage gap, not a vulnerability."},
    "defaultConfiguration": {"level": "none"}, "properties": {"tags": ["coverage"]}}


_CANARY_DESCRIPTOR = {
    "id": CANARY_RULE, "name": CANARY_RULE,
    "shortDescription": {"text": "A secret on a line marked as a planted canary"},
    "fullDescription": {"text": "A test suite marked this secret `redteam: canary`: planted on purpose, so it is not "
                                "a failure. It reaches the gate so a person can see it is not a real credential."},
    "defaultConfiguration": {"level": "note"}, "properties": {"tags": ["security", "canary"]}}


def _canary_result(c: Canary, index: int) -> dict[str, Any]:
    digest = hashlib.sha256(json.dumps([CANARY_RULE, c.path, c.kind, c.evidence]).encode("utf-8")).hexdigest()[:32]
    return {"ruleId": CANARY_RULE, "ruleIndex": index, "kind": "review", "level": "note",
            "message": {"text": f"Planted canary ({c.kind}): {c.evidence}. Check it is not a real secret."},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": c.path},
                                                "region": {"startLine": max(c.line, 1)}}}],
            "partialFingerprints": {FINGERPRINT_KEY: digest},
            "suppressions": [{"kind": "inSource", "justification": "marked redteam: canary in a test suite"}]}


def _gaps(coverage: Sequence[Coverage]) -> list[Coverage]:
    return [c for c in coverage if c.applicable and c.state != "measured"]


def _result(f: Finding, index: int, fingerprint: str) -> dict[str, Any]:
    region = {"startLine": f.line, "snippet": {"text": f.evidence}}
    return {"ruleId": f.rule, "ruleIndex": index, "kind": "fail", "level": f.level,
            "message": {"text": f"{f.title}. Evidence: {f.evidence}"},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": f.path}, "region": region}}],
            "partialFingerprints": {FINGERPRINT_KEY: fingerprint},
            "properties": {"severity": f.severity, "layer": f.layer, "owasp": f.owasp}}


def _gap_result(c: Coverage, index: int) -> dict[str, Any]:
    text = f"{c.layer}: {c.state}: {c.reason}"
    digest = hashlib.sha256(json.dumps([COVERAGE_RULE, c.layer, c.state]).encode("utf-8")).hexdigest()[:32]
    return {"ruleId": COVERAGE_RULE, "ruleIndex": index, "kind": "open", "level": "none",
            "message": {"text": text}, "partialFingerprints": {FINGERPRINT_KEY: digest},
            "properties": {"layer": c.layer, "gaps": c.gaps[:50]}}


def _rules_of(findings: Sequence[Finding], coverage: Sequence[Coverage]) -> list[Rule]:
    """The rules of every layer the scan covered, and of every finding: what was checked, not only what hit."""
    layers = {c.layer for c in coverage} | {f.layer for f in findings}
    rules = [r for r in KNOWN.values() if r.layer in layers]
    return rules + [KNOWN[rid] for rid in dict.fromkeys(f.rule for f in findings) if KNOWN[rid] not in rules]


def _run_properties(findings: Sequence[Finding], coverage: Sequence[Coverage],
                    canaries: Sequence[Canary]) -> dict[str, Any]:
    return {"verdict": verdict(findings, coverage),
            "coverage": [c.to_dict() | {"verdict": c.verdict(findings)} for c in coverage],
            "canaries": [asdict(c) | {"location": c.location} for c in canaries]}


def to_sarif(findings: Sequence[Finding], coverage: Sequence[Coverage], tool_version: str = TOOL_VERSION, *,
             canaries: Sequence[Canary] = (), kind: str = "static") -> dict[str, Any]:
    """A SARIF 2.1.0 log of the findings, with each coverage gap as an `open` result.

    Raises NothingMeasured when no applicable layer measured anything: an empty log would read as a pass."""
    if not any(c.applicable and c.state != "not measured" for c in coverage):
        raise NothingMeasured("no layer measured anything: no SARIF is written, because an empty log reads as a pass")
    rules = _rules_of(findings, coverage)
    index = {r.id: i for i, r in enumerate(rules)}
    results = [_result(f, index[f.rule], fp) for f, fp in zip(findings, fingerprints(findings), strict=True)]
    gaps = _gaps(coverage)
    results += [_gap_result(c, len(rules)) for c in gaps]
    planted = [c for c in canaries if c.kind != IDLE_MARKER and IGNORED not in c.kind]
    results += [_canary_result(c, len(rules) + 1) for c in planted]
    notes = [{"level": "warning", "message": {"text": f"{c.layer}: {c.state}: {c.reason}"}} for c in gaps]
    driver = {"name": tool_name(kind), "version": tool_version, "semanticVersion": tool_version,
              "rules": [_sarif_rule(r) for r in rules] + [_COVERAGE_DESCRIPTOR, _CANARY_DESCRIPTOR]}
    run = {"tool": {"driver": driver}, "results": results,
           "invocations": [{"executionSuccessful": True, "toolExecutionNotifications": notes}],
           "properties": _run_properties(findings, coverage, canaries)}
    return {"$schema": SARIF_SCHEMA, "version": SARIF_VERSION, "runs": [run]}


def write_sarif(path: str | Path, report: Report) -> dict[str, Any]:
    """Write the report's SARIF to ``path`` (UTF-8, LF). Raises NothingMeasured like `to_sarif`."""
    doc = to_sarif(report.findings, report.coverage, report.tool_version, canaries=report.canaries,
                   kind=report.kind)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return doc


# -- the summary a person reads --------------------------------------------------------------------

def _code(text: str) -> str:
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _coverage_lines(report: Report) -> list[str]:
    unit = "Files" if report.kind == "static" else "Requests"
    lines = ["## Coverage", "", f"| Layer | State | {unit} | Verdict | Reason |", "|---|---|---:|---|---|"]
    for c in report.coverage:
        lines.append(f"| {c.layer} | {c.state} | {c.files} | {c.verdict(report.findings)} | {_cell(c.reason)} |")
    return lines + [""]


def _finding_lines(report: Report) -> list[str]:
    if not report.findings:
        return ["## Findings", "", "None in what was measured.", ""]
    lines = ["## Findings", ""]
    for n, f in enumerate(report.findings, 1):
        lines += [f"{n}. **{f.rule}** ({f.severity}, {f.level}) at `{f.location}`: {f.title}. "
                  f"{f.cwe}; OWASP {f.owasp} {OWASP_2025.get(f.owasp, '')}.",
                  f"   Evidence: {_code(f.evidence)}", f"   Fix: {f.fix}"]
    return lines + [""]


def _canary_lines(report: Report) -> list[str]:
    if not report.canaries:
        return ["## Canary markers", "", "None: no line is marked `redteam: canary`.", ""]
    silenced = [c for c in report.canaries if c.kind != IDLE_MARKER and IGNORED not in c.kind]
    ignored = [c for c in report.canaries if IGNORED in c.kind]
    idle = [c for c in report.canaries if c.kind == IDLE_MARKER]
    lines = ["## Canary markers", "",
             f"{len(silenced)} planted secret(s) on line(s) of a test suite marked `redteam: canary`, not reported "
             "as findings; each reaches the gate as a note to review. A marker silences the secret rules on its own "
             "line only. Check that each one is planted on purpose and holds no real secret.", ""]
    lines += [f"- `{c.location}`: {c.kind}: {_code(c.evidence)}" for c in silenced]
    if ignored:
        lines += ["", f"{len(ignored)} marker(s) outside a test suite silenced nothing (the secret is a finding): "
                  + ", ".join(f"`{c.location}`" for c in ignored) + "."]
    if idle:
        lines += ["", f"{len(idle)} marker(s) silenced nothing: " + ", ".join(f"`{c.location}`" for c in idle) + "."]
    return lines + [""]


def markdown(report: Report) -> str:
    """The summary a person reads: verdict, coverage per layer, findings, canary markers, notes."""
    counts = report.counts()
    head = [f"# Red team: {report.kind} scan of {report.target}", "",
            f"**Verdict: {report.verdict}.** {counts['error']} error, {counts['warning']} warning, "
            f"{counts['note']} note. {tool_name(report.kind)} {report.tool_version}.", ""]
    notes = (["## Notes", ""] + [f"- {n}" for n in report.notes] + [""]) if report.notes else []
    canaries = _canary_lines(report) if report.kind == "static" else []
    return "\n".join(head + _coverage_lines(report) + _finding_lines(report) + canaries + notes)
