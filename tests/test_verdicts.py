"""Tests for kernel/verdicts.py (task T-004). Standard library only."""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from kernel.verdicts import combine_verdicts, validate_translation_table  # noqa: E402


class CombineVerdictsTest(unittest.TestCase):
    def test_FR_G3_AC_1_failed_outranks_not_measured(self):
        self.assertEqual(
            combine_verdicts(["not measured", "passed", "failed"]),
            "failed",
        )

    def test_FR_G3_AC_1_not_measured_without_failed(self):
        self.assertEqual(
            combine_verdicts(["passed", "not measured", "passed"]),
            "not measured",
        )

    def test_FR_G3_AC_1_all_not_applicable_is_not_measured(self):
        self.assertEqual(
            combine_verdicts(["not applicable", "not applicable"]),
            "not measured",
        )

    def test_FR_G3_AC_1_all_passed_is_passed(self):
        self.assertEqual(combine_verdicts(["passed"]), "passed")
        self.assertEqual(
            combine_verdicts(["passed", "passed", "not applicable"]),
            "passed",
        )


class TranslationTableTest(unittest.TestCase):
    def test_FR_G3_AC_2_non_zero_exit_to_passed_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_translation_table({0: "passed", 1: "passed"})

    def test_FR_G3_AC_2_valid_table_is_accepted(self):
        table = {0: "passed", 2: "violation", 10: "not measured"}
        self.assertIsNone(validate_translation_table(table))

    # T-011 (A-0002): violation, regressed and escalate never combine into passed.
    def test_FR_G3_AC_1_violation_never_combines_into_passed(self):
        self.assertEqual(combine_verdicts(["passed", "violation"]), "violation")

    def test_FR_G3_AC_1_regressed_counts_as_failed(self):
        self.assertEqual(combine_verdicts(["passed", "regressed"]), "failed")
        self.assertEqual(combine_verdicts(["violation", "regressed"]), "failed")

    def test_FR_G3_AC_1_escalate_never_combines_into_passed(self):
        self.assertEqual(combine_verdicts(["passed", "escalate"]), "escalate")
        self.assertEqual(combine_verdicts(["escalate", "violation"]), "violation")

    def test_FR_G3_AC_1_precedence_order_is_failed_violation_escalate_not_measured(self):
        self.assertEqual(combine_verdicts(["not measured", "escalate"]), "escalate")
        self.assertEqual(combine_verdicts(["not measured", "passed"]), "not measured")
        self.assertEqual(combine_verdicts([]), "not measured")

    def test_FR_G3_AC_3_translation_table_values_must_be_named_verdicts(self):
        with self.assertRaises(ValueError):
            validate_translation_table({0: "passed", 2: "denied"})
        with self.assertRaises(ValueError):
            validate_translation_table({0: "ok"})
        validate_translation_table({0: "passed", 2: "violation", 10: "not measured"})


if __name__ == "__main__":
    unittest.main()
