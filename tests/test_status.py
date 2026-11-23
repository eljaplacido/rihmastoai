import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, lazy_cell, model, no_findings  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task, resolve_escalations  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import evidence, health, now  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class StatusTest(FactoryTestCase):
    def compiled(self, title="Loans"):
        p = self.new(mode="assume", title=title)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def test_FR_A6_AC_5_questions_offer_options_with_the_proposal_first(self):
        p = self.new(mode="socratic")
        intake(p, IDEA, model=model(), requested_by="Aino")
        q1 = Canon(p).question("Q-001")
        self.assertEqual(q1["options"], ["the team lead approves", "any team member", "the IT desk", "a fourth"])
        q2 = Canon(p).question("Q-002")
        self.assertEqual(q2["options"], ["fewer lost items per month"])     # no options given: the proposal alone

    def test_FR_O6_AC_3_each_criterion_shows_verified_claimed_or_not_measured(self):
        p = self.compiled()
        build_task(p, "T-001", lanes=Lanes(self.tmp / "la", size=1), cell_runner=good_cell, verifier_runner=no_findings)
        ev = {e["criterion"]: e for e in evidence(p)}
        self.assertEqual(ev["R-1-AC-1"]["state"], "verified")
        self.assertEqual(ev["R-1-AC-1"]["evidence"][0]["tests"], ["test_R_1_AC_1_post_item_returns_201_with_id"])
        self.assertEqual(ev["R-1-AC-2"]["state"], "not_measured")            # a holdout no release has run
        self.assertEqual(ev["R-2-AC-1"]["state"], "not_measured")            # no test names it
        q = self.compiled("Loans B")
        esc_ = build_task(q, "T-001", lanes=Lanes(self.tmp / "lb", size=1), cell_runner=lazy_cell,
                          verifier_runner=no_findings, max_rounds=0)
        Canon(q).decide(esc_["card"], "accept_as_is", person="Aino", persona="business_owner")
        resolve_escalations(q)
        claimed = {e["criterion"]: e for e in evidence(q)}["R-1-AC-1"]
        self.assertEqual(claimed["state"], "claimed")                         # merged, but no gate proved it

    def test_FR_T1_AC_4_the_project_says_in_one_line_what_it_is_doing(self):
        p = self.new(mode="mixed")
        intake(p, IDEA, model=model(), requested_by="Aino")
        n = now(p)
        self.assertEqual(n["state"], "waiting_on_you")
        self.assertIn("question", n["line"])
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        compile_project(p)
        p.write("tasks.json", {"T-002": {"status": "building", "rounds": [{"round": 0}]}})
        n = now(p)
        self.assertEqual(n["state"], "working")
        self.assertIn("Building T-002", n["line"])
        self.assertIn("repair round 1", n["line"])
        p.write("tasks.json", {})
        p.write("releases/1.json", {"number": 1, "state": "done", "maturity": "demo"})
        self.assertEqual(now(p)["state"], "done")
        p.update_meta(halted=True)
        self.assertEqual(now(p)["state"], "failed")

    def test_FR_T1_AC_5_health_names_its_reasons_and_forecasts_from_history(self):
        p = self.compiled()
        h = health(p)
        self.assertEqual(h["status"], "on_track")
        self.assertIn("not measured", h["forecast"]["basis"])
        self.assertIsNone(h["forecast"]["eta_minutes"])
        lanes = Lanes(self.tmp / "lanes", size=1)
        build_task(p, "T-001", lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings)
        h = health(p)
        self.assertEqual(h["forecast"]["tasks_left"], 3)
        self.assertEqual(h["forecast"]["basis"], "1 merged task(s) in this project")
        esc_ = build_task(p, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=0)
        h = health(p)
        self.assertEqual(h["status"], "at_risk")
        self.assertTrue(any(esc_["card"] in r for r in h["reasons"]))
        Canon(p).decide(esc_["card"], "stop", person="Aino", persona="business_owner")
        resolve_escalations(p)
        self.assertEqual(health(p)["status"], "off_track")


if __name__ == "__main__":
    unittest.main()
