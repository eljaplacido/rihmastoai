import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from adapters.gnomon_ingest import ingest  # noqa: E402
from kernel.projections import cell, floor  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "gnomon"
PRICES = {"models": {"deepseek-v4-pro": {"input": 1.0, "output": 2.0}}}


class ProjectionsTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.record = json.loads((FIX / "analyst-run.record.json").read_text(encoding="utf-8"))
        self.trail = FIX / "analyst-run.jsonl"

    def test_FR_M3_AC_1_the_cell_projection_lists_each_runs_identity_verdict_chain_and_cost(self):
        p = self.new()
        ingest(p, dict(self.record, verify="passed"), self.trail, task="T-001", round_no=0, prices=PRICES)
        rows = cell(p)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["run"], self.record["session"])
        self.assertEqual((r["role"], r["model"], r["verdict"]), ("analyst", "deepseek-v4-pro", "passed"))
        self.assertEqual(r["native"]["verify"], "passed")
        self.assertEqual(r["surface_hash"], self.record["surface_hash"])
        self.assertTrue(r["chain"]["intact"])
        self.assertTrue(r["cost"]["measured"])
        self.assertAlmostEqual(r["cost"]["amount"], (2366 * 1.0 + 7564 * 2.0) / 1_000_000)

    def test_FR_M3_AC_2_the_floor_counts_by_phase_and_verdict_and_never_averages_not_measured(self):
        p = self.new()
        ingest(p, dict(self.record, verify="passed"), self.trail, prices=PRICES)
        ingest(p, dict(self.record, verify="failed"), self.trail, prices=PRICES)
        ingest(p, dict(self.record), self.trail, prices=PRICES)                       # no verify: not measured
        ingest(p, dict(self.record, bucket="apparatus_failure", code=10), self.trail, prices=PRICES)
        f = floor(self.factory)
        self.assertEqual(f["by_phase"]["1 need and decision"],
                         {"passed": 1, "failed": 1, "not measured": 2})
        self.assertEqual(f["overall"]["rate"], 0.5)                                  # 1 of 2 measured
        self.assertEqual(f["overall"]["not_measured"], 1)
        self.assertEqual(f["overall"]["apparatus_failures"], 1)
        tmp = self.tmp / "t.jsonl"
        shutil.copy(self.trail, tmp)
        self.assertEqual(f["spend"]["unmeasured_runs"], 0)

    def test_FR_M3_AC_4_the_floor_headline_is_the_gates_judgement_not_the_harness_outcome(self):
        from factory_fakes import good_cell, lazy_cell, model, no_findings

        from kernel.compile import compile_project
        from kernel.dispatch import build_task
        from kernel.intake import intake
        from kernel.lanes import Lanes
        from kernel.spec import make_spec

        p = self.new(mode="assume")
        intake(p, "Our team keeps losing track of who borrowed the drills.", model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        lanes = Lanes(self.tmp / "lanes", size=1)
        build_task(p, "T-001", lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings)
        build_task(p, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        ingest(p, dict(self.record), self.trail, prices=PRICES)       # a harness outcome: not measured
        f = floor(self.factory)
        self.assertEqual(f["gates"]["tasks_gated"], 2)
        self.assertEqual(f["gates"]["first_round_passed"], 1)
        self.assertEqual(f["gates"]["first_round_rate"], 0.5)
        self.assertEqual((f["gates"]["merged"], f["gates"]["escalated"]), (1, 1))
        self.assertEqual(f["overall"]["not_measured"], 1)               # counted beside, not instead
        self.assertIn("the gate judges the work", f["harness_note"])


if __name__ == "__main__":
    unittest.main()
