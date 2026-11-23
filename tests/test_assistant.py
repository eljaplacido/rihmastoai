import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, lazy_cell, model, no_findings  # noqa: E402

from kernel.assistant import ask, find_in_map, ui_map  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.lenses import LENSES, project_context  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class Seeded(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(mode="assume")
        intake(self.p, IDEA, model=model(), requested_by="Aino")
        make_spec(self.p, model=model())
        compile_project(self.p)
        lanes = Lanes(self.tmp / "lanes", size=1)
        build_task(self.p, "T-001", lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings)
        build_task(self.p, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        self.escalation = next(c for c in Canon(self.p).cards() if c["kind"] == "escalation")

    def records(self):
        return len(self.p.ledger().records())


class LensTest(Seeded):
    def test_FR_T1_AC_9_each_persona_starts_in_its_lens_and_the_stage_brings_its_views_forward(self):
        self.assertEqual(project_context(self.p, "developer")["lens"], "delivery")
        self.assertEqual(project_context(self.p, "business_owner")["lens"], "business")
        self.assertEqual(project_context(self.p, "concept_evaluator")["lens"], "concept")
        switched = project_context(self.p, "business_owner", lens="delivery")
        self.assertEqual(switched["lens"], "delivery")                       # anyone may switch
        self.assertEqual(project_context(self.p, "it", lens="no-such")["lens"], "operations")
        ctx = project_context(self.p, "business_owner")
        self.assertEqual(ctx["stage"], 5)
        self.assertEqual(ctx["views"][:2], ["tasks", "live"])                # stage 5 brings the run forward
        self.assertEqual(len(ctx["views"]), len(set(ctx["views"])))
        self.assertEqual(set(ctx["lenses"]), set(LENSES))
        known = {v["id"] for v in ui_map()["views"]} | {"live"}
        for lens in LENSES.values():                                         # every lens names real views
            self.assertLessEqual(set(lens["views"]), known)


class CommentTest(Seeded):
    def test_FR_T1_AC_10_people_comment_without_deciding_and_an_owner_may_promote_it_into_a_change(self):
        canon = Canon(self.p)
        cards_before = len(canon.cards())
        c = canon.comment({"kind": "requirement", "id": "R-2"}, "Could the approver be optional for small items?",
                          person="Sanna", persona="stakeholder")
        self.assertEqual(c["id"], "CM-001")
        self.assertEqual(len(canon.cards()), cards_before)                   # a comment decides nothing
        self.assertEqual(canon.comments({"kind": "requirement", "id": "R-2"})[0]["person"], "Sanna")
        with self.assertRaises(DecisionRefused):
            canon.comment({"kind": "task", "id": "T-001"}, "looks good", person="assistant", persona="developer")
        with self.assertRaises(ValueError):
            canon.comment({"kind": "nothing", "id": "x"}, "text", person="Sanna", persona="stakeholder")
        with self.assertRaises(DecisionRefused):
            canon.promote_comment("CM-001", person="Sanna", persona="stakeholder")
        card = canon.promote_comment("CM-001", person="Pekka", persona="product_owner")
        self.assertEqual(card["kind"], "change")
        self.assertIn("[requirement R-2]", card["payload"]["text"])
        self.assertIn("comment by Sanna", card["payload"]["text"])
        self.assertEqual(canon.comments()[0]["promoted_to"], card["id"])
        with self.assertRaises(DecisionRefused):
            canon.promote_comment("CM-001", person="Pekka", persona="product_owner")
        kinds = [r["event"]["kind"] for r in self.p.ledger().records()]
        self.assertIn("comment", kinds)
        self.assertIn("comment_promoted", kinds)


class AssistantTest(Seeded):
    def test_FR_V1_AC_1_where_is_questions_are_answered_from_the_cockpit_map_without_a_model(self):
        top = find_in_map("Where can I approve the plan?")[0]
        self.assertEqual(top["id"], "plan")
        out = ask(self.factory, "where do I see the token cost of each run?", persona="developer",
                  project_id=self.p.pid)
        self.assertEqual(out["by"], "map")
        self.assertIn(out["navigate"]["route"], (f"#/p/{self.p.pid}/cell", "#/floor"))
        out = ask(self.factory, "how do I pause this?", persona="developer", project_id=self.p.pid)
        self.assertEqual(out["navigate"]["control"], "pause")
        routes = {v["route"].split("/")[-1] for v in ui_map()["views"]}
        self.assertIn("try", routes)

    def test_FR_V1_AC_2_proposals_pass_the_inbox_rules_or_are_dropped_and_the_assistant_writes_nothing(self):
        esc = self.escalation["id"]
        answer = {"answer": "T-002 failed its gate twice and waits on a person.",
                  "navigate": {"route": f"#/p/{self.p.pid}/tasks", "control": None},
                  "propose": [
                      {"action": "decide", "args": {"card": esc, "verdict": "retry", "reason": "try again"}, "why": "w"},
                      {"action": "decide", "args": {"card": esc, "verdict": "approve"}, "why": "wrong verdict"},
                      {"action": "decide", "args": {"card": "C-9999", "verdict": "retry"}, "why": "no card"},
                      {"action": "pause", "args": {"reason": "x"}, "why": "w"},
                      {"action": "rm -rf", "args": {}, "why": "nonsense"}],
                  "sources": ["T-002", esc, "R-77"]}
        fake = FakeModel({"assistant": ["```json\n" + json.dumps(answer) + "\n```"]})
        before = self.records()
        out = ask(self.factory, "T-002 is stuck: retry it, and pause the project.", persona="developer",
                  project_id=self.p.pid, model=fake)
        self.assertEqual(self.records(), before)                             # it wrote nothing
        self.assertEqual(out["by"], "assistant")
        self.assertEqual([p["action"] for p in out["propose"]], ["decide", "pause"])
        self.assertEqual(len(out["dropped"]), 3)
        self.assertTrue(all(d["refused"] for d in out["dropped"]))
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/tasks")
        self.assertEqual(out["unbacked_sources"], ["R-77"])
        role, prompt = fake.calls[0]
        self.assertEqual(role, "assistant")
        self.assertIn("You never act", prompt)
        # the same proposal for a persona that may not decide escalations is dropped
        fake = FakeModel({"assistant": ["```json\n" + json.dumps(answer) + "\n```"]})
        out = ask(self.factory, "T-002 is stuck: retry it, and pause the project.", persona="end_user",
                  project_id=self.p.pid, model=fake)
        self.assertEqual(out["propose"], [])

    def test_FR_V1_AC_3_a_route_the_cockpit_lacks_is_never_followed_and_a_failed_model_falls_back_to_the_map(self):
        bad = {"answer": "go here", "navigate": {"route": "https://evil.example/", "control": None},
               "propose": [], "sources": []}
        fake = FakeModel({"assistant": ["```json\n" + json.dumps(bad) + "\n```"]})
        out = ask(self.factory, "where?", persona="developer", project_id=self.p.pid, model=fake)
        self.assertIsNone(out["navigate"])
        broken = FakeModel({"assistant": ["no json here at all"]})
        out = ask(self.factory, "where is the ledger?", persona="developer", project_id=self.p.pid, model=broken)
        self.assertEqual(out["by"], "map")
        self.assertIn("no usable answer", out["note"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/ledger")

    def test_FR_V1_AC_6_the_assistant_may_reshape_the_cockpit_only_within_its_boundaries(self):
        ui = {"widgets": ["kpi_strip", "gate_trend", "activity"],
              "layout": {"v": 1, "widgets": [{"id": "w1", "type": "gate_trend", "size": "M"}]}}
        answer = {"answer": "Made the gate trend bigger, a table, and the theme compact.", "navigate": None,
                  "propose": [
                      {"action": "layout_edit", "args": {"ops": [{"op": "resize", "widget": "gate_trend", "size": "XL"},
                                                                 {"op": "set_view", "widget": "gate_trend", "view": "table"}]}},
                      {"action": "theme", "args": {"settings": {"density": "compact", "accent": "teal"}}},
                      {"action": "layout_edit", "args": {"ops": [{"op": "add", "widget": "rm_rf_widget"}]}},
                      {"action": "theme", "args": {"settings": {"css": "body{display:none}"}}},
                      {"action": "theme", "args": {"settings": {"font_scale": 3}}},
                      {"action": "create_embed", "args": {"kind": "feedback", "origins": ["https://shop.example"]}},
                      {"action": "create_embed", "args": {"kind": "feedback", "origins": ["javascript:alert(1)"]}}],
                  "sources": []}
        fake = FakeModel({"assistant": ["```json\n" + json.dumps(answer) + "\n```"]})
        before = self.records()
        out = ask(self.factory, "make the gate trend bigger and as a table, compact theme, and a feedback chat for "
                  "our shop site", persona="product_owner", project_id=self.p.pid, model=fake, ui=ui)
        self.assertEqual(self.records(), before)                             # proposals only
        self.assertEqual([p["action"] for p in out["propose"]], ["layout_edit", "theme", "create_embed"])
        self.assertEqual(len(out["dropped"]), 4)
        self.assertIn("gate_trend", fake.calls[0][1])                        # it saw the widget library
        fake = FakeModel({"assistant": ["```json\n" + json.dumps(answer) + "\n```"]})
        out = ask(self.factory, "same", persona="end_user", project_id=self.p.pid, model=fake, ui=ui)
        self.assertNotIn("create_embed", [p["action"] for p in out["propose"]])   # an end user may not make one

    def test_FR_V1_AC_4_the_assistant_runs_toolless_in_the_analyst_lane(self):
        from kernel.lanes import ensure_analyst_lane, load_routing

        lane = ensure_analyst_lane(load_routing(), root=self.tmp / "lanes")
        roles = (lane / ".gnomon" / "roles.toml").read_text(encoding="utf-8")
        block = roles.split("[roles.assistant]")[1].split("[roles.")[0]
        self.assertIn("tools = []", block)


if __name__ == "__main__":
    unittest.main()
