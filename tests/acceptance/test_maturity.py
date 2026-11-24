"""The maturity columns: explore, demo, pilot and production (docs/acceptance.md; FR-AM4).

Maturity is today's lever from a rough demo to production-ready. The postures (prototype, balanced,
production, regulated) are being built in another stream; their cells are pending in
docs/acceptance.md with the criteria they must meet.
"""

from kernel import demo
from kernel.deliver import delivery_plan, latest_release

from .scripts import IT, OWNER, AcceptanceCase, payloads

PRODUCTION_CARDS = [("approval", "business_owner"), ("validation", "business_owner"), ("deploy_gate", "it")]


class MaturityTest(AcceptanceCase):
    def test_FR_AM4_AC_1_one_need_at_each_maturity_lands_where_the_maturity_says_after_the_people_it_names(self):
        """Explore and pilot here; demo is G1.demo (test_greenfield.py) and production the one-line need's
        production cell below."""
        landed = {}
        for maturity, env, cards in (("explore", "preview", []), ("pilot", "staging", PRODUCTION_CARDS[:2])):
            with self.subTest(maturity=maturity):
                p = self.need("rooms", mode="mixed", maturity=maturity)
                self.answer_blocking(p)
                out, decided = self.ship(p)
                self.assertEqual(decided, cards)
                self.assertDelivered(p, out, env)
                rel = latest_release(p)
                self.assertEqual([s["step"] for s in rel["steps"]], delivery_plan(maturity))
                landed[maturity] = (p.meta["stage"], len(p.read("spec.json")["requirements"]),
                                    [d["what"] for d in p.read("spec.json").get("dropped", [])])
        # explore keeps three requirements and records the fourth as dropped
        self.assertEqual(landed, {"explore": (6, 3, ["requirement"]), "pilot": (6, 4, [])})

    def production(self, key: str, *, mode: str = "mixed", cell=None, requested_by: str = OWNER[0]):
        p = self.need(key, mode=mode, maturity="production", requested_by=requested_by)
        out, decided = self.ship(p, cell)
        self.assertEqual([d for d in decided if d[0] != "question"], PRODUCTION_CARDS)
        pack = self.assertDelivered(p, out, "production")
        rel = latest_release(p)
        self.assertEqual([s["step"] for s in rel["steps"]], delivery_plan("production"))
        steps = {s["step"]: s for s in rel["steps"]}
        self.assertEqual(steps["canary:production"]["native"]["decision"], "promote")
        self.assertEqual(steps["deploy_gate"]["native"]["persona"], "it")
        self.assertEqual(p.meta["stage"], 7)
        self.assertTrue(p.meta.get("plan_approved"))
        self.assertTraced(p)
        gate = next(d for d in payloads(p, "decision") if d["kind"] == "deploy_gate")
        self.assertEqual((gate["person"], gate["persona"]), IT)
        return p, pack

    def test_FR_AM4_AC_2_the_one_line_need_reaches_production(self):
        self.production("rooms")

    def test_FR_AM4_AC_2_the_two_line_vague_need_reaches_production(self):
        self.production("queue")

    def test_FR_AM4_AC_2_the_written_spec_reaches_production(self):
        self.production("visitors")

    def test_FR_AM4_AC_2_the_finnish_need_reaches_production(self):
        self.production("reports")

    def test_FR_AM4_AC_2_the_workflow_reaches_production(self):
        self.production("purchases")

    def test_FR_AM4_AC_2_the_automation_reaches_production(self):
        self.production("invoices", mode="assume")

    def test_FR_AM4_AC_2_the_assistant_reaches_production(self):
        self.production("travel")

    def test_FR_AM4_AC_2_the_ops_agent_reaches_production(self):
        self.production("access", mode="assume", requested_by="Sanna")

    def test_FR_AM4_AC_2_the_integration_reaches_production(self):
        self.production("webhook", mode="assume", cell=demo.ScriptedCell(demo.WEBHOOK, self.clock),
                        requested_by="Pekka")
