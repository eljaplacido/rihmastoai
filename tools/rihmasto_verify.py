#!/usr/bin/env python3
"""rihmasto_verify: check a Rihmasto offline bundle, or an evidence pack, offline (FR-PT4).

One standard-library file that imports nothing from Rihmasto, so anyone can read it and run it with
nothing installed (docs/portability.md). It checks:
- SHA256SUMS: every listed file has its sha256, and every file but the signature's and the status's
  own is listed; a changed byte is named by its file;
- the capability pack: its content hashes to its content_sha256. The hash is sha256 over canonical
  JSON (keys sorted, no whitespace, UTF-8, no NaN or Infinity) of the pack without its unhashed
  fields. The pack holds no floats: this canonical form is not RFC 8785;
- BUNDLE.json, deploy-package.json and pack-status.json name that pack's version and hash, the deploy
  package names the image by the digest the pack pins, and the status is valid and unexpired at --at;
- the source zip's app files against the pack's app_files_sha256;
- the evidence pack (evidence.zip in a bundle, or the zip given): MANIFEST.json and the ledger's
  hash chain;
- in-toto statements: none yet (phase 2), so "not applicable";
- signatures: `cosign verify-blob` on SHA256SUMS.sigstore.json and on the status's own signature,
  against the key the factory published (--key), when cosign is on PATH. The cosign.pub inside the
  bundle is never trusted: whoever changed the bundle could have signed it again and replaced that
  file. Without cosign a line reads "not verified: no verifier", without --key "not verified: no
  trusted key", never "verified"; without a signature it reads "not signed". In a signed bundle the
  status must be signed too, and with --key a bundle must be signed: a signature that is missing
  there fails.
With schemas (--schemas DIR, by default schemas/ beside this file when it is there) the JSON files are
checked against Rihmasto's published schemas too.

The verdict is "passed" only when every check passed and every signature was verified against
--key; "failed" when any check failed; otherwise it says why nothing proves who made the bundle
("not verified: no verifier", "not verified: no trusted key" or "not signed"), never "passed".

Exit codes: 0 passed, 2 failed, 3 not verified or not signed (every other check passed), 4 not
measured (nothing readable was given).

Usage: python tools/rihmasto_verify.py BUNDLE --key factory-cosign.pub [--at 2026-11-22T12:00:00Z] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UNSUMMED = ("SHA256SUMS", "SHA256SUMS.sig", "signature.json", "SHA256SUMS.sigstore.json", "trusted_root.json",
            "cosign.pub", "pack-status.json", "pack-status.json.sigstore.json")
PACK_UNHASHED = ("acceptance", "provenance", "security", "version", "content_sha256")
SCHEMAS = {"capability-pack.json": "capability-pack.v1.schema.json", "BUNDLE.json": "offline-bundle.v1.schema.json",
           "deploy-package.json": "deploy-package.v2.schema.json", "pack-status.json": "pack-status.v1.schema.json"}
NO_VERIFIER = "not verified: no verifier"
NO_TRUSTED_KEY = "not verified: no trusted key"
NOT_SIGNED = "not signed"
STATUS_FILE = "pack-status.json"
EXIT = {"passed": 0, "failed": 2}  # any other verdict: 3, nothing proves who made it
CRLF, LF = b"\r\n", b"\n"
TYPES: dict[str, Any] = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
                         "boolean": bool, "null": type(None)}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line(check: str, verdict: str, detail: str) -> dict:
    return {"check": check, "verdict": verdict, "detail": detail}


def _judged(check: str, failed: list[str], passed: str) -> dict:
    return _line(check, "failed", "; ".join(failed)) if failed else _line(check, "passed", passed)


def read_files(target: Path) -> dict[str, bytes]:
    """Every file of a bundle folder or zip, by its path inside it (forward slashes)."""
    if target.is_dir():
        return {p.relative_to(target).as_posix(): p.read_bytes() for p in sorted(target.rglob("*")) if p.is_file()}
    with zipfile.ZipFile(target) as z:
        return {name: z.read(name) for name in z.namelist() if not name.endswith("/")}


def _unzip(blob: bytes) -> dict[str, bytes]:
    """The files of a zip inside the bundle; none when it is not a readable zip (its sha256 says why)."""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return {name: z.read(name) for name in z.namelist() if not name.endswith("/")}
    except (zipfile.BadZipFile, OSError, ValueError, EOFError, NotImplementedError, zlib.error):
        return {}


def _load(files: dict[str, bytes], name: str) -> Any:
    try:
        return json.loads(files[name].decode("utf-8")) if name in files else None
    except ValueError:
        return None


def pack_sha256(pack: dict) -> str:
    """The content_sha256 Rihmasto gives a pack: canonical JSON of it without the unhashed fields
    (the acceptance but its criteria and holdout scores, the ledger head, the site mode's source)."""
    hashed = {key: value for key, value in pack.items() if key not in PACK_UNHASHED}
    acceptance = pack.get("acceptance") or {}
    hashed["acceptance"] = {"criteria": acceptance.get("criteria"), "holdout_scores": acceptance.get("holdout_scores")}
    hashed["provenance"] = {k: v for k, v in (pack.get("provenance") or {}).items() if k != "ledger_head"}
    declared = hashed.get("declared")
    if isinstance(declared, dict) and isinstance(declared.get("site_mode"), dict):
        site = {k: v for k, v in declared["site_mode"].items() if k != "source"}
        hashed["declared"] = {**declared, "site_mode": site}
    canonical = json.dumps(hashed, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return _sha(canonical.encode("utf-8"))


# -- the checks ---------------------------------------------------------------------------------------

def check_sums(files: dict[str, bytes]) -> dict:
    """SHA256SUMS holds for every file it lists, and lists every file but the unsummed ones."""
    if "SHA256SUMS" not in files:
        return _line("SHA256SUMS", "failed", "the bundle has no SHA256SUMS")
    listed = {}
    for row in files["SHA256SUMS"].decode("utf-8", "replace").splitlines():
        digest, _, name = row.partition("  ")
        listed[name] = digest
    failed = [f"{name} is listed but missing" if name not in files else f"{name} does not match its sha256"
              for name, digest in sorted(listed.items()) if name not in files or _sha(files[name]) != digest]
    failed += [f"{name} is not listed" for name in sorted(files) if name not in listed and name not in UNSUMMED]
    return _judged("SHA256SUMS", failed, f"{len(listed)} files match")


def check_pack(pack: Any) -> dict:
    if not isinstance(pack, dict):
        return _line("capability pack", "failed", "capability-pack.json is missing or not JSON")
    digest = pack_sha256(pack)
    wrong = [] if digest == pack.get("content_sha256") else ["capability-pack.json: its content does not hash to "
                                                             "its content_sha256"]
    return _judged("capability pack", wrong, f"version {pack.get('version')}, content_sha256 {digest}")


def _names_pack(name: str, doc: Any, pack: dict, keys: tuple[str, str]) -> list[str]:
    if not isinstance(doc, dict):
        return [f"{name} is not JSON"]
    got = [doc.get(keys[0]), doc.get(keys[1])]
    return [] if got == [pack.get("version"), pack.get("content_sha256")] else [f"{name} names another pack: {got}"]


def check_links(files: dict[str, bytes], pack: dict) -> dict:
    """BUNDLE.json and deploy-package.json name the pack; the deploy package's image is the pinned digest."""
    failed = _names_pack("BUNDLE.json", _load(files, "BUNDLE.json"), pack, ("pack_version", "pack_content_sha256"))
    pkg = _load(files, "deploy-package.json")
    if "deploy-package.json" in files:
        named = (pkg or {}).get("pack") if isinstance(pkg, dict) else None
        failed += _names_pack("deploy-package.json", named, pack, ("version", "content_sha256"))
        art, road = (pkg or {}).get("artifact") or {}, ((pkg or {}).get("road") or {}).get("name")
        pinned = ((pack.get("pinned") or {}).get("artifacts") or {}).get(road)
        if art.get("digest") and pinned != art.get("ref"):
            failed.append(f"deploy-package.json: image {art.get('ref')} is not the one the pack pins ({pinned})")
    return _judged("pack named alike", failed, "BUNDLE.json and the deploy package name this pack and its image")


def check_status(doc: Any, pack: dict, at: datetime) -> dict:
    """The status document beside the pack: this pack, valid, unexpired at ``at``."""
    if doc is None:
        return _line("status", "not applicable", "no pack-status.json in the bundle")
    failed = _names_pack("pack-status.json", doc, pack, ("version", "content_sha256"))
    if failed or not isinstance(doc, dict):
        return _judged("status", failed, "")
    if doc.get("format") != "rihma.pack-status/1":
        failed.append("pack-status.json is not rihma.pack-status/1")
    if doc.get("state") != "valid":
        who = (doc.get("decided_by") or {}).get("person")
        failed.append(f"the pack is {doc.get('state')}: {doc.get('reason')}" + (f" (decided by {who})" if who else ""))
    try:
        if datetime.fromisoformat(str(doc.get("expires_at")).replace("Z", "+00:00")) < at:
            failed.append(f"pack-status.json expired at {doc.get('expires_at')}")
    except ValueError:
        failed.append("pack-status.json has no readable expires_at")
    return _judged("status", failed, f"valid until {doc.get('expires_at')}")


def check_trees(files: dict[str, bytes], pack: dict) -> dict:
    """The source zip's app files hash, CRLF read as LF, to the pack's app_files_sha256."""
    want = (pack.get("pinned") or {}).get("app_files_sha256")
    sources = sorted(n for n in files if n.startswith("source/") and n.endswith(".zip"))
    if not want or not sources:
        return _line("app files", "not applicable", "the pack pins no app files, or the bundle holds no source")
    app = {n.split("/", 1)[1]: data for n, data in _unzip(files[sources[0]]).items()
           if n.split("/", 1)[-1].startswith("app/") and not n.endswith(".pyc") and "/__pycache__/" not in n}
    rows ="".join(_sha(data.replace(CRLF, LF)) + "  " + name + "\n" for name, data in sorted(app.items()))
    wrong = [] if _sha(rows.encode("utf-8")) == want else [f"{sources[0]}: its app files do not hash to "
                                                          "the pack's app_files_sha256"]
    return _judged("app files", wrong, f"{len(app)} app files hash to the pack's app_files_sha256")


def _chained(rec: Any, seq: int, prev: str | None) -> bool:
    if not isinstance(rec, dict) or set(rec) != {"seq", "event", "prev", "hash"}:
        return False
    if type(rec["seq"]) is not int or rec["seq"] != seq or rec["prev"] != prev:
        return False
    chained = {"event": rec["event"], "prev": prev, "seq": seq}
    return bool(rec["hash"] == _sha(json.dumps(chained, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                               allow_nan=False).encode("utf-8")))


def check_ledger(raw: bytes, where: str) -> dict:
    """The ledger's hash chain: each record hashes its sequence, its event and the hash before it."""
    prev, count = None, 0
    for seq, row in enumerate(r for r in raw.splitlines() if r.strip()):
        try:
            rec = json.loads(row.decode("utf-8"))
        except ValueError:
            return _line("ledger chain", "failed", f"{where}: ledger line {seq} is not JSON")
        if not _chained(rec, seq, prev):
            return _line("ledger chain", "failed", f"{where}: the hash chain breaks at record {seq}")
        prev, count = rec["hash"], seq + 1
    return _line("ledger chain", "passed", f"{where}: {count} records chained")


def check_evidence(inner: dict[str, bytes], where: str) -> list[dict]:
    """An evidence pack's MANIFEST.json holds for every file, and its ledger's chain is intact."""
    if not inner:
        return [_line("evidence manifest", "failed", f"{where} is not a readable zip")]
    manifest =(_load(inner, "MANIFEST.json") or {}).get("files") or {}
    failed = [f"{where}: {name} does not match MANIFEST.json" for name, digest in sorted(manifest.items())
              if _sha(inner.get(name, b"")) != digest or name not in inner]
    failed += [f"{where}: {name} is not in MANIFEST.json" for name in sorted(inner)
               if name not in manifest and name != "MANIFEST.json"]
    if not manifest:
        failed.append(f"{where}: no MANIFEST.json")
    return [_judged("evidence manifest", failed, f"{where}: {len(manifest)} files match"),
            check_ledger(inner.get("ledger.jsonl", b""), where)]


def _cosign(files: dict[str, bytes], blob: str, key: str, cosign: str) -> dict:
    """`cosign verify-blob` of one signed file against the factory's published key, never the bundle's."""
    name = f"signature of {blob}"
    with tempfile.TemporaryDirectory(prefix="rihmasto-verify-") as tmp:
        for part in (blob, f"{blob}.sigstore.json", "trusted_root.json"):
            if part in files:
                Path(tmp, part).write_bytes(files[part])
        argv = [cosign, "verify-blob", "--key", key, "--bundle", str(Path(tmp, f"{blob}.sigstore.json")),
                "--insecure-ignore-tlog=true"]
        argv += ["--trusted-root", str(Path(tmp, "trusted_root.json"))] if "trusted_root.json" in files else []
        proc = subprocess.run([*argv, str(Path(tmp, blob))], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, timeout=300, check=False)
    if proc.returncode != 0:
        return _line(name, "failed", f"cosign verify-blob against {key} failed (exit {proc.returncode}): "
                                     f"{proc.stderr[-300:]}")
    return _line(name, "verified", f"cosign verified {blob} against the key {key}")


def _signed_files(files: dict[str, bytes]) -> tuple[list[str], list[dict]]:
    """What a signed bundle must carry signed: SHA256SUMS, and the status, which SHA256SUMS does not
    cover. A status without its signature, or missing where BUNDLE.json (inside SHA256SUMS) names one,
    fails: anyone could have replaced or removed it, and with it the expiry and a withdrawal."""
    blobs, failed, bundle = ["SHA256SUMS"], [], _load(files, "BUNDLE.json")
    named = bundle.get("status") if isinstance(bundle, dict) else None
    if STATUS_FILE in files:
        if f"{STATUS_FILE}.sigstore.json" in files:
            blobs.append(STATUS_FILE)
        else:
            failed.append(_line(f"signature of {STATUS_FILE}", "failed", "the bundle is signed but its status "
                                "document is not: anyone could have replaced it, so it is not trusted"))
    elif isinstance(named, dict) and named.get("file"):
        failed.append(_line(f"signature of {STATUS_FILE}", "failed", f"BUNDLE.json names {named['file']}, and the "
                            "bundle holds none: a status (and a withdrawal) cannot be removed"))
    return blobs, failed


def check_signatures(files: dict[str, bytes], key: str | None, cosign: str | None) -> list[dict]:
    """Each signature, verified only against ``key``, the key the factory published. The cosign.pub in
    the bundle is never trusted: whoever changed the bundle could have signed it again and replaced it."""
    if "SHA256SUMS.sigstore.json" not in files:
        if key:
            return [_line("signature of SHA256SUMS", "failed", "--key expects the factory's signature, and the bundle "
                          "holds no SHA256SUMS.sigstore.json: it was never signed, or its signature was removed")]
        return [_line("signature of SHA256SUMS", NOT_SIGNED, "the bundle holds no SHA256SUMS.sigstore.json, so "
                      "nothing shows who made it")]
    blobs, out = _signed_files(files)
    if cosign is None:
        why = "cosign is not installed, so the signature was not checked" + ("" if key else " (and no --key was given)")
        return out + [_line(f"signature of {b}", NO_VERIFIER, why) for b in blobs]
    if not key:
        why = ("pass the key the factory published with --key: the cosign.pub in the bundle proves nothing, "
               "whoever changed the bundle could have signed it again and replaced that file")
        return out + [_line(f"signature of {b}", NO_TRUSTED_KEY, why) for b in blobs]
    return out + [_cosign(files, b, key, cosign) for b in blobs]


# -- the published schemas, in the subset they use ----------------------------------------------------

def _type_ok(value: Any, name: str) -> bool:
    return not (name in ("integer", "number") and isinstance(value, bool)) and isinstance(value, TYPES[name])


def _value_problems(value: Any, schema: dict, path: str) -> list[str]:
    kinds = schema.get("type")
    if kinds is not None and not any(_type_ok(value, k) for k in ([kinds] if isinstance(kinds, str) else kinds)):
        return [f"{path}: expected {kinds}, got {type(value).__name__}"]
    out = []
    if "const" in schema and value != schema["const"]:
        out.append(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        out.append(f"{path}: {value!r} does not match {schema['pattern']}")
    return out


def _object_problems(value: dict, schema: dict, root: dict, path: str) -> list[str]:
    out = [f"{path}: no {k}" for k in schema.get("required", []) if k not in value]
    props, extra = schema.get("properties", {}), schema.get("additionalProperties", True)
    for k, v in value.items():
        if k in props or isinstance(extra, dict):
            out += schema_problems(v, props.get(k, extra), root, f"{path}.{k}")
        elif extra is False:
            out.append(f"{path}: unexpected {k}")
    return out


def schema_problems(value: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    """What ``value`` breaks of a JSON Schema (2020-12), in the subset Rihmasto's schemas use: a local
    $ref, type, const, enum, pattern, required, properties, additionalProperties, items and anyOf."""
    root = root or schema
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
    out = _value_problems(value, schema, path)
    if out:
        return out
    if isinstance(value, dict):
        out += _object_problems(value, schema, root, path)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            out += schema_problems(item, schema["items"], root, f"{path}[{i}]")
    if "anyOf" in schema and all(schema_problems(value, s, root, path) for s in schema["anyOf"]):
        out.append(f"{path}: matches none of its anyOf")
    return out


def check_schemas(files: dict[str, bytes], folder: Path | None) -> dict:
    if folder is None or not folder.is_dir():
        return _line("schemas", "not measured", "no schemas folder: pass --schemas DIR")
    failed: list[str] = []
    for name, schema_file in SCHEMAS.items():
        if name in files:
            schema = json.loads((folder / schema_file).read_text(encoding="utf-8"))
            failed += [f"{name} {p}" for p in schema_problems(_load(files, name), schema)]
    return _judged("schemas", failed[:20], f"the JSON files conform to {folder.name}/")


# -- the whole run ------------------------------------------------------------------------------------

def verify(target: Path, *, key: str | None = None, at: datetime | None = None, schemas: Path | None = None,
           cosign: str | None = None) -> dict:
    """Every check on an offline bundle (a folder or zip) or an evidence pack (a zip), and the verdict."""
    files, at = read_files(target), at or datetime.now(UTC)
    cosign = cosign or shutil.which("cosign")
    if "SHA256SUMS" not in files and "MANIFEST.json" in files:
        checks = check_evidence(files, target.name) + [
            _line("signature", NOT_SIGNED, "an evidence pack is not signed: its MANIFEST.json shows it is whole, "
                  "not who made it")]
        return {"target": str(target), "kind": "evidence pack", "checks": checks, "verdict": verdict(checks)}
    pack = _load(files, "capability-pack.json")
    checks = [check_sums(files), check_pack(pack)]
    if isinstance(pack, dict):
        checks += [check_links(files, pack), check_status(_load(files, "pack-status.json"), pack, at),
                   check_trees(files, pack)]
    if "evidence.zip" in files:
        checks += check_evidence(_unzip(files["evidence.zip"]), "evidence.zip")
    checks += [_line("statements", "not applicable", "no in-toto statements in this bundle (planned)"),
               check_schemas(files, schemas), *check_signatures(files, key, cosign)]
    return {"target": str(target), "kind": "offline bundle", "checks": checks, "verdict": verdict(checks)}


def verdict(checks: list[dict]) -> str:
    """failed when any check failed; passed only when every signature was verified against the
    factory's key; otherwise why it was not ("not verified: ...", "not signed"), never passed."""
    if any(c["verdict"] == "failed" for c in checks):
        return "failed"
    signatures = [c["verdict"] for c in checks if c["check"].startswith("signature")]
    unproven = [v for v in signatures if v != "verified"]
    if not signatures:
        return NOT_SIGNED
    return unproven[0] if unproven else "passed"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rihmasto_verify", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="an offline bundle (folder or zip) or an evidence pack (zip)")
    ap.add_argument("--key", help="the cosign public key the factory published (a file or a KMS reference); the "
                                  "cosign.pub inside the bundle is never trusted")
    ap.add_argument("--at", help="judge the status's expiry at this ISO time (default: now)")
    ap.add_argument("--schemas", help="the published schemas folder (default: schemas/ beside this file)")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = ap.parse_args(argv)
    beside = Path(__file__).resolve().parent.parent / "schemas"
    try:
        at = datetime.fromisoformat(args.at.replace("Z", "+00:00")) if args.at else None
        report = verify(Path(args.target), key=args.key, at=at,
                        schemas=Path(args.schemas) if args.schemas else (beside if beside.is_dir() else None))
    except (OSError, ValueError, EOFError, zipfile.BadZipFile, zlib.error) as exc:
        print(f"not measured: {args.target} could not be read ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 4
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for c in report["checks"]:
            print(f"{c['verdict']:<14} {c['check']}: {c['detail']}")
        print(f"verdict: {report['verdict']}")
    return EXIT.get(report["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
