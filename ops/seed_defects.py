"""Seeded defects for a gate: plant one defect at a time and see whether the tests catch it.

Usage: python3 seed_defects.py REPO MODULE TEST_MODULE
Each mutant is a (name, old, new) text replacement in MODULE. A mutant that leaves the tests
passing "survives": the suite cannot see that defect. Writes JSON to stdout.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MUTANTS = [
    # Anchored on kernel/ledger.py as of T-006 round 3. Earlier rounds' anchors are in git history.
    ("M1 append stores the caller's payload, not its JSON round trip",
     "stored_event = json.loads(canonical_json(event))", "stored_event = event"),
    ("M2 append returns the stored record itself",
     "return copy.deepcopy(record)", "return record"),
    ("M3 read returns the live list",
     "return copy.deepcopy(self._events)", "return self._events"),
    ("M4 verify skips the prev linkage check",
     "if prev != previous_hash:", "if False:"),
    ("M5 verify skips the seq continuity check",
     "if seq != i:", "if False:"),
    ("M6 verify skips the first-record prev=None check",
     "if prev is not None:", "if False:"),
    ("M7 verify skips the exact-keys check",
     "if keys != Ledger.ALLOWED_KEYS:", "if False:"),
    ("M8 canonical_json allows NaN",
     "allow_nan=False", "allow_nan=True"),
    ("M9 verify skips the hash recomputation",
     "if stored_hash != expected:", "if False:"),
    ("M10 verify lets canonicalisation errors raise",
     "except Exception:\n        # verify never raises", "except KeyError:\n        # verify never raises"),
    ("M11 seq accepts bool",
     "type(seq) is not int", "not isinstance(seq, int)"),
    ("M12 verify ignores a ledger shorter than the head",
     "if len(events) < head_seq + 1:", "if False:"),
    ("M13 verify ignores a rewritten head record",
     'if events[head_seq]["hash"] != head_hash:', "if False:"),
]


def main():
    repo, module, test_module = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    source = (repo / module).read_text(encoding="utf-8")
    results = []
    for name, old, new in MUTANTS:
        if source.count(old) != 1:
            results.append({"mutant": name, "status": "not applicable", "why": "anchor text not found once"})
            continue
        work = Path(tempfile.mkdtemp(prefix="gf-seed-"))
        try:
            shutil.copytree(repo, work / "r", ignore=shutil.ignore_patterns(".git", ".gnomon-audit", ".gnomon-sessions", "__pycache__"))
            (work / "r" / module).write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            proc = subprocess.run([sys.executable, "-m", "unittest", test_module], cwd=work / "r",
                                  capture_output=True, text=True, timeout=120)
            caught = proc.returncode != 0
            failing = [l.split(" ")[1] for l in proc.stderr.splitlines() if l.startswith(("FAIL: ", "ERROR: "))]
            results.append({"mutant": name, "status": "caught" if caught else "SURVIVED", "by": failing})
        finally:
            shutil.rmtree(work, ignore_errors=True)
    json.dump(results, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
