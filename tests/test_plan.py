import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, model, no_findings, script  # noqa: E402

from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.plan import edit_requirement  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class PlanTest(FactoryTestCase):
    def pilot(self, m=None):
        p = self.new(mode="assume", maturity="pilot")
        intake(p, IDEA, model=model(), requested_by="Aino")
        self.kw = dict(model=m or model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=generic_cell,
                       verifier_runner=no_findings)
        return p

    def test_FR_P7_AC_1_at_pilot_nothing_is_built_until_a_person_approves_the_plan(self):
        p = self.pilot()
        first = advance(p, **self.kw)
        self.assertEqual((first["state"], first["stage"]), ("waiting", 4))
        card = Canon(p).get_card(first["waiting_on"][0])
        self.assertEqual(card["refs"]["scope"], "plan")
        self.assertIn("R-1", card["body"])
        self.assertFalse(p.path("contract.json").exists())                 # nothing compiled, nothing built
        self.assertEqual(advance(p, **self.kw)["waiting_on"], first["waiting_on"])   # one card, not two
        Canon(p).decide(card["id"], "approve", person="Aino", persona="business_owner")
        after = advance(p, **self.kw)
        self.assertNotEqual(after["stage"], 4)
        self.assertTrue(p.path("contract.json").exists())
        self.assertEqual(p.meta["plan_approved"]["by"], "Aino")
        demo = self.new(mode="assume", maturity="demo", title="Demo loans")   # demo: no plan gate by default
        intake(demo, IDEA, model=model(), requested_by="Aino")
        self.assertNotEqual(advance(demo, **dict(self.kw, lanes=Lanes(self.tmp / "l2", size=1)))["stage"], 4)

    def test_FR_P7_AC_2_a_rejected_plan_is_redrawn_with_the_persons_reason(self):
        prompts = []

        def watching(prompt, role):
            prompts.append(prompt)
            return script(prompt, role)

        p = self.pilot(FakeModel(watching))
        first = advance(p, **self.kw)
        Canon(p).decide(first["waiting_on"][0], "reject", person="Aino", persona="business_owner",
                        reason="Drop the benefit report; add who approved each loan.")
        second = advance(p, **self.kw)
        self.assertEqual(second["state"], "waiting")
        self.assertNotEqual(second["waiting_on"], first["waiting_on"])     # a new card for the new plan
        redo = [x for x in prompts if "You turn a brief into a software specification" in x][-1]
        self.assertIn("Drop the benefit report", redo)
        self.assertIn("did not approve", redo)
        self.assertTrue(p.path("spec.v1.json").exists())

    def test_FR_P7_AC_3_a_person_edits_a_requirement_before_approving_and_owns_it(self):
        p = self.pilot()
        first = advance(p, **self.kw)
        with self.assertRaises(DecisionRefused):
            edit_requirement(p, "R-2", person="factory", persona="business_owner", statement="x")
        with self.assertRaises(DecisionRefused):
            edit_requirement(p, "R-2", person="Ilkka", persona="it", statement="x")
        req = edit_requirement(p, "R-2", person="Pekka", persona="product_owner",
                               statement="A loan records who approved it.",
                               acceptance=[{"given": "an item", "when": "POST /items/{id}/loan with approver",
                                            "then": "201 and the approver is stored", "kind": "test"}])
        self.assertEqual((req["provenance"], req["decided_by"]), ("customer-confirmed", "Pekka"))
        self.assertEqual(Canon(p).get_card(first["waiting_on"][0])["state"], "withdrawn")
        second = advance(p, **self.kw)
        self.assertNotEqual(second["waiting_on"], first["waiting_on"])     # reissued for the edited plan
        self.assertIn("A loan records who approved it.", Canon(p).get_card(second["waiting_on"][0])["body"])
        Canon(p).decide(second["waiting_on"][0], "approve", person="Aino", persona="business_owner")
        advance(p, **self.kw)
        with self.assertRaises(DecisionRefused):                           # after approval: the change loop
            edit_requirement(p, "R-2", person="Pekka", persona="product_owner", statement="y")


if __name__ == "__main__":
    unittest.main()
