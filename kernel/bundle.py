"""Offline bundles: one release in one folder or zip, to install or audit with no network (FR-Q6-AC-4).

A bundle holds:
- `capability-pack.json` and `capability-pack.yaml`: the release's capability pack;
- `contract.json`: the contract as the product carried it at the pinned revision;
- `source/product-<rev12>.zip`: the product's source at the pinned revision (`git archive`);
- `image.json`: each artifact's reference; `images/<name>.tar` only when docker is on PATH and the
  image is present on this host (`docker save`), otherwise the reason it is not there;
- `BUNDLE.json` and `README.md`: what is in the bundle and what is not;
- `SHA256SUMS`: the sha256 of every file above, in the format `sha256sum -c` reads;
- `signature.json`, and `SHA256SUMS.sig` only when cosign is on PATH and `RIHMA_COSIGN_KEY` names a
  key (a reference: the key itself is never read or stored). cosign signs SHA256SUMS offline
  (`--tlog-upload=false`). Without cosign the bundle says "not signed: cosign not installed". A
  signature is never made up. These two files describe the signature of SHA256SUMS, so they are
  not listed in it.

The export is recorded in the project's ledger with the person who asked for it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import is_person

KEY_ENV = "RIHMA_COSIGN_KEY"
UNSUMMED = ("SHA256SUMS", "SHA256SUMS.sig", "signature.json")
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


def sums(folder: Path) -> str:
    """`SHA256SUMS` for every file in the folder but the signature's own files."""
    names = sorted(p.relative_to(folder).as_posix() for p in Path(folder).rglob("*") if p.is_file())
    return "".join(f"{_sha256(Path(folder) / n)}  {n}\n" for n in names if n not in UNSUMMED)


def _sign(folder: Path, which: Callable, run: Runner) -> dict:
    cosign, key = which("cosign"), os.environ.get(KEY_ENV, "").strip()
    if cosign is None:
        return {"signed": False, "note": "not signed: cosign not installed"}
    if not key:
        return {"signed": False, "note": f"not signed: cosign is installed but {KEY_ENV} names no key"}
    sig = folder / "SHA256SUMS.sig"
    code, _, err = run([cosign, "sign-blob", "--yes", "--key", key, "--tlog-upload=false", "--output-signature",
                        str(sig.resolve()), str((folder / "SHA256SUMS").resolve())], 300)
    if code != 0 or not sig.exists() or not sig.read_bytes().strip():
        sig.unlink(missing_ok=True)
        return {"signed": False, "note": f"not signed: cosign failed (exit {code})", "stderr": str(err or "")[-500:]}
    return {"signed": True, "by": "cosign", "key": key, "file": "SHA256SUMS.sig", "signs": "SHA256SUMS",
            "transparency_log": "not uploaded: an offline bundle (--tlog-upload=false)"}


def _readme(project: Any, pack: dict, contents: dict) -> str:
    images = contents["images"]
    exported = [i["exported"] for i in images if i["exported"]]
    lines = [f"# Offline bundle: {project.meta.get('title')}", "",
             f"Release {pack['release']}, capability pack {pack['version']} "
             f"({'valid' if (pack.get('acceptance') or {}).get('valid') else 'not valid'}), product revision "
             f"{contents['revision']}.", "", "## Files", "",
             "- `capability-pack.json`, `capability-pack.yaml`: the pack (the JSON is the record).",
             f"- `contract.json`: from {contents['contract_from']}.",
             f"- `{contents['source']}`: the product's source at the pinned revision.",
             "- `image.json`: each artifact's reference" + (f"; exported: {', '.join(exported)}." if exported
                                                           else "; no image is exported in this bundle."),
             "- `SHA256SUMS`: every file above; check it with `sha256sum -c SHA256SUMS`.",
             "- `signature.json`: whether SHA256SUMS is signed, and how.", "", "## Not in this bundle", ""]
    lines += [f"- {i['ref']}: {i['note']}" for i in images if not i["exported"]] or ["- every artifact is here"]
    lines += ["- Holdout scenarios: they stay in their own custody. The pack holds their scores only."]
    return "\n".join(lines) + "\n"


def _fill(project: Any, pack: dict, folder: Path, which: Callable, run: Runner) -> dict:
    from kernel.packs import render_yaml

    revision = pack["pinned"]["product_revision"]
    if not revision:
        raise LookupError("the pack pins no product revision")
    _write(folder / "capability-pack.json", _json(pack))
    _write(folder / "capability-pack.yaml", render_yaml(pack))
    contents = {"revision": revision, "contract_from": _contract(project, revision, folder),
                "source": _source(project, revision, folder),
                "images": _images(project, pack["release"], folder, which, run)}
    _write(folder / "BUNDLE.json", _json({"format": "rihma.offline-bundle.v1", "project": project.pid,
                                          "release": pack["release"], "pack_version": pack["version"],
                                          "pack_content_sha256": pack["content_sha256"], **contents,
                                          "signature": "signature.json (outside SHA256SUMS, which it signs)"}))
    _write(folder / "README.md", _readme(project, pack, contents))
    _write(folder / "SHA256SUMS", sums(folder))
    contents["signature"] = _sign(folder, which, run)
    _write(folder / "signature.json", _json(contents["signature"]))
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
        contents = _fill(project, pack, work, which, run)
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
