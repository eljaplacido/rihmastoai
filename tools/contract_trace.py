#!/usr/bin/env python3
"""contract_trace: which tests name which acceptance criteria.

No model, standard library only. It reads the contract and the test tree, and lists
each criterion with the tests whose function names contain its id. Hyphens become
underscores: criterion FR-O1-AC-2 is named by `test_FR_O1_AC_2_<anything>`.

Naming a criterion is not verifying it. In M0 a named criterion reads "named": a test
claims it, and nobody has yet observed that test fail at base and pass at head. A
criterion no test names reads "not measured". This tool never reports "verified".

Verdicts and exit codes:
  0  passed        the contract passes and every customer-confirmed criterion is named
                   (with --strict: every criterion is named)
  2  failed        the contract fails its check, or a required criterion is not named
  4  not measured  the contract could not be read, or the test tree does not exist
  1  internal error

Usage: python tools/contract_trace.py contract/contract.json [--tests tests] [--strict] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract_check  # noqa: E402

REPORT_SCHEMA = "gnomonfactory.trace/1"
TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(", re.MULTILINE)


def token(criterion_id: str) -> re.Pattern:
    """The pattern a test name must contain to name `criterion_id`.

    FR-O1-AC-1 must not be matched by FR_O1_AC_10, and FR-O1-AC-1 must not match XFR_O1_AC_1.
    """
    t = re.escape(criterion_id.replace("-", "_"))
    return re.compile(rf"(?<![A-Za-z0-9]){t}(?![0-9])")


def collect_tests(tests_dir: str) -> dict[str, list[str]]:
    """Map each test function name to the files that define it."""
    found: dict[str, list[str]] = {}
    for root, dirs, files in os.walk(tests_dir):
        dirs[:] = sorted(d for d in dirs if d not in {"__pycache__", "fixtures"})
        for name in sorted(files):
            if not (name.startswith("test") and name.endswith(".py")):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                for test in TEST_DEF.findall(fh.read()):
                    found.setdefault(test, []).append(os.path.relpath(path, tests_dir).replace(os.sep, "/"))
    return found


def trace(contract: dict, tests: dict[str, list[str]]) -> list[dict]:
    rows = []
    for req in contract.get("requirements", []):
        if req.get("provenance") == "withdrawn":
            continue
        for ac in req.get("acceptance", []):
            pat = token(ac["id"])
            names = sorted(t for t in tests if pat.search(t))
            rows.append({
                "id": ac["id"],
                "requirement": req["id"],
                "provenance": req.get("provenance"),
                "tests": names,
                "status": "named" if names else "not measured",
            })
    return rows


def run(contract_path: str, tests_dir: str, strict: bool = False) -> tuple[int, dict]:
    report = {"schema": REPORT_SCHEMA, "contract": contract_path, "tests": tests_dir, "strict": strict}
    check_code, check_report = contract_check.run(contract_path)
    report["contract_check"] = {k: check_report.get(k) for k in ("verdict", "exit", "revision")}
    if check_code == 4:
        report.update(verdict="not measured", exit=4, reason=check_report.get("reason"))
        return 4, report
    if not os.path.isdir(tests_dir):
        report.update(verdict="not measured", exit=4, reason=f"no test tree at {tests_dir}")
        return 4, report
    with open(contract_path, encoding="utf-8") as fh:
        contract = json.load(fh)
    rows = trace(contract, collect_tests(tests_dir))
    required = [r for r in rows if strict or r["provenance"] in contract_check.NEEDS_HUMAN]
    missing = [r["id"] for r in required if r["status"] != "named"]
    failed = check_code != 0 or bool(missing)
    report.update(
        verdict="failed" if failed else "passed",
        exit=2 if failed else 0,
        criteria=rows,
        summary={
            "criteria": len(rows),
            "named": sum(r["status"] == "named" for r in rows),
            "not_measured": sum(r["status"] == "not measured" for r in rows),
            "required_not_named": missing,
        },
    )
    return report["exit"], report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trace acceptance criteria to the tests that name them.")
    parser.add_argument("contract")
    parser.add_argument("--tests", default="tests")
    parser.add_argument("--strict", action="store_true", help="require every criterion to be named")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        code, report = run(args.contract, args.tests, args.strict)
    except Exception as exc:  # a bug in this tool, never a verdict
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return code
    if code == 4:
        print(f"NOT MEASURED  {report['reason']}")
        return code
    if report["contract_check"]["exit"] != 0:
        print(f"FAIL contract check: {report['contract_check']['verdict']} (run tools/contract_check.py for details)")
    for r in report["criteria"]:
        mark = "named       " if r["status"] == "named" else "NOT MEASURED"
        tests = ", ".join(r["tests"]) if r["tests"] else "-"
        print(f"{mark}  {r['id']:<12} [{r['provenance']}]  {tests}")
    s = report["summary"]
    print(f"{report['verdict'].upper()}  {s['named']} of {s['criteria']} criteria named by a test, "
          f"{s['not_measured']} not measured; required but not named: {', '.join(s['required_not_named']) or 'none'}")
    print("named means a test claims the criterion; it is not verified until the test is seen failing at base and passing at head")
    return code


if __name__ == "__main__":
    sys.exit(main())
