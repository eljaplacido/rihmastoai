"""Tests for tools/contract_trace.py (task T-002)."""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, HERE)   # its sibling test_contract_check, also as `python -m unittest tests.test_contract_trace`
import contract_trace as ct  # noqa: E402
from test_contract_check import base_contract  # noqa: E402


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.tests = os.path.join(self.dir, "tests")
        os.makedirs(self.tests)
        self.contract = os.path.join(self.dir, "contract.json")
        with open(self.contract, "w", encoding="utf-8") as fh:
            json.dump(base_contract(), fh)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write_tests(self, body: str, name: str = "test_sample.py"):
        with open(os.path.join(self.tests, name), "w", encoding="utf-8") as fh:
            fh.write(body)

    def test_FR_O6_AC_1_named_and_unnamed_criteria(self):
        self.write_tests(
            "def test_REQ_014_AC_1_fall_back_day():\n    pass\n"
            "def test_REQ_014_AC_2_exports_match():\n    pass\n"
        )
        code, report = ct.run(self.contract, self.tests)
        status = {r["id"]: r["status"] for r in report["criteria"]}
        self.assertEqual(status["REQ-014-AC-1"], "named")
        self.assertEqual(status["REQ-021-AC-1"], "not measured")
        # REQ-021 is vendor-proposed, so its gap is reported but does not fail the trace
        self.assertEqual(code, 0, report)
        # the trace never claims more than "named"
        self.assertNotIn("verified", {r["status"] for r in report["criteria"]})
        self.assertNotIn("passed", {r["status"] for r in report["criteria"]})

    def test_FR_O6_AC_1_unnamed_customer_criterion_fails(self):
        self.write_tests("def test_REQ_014_AC_1_fall_back_day():\n    pass\n")
        code, report = ct.run(self.contract, self.tests)
        self.assertEqual(code, 2)
        self.assertEqual(report["summary"]["required_not_named"], ["REQ-014-AC-2"])

    def test_FR_O6_AC_1_id_boundaries_are_exact(self):
        # AC_10 must not name AC_1, and a longer prefix must not either
        self.write_tests(
            "def test_REQ_014_AC_10_other():\n    pass\n"
            "def test_XREQ_014_AC_1_other():\n    pass\n"
            "def test_REQ_014_AC_2_ok():\n    pass\n"
        )
        code, report = ct.run(self.contract, self.tests)
        status = {r["id"]: r["status"] for r in report["criteria"]}
        self.assertEqual(status["REQ-014-AC-1"], "not measured")
        self.assertEqual(code, 2)

    def test_FR_O6_AC_1_strict_requires_every_criterion(self):
        self.write_tests(
            "def test_REQ_014_AC_1_a():\n    pass\n"
            "def test_REQ_014_AC_2_b():\n    pass\n"
        )
        self.assertEqual(ct.run(self.contract, self.tests)[0], 0)
        code, report = ct.run(self.contract, self.tests, strict=True)
        self.assertEqual((code, report["summary"]["required_not_named"]), (2, ["REQ-021-AC-1"]))

    def test_FR_O6_AC_1_missing_test_tree_is_not_measured(self):
        code, report = ct.run(self.contract, os.path.join(self.dir, "nope"))
        self.assertEqual((code, report["verdict"]), (4, "not measured"))

    def test_FR_O6_AC_1_failing_contract_fails_the_trace(self):
        c = base_contract()
        c["requirements"][0]["frobnicate"] = True
        with open(self.contract, "w", encoding="utf-8") as fh:
            json.dump(c, fh)
        self.write_tests("def test_REQ_014_AC_1_a():\n    pass\ndef test_REQ_014_AC_2_b():\n    pass\n")
        self.assertEqual(ct.run(self.contract, self.tests)[0], 2)


class RepositoryContractTest(unittest.TestCase):
    """This repository's own contract, judged by its own tools (FR-O8)."""

    def test_FR_O8_AC_2_repository_contract_passes_and_confirmed_criteria_are_named(self):
        code, report = ct.run(os.path.join(REPO, "contract", "contract.json"), os.path.join(REPO, "tests"))
        self.assertEqual(report["contract_check"]["exit"], 0, report["contract_check"])
        self.assertEqual(report["summary"]["required_not_named"], [], report["summary"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
