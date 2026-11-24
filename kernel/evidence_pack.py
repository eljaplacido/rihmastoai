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
- the governance map where the latest release runs (`governance-map.json`): each of the five
  guarantees of docs/portability.md held, partial or lost, as the release's deploy gate card shows it;
- `MANIFEST.json`, holding the sha256 of every file.

The export itself is recorded in the ledger, with the person who asked for it.

The ledger is read once, under its lock, after the capability pack is built (building it may
append a record). The records the bundle reports on, its decisions and gates, and the
`ledger.jsonl` it ships (the file's bytes as read) all come from that one read. Its chain is
verified against the head the cockpit keeps outside the project's folder (FR-L3-AC-1), so a
ledger cut short or rewritten consistently from its start shows as broken. That head is read
before the ledger: a head only moves on, so a record appended and kept meanwhile never shows as a
break. With no head kept, the bundle says its end was not checked. A record not shaped as the
kernel writes it, or a line that is not UTF-8 or is nested too deep to read, is reported through
the chain check and never stops the export or its record in the ledger. An export never replaces
another one's file.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.ledgerstore import LedgerStore
from kernel.people import is_person

EXPORTERS = ("compliance", "it", "business_owner", "product_owner", "developer")
# Where the cockpit keeps each project's last verified ledger head, under the factory home.
KEPT_HEADS = ("cockpit", "heads.json")
# What building the pack or reading the evidence raises on records not shaped as the kernel writes
# them, and on a ledger line the store cannot read (not UTF-8, a ValueError; or nested too deep).
_UNREADABLE = (KeyError, TypeError, AttributeError, ValueError, IndexError, RecursionError)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")
_MARKUP = re.compile(r"[`<>|]")


def _parsed(raw: bytes) -> list:
    """The records in a ledger's bytes, in lines as LedgerStore.records splits the file. A line that
    is not UTF-8, not JSON or nested too deep to read stays a string, so verify reports it."""
    records: list = []
    for line in raw.splitlines():
        if not line:
            continue
        try:
            records.append(json.loads(line.decode("utf-8")))
        except (ValueError, RecursionError):
            records.append(line.decode("utf-8", errors="replace"))
    return records


class _ReadingStore(LedgerStore):
    """The project's ledger, reading a line its store cannot read (not UTF-8, nested too deep) as a
    string, as the store reads a line that is not JSON. The export's record then follows it as it
    follows any broken record."""

    def records(self) -> list[Any]:
        return _parsed(self.path.read_bytes()) if self.path.exists() else []


def _ledger_snapshot(project: Any) -> tuple[bytes, list]:
    """The ledger's bytes, read once under its lock, and the records parsed from them."""
    from kernel.filelock import locked

    path = project.path("ledger.jsonl")
    if not path.exists():
        return b"", []
    with locked(path.with_name(path.name + ".lock")):
        raw = path.read_bytes()
    return raw, _parsed(raw)


def _kept_head(project: Any) -> Any:
    """The head the cockpit keeps for this project, None when it keeps none. A heads file that cannot
    be read gives an empty head, which verify cannot compare: the chain is then not intact."""
    from kernel.store import read_json

    try:
        heads = read_json(project.factory.home.joinpath(*KEPT_HEADS), {})
    except (OSError, ValueError, RecursionError):
        return {}
    return heads.get(project.pid) if isinstance(heads, dict) else {}


def _ledger_check(records: list, kept: Any) -> dict:
    from kernel.ledger import verify

    check = verify(records, head=kept)
    return {"intact": check.intact, "broken_seq": check.broken_seq, "records": len(records),
            "tail_checked": check.tail_checked,
            "kept_head": {k: kept.get(k) for k in ("seq", "hash")} if isinstance(kept, dict) else None}


def _of(records: list, kind: str) -> list:
    """The payloads of one kind with when they happened, skipping records not shaped as the kernel
    writes them (the chain check reports those)."""
    out = []
    for r in records:
        event = r.get("event") if isinstance(r, dict) else None
        if isinstance(event, dict) and event.get("kind") == kind and isinstance(event.get("payload"), dict):
            out.append(event["payload"] | {"at": event.get("at")})
    return out


def _pack(project: Any) -> dict:
    """The capability pack of the latest release, or a note saying why there is none."""
    from kernel.packs import build_pack

    try:
        return build_pack(project)
    except LookupError:
        return {"note": "no release yet, so no capability pack"}
    except _UNREADABLE as exc:
        return {"note": f"no capability pack: the records could not be read ({type(exc).__name__})"}


def _evidence(project: Any) -> list:
    from kernel.status import evidence

    if not project.path("contract.json").exists():
        return []
    try:
        return evidence(project)
    except _UNREADABLE:
        return []


def _gather(project) -> tuple[dict, bytes]:
    """The bundle's files, and the ledger bytes they were taken from."""
    from kernel.repo_checks import evidence_files
    from kernel.security import summary as security_summary

    kept = _kept_head(project)                 # first: a kept head only moves on, so it lies within any later read
    pack = _pack(project)                       # before the read: building it may append to the ledger
    raw, records = _ledger_snapshot(project)
    runs = [{k: r.get(k) for k in ("task", "round", "role", "model", "endpoint", "surface_hash", "verdict", "chain",
                                   "tampered", "at")} for r in _of(records, "gnomon_run")]
    files = {
        "capability-pack.json": pack,
        "contract.json": project.read("contract.json") or {"note": "not compiled yet"},
        "evidence.json": _evidence(project),
        "decisions.json": _of(records, "decision"),
        "gates.json": _of(records, "gate"),
        "holdout-scores.json": (pack.get("acceptance") or {}).get("holdout_scores"),
        "gnomon-runs.json": runs,
        "ledger-check.json": _ledger_check(records, kept),
        "security.json": security_summary(project),
        "governance-map.json": _governance(project),
    }
    return files | evidence_files(project), raw     # an attached repository's own releases (evidence only)


# -- the governance map (docs/portability.md): which guarantee holds where a release runs --------------

GUARANTEES = ("pinning", "evals", "revocation", "evidence", "telemetry")
GOVERNANCE_STATES = ("held", "partial", "lost")
# Where the factory runs the release itself, by road kind; anything else is an export a site runs.
FACTORY_RUN = ("local-process", "docker", "azure-containerapps")
# A target resting on a platform feature nobody has verified: no guarantee there is ever "held".
UNVERIFIED = {"azure-containerapps": "it rests on Azure Container Apps, rendered and validated but never deployed "
                                     "(UNVERIFIED)"}


def _pinning(target: Any, artifacts: dict, guarded: bool) -> tuple[str, str]:
    from kernel.packs import pin_of

    hows = {road: pin_of(a)[1] for road, a in sorted(artifacts.items())}
    tags = [road for road, how in hows.items() if how == "tag"]
    if not hows or tags:
        return "lost", f"pinned by a movable tag on {', '.join(tags)}" if tags else "the release has no artifact"
    if target in FACTORY_RUN:
        return "held", f"the factory runs what it pinned, by {', '.join(sorted(set(hows.values())))}"
    loose = [f"{road} ({how})" for road, how in hows.items() if how != "digest"]
    if loose:
        return "partial", f"not pinned by a registry digest, so a site cannot pull it by one: {', '.join(loose)}"
    if not guarded:
        return "partial", "image by digest and pack by hash, but nothing at the site checks them at start"
    return "held", "image by digest and pack by hash; pack_guard checks the pack and the file trees at start"


def _guarantees(target: Any, artifacts: dict, signed: bool, guarded: bool) -> dict:
    pinning = _pinning(target, artifacts, guarded)
    if target in FACTORY_RUN:
        return {
            "pinning": pinning,
            "evals": ("held", "the gate and the holdouts ran here; the pack is valid only while its acceptance holds"),
            "revocation": ("partial", "a withdrawal is recorded and its status issued, but the factory's own roads "
                                      "do not stop on it yet"),
            "evidence": ("partial", "the ledger and the evidence pack stay in the factory; no SBOM yet"),
            "telemetry": ("partial", "probes and recorded traffic stay in the factory; no content-free telemetry yet"),
        }
    gaps = "; ".join(g for g, ok in (("the acceptance scores travel unsigned", signed),
                                     ("nothing re-runs the smoke set at start", guarded)) if not ok)
    return {
        "pinning": pinning,
        "evals": ("partial", gaps) if gaps
        else ("held", "signed acceptance scores, and pack_guard re-runs the public smoke set at start"),
        "revocation": ("partial", "pack_guard reads the expiring status document beside the pack; polling the "
                                  "site's URL is planned") if guarded
        else ("lost", "nothing at the site reads the status document"),
        "evidence": ("partial", f"SHA256SUMS and the evidence pack check offline "
                                f"({'signed' if signed else 'not signed'}); no SBOM yet"),
        "telemetry": ("lost", "no telemetry channel: the site reads not measured, never healthy"),
    }


def governance_map(target: Any, artifacts: dict, *, signed: bool = False, guarded: bool = False) -> list:
    """Each of the five guarantees (pinning, evals, revocation, evidence, telemetry) held, partial or
    lost where the release runs: ``target`` is a road kind the factory runs it on, or an export a site
    runs (`compose`, `offline-bundle`). ``signed``: the export's SHA256SUMS is signed; ``guarded``: the
    site runs pack_guard. A guarantee resting on an UNVERIFIED platform feature is never held."""
    rules = _guarantees(target, artifacts if isinstance(artifacts, dict) else {}, signed, guarded)
    out = []
    for name in GUARANTEES:
        state, why = rules[name]
        if state == "held" and target in UNVERIFIED:
            state, why = "partial", f"{why}; {UNVERIFIED[target]}"
        out.append({"guarantee": name, "state": state, "why": why})
    return out


def governance_line(gmap: list) -> str:
    return ", ".join(f"{g['guarantee']} {g['state']}" for g in gmap) or "no governance map"


def governance_lines(gmap: list) -> list:
    return [f"- **{g['guarantee']}**: {g['state']}: {g['why']}." for g in gmap] or ["- no governance map"]


def _governance(project: Any) -> dict:
    """The map where the latest release runs: its landing environment's road, as its deploy gate card had it."""
    from kernel.deliver import LANDING, latest_release

    try:
        rel = latest_release(project)
        if not isinstance(rel, dict):
            return {"target": None, "map": [], "note": "no release yet, so no governance map"}
        env = LANDING.get(str(rel.get("maturity")))
        target = ((rel.get("roads") or {}).get(env) or {}).get("kind")
        return {"target": target, "environment": env, "release": rel.get("release"),
                "map": governance_map(target, rel.get("artifacts") or {})}
    except _UNREADABLE:
        return {"target": None, "map": [], "note": "no governance map: the release records could not be read"}


def _chain_intact(run: Any) -> Any:
    chain = run.get("chain") if isinstance(run, dict) else None
    return chain.get("intact") if isinstance(chain, dict) else None


def _code(text: Any, limit: int = 120) -> str:
    """A value from outside the factory (a scanner's name or version) as one line of inline code:
    no line breaks, no backticks, no markup or table pipes, at most ``limit`` characters."""
    one = _MARKUP.sub("", _CONTROL.sub(" ", str(text))).strip()
    return f"`{one[:limit] or '-'}`"


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
    tools = ", ".join(_code(f"{s['tool']} {s['version']}") for s in sec["scans"])
    by = {"ai-act:art15": f"evidence.json, gates.json, holdout-scores.json; security.json: the latest scan by {tools}",
          "nis2:art21": "change control and approvals in decisions.json; security.json: scan findings and the risks "
                        "a named person accepted, with their expiry"}
    return [dict(c, by=by[c["control"]]) if c["control"] in by else c for c in CONTROLS]


UNCHECKED_END = ("the ledger's end was not checked against a head kept outside it, so records cut from its end "
                 "would not show")


def attestation(files: dict) -> dict:
    """attestable, chain broken, or insufficient evidence: never 'compliant'. A ledger verified
    without a kept head says so in the meaning."""
    lc = files["ledger-check.json"]
    runs = files["gnomon-runs.json"]
    pack = files["capability-pack.json"] if isinstance(files["capability-pack.json"], dict) else {}
    if not lc["intact"] or any(_chain_intact(r) is False for r in runs):
        verdict = "chain broken"
    elif not pack.get("acceptance") or not files["decisions.json"]:
        verdict = "insufficient evidence"
    else:
        verdict = "attestable"
    meaning = {
        "attestable": "the records are intact and complete enough for a reviewer to judge",
        "chain broken": "a hash chain did not verify: what it covers cannot be trusted as recorded",
        "insufficient evidence": "intact, but too little was recorded to judge (no release or no human decision)",
    }[verdict]
    out: dict[str, Any] = {"verdict": verdict, "meaning": meaning, "controls": _controls(files),
                           "not_measured": [c["criterion"] for c in files["evidence.json"]
                                            if c.get("state") == "not_measured"]}
    if "tail_checked" in lc:
        out["tail_checked"] = bool(lc["tail_checked"])
        if lc["intact"] and not lc["tail_checked"]:
            out["meaning"] = f"{meaning}; {UNCHECKED_END}"
    return out


def _security_line(sec: dict) -> str:
    if not sec.get("scans"):
        return sec.get("note") or "not measured: no security scan"
    scans = "; ".join(f"{_code(str(s['tool']) + ' ' + str(s['version']))} (scan {s['scan']}, "
                      f"sha256 {s['sha256'][:12]}: "
                      + (", ".join(f"{n} {lvl}" for lvl, n in s["counts"].items() if n) or "no findings") + ")"
                      for s in sec["scans"])
    return (f"{scans}; gate {sec['verdict']} ({sec['note']}); {len(sec.get('accepted_risks') or [])} risk(s) "
            "accepted by a named person until a date")


def _ledger_line(lc: dict) -> str:
    """The ledger's line in the README: its records, and how far its chain was checked."""
    if lc["intact"]:
        end = (f"its end checked against the head kept outside it (sequence {(lc.get('kept_head') or {}).get('seq')})"
               if lc.get("tail_checked") else UNCHECKED_END.replace("the ledger's end", "its end"))
        return f"- Project ledger: {lc['records']} records, hash chain intact at export; {end}."
    if lc.get("broken_seq") is None:
        return (f"- Project ledger: {lc['records']} records, hash chain NOT VERIFIED at export: the head kept "
                "outside it could not be compared.")
    return f"- Project ledger: {lc['records']} records, hash chain BROKEN at {lc['broken_seq']} at export."


def _pack_line(pack: dict) -> str:
    acc = pack.get("acceptance") or {}
    release = f"{acc['not_delivered']}; " if acc.get("not_delivered") else ""
    return (f"- Capability pack: version {pack.get('version', '—')}, {'valid' if acc.get('valid') else 'not valid'} "
            f"({release}{len(acc.get('not_valid_because') or [])} criteria not verified or held out).")


def _readme(project, files: dict) -> str:
    pack = files["capability-pack.json"] if isinstance(files["capability-pack.json"], dict) else {}
    lc = files["ledger-check.json"]
    title = _CONTROL.sub(" ", str(project.meta.get("title")))
    broken_runs = sum(1 for r in files["gnomon-runs.json"] if not _chain_intact(r))
    gov = files["governance-map.json"]
    where = (f"Where release {gov.get('release')} runs ({gov.get('target') or 'no road named'}), from "
             "`governance-map.json`:") if gov.get("map") else f"{gov.get('note')}."
    lines = [f"# Evidence pack: {title}", "",
             f"Project `{project.pid}`, profile {project.meta.get('profile', 'web_service')}, "
             f"maturity {project.meta.get('maturity')}.", "",
             "This bundle is evidence for a reviewer to judge. It does not claim conformity with any framework.", "",
             "## At a glance", "",
             _pack_line(pack),
             f"- Decisions by people: {len(files['decisions.json'])}. Gate verdicts: {len(files['gates.json'])}.",
             f"- Gnomon runs: {len(files['gnomon-runs.json'])}, of which audit chain not intact: {broken_runs}.",
             _ledger_line(lc),
             f"- Security: {_security_line(files.get('security.json') or {})}.",
             *([f"- The repository's own releases: {len(files['repository-releases.json'])}, each with its tag, commit "
                "and what the kernel checked there (`repository-releases.json`; dates as git states them)."]
               if files.get("repository-releases.json") else []),
             "", "## Governance map", "", where, "", *governance_lines(gov.get("map") or []),
             "", "## Not in this bundle", "",
             "- Holdout scenarios: they stay in their own custody. Only their scores are here.",
             "- Secrets and credentials: never recorded by the factory.",
             "- An SBOM and a signature, unless the capability pack names them.", "",
             "## Files", "", "`MANIFEST.json` lists every file with its sha256."]
    return "\n".join(lines) + "\n"


def _sha256(content: str | bytes) -> str:
    return hashlib.sha256(content if isinstance(content, bytes) else content.encode("utf-8")).hexdigest()


def _record(project: Any, payload: dict) -> None:
    """Record the export in the project's ledger. A line the store cannot read (not UTF-8, nested too
    deep) does not stop it: the record follows that line as it follows any broken record."""
    try:
        project.log("evidence_exported", payload)
    except (RecursionError, UnicodeDecodeError):
        _ReadingStore(project.path("ledger.jsonl"), clock=project.factory.clock).append("evidence_exported", payload)


def export(project: Any, out_dir: str | Path, *, person: str, persona: str) -> Path:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in EXPORTERS:
        raise DecisionRefused(f"a {persona} may not export evidence; {', '.join(EXPORTERS)} may")
    files, ledger_raw = _gather(project)
    texts: dict[str, str | bytes] = {name: json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n"
                                     for name, value in files.items()}
    texts["spec.md"] = project.path("spec.md").read_text(encoding="utf-8") if project.path("spec.md").exists() else ""
    texts["ledger.jsonl"] = ledger_raw          # the very bytes ledger-check.json describes
    att = attestation(files)
    texts["attestation.json"] = json.dumps(att, indent=2, ensure_ascii=False) + "\n"
    texts["README.md"] = _readme(project, files) + (
        f"\n## Attestation\n\n**{att['verdict']}**: {att['meaning']}. This is not a statement of conformity.\n\n"
        "| Control | Topic | Evidence | Where |\n|---|---|---|---|\n"
        + "".join(f"| `{c['control']}` | {c['topic']} | {c['status']} | {c['by']} |\n" for c in att["controls"]))
    manifest = {name: _sha256(t) for name, t in sorted(texts.items())}
    stamp = project.factory.clock.stamp().replace(":", "").replace("-", "")
    listing = json.dumps({"files": manifest, "project": project.pid, "exported_by": person, "persona": persona},
                         indent=2) + "\n"
    out = _write_new_zip(Path(out_dir), f"{project.pid}-evidence-{stamp}", texts, listing)
    _record(project, {"file": out.name, "by": person, "persona": persona, "verdict": att["verdict"],
                      "manifest_sha256": _sha256(json.dumps(manifest, sort_keys=True))})
    return out


def _write_new_zip(out_dir: Path, stem: str, texts: dict, manifest: str) -> Path:
    """Write the bundle under a name no file has yet: ``<stem>.zip``, else ``<stem>-2.zip`` and on.
    An export never replaces another, so each ledger record keeps naming the file it hashed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        out = out_dir / (f"{stem}.zip" if n == 1 else f"{stem}-{n}.zip")
        try:
            z = zipfile.ZipFile(out, "x", compression=zipfile.ZIP_DEFLATED)
        except FileExistsError:
            n += 1
            continue
        with z:
            for name, t in sorted(texts.items()):
                z.writestr(name, t)
            z.writestr("MANIFEST.json", manifest)
        return out
