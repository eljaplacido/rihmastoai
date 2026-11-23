"""The factory's own code passes its quality gate (task V-42, criterion FR-O8-AC-5).

The first test runs `tools/quality.py --gate` on this repository against the recorded baseline.
The others seed each defect the gate exists to catch into a small tree, and check that the gate
names it, so a gate that silently stopped looking would fail here.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import quality  # noqa: E402

CLEAN = '''"""A clean module."""

import json


def load(text: str) -> dict:
    return json.loads(text)
'''


class SeededTree(unittest.TestCase):
    """A throwaway repository with a kernel/ package, measured with no ruff or mypy."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rihma-quality-"))
        self.write("kernel/__init__.py", "")
        self.write("kernel/clean.py", CLEAN)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, text, newline="\n"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)

    def measure(self, baseline=None):
        report = quality.analyse(self.root)
        held = baseline if baseline is not None else {"counts": dict(report["counts"])}
        return report, quality.gate(report["counts"], {}, held)


class GateTest(SeededTree):
    def test_FR_O8_AC_5_the_factory_code_passes_its_quality_gate(self):
        # ruff and mypy join in when RIHMA_QA_PYTHON names an interpreter that has them
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "quality.py"), "--gate"], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=900)
        self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-2000:])
        self.assertIn("GATE PASSED", proc.stdout)

    def test_FR_O8_AC_5_each_hard_rule_fails_the_gate_whatever_the_baseline(self):
        self.write("kernel/bad.py", "import requests\n\n\ndef f(x=[]):\n    try:\n        return x\n    except:\n"
                                    "        return None\n")
        self.write("kernel/crlf.py", "X = 1\n", newline="\r\n")
        report, verdict = self.measure()
        self.assertFalse(verdict["passed"])
        failed = " ".join(verdict["failures"])
        for rule in ("third_party_imports", "bare_excepts", "mutable_defaults", "non_lf_files"):
            self.assertIn(f"hard rule {rule}", failed)
        self.assertEqual(report["counts"]["third_party_imports"], 1)

    def test_FR_O8_AC_5_a_count_above_its_baseline_fails_and_a_lower_one_asks_to_lower_it(self):
        self.write("kernel/extra.py", "import os\n\n\ndef f() -> None:\n    return None\n")
        report, _ = self.measure()
        self.assertEqual(report["counts"]["unused_imports"], 1)
        held = {"counts": {**report["counts"], "unused_imports": 0}}
        self.assertIn("unused_imports: 1, above its baseline 0", quality.gate(report["counts"], {}, held)["failures"])
        held = {"counts": {**report["counts"], "unused_imports": 2}}
        verdict = quality.gate(report["counts"], {}, held)
        self.assertTrue(verdict["passed"])
        self.assertTrue(any(x.startswith("unused_imports: 1, below") for x in verdict["lowered"]))

    def test_FR_O8_AC_5_no_baseline_fails_the_gate(self):
        report = quality.analyse(self.root)
        self.assertFalse(quality.gate(report["counts"], {}, None)["passed"])

    def test_FR_O8_AC_5_without_ruff_and_mypy_their_counts_are_not_measured(self):
        with mock.patch.dict(os.environ, {quality.QA_PYTHON_ENV: str(self.root / "no-such-python")}):
            ext = quality.external(self.root)
        self.assertFalse(ext["ruff"]["measured"])
        self.assertIn("not measured", ext["mypy"]["reason"])
        counts, versions = quality.external_counts(ext)
        self.assertEqual((counts, versions), ({}, {}))
        report = quality.analyse(self.root)
        held = {"counts": {**report["counts"], "ruff_findings": 5}, "tools": {"ruff": "0.17.6"}}
        verdict = quality.gate(report["counts"], versions, held)
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["not_measured"], ["ruff_findings"])


class DetectionTest(SeededTree):
    def findings(self, rel, key):
        report = quality.analyse(self.root)
        return next(f for f in report["files"] if f["path"] == rel).get(key, [])

    def test_FR_O8_AC_5_a_local_import_shadows_an_unused_module_import(self):
        self.write("kernel/shadow.py", "from json import loads\n\n\ndef f(t: str) -> object:\n"
                                       "    from json import loads\n    return loads(t)\n")
        self.assertEqual([u["line"] for u in self.findings("kernel/shadow.py", "unused_imports")], [1])
        self.assertEqual(self.findings("kernel/shadow.py", "duplicate_imports")[0]["why"],
                         "already imported by the module")

    def test_FR_O8_AC_5_exports_string_annotations_and_submodule_imports_are_not_findings(self):
        self.write("kernel/ok.py", '"""Uses."""\n\nimport urllib.error\nimport urllib.request\n'
                                   'from pathlib import Path\nfrom json import dumps\n\n__all__ = ["dumps"]\n\n\n'
                                   'def f(p: "Path") -> object:\n    return urllib.request, urllib.error\n')
        self.assertEqual(self.findings("kernel/ok.py", "unused_imports"), [])
        self.assertEqual(self.findings("kernel/ok.py", "duplicate_imports"), [])

    def test_FR_O8_AC_5_unused_locals_duplicates_prints_and_broad_excepts_are_found(self):
        helper = ("def _store(factory):\n    from kernel.learn import factory_project\n\n"
                  "    return factory_project(factory)\n")
        self.write("kernel/a.py", helper)
        self.write("kernel/b.py", helper + "\n\ndef g():\n    unused = 1\n    print('x')\n    try:\n        return 2\n"
                                  "    except Exception:\n        return 3\n    except Exception:  # said why\n"
                                  "        return 4\n\n\nif __name__ == '__main__':\n    print('ok')\n")
        report = quality.analyse(self.root)
        self.assertEqual([[m["path"] for m in g] for g in report["duplicates"]], [["kernel/a.py", "kernel/b.py"]])
        self.assertEqual(report["counts"]["duplicate_bodies"], 1)
        self.assertEqual([u["name"] for u in self.findings("kernel/b.py", "unused_locals")], ["unused"])
        self.assertEqual([p["line"] for p in self.findings("kernel/b.py", "prints")], [9])
        self.assertEqual([b["explained"] for b in self.findings("kernel/b.py", "broad_excepts")], [False, True])

    def test_FR_O8_AC_5_annotation_length_and_complexity_are_measured(self):
        branches = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(16))
        self.write("kernel/c.py", f"def big(x):\n{branches}    return -1\n\n\nclass K:\n"
                                  "    def m(self, a: int) -> int:\n        return a\n")
        report = quality.analyse(self.root)
        row = next(f for f in report["files"] if f["path"] == "kernel/c.py")
        big = next(fn for fn in row["functions"] if fn["name"] == "big")
        self.assertEqual((big["complexity"], big["lines"], big["annotated"]), (17, 34, False))
        self.assertTrue(next(fn for fn in row["functions"] if fn["name"] == "K.m")["annotated"])
        self.assertEqual(report["annotation"]["by_file"]["kernel/c.py"]["missing"], ["big"])
        self.assertEqual(report["counts"]["complex_functions"], 1)

    def test_FR_O8_AC_5_the_coverage_fallback_counts_statements_that_ran(self):
        self.write("kernel/m.py", "def used():\n    return 1\n\n\ndef unused():\n    return 2\n")
        self.write("tests/test_m.py", "import unittest\n\nfrom kernel.m import used\n\n\n"
                                      "class T(unittest.TestCase):\n    def test_used(self):\n"
                                      "        self.assertEqual(used(), 1)\n")
        proc = subprocess.run([sys.executable, str(ROOT / "tools" / "covered.py"), "--root", str(self.root),
                               "--packages", "kernel", "--json"], cwd=self.root, capture_output=True, text=True,
                              encoding="utf-8", timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        rep = json.loads(proc.stdout)
        row = next(r for r in rep["modules"] if r["path"] == "kernel/m.py")
        self.assertEqual((row["statements"], row["missed"], row["missing"]), (4, 1, "6"))
        self.assertEqual(rep["tests"], 1)


if __name__ == "__main__":
    unittest.main()
