"""A fake Gnomon for the audits and evals tests (FR-EVL1): a `gnomon` on PATH, written by the test, that answers as
Gnomon 0.6.5's own commands do (`--version`, `--help`, `security --json`, `security test --json`, `compliance --json`,
`compliance dataflow --json`, `audit metrics --json`, `audit verify`, `check --json`, `eval --json`, `chaos --json`,
`doctor --json`), with the report shapes of its published schemas (gnomon.security/1, gnomon.security_test/2,
gnomon.compliance/1, gnomon.dataflow/2, gnomon.metrics/2, gnomon.check/1, gnomon.eval/3, gnomon.chaos/1,
gnomon.doctor/1) and its exit codes; and a fake Gnomon source checkout with the claim check, the context cost and the
degradation contract (a fake `node` runs the two .mjs ones). The real Gnomon, its benchmarks and any model never run.

A test changes what a command answers by writing ``scenario`` (command -> {"exit", "doc" | "text", "err"}); every
call is appended to ``$FAKE_GNOMON_LOG`` (its arguments and working folder).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest import mock

from console_fakes import fake_tool

HELP = """gnomon/0.6.5+fake — deterministic coding agent harness

Commands:
  doctor [--json] [--catalog FILE]
  audit [show|verify|anchor|tamper|metrics|resolve <trail>:<seq> --reason <text>] [--dir <path>]
    'metrics [--last <n>] [--session <id>] [--json]' counts how the agent worked
  task "<what to do>" [--role <name>] [--yes] [--json] [--trust] [--dir <path>]
  check --base <rev> [--head <rev>] [--role <role> | --agent <name>] [--json]
  security [--json] [--dir <path>]
  security test [--host claude-code|opencode|cursor|all] [--role <r>] [--json] [--dir <path>]
  compliance [--framework <id,...>] [--json] [--catalog <file>] [--dir <path>]
  compliance dataflow [--json] [--dir <path>]
  eval [--against profile:<name>|surface:<git ref>|command:<harness>]
  chaos [--json] [--seed <n>] [--faults <id,...>] [--schedules <s,...>] [--out <file>]
"""
SURFACE = "ab" * 32


def security(findings: list[dict[str, Any]] | None = None, exit_code: int | None = None) -> dict[str, Any]:
    found = findings if findings is not None else [
        {"id": "sandbox_network", "severity": "advice", "message": "the builder role can reach the network",
         "fix": "set network = false on the role"}]
    code = exit_code if exit_code is not None else (2 if any(f["severity"] == "risk" for f in found) else 0)
    return {"exit": code, "doc": {
        "schema": "gnomon.security/1", "project": ".", "surface_hash": SURFACE,
        "trust": {"status": "default", "grants": [], "uncovered": 0}, "approval": "on_write",
        "roles": [{"role": "builder", "exec": "host", "network": True, "read_only_source": False, "bash": True,
                   "writes": True, "bash_allowlist": True, "write_scoped": True}],
        "hosts": [], "audit": {"enabled": True, "anchored": False, "trails": 4, "verified": 4, "broken": [],
                               "tamper_unresolved": 0}, "findings": found, "exit": code}}


def risky_security() -> dict[str, Any]:
    return security([{"id": "chain_broken", "severity": "risk", "message": "an audit chain is broken",
                      "fix": "gnomon audit verify names it"},
                     {"id": "host_hook", "severity": "risk", "message": "the Claude Code guard hook is off",
                      "fix": "gnomon guard install claude-code --write"},
                     {"id": "audit_off", "severity": "risk", "message": "the audit trail is off",
                      "fix": "set [audit] enabled = true"},
                     {"id": "sandbox_network", "severity": "advice", "message": "the builder role can reach the "
                      "network", "fix": "set network = false on the role"}])


def security_test(failed: int = 0) -> dict[str, Any]:
    cases = [{"host": "claude-code", "id": f"case-{n}", "family": "destructive", "owasp": ["LLM06"],
              "story": f"rm -rf outside the project ({n})", "tool": "Bash", "expect": "deny",
              "decision": "allow" if n < failed else "deny", "rule": "bash_deny", "pass": n >= failed}
             for n in range(10)]
    return {"exit": 2 if failed else 0, "doc": {
        "schema": "gnomon.security_test/2", "project": ".", "surface_hash": SURFACE, "harness": "gnomon/0.6.5",
        "hosts": [{"host": "claude-code", "role": "builder", "role_source": "default", "passed": 10 - failed,
                   "total": 10, "errors": 0}], "cases": cases, "not_covered": [], "by_family": {},
        "by_owasp": {}, "passed": 10 - failed, "total": 10, "errors": 0, "limits": [], "exit": 2 if failed else 0}}


def compliance(gaps: int = 1) -> dict[str, Any]:
    controls = [{"framework": "eu-ai-act", "id": f"art-{n}", "title": f"Record keeping {n}", "scope": "shared",
                 "status": "gap" if n < gaps else "evidence",
                 "probes": [{"id": "audit_on", "holds": n >= gaps, "meaning": "the audit trail is on",
                             "fix": "set [audit] enabled = true"}], "facts": []} for n in range(4)]
    return {"exit": 2 if gaps else 0, "doc": {
        "schema": "gnomon.compliance/1", "project": ".", "surface_hash": SURFACE,
        "catalog": {"as_of": "2026-10-01", "stale": False}, "disclaimer": "a mapping, never an assessment",
        "frameworks": [{"id": "eu-ai-act", "name": "EU AI Act", "source": "x",
                        "counts": {"evidence": 4 - gaps, "partial": 0, "gap": gaps, "harness": 0,
                                   "organisational": 0}}], "controls": controls, "exit": 2 if gaps else 0}}


def dataflow() -> dict[str, Any]:
    return {"exit": 0, "doc": {
        "schema": "gnomon.dataflow/2", "project": ".", "surface_hash": SURFACE,
        "residency": {"allowed_regions": None, "refused": 0, "closed": 0, "outside": []},
        "destinations": [{"kind": "model", "name": "local", "host": "127.0.0.1", "locality": "local", "region": None,
                          "region_source": None, "sends": "prompts", "key_env": None,
                          "used_by": [{"role": "builder", "as": "primary", "admitted": None}]}],
        "records": {"audit": True, "record": "local", "dir": ".gnomon-audit", "leaves_machine": False},
        "telemetry": "none", "harness": [], "exit": 0}}


def metrics() -> dict[str, Any]:
    return {"exit": 0, "doc": {
        "schema": "gnomon.metrics/2", "project": ".", "audit": {"enabled": True, "dir": ".gnomon-audit"},
        "window": {"last": 50, "trails_seen": 3, "sessions": 3},
        "sessions": [{"trail": "task-1.jsonl", "chain_ok": True}],
        "totals": {"sessions": 3, "unsealed": 0, "model_calls": {"n": 9, "errors": 0, "prompt_tokens": 9000,
                                                                 "completion_tokens": 1200},
                   "process": {"writes": 6, "sessions_with_writes": 3,
                               "verified_after_last_write": {"yes": 3, "no": 1, "no_verify": 0},
                               "refusal_rate": 0.0, "apparatus_rate": 0.0}}, "exit": 0}}


def check(fail: bool = False) -> dict[str, Any]:
    checks = [{"id": "write_allow", "status": "pass"}, {"id": "surface", "status": "pass"},
              {"id": "verify", "status": "fail" if fail else "pass", "reason": "2 tests failed" if fail else None},
              {"id": "must_fail_first", "status": "skipped"}]
    return {"exit": 2 if fail else 0, "doc": {"schema": "gnomon.check/1", "base": "HEAD~1", "head": "c0ffee",
                                              "role": "builder", "surface_hash": SURFACE, "checks": checks,
                                              "exit": 2 if fail else 0}}


def eval_report(passes: int = 8, n: int = 10, meets: Any = True) -> dict[str, Any]:
    return {"exit": 0 if meets is True else 2, "doc": {
        "schema": "gnomon.eval/3", "mode": "alone", "spec": {"name": "default", "path": ".gnomon/trials/default.toml",
                                                             "sha256": "0" * 64},
        "harness": "gnomon/0.6.5", "role": "builder", "arms": {"base": {}, "candidate": None, "differ": []},
        "pairs": {"planned": n, "run": n, "valid": n}, "cells": {"total": n, "result": n, "refusal": 0,
                                                                  "apparatus_failure": 0},
        "endpoints": {"pass": {"base": {"passes": passes, "n": n, "wilson": [0.5, 0.9]}, "candidate": None}},
        "budget": {"requests_used": 40, "cost_enforced": False}, "status": "complete", "meets_thresholds": meets,
        "reasons": [] if meets is True else ["the pass rate is under min_pass_rate 0.9"]}}


def chaos(silent: int = 0) -> dict[str, Any]:
    faults = [{"id": f"fault-{n}", "family": "transport", "injects": "a timeout", "origin": "field", "cases": 2,
               "fired": 2, "announced": 0 if n < silent else 2, "named": 2, "recovered": 1,
               "silent": 2 if n < silent else 0, "verdict": "silent" if n < silent else "announced",
               "tokens_wasted": 0} for n in range(5)]
    return {"exit": 1 if silent else 0, "doc": {
        "schema": "gnomon.chaos/1", "harness": "gnomon/0.6.5", "mode": "suite", "seed": 1, "faults": faults,
        "cases": [], "apparatus": {"ok": True, "problems": []},
        "summary": {"faults": 5, "faults_announced": 5 - silent, "faults_silent": [f"fault-{n}" for n in range(silent)],
                    "cases": 10, "cases_fired": 10, "cases_announced": 10 - 2 * silent, "cases_named": 10,
                    "cases_recovered": 5, "failed": 4, "silent_failures": 2 * silent,
                    "silent_failure_share": round(2 * silent / 4, 2), "tokens_wasted": 0}, "exit": 1 if silent else 0}}


def doctor(problems: int = 0) -> dict[str, Any]:
    return {"exit": 1 if problems else 0, "doc": {
        "schema": "gnomon.doctor/1", "dir": ".", "catalog": {"as_of": "2026-10-01", "label": "x"},
        "surface": {"routes": [{"roles": ["builder"], "model": "local-model", "where": "127.0.0.1", "local": True,
                                "ready": not problems}], "setup": None},
        "findings": [{"kind": "route", "severity": "problem", "message": "the builder's model does not answer",
                      "fix": "start the model server"}] * problems, "next": [], "exit": 1 if problems else 0}}


VERIFY_OK = {"exit": 0, "text": "task-1.jsonl: 12 records — chain intact, sealed\n"
                                "task-2.jsonl: 8 records — chain intact, sealed\n"
                                "  anchor: NOT SIGNED — this surface declares no [audit.attest] signer.\n"}
DEFAULTS = {"security": security(), "security test": security_test(), "compliance": compliance(),
            "compliance dataflow": dataflow(), "audit metrics": metrics(), "audit verify": VERIFY_OK,
            "check": check(), "eval": eval_report(), "chaos": chaos(), "doctor": doctor()}

IMPL = r'''
import json, os, sys
args = sys.argv[1:]
log = os.environ.get("FAKE_GNOMON_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")
if not args or args[0] in ("--help", "-h", "help"):
    print(HELP)
    sys.exit(0)
if args[0] == "--version":
    print("gnomon/0.6.5+fake")
    sys.exit(0)
words = [a for a in args if not a.startswith("-")]
key = " ".join(words[:2]) if " ".join(words[:2]) in DEFAULTS else words[0]
scenario = dict(DEFAULTS)
path = os.environ.get("FAKE_GNOMON_SCENARIO")
if path and os.path.exists(path):
    scenario.update(json.load(open(path, encoding="utf-8")))
if key not in scenario:
    sys.stderr.write("Unknown command: " + key + "\n")
    print(HELP)
    sys.exit(1)
out = scenario[key]
print("running " + key, file=sys.stderr)
if "doc" in out:
    print(json.dumps(out["doc"], indent=2))
else:
    sys.stdout.write(out.get("text", ""))
if out.get("err"):
    sys.stderr.write(out["err"])
sys.exit(out.get("exit", 0))
'''


def install(case: Any, folder: Path) -> dict[str, Path]:
    """Write the fake `gnomon` to ``folder`` and put it first on PATH for the test (GNOMON_CMD unset); the paths
    of its scenario and its log."""
    from kernel import gnomon_evals

    fake_tool(folder, "gnomon", f"import json as _j\nHELP = {HELP!r}\nDEFAULTS = _j.loads({json.dumps(DEFAULTS)!r})\n"
              + IMPL)
    scenario, log = folder / "scenario.json", folder / "calls.jsonl"
    env = {"PATH": os.pathsep.join([str(folder), os.environ.get("PATH", "")]),
           "FAKE_GNOMON_SCENARIO": str(scenario), "FAKE_GNOMON_LOG": str(log)}
    patcher = mock.patch.dict(os.environ, env)
    patcher.start()
    case.addCleanup(patcher.stop)
    os.environ.pop("GNOMON_CMD", None)
    gnomon_evals._CACHE.clear()
    case.addCleanup(gnomon_evals._CACHE.clear)
    return {"scenario": scenario, "log": log}


def answer(paths: dict[str, Path], **commands: dict[str, Any]) -> None:
    """Change what the fake answers: security=..., security_test=... (an underscore for a space)."""
    kept = json.loads(paths["scenario"].read_text(encoding="utf-8")) if paths["scenario"].exists() else {}
    kept.update({k.replace("_", " "): v for k, v in commands.items()})
    paths["scenario"].write_text(json.dumps(kept), encoding="utf-8")


def calls(paths: dict[str, Path]) -> list[dict[str, Any]]:
    if not paths["log"].exists():
        return []
    return [json.loads(line) for line in paths["log"].read_text(encoding="utf-8").splitlines() if line.strip()]


def write_rows(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The audits' and the role evals' write routes (FR-EVL1) for the cockpit's completeness tables
    (tests/test_brief_ln.py, tests/test_access.py): each signed, each recorded. A run is a job the test's runner
    never starts; the finding made a change is one recorded here first, as a run would have."""
    from kernel import gnomon_evals as ge
    from kernel import gnomon_evals_run as gr
    from kernel.gnomon_evals_read import answer as result
    from kernel.gnomon_evals_read import finding

    b = w["built"].pid
    found = finding("security", "audit_off", "the audit trail is off", "issue", ["fix: set [audit] enabled = true"])
    if not gr.results(w["built"], "security"):
        gr.record(w["built"], ge.find("security"), result("failed", "1 risk(s)", {"risks": 1}, [found]),
                  person="Aino Example", persona="developer", via="test")
    return [
        ("post_eval_run", "POST", f"/api/projects/{b}/evals/security/run",
         lambda who, got: {"person": who, "persona": "developer"}),
        ("post_eval_finding_change", "POST", f"/api/projects/{b}/evals/findings/{found['id']}/change",
         lambda who, got: {"person": who, "persona": "developer"}),
        ("post_role_evals_run", "POST", "/api/evals/roles/run",
         lambda who, got: {"role": "assistant", "person": who, "persona": "it"}),
    ]


def cli_writes(pid: str) -> dict[str, list[str]]:
    """The signed `rihmasto evals` commands for tests/test_access.py, each with a persona Mallory is not granted."""
    who = ["--person", "Mallory Example"]
    return {"evals run": ["evals", "run", pid, "--eval", "security", *who, "--persona", "developer"],
            "evals change": ["evals", "change", pid, "F-0000000000", *who, "--persona", "developer"],
            "evals roles": ["evals", "roles", "--role", "assistant", *who, "--persona", "it"]}


# -- a Gnomon source checkout with three benchmark scripts, and a fake node ---------------------------------------

CLAIMS = r'''
import json, sys
args = sys.argv[1:]
out = args[args.index("--json") + 1]
text = open(args[0], encoding="utf-8").read()
claims = [{"kind": "citation", "raw": "app.py:3", "verdict": "verified", "detail": ""},
          {"kind": "test_count", "raw": "12 passed", "verdict": "refuted" if "12 passed" in text else "verified",
           "detail": "the test run said 10 passed"}]
refuted = sum(1 for c in claims if c["verdict"] == "refuted")
doc = {"counts": {"verified": len(claims) - refuted, "refuted": refuted, "unverifiable": 0},
       "accuracy": (len(claims) - refuted) / len(claims), "claims": claims}
open(out, "w", encoding="utf-8").write(json.dumps(doc))
print("  CLAIM ACCURACY: %.1f%% over %d checkable claim(s)" % (doc["accuracy"] * 100, len(claims)))
sys.exit(1 if refuted else 0)
'''
NODE = r'''
import json, sys
args = sys.argv[1:]
script = args[0].replace("\\", "/")
out = args[args.index("--json") + 1]
if "context-cost" in script:
    doc = {"prompt": "fixture", "gnomon": {"requests": 2, "total_bytes": 48200, "turn_bytes": 24100,
                                           "turn_tool_bytes": 9000, "turn_message_bytes": 15100, "turn_tool_count": 9,
                                           "other_bytes": 0, "per": []}, "opencode": None}
    code = 0
else:
    rows = [{"id": "d-%d" % n, "recordedBy": "x", "announced": True, "misnamed": False, "recorded": n != 3,
             "complete": n != 3} for n in range(15)]
    doc, code = {"rows": rows}, 1
open(out, "w", encoding="utf-8").write(json.dumps(doc))
print("measured " + script.rsplit("/", 1)[-1])
sys.exit(code)
'''


def source(case: Any, folder: Path, bin_folder: Path) -> Path:
    """A fake Gnomon source checkout in ``folder`` (GNOMON_SOURCE) and a fake `node` in ``bin_folder``."""
    for rel, text in (("benchmarks/claim-check/check_claims.py", CLAIMS),
                      ("benchmarks/context-cost/measure.mjs", "// measured by the fake node\n"),
                      ("benchmarks/degradation-contract/contract.mjs", "// measured by the fake node\n")):
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8", newline="\n")
    fake_tool(bin_folder, "node", NODE)
    patcher = mock.patch.dict(os.environ, {"GNOMON_SOURCE": str(folder)})
    patcher.start()
    case.addCleanup(patcher.stop)
    return folder
