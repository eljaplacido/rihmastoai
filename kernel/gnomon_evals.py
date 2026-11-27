"""Gnomon's capability-based audits, benchmarks and evals, run against a project's repository (FR-EVL1).

The owner (2026-11-24): "besides automations I want Rihmasto to be able to run Gnomon capability-based audits,
benchmarks and evals." Rihmasto is the middle layer over a team's existing projects, so it does not write audits
of its own here: it runs what Gnomon already has, headless, in the project's workspace (the working copy of its
repository, kernel/console.py), reads Gnomon's own JSON (or its text, where it has no JSON), and records the result.

The catalogue (``CATALOGUE``) is what Gnomon offers today. Each entry says what it measures, what it needs, how
long it takes, whether it calls a model (and which roles: a confidential project only with local or private
endpoints), and how its result is read (kernel/gnomon_evals_read.py). Two kinds:

- **cli**: a command of the installed ``gnomon`` (0.6.5 or later has them all): ``security``, ``security test``,
  ``compliance``, ``compliance dataflow``, ``audit metrics``, ``audit verify``, ``check``, ``eval``, ``chaos`` and
  ``doctor``. Whether this machine's Gnomon has one is read from its own help listing (``detect``), never assumed.
- **source**: a benchmark script of a Gnomon source checkout (``$GNOMON_SOURCE``, else
  ``~/src/gnomonharness-master``): the claim check, the context cost and the degradation contract.

Gnomon's audit-existing and greenfield benchmarks run only on their own planted corpus against a fixed local
endpoint, so they are not offered for a project (docs/guides/audits-and-evals.md says so).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SOURCE_ENV = "GNOMON_SOURCE"
DIMENSIONS = ("qa", "governance", "drift")
DURATIONS = {"seconds": 300, "minutes": 1800, "minutes to hours": 6 * 3600}
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_SECONDS = 60.0


@dataclass(frozen=True)
class Eval:
    """One audit, benchmark or eval Gnomon can run headless."""

    id: str
    label: str
    measures: str
    kind: str                              # cli | source
    marker: str                            # cli: words its help listing has; source: the script's path
    command: Callable[[str, dict[str, Any]], list[str]]
    inputs: tuple[str, ...]
    duration: str                          # seconds | minutes | minutes to hours
    models: str                            # none | listing | roles
    dimension: str                         # the Insights dimension its tile is in: qa, governance, drift
    reads: str                             # how its result is read
    score: str                             # its main figure
    score_label: str
    unit: str = ""
    higher_is_better: bool = True
    roles: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    runs_code: bool = False                # runs the project's own check or tests
    scope: str = "repository"              # repository | harness (it measures Gnomon on this machine)
    every: str | None = "7d"
    out_file: bool = False                 # writes its JSON to a file (--json <file>) instead of stdout
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def check_kind(self) -> str:
        return "gnomon_" + self.id

    @property
    def timeout(self) -> int:
        return DURATIONS[self.duration]


def _dir(cmd: list[str]) -> Callable[[str, dict[str, Any]], list[str]]:
    return lambda ws, cfg: [*cmd, "--dir", ws]


def _framework(ws: str, cfg: dict[str, Any]) -> list[str]:
    fw = cfg.get("framework")
    return ["compliance", "--json", *(["--framework", str(fw)] if fw else []), "--dir", ws]


def _check(ws: str, cfg: dict[str, Any]) -> list[str]:
    return ["check", "--base", str(cfg.get("base") or "HEAD~1"), *(["--role", str(cfg["role"])] if cfg.get("role")
                                                                    else []), "--json", "--dir", ws]


def _eval(ws: str, cfg: dict[str, Any]) -> list[str]:
    out = ["eval", "--spec", str(cfg.get("spec") or "default"), "--yes", "--json", "--dir", ws]
    if cfg.get("against"):
        out[1:1] = ["--against", str(cfg["against"])]
    return out + (["--yes-spend"] if cfg.get("spend") is True else [])


def _claims(ws: str, cfg: dict[str, Any]) -> list[str]:
    out = ["{python}", "{source}/benchmarks/claim-check/check_claims.py", str(Path(ws) / str(cfg.get("report") or "")),
           "--repo", ws, "--json", "{out}"]
    return out + (["--test-cmd", *str(cfg["test_cmd"]).split()] if cfg.get("test_cmd") else [])


CATALOGUE: tuple[Eval, ...] = (
    Eval("security", "Security posture", "what the repository's Gnomon surface grants and contains: trust, where each "
         "role's commands run, network, allow-lists, other harnesses' guard hooks, and the audit trail's health",
         "cli", "security [--json]", _dir(["security", "--json"]), ("a .gnomon/ surface in the repository",),
         "seconds", "none", "governance", "gnomon.security/1 JSON: each finding (risk or advice) with its fix; exit 0 "
         "no risk, 2 a risk, 10 could not run", "risks", "Risks", higher_is_better=False),
    Eval("security_test", "Guard attack corpus", "a model-free attack corpus (destructive commands, exfiltration, "
         "secrets, writes outside the project, CI and policy tampering) run through Gnomon's guard on a scratch copy "
         "of the surface, mapped to the OWASP LLM Top 10", "cli", "security test", _dir(["security", "test", "--json"]),
         ("a .gnomon/ surface in the repository",), "minutes", "none", "governance",
         "gnomon.security_test/2 JSON: each case expected and got; exit 0 every case held, 2 one did not",
         "held_pct", "Cases held", unit="%"),
    Eval("compliance", "Compliance mapping", "which controls of EU AI Act, GDPR, OWASP LLM, ISO 42001, NIST AI RMF, "
         "ISO 27001, SOC 2, CRA and DORA the repository has Gnomon evidence for: a mapping, never an assessment",
         "cli", "compliance [--framework", _framework, ("a .gnomon/ surface in the repository",), "seconds", "none",
         "governance", "gnomon.compliance/1 JSON: each control evidence, partial, gap, harness or organisational; "
         "exit 0 no gap, 2 a gap or partial", "evidence_pct", "Controls with evidence", unit="%",
         options=("framework",)),
    Eval("dataflow", "Data-flow register", "every model endpoint a role can reach (primary, fallback, escalation) "
         "with host, locality and region, MCP servers and where records stay, against the residency rule",
         "cli", "compliance dataflow", _dir(["compliance", "dataflow", "--json"]),
         ("a .gnomon/ surface in the repository",), "seconds", "none", "governance",
         "gnomon.dataflow/2 JSON: each destination and who uses it; exit 0 every route admitted, 2 one refused",
         "hosted", "Hosted destinations", higher_is_better=False),
    Eval("metrics", "How the agent worked", "from the newest audit trails whose chains verify: turns, stop reasons, "
         "model calls and tokens, tool calls, approvals, verify runs and whether a check passed after the last write",
         "cli", "metrics [--last", _dir(["audit", "metrics", "--json"]), ("Gnomon's audit trails in the repository",),
         "seconds", "none", "qa", "gnomon.metrics/2 JSON: totals and each session; exit 2 when a trail failed "
         "verification", "verified_pct", "Checked after the last write", unit="%"),
    Eval("audit_verify", "Audit trail integrity", "re-hashes every audit trail record and checks each chain and its "
         "seal, so a trail altered after the fact is found", "cli", "audit [show|verify", _dir(["audit", "verify"]),
         ("Gnomon's audit trails in the repository",), "seconds", "none", "governance",
         "text: one line per trail (chain intact, BROKEN, NOT SEALED); exit 1 when a chain is broken or there is "
         "nothing to verify", "intact_pct", "Trails intact", unit="%"),
    Eval("check", "Change judged by the surface", "judges the latest change (whoever made it) by the surface's rules: "
         "paths inside the role's write scope, .gnomon/ not edited, [verify] passes on head, a new test fails first",
         "cli", "check --base", _check, ("a .gnomon/ surface", "a base revision (default HEAD~1)"), "minutes", "none",
         "qa", "gnomon.check/1 JSON: each check pass, fail, skipped or error; exit 0 held, 2 failed, 10 no verdict",
         "passed_pct", "Checks held", unit="%", options=("base", "role"), runs_code=True, every="1d"),
    Eval("eval", "Eval on the project's own tasks", "the surface's pass rate on the project's own tasks "
         "(.gnomon/trials/<spec>.toml), each in a fresh private clone judged by the task's check; with --against, "
         "whether another profile, surface or harness does better", "cli", "eval [--against", _eval,
         ("a trials spec .gnomon/trials/<spec>.toml", "the lane's model roles"), "minutes to hours", "roles", "qa",
         "gnomon.eval/3 JSON: pass rate with its interval, tokens, requests, and whether it meets the spec's "
         "thresholds; exit 0 meets, 2 does not, 10 no answer", "pass_rate", "Pass rate", unit="%",
         roles=("builder",), options=("spec", "against", "spend"), runs_code=True, every=None),
    Eval("chaos", "Fault disclosure (chaos)", "a scripted model on 127.0.0.1 injects one fault per case (errors, "
         "timeouts, truncated replies, rate limits): is each failure announced, or silent?", "cli", "chaos [--json]",
         lambda ws, cfg: ["chaos", "--json"], ("Gnomon on this machine",), "minutes", "none", "qa",
         "gnomon.chaos/1 JSON: each fault announced, silent or not fired; exit 0 every fault announced, 1 one silent, "
         "2 the run is void", "announced_pct", "Faults announced", unit="%", scope="harness", every="30d"),
    Eval("doctor", "Machine and routes doctor", "whether this machine still runs what the surface says: every role's "
         "model answers its listing, memory, GPUs and model servers since setup", "cli", "doctor [--json]",
         _dir(["doctor", "--json"]), ("a .gnomon/ surface",), "seconds", "listing", "drift",
         "gnomon.doctor/1 JSON: each finding problem or info with its fix; exit 0 nothing to do, 1 attention",
         "problems", "Problems", higher_is_better=False, every="1d"),
    Eval("claim_check", "Claim check of an agent's report", "checks the claims in a report an agent wrote: file:line "
         "citations resolve, the diff size matches git, the test count matches a test run", "source",
         "benchmarks/claim-check/check_claims.py", _claims, ("a report file in the repository", "a Gnomon source "
         "checkout"), "seconds", "none", "qa", "JSON: each claim verified, refuted or unverifiable, and the accuracy; "
         "exit 1 when a claim is refuted", "accuracy", "Claim accuracy", unit="%", options=("report", "test_cmd"),
         needs=("report",), runs_code=True, every=None, out_file=True),
    Eval("context_cost", "Context cost", "the bytes on the wire for one prompt, measured against a local canary "
         "endpoint: how much context Gnomon sends per request", "source", "benchmarks/context-cost/measure.mjs",
         lambda ws, cfg: ["{node}", "{source}/benchmarks/context-cost/measure.mjs", "--json", "{out}"],
         ("a Gnomon source checkout", "node"), "minutes", "none", "drift", "JSON: requests and total bytes per run; "
         "exit 1 when a run is void", "total_bytes", "Bytes per prompt", unit="bytes", higher_is_better=False,
         options=("max_bytes",), scope="harness", every="30d", out_file=True),
    Eval("degradation", "Degradation contract", "whether every degradation Gnomon can fall into is both announced "
         "and recorded", "source", "benchmarks/degradation-contract/contract.mjs",
         lambda ws, cfg: ["{node}", "{source}/benchmarks/degradation-contract/contract.mjs", "--json", "{out}"],
         ("a Gnomon source checkout", "node"), "seconds", "none", "qa", "JSON: each degradation announced, recorded "
         "and complete; exit 1 a failure found, 2 void", "complete_pct", "Degradations complete", unit="%",
         scope="harness", every="30d", out_file=True),
)
BY_ID = {e.id: e for e in CATALOGUE}


def find(eid: str) -> Eval:
    key = str(eid or "").removeprefix("gnomon_")
    if key not in BY_ID:
        raise ValueError(f"a Gnomon eval is one of {', '.join(BY_ID)}, got {eid!r}")
    return BY_ID[key]


# -- what this machine's Gnomon has ---------------------------------------------------------------------------

def gnomon() -> list[str]:
    """The command that runs Gnomon: ``$GNOMON_CMD``, else kernel.model.gnomon_cmd() (PATH, or the pinned build)."""
    from kernel.model import gnomon_cmd

    return gnomon_cmd()


def source_dir() -> Path | None:
    """A Gnomon source checkout for the benchmark scripts: ``$GNOMON_SOURCE``, else ~/src/gnomonharness-master."""
    named = os.environ.get(SOURCE_ENV)
    path = Path(named) if named else Path.home() / "src" / "gnomonharness-master"
    return path if (path / "benchmarks").is_dir() else None


def detect(*, fresh: bool = False) -> dict[str, Any]:
    """Whether Gnomon runs here, its version, and its help listing (``gnomon --help``), kept for a minute."""
    cmd = gnomon()
    key = " ".join(cmd) + "|" + os.environ.get("PATH", "")
    hit = _CACHE.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    found: dict[str, Any] = {"found": False, "version": None, "help": "", "command": cmd[-1:]}
    exe = cmd[0] if len(cmd) > 1 or Path(cmd[0]).exists() else shutil.which(cmd[0])
    if exe:
        try:
            proc = subprocess.run([exe, *cmd[1:], "--help"], capture_output=True, text=True, timeout=30,
                                  encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
            text = proc.stdout or ""
            m = re.match(r"\s*gnomon/(\S+)", text)
            found = {"found": bool(m), "version": m.group(1) if m else None, "help": text, "command": cmd[-1:]}
        except (OSError, subprocess.SubprocessError):
            pass
    _CACHE[key] = (time.monotonic(), found)
    return found


def availability(ev: Eval, seen: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Whether ``ev`` can run on this machine, and why not."""
    if ev.kind == "source":
        src = source_dir()
        if src is None:
            return False, f"no Gnomon source checkout (set {SOURCE_ENV} to one; the {ev.label} is a benchmark script)"
        if not (src / ev.marker).is_file():
            return False, f"this Gnomon checkout has no {ev.marker}"
        if ev.marker.endswith(".mjs") and not shutil.which("node"):
            return False, "node is not installed here"
        return True, ""
    seen = seen if seen is not None else detect()
    if not seen["found"]:
        return False, "Gnomon is not installed here (npm install -g gnomon-harness, or set GNOMON_CMD)"
    if ev.marker not in seen["help"]:
        command = ev.marker.split(" [")[0]
        return False, f"this Gnomon ({seen['version']}) has no `gnomon {command}`: 0.6.5 or later has it"
    return True, ""


def _demo(project: Any) -> bool:
    from kernel.itdata import demo_home

    return demo_home(getattr(project, "factory", None))


def public(project: Any = None) -> list[dict[str, Any]]:
    """The catalogue as the cockpit and the command line show it, with whether each runs here (and for a project,
    whether it applies: a project with no repository of its own has nothing to audit but the harness)."""
    seen = detect()
    out = []
    for ev in CATALOGUE:
        ok, why = availability(ev, seen)
        if ok and project is not None and ev.scope == "repository" and not has_repository(project):
            ok, why = False, f"{project.pid} has no repository of its own yet"
        if ok and project is not None and ev.models != "none" and _demo(project):
            ok, why = False, "a demo home runs on its scripted model and contacts no endpoint: not run here"
        out.append({"id": ev.id, "label": ev.label, "measures": ev.measures, "kind": ev.kind, "inputs": list(ev.inputs),
                    "duration": ev.duration, "models": ev.models, "roles": list(ev.roles), "dimension": ev.dimension,
                    "reads": ev.reads, "score": ev.score_label, "unit": ev.unit, "options": list(ev.options),
                    "needs": list(ev.needs), "runs_code": ev.runs_code, "scope": ev.scope, "every": ev.every,
                    "check": ev.check_kind, "available": ok, "why_not": why or None})
    return out


def has_repository(project: Any) -> bool:
    """Whether the project has code of its own to audit: a repository it built, attached or adopted."""
    from kernel.console import workspace

    try:
        return workspace(project)["kind"] is not None
    except (OSError, ValueError, KeyError):
        return False


def summary_line() -> dict[str, Any]:
    """For goal help's catalogue and doctor: is Gnomon here, which version, how many evals run."""
    seen = detect()
    ready = [e.id for e in CATALOGUE if availability(e, seen)[0]]
    return {"gnomon": seen["found"], "version": seen["version"], "runnable": ready, "total": len(CATALOGUE)}
