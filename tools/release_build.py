"""Build a Rihmasto release from a checkout (FR-REL1): the source archives, a CycloneDX SBOM, the
checksums and the release notes, in one folder, the same commit giving the same bytes.

    python tools/release_build.py --tag v1.0.0 --out dist        # a release: the tag must match
    python tools/release_build.py --dry-run --out dist           # a rehearsal from the version as it is

The release workflow (.github/workflows/release.yml) runs it when a person pushes a version tag, then
publishes what it built. Standard-library Python only: nothing is installed. Rihmasto runs from a
checkout (pyproject.toml), so the source archive is the release; there is no wheel and no image."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "rihmasto"
REPO = "eljaplacido/rihmastoai"
# PEP 440 as this project uses it: 1.2.3, then an optional a/b/rc or .devN part.
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?$")


class ReleaseRefused(Exception):
    """The release would be wrong, so nothing is built."""


def project_version(root: Path = ROOT) -> str:
    """The version pyproject.toml declares."""
    with (root / "pyproject.toml").open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def version_for(tag: str | None, root: Path = ROOT, *, dry_run: bool = False) -> str:
    """The version to release: the tag without its ``v``, which must be the declared version, unless
    this is a rehearsal, which takes the declared version as it is."""
    declared = project_version(root)
    if dry_run:
        return declared
    if not tag or not tag.startswith("v"):
        raise ReleaseRefused(f"a release needs a tag such as v{declared}, got {tag!r}")
    version = tag[1:]
    if not VERSION.match(version):
        raise ReleaseRefused(f"the tag {tag} is not a version (expected v1.2.3, v1.2.3rc1 and the like)")
    if version != declared:
        raise ReleaseRefused(f"the tag {tag} does not match pyproject.toml's version {declared}: "
                             "set the version first, then tag the commit that has it")
    return version


def prerelease(version: str) -> bool:
    """An alpha, beta, release candidate or development version is published as a pre-release."""
    return bool(re.search(r"(a|b|rc)\d+|\.dev\d+$", version))


def notes(version: str, root: Path = ROOT, *, dry_run: bool = False) -> str:
    """The CHANGELOG section for the version, word for word. A release needs one; a rehearsal falls back
    to [Unreleased]."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)
    wanted = [f"[{version}]"] + (["[Unreleased]"] if dry_run else [])
    for head in wanted:
        for part in sections[1:]:
            if part.startswith(head):
                body = part.split("\n", 1)[1] if "\n" in part else ""
                return body.strip() + "\n"
    raise ReleaseRefused(f"CHANGELOG.md has no section ## [{version}]: move the changes under "
                         "[Unreleased] into it before tagging")


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def archives(version: str, out: Path, root: Path = ROOT) -> list[Path]:
    """The tracked files at HEAD, as .tar.gz and .zip, under one folder named for the version."""
    prefix = f"{NAME}-{version}/"
    made = []
    for fmt, ext in (("tar.gz", "tar.gz"), ("zip", "zip")):
        path = out / f"{NAME}-{version}.{ext}"
        path.write_bytes(git(root, "archive", f"--format={fmt}", f"--prefix={prefix}", "HEAD"))
        made.append(path)
    return made


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sbom(version: str, commit: str, made: list[Path], root: Path = ROOT) -> dict:
    """A CycloneDX 1.5 SBOM. Rihmasto has no package dependencies (standard-library Python), so the only
    component is Gnomon, its one runtime dependency, which is a separate command and not bundled."""
    with (root / "pyproject.toml").open("rb") as fh:
        meta = tomllib.load(fh)["project"]
    purl = f"pkg:github/{REPO}@v{version}"
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "serialNumber": "urn:uuid:" + _uuid_from(commit + version),
        "metadata": {
            "component": {
                "type": "application", "bom-ref": purl, "name": NAME, "version": version, "purl": purl,
                "description": meta.get("description", ""),
                "licenses": [{"license": {"id": meta.get("license", "Apache-2.0")}}],
                "hashes": [{"alg": "SHA-256", "content": sha256(p)} for p in made],
                "externalReferences": [{"type": "vcs", "url": f"https://github.com/{REPO}"}],
                "properties": [{"name": "rihmasto:commit", "value": commit},
                               {"name": "rihmasto:requires-python", "value": meta.get("requires-python", "")},
                               {"name": "rihmasto:python-dependencies", "value": "none (standard library only)"}],
            },
        },
        "components": [{
            "type": "application", "bom-ref": "gnomon", "name": "gnomon", "scope": "required",
            "description": "The Gnomon harness: Rihmasto's one runtime dependency, a separate command "
                           "installed on its own; not part of this archive.",
        }],
        "dependencies": [{"ref": purl, "dependsOn": ["gnomon"]}],
    }


def _uuid_from(seed: str) -> str:
    """A stable UUID from the commit and version, so the same release gives the same SBOM bytes."""
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{h[:8]}-{h[8:12]}-5{h[13:16]}-{'89ab'[int(h[16], 16) % 4]}{h[17:20]}-{h[20:32]}"


def build(out: Path, *, tag: str | None = None, dry_run: bool = False, root: Path = ROOT) -> dict:
    """Build everything a release publishes into ``out`` and say what was built."""
    version = version_for(tag, root, dry_run=dry_run)
    body = notes(version, root, dry_run=dry_run)
    out.mkdir(parents=True, exist_ok=True)
    commit = git(root, "rev-parse", "HEAD").decode().strip()
    made = archives(version, out, root)
    bom = out / f"{NAME}-{version}.cdx.json"
    bom.write_text(json.dumps(sbom(version, commit, made, root), indent=2) + "\n", encoding="utf-8", newline="\n")
    files = [*made, bom]
    sums = out / "SHA256SUMS"
    sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files), encoding="utf-8", newline="\n")
    (out / "RELEASE_NOTES.md").write_text(body, encoding="utf-8", newline="\n")
    return {"version": version, "commit": commit, "prerelease": prerelease(version), "dry_run": dry_run,
            "files": [p.name for p in [*files, sums]], "notes": "RELEASE_NOTES.md"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tag", help="the version tag being released, such as v1.0.0")
    ap.add_argument("--dry-run", action="store_true", help="a rehearsal: the declared version, nothing to match")
    ap.add_argument("--out", default="dist", help="the folder to build into (default: dist)")
    args = ap.parse_args(argv)
    try:
        got = build(Path(args.out), tag=args.tag, dry_run=args.dry_run)
    except ReleaseRefused as exc:
        print(f"release refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(got, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
