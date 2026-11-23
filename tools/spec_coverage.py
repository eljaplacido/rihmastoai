"""Spec coverage: how much of the brief is in the contract, and how much of that is verified.

The chain this measures, for every requirement the brief names:

  brief requirement -> contract requirement -> criteria -> tests that name them

Each brief requirement ends in one of these states:
- covered: in the contract, and every criterion is named by a test;
- partial: in the contract, but some criterion is named by no test;
- deferred: recorded in contract/deferred.json or contract/deferred/*.json with a reason;
- missing: neither.

    python tools/spec_coverage.py [--json] [--brief FILE] [--contract FILE]

Exit 0 always; `--gate` exits 1 while anything is missing.

The brief is private: a checkout without it (the public repository ships no intake/) has nothing to
measure against. The tool then says "the brief is not in this checkout", claims no measurement
(`"measured": false` with --json) and exits 0, with --gate too: not measured is not a pass and not a
fail.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIEF = ROOT / "intake" / "gnomon-factory-brief.md"
CONTRACT = ROOT / "contract" / "contract.json"
DEFERRED = ROOT / "contract" / "deferred.json"
NO_BRIEF = "the brief is not in this checkout"
_REQ =re.compile(r"^- \*\*(FR-[A-Z]\d+|NFR-[A-Z]+-?\d*)\*\*\s*(?:\[([^\]]+)\])?:?\s*(.*)$")
_SECTION = re.compile(r"^### ([A-Z])\. (.+)$")


def brief_requirements(path: Path = BRIEF) -> list[dict]:
    out, section = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _SECTION.match(line)
        if m:
            section = f"{m.group(1)}. {m.group(2)}"
            continue
        m = _REQ.match(line)
        if m:
            out.append({"id": m.group(1), "tier": m.group(2) or "", "text": m.group(3).strip(), "section": section})
    return out


def named_tests(root: Path = ROOT) -> set[str]:
    """Criterion ids named by a test function in tests/ (test_FR_X_AC_n_...)."""
    ids = set()
    for f in (root / "tests").glob("test_*.py"):
        for m in re.finditer(r"def (test_((?:FR|NFR)_[A-Z0-9_]+?_AC_\d+))", f.read_text(encoding="utf-8")):
            ids.add(m.group(2).replace("_", "-"))
    return ids


def deferrals(deferred: Path = DEFERRED) -> dict:
    """contract/deferred.json and contract/deferred/*.json (one file per section, so parallel work never collides)."""
    defer = json.loads(deferred.read_text(encoding="utf-8")) if deferred.exists() else {}
    folder = deferred.parent / "deferred"
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        defer.update(json.loads(f.read_text(encoding="utf-8")))
    return defer


def classify(r: dict, by_id: dict, named: set[str], defer: dict) -> dict:
    if r["id"] in by_id:
        crits = [a["id"] for a in by_id[r["id"]]["acceptance"]]
        unnamed = [x for x in crits if x not in named]
        row = {**r, "state": "covered" if crits and not unnamed else "partial", "criteria": crits, "unnamed": unnamed}
        if r["id"] in defer:                       # built in part: the rest is recorded as deferred
            row["rest"] = defer[r["id"]]
        return row
    if r["id"] in defer:
        return {**r, "state": "deferred", "reason": defer[r["id"]]}
    return {**r, "state": "missing"}


def coverage(brief: Path = BRIEF, contract: Path = CONTRACT, deferred: Path = DEFERRED) -> dict:
    if not brief.is_file():
        return {"measured": False, "reason": NO_BRIEF, "brief": str(brief)}
    reqs = brief_requirements(brief)
    c = json.loads(contract.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in c["requirements"]}
    named, defer = named_tests(contract.parent.parent), deferrals(deferred)
    rows = [classify(r, by_id, named, defer) for r in reqs]
    beyond = sorted(set(by_id) - {r["id"] for r in reqs})
    counts = {s: sum(1 for x in rows if x["state"] == s) for s in ("covered", "partial", "deferred", "missing")}
    total = len(rows)
    return {"measured": True, "brief_requirements": total, "counts": counts,
            "in_contract_share": (counts["covered"] + counts["partial"]) / total if total else None,
            "accounted_share": (total - counts["missing"]) / total if total else None,
            "rows": rows, "contract_beyond_brief": beyond}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/spec_coverage.py")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true", help="exit 1 while any brief requirement is missing")
    ap.add_argument("--brief", type=Path, default=BRIEF)
    ap.add_argument("--contract", type=Path, default=CONTRACT)
    args = ap.parse_args(argv)
    cov = coverage(args.brief, args.contract)
    if args.json:
        sys.stdout.write(json.dumps(cov, indent=2, ensure_ascii=False) + "\n")
    elif not cov["measured"]:
        print(f"{NO_BRIEF} ({args.brief}): spec coverage is not measured")
    else:
        n, k = cov["brief_requirements"], cov["counts"]
        print(f"brief requirements: {n}")
        print(f"  covered (in contract, every criterion named by a test): {k['covered']}")
        print(f"  partial (in contract, a criterion not named): {k['partial']}")
        print(f"  deferred (recorded with a reason): {k['deferred']}")
        print(f"  missing: {k['missing']}")
        print(f"contract requirements beyond the brief: {len(cov['contract_beyond_brief'])}")
        by_section: dict[str, list[str]] = {}
        for r in cov["rows"]:
            if r["state"] == "missing":
                by_section.setdefault(r["section"] or "?", []).append(r["id"])
        for s, ids in by_section.items():
            print(f"  missing in {s}: {', '.join(ids)}")
    return 1 if args.gate and cov["measured"] and cov["counts"]["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
