"""The assessment's rules for security and compliance (kernel/assess.py).

Security is the red team's own static layer (`kernel/redteam/static.py`, D-0014) run over the revision:
each finding of it is a finding here, with its rule, CWE, location and fix, and its coverage per layer is
said. An unpinned action is reported once, under CI/CD governance (`cicd.pinned_actions`). Compliance is
what the files say about the licence, attribution, personal data and record-keeping, and what the
factory's own records could attest for the system today. A rule that cannot know says "not measured":
finding no field named like personal data does not show that none is processed.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.assess_repo import Repo, base, fact, listed, result
from kernel.redteam.report import Report, fingerprints

# Reported under CI/CD governance, not twice.
ELSEWHERE = {"RT-GHA-UNPINNED": "cicd.pinned_actions"}
MAX_SCAN_FINDINGS = 60
POLICIES = ("SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md", "SECURITY.txt", ".well-known/security.txt")
ENV_FILE_USE = re.compile(r"\b(load_dotenv|dotenv|env_file)\b")
ENV_IGNORED = re.compile(r"^\s*/?(\*?\.env\b|\.env\*|\*\.env)")
LICENCES = (("Apache-2.0", ("Apache License", "Version 2.0")),
            ("MIT", ("Permission is hereby granted, free of charge",)),
            ("AGPL-3.0", ("GNU AFFERO GENERAL PUBLIC LICENSE",)), ("LGPL", ("GNU LESSER GENERAL PUBLIC LICENSE",)),
            ("GPL-3.0", ("GNU GENERAL PUBLIC LICENSE", "Version 3")), ("GPL-2.0", ("GNU GENERAL PUBLIC LICENSE",)),
            ("MPL-2.0", ("Mozilla Public License",)), ("BSD", ("Redistribution and use in source and binary forms",)),
            ("Unlicense", ("free and unencumbered software released into the public domain",)))
LICENCE_DECLARED = re.compile(r"""^\s*["']?licen[cs]e["']?\s*[:=]""", re.I)
NOTICES = ("NOTICE", "NOTICE.md", "NOTICE.txt", "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.txt",
           "THIRD-PARTY-NOTICES.txt", "ThirdPartyNotices.txt", "THIRD_PARTY_LICENSES")
VENDOR_DIRS = ("vendor/", "third_party/", "third-party/", "external/", "extern/")
PERSONAL = re.compile(r"\b(e[-_]?mail(_address)?|phone(_number)?|ssn|social_security|date_of_birth|birth_?date|dob|"
                      r"hetu|personal_id|national_id|passport|iban|credit_?card|card_number|first_?name|last_?name|"
                      r"full_?name|home_address|street_address|ip_address)\b", re.I)
# A section on it, by its heading: a word in passing ("no privacy story at all") says nothing of how.
PRIVACY_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+.*\b(personal data|gdpr|data protection|data handling|retention|"
                             r"privacy)\b", re.I)
# An audit trail by name (audit_log, AuditTrail, audit-event) or by a library that keeps one; the bare
# word "audit" names nothing that records.
AUDIT = re.compile(r"\baudit[_-]?(log|trail|event|entry|record|history)s?\b|\bauditlog\b|\bHistoricalRecords\b|"
                   r"@Audited\b|\bhas_paper_trail\b|\bsimple_history\b|\breversion\.register\b", re.I)


def _sec(key: str, title: str, verdict: str, **kw: Any) -> dict[str, Any]:
    return result(f"security.{key}", "security", title, verdict, **kw)


def redteam(report: Report) -> list[dict[str, Any]]:
    """Each finding of the red team's static layer, by its rule, with its masked evidence and fix."""
    shown = [f for f in report.findings if f.rule not in ELSEWHERE]
    out = []
    for f, fp in list(zip(shown, fingerprints(shown), strict=True))[:MAX_SCAN_FINDINGS]:
        out.append(_sec(f"{f.rule}:{f.path}:{fp[:16]}", f.title, "failed", severity=f.severity,
                        summary=f"{f.rule} ({f.cwe}, OWASP {f.owasp}), {f.layer} layer of the red team",
                        evidence=[{"file": f.path, "line": f.line, "text": f.evidence}], suggestion=f.fix))
    return out


def scan_coverage(report: Report, gaps: list[str], notes: list[str]) -> dict[str, Any]:
    """What the red team's static layer read: every applicable layer measured, or what it could not read."""
    title = "The red team's static layer read the whole repository"
    layers = [c for c in report.coverage if not c.layer.startswith("external:")]
    evidence = [fact(f"{c.layer}: {c.state}, {c.reason}") for c in layers] + [fact(n) for n in notes]
    shown = [f for f in report.findings if f.rule not in ELSEWHERE]
    more = len(shown) - MAX_SCAN_FINDINGS
    summary = f"{len(shown)} finding(s), each listed on its own" + (f"; {more} more not listed" if more > 0 else "")
    partial = [c for c in layers if c.applicable and c.state != "measured"]
    if partial or gaps:
        why = "; ".join([f"{c.layer} {c.state}: {c.reason}" for c in partial] + gaps)
        return _sec("scan_coverage", title, "not measured", summary=summary, evidence=evidence,
                    reason=f"what was not read was not checked: {why}")
    if not any(c.applicable for c in layers):
        return _sec("scan_coverage", title, "not measured", reason="no file of a kind the static layer reads",
                    evidence=evidence)
    return _sec("scan_coverage", title, "passed", summary=summary, evidence=evidence)


def policy(repo: Repo) -> dict[str, Any]:
    title = "A security policy says how to report a vulnerability"
    found = repo.first(*POLICIES)
    if found:
        return _sec("policy", title, "passed", evidence=[{"file": found, "fact": "present"}])
    return _sec("policy", title, "failed", severity="medium", summary="no SECURITY.md",
                evidence=[fact(f"none of {listed(list(POLICIES))}")],
                suggestion="Add a SECURITY.md that says where to report a vulnerability and how it is handled.")


def env_files_ignored(repo: Repo) -> dict[str, Any]:
    title = "Environment files are kept out of the repository"
    uses = [f for f in repo.files if base(f) in (".env.example", ".env.sample", ".env.template")]
    uses += [e["file"] for e in repo.find(ENV_FILE_USE, repo.code(), limit=1)]
    if not uses:
        return _sec("env_files_ignored", title, "not applicable", reason="no sign the system reads environment files")
    ignore = repo.first(".gitignore")
    hits = repo.find(ENV_IGNORED, [ignore], limit=1) if ignore else []
    if hits:
        return _sec("env_files_ignored", title, "passed", evidence=hits)
    return _sec("env_files_ignored", title, "failed", severity="low",
                summary="the system reads environment files and git does not ignore them",
                evidence=[{"file": uses[0], "fact": "uses an environment file"},
                          fact("no .env pattern in .gitignore" if ignore else "no .gitignore")],
                suggestion="Ignore .env files in .gitignore, so a local secret is never committed by mistake.")


SECURITY = (policy, env_files_ignored)


# -- compliance --------------------------------------------------------------------------------------

def _comp(key: str, title: str, verdict: str, **kw: Any) -> dict[str, Any]:
    return result(f"compliance.{key}", "compliance", title, verdict, **kw)


def identify(text: str) -> str:
    return next((name for name, marks in LICENCES if all(m.lower() in text.lower() for m in marks)),
                "a text the kernel does not recognise")


def licence(repo: Repo) -> dict[str, Any]:
    title = "A licence is declared"
    files = [f for f in repo.files if "/" not in f and base(f).startswith(("license", "licence", "copying"))]
    declared = repo.find(LICENCE_DECLARED, [f for f in ("pyproject.toml", "package.json", "setup.cfg", "Cargo.toml")
                                            if f in repo.files], limit=2)
    if files:
        return _comp("licence", title, "passed", summary=identify(repo.text(files[0])),
                     evidence=[{"file": f, "fact": identify(repo.text(f))} for f in files] + declared)
    if declared:
        return _comp("licence", title, "passed", summary="declared in a manifest; no licence text", evidence=declared)
    return _comp("licence", title, "failed", severity="medium", summary="no licence",
                 evidence=[fact("no LICENSE, LICENCE or COPYING file, and no licence field in a manifest")],
                 suggestion="Add a LICENSE (or a proprietary notice) that says who may use, change and distribute "
                            "the code.")


def notice(repo: Repo) -> dict[str, Any]:
    title = "Third-party code carries its attribution"
    found = repo.first(*NOTICES)
    vendored = sorted({f.split("/", 1)[0] + "/" for f in repo.files if f.startswith(VENDOR_DIRS)})
    if found:
        return _comp("notice", title, "passed", evidence=[{"file": found, "fact": "present"}])
    if vendored:
        return _comp("notice", title, "failed", severity="medium", summary="vendored code without a NOTICE",
                     evidence=[fact(f"third-party folder(s) {listed(vendored)} and no NOTICE or third-party notices")],
                     suggestion="Add a NOTICE (or THIRD_PARTY_NOTICES) naming each vendored component and its licence.")
    return _comp("notice", title, "not applicable",
                 reason="no vendored third-party folder found by rule, and no NOTICE to carry")


def personal_data(repo: Repo) -> dict[str, Any]:
    title = "How personal data is handled is written down"
    hints = repo.find(PERSONAL, repo.code() + repo.named(lambda f: f.lower().endswith(".sql")), limit=5)
    if not hints:
        return _comp("personal_data", title, "not measured",
                     reason="no field named like personal data was found by rule; that does not show none is processed")
    docs = [f for f in repo.files if re.search(r"privacy|data[-_]protection|personal[-_]data|gdpr|dpia|"
                                                      r"record[-_]of[-_]processing", base(f))
            and f.lower().endswith((".md", ".rst", ".txt", ".adoc"))]
    if docs:
        return _comp("personal_data", title, "passed", summary="a document named for it; what it says is not checked by rule",
                     evidence=hints[:2] + [{"file": docs[0], "fact": "a document on personal data, by its name"}])
    section = repo.find(PRIVACY_HEADING, [f for f in repo.files if f.lower().endswith(".md")], limit=1)
    if section:
        return _comp("personal_data", title, "passed", evidence=hints[:2] + section,
                     summary="a document has a section on it; what the section says is not checked by rule")
    return _comp("personal_data", title, "failed", severity="medium",
                 summary="the code names what looks like personal data, and no document says how it is handled",
                 evidence=hints, suggestion="Write down which personal data the system keeps, why, for how long, and "
                                            "who may read it (a PRIVACY.md, or the record of processing).")


def audit_trail(repo: Repo) -> dict[str, Any]:
    title = "The system records who changed what"
    hits = repo.find(AUDIT, repo.code(), limit=3, code_only=True)
    if hits:
        return _comp("audit_trail", title, "passed", evidence=hits,
                     summary="an audit trail is named in the code; what it records is not checked by rule")
    return _comp("audit_trail", title, "not measured",
                 reason="no audit-trail code was found by rule; the rule cannot tell whether the system records who "
                        "changed what by other means")


def factory_evidence(repo: Repo) -> dict[str, Any]:
    """What the factory's own records could attest for this system today (kernel/evidence_pack.py)."""
    title = "The factory's records of this system verify"
    own = repo.records.get("factory") or {}
    evidence = [fact(f"ledger: {own.get('records')} records, hash chain {'intact' if own.get('intact') else 'BROKEN'}"),
                fact(f"decisions by people: {own.get('decisions')}")]
    evidence += [fact(f"{c['control']} ({c['topic']}): {c['status']}") for c in own.get("controls") or []]
    if not own.get("intact"):
        return _comp("factory_evidence", title, "failed", severity="high", summary="the ledger does not verify",
                     evidence=evidence, suggestion="Find where the project's ledger chain breaks before relying on "
                                                   "anything it records (rihmasto status shows ledger_intact).")
    return _comp("factory_evidence", title, "passed", evidence=evidence,
                 summary="an evidence pack can show what ran and who decided; it never claims conformity")


def security_evidence(repo: Repo) -> dict[str, Any]:
    title = "A security scan is on record for the security gate"
    own = repo.records.get("factory") or {}
    scans = own.get("scans") or []
    if scans:
        return _comp("security_evidence", title, "passed",
                     evidence=[fact(f"{s.get('tool')} {s.get('version')}: scan {s.get('scan')}") for s in scans])
    return _comp("security_evidence", title, "failed", severity="low", summary="no scan ingested",
                 evidence=[fact("the security gate says not measured: no scan; ai-act:art15 and nis2:art21 stay "
                                "partial in an evidence pack")],
                 suggestion="Ingest this assessment's red-team scan (the SARIF beside it) with `rihmasto security "
                            "ingest`, signed by IT or compliance.")


COMPLIANCE = (licence, notice, personal_data, audit_trail, factory_evidence, security_evidence)

__all__ = ["COMPLIANCE", "ELSEWHERE", "SECURITY", "identify", "redteam", "scan_coverage"]
