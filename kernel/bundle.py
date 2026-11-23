"""Offline bundles: one release in one folder or zip, to install or audit with no network (FR-Q6-AC-4,
FR-PT1 to FR-PT5; docs/portability.md, phase 1).

A bundle holds:
- `capability-pack.json` and `capability-pack.yaml`: the release's capability pack;
- `contract.json`: the contract as the product carried it at the pinned revision;
- `source/product-<rev12>.zip`: the product's source at the pinned revision (`git archive`);
- `image.json`: each artifact's reference; `images/<name>.tar` only when docker is on PATH and the
  image is present on this host (`docker save`), otherwise the reason it is not there;
- `deploy-package.json`: the site's deploy package (`gnomonfactory.deploy_package/2`): the release's
  package for its landing environment, naming the image by digest and the pack by version and hash;
- `compose.yaml`, when the image is pinned by digest: any Docker or Podman host runs the release
  with it (`kernel.roads.render_compose`), the pack and its status mounted beside the image, read-only;
- `evidence.zip`: an evidence pack (kernel/evidence_pack.py), exported by the same person;
- `rihmasto_verify.py`: the offline verifier, when the checkout has `tools/`;
- `BUNDLE.json` and `README.md`: what is in the bundle and what is not, and its governance map;
- `SHA256SUMS`: the sha256 of every file above, in the format `sha256sum -c` reads.

Outside SHA256SUMS, because they sign it or change after it:
- `signature.json`; and, only when cosign is on PATH and `RIHMA_COSIGN_KEY` names a key (a reference:
  the key itself is never read or stored), `SHA256SUMS.sigstore.json`, a Sigstore bundle. cosign 3.1
  and later refuse to sign a blob without bundle output or a registry upload, so a detached
  `--output-signature` is never asked for. cosign signs offline (`--tlog-upload=false`) and also writes
  `cosign.pub` and `trusted_root.json`, so `cosign verify-blob` runs with no network. `cosign.pub` is
  for reference only: a site verifies against the key the factory published (VERIFY_WITH), since
  whoever changed a bundle could sign it again and replace that file. Without cosign the bundle says
  "not signed: cosign not installed". A signature is never made up.
- `pack-status.json` (`rihma.pack-status/1`): the pack's status when the bundle was made, and its
  signature `pack-status.json.sigstore.json`. It expires; a site replaces it with a fresh copy, and a
  withdrawal (`withdraw`, a named person's ledgered act) issues one that says `withdrawn`. BUNDLE.json
  names it, so a signed bundle's status cannot be removed or left unsigned unseen.

UNVERIFIED against a real cosign 3.1.4 (not installed where this was built): the exact flags
`--use-signing-config=false` and `trusted-root create` with no services. The tests run a stand-in
cosign that enforces the bundle rule.

The export is recorded in the project's ledger with the person who asked for it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import is_person

KEY_ENV = "RIHMA_COSIGN_KEY"
STATUS = "pack-status.json"
WITHDRAWALS = "pack-withdrawals.json"  # in the project: each withdrawn version, its reason and person
SIGNED_BY = ("SHA256SUMS.sigstore.json", "trusted_root.json", "cosign.pub", STATUS, STATUS + ".sigstore.json")
UNSUMMED = ("SHA256SUMS", "SHA256SUMS.sig", "signature.json", *SIGNED_BY)
# The key is the one the factory published (`cosign public-key --key $RIHMA_COSIGN_KEY`), handed to the
# site apart from the bundle: never the bundle's own cosign.pub, which proves nothing.
VERIFY_WITH = ("cosign verify-blob --key factory-cosign.pub --bundle SHA256SUMS.sigstore.json "
               "--trusted-root trusted_root.json --insecure-ignore-tlog=true SHA256SUMS")
STATUS_FORMAT = "rihma.pack-status/1"
STATUS_STATES = ("valid", "suspended", "superseded", "withdrawn")
WITHDRAWERS = ("it", "compliance", "product_owner")
STATUS_DAYS = 30
# The files the image copies besides app/ (the template's Dockerfile): their tree is pinned apart.
RUNTIME_FILES = ("factory/look.json", "factory/pack_guard.py")
CRLF, LF = b"\r\n", b"\n"
Runner = Callable[[list, float], tuple]


def _run(argv: list, timeout: float) -> tuple:
    """(exit, stdout, stderr). A tool that cannot start or does not finish is an exit code, so the
    bundle says why something is missing instead of failing."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout, check=False)
    except OSError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return 124, "", f"did not finish in {timeout} s"
    return proc.returncode, proc.stdout, proc.stderr


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


# -- the product's file trees, as pack_guard hashes them in the image --------------------------------

def tree_sha256(files: dict) -> str:
    """sha256 over one line per file, `<sha256 of its bytes, CRLF read as LF>  <path>`, sorted by path.
    Line endings are read as LF so a checkout made with core.autocrlf hashes as the repository does."""
    lines = [f"{hashlib.sha256(data.replace(CRLF, LF)).hexdigest()}  {name}\n" for name, data in sorted(files.items())]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _kept(name: str) -> bool:
    return "__pycache__" not in name.split("/") and not name.endswith(".pyc")


def product_trees(project: Any, revision: Any) -> dict:
    """The pack's pins on the product's files at ``revision``: `app_files_sha256` (every file under
    app/) and `runtime_files_sha256` (RUNTIME_FILES the product has). pack_guard recomputes both inside
    the container, so an edited file keeps it from ever becoming ready."""
    try:
        data = subprocess.run(["git", "archive", "--format=tar", str(revision)], cwd=project.path("repo.git"),
                              capture_output=True, check=True, timeout=120, stdin=subprocess.DEVNULL).stdout
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            files = {m.name: (tar.extractfile(m) or io.BytesIO()).read() for m in tar.getmembers()
                     if m.isfile() and _kept(m.name)}
    except (OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
        return {"app_files_sha256": None, "runtime_files": [], "runtime_files_sha256": None,
                "trees_note": f"not pinned: the product's files at {revision} could not be read ({type(exc).__name__})"}
    app = {n: d for n, d in files.items() if n.startswith("app/")}
    runtime = {n: files[n] for n in RUNTIME_FILES if n in files}
    out: dict[str, Any] = {"app_files_sha256": tree_sha256(app) if app else None, "runtime_files": sorted(runtime),
                           "runtime_files_sha256": tree_sha256(runtime) if runtime else None}
    if "factory/pack_guard.py" not in runtime:
        out["trees_note"] = "no pack_guard: built from an earlier template, so nothing checks these pins at start"
    elif not guard_starts(files.get("Dockerfile", b"")):
        out["trees_note"] = ("pack_guard is not the image's entrypoint (the Dockerfile's CMD), so nothing checks "
                             "these pins at start")
    return out


def guard_starts(dockerfile: bytes) -> bool:
    """Whether the Dockerfile's last CMD runs factory/pack_guard.py (protected), never app/server.py."""
    cmds = [line for line in dockerfile.decode("utf-8", "replace").splitlines() if line.strip().startswith("CMD")]
    return bool(cmds) and "factory/pack_guard.py" in cmds[-1]


# -- the status document and withdrawal ---------------------------------------------------------------

def _stamp(moment: dt.datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def status_document(project: Any, pack: dict, *, days: int = STATUS_DAYS) -> dict:
    """The pack's status (`rihma.pack-status/1`) as of now: `withdrawn` when a person withdrew its
    version, else `valid` while its acceptance holds, else `suspended`. It expires after ``days``: an
    expired status is not trusted (the TUF rule), so a site needs a fresh copy."""
    now = project.factory.clock.now()
    acc = pack.get("acceptance") or {}
    withdrawn = (project.read(WITHDRAWALS, {}) or {}).get(pack["version"])
    by = None
    if isinstance(withdrawn, dict):
        state, reason = "withdrawn", str(withdrawn.get("reason"))
        by = {k: withdrawn.get(k) for k in ("person", "persona", "at")}
    elif acc.get("valid"):
        state, reason = "valid", "its acceptance holds"
    else:
        state, reason = "suspended", acc.get("not_delivered") or "its acceptance does not hold: " + ", ".join(
            f"{c.get('criterion')} {c.get('state')}" for c in acc.get("not_valid_because") or [])
    return {"format": STATUS_FORMAT, "pack": pack["pack"], "version": pack["version"],
            "content_sha256": pack["content_sha256"], "state": state, "reason": reason, "decided_by": by,
            "issued_at": _stamp(now), "expires_at": _stamp(now + dt.timedelta(days=days)), "revoked_key_ids": []}


def withdraw(project: Any, version: str, *, person: str, persona: str, reason: str,
             which: Callable = shutil.which, run: Runner = _run) -> dict:
    """A named person with the it, compliance or product_owner persona withdraws a pack version. It is
    recorded in the ledger with them, and a status document saying `withdrawn` is issued (signed when
    cosign can sign) for the sites to place beside the pack: their pack_guard then answers 503."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in WITHDRAWERS:
        raise DecisionRefused(f"a {persona} may not withdraw a pack; {', '.join(WITHDRAWERS)} may")
    if not str(reason).strip():
        raise ValueError("a withdrawal needs a reason")
    history = project.read("packs.json", []) or []
    entry = next((h for h in history if isinstance(h, dict) and h.get("version") == version), None)
    if entry is None:
        raise LookupError(f"no capability pack version {version} in packs.json")
    statuses = project.read(WITHDRAWALS, {}) or {}
    statuses[version] = {"state": "withdrawn", "reason": reason, "person": person, "persona": persona,
                         "at": project.factory.clock.stamp()}
    project.write(WITHDRAWALS, statuses)
    project.log("pack_withdrawn", {"version": version, "content_sha256": entry["content_sha256"], "by": person,
                                   "persona": persona, "reason": reason})
    doc = status_document(project, {"pack": project.pid, "version": version, "content_sha256": entry["content_sha256"]})
    folder = project.path("pack-status")
    _write(folder / f"{version}.json", _json(doc))
    return {"status": doc, "file": str(folder / f"{version}.json"),
            "signature": _sign(folder, f"{version}.json", which, run)}


def pack_command(factory: Any, args: Any, show: Callable) -> None:
    """`rihmasto pack withdraw <pid> "why" --person P --persona X [--release N]`: withdraw the pack of
    release N, or the newest pack, and show the status document it issued."""
    from kernel.packs import latest_pack

    if len(args.words) != 2:
        raise ValueError('say it as: rihmasto pack withdraw <pid> "why" --person <name> --persona <persona>')
    if not (args.person and args.persona):
        raise DecisionRefused("a withdrawal is signed: give --person and --persona")
    project = factory.project(args.words[0])
    pack = project.read(f"releases/{args.release}/capability-pack.json") if args.release else latest_pack(project)
    if not isinstance(pack, dict) or not pack.get("version"):
        raise LookupError("no capability pack to withdraw: build one first (rihmasto pack <pid>)")
    show(withdraw(project, pack["version"], person=args.person, persona=args.persona, reason=args.words[1]))


# -- the site's deploy package ------------------------------------------------------------------------

def deploy_package(project: Any, pack: dict) -> tuple[dict | None, str]:
    """The deploy package a site runs (`gnomonfactory.deploy_package/2`): the release's package for its
    landing environment, with the image as the release pins it now (by digest once pinned) and the pack
    it belongs to by version and hash. None, and why, when the release was never deployed there."""
    from kernel.deliver import LANDING
    from kernel.roads import SITE_PACKAGE_SCHEMA

    rel = project.read(f"releases/{pack['release']}.json") or {}
    env = LANDING.get(str(rel.get("maturity")))
    name = (rel.get("packages") or {}).get(f"{env}:current")
    base = project.read(name) if name else None
    if not isinstance(base, dict):
        return None, f"release {pack['release']} has no deploy package for {env}: it was never deployed there"
    pinned = (rel.get("artifacts") or {}).get((base.get("road") or {}).get("name"))
    if isinstance(pinned, dict) and pinned.get("digest") and isinstance(base.get("artifact"), dict):
        base = {**base, "artifact": {**base["artifact"], **pinned}}
    return {**base, "schema": SITE_PACKAGE_SCHEMA,
            "pack": {"format": pack["format"], "version": pack["version"], "content_sha256": pack["content_sha256"],
                     "file": "capability-pack.json", "status_file": STATUS}}, f"from {name}"


# -- what goes in the bundle --------------------------------------------------------------------------

def _contract(project: Any, revision: str, folder: Path) -> str:
    """The contract the product carried at its pinned revision; the project's own when the
    product's history does not hold one, and then the bundle says so."""
    from kernel.lanes import _git

    try:
        text = _git(project.path("repo.git"), "show", f"{revision}:contract.json") + "\n"
        source = f"the product repository at {revision[:12]}"
    except RuntimeError:
        text, source = _json(project.read("contract.json") or {}), "the project's current contract.json"
    _write(folder / "contract.json", text)
    return source


def _source(project: Any, revision: str, folder: Path) -> str:
    from kernel.lanes import _git

    name = f"source/product-{revision[:12]}.zip"
    (folder / "source").mkdir(parents=True, exist_ok=True)
    try:
        _git(project.path("repo.git"), "archive", "--format=zip", "--prefix=product/", "-o",
             str((folder / name).resolve()), revision)
    except RuntimeError as exc:
        raise LookupError(f"the pinned product revision {revision} is not in the product repository: {exc}") from exc
    return name


def _image(artifact: dict, road: str, folder: Path, docker: str | None, run: Runner) -> dict:
    ref = artifact.get("ref")
    entry = {"road": road, "type": artifact.get("type"), "ref": ref, "id": artifact.get("id"), "exported": None}
    if artifact.get("digest"):
        entry["digest"] = artifact["digest"]
    if artifact.get("type") != "image":
        return entry | {"note": "no image: this road runs the product as a process from the source"}
    if docker is None:
        return entry | {"note": "not exported: docker is not installed on this host"}
    if run([docker, "image", "inspect", "--format", "{{.Id}}", str(ref)], 120)[0] != 0:
        return entry | {"note": "not exported: the image is not present on this host"}
    name = "images/" + "".join(c if c.isalnum() or c in "-_." else "_" for c in str(ref)) + ".tar"
    (folder / "images").mkdir(parents=True, exist_ok=True)
    code = run([docker, "save", "--output", str((folder / name).resolve()), str(ref)], 1800)[0]
    if code != 0 or not (folder / name).exists():
        (folder / name).unlink(missing_ok=True)
        return entry | {"note": f"not exported: docker save failed (exit {code})"}
    return entry | {"exported": name, "note": "exported with docker save"}


def _images(project: Any, release: int, folder: Path, which: Callable, run: Runner) -> list:
    rel = project.read(f"releases/{release}.json") or {}
    docker = which("docker")
    entries = [_image(a if isinstance(a, dict) else {"ref": a}, road, folder, docker, run)
               for road, a in sorted((rel.get("artifacts") or {}).items())]
    _write(folder / "image.json", _json({"release": release, "artifacts": entries}))
    return entries


def _site(project: Any, pack: dict, folder: Path) -> dict:
    """deploy-package.json, and compose.yaml when the package can run at a site; otherwise why not."""
    from kernel.roads import render_compose

    pkg, source = deploy_package(project, pack)
    if pkg is None:
        return {"deploy_package": None, "compose": None, "note": source}
    _write(folder / "deploy-package.json", _json(pkg))
    rendered = render_compose(pkg)
    if rendered["problems"]:
        return {"deploy_package": "deploy-package.json", "compose": None,
                "note": "no compose.yaml: " + "; ".join(rendered["problems"])}
    _write(folder / "compose.yaml", rendered["yaml"])
    return {"deploy_package": "deploy-package.json", "compose": "compose.yaml",
            "note": "compose.yaml runs the image by digest, with the pack and its status mounted beside it"}


def _evidence(project: Any, folder: Path, person: str, persona: str) -> str:
    """An evidence pack inside the bundle, exported (and recorded) as any other."""
    from kernel.evidence_pack import export

    made = export(project, folder / ".evidence", person=person, persona=persona)
    made.replace(folder / "evidence.zip")
    shutil.rmtree(folder / ".evidence", ignore_errors=True)
    return made.name


def _verifier(folder: Path) -> str | None:
    found = Path(__file__).resolve().parent.parent / "tools" / "rihmasto_verify.py"
    if not found.is_file():
        return None
    shutil.copyfile(found, folder / "rihmasto_verify.py")
    return "rihmasto_verify.py"


def sums(folder: Path) -> str:
    """`SHA256SUMS` for every file in the folder but the signature's and the status's own."""
    names = sorted(p.relative_to(folder).as_posix() for p in Path(folder).rglob("*") if p.is_file())
    return "".join(f"{_sha256(Path(folder) / n)}  {n}\n" for n in names if n not in UNSUMMED)


def _sign(folder: Path, name: str, which: Callable, run: Runner) -> dict:
    """Sign one file of ``folder`` with cosign into `<name>.sigstore.json`, offline; or say why not."""
    cosign, key = which("cosign"), os.environ.get(KEY_ENV, "").strip()
    if cosign is None:
        return {"signed": False, "note": "not signed: cosign not installed"}
    if not key:
        return {"signed": False, "note": f"not signed: cosign is installed but {KEY_ENV} names no key"}
    out = folder / f"{name}.sigstore.json"
    code, _, err = run([cosign, "sign-blob", "--yes", "--key", key, "--bundle", str(out.resolve()),
                        "--use-signing-config=false", "--tlog-upload=false", str((folder / name).resolve())], 300)
    if code != 0 or not out.exists() or not out.read_bytes().strip():
        out.unlink(missing_ok=True)
        return {"signed": False, "note": f"not signed: cosign failed (exit {code})", "stderr": str(err or "")[-500:]}
    return {"signed": True, "by": "cosign", "key": key, "file": out.name, "signs": name, "format": "Sigstore bundle",
            "transparency_log": "not uploaded: an offline bundle (--tlog-upload=false)"}


def _material(folder: Path, which: Callable, run: Runner) -> dict:
    """cosign.pub and trusted_root.json beside the signature, so verify-blob needs no network."""
    cosign, key, out = which("cosign"), os.environ.get(KEY_ENV, "").strip(), {}
    for name, argv in (("cosign.pub", ["public-key", "--key", key, "--outfile"]),
                       ("trusted_root.json", ["trusted-root", "create", "--out"])):
        code = run([cosign, *argv, str((folder / name).resolve())], 120)[0]
        if code == 0 and (folder / name).is_file():
            out[name] = name
        else:
            (folder / name).unlink(missing_ok=True)
            out[name] = f"not included: cosign failed (exit {code})"
    return out


def _readme(project: Any, pack: dict, contents: dict) -> str:
    from kernel.evidence_pack import governance_lines

    images = contents["images"]
    exported = [i["exported"] for i in images if i["exported"]]
    site = contents["site"]
    lines = [f"# Offline bundle: {project.meta.get('title')}", "",
             f"Release {pack['release']}, capability pack {pack['version']} "
             f"({'valid' if (pack.get('acceptance') or {}).get('valid') else 'not valid'}), product revision "
             f"{contents['revision']}.", "", "## Files", "",
             "- `capability-pack.json`, `capability-pack.yaml`: the pack (the JSON is the record).",
             f"- `contract.json`: from {contents['contract_from']}.",
             f"- `{contents['source']}`: the product's source at the pinned revision.",
             "- `image.json`: each artifact's reference" + (f"; exported: {', '.join(exported)}." if exported
                                                           else "; no image is exported in this bundle."),
             f"- `deploy-package.json`, `compose.yaml`: {site['note']}.",
             "- `evidence.zip`: the evidence pack; `rihmasto_verify.py`: the offline verifier, when included.",
             "- `SHA256SUMS`: every file above; check it with `sha256sum -c SHA256SUMS`, or run "
             "`python rihmasto_verify.py . --key <the key the factory published>` (better: your own copy of the "
             "verifier).",
             "- `signature.json`: whether SHA256SUMS is signed, and how. `cosign.pub` is for reference only: "
             "verify against the key the factory published, never the one in this folder.",
             "- `pack-status.json`: the pack's status, which expires: replace it with a fresh copy in this folder.",
             "", "## Run it", "",
             "With `compose.yaml`, in this folder: set each secret's environment variable it names, then "
             "`docker compose up -d` (or `podman compose up -d`). The folder is mounted read-only at /pack, so a "
             "fresh `pack-status.json` reaches pack_guard however it is written. `/health` answers 503 until "
             "pack_guard has checked the pack.", "",
             "## Governance", "", *governance_lines(contents["governance"]), "", "## Not in this bundle", ""]
    lines += [f"- {i['ref']}: {i['note']}" for i in images if not i["exported"]] or ["- every artifact is here"]
    lines += ["- Holdout scenarios: they stay in their own custody. The pack holds their scores only."]
    return "\n".join(lines) + "\n"


def _describe(project: Any, pack: dict, folder: Path, contents: dict, signed: bool) -> None:
    """BUNDLE.json, README.md and SHA256SUMS, with the governance map as signed or not."""
    from kernel.evidence_pack import governance_map

    rel = project.read(f"releases/{pack['release']}.json") or {}
    runtime = pack["pinned"].get("runtime_files") or []
    guarded = bool(contents["site"]["compose"]) and "factory/pack_guard.py" in runtime \
        and not pack["pinned"].get("trees_note")
    contents["governance"] = governance_map("compose" if contents["site"]["compose"] else "offline-bundle",
                                            rel.get("artifacts") or {}, signed=signed, guarded=guarded)
    _write(folder / "BUNDLE.json", _json({"format": "rihma.offline-bundle.v1", "project": project.pid,
                                          "release": pack["release"], "pack_version": pack["version"],
                                          "pack_content_sha256": pack["content_sha256"], **contents,
                                          "signature": "signature.json (outside SHA256SUMS, which it signs)"}))
    _write(folder / "README.md", _readme(project, pack, contents))
    _write(folder / "SHA256SUMS", sums(folder))


def _fill(project: Any, pack: dict, folder: Path, who: tuple, which: Callable, run: Runner) -> dict:
    from kernel.packs import render_yaml

    revision = pack["pinned"]["product_revision"]
    if not revision:
        raise LookupError("the pack pins no product revision")
    _write(folder / "capability-pack.json", _json(pack))
    _write(folder / "capability-pack.yaml", render_yaml(pack))
    contents = {"revision": revision, "contract_from": _contract(project, revision, folder),
                "source": _source(project, revision, folder),
                "images": _images(project, pack["release"], folder, which, run),
                "site": _site(project, pack, folder), "evidence": {"file": "evidence.zip"},
                "verifier": _verifier(folder), "status": {"file": STATUS}}
    contents["evidence"]["exported_as"] = _evidence(project, folder, *who)
    planned = which("cosign") is not None and bool(os.environ.get(KEY_ENV, "").strip())
    _describe(project, pack, folder, contents, signed=planned)
    signature = _sign(folder, "SHA256SUMS", which, run)
    if signature["signed"]:
        signature |= {"verification": _material(folder, which, run), "verify_with": VERIFY_WITH}
    elif planned:  # cosign was there but did not sign: the description must not say it is signed
        _describe(project, pack, folder, contents, signed=False)
    _write(folder / STATUS, _json(status_document(project, pack)))
    signature["status"] = _sign(folder, STATUS, which, run)
    _write(folder / "signature.json", _json(signature))
    contents["signature"] = signature
    return contents


def export_bundle(project: Any, out_dir: str | Path, *, person: str, persona: str, release: int | None = None,
                  as_zip: bool = False, which: Callable = shutil.which, run: Runner = _run) -> Path:
    """Export a release (the latest by default) as an offline bundle folder, or a zip of it.
    ``which`` and ``run`` find and run docker and cosign; tests replace them."""
    from kernel.evidence_pack import EXPORTERS
    from kernel.packs import build_pack
    from kernel.roads import rmtree

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in EXPORTERS:
        raise DecisionRefused(f"a {persona} may not export a bundle; {', '.join(EXPORTERS)} may")
    pack = build_pack(project, release)
    name = f"{project.pid}-{pack['version']}-offline"
    out_dir = Path(out_dir)
    final = out_dir / (name + ".zip" if as_zip else name)
    if final.exists():
        raise FileExistsError(f"{final} exists already")
    work = out_dir / f".{name}.partial"
    rmtree(work)
    try:
        contents = _fill(project, pack, work, (person, persona), which, run)
        if as_zip:
            with zipfile.ZipFile(final, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for p in sorted(work.rglob("*")):
                    if p.is_file():
                        z.write(p, p.relative_to(work).as_posix())
        else:
            work.rename(final)
    finally:
        rmtree(work)
    project.log("bundle_exported", {"bundle": final.name, "release": pack["release"], "version": pack["version"],
                                    "by": person, "persona": persona, "signed": contents["signature"]["signed"],
                                    "images_exported": sum(1 for i in contents["images"] if i["exported"]),
                                    "sha256sums": hashlib.sha256(sums_text(final, as_zip)).hexdigest()})
    return final


def sums_text(bundle: Path, is_zip: bool) -> bytes:
    """The bytes of a bundle's SHA256SUMS, from its folder or its zip."""
    if is_zip:
        with zipfile.ZipFile(bundle) as z:
            return z.read("SHA256SUMS")
    return (Path(bundle) / "SHA256SUMS").read_bytes()
