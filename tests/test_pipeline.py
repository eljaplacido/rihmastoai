import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, model, no_findings  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.pipeline import advance  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class PipelineTest(FactoryTestCase):
    def test_FR_N2_AC_1_an_idea_goes_to_a_built_product_and_stops_at_human_gates(self):
        p = self.new(mode="mixed", maturity="explore")
        intake(p, IDEA, model=model(), requested_by="Aino")
        lanes = Lanes(self.tmp / "lanes", size=1)
        kwargs = dict(model=model(), lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings,
                      deliver_kwargs={})
        first = advance(p, **kwargs)
        self.assertEqual(first["state"], "waiting")          # the blocking business question
        self.assertEqual(first["stage"], 2)
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        second = advance(p, **kwargs)
        self.assertNotEqual(second["state"], "failed", second)
        tasks = p.read("tasks.json")
        self.assertEqual({s["status"] for s in tasks.values()}, {"merged"})
        self.assertTrue(p.meta["built"])
        self.assertTrue(p.ledger().verify(head=p.ledger().head()).intact)


if __name__ == "__main__":
    unittest.main()
