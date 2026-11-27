"""The cockpit assistant, repaired after the UX audit (kernel/assistant.py, assistant_rules.py,
assistant_snapshot.py):

- Take me there opens the page a control is on, and a view a project must hold says so (FR-V1-AC-1).
- A proposal is offered only when the person asked for an action, is checked as the route would check
  it, and an answer never says the assistant did something; a source the records hold is backed
  (FR-V1-AC-2); "I have noted", "I've flagged" or "Noted." is such a claim.
- A control the model names as a view, or a route the cockpit lacks, is never followed; a busy lane
  falls back to the map with a note (FR-V1-AC-3).
- The assistant asks in a lane of its own, with a short wait and timeout (FR-V1-AC-4).
- A real model's layout and theme shapes are read, not dropped (FR-V1-AC-6).
- The snapshot holds what the questions need, and names what it left out; what waits on the person is
  counted as the Decisions waiting widget and the Inbox count it (FR-Z1-AC-4).
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel import assistant  # noqa: E402
from kernel.assistant import ask, find_in_map, fit_snapshot, normalize, prompt, snapshot, ui_map  # noqa: E402
from kernel.assistant_rules import CONTROL_PAGES, PERSONA_LABEL, asks_for_action, honest  # noqa: E402
from kernel.assistant_snapshot import relevant_first  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.filelock import LockHeld  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.model import FakeModel, GnomonModel  # noqa: E402
from kernel.safestop import request_pause  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
SECRET = "the scenario expected header X-Hmac-Sig-7731"
UI = {"widgets": ["kpi_strip", "gate_trend", "decisions", "activity"],
      "layout": {"v": 1, "widgets": [{"id": "gate_trend-2", "type": "gate_trend", "size": "M"},
                                     {"id": "decisions-x1", "type": "decisions", "size": "M"}]}}


def written(project) -> int:
    """The project's records, less the usage metadata of a model run (model_run, FR-INS1-AC-9): that says a model
    answered, never what; the assistant itself writes nothing."""
    return len([r for r in project.ledger().records() if r["event"]["kind"] != "model_run"])


def answering(answer: dict) -> FakeModel:
    return FakeModel(lambda prompt, role: "```json\n" + json.dumps(answer) + "\n```")


class Built(FactoryTestCase):
    """A project with open questions, a spec and a contract, an open escalation, a decided change card,
    a holdout ruling whose body is in custody, and a release that ran on demo."""

    def setUp(self):
        super().setUp()
        self.p = self.new(mode="assume")
        intake(self.p, IDEA, model=model(), requested_by="Aino")
        make_spec(self.p, model=model())
        compile_project(self.p)
        canon = Canon(self.p)
        canon.add_question("Which items can be borrowed?", "business")
        canon.add_question("Who approves a loan?", "operations")
        self.esc = canon.card("escalation", "T-002 failed its gate three times", body="the harness failed 3 times")
        self.change = canon.card("change", "Sort the list by name", payload={"text": "sort it"})
        canon.decide(self.change["id"], "defer", person="Aino", persona="business_owner", reason="after the pilot")
        self.ruling = canon.card("holdout_ruling", "Holdout R-1-AC-1 failed", body=SECRET)
        self.p.write("releases/1.json", {"release": 1, "state": "done", "environments": ["demo"], "maturity": "demo",
                                         "steps": [{"step": "deploy:demo", "outcome": "passed"}]})
        self.records = written(self.p)

    def ask_model(self, question: str, answer: dict, persona: str = "business_owner", **kw) -> dict:
        return ask(self.factory, question, persona=persona, project_id=self.p.pid, model=answering(answer), **kw)


class MapTest(Built):
    def test_FR_V1_AC_1_take_me_there_opens_the_page_a_control_is_on_and_says_when_a_project_must_be_open(self):
        controls = {c["id"]: c for c in ui_map()["controls"]}
        self.assertEqual(set(controls), set(CONTROL_PAGES))                     # the map says where each one is
        views = {v["id"] for v in ui_map()["views"]}
        for view, page in CONTROL_PAGES.values():
            self.assertTrue(view is None or view in views)
            self.assertTrue(page is None or page in views)
        pid = self.p.pid
        cases = {"Where do I export the evidence pack?": (f"#/p/{pid}/evidence", "export_evidence"),
                 "How do I pause this?": (f"#/p/{pid}/overview", "pause"),
                 "Where do I validate a concept?": ("#/square", "validate_concept"),
                 "Where is customize?": ("#/home", "customize"),
                 "Where is the log?": (f"#/p/{pid}/ledger", None),
                 "Where is the chat?": (None, "assistant")}
        for question, (route, control) in cases.items():
            out = ask(self.factory, question, persona="business_owner", project_id=pid)
            self.assertEqual(out["navigate"], {"route": route, "control": control}, question)
        home = ask(self.factory, "Where is the ledger?", persona="business_owner")
        self.assertEqual(home["navigate"], {"route": "#/projects", "control": None})
        self.assertIn("Open a project first", home["answer"])
        pause = ask(self.factory, "How do I pause this?", persona="business_owner")
        self.assertEqual(pause["navigate"], {"route": "#/projects", "control": None})   # not on the Projects page
        self.assertEqual(ask(self.factory, "Make a feedback chat for our website", persona="business_owner")["navigate"],
                         {"route": "#/settings", "control": "create_embed"})

    def test_FR_V1_AC_1_the_map_reads_well_and_never_opens_a_view_rihma_itself_lacks(self):
        out = ask(self.factory, "Where is the persona switcher?", persona="business_owner")
        self.assertIn("is in the person chip", out["answer"])
        self.assertNotIn("the the", out["answer"])
        verdicts = ask(self.factory, "Where are the verdict buttons?", persona="business_owner")["answer"]
        self.assertIn("Verdict buttons are in an Inbox card", verdicts)
        self.assertIn("they decide the card", verdicts)
        status = ask(self.factory, "hello there", persona="business_owner", project_id=self.p.pid)["answer"]
        self.assertRegex(status, r"\. Health: [a-z ]+\.$")                    # two sentences, each with its stop
        from kernel.learn import factory_project

        factory_project(self.factory)                                          # Rihma's own canon
        plan = ask(self.factory, "Where do I approve the plan?", persona="business_owner", project_id="_factory")
        self.assertIsNone(plan["navigate"])
        self.assertIn("Rihmasto itself has no Plan view", plan["answer"])
        self.assertIsNone(ask(self.factory, "How do I pause this?", persona="it", project_id="_factory")["navigate"])

    def test_FR_V1_AC_1_without_a_model_a_request_to_act_is_told_so_and_pointed_at_its_control(self):
        theme = ask(self.factory, "Use a compact teal theme", persona="operations")
        self.assertEqual(theme["navigate"], {"route": None, "control": "theme"})
        self.assertIn("by rule (no model is needed for this)", theme["answer"])    # a plain request: proposed by rule
        self.assertEqual([p["args"]["settings"] for p in theme["propose"]], [{"density": "compact", "accent": "teal"}])
        wide = ask(self.factory, "Make the decisions widget wide", persona="business_owner")
        self.assertEqual(wide["navigate"], {"route": "#/home", "control": "customize"})
        self.assertEqual([h["id"] for h in find_in_map("Where is the embed?")][:2], ["settings", "create_embed"])


class ProposalTest(Built):
    def test_FR_V1_AC_2_a_question_about_how_things_stand_gets_no_proposal_and_the_answer_never_claims_an_act(self):
        ruling = {"answer": "The run is at risk. I have recorded your decision to rule it a product defect.",
                  "navigate": None, "sources": [self.p.pid],
                  "propose": [{"action": "decide", "args": {"card": self.esc["id"], "verdict": "retry"}}]}
        out = self.ask_model("How is the run going?", ruling, persona="developer")
        self.assertEqual((out["propose"], out["dropped"], out["unasked"]), ([], [], 1))
        self.assertNotIn("I have recorded", out["answer"])
        self.assertIn("Nothing is done", out["answer"])
        self.assertIn("taken out", out["note"])
        asked = self.ask_model(f"Retry {self.esc['id']}", ruling, persona="developer")
        self.assertEqual([p["action"] for p in asked["propose"]], ["decide"])
        self.assertEqual((asked["propose"][0]["persona"], asked["propose"][0]["project"]), ("developer", self.p.pid))
        self.assertIn("runs only when you confirm it", asked["answer"])
        self.assertEqual(written(self.p), self.records)       # it wrote nothing
        for q in ("How is the shipment desk run going?", "Which tasks are merged?", "What does the plan assume?",
                  "Mikä odottaa minua, ja onko projekti tauolla?", "Where do I approve the plan?"):
            self.assertFalse(asks_for_action(q), q)
        for q in ("Rule C-0013 as a scenario defect", "Can you pause it?", "Use a compact teal theme",
                  "Let Rihma assume Q-015", "Make a feedback chat for our website", "Voitko tauottaa projektin?"):
            self.assertTrue(asks_for_action(q), q)

    def test_FR_V1_AC_2_an_answer_that_says_it_noted_or_flagged_something_is_corrected(self):
        ruling = {"answer": "I have noted that the scenarios for C-0013 failed because requests were not signed. "
                            "As End-user tester you cannot rule on a holdout.", "navigate": None, "sources": [],
                  "propose": [{"action": "decide", "args": {"card": self.ruling["id"], "verdict": "scenario_defect"}}]}
        out = self.ask_model("Rule it as a scenario defect, the scenarios forgot to sign their requests", ruling,
                             persona="end_user")
        self.assertEqual(out["propose"], [])                                     # end_user may not rule on it
        self.assertNotIn("noted", out["answer"])
        self.assertIn("As End-user tester you cannot rule on a holdout.", out["answer"])
        self.assertIn("Nothing is done, and I could not offer it", out["answer"])
        self.assertIn("taken out", out["note"])
        claims = ("Noted. The scenarios failed.", "I've flagged C-0013 for the developer.", "We sent it on.",
                  "I have taken note of your request.", "I went ahead and filed it.", "Done: the card is decided.",
                  "Olen merkinnyt sen.", "I have confirmed the assumption.")
        facts = ("I note that the release stopped at staging.", "I propose ruling C-0013 as a scenario defect.",
                 "I cannot see the failure detail.", "Done tasks are T-001 and T-002.", "I recommend the Inbox.")
        for said in claims:
            self.assertIsNotNone(honest(said, [], [])[1], said)
        for said in facts:
            self.assertEqual(honest(said, [], []), (said, None), said)
        self.assertEqual(written(self.p), self.records)         # it wrote nothing

    def test_FR_V1_AC_2_what_the_route_would_refuse_is_not_offered_and_reasons_name_the_persona(self):
        def offered(question, proposal, persona="business_owner", project_id=None):
            answer = {"answer": "Here it is.", "navigate": None, "sources": [], "propose": [proposal]}
            return ask(self.factory, question, persona=persona, project_id=project_id or self.p.pid,
                       model=answering(answer))
        self.assertEqual(offered("Resume it", {"action": "resume", "args": {}})["dropped"][0]["refused"],
                         f"{self.p.pid} is not paused")
        request_pause(self.p, person="Aino", persona="business_owner", reason="feed is down")
        self.assertIn("already paused by Aino", offered("Pause it", {"action": "pause", "args": {}})["dropped"][0]["refused"])
        refused = offered("Retry it", {"action": "decide", "args": {"card": self.esc["id"], "verdict": "retry"}},
                          persona="end_user")["dropped"][0]["refused"]
        self.assertIn("as End-user tester you may not decide an escalation card", refused)
        self.assertIn("Developer", refused)
        self.assertIn(f"{self.change['id']} is decided", offered("Accept it", {"action": "decide", "args": {
            "card": self.change["id"], "verdict": "accept"}})["dropped"][0]["refused"])
        self.assertIn("a comment's target", offered("Comment on it", {"action": "comment", "args": {
            "target_kind": "banana", "target_id": "x", "text": "hi"}})["dropped"][0]["refused"])
        nested = offered("Filter decisions", {"action": "layout_edit", "args": {"ops": [
            {"op": "set_filter", "widget": "decisions", "filter": {"deep": {"a": [1, 2]}}}]}}, persona="business_owner")
        self.assertEqual(nested["propose"], [])                                 # the layout route would refuse it
        answer = {"answer": "I will make it.", "navigate": None, "sources": [],
                  "propose": [{"action": "create_embed", "args": {"kind": "feedback", "origins": ["*"]}}]}
        out = self.ask_model("Make a feedback chat for our website", answer, ui=UI)
        self.assertEqual(out["propose"][0]["args"]["origins"], [])              # the form opens for them to fill in
        self.assertNotIn("I will", out["answer"])

    def test_FR_V1_AC_2_sources_the_records_hold_are_backed_and_only_unknown_ones_are_flagged(self):
        canon = Canon(self.p)
        answered = canon.questions("open")[0]["id"]
        canon.answer(answered, "Laptops and drills", person="Aino", persona="business_owner")
        sources = [self.p.pid, self.esc["id"], self.change["id"], "R-1", "R-1-AC-1", answered, "T-001",
                   f"card: {self.esc['id']}", f"project: {self.p.pid}", "factory.gates.first_round_rate",
                   f"question: {answered} (implied by {self.change['id']})", "release 1", "C-9999", "made-up",
                   "project_settings", "models"]          # a control and a view of the cockpit's map are sources too
        out = self.ask_model("Where does it stand?", {"answer": "x", "navigate": None, "propose": [],
                                                      "sources": sources})
        self.assertEqual(out["unbacked_sources"], ["C-9999", "made-up"])


class NavigationAndLaneTest(Built):
    def test_FR_V1_AC_3_a_view_named_as_a_control_opens_the_view_and_an_unknown_control_is_dropped(self):
        pid = self.p.pid
        out = self.ask_model("What waits on me?", {"answer": "x", "propose": [], "sources": [],
                                                   "navigate": {"route": None, "control": "inbox"}})
        self.assertEqual(out["navigate"], {"route": f"#/p/{pid}/inbox", "control": None})
        out = self.ask_model("Where?", {"answer": "x", "propose": [], "sources": [],
                                        "navigate": {"route": f"#/p/{pid}/overview", "control": "rm-rf"}})
        self.assertEqual(out["navigate"], {"route": f"#/p/{pid}/overview", "control": None})
        out = self.ask_model("Where?", {"answer": "x", "propose": [], "sources": [],
                                        "navigate": {"route": None, "control": "export_evidence"}})
        self.assertEqual(out["navigate"], {"route": f"#/p/{pid}/evidence", "control": "export_evidence"})
        out = self.ask_model("Where?", {"answer": "x", "propose": [], "sources": [],
                                        "navigate": {"route": "#/p/no-such-project/inbox", "control": None}})
        self.assertIsNone(out["navigate"])
        # "open" with a control of the map as its route is Take me there, never "not a cockpit route"
        out = self.ask_model("I chose the wrong template, what do I do?", {
            "answer": "Change it in Project settings.", "navigate": None, "sources": ["project_settings"],
            "propose": [{"action": "open", "args": {"route": "project_settings"}, "why": "w"}]})
        self.assertEqual((out["dropped"], out["unbacked_sources"]), ([], []))
        self.assertEqual(out["navigate"], {"route": f"#/p/{pid}/overview", "control": "project_settings"})
        self.assertNotIn("could not offer", out["answer"])

    def test_FR_V1_AC_3_a_busy_lane_falls_back_to_the_map_with_a_note(self):
        class Busy(FakeModel):
            def ask(self, prompt, *, role):
                raise LockHeld("the lane is held")
        out = ask(self.factory, "Where is the ledger?", persona="developer", project_id=self.p.pid, model=Busy({}))
        self.assertEqual(out["by"], "map")
        self.assertIn("busy", out["note"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/ledger")

    def test_FR_V1_AC_4_the_assistant_asks_in_a_lane_of_its_own_with_a_short_wait(self):
        from kernel.lanes import lane_lock

        root = self.tmp / "lanes"
        own = assistant._own_lane(GnomonModel(root / "analyst", timeout=180))
        self.assertIsInstance(own, assistant.AssistantModel)
        self.assertEqual(own.lane_dir, root / "assistant" / "analyst")       # never the factory's analyst lane
        self.assertLessEqual(own.timeout, 60)
        self.assertLessEqual(own.lane_wait, 10)
        roles = (own.lane_dir / ".gnomon" / "roles.toml").read_text(encoding="utf-8")
        self.assertIn("tools = []", roles.split("[roles.assistant]")[1].split("[roles.")[0])
        quick = assistant.AssistantModel(own.lane_dir, lane_wait=0.3)
        with lane_lock(own.lane_dir):
            started = time.monotonic()
            with self.assertRaises(LockHeld):
                quick.ask("hello", role="assistant")
            self.assertLess(time.monotonic() - started, 5)


class ReshapeTest(Built):
    def test_FR_V1_AC_6_a_real_models_layout_and_theme_shapes_are_read_not_dropped(self):
        answer = {"answer": "I will resize the gate trend widget and switch the theme.", "navigate": None,
                  "sources": [], "propose": [
                      {"action": "layout_edit", "args": {"ops": [{"op": "resize", "widget_id": "gate_trend-2", "size": "L"},
                                                                 {"op": "set_view", "widget_id": "gate_trend-2",
                                                                  "view": "Table"}]}},
                      {"action": "theme", "args": {"accent": "Teal", "density": "compact"}},
                      {"action": "layout_edit", "args": {"ops": {"op": "resize", "widget": "decisions-x1", "size": "wide"}}}]}
        out = self.ask_model("Make the gate trend bigger and show it as a table, compact teal", answer, ui=UI)
        self.assertEqual(out["dropped"], [])
        layout, theme, wide = out["propose"]
        self.assertEqual(layout["args"]["ops"], [{"op": "resize", "widget": "gate_trend", "size": "L"},
                                                 {"op": "set_view", "widget": "gate_trend", "view": "table"}])
        self.assertEqual(theme["args"], {"settings": {"accent": "teal", "density": "compact"}})
        self.assertEqual(wide["args"]["ops"], [{"op": "resize", "widget": "decisions", "size": "L"}])
        self.assertNotIn("I will", out["answer"])
        self.assertIn("after a preview", out["answer"])
        self.assertEqual(normalize({"action": "set_theme", "args": {"settings": {"mode": "dark mode"}}})["args"],
                         {"settings": {"mode": "dark"}})


class SnapshotTest(Built):
    def test_FR_Z1_AC_4_the_snapshot_holds_what_answers_need_and_keeps_the_named_items_within_its_budget(self):
        snap = snapshot(self.factory, project=self.p, persona="it")
        text = json.dumps(snap)
        self.assertNotIn(SECRET, text)                                           # a ruling's body stays in custody
        self.assertEqual(snap["factory"]["in_production"], [])                   # demo is not production
        self.assertEqual(snap["project"]["releases"][0]["deployed_to"], ["demo"])
        self.assertIs(snap["project"]["paused"], False)
        self.assertIs(snap["project"]["plan_held_for_approval"], False)          # demo holds no plan
        waiting = {c["card"]: c["yours"] for c in snap["factory"]["waiting_cards"]}
        self.assertFalse(waiting[self.ruling["id"]])                              # IT may not rule on a holdout
        self.assertEqual(snap["factory"]["waiting"]["yours"], 0)
        decided = snap["project"]["decided_cards"][0]                             # a decision's reason never
        self.assertEqual(decided["verdict"], "defer")                             # reaches the model (FR-H10-AC-24)
        self.assertNotIn("reason", decided)
        self.assertNotIn("after the pilot", text)
        self.assertIn("the harness failed 3 times", text)                        # an escalation says why
        counts = snap["project"]["counts"]
        self.assertEqual(counts["open_questions"], len(Canon(self.p).questions("open")))
        many = json.loads(text)
        many["project"]["open_questions"] = [{"id": f"Q-{i:03d}", "text": f"About topic {i}", "blocking": False}
                                             for i in range(1, 13)]
        many["project"]["open_questions"][11]["text"] = "Which vendor-baseline controls must run in the demo?"
        fitted = fit_snapshot(relevant_first(many, "Let Rihma assume the question about vendor-baseline controls"))
        self.assertEqual(fitted["project"]["open_questions"][0]["id"], "Q-012")  # the one the question names stays
        self.assertIn("6 of 12 open questions", fitted["not_shown"])

    def test_FR_Z1_AC_4_what_waits_on_the_person_is_what_the_decisions_widget_and_the_inbox_count(self):
        from kernel.learn import factory_project

        canon = Canon(self.p)
        asked = canon.ask(canon.questions("open")[0]["id"])                     # a question put to a person
        self.assertFalse(asked["blocking"])                                     # not blocking: still waits on one
        own = factory_project(self.factory)                                     # Rihma's own canon
        concept = Canon(own).card("concept", "Validate as a concept? Offline visits",
                                  payload={"title": "Offline visits", "text": "Field staff work offline",
                                           "profile": "mobile_prototype"})
        Canon(own).card("update", "A newer model")                              # not in the widget's count
        snap = snapshot(self.factory, project=self.p, persona="it")
        waiting = snap["factory"]["waiting"]
        cards = {(c["project"], c["card"]): c for c in snap["factory"]["waiting_cards"]}
        self.assertEqual(set(cards), {(self.p.pid, asked["id"]), (self.p.pid, self.esc["id"]),
                                      (self.p.pid, self.ruling["id"]), ("_factory", concept["id"])})
        self.assertEqual((waiting["total"], waiting["yours"]), (4, 1))            # IT answers the question only
        self.assertEqual(waiting["yours_by_project"], {self.p.pid: 1})
        self.assertEqual(waiting["by_kind"], {"question": 1, "escalation": 1, "holdout_ruling": 1, "concept": 1})
        first = snap["factory"]["waiting_cards"][0]
        self.assertEqual((first["card"], first["yours"], first["deciders"]), (asked["id"], True, "any persona"))
        owner = snapshot(self.factory, project=self.p, persona="business_owner")["factory"]["waiting"]
        self.assertEqual((owner["total"], owner["yours"]), (4, 4))
        self.assertIn("Decisions waiting widget", prompt("What waits on me?", snap, persona="it", view="home", hints=[]))


class LabelsTest(unittest.TestCase):
    def test_FR_V1_AC_2_the_persona_labels_in_a_reason_are_the_cockpits(self):
        from cockpit.server import PERSONA_INFO

        self.assertEqual(PERSONA_LABEL, {k: v[0] for k, v in PERSONA_INFO.items()})


if __name__ == "__main__":
    unittest.main()
