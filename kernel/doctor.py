"""`rihma doctor`: can this machine run the factory, and on which Gnomon (FR-N2-AC-2).

Rihma needs Gnomon 0.6.5 or later; 0.6.7 recommended, the latest (Rihmasto tracks Gnomon's latest release).
0.6.6 is the first release that reads
every `[verify]` key the factory's own surface declares (`protects`, `exit_on_fail`,
`record_detail`, `timeout_seconds`, `exit_map`); the source build `0.6.5+fb458ea5` pinned for
cells reads them too (D-0003). docs/gnomon-0.6.6-audit.md has the rest.

The report is JSON. It reads, and writes nothing but a temporary file it deletes again (the
lanes root writability probe). It never prints a key: for each endpoint that names an
`api_key_env`, it says only whether that variable is set. The endpoints are the routing the
factory runs on: `kernel/routing.json` with this machine's `kernel/routing.local.json` merged
over it when present, and the report says whether it is.

A hard failure exits 1: no Gnomon, a Gnomon older than MIN_GNOMON, or one whose version cannot
be read (a version that cannot be read cannot be shown to be supported). Everything else is a
warning and exits 0.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from kernel.version import is_prerelease, rihmasto_version

MIN_GNOMON = "0.6.5"
RECOMMENDED_GNOMON = "0.6.7"
MIN_PYTHON = (3, 11)
SCHEMA = "rihma.doctor/1"

# `gnomon --version` prints harnessBuild(): `gnomon/<version>+<build>` (packages/gnomon-core/src/
# build.ts), e.g. `gnomon/0.6.5+v0.6.5-53f83bd` (a release), `gnomon/0.6.5+fb458ea5` (a source
# build), `gnomon/0.6.6+npm`, `gnomon/0.6.6+abf40c0-dirty`.
_VERSION = re.compile(r"(?:gnomon/)?v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+(\S+))?")


def parse_version(text: str) -> dict | None:
    """{version, build, prerelease} from a `gnomon --version` line, or None."""
    m = _VERSION.search(text or "")
    if not m:
        return None
    major, minor, patch, pre, build = m.groups()
    version = f"{int(major)}.{int(minor)}.{int(patch)}" + (f"-{pre}" if pre else "")
    return {"version": version, "build": build, "prerelease": pre}


def version_key(version: str) -> tuple:
    """Orders versions as semver does for these purposes: a pre-release sorts below its release."""
    m = _VERSION.fullmatch(version.strip())
    if not m:
        raise ValueError(f"not a version: {version!r}")
    major, minor, patch, pre, _ = m.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1)


def gnomon_version(cmd=None, *, timeout: int = 30) -> dict:
    """Run `<gnomon> --version` and parse it. ``cmd`` defaults to kernel.model.gnomon_cmd()."""
    from kernel.model import gnomon_cmd

    cmd = list(cmd) if cmd else gnomon_cmd()
    out = {"found": False, "command": cmd, "raw": None, "version": None, "build": None}
    try:
        proc = subprocess.run([*cmd, "--version"], capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**out, "error": f"{type(exc).__name__}: {exc}"}
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    raw = lines[0] if lines else None
    parsed = parse_version(raw or "")
    out.update(found=True, raw=raw, exit=proc.returncode)
    if parsed:
        out.update(version=parsed["version"], build=parsed["build"])
    else:
        out["error"] = f"`--version` printed no version (exit {proc.returncode})"
    return out


def _tool(name: str, args=("--version",)) -> dict:
    path = shutil.which(name)
    if not path:
        return {"found": False}
    try:
        proc = subprocess.run([path, *args], capture_output=True, text=True, timeout=20, encoding="utf-8",
                              errors="replace")
        first = next((ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()), None)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"found": True, "path": path, "version": None, "error": f"{type(exc).__name__}: {exc}"}
    return {"found": True, "path": path, "version": first}


def _writable(root: Path) -> dict:
    """Whether the lanes root can be written: probed with a temporary file that is deleted again.
    A root that does not exist yet is judged by its nearest existing parent (it will be created)."""
    probe, exists = Path(root), Path(root).exists()
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        with tempfile.NamedTemporaryFile(dir=probe, prefix=".rihma-doctor-", delete=True):
            pass
        ok = True
    except OSError:
        ok = False
    return {"root": str(root), "exists": exists, "writable": ok,
            **({} if exists else {"created_under": str(probe)})}


def doctor(home, *, gnomon=None, routing: dict | None = None, lanes_root=None, environ=None,
           harnesses: list | None = None) -> dict:
    """The report. ``gnomon`` (a command list), ``routing``, ``lanes_root``, ``environ`` and ``harnesses`` (the
    coding agents found, kernel/harness_setup.py) replace what the machine would give, for tests."""
    from kernel.lanes import ROUTING_LOCAL_FILE, read_routing
    from kernel.lanes import lanes_root as default_lanes_root
    from kernel.store import REPO_ROOT

    env = os.environ if environ is None else environ
    problems, warnings = [], []

    py = sys.version_info
    python = {"version": platform.python_version(), "executable": sys.executable,
              "ok": (py.major, py.minor) >= MIN_PYTHON, "min": ".".join(map(str, MIN_PYTHON))}
    if not python["ok"]:
        warnings.append(f"Python {python['version']} is older than {python['min']}")

    g = gnomon_version(gnomon)
    g.update(min=MIN_GNOMON, recommended=RECOMMENDED_GNOMON, supported=False, is_recommended=False)
    if not g["found"]:
        problems.append(f"Gnomon was not found ({' '.join(g['command'])}): install it, or set GNOMON_CMD")
    elif not g["version"]:
        problems.append(f"Gnomon's version could not be read from {g['raw']!r}; Rihma needs {MIN_GNOMON} or later")
    else:
        key = version_key(g["version"])
        g["supported"] = key >= version_key(MIN_GNOMON)
        g["is_recommended"] = key >= version_key(RECOMMENDED_GNOMON)
        if not g["supported"]:
            problems.append(f"Gnomon {g['version']} is older than {MIN_GNOMON}: Rihma needs {MIN_GNOMON} or later, "
                            f"{RECOMMENDED_GNOMON} recommended")
        elif not g["is_recommended"]:
            warnings.append(f"Gnomon {g['version']} works; {RECOMMENDED_GNOMON} is recommended: "
                            "`gnomon update` upgrades it (docs/gnomon-0.6.6-audit.md, 'Upgrade steps', "
                            "has the pinned and source-build ways)")

    git = _tool("git")
    if not git["found"]:
        warnings.append("git was not found: lanes are git clones and cannot be prepared without it")
    docker = {**_tool("docker"), "optional": True}

    lanes = _writable(Path(lanes_root) if lanes_root else default_lanes_root())
    if not lanes["writable"]:
        warnings.append(f"the lanes root {lanes['root']} is not writable")

    overlay = None
    if routing is None:
        local = ROUTING_LOCAL_FILE
        overlay = {"path": local.relative_to(REPO_ROOT).as_posix() if local.is_relative_to(REPO_ROOT) else str(local),
                   "present": local.exists()}
        try:
            routing = read_routing() or {}
        except ValueError as exc:
            warnings.append(f"the routing could not be read: {exc}")
            routing = {}
    from kernel.models_setup import gnomon_keys, stored_keys  # stored in Models setup, or held by Gnomon: set

    stored = stored_keys() if environ is None else {}
    held = (gnomon_keys() or frozenset()) if environ is None else frozenset()
    endpoints = [{"name": name, "api_key_env": ep["api_key_env"],
                  "set": bool(env.get(ep["api_key_env"]) or stored.get(ep["api_key_env"]) or ep["api_key_env"] in held)}
                 for name, ep in sorted((routing.get("endpoints") or {}).items())
                 if isinstance(ep, dict) and ep.get("api_key_env")]
    for e in endpoints:
        if not e["set"]:
            warnings.append(f"{e['api_key_env']} is not set: endpoint {e['name']} cannot be reached from here")

    from kernel.harness_setup import doctor_part  # "No API key? Claude Code found: use it" (FR-HMD1)

    found = harnesses if harnesses is not None else None if environ is None else []
    home = Path(home)
    own = rihmasto_version()   # which Rihmasto this is (FR-PUB2)
    report = {
        "schema": SCHEMA, "rihmasto": {"version": own, "prerelease": is_prerelease(own)},
        "python": python, "gnomon": g, "git": git, "docker": docker, "lanes": lanes,
        "endpoints": endpoints, "home": {"path": str(home), "exists": home.exists()},
        **({"routing_overlay": overlay} if overlay else {}), **doctor_part(routing, endpoints, g["found"], found),
        "problems": problems, "warnings": warnings, "exit": 1 if problems else 0,
    }
    return report
