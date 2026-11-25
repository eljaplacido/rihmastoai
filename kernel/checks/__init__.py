"""Pluggable checks for maintenance and administration (FR-CHK1).

The owner (2026-11-24): "In maintenance and administration you want automations of compliance checks or
integration CI/CD checks or whatsoever, because eventually it is not just about getting something deployed,
but how you keep on monitoring it and governing it and having checks."

A **check** is one kind of question about a project, answered with a recorded result: **passed**,
**failed**, or **not measured**, always with its evidence and, when not measured, why. Not measured is never
shown as passed. The catalogue (``catalogue()``):

| Kind | What it asks | Module |
|---|---|---|
| tests | the project's own test suite (the stated test command, else the one detected by rule) | suite |
| custom | a command of your own, whose exit code decides | suite |
| ci | the latest CI/CD runs on the repository's default branch (GitHub API, else `gh run list`) | ci |
| dependencies | a dependency audit: pip-audit, npm audit, cargo audit or osv-scanner, when installed | deps |
| secrets | Rihmasto's own secret scan (kernel/redteam/secretscan.py) | scans |
| licences | dependency licences from manifests and lockfiles, copyleft flagged against a policy list | licences |
| sbom | a CycloneDX SBOM generated from the lockfiles, kept with the project | licences |
| probe | an HTTP probe of a deployed URL: status, latency, TLS expiry | probe |
| repo_gate | the gate on the latest commits of an attached repository | scans |
| security_gate | Rihmasto's own security gate over the project's scans | scans |

A person enables a check on a project, or across projects, with its settings and an optional schedule
(``every``: 15m, 6h, 1d), and runs it on demand, from an automation (the ``run_check`` action,
kernel/checks/automation_hook.py) or on its schedule (the cockpit's ticker, or ``rihmasto checks tick``).
Several of one kind take a name (``probe:prod``). Enabling, disabling and every result are in the project's
ledger (``check_enabled``, ``check_disabled``, ``check_ran``). A failing check can log a signal or open a
change proposal (``on_fail``), and an automation reacting to ``check_ran`` can notify (kernel/checks/store.py).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kernel.store import Project

VERDICTS = ("passed", "failed", "not measured")
MAX_EVIDENCE, MAX_LINE = 20, 300
ENABLERS = ("developer", "it", "operations", "compliance", "product_owner")


@dataclass
class Ctx:
    """What a check runs with: the project, its settings, who asked and how tools are found."""

    project: Project
    config: dict[str, Any]
    person: str = ""
    persona: str = ""
    timeout: int = 600
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    _workspace: tuple[Path, str] | None = None

    def which(self, name: str) -> str | None:
        return shutil.which(name, path=self.environ.get("PATH"))

    def workspace(self) -> tuple[Path, str]:
        """The project's workspace (kernel/console.py), made or moved forward once per run."""
        if self._workspace is None:
            from kernel.console import ensure_workspace

            self._workspace = ensure_workspace(self.project, self.person or None)
        return self._workspace


@dataclass(frozen=True)
class Check:
    kind: str
    label: str
    what: str
    run: Callable[[Ctx], dict[str, Any]]
    options: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    runs_code: bool = False            # runs the project's own code: a persona the console allows enables it
    every: str | None = None           # the schedule it suggests


def result(verdict: str, summary: str, evidence: list[str] | None = None, **data: Any) -> dict[str, Any]:
    """One check's answer; evidence is a few short lines, never a whole output."""
    if verdict not in VERDICTS:
        raise ValueError(f"a check's verdict is one of {', '.join(VERDICTS)}")
    lines = [str(e)[:MAX_LINE] for e in (evidence or [])][:MAX_EVIDENCE]
    return {"verdict": verdict, "summary": str(summary)[:MAX_LINE], "evidence": lines, **data}


def not_measured(why: str, evidence: list[str] | None = None, **data: Any) -> dict[str, Any]:
    text = why if why.startswith("not measured") else f"not measured: {why}"
    return result("not measured", text, evidence, **data)


def catalogue() -> dict[str, Check]:
    """Every kind of check, by kind."""
    from kernel.checks import ci, deps, licences, probe, scans, suite

    found: dict[str, Check] = {}
    for module in (suite, ci, deps, scans, licences, probe):
        for check in module.CHECKS:
            found[check.kind] = check
    return found


def last_results(project: Any) -> list[dict[str, Any]]:
    """Each enabled check's last result on the project (what Insights reads, kernel/insights/health.py): its key,
    kind, verdict (passed, failed or not measured), summary and when it ran. A check that never ran is left out."""
    from kernel.checks import store

    out = []
    for key, entry in sorted(store.enabled(project).items()):
        rows = store.results(project, key, 1)
        if rows:
            last = rows[-1]
            out.append({"check": key, "kind": entry.get("kind"), "verdict": last.get("verdict"),
                        "summary": last.get("summary"), "at": last.get("at")})
    return out


def public() -> list[dict[str, Any]]:
    """The catalogue as the cockpit and the command line show it."""
    return [{"kind": c.kind, "label": c.label, "what": c.what, "options": list(c.options), "needs": list(c.needs),
             "runs_code": c.runs_code, "every": c.every} for c in catalogue().values()]
