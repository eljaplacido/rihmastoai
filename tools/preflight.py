#!/usr/bin/env python3
"""preflight: is this repository's surface ready for cells under the pinned Gnomon build?

Criterion FR-O8-AC-3 (contract r2, amendment A-0001). No model in this tool; it runs
Gnomon and judges what Gnomon reports. Standard library only.

Checks:
  doctor        `gnomon doctor --json` exits 0
  task_result   a smoke task that needs a tool ends as code 0 / bucket "result"
  surface_match the smoke task ran under the surface doctor reported (same full hash)
  tool_use      the smoke task made at least one tool call (a role offered no tools,
                or a model writing calls as text, makes none)
  inert_keys    the engine reported no declared key it does not read ("does nothing",
                "Surface cannot be used"); deliberate profile overrides are exempt

Verdicts (failure outranks not measured, as in FR-G3):
  0  passed        every check passed
  2  failed        at least one check failed
  4  not measured  Gnomon could not run, or gave no record, or the smoke task was an
                   apparatus failure, and nothing failed
  1  internal error

Usage:
  python3 tools/preflight.py --gnomon "node ~/src/gnomonharness-master/packages/gnomon-cli/gnomon.js" [--dir .] [--role preflight] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

REPORT_SCHEMA = "gnomonfactory.preflight/1"
SMOKE_PROMPT = ("Preflight check. Call the glob tool once with the pattern tools/*.py, "
                "then answer with only the number of files it found. Do nothing else.")
INERT = [re.compile(r"does nothing"), re.compile(r"Surface cannot be used")]
EXEMPT = [re.compile(r"is ignored: role_profile")]   # a profile overriding a base key on purpose


def inert_lines(stderr: str) -> list[str]:
    out = []
    for line in stderr.splitlines():
        if any(p.search(line) for p in INERT) and not any(p.search(line) for p in EXEMPT):
            out.append(line.strip())
    return out


def judge(doctor: dict | None, doctor_exit: int | None, record: dict | None, stderr: str) -> tuple[int, dict]:
    """Judge parsed Gnomon output. Pure: no I/O, so it can be tested without Gnomon."""
    checks: list[dict] = []

    def add(name: str, status: str, detail) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    if doctor is None or doctor_exit is None:
        add("doctor", "not measured", "gnomon doctor did not run or gave no JSON")
        doctor_hash = None
    else:
        add("doctor", "passed" if doctor_exit == 0 else "failed", f"exit {doctor_exit}")
        doctor_hash = (doctor.get("surface") or {}).get("hash")

    if record is None:
        add("task_result", "not measured", "the smoke task gave no record")
    elif record.get("code") == 10 or record.get("bucket") == "apparatus_failure":
        add("task_result", "not measured",
            f"apparatus failure (stop_reason {record.get('stop_reason')}); nothing was judged")
    else:
        ok = record.get("code") == 0 and record.get("bucket") == "result"
        add("task_result", "passed" if ok else "failed",
            f"code {record.get('code')}, bucket {record.get('bucket')}, stop_reason {record.get('stop_reason')}")
        rec_hash = record.get("surface_hash")
        if doctor_hash is None:
            add("surface_match", "not measured", "doctor reported no surface hash")
        else:
            add("surface_match", "passed" if rec_hash == doctor_hash else "failed",
                {"doctor": doctor_hash, "task": rec_hash})
        steps = record.get("tool_steps")
        add("tool_use", "passed" if isinstance(steps, int) and steps > 0 else "failed",
            f"tool_steps {steps}")

    lines = inert_lines(stderr or "")
    add("inert_keys", "failed" if lines else "passed", lines or "none")

    statuses = {c["status"] for c in checks}
    if "failed" in statuses:
        code, verdict = 2, "failed"
    elif "not measured" in statuses:
        code, verdict = 4, "not measured"
    else:
        code, verdict = 0, "passed"
    return code, {"schema": REPORT_SCHEMA, "verdict": verdict, "exit": code, "checks": checks}


def _run_json(argv: list[str], cwd: str, timeout: int) -> tuple[int | None, dict | None, str]:
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, None, f"{type(exc).__name__}: {exc}"
    try:
        return proc.returncode, json.loads(proc.stdout), proc.stderr
    except json.JSONDecodeError:
        return proc.returncode, None, proc.stderr


def run(gnomon: str, directory: str = ".", role: str = "preflight", timeout: int = 420) -> tuple[int, dict]:
    base = shlex.split(os.path.expanduser(gnomon))
    base = [os.path.expanduser(part) for part in base]
    d_exit, doctor, d_err = _run_json(base + ["doctor", "--json"], directory, 120)
    _, record, t_err = _run_json(
        base + ["task", SMOKE_PROMPT, "--role", role, "--json"], directory, timeout)
    code, report = judge(doctor, d_exit, record, (d_err or "") + "\n" + (t_err or ""))
    report.update(gnomon=gnomon, dir=os.path.abspath(directory), role=role,
                  harness=(record or {}).get("harness"))
    return code, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the surface is ready for cells.")
    parser.add_argument("--gnomon", default="gnomon", help="command that runs the pinned Gnomon build")
    parser.add_argument("--dir", default=".")
    parser.add_argument("--role", default="preflight")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        code, report = run(args.gnomon, args.dir, args.role)
    except Exception as exc:  # a bug in this tool, never a verdict
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for c in report["checks"]:
            print(f"{c['status']:<13} {c['check']:<14} {c['detail']}")
        print(f"{report['verdict'].upper()}  harness {report.get('harness')}")
    return code


if __name__ == "__main__":
    sys.exit(main())
