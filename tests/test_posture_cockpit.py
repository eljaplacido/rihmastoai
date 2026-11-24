"""Postures in the cockpit's API, the MCP server and the assistant's map (FR-POS6-AC-1, FR-POS6-AC-2), and
the reads that list what a persona may decide, which follow a card a posture narrowed (FR-POS7-AC-6).

The real cockpit server on a loopback port and the real MCP server in process, over a temp factory.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import model  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel.assistant import from_map  # noqa: E402
from kernel.assistant_rules import check_proposal  # noqa: E402
from kernel.assistant_snapshot import snapshot  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.plan import gate as plan_gate  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.posture import lines, of, preview  # noqa: E402
from mcp.server import RihmaMCP  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class PostureApiTest(CockpitTestCase):
    def kinds(self, project) -> list:
        return [r["event"]["kind"] for r in project.ledger().records()]

    def test_FR_POS6_AC_1_the_cockpit_previews_creates_shows_and_changes_a_posture_through_its_api(self):
        status, meta, _ = self.call("GET", "/api/meta")
        self.assertEqual([p["id"] for p in meta["postures"]["postures"]], ["prototype", "balanced", "production", "regulated"])
        self.assertEqual(self.call("GET", "/api/postures")[1], meta["postures"])
        # the preview is the kernel's own, and it records nothing
        before = sorted(str(p) for p in self.factory.home.rglob("*"))
        status, shown, _ = self.call("POST", "/api/postures/preview", {"posture": "production", "weights": {"ux": 3},
                                                                        "profile": "web_service"})
        self.assertEqual((status, shown["lines"]), (200, preview("production", {"ux": 3}, profile="web_service")["lines"]))
        self.assertEqual(sorted(str(p) for p in self.factory.home.rglob("*")), before)
        for bad, code in (({"posture": "reckless"}, 400), ({"posture": "balanced", "weights": {"ux": "3"}}, 400),
                          ({"posture": "balanced", "weights": {"ux": 9}}, 400),
                          ({"posture": "prototype", "maturity": "production"}, 400)):
            self.assertEqual(self.call("POST", "/api/postures/preview", bad)[0], code, bad)
        # a project made with a posture: its mode and maturity, and who chose it
        status, made, _ = self.call("POST", "/api/projects", {
            "title": "Equipment loans", "source": IDEA, "profile": "web_service", "posture": "regulated",
            "weights": {"ux": 2}, "requested_by": "Aino", "persona": "business_owner"})
        self.assertEqual(status, 201, made)
        pid = made["project"]["id"]
        self.assertEqual((made["project"]["mode"], made["project"]["maturity"], made["project"]["posture"]["name"]),
                         ("socratic", "pilot", "regulated"))
        p = self.factory.project(pid)
        chosen = [r["event"]["payload"] for r in p.ledger().of_kind("posture_chosen")][0]
        self.assertEqual((chosen["by"], chosen["persona"], chosen["shown"]), ("Aino", "business_owner", lines(of(p))))
        self.assertEqual(self.call("POST", "/api/projects", {
            "title": "T", "source": IDEA, "posture": "production", "maturity": "demo", "requested_by": "Aino",
            "persona": "business_owner"})[0], 400)
        plain = self.call("POST", "/api/projects", {"title": "Plain", "source": IDEA, "requested_by": "Aino",
                                                     "persona": "business_owner"})[1]["project"]
        self.assertEqual((plain["mode"], plain["maturity"], "posture" in plain), ("mixed", "demo", False))
        # the project's posture: what it does and what holds it now
        status, view, _ = self.call("GET", f"/api/projects/{pid}/posture")
        self.assertEqual((status, view["posture"]["posture"], view["cap"]), (200, "regulated", 4))
        self.assertEqual(view["lines"], lines(of(p)))
        self.assertIsNone(self.call("GET", f"/api/projects/{plain['id']}/posture")[1]["posture"])
        self.assertIsNone(self.call("GET", "/api/projects/_factory/posture")[1]["posture"])
        # what a change would do, before anyone makes it; then the change, signed and audited
        intake(p, IDEA, model=model(), requested_by="Aino")
        status, ahead, _ = self.call("POST", "/api/postures/preview", {"posture": "prototype", "project": pid})
        self.assertEqual(status, 200)
        self.assertIn("autonomy 1 to 3", ahead["loosens"])
        self.assertTrue(any(x.startswith("mode socratic to assume") for x in ahead["later"]))
        refused = self.call("PUT", f"/api/projects/{pid}/posture", {"posture": "prototype", "reason": "faster",
                                                                     "person": "Pia", "persona": "product_owner"})
        self.assertEqual(refused[0], 403)
        self.assertIn("loosens", refused[1]["error"])
        self.assertEqual(self.call("PUT", f"/api/projects/{pid}/posture", {
            "posture": "balanced", "person": "Aino", "persona": "business_owner"})[0], 400)     # no reason
        status, out, _ = self.call("PUT", f"/api/projects/{pid}/posture", {
            "posture": "production", "weights": {"security": 3}, "reason": "the pilot is enough", "person": "Aino",
            "persona": "business_owner"})
        self.assertEqual((status, out["posture"], out["maturity"]), (200, "production", "pilot"), out)
        self.assertIn("cockpit_write", self.kinds(p))
        rec = [r["event"]["payload"] for r in p.ledger().of_kind("posture_changed")][-1]
        self.assertEqual((rec["by"], rec["reason"], rec["now"], rec["later"]),
                         ("Aino", "the pilot is enough", out["now"], out["later"]))
        self.assertEqual(Canon(p).get_card(Canon(p).cards()[0]["id"])["kind"], "question")


class PostureReadsTest(CockpitTestCase):
    def test_FR_POS6_AC_2_the_mcp_server_reads_a_projects_posture_and_the_map_takes_a_person_to_it(self):
        p = self.factory.new_project("Equipment loans", posture={"name": "balanced", "weights": {"security": 2},
                                                                "by": "Aino", "persona": "business_owner"})
        intake(p, IDEA, model=model(), requested_by="Aino")
        before = len(p.ledger().records())
        server = RihmaMCP(self.factory, person="Tessa", persona="developer", lanes_root=self.tmp / "no-lanes")
        answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "rihma_project", "arguments": {"pid": p.pid}}})
        got = answer["result"]["structuredContent"]["posture"]
        self.assertEqual((got["posture"]["posture"], got["posture"]["autonomy"], got["posture"]["chosen_by"]),
                         ("balanced", 2, "Aino"))
        self.assertEqual(got["lines"], lines(of(p)))
        self.assertIn("holds", got)
        self.assertNotIn("effects", got)
        self.assertEqual(len(p.ledger().records()), before)                     # a read writes nothing
        plain = self.factory.new_project("Plain")
        answer = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": "rihma_project", "arguments": {"pid": plain.pid}}})
        self.assertIsNone(answer["result"]["structuredContent"]["posture"]["posture"])
        # the assistant's map: where the posture is, and Take me there opens the project with it
        said = from_map("Where do I change the posture and its priority weights?", p)
        self.assertEqual(said["matches"][0], "posture")
        self.assertEqual(said["navigate"], {"route": f"#/p/{p.pid}/overview", "control": "posture"})
        status, ui, _ = self.call("GET", "/api/ui-map")
        self.assertIn("posture", [c["id"] for c in ui["controls"]])


class NarrowedDecidersReadTest(CockpitTestCase):
    def test_FR_POS7_AC_6_every_list_of_what_a_persona_may_decide_follows_a_cards_narrowed_deciders(self):
        p = self.factory.new_project("Equipment loans", maturity="demo", posture={
            "name": "regulated", "weights": None, "by": "Aino", "persona": "business_owner"})
        intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        for q in canon.questions("open"):
            canon.answer(q["id"], q["opinions"].get(q["perspective"]) or "yes", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        cid = plan_gate(p, model=model())["waiting_on"][0]
        self.assertEqual(canon.get_card(cid)["deciders"], ["business_owner"])   # the posture narrowed them
        with self.assertRaises(DecisionRefused):
            canon.decide(cid, "approve", person="Dev Person", persona="developer")

        def tool(server, name, args):
            return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": args}})["result"]["structuredContent"]

        for persona, listed in (("developer", False), ("business_owner", True)):
            def inbox(path):
                return [c["id"] for c in self.call("GET", f"{path}?persona={persona}")[1]["cards"]]

            server = RihmaMCP(self.factory, person="Dev Person", persona=persona, lanes_root=self.tmp / "no-lanes")
            seen = {"canon": [c["id"] for c in canon.cards(persona=persona)],
                    "project inbox": inbox(f"/api/projects/{p.pid}/inbox"), "inbox": inbox("/api/inbox"),
                    "rihma_project": [c["id"] for c in tool(server, "rihma_project", {"pid": p.pid})["cards_you_may_decide"]],
                    "rihma_waiting": [i["card"] for i in tool(server, "rihma_waiting", {})["items"]
                                      if i["project"] == p.pid]}
            seen["assistant"] = [c["card"] for c in snapshot(self.factory, persona=persona)["factory"]["waiting_cards"]
                                 if c["project"] == p.pid and c["yours"]]
            refused = check_proposal(self.factory, p, persona, {"action": "decide", "args": {
                "card": cid, "verdict": "approve", "reason": "go"}})
            seen["assistant proposal"] = [cid] if refused is None else []
            for where, ids in seen.items():
                self.assertEqual(cid in ids, listed, f"{where} as {persona}: {ids}")
        # the dashboard's decisions name the card's own deciders, so the page shows who it waits on
        item = next(i for i in self.call("GET", "/api/dashboard")[1]["decisions"] if i["card"] == cid)
        self.assertEqual(item["deciders"], ["business_owner"])


if __name__ == "__main__":
    unittest.main()
