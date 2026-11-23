import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, lazy_cell, model, no_findings  # noqa: E402

from kernel.compile import compile_project  # noqa: E402
from kernel.dashboard import activity, coverage, gate_trend, pipeline, queue, timeline  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class DashboardTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.built = self.new(mode="assume", title="Built")
        intake(self.built, IDEA, model=model(), requested_by="Aino")
        make_spec(self.built, model=model())
        compile_project(self.built)
        lanes = Lanes(self.tmp / "lanes", size=1)
        build_task(self.built, "T-001", lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings)
        self.clock.advance(minutes=70)
        build_task(self.built, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        self.waiting = self.new(mode="mixed", title="Waiting")
        intake(self.waiting, IDEA, model=model(), requested_by="Aino")
        self.clock.advance(hours=3)

    def test_FR_M3_AC_6_dashboard_read_models_answer_each_widgets_question_from_the_records(self):
        pipe = pipeline(self.factory)
        self.assertEqual(pipe["total"], 2)
        self.assertEqual([b["band"] for b in pipe["bands"]], ["Decide", "Shape", "Deliver", "Run"])
        self.assertEqual(pipe["bands"][0]["count"], 1)                       # the waiting project, stage 2
        self.assertEqual(pipe["bands"][2]["count"], 1)                       # the built project, stage 5
        q = queue(self.factory)
        self.assertEqual(q["by_kind"], {"question": 1, "escalation": 1})
        self.assertGreaterEqual(q["oldest_hours"], 3.0)
        self.assertEqual(q["items"][0]["age_hours"], q["oldest_hours"])      # oldest first
        trend = gate_trend(self.factory)
        self.assertEqual(trend["rounds"], 3)                                  # 1 passed + 2 lazy rounds
        self.assertEqual(len(trend["series"]), 2)                             # two different hours
        self.assertAlmostEqual(trend["pass_rate"], 1 / 3)
        tl = timeline(self.built)
        t1 = next(t for t in tl["tasks"] if t["task"] == "T-001")
        self.assertEqual((len(t1["rounds"]), t1["rounds"][0]["verdict"]), (1, "passed"))
        self.assertTrue(t1["merged_at"])
        t2 = next(t for t in tl["tasks"] if t["task"] == "T-002")
        self.assertEqual(len(t2["rounds"]), 2)
        self.assertTrue(t2["escalated_at"])
        acts = activity(self.factory)
        self.assertTrue(any(a["actor"]["type"] == "agent" and a["actor"]["name"] == "builder" for a in acts))
        self.assertEqual(acts, sorted(acts, key=lambda a: a["at"] or "", reverse=True))
        cov = coverage(self.factory)
        self.assertEqual(len(cov["projects"]), 1)                             # only the compiled project
        self.assertEqual(cov["projects"][0]["verified"], 1)
        self.assertIsNotNone(cov["proven_share"])

    def test_FR_M3_AC_6_an_empty_factory_says_not_measured_never_zero(self):
        from kernel.store import Factory

        empty = Factory(self.tmp / "empty", clock=self.clock)
        self.assertIsNone(gate_trend(empty)["pass_rate"])
        self.assertIsNone(queue(empty)["oldest_hours"])
        self.assertIsNone(coverage(empty)["proven_share"])
        self.assertEqual(pipeline(empty)["total"], 0)


if __name__ == "__main__":
    unittest.main()
