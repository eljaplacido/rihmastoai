"""The IT persona's acceptance run (2026-11-26), automations: what "Describe it" reads, what a test run does on a
built project, an assessment and a chosen Gnomon eval on a schedule, and one incident per failed run.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import automation_compose as compose  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel import automations_actions as acts  # noqa: E402
from kernel import automations_text as words  # noqa: E402
from kernel import heal_wiring  # noqa: E402
from kernel import incidents as inc  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "cockpit" / "static"
OWNER = {"person": "Ilkka Example", "persona": "it"}


class DescribeItTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Shipment webhook")          # built here: neither attached nor adopted

    def draft(self, text):
        return compose.compose(self.factory, text, project=self.p)

    def test_running_the_tests_of_a_built_project_is_the_health_test_suite_check(self):
        out = self.draft("every night run the tests and tell me on Teams if they fail")
        self.assertEqual(out["draft"]["action"], {"kind": "run_check", "check": "tests"})
        self.assertTrue(out["ok"], out)
        self.assertIn("Test suite", out["summary"])

    def test_a_command_action_on_a_built_project_says_why_instead_of_a_raw_error(self):
        a = {"id": "AU-001", "action": {"kind": "command"}, "owner": OWNER}
        out = acts._command(self.factory, a, {"project": self.p.pid}, None)
        self.assertEqual(out["outcome"], "refused")
        self.assertIn("Test suite", out["detail"])
        self.assertNotIn("neither an attached nor an adopted", out["detail"])

    def test_every_15_minutes_probe_keeps_its_schedule_and_probes_every_15m(self):
        out = self.draft("every 15 minutes probe production and open an incident if it fails")
        d = out["draft"]
        self.assertEqual(d["trigger"], {"kind": "schedule", "every": "15m"})
        self.assertEqual(d["action"], {"kind": "probe", "environment": "production", "every": "15m"})
        self.assertTrue(out["ok"], out)

    def test_an_assessment_and_a_named_gnomon_eval_can_be_scheduled(self):
        out = self.draft("every monday run the assessment again")
        self.assertEqual(out["draft"]["action"], {"kind": "run_assessment"})
        self.assertTrue(out["ok"], out)
        self.assertIn("assess", out["summary"])
        out = self.draft("run the gnomon eval on the project's own tasks every day")
        self.assertEqual(out["draft"]["action"], {"kind": "run_eval", "eval": "eval"})
        self.assertIn("Eval on the project's own tasks", out["summary"])
        self.assertIn("Security posture", words.action({"kind": "run_eval", "eval": "security"}))
        self.assertIn("run_assessment", au.ACTIONS)

    def test_the_builder_chooses_the_eval_and_the_check(self):
        js = (STATIC / "automations.js").read_text(encoding="utf-8")
        self.assertIn('"data-show": "action:run_eval"', js)
        self.assertIn('"data-show": "action:run_check"', js)
        self.assertIn('val("amn-a-eval")', js)
        from cockpit.automation_routes import AutomationRoutes

        offers = AutomationRoutes._offers(type("A", (AutomationRoutes,), {"factory": self.factory})())
        self.assertIn({"id": "eval", "label": "Eval on the project's own tasks"}, offers["evals"])
        self.assertIn("tests", {c["id"] for c in offers["checks"]})


class OneIncidentPerRunTest(FactoryTestCase):
    def test_a_failed_run_recorded_in_both_ledgers_opens_one_incident(self):
        p = self.new(title="Shipment webhook")
        run = {"id": "AU-001", "action": "command", "outcome": "failed", "detail": "boom", "project": p.pid}
        factory_project(self.factory).log("automation_ran", run)
        p.log("automation_ran", run)
        heal_wiring.sweep(self.factory)
        rows = inc.incidents(self.factory)
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["project"], p.pid)


if __name__ == "__main__":
    unittest.main()
