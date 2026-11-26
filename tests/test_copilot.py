"""FR-CPL1: goal help in a project. A goal in a person's words gets a plan from the project's records and what this
Rihmasto can do, with honest gaps; every step is one allowed action, and planning writes nothing."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel import copilot  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.assistant_rules import route_ok, ui_map  # noqa: E402
from kernel.copilot_catalog import catalogue  # noqa: E402
from kernel.copilot_steps import STEP_KINDS  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.roads import SCHEMA  # noqa: E402
from kernel.store import write_json  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
DRIVE = "I want to hook this solution to Google Drive"
GOALS = {  # a goal in English or Finnish, and what it is
    DRIVE: ["connect"], "Haluan kytkeä tämän Google Driveen": ["connect"],
    "Run it every night in our cloud": ["cloud", "schedule"], "Aja tämä joka yö pilvessä": ["cloud", "schedule"],
    "Deploy it to test": ["test_env"], "Julkaise testiympäristöön": ["test_env"],
    "Add sign-in": ["sign_in"], "Lisää kirjautuminen": ["sign_in"],
    "Monitor it and alert us": ["monitor"], "Valvo tätä": ["monitor"],
    "Give this to my coding agent": ["handoff"], "Anna tämä Claudelle": ["handoff"],
}


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class Scripted:
    """An assistant model that answers with what it is given, and counts its calls."""

    def __init__(self, answer: dict):
        self.answer, self.calls = answer, []

    def ask(self, prompt: str, *, role: str) -> str:
        self.calls.append((role, prompt))
        return "```json\n" + json.dumps(self.answer) + "\n```"


class GoalCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Invoice archive")
        intake(self.p, IDEA, model=model(), requested_by="Aino")
        self.p.update_meta(source_kind="adopted", intent="improve")

    def checked(self, plan: dict) -> None:
        controls = {c["id"] for c in ui_map()["controls"]}
        for s in plan["steps"]:
            self.assertIn(s["action"]["kind"], STEP_KINDS, s)
            if s["action"].get("route"):
                self.assertTrue(route_ok(s["action"]["route"], self.factory), s)
            if s["action"].get("control"):
                self.assertIn(s["action"]["control"], controls, s)
            if s["action"].get("command"):
                self.assertTrue(s["action"]["command"].startswith("rihmasto "), s)
            self.assertTrue(s["available"] or s["why_not"], s)


class RulesTest(GoalCase):
    def test_FR_CPL1_AC_1_goals_are_recognised_without_a_model_and_the_drive_plan_maps_to_real_actions(self):
        for goal, found in GOALS.items():
            self.assertEqual(copilot.intents(goal), found, goal)
            self.assertTrue(copilot.asks_goal(goal), goal)
        self.assertEqual(copilot.agent_named("Anna tämä Claudelle"), "claude-code")
        home = self.factory.home
        before = tree(home)
        plan = copilot.plan(self.factory, self.p, DRIVE)
        self.assertEqual(tree(home), before)                                    # planning writes nothing
        self.assertEqual(plan["by"], "rules")
        kinds = [s["action"]["kind"] for s in plan["steps"]]
        self.assertEqual(kinds[0], "draft_change")
        draft = plan["steps"][0]["action"]["text"]
        self.assertIn(DRIVE, draft)
        self.assertIn("Read only, or does the product also write back?", draft)
        self.assertEqual(plan["gaps"], [])           # the Google Drive integration kind is here (FR-GDR1)
        titles = [s["title"] for s in plan["steps"]]
        self.assertIn("Declare the Google Drive integration", titles)
        self.assertIn("Choose where it runs in production", titles)               # the deployment road
        self.assertIn("Keep Google Drive in sync on a schedule", titles)           # the schedule automation
        self.assertEqual(kinds[-1], "handoff")
        self.assertIn("automation", kinds)
        self.assertIn("adopted project", plan["answer"])
        self.checked(plan)
        for goal in GOALS:
            self.checked(copilot.plan(self.factory, self.p, goal))
        self.assertEqual(tree(home), before)

    def test_FR_CPL1_AC_2_the_catalogue_is_read_at_run_time_roads_connectors_and_what_this_build_lacks(self):
        write_json(self.factory.paved_roads_path, {"schema": SCHEMA, "roads": {
            "team-docker": {"kind": "docker", "configured": True, "environments": ["staging", "production"]}}})
        cat = catalogue(self.factory, self.p)
        self.assertEqual(cat["roads"]["configured"], ["team-docker"])
        self.assertIn("postgres", {c["system"] for c in cat["connectors"]})
        self.assertEqual(next(c for c in cat["connectors"] if c["system"] == "postgres")["state"], "off")
        plan = copilot.plan(self.factory, self.p, "We need to connect it to our Postgres database")
        steps = {s["title"]: s for s in plan["steps"]}
        self.assertEqual(plan["gaps"], [])                                       # Postgres has a connector
        enable = steps["IT turns on the PostgreSQL (read-only) connector"]
        self.assertIn("rihmasto connector enable postgres", enable["action"]["command"])
        self.assertEqual(enable["who"], "it")
        self.assertIn("--kind postgres", steps["Declare the PostgreSQL integration"]["action"]["command"])
        road = steps["Choose where it runs in production"]
        self.assertTrue(road["available"])
        self.assertIn("team-docker (docker)", road["detail"])
        sync = steps["Keep PostgreSQL in sync on a schedule"]
        self.assertEqual(sync["available"], cat["automations"]["available"])   # a stream not merged is said so
        if not sync["available"]:
            self.assertIn("not in this Rihmasto yet", sync["why_not"])
        monitor = copilot.plan(self.factory, self.p, "Monitor it")
        probe = next(s for s in monitor["steps"] if s["action"]["kind"] == "enable_check")
        self.assertEqual(probe["available"], "probe" in {c["kind"] for c in cat["checks"]["kinds"]})
        gcp = copilot.plan(self.factory, self.p, "Deploy it to production in Google Cloud")
        self.assertEqual(bool(gcp["gaps"]), not cat["roads"]["gcp"])


class ModelTest(GoalCase):
    def test_FR_CPL1_AC_3_the_models_steps_are_checked_and_a_confidential_project_never_asks_a_hosted_model(self):
        pid = self.p.pid
        m = Scripted({"answer": "I have filed the change for you. Here is how to reach Google Drive.", "steps": [
            {"title": "Draft the change", "detail": "", "action": {"kind": "draft_change", "text": "Reach Google Drive"}},
            {"title": "Open the plan", "action": {"kind": "open", "route": f"#/p/{pid}/plan", "control": "integrations"}},
            {"title": "Deploy now", "action": {"kind": "deploy_now"}},
            {"title": "Clean up", "action": {"kind": "command", "command": "rm -rf / ; rihmasto run x"}},
            {"title": "Go nowhere", "action": {"kind": "open", "route": "#/nowhere"}}],
            "gaps": [{"what": "No Drive connector.", "options": ["REST"]}]})
        before = tree(self.factory.home)
        plan = copilot.plan(self.factory, self.p, DRIVE, model=m)
        self.assertEqual(tree(self.factory.home), before)
        self.assertEqual(plan["by"], "model")
        self.assertEqual([s["title"] for s in plan["steps"]], ["Draft the change", "Open the plan"])
        refused = {d["step"]["title"]: d["refused"] for d in plan["dropped"]}
        self.assertEqual(refused["Deploy now"], "unknown step kind 'deploy_now'")
        self.assertIn("one plain `rihmasto ...` command", refused["Clean up"])
        self.assertIn("is not a cockpit route", refused["Go nowhere"])
        self.assertNotIn("I have filed", plan["answer"])                         # it proposes; it never acted
        self.assertEqual(m.calls[0][0], "assistant")
        self.assertIn("Google Drive", m.calls[0][1])
        # a confidential project with a hosted assistant model: the rules plan it, the model is never asked
        self.p.update_meta(confidential=True)
        m2 = Scripted({"answer": "x", "steps": []})
        with mock.patch("kernel.confidential.refusal", return_value="refused: hosted"):
            plan = copilot.plan(self.factory, self.p, DRIVE, model=m2)
        self.assertEqual(m2.calls, [])
        self.assertEqual(plan["by"], "rules")
        self.assertIn("Models setup", plan["note"])
        self.assertTrue(plan["confidential"])
        # a model that gives nothing usable: the rules' plan, said so
        plan = copilot.plan(self.factory, self.p.__class__(self.factory, self.new(title="Other").pid), DRIVE,
                            model=Scripted({"answer": "", "steps": [{"title": "x", "action": {"kind": "nope"}}]}))
        self.assertEqual(plan["by"], "rules")
        self.assertIn("none of the model's steps passed", plan["note"])


class AskTest(GoalCase):
    def test_FR_CPL1_AC_4_ask_rihma_answers_a_goal_with_a_plan_and_keeps_map_and_status_answers(self):
        out = ask(self.factory, DRIVE, persona="developer", project_id=self.p.pid)
        self.assertEqual(out["by"], "goal")
        self.assertEqual(out["plan"]["intents"], ["connect"])
        self.assertTrue(out["plan"]["steps"])
        self.assertEqual(out["propose"], [])                                       # nothing to confirm blindly
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/plan")
        self.assertEqual(ask(self.factory, "where is the ledger?", persona="developer",
                             project_id=self.p.pid)["by"], "map")
        status = ask(self.factory, "what's the status of this project?", persona="developer", project_id=self.p.pid)
        self.assertNotIn("plan", status)
        self.assertNotEqual(ask(self.factory, DRIVE, persona="developer")["by"], "goal")   # no project: no plan
        out = ask(self.factory, "Haluan kytkeä tämän Google Driveen", persona="developer", project_id=self.p.pid)
        self.assertEqual(out["by"], "goal")


if __name__ == "__main__":
    unittest.main()
