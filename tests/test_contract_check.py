"""Tests for tools/contract_check.py. Standard library only: python -m unittest discover -s tests"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import contract_check as cc  # noqa: E402


def base_contract() -> dict:
    """A small contract that holds every rule."""
    return {
        "schema": cc.SCHEMA,
        "contract": "energy-reports",
        "requirements": [
            {
                "id": "REQ-014",
                "statement": "Daily totals are grouped by local calendar day.",
                "provenance": "customer-confirmed",
                "decided_by": "product-owner",
                "decided_on": "2026-10-02",
                "acceptance": [
                    {
                        "id": "REQ-014-AC-1",
                        "given": "a meter in Europe/Helsinki",
                        "when": "the daily report runs for 27 Oct 2026",
                        "then": "27 Oct has 25 hourly buckets",
                        "check": {"kind": "test"},
                        "must_differ_on": [{"tz": "Europe/Helsinki"}, {"tz": "UTC"}],
                    },
                    {"id": "REQ-014-AC-2", "then": "exports match report totals",
                     "check": {"kind": "holdout", "ref": "H-11"}},
                ],
            },
            {
                "id": "REQ-021",
                "statement": "The report lists meters by site.",
                "provenance": "vendor-proposed",
                "acceptance": [{"id": "REQ-021-AC-1", "then": "meters are grouped by site"}],
            },
        ],
        "tasks": [
            {"id": "T-001", "title": "Group by local day", "criteria": ["REQ-014-AC-1", "REQ-014-AC-2"],
             "scope": {"write": ["src/reports/**", "tests/reports/**"], "read": ["src/**"]}},
            {"id": "T-002", "title": "Site grouping", "criteria": ["REQ-021-AC-1"], "depends_on": ["T-001"]},
        ],
    }


class ContractCheckTest(unittest.TestCase):
    def judge(self, contract) -> tuple[int, dict]:
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(contract, fh)
        try:
            return cc.run(path)
        finally:
            os.unlink(path)

    def rules(self, report) -> set:
        return {v["rule"] for v in report.get("violations", [])}

    def assertFailsWith(self, contract, rule):
        code, report = self.judge(contract)
        self.assertEqual(code, 2, report)
        self.assertIn(rule, self.rules(report), report["violations"])

    def test_valid_contract_passes(self):
        code, report = self.judge(base_contract())
        self.assertEqual(code, 0, report)
        self.assertEqual(report["verdict"], "passed")
        self.assertEqual(report["counts"], {"requirements": 2, "criteria": 3, "tasks": 2})
        # a vendor-proposed criterion without a check is a warning, not a violation
        self.assertEqual([w["rule"] for w in report["warnings"]], ["W-UNCHECKED"])

    def test_FR_O2_AC_1_unknown_key_is_rejected(self):
        c = base_contract()
        c["requirements"][0]["priority"] = "high"
        self.assertFailsWith(c, "R-KEYS")

    def test_missing_required_key(self):
        c = base_contract()
        del c["requirements"][0]["statement"]
        self.assertFailsWith(c, "R-KEYS")

    def test_FR_O1_AC_1_customer_criterion_without_check_fails(self):
        c = base_contract()
        del c["requirements"][0]["acceptance"][0]["check"]
        self.assertFailsWith(c, "R-CHECK")

    def test_signed_plan_entry_excuses_missing_check(self):
        c = base_contract()
        del c["requirements"][0]["acceptance"][0]["check"]
        c["verification_plan"] = [{"criterion": "REQ-014-AC-1", "reason": "needs a real meter",
                                   "signed_by": "product-owner", "signed_on": "2026-11-22"}]
        code, report = self.judge(c)
        self.assertEqual(code, 0, report)

    def test_plan_signed_by_autopilot_does_not_count(self):
        c = base_contract()
        del c["requirements"][0]["acceptance"][0]["check"]
        c["verification_plan"] = [{"criterion": "REQ-014-AC-1", "reason": "x",
                                   "signed_by": "factory-autopilot", "signed_on": "2026-11-22"}]
        code, report = self.judge(c)
        self.assertEqual(code, 2)
        self.assertTrue({"R-HUMAN", "R-CHECK"} <= self.rules(report))

    def test_signed_manual_needs_plan_entry(self):
        c = base_contract()
        c["requirements"][0]["acceptance"][0]["check"] = {"kind": "signed_manual"}
        self.assertFailsWith(c, "R-CHECK")

    def test_customer_requirement_needs_a_person(self):
        c = base_contract()
        c["requirements"][0]["decided_by"] = "autopilot"
        self.assertFailsWith(c, "R-HUMAN")

    def test_unknown_provenance(self):
        c = base_contract()
        c["requirements"][1]["provenance"] = "probably"
        self.assertFailsWith(c, "R-ENUM")

    def test_criterion_id_must_extend_requirement_id(self):
        c = base_contract()
        c["requirements"][1]["acceptance"][0]["id"] = "REQ-099-AC-1"
        c["tasks"][1]["criteria"] = ["REQ-099-AC-1"]
        self.assertFailsWith(c, "R-ID")

    def test_duplicate_id(self):
        c = base_contract()
        c["tasks"][1]["id"] = "T-001"
        self.assertFailsWith(c, "R-UNIQUE")

    def test_FR_O2_AC_3_untraced_criterion_fails(self):
        c = base_contract()
        c["tasks"][1]["criteria"] = ["REQ-014-AC-1"]
        self.assertFailsWith(c, "R-TRACE")

    def test_FR_O2_AC_3_task_without_criteria_fails(self):
        c = base_contract()
        c["tasks"].append({"id": "T-003", "title": "Refactor", "criteria": []})
        self.assertFailsWith(c, "R-TRACE")

    def test_task_referencing_unknown_criterion(self):
        c = base_contract()
        c["tasks"][0]["criteria"].append("REQ-014-AC-9")
        self.assertFailsWith(c, "R-REF")

    def test_work_on_withdrawn_requirement_fails(self):
        c = base_contract()
        c["requirements"][1]["provenance"] = "withdrawn"
        self.assertFailsWith(c, "R-TRACE")

    def test_task_may_not_write_the_contract(self):
        c = base_contract()
        c["tasks"][0]["scope"]["write"].append("contract/**")
        self.assertFailsWith(c, "R-SCOPE")

    def test_must_differ_on_needs_two_different_inputs(self):
        c = base_contract()
        c["requirements"][0]["acceptance"][0]["must_differ_on"] = [{"tz": "UTC"}, {"tz": "UTC"}]
        self.assertFailsWith(c, "R-DIFFER")

    def test_holdout_needs_scenario_ref(self):
        c = base_contract()
        c["requirements"][0]["acceptance"][1]["check"] = {"kind": "holdout"}
        self.assertFailsWith(c, "R-CHECK")

    def test_dependency_cycle(self):
        c = base_contract()
        c["tasks"][0]["depends_on"] = ["T-002"]
        code, report = self.judge(c)
        self.assertEqual(code, 2)
        self.assertIn("T-001 -> T-002 -> T-001", [v["got"] for v in report["violations"]])

    def test_FR_O2_AC_2_counts_are_recomputed(self):
        c = base_contract()
        c["counts"] = {"requirements": 2, "criteria": 4, "tasks": 2}
        self.assertFailsWith(c, "R-COUNTS")

    def test_FR_O1_AC_3_stale_revision_fails_and_fresh_revision_passes(self):
        c = base_contract()
        c["revision"] = "sha256:" + "0" * 64
        self.assertFailsWith(c, "R-REVISION")
        c["revision"] = cc.canonical_revision(c)
        self.assertEqual(self.judge(c)[0], 0)

    def test_FR_O1_AC_2_revision_ignores_key_order(self):
        c = base_contract()
        reordered = json.loads(json.dumps(c, sort_keys=True))
        self.assertEqual(cc.canonical_revision(c), cc.canonical_revision(reordered))
        changed = copy.deepcopy(c)
        changed["requirements"][0]["statement"] += " "
        self.assertNotEqual(cc.canonical_revision(c), cc.canonical_revision(changed))

    def test_FR_O2_AC_4_unknown_schema_is_not_measured(self):
        c = base_contract()
        c["schema"] = "gnomonfactory.contract/2"
        code, report = self.judge(c)
        self.assertEqual((code, report["verdict"]), (4, "not measured"))

    def test_FR_O2_AC_4_unreadable_file_is_not_measured(self):
        code, report = cc.run(os.path.join(tempfile.gettempdir(), "does-not-exist-gf.json"))
        self.assertEqual(code, 4)

    def test_FR_O2_AC_4_invalid_json_is_not_measured(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            fh.write("{not json")
        try:
            self.assertEqual(cc.run(path)[0], 4)
        finally:
            os.unlink(path)

    def test_cli_json_output(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(base_contract(), fh)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(cc.main([path, "--json"]), 0)
        finally:
            os.unlink(path)
        self.assertEqual(json.loads(out.getvalue())["verdict"], "passed")


if __name__ == "__main__":
    unittest.main()
