import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import model, no_findings  # noqa: E402
from test_deliver import DeliveryTestCase  # noqa: E402

from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.lanes import _git  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.rulings import apply_rulings, held_reason  # noqa: E402
from kernel.store import write_json  # noqa: E402

BROKEN = {"criterion": "R-1-AC-2", "kind": "holdout", "author_role": "holdout_author",
          "steps": [{"method": "GET", "path": "/items", "expect_status": 200, "expect_contains": "no-such-item-xyz"}]}


class RulingTest(DeliveryTestCase):
    maturity = "demo"

    def setUp(self):
        super().setUp()
        write_json(self.project.holdouts_dir / "R-1-AC-2.json", BROKEN)
        self.project.update_meta(built=True)

    def advance(self):
        return advance(self.project, model=model(), verifier_runner=no_findings)

    def test_FR_H3_AC_2_a_failing_holdout_waits_for_a_persons_ruling_and_a_scenario_defect_is_rewritten(self):
        first = self.advance()
        self.assertEqual(first["state"], "waiting")
        card = Canon(self.project).get_card(first["waiting_on"][0])
        self.assertEqual(card["kind"], "holdout_ruling")
        self.assertEqual(card["refs"]["criteria"], ["R-1-AC-2"])
        with self.assertRaises(DecisionRefused):           # IT does not rule on product behaviour
            self.decide(card["id"], "scenario_defect", "it", person="Jaana")
        self.decide(card["id"], "scenario_defect", "developer", person="Dev",
                    reason="the scenario looked for an item it never created")
        second = self.advance()
        self.assertEqual(second["state"], "waiting")
        waiting = Canon(self.project).get_card(second["waiting_on"][0])
        self.assertEqual(waiting["kind"], "approval")       # the owner's acceptance: holdouts passed
        rewritten = json.loads((self.project.holdouts_dir / "R-1-AC-2.json").read_text(encoding="utf-8"))
        self.assertNotIn("no-such-item-xyz", json.dumps(rewritten))
        self.assertEqual(rewritten["author_role"], "holdout_author")
        events = [r["event"]["payload"] for r in self.project.ledger().of_kind("holdouts_authored")]
        because = events[-1]["reauthored_because"]                 # a pointer: the reason is in the custody
        self.assertEqual((events[-1]["ruled_by"], because["custody"]), ("Dev", "holdout"))
        self.assertEqual(held_reason(self.project, because["sha256"]),
                         "the scenario looked for an item it never created")
        rel = [self.project.read(f"releases/{n}.json") for n in (1, 2)]
        self.assertEqual(rel[0]["revision"], rel[1]["revision"])   # the same revision, delivered again

    def test_FR_H3_AC_2_a_product_defect_goes_back_through_the_change_loop(self):
        first = self.advance()
        card_id = first["waiting_on"][0]
        self.decide(card_id, "product_defect", "product_owner", person="Pekka")
        before = self.project.read("contract.json")["revision"]
        done = apply_rulings(self.project, model=model())
        self.assertEqual(done[0]["verdict"], "product_defect")
        change = Canon(self.project).get_card(done[0]["change"])
        self.assertEqual(change["payload"]["triage"]["class"], "defect")
        self.assertNotEqual(self.project.read("contract.json")["revision"], before)
        self.assertEqual(self.project.read("lessons.json")[-1]["requirement"], "R-1")
        self.assertEqual(self.project.read("tasks.json")["T-001"]["status"], "pending")
        self.assertEqual(apply_rulings(self.project, model=model()), [])   # carried out once

    def test_FR_H2_AC_2_a_release_that_failed_on_a_holdout_keeps_that_criterion_failing(self):
        self.advance()
        rel = self.project.read("releases/1.json")
        kept = {c["criterion"]: c["state"] for c in rel["criteria_at_end"]["criteria"]}
        self.assertEqual((rel["state"], kept["R-1-AC-2"]), ("failed", "failing"))   # the step that ended it counts

    def test_FR_B4_AC_2_a_product_defect_ruling_shows_the_builder_only_that_a_held_out_check_of_its_requirement_failed(self):
        first = self.advance()
        self.decide(first["waiting_on"][0], "product_defect", "product_owner", person="Pekka")
        done = apply_rulings(self.project, model=model())
        contract = self.project.read("contract.json")
        regression = next(c for r in contract["requirements"] for c in r["acceptance"]
                          if c["id"] == "R-1-AC-3")
        self.assertEqual((regression["given"], regression["when"]), ("-", "-"))
        self.assertIn("R-1 holds as its statement says", regression["then"])
        self.assertIn("release 1", regression["then"])
        text = self.envelope_of("T-001", contract)
        self.assertIn("R-1-AC-3", text)                                    # the builder sees the regression
        repo = _git(self.project.path("repo.git"), "show", "main:contract.json")
        change = Canon(self.project).get_card(done[0]["change"])
        held = [json.dumps(BROKEN["steps"][0]["expect_contains"]).strip('"'), "expect_status", "expect_contains"]
        for where, seen in (("envelope", text), ("repository contract", repo), ("contract", json.dumps(contract)),
                            ("lessons", json.dumps(self.project.read("lessons.json"))),
                            ("change card", json.dumps(change))):
            for value in held:
                self.assertNotIn(value, seen, f"the {where} carries what the scenario expected")
        self.assertNotIn("R-1-AC-2", text)                                 # nor names the held-out criterion

    def envelope_of(self, task_id: str, contract: dict) -> str:
        from kernel.dispatch import envelope

        return envelope(self.project, contract, task_id, base=_git(self.project.path("repo.git"), "rev-parse", "main"))


if __name__ == "__main__":
    unittest.main()
