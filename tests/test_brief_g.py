"""Brief section G, gate and evidence: what the kernel's gate really does for FR-G2.

FR-G2 says a criterion counts as met only when an executing test names it, the factory saw the
test run, and the test failed on the revision before the change. These tests drive real builds
(a scripted builder cell, the kernel's own gate on a real git product) and check each part that
is built. What is not built (the gate does not check that the naming test executed rather than
being skipped or never collected), and FR-G4, FR-G5, FR-G7 and FR-G9, are recorded in
contract/deferred/g.json.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import (GOOD_ROUTES, GOOD_TEST, FactoryTestCase, good_cell, lazy_cell, model,  # noqa: E402
                           no_findings)

from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.gate import run_suite  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import GIT_ID, Lanes, _git  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import evidence  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
GOOD_NAME = "test_R_1_AC_1_post_item_returns_201_with_id"

# The test R-1-AC-1 names expects 200 where the route answers 201: it fails at head.
BOASTING_TEST = GOOD_TEST.replace("self.assertEqual(status, 201)", "self.assertEqual(status, 200)")

LOANS_TEST = '''import unittest


class LoansTest(unittest.TestCase):
    def test_R_2_AC_1_loan_without_approver_is_refused(self):
        self.assertTrue(True)
'''


def boasting_cell(lane_path, prompt):
    """Builds the route, leaves a failing test, and reports that every test passed."""
    Path(lane_path, "app", "routes.py").write_text(GOOD_ROUTES, encoding="utf-8", newline="\n")
    Path(lane_path, "tests", "test_items.py").write_text(BOASTING_TEST, encoding="utf-8", newline="\n")
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 6, "model": "fake-builder",
            "output": "Done. R-1-AC-1 is met: I ran python3 -m unittest discover -s tests and every test passed."}


def signals(out: dict) -> dict:
    return {s["name"]: s for s in out["rounds"][-1]["gate"]["signals"]}


class BriefGateTest(FactoryTestCase):
    def compiled(self, title="Loans"):
        p = self.new(mode="assume", title=title)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def states(self, p) -> dict:
        return {e["criterion"]: e for e in evidence(p)}

    def push_to_main(self, p, name: str, change) -> str:
        """Commit straight to the product's main, past every gate, as a person with push access could."""
        work = self.tmp / name
        _git(self.tmp, "clone", "-q", str(p.path("repo.git")), name)
        change(work)
        _git(work, "add", "-A")
        _git(work, *GIT_ID, "commit", "-q", "-m", f"{name}: straight to main")
        _git(work, "push", "-q", "origin", "main")
        return _git(work, "rev-parse", "HEAD")

    # -- the factory saw the test run ------------------------------------------------------------

    def test_FR_G2_AC_1_the_gate_runs_the_suite_itself_and_a_cells_claim_of_passing_tests_counts_for_nothing(self):
        p = self.compiled()
        good = build_task(p, "T-001", lanes=Lanes(self.tmp / "la", size=1), cell_runner=good_cell,
                          verifier_runner=no_findings)
        self.assertEqual(good["status"], "merged")
        seen = signals(good)["tests"]
        self.assertEqual(seen["verdict"], "passed")
        self.assertEqual(seen["native"]["exit"], 0)
        self.assertEqual(seen["native"]["tests"][GOOD_NAME], "ok")     # the kernel saw this very test run
        self.assertGreaterEqual(seen["native"]["ran"], 1)
        self.assertEqual(self.states(p)["R-1-AC-1"]["state"], "verified")

        q = self.compiled("Loans B")
        main_before = _git(q.path("repo.git"), "rev-parse", "main")
        out = build_task(q, "T-001", lanes=Lanes(self.tmp / "lb", size=1), cell_runner=boasting_cell,
                         verifier_runner=no_findings, max_rounds=0)
        self.assertEqual(out["status"], "escalated")                    # the cell's "every test passed" is not read
        sig = signals(out)
        self.assertEqual(sig["tests"]["verdict"], "failed")
        self.assertNotEqual(sig["tests"]["native"]["exit"], 0)
        self.assertEqual(sig["tests"]["native"]["tests"][GOOD_NAME], "FAIL")
        self.assertIn(GOOD_NAME, sig["tests"]["detail"])
        self.assertEqual((sig["trace"]["verdict"], sig["fail_first"]["verdict"]), ("passed", "passed"))
        gate = [r["event"]["payload"] for r in q.ledger().of_kind("gate")][-1]
        self.assertEqual((gate["verdict"], gate["signals"]["tests"]), ("failed", "failed"))
        self.assertTrue(any(o.startswith("tests:") and GOOD_NAME in o for o in gate["objections"]), gate["objections"])
        self.assertEqual(q.ledger().of_kind("merged"), [])
        self.assertEqual(_git(q.path("repo.git"), "rev-parse", "main"), main_before)
        self.assertNotEqual(self.states(q)["R-1-AC-1"]["state"], "verified")

    # -- the test failed on the revision before the change ----------------------------------------

    def test_FR_G2_AC_2_each_criterions_test_must_fail_on_the_revision_before_the_change(self):
        p = self.compiled()
        repo = p.path("repo.git")
        base = _git(repo, "rev-parse", "main")
        out = build_task(p, "T-001", lanes=Lanes(self.tmp / "la", size=1), cell_runner=good_cell,
                         verifier_runner=no_findings)
        self.assertEqual(out["status"], "merged")
        ff = signals(out)["fail_first"]
        self.assertEqual(ff["verdict"], "passed")
        self.assertEqual(ff["native"]["base"], base)                    # the revision before the change
        self.assertEqual(ff["native"]["criteria"], ["R-1-AC-1"])
        self.assertEqual(ff["native"]["passed_at_base"], {})

        # What the gate recorded holds: the head's test fails at that base and passes at main.
        work = self.tmp / "replay"
        _git(self.tmp, "clone", "-q", str(repo), "replay")
        head_test = _git(work, "show", "main:tests/test_items.py")
        _git(work, "checkout", "-q", base)
        Path(work, "tests", "test_items.py").write_text(head_test + "\n", encoding="utf-8", newline="\n")
        self.assertIn(run_suite(work, pattern="R_1_AC_1")["tests"].get(GOOD_NAME), ("FAIL", "ERROR"))
        _git(work, "checkout", "-q", "--", ".")
        _git(work, "clean", "-q", "-fd")
        _git(work, "checkout", "-q", "main")
        self.assertEqual(run_suite(work, pattern="R_1_AC_1")["tests"].get(GOOD_NAME), "ok")

        # A test that already passes before the change proves nothing, and the gate says which one.
        q = self.compiled("Loans B")
        q_base = _git(q.path("repo.git"), "rev-parse", "main")
        lazy = build_task(q, "T-001", lanes=Lanes(self.tmp / "lb", size=1), cell_runner=lazy_cell,
                          verifier_runner=no_findings, max_rounds=0)
        self.assertEqual(lazy["status"], "escalated")
        ff = signals(lazy)["fail_first"]
        self.assertEqual(ff["verdict"], "failed")
        self.assertEqual(ff["native"]["base"], q_base)
        self.assertEqual(ff["native"]["passed_at_base"], {"R-1-AC-1": ["test_R_1_AC_1_always_true"]})
        self.assertEqual(signals(lazy)["tests"]["verdict"], "passed")   # its suite is green: that is not enough
        objections = lazy["rounds"][-1]["gate"]["objections"]
        self.assertTrue(any(o.startswith("fail_first:") and "test_R_1_AC_1_always_true" in o for o in objections),
                        objections)
        self.assertEqual(_git(q.path("repo.git"), "rev-parse", "main"), q_base)
        self.assertNotEqual(self.states(q)["R-1-AC-1"]["state"], "verified")

    # -- met only while a test names it, and only through the gate --------------------------------

    def test_FR_G2_AC_3_a_criterion_counts_as_met_only_while_a_test_on_main_names_it_and_a_gate_passed_for_it(self):
        p = self.compiled()
        build_task(p, "T-001", lanes=Lanes(self.tmp / "la", size=1), cell_runner=good_cell,
                   verifier_runner=no_findings)
        before = self.states(p)
        self.assertEqual(before["R-1-AC-1"]["state"], "verified")
        self.assertEqual(before["R-1-AC-1"]["evidence"][0]["tests"], [GOOD_NAME])
        self.assertEqual(before["R-2-AC-1"]["state"], "not_measured")

        # A test pushed past the gate names R-2-AC-1: claimed, never verified.
        self.push_to_main(p, "claim", lambda w: Path(w, "tests", "test_loans.py").write_text(
            LOANS_TEST, encoding="utf-8", newline="\n"))
        claimed = self.states(p)["R-2-AC-1"]
        self.assertEqual(claimed["state"], "claimed")
        self.assertEqual(claimed["evidence"][0]["tests"], ["test_R_2_AC_1_loan_without_approver_is_refused"])
        self.assertIn("no passing gate", claimed["evidence"][0]["why"])

        # The test that verified R-1-AC-1 leaves main: the passing gate in the ledger no longer counts.
        self.push_to_main(p, "drop", lambda w: _git(w, "rm", "-q", "tests/test_items.py"))
        self.assertEqual(len([r for r in p.ledger().of_kind("gate") if r["event"]["payload"]["verdict"] == "passed"]),
                         1)
        after = self.states(p)["R-1-AC-1"]
        self.assertEqual((after["state"], after["evidence"]), ("not_measured", []))


if __name__ == "__main__":
    unittest.main()
