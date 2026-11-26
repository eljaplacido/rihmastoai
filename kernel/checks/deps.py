"""A dependency audit (FR-CHK1): known vulnerabilities in the project's dependencies, by the tools that know.

Each ecosystem the workspace holds is audited by its own tool when it is installed: ``pip-audit`` for Python
requirements (``requirements*.txt``, else the project in ``pyproject.toml``), ``npm audit`` for a
``package-lock.json``, ``cargo audit`` for a ``Cargo.lock``; ``osv-scanner`` audits any lockfile when it is
installed and the ecosystem's own tool is not. Rihmasto installs nothing. An ecosystem with no tool here is
not measured, and says which tool would measure it; so is a run whose output cannot be read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel.checks import Check, Ctx, not_measured, result
from kernel.checks.tools import first_found, json_of, run_tool
from kernel.verdicts import combine_verdicts


def _count_pip(doc: Any) -> int | None:
    deps = doc.get("dependencies") if isinstance(doc, dict) else doc
    if not isinstance(deps, list):
        return None
    return sum(len(d.get("vulns") or []) for d in deps if isinstance(d, dict))


def _count_npm(doc: Any) -> int | None:
    meta = ((doc or {}).get("metadata") or {}).get("vulnerabilities") if isinstance(doc, dict) else None
    if isinstance(meta, dict):
        return sum(int(v) for k, v in meta.items() if k != "total" and isinstance(v, int))
    return None


def _count_cargo(doc: Any) -> int | None:
    vulns = (doc or {}).get("vulnerabilities") if isinstance(doc, dict) else None
    return int(vulns.get("count", 0)) if isinstance(vulns, dict) else None


def _count_osv(doc: Any) -> int | None:
    results = (doc or {}).get("results") if isinstance(doc, dict) else None
    if not isinstance(results, list):
        return None
    return sum(len(p.get("vulnerabilities") or []) for r in results if isinstance(r, dict)
               for p in r.get("packages") or [] if isinstance(p, dict))


def _python_args(root: Path) -> list[str] | None:
    reqs = sorted(p.name for p in root.glob("requirements*.txt"))
    if reqs:
        return [w for r in reqs for w in ("-r", r)]
    return ["."] if (root / "pyproject.toml").is_file() else None


def _ecosystems(root: Path) -> list[tuple[str, list[str], str, Any]]:
    """(ecosystem, its tool's argv, the tool's name, how to count its findings) for what the workspace holds."""
    found = []
    py = _python_args(root)
    if py is not None:
        found.append(("python", ["pip-audit", "--format", "json", "--progress-spinner", "off", *py], "pip-audit",
                      _count_pip))
    if (root / "package-lock.json").is_file():
        found.append(("node", ["npm", "audit", "--json"], "npm", _count_npm))
    if (root / "Cargo.lock").is_file():
        found.append(("rust", ["cargo", "audit", "--json"], "cargo-audit", _count_cargo))
    return found


def _audit(ctx: Ctx, eco: str, argv: list[str], tool: str, count: Any) -> dict[str, Any]:
    if tool == "cargo-audit" and not ctx.which("cargo-audit"):
        tool = ""
    if not tool or not ctx.which(argv[0]):
        if ctx.which("osv-scanner"):
            argv, tool, count = ["osv-scanner", "--format", "json", "-r", "."], "osv-scanner", _count_osv
        else:
            return not_measured(f"{eco}: {argv[0] if eco != 'rust' else 'cargo-audit'} (or osv-scanner) is not "
                                "installed; Rihmasto installs nothing")
    ran = run_tool(ctx, argv)
    if ran.code is None:
        return not_measured(f"{eco}: {ran.why}")
    n = count(json_of(ran.out))
    if n is None:
        return not_measured(f"{eco}: {tool} exited {ran.code} with output that could not be read", ran.tail(3))
    line = f"{eco}: {tool} found {n} known vulnerabilit{'y' if n == 1 else 'ies'}"
    return result("failed" if n else "passed", line, [line])


def dependencies(ctx: Ctx) -> dict[str, Any]:
    root, _ = ctx.workspace()
    ecos = _ecosystems(Path(root))
    if not ecos and first_found(ctx, "osv-scanner") and any(Path(root).glob("*.lock")):
        ecos = [("lockfiles", ["osv-scanner", "--format", "json", "-r", "."], "osv-scanner", _count_osv)]
    if not ecos:
        return not_measured("no dependency manifest or lockfile was found (requirements*.txt, pyproject.toml, "
                            "package-lock.json, Cargo.lock)")
    parts = [_audit(ctx, *eco) for eco in ecos]
    verdict = combine_verdicts([p["verdict"] for p in parts])
    summary = "; ".join(p["summary"].removeprefix("not measured: ") for p in parts)
    evidence = [e for p in parts for e in (p["evidence"] or [p["summary"]])]
    if verdict == "not measured":
        return not_measured(summary, evidence)
    return result(verdict, summary, evidence)


CHECKS = (Check("dependencies", "Dependency audit", "known vulnerabilities in the dependencies: pip-audit, npm audit, "
                "cargo audit or osv-scanner, when installed", dependencies, options=("timeout",), every="1d"),)
