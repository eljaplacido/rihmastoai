import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, model, no_findings  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.change import submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.insight import alignment, change_impact, impact  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class InsightTest(FactoryTestCase):
    def compiled(self, mode="assume"):
        p = self.new(mode=mode)
        intake(p, IDEA, model=model(), requested_by="Aino")
        if mode == "mixed":
            Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def test_FR_P5_AC_2_before_a_change_is_decided_its_impact_is_shown(self):
        p = self.compiled()
        build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=good_cell,
                   verifier_runner=no_findings)
        canon = Canon(p)
        acc = canon.card("validation", "Accept the pilot?", refs={"requirements": ["R-1"]})
        canon.decide(acc["id"], "accept", person="Aino", persona="business_owner")
        card = submit(p, persona="end_user", person="Tester", text="Adding an item with an empty name crashes with 500")
        triage(p, card["id"], model=model())
        before = len(canon.decisions(stale=True))
        out = change_impact(p, card["id"])
        self.assertEqual(out["requirements"], ["R-1"])
        self.assertEqual(out["criteria"], ["R-1-AC-1", "R-1-AC-2"])
        self.assertEqual(out["tests"]["R-1-AC-1"], ["test_R_1_AC_1_post_item_returns_201_with_id"])
        self.assertEqual(out["kinds"], {"R-1-AC-1": "test", "R-1-AC-2": "holdout"})   # a holdout has no visible test by design
        self.assertEqual(out["tasks_reopened"], ["T-001"])
        self.assertEqual([a["card"] for a in out["approvals_going_stale"]], [acc["id"]])
        self.assertEqual(len(Canon(p).decisions(stale=True)), before)    # shown, not done
        self.assertEqual(impact(p, ["R-9"])["unknown_requirements"], ["R-9"])

    def test_FR_S6_AC_1_the_canons_contradictions_are_listed(self):
        p = self.compiled(mode="mixed")
        canon = Canon(p)
        kinds = {f["kind"] for f in alignment(p)}
        self.assertNotIn("assumed_over_dissent", kinds)      # Q-001 has dissent but was answered
        q = canon.add_question("Who repairs broken items?", "operations", opinions={
            "operations": "the IT desk", "business": "the team itself"})
        canon.assume(q["id"], "the IT desk")
        a = canon.assumptions()[-1]
        canon.settle_assumption(canon.assumptions()[0]["id"], confirmed=False, person="Olli", persona="operations",
                                correction="no")
        self.clock.advance(days=30)
        acc = canon.card("validation", "Accept?", refs={"requirements": ["R-2"]})
        canon.decide(acc["id"], "accept", person="Aino", persona="business_owner")
        canon.mark_stale(["R-2"], reason="change C-9")
        found = alignment(p)
        kinds = {f["kind"] for f in found}
        self.assertIn("assumed_over_dissent", kinds)
        self.assertIn("assumption_overdue", kinds)
        self.assertIn("stale_approval", kinds)
        refuted_q = canon.assumptions("refuted")[0]["question"]
        self.assertEqual(refuted_q, "Q-002")                 # the first assumed question in mixed mode
        self.assertIn("Q-002", next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-3")["sources"])
        self.assertIn("rests_on_refuted_assumption", kinds)
        self.assertTrue(any(f.get("requirement") == "R-3" for f in found if f["kind"] == "rests_on_refuted_assumption"))
        self.assertTrue(any(a["id"] in f["text"] for f in found if f["kind"] == "assumption_overdue"))


if __name__ == "__main__":
    unittest.main()
