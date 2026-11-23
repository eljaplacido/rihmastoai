"""Evidence packs: one exportable bundle that shows what ran, which versions, who approved, and that
it was checked. It is for compliance and audit (AI Act, GDPR and NIS2 reviews, internal audit),
and it claims no conformity: it is the evidence a reviewer judges.

The bundle holds:
- the capability pack;
- the contract and the spec;
- each criterion's evidence state;
- every decision with its person and persona;
- every gate verdict;
- the holdouts' results as scores only (the scenarios stay in their custody, never in the bundle);
- the Gnomon runs (role, model, surface hash, audit-chain head and whether it was intact);
- the latest security scan per tool, with its counts and the accepted risks, or "not measured: no
  security scan";
- the full project ledger, with the result of verifying its hash chain at export;
- `MANIFEST.json`, holding the sha256 of every file.

The export itself is recorded in the ledger, with the person who asked for it.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from kernel.canon import DecisionRefused
from kernel.people import is_person

EXPORTERS = ("compliance", "it", "business_owner", "product_owner", "developer")


def _gather(project) -> dict:
    from kernel.packs import build_pack
    from kernel.security import summary as security_summary
    from kernel.status import evidence

    led = project.ledger()
    records = led.records()
    check = led.verify()
    try:
        pack = build_pack(project)
    except LookupError:
        pack = None
    of = lambda kind: [r["event"]["payload"] | {"at": r["event"].get("at")} for r in records  # noqa: E731
                       if isinstance(r, dict) and r.get("event", {}).get("kind") == kind]
    files = {
        "capability-pack.json": pack or {"note": "no release yet, so no capability pack"},
        "contract.json": project.read("contract.json") or {"note": "not compiled yet"},
        "evidence.json": evidence(project) if project.path("contract.json").exists() else [],
        "decisions.json": of("decision"),
        "gates.json": of("gate"),
        "holdout-scores.json": (pack or {}).get("acceptance", {}).get("holdout_scores"),
        "gnomon-runs.json": [{k: r.get(k) for k in ("task", "round", "role", "model", "endpoint", "surface_hash",
                                                     "verdict", "chain", "tampered", "at")} for r in of("gnomon_run")],
        "ledger-check.json": {"intact": getattr(check, "intact", None), "broken_seq": getattr(check, "broken_seq", None),
                              "records": len(records)},
        "security.json": security_summary(project),
    }
    return files


# What the bundle can evidence, by control family. Keyed by public control ids; it says evidenced,
# partial or no, never "compliant". A reviewer judges conformity, not the factory.
CONTROLS = [
    {"control": "ai-act:art12", "topic": "record-keeping of an AI system's operation", "status": "partial",
     "by": "ledger.jsonl, gnomon-runs.json: every factory run and decision; the product's own runtime logs are not here"},
    {"control": "ai-act:art14", "topic": "human oversight", "status": "evidenced",
     "by": "decisions.json: every decision signed by a named person and persona; the autonomy cap in capability-pack.json"},
    {"control": "ai-act:art15", "topic": "accuracy, robustness and cybersecurity", "status": "partial",
     "by": "evidence.json, gates.json, holdout-scores.json; no security scan yet"},
    {"control": "ai-act:art50", "topic": "transparency to people interacting with AI", "status": "no",
     "by": "not evidenced by the factory: it is a property of the product's screens"},
    {"control": "gdpr:art30", "topic": "records of processing activities", "status": "no",
     "by": "not evidenced: the factory does not record which personal data a product processes"},
    {"control": "nis2:art21", "topic": "cybersecurity risk-management measures", "status": "partial",
     "by": "change control and approvals in decisions.json; no vulnerability handling evidence yet"},
]


def _controls(files: dict) -> list:
    """The control table, naming the security scan where there is one."""
    sec = files.get("security.json") or {}
    if not sec.get("scans"):
        return CONTROLS
    tools = ", ".join(f"{s['tool']} {s['version']}" for s in sec["scans"])
    by = {"ai-act:art15": f"evidence.json, gates.json, holdout-scores.json; security.json: the latest scan by {tools}",
          "nis2:art21": "change control and approvals in decisions.json; security.json: scan findings and the risks "
                        "a named person accepted, with their expiry"}
    return [dict(c, by=by[c["control"]]) if c["control"] in by else c for c in CONTROLS]


def attestation(files: dict) -> dict:
    """attestable, chain broken, or insufficient evidence: never 'compliant'."""
    lc = files["ledger-check.json"]
    runs = files["gnomon-runs.json"]
    pack = files["capability-pack.json"] if isinstance(files["capability-pack.json"], dict) else {}
    if not lc["intact"] or any((r.get("chain") or {}).get("intact") is False for r in runs):
        verdict = "chain broken"
    elif not pack.get("acceptance") or not files["decisions.json"]:
        verdict = "insufficient evidence"
    else:
        verdict = "attestable"
    return {"verdict": verdict, "meaning": {
        "attestable": "the records are intact and complete enough for a reviewer to judge",
        "chain broken": "a hash chain did not verify: what it covers cannot be trusted as recorded",
        "insufficient evidence": "intact, but too little was recorded to judge (no release or no human decision)",
    }[verdict], "controls": _controls(files),
        "not_measured": [c["criterion"] for c in files["evidence.json"] if c.get("state") == "not_measured"]}


def _security_line(sec: dict) -> str:
    if not sec.get("scans"):
        return sec.get("note") or "not measured: no security scan"
    scans = "; ".join(f"{s['tool']} {s['version']} (scan {s['scan']}, sha256 {s['sha256'][:12]}: "
                      + (", ".join(f"{n} {lvl}" for lvl, n in s["counts"].items() if n) or "no findings") + ")"
                      for s in sec["scans"])
    return (f"{scans}; gate {sec['verdict']} ({sec['note']}); {len(sec.get('accepted_risks') or [])} risk(s) "
            "accepted by a named person until a date")


def _readme(project, files: dict) -> str:
    pack = files["capability-pack.json"]
    acc = pack.get("acceptance", {}) if isinstance(pack, dict) else {}
    lc = files["ledger-check.json"]
    lines = [f"# Evidence pack: {project.meta.get('title')}", "",
             f"Project `{project.pid}`, profile {project.meta.get('profile', 'web_service')}, "
             f"maturity {project.meta.get('maturity')}.", "",
             "This bundle is evidence for a reviewer to judge. It does not claim conformity with any framework.", "",
             "## At a glance", "",
             f"- Capability pack: version {pack.get('version', '—')}, "
             f"{'valid' if acc.get('valid') else 'not valid'} "
             f"({len(acc.get('not_valid_because') or [])} criteria not verified or held out).",
             f"- Decisions by people: {len(files['decisions.json'])}. Gate verdicts: {len(files['gates.json'])}.",
             f"- Gnomon runs: {len(files['gnomon-runs.json'])}, of which audit chain not intact: "
             f"{sum(1 for r in files['gnomon-runs.json'] if not (r.get('chain') or {}).get('intact'))}.",
             f"- Project ledger: {lc['records']} records, hash chain {'intact' if lc['intact'] else 'BROKEN at ' + str(lc['broken_seq'])} at export.",
             f"- Security: {_security_line(files.get('security.json') or {})}.",
             "", "## Not in this bundle", "",
             "- Holdout scenarios: they stay in their own custody. Only their scores are here.",
             "- Secrets and credentials: never recorded by the factory.",
             "- An SBOM and a signature, unless the capability pack names them.", "",
             "## Files", "", "`MANIFEST.json` lists every file with its sha256."]
    return "\n".join(lines) + "\n"


def export(project, out_dir, *, person: str, persona: str) -> Path:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in EXPORTERS:
        raise DecisionRefused(f"a {persona} may not export evidence; {', '.join(EXPORTERS)} may")
    files = _gather(project)
    texts = {name: json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n" for name, value in files.items()}
    texts["spec.md"] = project.path("spec.md").read_text(encoding="utf-8") if project.path("spec.md").exists() else ""
    texts["ledger.jsonl"] = project.path("ledger.jsonl").read_text(encoding="utf-8") \
        if project.path("ledger.jsonl").exists() else ""
    att = attestation(files)
    texts["attestation.json"] = json.dumps(att, indent=2, ensure_ascii=False) + "\n"
    texts["README.md"] = _readme(project, files) + (
        f"\n## Attestation\n\n**{att['verdict']}**: {att['meaning']}. This is not a statement of conformity.\n\n"
        "| Control | Topic | Evidence | Where |\n|---|---|---|---|\n"
        + "".join(f"| `{c['control']}` | {c['topic']} | {c['status']} | {c['by']} |\n" for c in att["controls"]))
    manifest = {name: hashlib.sha256(t.encode("utf-8")).hexdigest() for name, t in sorted(texts.items())}
    stamp = project.factory.clock.stamp().replace(":", "").replace("-", "")
    out = Path(out_dir) / f"{project.pid}-evidence-{stamp}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, t in sorted(texts.items()):
            z.writestr(name, t)
        z.writestr("MANIFEST.json", json.dumps({"files": manifest, "project": project.pid,
                                                "exported_by": person, "persona": persona}, indent=2) + "\n")
    project.log("evidence_exported", {"file": out.name, "by": person, "persona": persona, "verdict": att["verdict"],
                                      "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True)
                                                                        .encode("utf-8")).hexdigest()})
    return out
