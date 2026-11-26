"""FR-ITD2: IT's view of integrations and data tells each project its own truth (tests/itdata_fixture.py).

The owner (2026-11-25): "from IT perspective, you would want to view for integrations and the data side of things as
well". An independent check found one project's result shown in another, a platform-wide channel that IT on one
project could stop, how-to questions answered with the connection list, confidential agents shown as working while
refused, and a caption counting a line the diagram never drew. Every connection here is a neutral stand-in; a check
reaches loopback only.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import itdata_fixture as fx  # noqa: E402
from factory_fakes import isolated_routing  # noqa: E402
from test_access import ADMIN, DEV, EnforcedCockpitCase, access_doc  # noqa: E402
from test_itdata import ItDataTestCase, by_id  # noqa: E402

from kernel import assistant, embeds, hooks, itdata, itdata_actions, itdata_chat, relay  # noqa: E402
from kernel import itdata_project as views  # noqa: E402

IT = fx.PERSON


class HealthPerProjectTest(ItDataTestCase):
    def second(self):
        """A second project that declares an integration of the same name and runs in the same environment."""
        p = self.factory.new_project("Loan desk", mode="assume", maturity="pilot")
        spec = p.read("spec.json") or {}
        p.write("spec.json", {"title": "Loan desk", "requirements": [], **spec, "integrations": [fx.ORDERS]})
        return p

    def test_FR_ITD2_AC_1_a_check_on_one_project_never_shows_in_another_that_has_the_same_id(self):
        loans = self.second()
        for _ in range(2):
            itdata_actions.check(self.factory, person="Olli Example", persona="operations", project=self.project,
                                 item="integration:orders_api")
        mine = by_id(views.project_view(self.project))["integration:orders_api"]
        self.assertEqual((mine["state"], mine["health"]["ok"], mine["health"]["failures"]), ("failing", False, 2))
        view = views.project_view(loans)
        theirs = by_id(view)["integration:orders_api"]
        self.assertIsNone(theirs["health"], "never checked there")
        self.assertNotEqual(theirs["state"], "failing")
        self.assertIsNone(view["checked"], "it says it has not been checked")
        a, b = by_id(views.project_view(self.project))["road:staging"], by_id(view)["road:staging"]
        self.assertNotEqual(itdata.health_key(a), itdata.health_key(b), "each project's road:staging apart")
        relay_ = by_id(views.project_view(self.project))["relay:SUB-002"]
        self.assertEqual(itdata.health_key(relay_), "relay:SUB-002", "the platform's own: one result")

    def test_FR_ITD2_AC_6_a_road_check_that_measured_nothing_never_hides_the_probe(self):
        out = itdata_actions.check(self.factory, person="Olli Example", persona="operations", project=self.project,
                                   item="road:staging")
        self.assertIsNone(out["results"][0]["ok"])
        kept = itdata.kept(self.factory, "health.json")
        self.assertFalse([k for k in kept if k.endswith("road:staging")], "a check that measured nothing is not kept")
        probe = {"ok": False, "at": "2026-11-24T09:00:00Z", "why": "the probe got 503", "by": "probe", "failures": 1}
        road = itdata.item("road:staging", "road", "Staging", direction="out", where=itdata.LOCAL, scope="project",
                           projects=[self.project.pid], native=probe)
        kept[itdata.health_key(road)] = {"ok": None, "at": "2026-11-25T09:00:00Z", "by": "check", "why": "nothing"}
        with mock.patch.object(itdata, "kept", return_value=kept):
            shown = itdata.with_health(self.factory, [road])[0]
        self.assertEqual((shown["state"], shown["health"]["why"]), ("failing", "the probe got 503"))


class ScopeTest(ItDataTestCase):
    def test_FR_ITD2_AC_2_a_connection_serving_other_projects_is_marked_and_warned_before_turning_off(self):
        hooks.add_source(self.factory, "shared-events", scheme="standard", secret_env="ITD_EVENTS_SECRET",
                         person=IT[0], persona=IT[1], bind=[self.project.pid, self.notes.pid])
        items = by_id(views.project_view(self.project))
        wide, shared, own = items["relay:SUB-002"], items["hook:shared-events"], items["relay:SUB-001"]
        self.assertEqual((wide["scope"], shared["scope"], own["scope"]), ("platform", "shared", "project"))
        self.assertIn("every project", wide["disable"]["wide"])
        self.assertIn("1 other project", shared["disable"]["wide"])
        self.assertNotIn("wide", own["disable"])
        self.assertIsNone(itdata_actions.signs_on(self.factory, "relay:SUB-002", self.project), "on the platform")
        self.assertIsNone(itdata_actions.signs_on(self.factory, "hook:shared-events", self.project))
        self.assertEqual(itdata_actions.signs_on(self.factory, "relay:SUB-001", self.project), self.project.pid)
        out = assistant.ask(self.factory, "Turn off relay:SUB-002", persona="it", project_id=self.project.pid,
                            model=None)
        self.assertIn("Before you confirm: it serves every project", out["answer"])
        act = next(p for p in out["propose"] if p["action"] == "act")
        self.assertIn("for every project it serves", act["why"])
        done = itdata_actions.disable(self.factory, "relay:SUB-002", person=IT[0], persona=IT[1], project=self.project)
        self.assertIn("every project", done["wide"])
        self.assertTrue(self.project.ledger().of_kind("itdata_disabled")[-1]["event"]["payload"]["wide"])


class ChatTest(ItDataTestCase):
    def ask(self, question: str) -> dict:
        return assistant.ask(self.factory, question, persona="it", project_id=self.project.pid, model=None)

    def test_FR_ITD2_AC_3_how_to_questions_get_the_maps_answers_not_the_connection_list(self):
        self.assertIsNone(itdata_chat.answer(self.factory, "Can I connect with Slack?", self.project, "it"))
        for q, first in (("How do I connect to Teams?", "people_idp"), ("how do I connect to GitHub?", "adopt_project")):
            self.assertIsNone(itdata_chat.answer(self.factory, q, self.project, "it"), q)
            out = self.ask(q)                                   # in a project: never the connection list
            self.assertNotIn("itdata", out.get("matches") or [], q)
            self.assertNotIn("Data integrations:", out["answer"], q)
            out = assistant.ask(self.factory, q, persona="it", model=None)     # on the platform: the map's how-to
            self.assertEqual((out.get("matches") or [None])[0], first, (q, out.get("matches")))
        self.assertIsNone(itdata_chat.answer(self.factory, "stop SUB-1 from failing", self.project, "it"))
        self.assertIsNone(itdata_chat.answer(self.factory, "How do I stop SUB-001 from failing?", self.project, "it"))
        for q in ("What does this project connect to?", "What is it connected to?", "Which systems do we use?"):
            self.assertEqual(self.ask(q)["matches"], ["itdata"], q)
        self.assertIn("relay:SUB-001", self.ask("stop relay:SUB-001")["answer"])


class ConfidentialTest(ItDataTestCase):
    def test_FR_ITD2_AC_4_a_confidential_projects_agents_on_a_hosted_model_are_blocked_not_local(self):
        view = views.project_view(self.notes)
        agents = {a["id"]: a for a in view["agents"]}
        for role in ("analyst", "holdout_author", "builder", "verifier"):
            self.assertIn("Models setup", agents[role]["blocked"] or "", role)
            self.assertFalse(agents[role]["leaves"], role)
        self.assertIsNone(agents["assistant"]["blocked"], "its own model is local")
        subs = {n["agent"]: n["sub"] for n in view["flow"]["nodes"] if n["agent"]}
        self.assertEqual(subs["analyst"], "blocked: needs a local model")
        self.assertIsNone(views.project_view(self.project)["agents"][0]["blocked"], "not confidential: works")
        out = assistant.ask(self.factory, "Which data leaves the machine?", persona="it", project_id=self.notes.pid,
                            model=None)
        self.assertIn("blocked here, not working locally", out["answer"])
        self.assertIn("Analyst", out["answer"])


class FlowTest(ItDataTestCase):
    def test_FR_ITD2_AC_5_a_website_chats_answers_are_drawn_leaving_and_the_count_matches(self):
        embeds.create(self.factory, kind="feedback", origins=["https://shop.example.org"], person=IT[0],
                      persona=IT[1], project_id=self.project.pid, label="Shop")
        view = views.project_view(self.project)
        chat = next(x for x in view["items"] if x["kind"] == "chat")
        edges = {(e["from"], e["to"]): e for e in view["flow"]["edges"]}
        back = edges[("n:rihmasto", "n:" + chat["id"])]
        self.assertEqual((back["leaves"], back["label"]), (True, "answers"))
        self.assertIn("n:" + chat["id"], view["flow"]["leaving"])
        self.assertEqual(len(view["flow"]["leaving"]), len(view["summary"]["leaving"]),
                         "every connection data may leave through is a dashed line")


class EnforcedTurnOffTest(EnforcedCockpitCase):
    def setUp(self):
        super().setUp()
        isolated_routing(self, self.tmp)
        self.listener = fx.Listener()
        self.addCleanup(self.listener.stop)
        w = fx.build(self.factory.home, self.listener.port)
        self.project, self.notes = w["project"], w["notes"]
        os.environ.pop("ITD_EVENTS_SECRET", None)

    def test_FR_ITD2_AC_2_it_on_one_project_cannot_stop_a_channel_every_project_uses(self):
        pid = self.project.pid
        hooks.add_source(self.factory, "shared-events", scheme="standard", secret_env="ITD_EVENTS_SECRET",
                         person=IT[0], persona=IT[1], bind=[pid, self.notes.pid])
        doc = access_doc()
        doc["bindings"].append({"subject": DEV, "persona": "it", "scope": [pid]})
        self.enforce(doc)
        self.sign_in(DEV)
        self.sign_in(ADMIN)
        for item in ("relay:SUB-002", "hook:shared-events"):
            status, out = self.pcall("POST", "/api/it-data/disable", {"project": pid, "item": item, "persona": "it"},
                                     who=DEV)
            self.assertEqual(status, 403, (item, out))
        self.assertIn("SUB-002", [s["id"] for s in relay.subscriptions(self.factory)])
        self.assertIn("shared-events", [s["id"] for s in hooks.sources(self.factory) if s.get("state") == "active"])
        status, out = self.pcall("POST", "/api/it-data/disable", {"project": pid, "item": "relay:SUB-001",
                                                                   "persona": "it"}, who=DEV)
        self.assertEqual(status, 200, out)                     # the project's own: signed on the project
        status, out = self.pcall("POST", "/api/it-data/disable", {"project": pid, "item": "relay:SUB-002",
                                                                   "persona": "it", "reason": "moved"}, who=ADMIN)
        self.assertEqual((status, bool(out["wide"])), (200, True), out)
        self.assertNotIn("SUB-002", [s["id"] for s in relay.subscriptions(self.factory)])


if __name__ == "__main__":
    unittest.main()
