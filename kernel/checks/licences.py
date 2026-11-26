"""Licences and the SBOM (FR-CHK1), read from the manifests and lockfiles the workspace holds, by rule.

**Licences.** Each dependency's licence as its lockfile records it: ``package-lock.json`` (each package's
``license``), ``composer.lock`` and ``Pipfile.lock`` do not always say, so a dependency whose licence is not
recorded is counted as unknown. A licence on the policy list (``deny``; by default the copyleft families:
GPL, AGPL, LGPL, SSPL, EUPL, OSL, CC-BY-SA, MPL is not on it) fails the check; unknown licences make it not
measured, never passed; all known and none denied passes. The project's own licence (``package.json``,
``pyproject.toml``) is said beside it.

**SBOM.** A CycloneDX 1.5 JSON document of the components the lockfiles pin (``package-lock.json``,
``requirements*.txt`` lines pinned with ``==``, ``Cargo.lock``, ``go.mod``), written to the project's
``checks/sbom-<stamp>.json`` and kept with it. No lockfile is not measured.
"""

from __future__ import annotations

import json
import re
import tomllib
import uuid
from pathlib import Path
from typing import Any

from kernel.checks import Check, Ctx, not_measured, result
from kernel.store import write_json

COPYLEFT = ("GPL", "AGPL", "LGPL", "SSPL", "EUPL", "OSL", "CC-BY-SA", "CPAL", "RPL")
MAX_FILE = 16 * 1024 * 1024
_PIN = re.compile(r"^\s*([A-Za-z0-9_.\-\[\]]+)\s*==\s*([A-Za-z0-9_.+!\-]+)")
_GO = re.compile(r"^\s*([a-z0-9.\-]+\.[a-z]{2,}/[^\s]+)\s+(v[0-9][^\s]*)")


def _json(path: Path) -> Any:
    try:
        if path.is_file() and path.stat().st_size <= MAX_FILE:
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return None
    return None


def npm_packages(root: Path) -> list[dict[str, Any]]:
    """name, version and licence of each package a package-lock.json (v2 or v3) pins."""
    doc = _json(root / "package-lock.json")
    packages = doc.get("packages") if isinstance(doc, dict) else None
    if not isinstance(packages, dict):
        return []
    out = []
    for key, p in packages.items():
        if not key or not isinstance(p, dict):
            continue
        name = p.get("name") or key.split("node_modules/")[-1]
        lic = p.get("license")
        out.append({"name": str(name), "version": str(p.get("version") or ""), "ecosystem": "npm",
                    "license": lic if isinstance(lic, str) else None})
    return out


def _pinned_python(root: Path) -> list[dict[str, Any]]:
    out = []
    for req in sorted(root.glob("requirements*.txt")):
        try:
            text = req.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = _PIN.match(line)
            if m:
                out.append({"name": m.group(1).split("[")[0], "version": m.group(2), "ecosystem": "pypi",
                            "license": None})
    return out


def _cargo(root: Path) -> list[dict[str, Any]]:
    lock = root / "Cargo.lock"
    try:
        doc = tomllib.loads(lock.read_text(encoding="utf-8")) if lock.is_file() else {}
    except (OSError, tomllib.TOMLDecodeError):
        return []
    return [{"name": str(p.get("name")), "version": str(p.get("version")), "ecosystem": "cargo", "license": None}
            for p in doc.get("package") or [] if isinstance(p, dict)]


def _go(root: Path) -> list[dict[str, Any]]:
    try:
        text = (root / "go.mod").read_text(encoding="utf-8") if (root / "go.mod").is_file() else ""
    except OSError:
        return []
    return [{"name": m.group(1), "version": m.group(2), "ecosystem": "golang", "license": None}
            for m in map(_GO.match, text.splitlines()) if m]


def components(root: Path) -> list[dict[str, Any]]:
    return npm_packages(root) + _pinned_python(root) + _cargo(root) + _go(root)


def own_licence(root: Path) -> str | None:
    doc = _json(root / "package.json")
    if isinstance(doc, dict) and isinstance(doc.get("license"), str):
        return doc["license"]
    try:
        py = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    lic = (py.get("project") or {}).get("license")
    return lic if isinstance(lic, str) else (lic.get("text") if isinstance(lic, dict) else None)


def denied(licence: str, deny: list[str]) -> bool:
    words = re.split(r"[\s()]+", licence.upper())
    return any(w == d or w.startswith(d + "-") for w in words for d in (x.upper() for x in deny))


def licences(ctx: Ctx) -> dict[str, Any]:
    root, _ = ctx.workspace()
    deny = [str(d) for d in ctx.config.get("deny") or COPYLEFT]
    deps = npm_packages(Path(root))
    own = own_licence(Path(root))
    own_line = [f"the project's own licence: {own}"] if own else []
    if not deps:
        return not_measured("no lockfile records its dependencies' licences (package-lock.json does)", own_line)
    flagged = [d for d in deps if d["license"] and denied(d["license"], deny)]
    unknown = [d for d in deps if not d["license"]]
    lines = own_line + [f"denied: {d['name']}@{d['version']} {d['license']}" for d in flagged]
    lines += [f"unknown: {d['name']}@{d['version']}" for d in unknown[:10]]
    if flagged:
        return result("failed", f"{len(flagged)} of {len(deps)} dependencies carry a licence on the policy list "
                                f"({', '.join(deny[:6])})", lines, denied=len(flagged), unknown=len(unknown))
    if unknown:
        return not_measured(f"{len(unknown)} of {len(deps)} dependencies record no licence", lines,
                            unknown=len(unknown))
    return result("passed", f"{len(deps)} dependencies, none under a licence on the policy list", lines)


def _purl(c: dict[str, Any]) -> str:
    return f"pkg:{c['ecosystem']}/{c['name']}@{c['version']}"


def sbom(ctx: Ctx) -> dict[str, Any]:
    root, kind = ctx.workspace()
    found = components(Path(root))
    if not found:
        return not_measured("no lockfile pins the components (package-lock.json, requirements*.txt with ==, "
                            "Cargo.lock, go.mod)")
    project = ctx.project
    stamp = re.sub(r"[^0-9TZ]", "", project.factory.clock.stamp())
    doc = {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{uuid.uuid4()}", "version": 1,
           "metadata": {"timestamp": project.factory.clock.stamp(), "tools": [{"name": "rihmasto checks (sbom)"}],
                        "component": {"type": "application", "name": project.meta.get("title") or project.pid}},
           "components": [{"type": "library", "name": c["name"], "version": c["version"], "purl": _purl(c),
                           **({"licenses": [{"expression": c["license"]}]} if c["license"] else {})} for c in found]}
    path = project.path("checks", f"sbom-{stamp}.json")
    write_json(path, doc)
    by = sorted({c["ecosystem"] for c in found})
    return result("passed", f"an SBOM of {len(found)} components ({', '.join(by)}) from the {kind} workspace",
                  [f"kept as checks/{path.name}"], sbom=path.name, components=len(found))


CHECKS = (
    Check("licences", "Licence check", "dependency licences from the lockfiles, copyleft flagged against a policy list",
          licences, options=("deny",), every="1d"),
    Check("sbom", "SBOM", "a CycloneDX SBOM generated from the lockfiles, kept with the project", sbom, every="1d"),
)
