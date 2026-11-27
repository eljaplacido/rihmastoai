"""The IT persona's acceptance run (2026-11-26): each problem it found, held by a test that failed before its fix.

Kernel-level, over a fresh home per test (tests/factory_fakes.py); nothing reaches a network.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import destinations, destinations_cli, destinations_feedback  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "cockpit" / "static"
IT = ("Ilkka Example", "it")


class DeliverToTestTest(FactoryTestCase):
    """Deliver to test on an explore project reprinted an old preview release and said it had started."""

    def test_preview_is_development_and_a_plan_without_test_refuses_with_how_to_add_one(self):
        p = self.new(title="Shipment webhook", maturity="explore")
        self.assertEqual(destinations.tier("preview"), "development")      # as D-0026 places it
        self.assertEqual(destinations.tier("staging"), "test")
        with self.assertRaises(ValueError) as cm:
            destinations_cli.request_delivery(p, to="test", person=IT[0], persona=IT[1])
        self.assertIn("no test environment", str(cm.exception))
        self.assertIn("pilot", str(cm.exception))
        self.assertEqual(p.ledger().of_kind("destination_delivery_requested"), [])
        (deliver,) = [a for a in destinations._deploy_actions(p, "preview", ["preview"], None, None, None)
                      if a["id"] == "deliver"]
        self.assertIn("no test environment", deliver["disabled"])

    def test_a_pilot_plan_delivers_to_staging(self):
        p = self.new(title="Shipment webhook", maturity="pilot")
        rec = destinations_cli.request_delivery(p, to="test", person=IT[0], persona=IT[1])
        self.assertEqual(rec["environments"], ["staging"])


class CheckNowWordsTest(unittest.TestCase):
    """Check now said "nothing is failing" while the page said it runs nowhere."""

    def view(self, *states):
        return {"summary": {"failing": []},
                "groups": {"deployed": [{"label": f"Preview {i}", "state": s} for i, s in enumerate(states)]}}

    def test_nothing_running_is_not_measured(self):
        said, tone = destinations_feedback.said_of(self.view("configured"))
        self.assertTrue(said.startswith("Not measured: it runs nowhere yet"), said)
        self.assertEqual(tone, "warning")
        said, tone = destinations_feedback.said_of(self.view("healthy"))
        self.assertEqual((said, tone), ("Checked: nothing is failing (Preview 0).", "good"))
        js = (STATIC / "destinations.js").read_text(encoding="utf-8")
        self.assertNotIn("Checked: nothing is failing", js)
        self.assertIn("say(out.said, out.tone)", js)


class RunNowShowsRunningTest(FactoryTestCase):
    """Run now left the row at Not run yet while its job ran; Incidents needed a reload to show a new one."""

    def test_a_requested_eval_reads_as_running_until_it_is_carried_out(self):
        from kernel import gnomon_evals_run as gr
        from kernel import gnomon_evals_view as gv

        p = self.new(title="Shipment webhook")
        gr.request(p, "security", person=IT[0], persona=IT[1])
        row = next(e for e in gv.project_view(p)["evals"] if e["id"] == "security")
        self.assertTrue(row["running"])

    def test_the_views_read_again_while_a_run_goes_on_and_while_incidents_are_open(self):
        evals = (STATIC / "evals.js").read_text(encoding="utf-8")
        self.assertIn("data.evals.some((e) => e.running)", evals)
        heal = (STATIC / "heal.js").read_text(encoding="utf-8")
        self.assertIn("keepFresh(box, null)", heal)
        self.assertIn("keepFresh(root, p.meta.id)", heal)


class FailingCheckCase(FactoryTestCase):
    """An Integration or connector project whose custom check failed, swept into its incident."""

    def setUp(self):
        super().setUp()
        from kernel import heal_wiring
        from kernel.checks import store as cstore

        self.p = self.new(title="Shipment webhook")
        self.p.update_meta(profile="integration")
        entry = cstore.enable(self.p, "custom", person=IT[0], persona=IT[1], config={"command": "exit 3"})
        cstore.record(self.p, "custom", entry, {"verdict": "failed", "summary": "exit 3", "evidence": []},
                      person=IT[0], persona=IT[1], via="person")
        heal_wiring.sweep(self.factory)


class HealthAnswersTest(FailingCheckCase):
    """Ask Rihma described views ("Projects shows every project...") instead of the project's real state."""

    def ask(self, q):
        from kernel.assistant import ask

        return ask(self.factory, q, persona="it", project_id=self.p.pid)

    def test_health_and_failures_name_the_check_the_incident_and_the_next_step(self):
        from kernel import incidents as inc

        (i,) = inc.incidents(self.factory, pid=self.p.pid)
        for q in ("Is this project healthy?", "What failed and what should I do?"):
            out = self.ask(q)
            self.assertIn("Custom check failed (exit 3)", out["answer"], q)
            self.assertIn(i["id"], out["answer"], q)
            self.assertIn("Next step:", out["answer"], q)
            self.assertNotIn("Projects shows every project", out["answer"])
            self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/incidents")

    def test_checks_are_suggested_for_the_solution_type(self):
        out = self.ask("What checks should this project have?")
        self.assertIn("Integration or connector", out["answer"])
        self.assertIn("HTTP probe", out["answer"])
        from kernel.checks import health as chealth

        rec = chealth.project_health(self.p)["recommended"]
        self.assertEqual((rec["label"], rec["kinds"][:2]), ("Integration or connector", ["tests", "probe"]))
        self.assertIn("recommended for", (STATIC / "health.js").read_text(encoding="utf-8"))

    def test_why_an_automation_failed_reads_its_runs(self):
        from kernel.learn import factory_project

        factory_project(self.factory).log("automation_ran", {"id": "AU-001", "action": "command", "outcome": "failed",
                                                             "detail": "the suite exited 2", "project": self.p.pid})
        out = self.ask("Why did AU-001 fail?")
        self.assertIn("AU-001 (command) failed", out["answer"])
        self.assertIn("the suite exited 2", out["answer"])
        self.assertNotIn("I did it", out["answer"])


class IncidentClaimsTest(FailingCheckCase):
    """"This fixed it" closed an incident whose check still failed; a remedy's claims did not match what it does."""

    def test_a_failed_checks_incident_is_not_closed_while_the_check_still_fails(self):
        from kernel import immune
        from kernel import incidents as inc

        (i,) = inc.incidents(self.factory, pid=self.p.pid)
        how = {"kind": "explain", "text": "fixed the script", "label": "Fixed the script"}
        with self.assertRaises(inc.IncidentRefused) as cm:
            inc.resolve(self.factory, i["id"], how=how, person=IT[0], persona=IT[1], note="fixed the script")
        self.assertIn("still fails", str(cm.exception))
        done = inc.resolve(self.factory, i["id"], how=how, person=IT[0], persona=IT[1], note="known flake",
                           anyway=True)
        self.assertEqual(done["state"], "fixed")
        self.assertEqual(immune.classify(i)["id"], "check_failed")
        self.assertEqual(immune.classify(i)["classification"], "project bug")

    def test_the_remedy_says_what_it_does_and_investigate_is_not_offered_twice(self):
        js = (STATIC / "heal.js").read_text(encoding="utf-8")
        self.assertNotIn("safe: applied on its own once approved", js)
        self.assertIn('if (a.kind === "explain") return "shows what fixed it last time: a person does it"', js)
        self.assertIn('.filter((a) => a.kind !== "investigate")', js)
        self.assertIn("anyway: warned", js)


class DemoHomeStaysHomeTest(FactoryTestCase):
    """A demo home showed the checkout's routing (opencode.ai, data goes out), the machine's lanes, and would probe."""

    def setUp(self):
        super().setUp()
        self.factory.home.mkdir(parents=True, exist_ok=True)
        (self.factory.home / "demo.json").write_text('{"schema": 1}', encoding="utf-8")

    def test_the_demo_shows_its_scripted_model_its_own_stores_and_probes_nothing_outside(self):
        import os
        from unittest import mock

        from kernel import data_stores, gnomon_evals, itdata_actions, itdata_project
        from kernel import gnomon_evals_run as gr

        view = itdata_project.platform_view(self.factory)
        (model,) = [x for x in view["items"] if x["kind"] == "model"]
        self.assertEqual((model["id"], model["locality"]), ("model:demo-model", "this machine"))
        lanes = self.tmp / "lanes"
        (lanes / "x").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"GF_LANES": str(lanes)}):
            self.assertNotIn("lanes", {s["store"] for s in data_stores.stores(self.factory)})
        dialled = []
        with mock.patch.object(itdata_actions, "connect", lambda *a, **k: dialled.append(a)):
            itdata_actions.check(self.factory, person=IT[0], persona=IT[1])
        self.assertEqual(dialled, [])
        p = self.new(title="Demo desk")
        doctor = next(e for e in gnomon_evals.public(p) if e["id"] == "doctor")
        self.assertFalse(doctor["available"])
        with self.assertRaises(gr.EvalsRefused):
            gr.request(p, "doctor", person=IT[0], persona=IT[1])


if __name__ == "__main__":
    unittest.main()
