import unittest

from adapters.gnomon_outcome import UnknownNative, outcome


def rec(bucket="result", code=0, verify=None, stop="answered"):
    r = {"bucket": bucket, "code": code, "stop_reason": stop}
    if verify is not None:
        r["verify"] = verify
    return r


class OutcomeTest(unittest.TestCase):
    def test_FR_C5_AC_1_each_native_outcome_maps_to_its_verdict_with_native_values(self):
        cases = [
            (rec(verify="passed"), "passed", False),
            (rec(verify={"status": "passed"}), "passed", False),
            (rec(verify="failed"), "failed", False),
            (rec(verify="regressed"), "failed", False),
            (rec(verify="passed_unverified"), "failed", False),
            (rec(verify="unrunnable"), "not measured", False),
            (rec(verify="skipped"), "not measured", False),
            (rec(verify="declined"), "not measured", False),
            (rec(), "not measured", False),                          # no verify configured
            (rec("refusal", 2, verify="passed"), "violation", False),
            (rec("apparatus_failure", 10, stop="error"), "not measured", True),
            (rec("apparatus_failure", 11, stop="in_progress"), "not measured", True),
        ]
        for r, verdict, apparatus in cases:
            out = outcome(r)
            self.assertEqual(out["verdict"], verdict, r)
            self.assertEqual(out["apparatus_failure"], apparatus, r)
            self.assertEqual(out["native"]["bucket"], r["bucket"])
            self.assertEqual(out["native"]["code"], r["code"])
        tampered = outcome(rec("refusal", 3, stop="tamper"))
        self.assertEqual((tampered["verdict"], tampered["tampered"]), ("not measured", True))

    def test_FR_C5_AC_3_exit_12_and_13_are_apparatus_failures_and_verify_detail_travels_as_native(self):
        # CONTRACTS §1: 12 provider_unreachable, 13 context_exhausted, both apparatus_failure, ending
        # on stop_reason endpoint_error. 0.6.6 sends more overflows to 13. Before, both raised.
        for code in (10, 11, 12, 13):
            out = outcome(rec("apparatus_failure", code, stop="endpoint_error"))
            self.assertEqual((out["verdict"], out["apparatus_failure"]), ("not measured", True), code)
            self.assertEqual(out["native"]["code"], code)
        # [verify] exit_on_fail / --require-verify (§53): the process exits 4 for an unrunnable
        # check and 1 for a failed one, while the record's bucket and code stay result and 0.
        # The record decides; the exit and the detail travel beside the verdict.
        unrunnable = dict(rec(verify="unrunnable"), _exit=4, verify_exit=5, verify_rounds=1,
                          verify_reason="exit 5 read as unrunnable", verify_tail="NO TESTS RAN")
        out = outcome(unrunnable)
        self.assertEqual(out["verdict"], "not measured")
        self.assertEqual({k: out["native"][k] for k in ("exit", "verify_exit", "verify_rounds", "verify_reason")},
                         {"exit": 4, "verify_exit": 5, "verify_rounds": 1, "verify_reason": "exit 5 read as unrunnable"})
        self.assertNotIn("NO TESTS RAN", str(out["native"]))                 # the tail is content: it stays in the record
        for status in ("failed", "regressed", "passed_unverified"):
            self.assertEqual(outcome(dict(rec(verify=status), _exit=1))["verdict"], "failed", status)
        self.assertEqual(outcome(dict(rec(verify="passed"), _exit=0))["verdict"], "passed")

    def test_FR_C5_AC_3_every_0_6_6_stop_reason_on_its_documented_bucket_maps_without_guessing(self):
        from adapters.gnomon_outcome import STOP_REASONS

        documented = [  # CONTRACTS `stop_reason` and §1 at v0.6.6: (stop reason, bucket, code) a record carries
            ("answered", "result", 0), ("truncated", "result", 0), ("empty", "result", 0), ("stall", "refusal", 2),
            ("step_wall", "refusal", 2), ("cancelled", "refusal", 2), ("malformed", "refusal", 2),
            ("truncated", "refusal", 2), ("deadline", "refusal", 2), ("tamper", "refusal", 3),
            ("apparatus", "apparatus_failure", 10), ("endpoint_error", "apparatus_failure", 12),
            ("endpoint_error", "apparatus_failure", 13), ("killed", "apparatus_failure", 11),
            ("in_progress", "apparatus_failure", 11),
        ]
        self.assertEqual({s for s, _, _ in documented}, set(STOP_REASONS))
        for stop, bucket, code in documented:
            out = outcome(rec(bucket, code, stop=stop))
            self.assertEqual(out["native"]["stop_reason"], stop)
            self.assertEqual(out["apparatus_failure"], bucket == "apparatus_failure", stop)

    def test_FR_C5_AC_2_an_unknown_native_value_raises(self):
        for r in (rec(verify="kinda"), rec("refusal", 7), rec("result", 2, verify="passed"), rec("weird", 0),
                  rec("apparatus_failure", 1), {"bucket": "result", "code": True}, {"bucket": "result"}):
            with self.assertRaises(UnknownNative, msg=r):
                outcome(r)


if __name__ == "__main__":
    unittest.main()
