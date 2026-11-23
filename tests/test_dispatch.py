import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, lazy_cell, model, no_findings  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.gate import run_suite  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class DispatchTest(FactoryTestCase):
    def compiled(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def test_FR_G1_AC_1_a_task_merges_only_warranted_and_permitted_at_one_revision(self):
        p = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        out = build_task(p, "T-001", lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings)
        self.assertEqual(out["status"], "merged")
        gate = out["rounds"][-1]["gate"]
        self.assertTrue(gate["warranted"])
        self.assertEqual({s["name"]: s["verdict"] for s in gate["signals"]},
                         {"tests": "passed", "trace": "passed", "fail_first": "passed", "verifier": "passed"})
        merged = [r["event"]["payload"] for r in p.ledger().of_kind("merged")]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["revision"], gate["head"])          # warranted at this revision
        self.assertTrue(merged[0]["permitted_by"].startswith("policy:"))  # permitted, recorded
        main = _git(p.path("repo.git"), "rev-parse", "main")
        self.assertEqual(main, gate["head"])                            # and that revision is main
        work = self.tmp / "check"
        _git(self.tmp, "clone", "-q", str(p.path("repo.git")), "check")
        self.assertEqual(run_suite(work)["exit"], 0)

    def test_FR_G8_AC_1_a_task_that_keeps_failing_escalates_with_every_objection(self):
        p = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        out = build_task(p, "T-001", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        self.assertEqual(out["status"], "escalated")
        self.assertEqual(len(out["rounds"]), 2)
        card = Canon(p).get_card(out["card"])
        self.assertEqual(card["kind"], "escalation")
        self.assertTrue(card["blocking"])
        objections = card["payload"]["objections"]
        self.assertTrue(any(o.startswith("fail_first:") for o in objections), objections)
        self.assertIn("R-1", card["refs"]["requirements"])
        main_before = _git(p.path("repo.git"), "log", "--oneline", "main")
        self.assertEqual(len(main_before.splitlines()), 1)  # nothing reached main


if __name__ == "__main__":
    unittest.main()
