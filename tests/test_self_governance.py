"""This repository's Gnomon surface enforces the spec-to-verify chain on itself (task T-003, FR-O8-AC-1)."""

import os
import tomllib
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name: str) -> dict:
    with open(os.path.join(REPO, ".gnomon", name), "rb") as fh:
        return tomllib.load(fh)


class SelfGovernanceTest(unittest.TestCase):
    def setUp(self):
        self.policy = load("policy.toml")
        self.roles = load("roles.toml")["roles"]

    def test_FR_O8_AC_1_contract_specs_and_intake_are_write_protected(self):
        protected = self.policy["governance"]["paths"]["ci"]
        for path in ("contract/**", "specs/**", "intake/**", "decisions/**", "evidence/**"):
            self.assertIn(path, protected)
        self.assertEqual(self.policy["governance"]["ci"], "enforce")

    def test_FR_O8_AC_1_verify_declares_the_evidence_rules(self):
        verify = self.policy["verify"]
        self.assertTrue(verify.get("test_must_fail_first"))
        self.assertTrue(verify.get("exit_on_fail"))
        self.assertIn("@detected", verify.get("protects", []))
        # a run where no tests ran measured nothing; it must not read as a failure or a pass
        self.assertEqual(self.policy["verify"].get("exit_map", {}).get("5"), "unrunnable")

    def test_FR_O8_AC_1_no_role_may_write_the_contract(self):
        for name, role in self.roles.items():
            for glob in role.get("write_allow", []):
                self.assertFalse(glob.startswith(("contract/", "specs/", "intake/", "decisions/", ".gnomon/")),
                                 f"role {name} may write {glob}")

    def test_FR_O8_AC_1_verifier_is_read_only_and_on_a_different_model(self):
        verifier, builder = self.roles["verifier"], self.roles["builder"]
        self.assertFalse({"write", "edit"} & set(verifier["tools"]))
        self.assertNotEqual(verifier["model"], builder["model"])


if __name__ == "__main__":
    unittest.main()
