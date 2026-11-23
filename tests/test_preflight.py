"""Tests for tools/preflight.py (task T-010, criterion FR-O8-AC-3)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import preflight as pf  # noqa: E402

HASH = "a" * 64
DOCTOR = {"exit": 0, "surface": {"hash": HASH}}


def record(**over):
    r = {"code": 0, "bucket": "result", "stop_reason": "answered", "surface_hash": HASH, "tool_steps": 3,
         "harness": "gnomon/0.6.5+fb458ea5"}
    r.update(over)
    return r


def statuses(report):
    return {c["check"]: c["status"] for c in report["checks"]}


class PreflightTest(unittest.TestCase):
    def test_FR_O8_AC_3_clean_run_passes(self):
        code, report = pf.judge(DOCTOR, 0, record(), "")
        self.assertEqual((code, report["verdict"]), (0, "passed"), report)

    def test_FR_O8_AC_3_inert_key_warning_fails(self):
        err = "  ⚠ .gnomon/policy.toml [verify]: protects is not a key [verify] reads; it does nothing."
        code, report = pf.judge(DOCTOR, 0, record(), err)
        self.assertEqual(code, 2)
        self.assertEqual(statuses(report)["inert_keys"], "failed")

    def test_FR_O8_AC_3_unusable_surface_fails(self):
        code, report = pf.judge(DOCTOR, 0, record(), "Surface cannot be used:\n  [audit] is declared here")
        self.assertEqual(code, 2)

    def test_FR_O8_AC_3_profile_override_is_exempt(self):
        err = ('  ⚠ .gnomon/roles.toml [roles.builder] model: model = "qwen3.6-35b" is ignored: '
               'role_profile "cloud_build" sets model = "deepseek-v4-pro" for this role, and the profile wins.')
        self.assertEqual(pf.judge(DOCTOR, 0, record(), err)[0], 0)

    def test_FR_O8_AC_3_no_tool_calls_fails(self):
        # a role offered no tools, or a model writing calls as text, makes no tool call
        code, report = pf.judge(DOCTOR, 0, record(tool_steps=0), "")
        self.assertEqual(code, 2)
        self.assertEqual(statuses(report)["tool_use"], "failed")

    def test_FR_O8_AC_3_surface_mismatch_fails(self):
        code, report = pf.judge(DOCTOR, 0, record(surface_hash="b" * 64), "")
        self.assertEqual((code, statuses(report)["surface_match"]), (2, "failed"))

    def test_FR_O8_AC_3_refusal_fails(self):
        code, report = pf.judge(DOCTOR, 0, record(code=2, bucket="refusal", stop_reason="malformed"), "")
        self.assertEqual((code, statuses(report)["task_result"]), (2, "failed"))

    def test_FR_O8_AC_3_doctor_problem_fails(self):
        self.assertEqual(pf.judge(DOCTOR, 1, record(), "")[0], 2)

    def test_FR_O8_AC_3_apparatus_failure_is_not_measured(self):
        code, report = pf.judge(DOCTOR, 0, record(code=10, bucket="apparatus_failure", stop_reason="apparatus"), "")
        self.assertEqual((code, report["verdict"]), (4, "not measured"))

    def test_FR_O8_AC_3_no_record_is_not_measured(self):
        self.assertEqual(pf.judge(DOCTOR, 0, None, "")[0], 4)

    def test_FR_O8_AC_3_failure_outranks_not_measured(self):
        code, report = pf.judge(DOCTOR, 1, None, "")
        self.assertEqual((code, report["verdict"]), (2, "failed"))

    def test_FR_O8_AC_3_missing_engine_is_not_measured(self):
        code, report = pf.run(os.path.join(os.path.dirname(__file__), "no-such-gnomon-binary"))
        self.assertEqual((code, report["verdict"]), (4, "not measured"))


if __name__ == "__main__":
    unittest.main()
