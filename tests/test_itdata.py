"""FR-ITD1: IT's view of integrations and data, its actions and Ask Rihma's answers (tests/itdata_fixture.py).

The owner (2026-11-25): "from IT perspective, you would want to view for integrations and the data side of things as
well". Every connection here is a neutral stand-in; a check reaches loopback only (itdata_fixture.offline).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import itdata_fixture as fx  # noqa: E402
from factory_fakes import isolated_routing  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import assistant, assistant_ops, itdata_actions, itdata_chat, relay  # noqa: E402
from kernel import itdata_project as views  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def by_id(view: dict) -> dict:
    return {x["id"]: x for x in view["items"]}


class ItDataTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-itd-")).resolve()
        isolated_routing(self, self.tmp)
        env = mock.patch.dict(os.environ, {"ORDERS_STAGING_TOKEN": fx.SECRET_VALUE})
        env.start()
        self.addCleanup(env.stop)
        for name in fx.VARS[1:]:
            os.environ.pop(name, None)
        self.listener = fx.Listener()
        self.addCleanup(self.listener.stop)
        w = fx.build(self.tmp / "home", self.listener.port)
        self.factory, self.project, self.notes = w["factory"], w["project"], w["notes"]
        self.calls = []
        patcher = mock.patch.object(itdata_actions, "connect", fx.offline(self.calls))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


class ViewTest(ItDataTestCase):
    def test_FR_ITD1_AC_1_a_project_lists_every_connection_with_where_it_is_its_access_and_credentials_by_name(self):
        before = tree(self.factory.home)
        view = views.project_view(self.project)
        self.assertEqual(tree(self.factory.home), before, "reading writes nothing")
        items = by_id(view)
        orders = items["integration:orders_api"]
        self.assertEqual((orders["direction"], orders["locality"], orders["access"], orders["data_classes"]),
                         ("both", "this machine", "read-write", ["confidential"]))
        self.assertEqual(orders["credentials"], [{"name": "ORDERS_API_TOKEN", "where": "environment variable "
                                                  "ORDERS_STAGING_TOKEN", "set": True}])
        self.assertIn("IT approves the binding on local", " ".join(orders["missing"]))
        self.assertEqual(orders["state"], "not set up")
        drive = items["integration:recordings"]
        self.assertEqual((drive["direction"], drive["locality"], drive["host"]), ("in", "outside", "www.googleapis.com"))
        teams = items["relay:SUB-001"]
        self.assertEqual((teams["locality"], teams["scope"]), ("not known", "project"))
        self.assertIn("DESK_TEAMS_URL is not set where Rihmasto runs", " ".join(teams["missing"]))
        self.assertEqual(items["relay:SUB-002"]["host"], "hooks.example.org")
        self.assertEqual(items["hook:order-events"]["direction"], "in")
        self.assertIn("model:go", items)
        self.assertIn("road:staging", items)
        names = {c["name"]: c for c in view["credentials"]}
        self.assertLessEqual({"ORDERS_API_TOKEN", "DESK_TEAMS_URL", "HOOK_SIGNING_SECRET", "ORDER_EVENTS_SECRET"},
                             set(names))
        self.assertNotIn(fx.SECRET_VALUE, json.dumps(view), "a value is never read into the view")

    def test_FR_ITD1_AC_2_the_platform_shows_every_connection_each_projects_integrations_and_the_data_stores(self):
        view = views.platform_view(self.factory)
        items = by_id(view)
        for iid in ("relay:SUB-001", "relay:SUB-002", "hook:order-events", "model:go", "model:local", "road:local"):
            self.assertIn(iid, items)
        self.assertEqual(items["model:go"]["locality"], "outside")
        self.assertEqual(items["model:local"]["locality"], "this machine")
        self.assertTrue(all(x["state"] == "off" for x in view["items"] if x["kind"] == "connector"))
        desk = next(p for p in view["projects"] if p["pid"] == self.project.pid)
        self.assertEqual([(i["name"], i["access"], i["data_classes"]) for i in desk["integrations"]],
                         [("orders_api", "read-write", ["confidential"]), ("recordings", "read", ["internal"])])
        self.assertTrue(next(p for p in view["projects"] if p["pid"] == self.notes.pid)["confidential"])
        stores = {s["store"]: s for s in view["stores"]["stores"]}
        self.assertIn("relay", stores)
        self.assertTrue(stores["projects"]["retention"])
        self.assertEqual(view["stores"]["integrity"]["broken"], [])
        self.assertIn("may send data outside", view["summary"]["line"])

    def test_FR_ITD1_AC_3_the_data_flow_and_what_each_agent_may_reach(self):
        view = views.project_view(self.project)
        flow = view["flow"]
        cols = {n["id"]: n["column"] for n in flow["nodes"]}
        self.assertEqual(cols["n:integration:orders_api"], "sources")
        self.assertEqual(cols["n:rihmasto"], "rihmasto")
        self.assertEqual(cols["n:agent:builder"], "agents")
        self.assertEqual(cols["n:model:go"], "destinations")
        edges = {(e["from"], e["to"]): e for e in flow["edges"]}
        self.assertTrue(edges[("n:agent:builder", "n:model:go")]["leaves"])
        self.assertFalse(edges[("n:agent:product", "n:integration:orders_api")]["leaves"])   # writes, on loopback
        self.assertTrue(edges[("n:rihmasto", "n:relay:SUB-002")]["leaves"])
        self.assertIn("n:model:go", flow["leaving"])
        self.assertTrue(all(n["item"] in by_id(view) for n in flow["nodes"] if n["item"]), "each node opens one")
        agents = {a["id"]: a for a in view["agents"]}
        self.assertIn("stand-in", agents["builder"]["reaches"])
        self.assertIn("secret values", agents["assistant"]["never"])
        self.assertIn("orders_api", agents["product"]["reaches"])
        secret = views.project_view(self.notes)
        go = by_id(secret)["model:go"]
        self.assertTrue(secret["confidential"] and go["refused"])
        self.assertNotIn("n:model:go", secret["flow"]["leaving"], "a confidential project never calls it")


class ActionsTest(ItDataTestCase):
    def test_FR_ITD1_AC_4_check_now_is_signed_keeps_each_result_and_opens_only_a_tcp_connection(self):
        home = self.factory.home
        before = tree(home)
        with self.assertRaises(DecisionRefused):
            itdata_actions.check(self.factory, person="system", persona="it", project=self.project)
        with self.assertRaises(DecisionRefused):
            itdata_actions.check(self.factory, person="Bea Example", persona="business_owner", project=self.project)
        self.assertEqual(tree(home), before)
        out = itdata_actions.check(self.factory, person="Olli Example", persona="operations", project=self.project)
        got = {r["id"]: r for r in out["results"]}
        self.assertFalse(got["relay:SUB-002"]["ok"])                        # outside: refused by the stand-in
        self.assertEqual(got["relay:SUB-002"]["failures"], 1)
        self.assertFalse(got["integration:orders_api"]["ok"])               # not approved by IT yet
        self.assertIn("approves the binding", got["integration:orders_api"]["why"])
        self.assertIsNone(got["road:staging"]["ok"])
        self.assertTrue(all(len(c) == 2 for c in self.calls), "a host and a port, nothing else")
        again = itdata_actions.check(self.factory, person="Olli Example", persona="operations", project=self.project,
                                     item="relay:SUB-002")
        self.assertEqual(again["results"][0]["failures"], 2, "failures in a row")
        view = by_id(views.project_view(self.project))
        self.assertEqual((view["relay:SUB-002"]["state"], view["relay:SUB-002"]["health"]["failures"]), ("failing", 2))
        rec = self.project.ledger().of_kind("itdata_checked")
        self.assertEqual((rec[-1]["event"]["payload"]["person"], rec[-1]["event"]["payload"]["failing"]),
                         ("Olli Example", ["Signed webhook events (SUB-002)"]))
        self.assertNotIn(fx.SECRET_VALUE, (home / "itdata" / "health.json").read_text(encoding="utf-8"))
        with self.assertRaises(KeyError):
            itdata_actions.check(self.factory, person="Olli Example", persona="it", item="relay:SUB-999")

    def test_FR_ITD1_AC_4_a_connection_that_answers_passes_with_its_latency(self):
        from kernel import itdata

        x = itdata.item("model:t", "model", "t", direction="out", where="this machine",
                        probe={"host": "127.0.0.1", "port": self.listener.port})
        r = itdata_actions.check_one(x)
        self.assertTrue(r["ok"])
        self.assertIsInstance(r["latency_ms"], int)

    def test_FR_ITD1_AC_5_it_turns_a_connection_off_through_its_own_rule_and_elsewhere_says_where(self):
        with self.assertRaises(DecisionRefused):
            itdata_actions.disable(self.factory, "relay:SUB-001", person="Aino Example", persona="developer",
                                   project=self.project)
        out = itdata_actions.disable(self.factory, "relay:SUB-001", person="Ilkka Example", persona="it",
                                     reason="the desk moved to email", project=self.project)
        self.assertEqual(out["disabled"], "relay:SUB-001")
        self.assertNotIn("SUB-001", [s["id"] for s in relay.subscriptions(self.factory)])
        rec = self.project.ledger().of_kind("itdata_disabled")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["reason"]), ("Ilkka Example", "the desk moved to email"))
        itdata_actions.disable(self.factory, "hook:order-events", person="Ilkka Example", persona="it")
        self.assertNotIn("hook:order-events", by_id(views.platform_view(self.factory, stores=False)))
        with self.assertRaises(itdata_actions.NotHere) as caught:
            itdata_actions.disable(self.factory, "model:go", person="Ilkka Example", persona="it")
        self.assertIn("Models setup", str(caught.exception))

    def test_FR_ITD1_AC_6_a_rotation_reminder_names_the_credential_and_its_date_never_its_value(self):
        with self.assertRaises(DecisionRefused):
            itdata_actions.remind_rotation(self.factory, "ORDERS_API_TOKEN", person="Aino Example",
                                           persona="developer", project=self.project)
        with self.assertRaises(KeyError) as caught:
            itdata_actions.remind_rotation(self.factory, "NOT_A_NAME", person="Ilkka Example", persona="it",
                                           project=self.project)
        self.assertIn("ORDERS_API_TOKEN", str(caught.exception))
        with self.assertRaises(ValueError):
            itdata_actions.remind_rotation(self.factory, "ORDERS_API_TOKEN", person="Ilkka Example", persona="it",
                                           days=0, project=self.project)
        out = itdata_actions.remind_rotation(self.factory, "ORDERS_API_TOKEN", person="Ilkka Example", persona="it",
                                             days=30, project=self.project)
        self.assertEqual(out["due"], "2026-12-25")
        cred = {c["name"]: c for c in views.project_view(self.project)["credentials"]}["ORDERS_API_TOKEN"]
        self.assertEqual((cred["rotation"]["due"], cred["rotation"]["overdue"]), ("2026-12-25", False))
        self.factory.clock.advance(days=31)
        cred = {c["name"]: c for c in views.project_view(self.project)["credentials"]}["ORDERS_API_TOKEN"]
        self.assertTrue(cred["rotation"]["overdue"])
        rec = self.project.ledger().of_kind("credential_rotation_reminder")[-1]["event"]["payload"]
        self.assertEqual((rec["name"], rec["due"], rec["person"]), ("ORDERS_API_TOKEN", "2026-12-25", "Ilkka Example"))
        self.assertNotIn(fx.SECRET_VALUE, json.dumps(self.project.ledger().records()))


class ChatTest(ItDataTestCase):
    def ask(self, question: str, project=None, persona: str = "it") -> dict:
        return assistant.ask(self.factory, question, persona=persona,
                             project_id=project.pid if project is not None else None, model=None)

    def test_FR_ITD1_AC_7_ask_rihma_answers_what_it_connects_to_and_which_data_leaves_by_rule(self):
        out = self.ask("What does this project connect to?", self.project)
        self.assertEqual((out["by"], out["navigate"]["route"]), ("map", f"#/p/{self.project.pid}/itdata"))
        for words in ("orders_api", "recordings", "Teams notices (SUB-001)", "go (opencode.ai)"):
            self.assertIn(words, out["answer"])
        out = self.ask("Which data leaves the machine?", self.project)
        self.assertIn("opencode.ai", out["answer"])
        self.assertIn("hooks.example.org", out["answer"])
        self.assertIn("not known here", out["answer"])                   # SUB-001's address is in a variable
        self.assertEqual(out["navigate"]["control"], "itdata_flow")
        out = self.ask("Which data leaves the machine?", self.notes)
        self.assertIn("confidential, so these are never called", out["answer"])
        out = self.ask("What does the platform connect to?")
        self.assertEqual(out["navigate"]["route"], "#/connections")
        self.assertNotIn(fx.SECRET_VALUE, json.dumps(out))
        self.assertIsNone(itdata_chat.answer(self.factory, "How is the build going?", self.project, "it"))

    def test_FR_ITD1_AC_7_asked_to_act_it_proposes_the_same_signed_write_a_button_makes(self):
        out = self.ask("Please check the integrations", self.project)
        act = next(p for p in out["propose"] if p["action"] == "act")
        self.assertEqual(act["args"]["call"], {"method": "POST", "path": "/api/it-data/check",
                                               "body": {"project": self.project.pid}})
        out = self.ask("Turn off relay:SUB-002", self.project)
        act = next(p for p in out["propose"] if p["action"] == "act")
        self.assertEqual(act["args"]["call"]["body"]["item"], "relay:SUB-002")
        out = self.ask("Remind me to rotate ORDERS_API_TOKEN in 45 days", self.project)
        act = next(p for p in out["propose"] if p["action"] == "act")
        self.assertEqual(act["args"]["call"]["body"], {"project": self.project.pid, "credential": "ORDERS_API_TOKEN",
                                                       "days": 45})
        for op in ("check_integrations", "disable_connection", "remind_rotation"):
            self.assertIn(op, assistant_ops.OPS)
        self.assertEqual(self.project.ledger().of_kind("itdata_checked"), [], "proposing writes nothing")


class RoutesTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        isolated_routing(self, self.tmp)
        self.listener = fx.Listener()
        self.addCleanup(self.listener.stop)
        w = fx.build(self.factory.home, self.listener.port)
        self.project = w["project"]
        patcher = mock.patch.object(itdata_actions, "connect", fx.offline([]))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_FR_ITD1_AC_8_the_cockpit_serves_both_views_and_each_signed_write(self):
        pid = self.project.pid
        status, view, _ = self.call("GET", f"/api/projects/{pid}/it-data")
        self.assertEqual(status, 200, view)
        self.assertIn("integration:orders_api", by_id(view))
        status, plat, _ = self.call("GET", "/api/it-data")
        self.assertEqual((status, bool(plat["stores"]["stores"])), (200, True))
        status, out, _ = self.call("POST", "/api/it-data/check", {"project": pid, "item": "relay:SUB-001",
                                                                   "person": "Olli Example", "persona": "operations"})
        self.assertEqual((status, out["failing"]), (200, ["Teams notices (SUB-001)"]), out)
        status, out, _ = self.call("POST", "/api/it-data/check", {"item": "relay:SUB-404", "person": "Olli Example",
                                                                   "persona": "it"})
        self.assertEqual(status, 404, out)
        status, out, _ = self.call("POST", "/api/it-data/disable", {"item": "model:go", "person": "Ilkka Example",
                                                                     "persona": "it"})
        self.assertEqual(status, 409, out)
        self.assertIn("Models setup", out["error"])
        status, out, _ = self.call("POST", "/api/it-data/disable", {"item": "relay:SUB-002", "person": "Ilkka Example",
                                                                     "persona": "developer"})
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("POST", "/api/it-data/rotate-reminder", {"project": pid, "credential": "ORDERS_API_TOKEN",
                                                                             "person": "Ilkka Example", "persona": "it"})
        self.assertEqual((status, out["due"]), (200, "2027-02-20"), out)


if __name__ == "__main__":
    unittest.main()
