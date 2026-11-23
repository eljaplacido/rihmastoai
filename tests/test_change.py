import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.change import CLASSES, WAY_BACK, apply_change, submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class ChangeTest(FactoryTestCase):
    def compiled(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def test_FR_I3_AC_1_each_change_gets_one_class_and_a_way_back(self):
        p = self.compiled()
        cases = [("end_user", "Adding an item with an empty name crashes with 500", "defect"),
                 ("product_owner", "The approver should be optional", "change_request"),
                 ("it", "All services must use TLS 1.3 from January", "infra_change")]
        for persona, text, expected in cases:
            card = submit(p, persona=persona, person="Tester", text=text)
            result = triage(p, card["id"], model=model() if persona != "it" else None)
            self.assertIn(result["class"], CLASSES)
            self.assertEqual(result["class"], expected, text)
            self.assertEqual(result["way_back"], WAY_BACK[expected])
            self.assertEqual(Canon(p).get_card(card["id"])["payload"]["triage"]["class"], expected)

    def test_FR_P4_AC_1_a_change_request_waits_for_a_business_decision(self):
        p = self.compiled()
        card = submit(p, persona="product_owner", person="Pekka", text="The approver should be optional")
        triage(p, card["id"], model=model())
        with self.assertRaises(PermissionError):
            apply_change(p, card["id"], model=model())
        Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner", reason="yes, optional")
        out = apply_change(p, card["id"], model=model())
        self.assertEqual(out["changed"], ["R-2"])
        r2 = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        self.assertEqual((r2["provenance"], r2["decided_by"]), ("customer-confirmed", "Aino"))
        self.assertEqual(p.read("tasks.json")["T-002"]["status"], "pending")
        self.assertTrue(p.path("spec.v1.json").exists())

    def test_FR_P5_AC_1_a_change_makes_approvals_resting_on_it_stale(self):
        p = self.compiled()
        canon = Canon(p)
        acc = canon.card("validation", "Accept the pilot?", refs={"requirements": ["R-2", "R-3"]})
        other = canon.card("validation", "Accept the report?", refs={"requirements": ["R-3"]})
        canon.decide(acc["id"], "accept", person="Aino", persona="business_owner")
        canon.decide(other["id"], "accept", person="Aino", persona="business_owner")
        card = submit(p, persona="product_owner", person="Pekka", text="The approver should be optional")
        triage(p, card["id"], model=model())
        canon.decide(card["id"], "accept", person="Aino", persona="business_owner")
        out = apply_change(p, card["id"], model=model())
        stale = {d["card"] for d in Canon(p).decisions(stale=True)}
        self.assertEqual(stale, {acc["id"]})          # rests on R-2, which changed
        self.assertEqual(len(out["stale"]), 1)
        self.assertNotIn(other["id"], stale)           # R-3 did not change

    def test_FR_K2_AC_1_a_defect_closes_only_with_a_regression_criterion_and_a_lesson(self):
        p = self.compiled()
        before = p.read("contract.json")["revision"]
        card = submit(p, persona="end_user", person="Tester", text="Adding an item with an empty name crashes with 500")
        triage(p, card["id"], model=model())
        out = apply_change(p, card["id"], model=model())
        contract = p.read("contract.json")
        r1 = next(r for r in contract["requirements"] if r["id"] == "R-1")
        new = r1["acceptance"][-1]
        self.assertEqual(new["id"], "R-1-AC-3")
        self.assertIn("400", new["then"])
        self.assertNotEqual(contract["revision"], before)
        lessons = p.read("lessons.json")
        self.assertEqual(lessons[-1]["regression_criterion"], "R-1-AC-3")
        self.assertEqual(Canon(p).get_card(card["id"])["state"], "resolved")
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "pending")
        self.assertEqual(out["class"], "defect")

    def test_FR_Q2_AC_1_an_infrastructure_change_becomes_a_road_card_only_it_decides(self):
        from kernel.canon import DecisionRefused

        p = self.compiled()
        card = submit(p, persona="it", person="Ilkka", text="All services must use TLS 1.3 from January")
        triage(p, card["id"])
        out = apply_change(p, card["id"])
        road = Canon(p).get_card(out["road_card"])
        self.assertEqual(road["kind"], "road")
        self.assertEqual(road["refs"]["change"], card["id"])
        with self.assertRaises(DecisionRefused):
            Canon(p).decide(road["id"], "configured", person="Aino", persona="business_owner")
        Canon(p).decide(road["id"], "configured", person="Ilkka", persona="it")
        self.assertEqual(Canon(p).get_card(card["id"])["state"], "resolved")


if __name__ == "__main__":
    unittest.main()
