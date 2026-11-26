"""FR-HITL2: People in the loop end to end. A link made by Ask Rihma or renewed by a Nudge is shown once where it
was made (with a warning when it points at this computer only); a withdrawn link takes its asks back; a nudge counts
only once it reached someone; an outside ask nudges in solo mode; Ask Rihma sends a named ask, reaches IT and sets a
level for all projects; a rule for every project is signed on the factory; holds show in Now and the Inbox; an ask
put to another persona says how to answer it; failed tries behind one proxy never lock a reviewer out. The browser
half is tests/test_hitl_fix_ui.py. Nothing is ever sent anywhere but 127.0.0.1."""

import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import hitl, hitl_chat, hitl_links, hitl_nudge, hitl_page, relay  # noqa: E402
from kernel.assistant import ask as rihma  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.learn import FACTORY_PID, factory_project  # noqa: E402
from kernel.status import now  # noqa: E402

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OK = (lambda url, body, headers: 200)
SLACK = {"SLACK_URL": "http://127.0.0.1:9/slack"}
AINO = {"person": "Aino Example", "persona": "business_owner"}


def opened(base, token, forwarded=None):
    headers = {"Origin": base, "Content-Type": "application/json"}
    if forwarded:
        headers["X-Forwarded-For"] = forwarded
    req = urllib.request.Request(base + "/r/api/open", data=json.dumps({"link": token}).encode(), headers=headers,
                                 method="POST")
    try:
        with _DIRECT.open(req, timeout=10) as res:
            return res.status
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code


class Loop:
    def legal(self, p, text="May we keep the loan history for two years?", **kw):
        return hitl.ask(p, text=text, **({"family": "legal"} | kw), **AINO)

    def link(self, p, asks=("HQ-001",), **kw):
        args = {"name": "Maria Example", "persona": "compliance", "asks": list(asks), "person": "Aino Example",
                "creator_persona": "business_owner"} | kw
        return hitl_links.create(p, **args)


class RouteCase(Loop, CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Tool loans")
        self.base = f"/api/projects/{self.p.pid}/hitl"

    def give(self, **kw):
        status, out, _ = self.call("POST", self.base + "/links", {"name": "Maria Example", "asks": ["HQ-001"]}
                                   | AINO | kw)
        self.assertEqual(status, 201, out)
        return out


class ShownOnceTest(RouteCase):
    def test_FR_HITL2_AC_1_a_link_made_by_ask_rihma_comes_back_once_to_show_with_a_local_warning(self):
        self.legal(self.p)
        said = rihma(self.factory, "give Maria Example a link for the legal questions", persona="business_owner",
                     project_id=self.p.pid)
        self.assertIn("shown here once, with Copy", said["answer"])
        self.assertIn("IT has not set where outside links point", said["answer"])
        call = said["propose"][0]["args"]["call"]                       # what Confirm sends, signed
        status, out, _ = self.call(call["method"], call["path"], call["body"] | AINO)
        self.assertEqual(status, 201, out)
        once = out["once"][0]
        self.assertEqual((once["link"], once["name"], once["url"]), ("RL-001", "Maria Example", out["url"]))
        self.assertIn("/r/#rv_", once["url"])
        self.assertIn("nobody outside can open it", out["warning"])     # the cockpit is on 127.0.0.1
        self.assertIn("shown once below", out["said"])
        status, view, _ = self.call("GET", self.base)
        self.assertTrue(view["link_base_local"])
        self.assertNotIn(once["url"].split("#")[1], json.dumps(view))   # shown once, then never
        self.call("PUT", "/api/hitl/channels", {"link_base": "https://review.example.org", "person": "Ilkka",
                                                "persona": "it"})
        self.legal(self.p, text="Second question?")
        out = self.give(asks=["HQ-002"])
        self.assertNotIn("warning", out)
        self.assertTrue(out["url"].startswith("https://review.example.org/r/#rv_"))
        self.assertFalse(self.call("GET", self.base)[1]["link_base_local"])
        again = rihma(self.factory, "give Maria Example a link for the legal questions", persona="business_owner",
                      project_id=self.p.pid)
        self.assertNotIn("IT has not set", again["answer"])

    def test_FR_HITL2_AC_1_a_nudge_that_renews_an_outside_link_shows_the_new_address_once(self):
        self.legal(self.p)
        first = self.give()
        self.clock.advance(hours=30)
        status, out, _ = self.call("POST", self.base + "/nudge", AINO)
        self.assertEqual(status, 200, out)
        self.assertEqual([o["link"] for o in out["once"]], ["RL-002"])
        fresh = out["once"][0]["url"]
        self.assertIn("A new link for Maria Example (RL-002) is shown once", out["said"])
        self.assertIn("nobody outside can open it", out["said"])
        self.assertEqual(opened(self.origin, first["url"].split("#")[1]), 403)   # the old one ended
        self.assertEqual(opened(self.origin, fresh.split("#")[1]), 200)          # the new one is in hand

    def test_FR_HITL2_AC_1_a_fresh_link_whose_send_failed_is_shown_too(self):
        self.legal(self.p)
        self.give(channel="whatsapp", address="+358401234567")           # WhatsApp is not set up: not sent
        self.clock.advance(hours=30)
        out = hitl_nudge.nudge(self.p, base="https://review.example.org", environ={}, **AINO)
        self.assertEqual(out["once"][0]["link"], "RL-002")
        self.assertTrue(out["once"][0]["url"].startswith("https://review.example.org/r/#rv_"))
        self.assertNotIn("warning", out)


class RevokeTest(Loop, FactoryTestCase):
    def test_FR_HITL2_AC_2_a_withdrawn_link_takes_its_asks_back_and_no_nudge_renews_it(self):
        p = self.new()
        self.legal(p)
        link = self.link(p)
        self.assertTrue(hitl.get(p, "HQ-001")["to"]["external"])
        hitl_links.revoke(p, link["id"], why="wrong person", **{"person": "Aino Example", "persona": "business_owner"})
        to = hitl.get(p, "HQ-001")["to"]
        self.assertEqual((to["external"], to["link"], to["person"], to["withdrawn_from"]),
                         (False, None, None, "Maria Example"))
        self.clock.advance(hours=30)
        row = hitl_nudge.due(p, solo=False)[0]
        self.assertEqual((row["external"], row["link"], row["to"]), (False, None, ["compliance"]))
        relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["compliance"], person="Ilkka",
                        persona="it")
        out = hitl_nudge.nudge(p, base="", environ=SLACK, post=OK, solo=False, **AINO)
        self.assertEqual((out["count"], out["once"]), (1, []))
        self.assertEqual([r["id"] for r in hitl_links.links(self.factory)], ["RL-001"])   # no RL-002 for her
        rec = p.ledger().of_kind("hitl_link_revoked")[-1]["event"]["payload"]
        self.assertEqual(rec["asks_back"], ["HQ-001"])

    def test_FR_HITL2_AC_2_an_ask_on_a_link_withdrawn_before_this_fix_is_the_personas_again(self):
        p = self.new()
        self.legal(p)
        link = self.link(p)
        with mock.patch.object(hitl, "unaddress", lambda project, link_id: []):   # as records made before it
            hitl_links.revoke(p, link["id"], person="Aino Example", persona="business_owner")
        self.assertTrue(hitl.get(p, "HQ-001")["to"]["external"])
        self.clock.advance(hours=30)
        self.assertEqual(hitl_nudge.due(p, solo=False)[0]["external"], False)


class HonestNudgeTest(Loop, FactoryTestCase):
    def test_FR_HITL2_AC_3_a_nudge_with_no_channel_stays_due_says_what_IT_adds_then_goes(self):
        p = self.new()
        hitl.ask(p, text="Is TLS on?", family="security", **AINO)
        self.clock.advance(hours=25)
        out = hitl_nudge.nudge(p, base="", environ={}, solo=False, **AINO)
        self.assertEqual(out["count"], 0)
        self.assertNotIn("nudge(s) sent", out["said"])
        self.assertIn("Not sent, so still due: HQ-001: No channel reaches the it yet", out["said"])
        self.assertIn("rihmasto relay subscribe --sink teams --notify it", out["said"])
        self.assertEqual(hitl.get(p, "HQ-001")["nudged"], {})           # the step is still open
        self.assertEqual(p.ledger().of_kind("hitl_nudged"), [])
        self.assertEqual(p.ledger().of_kind("hitl_nudge_asked")[-1]["event"]["payload"]["not_sent"], 1)
        self.assertTrue(hitl_nudge.due(p, solo=False)[0]["to_send"])
        self.assertEqual(hitl_nudge.relay_round(self.factory, environ={}, post=OK, send=None), 0)
        relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["it"], person="Ilkka",
                        persona="it")                                     # IT adds a channel
        out = hitl_nudge.nudge(p, base="", environ=SLACK, post=OK, solo=False, **AINO)
        self.assertEqual((out["count"], out["said"]), (1, "1 nudge(s) sent."))
        self.assertIn("nudge", hitl.get(p, "HQ-001")["nudged"])

    def test_FR_HITL2_AC_3_a_failed_delivery_is_not_counted_either(self):
        p = self.new()
        hitl.ask(p, text="Is TLS on?", family="security", **AINO)
        relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["it"], person="Ilkka",
                        persona="it")
        self.clock.advance(hours=25)
        out = hitl_nudge.nudge(p, base="", environ=SLACK, post=lambda u, b, h: 500, solo=False, **AINO)
        self.assertEqual(out["count"], 0)
        self.assertIn("HTTP 500", out["said"])


class SoloOutsideTest(Loop, FactoryTestCase):
    def test_FR_HITL2_AC_4_in_solo_an_outside_ask_is_nudged_and_an_inside_advised_one_waits(self):
        p = self.new()
        self.legal(p)
        hitl.ask(p, text="Is the copy clear?", family="quality", **AINO)
        self.link(p)
        self.clock.advance(hours=30)
        rows = {r["ask"]: r for r in hitl_nudge.due(p, solo=True)}
        self.assertEqual((rows["HQ-001"]["quiet"], rows["HQ-001"]["to_send"]), (False, True))
        self.assertEqual((rows["HQ-002"]["quiet"], rows["HQ-002"]["to_send"]), (True, False))
        out = hitl_nudge.nudge(p, base="https://review.example.org", environ={}, solo=True, **AINO)
        self.assertEqual([o["link"] for o in out["once"]], ["RL-002"])
        self.assertEqual(hitl.get(p, "HQ-001")["to"]["link"], "RL-002")


class ChatTest(Loop, FactoryTestCase):
    def say(self, p, question):
        return rihma(self.factory, question, persona="business_owner", project_id=p.pid)

    def test_FR_HITL2_AC_5_naming_an_ask_sends_it_and_never_copies_it(self):
        p = self.new()
        hitl.ask(p, text="Is the admin page behind sign-in?", family="security", **AINO)
        out = self.say(p, "send HQ-001 to the legal reviewer")
        self.assertEqual(out["propose"][0]["args"]["call"], {"method": "POST", "path": f"/api/projects/{p.pid}/hitl/send",
                                                             "body": {"ask": "HQ-001"}})
        self.assertIn("HQ-001 is put to IT / partner", out["answer"])
        self.assertIn("You named Compliance", out["answer"])
        self.assertEqual(out["navigate"]["control"], "hitl_send")
        self.assertEqual(len(hitl.asks(p)), 1)                              # nothing copied
        self.assertIn("There is no HQ-009", self.say(p, "send HQ-009")["answer"])

    def test_FR_HITL2_AC_5_words_for_IT_become_an_ask_to_IT_that_says_nothing_is_sent_yet(self):
        p = self.new()
        out = self.say(p, "send the security question to IT: is TLS on?")
        self.assertEqual(out["propose"][0]["args"]["call"]["body"],
                         {"text": "is TLS on?", "kind": "question", "family": "security", "to_persona": "it"})
        self.assertIn("nothing is sent until you press Send to their channels", out["answer"])
        self.assertNotIn("It goes to their channels", out["answer"])
        out = self.say(p, "send it to compliance: Do we log consent?")
        self.assertEqual(out["propose"][0]["args"]["call"]["body"]["to_persona"], "compliance")
        self.assertIsNone(hitl_chat.answer(self.factory, "send it now please", p, "business_owner"))

    def test_FR_HITL2_AC_5_a_level_for_all_projects_is_proposed_platform_wide(self):
        p = self.new()
        out = self.say(p, "require security checks for all projects")
        self.assertEqual(out["propose"][0]["args"]["call"]["body"],
                         {"family": "security", "level": "require", "scope": "platform"})
        self.assertIn("for all projects", out["answer"])
        out = self.say(p, "require security checks on this project")
        self.assertEqual(out["propose"][0]["args"]["call"]["body"]["scope"], "project")


class PlatformScopeTest(Loop, CockpitTestCase):
    def test_FR_HITL2_AC_6_a_rule_for_every_project_is_signed_on_the_factory_and_on_its_record(self):
        from cockpit import server

        p = self.new(title="Tool loans")
        seen = []
        real = server.Api._who

        def spy(api, body, pid):
            seen.append(pid)
            return real(api, body, pid)

        base = f"/api/projects/{p.pid}/hitl/enforcement"
        with mock.patch.object(server.Api, "_who", spy):
            status, out, _ = self.call("PUT", base, {"family": "legal", "level": "require", "scope": "platform",
                                                     "person": "Kaisa Example", "persona": "compliance"})
            self.assertEqual(status, 200, out)
            self.call("PUT", base, {"family": "quality", "level": "require", "person": "Kaisa Example",
                                    "persona": "compliance"})
        self.assertEqual(seen, [FACTORY_PID, p.pid])
        rec = factory_project(self.factory).ledger().of_kind("hitl_enforcement_set")[-1]["event"]["payload"]
        self.assertEqual((rec["family"], rec["scope"], rec["from_project"]), ("legal", "platform", p.pid))
        self.assertEqual(hitl.level(self.new(title="Room bookings"), "legal"), ("require", "platform-wide"))

    def test_FR_HITL2_AC_6_a_grant_refused_on_the_factory_refuses_the_platform_rule(self):
        from cockpit import server

        p = self.new(title="Tool loans")

        def only_projects(api, body, pid):
            if pid == FACTORY_PID:
                raise server.ApiError(403, "refused: compliance is granted on one project only")
            return body["person"], body["persona"]

        with mock.patch.object(server.Api, "_who", only_projects):
            status, out, _ = self.call("PUT", f"/api/projects/{p.pid}/hitl/enforcement",
                                       {"family": "legal", "level": "require", "scope": "platform",
                                        "person": "Kaisa Example", "persona": "compliance"})
            self.assertEqual(status, 403, out)
            status, _, _ = self.call("PUT", f"/api/projects/{p.pid}/hitl/enforcement",
                                     {"family": "legal", "level": "require", "person": "Kaisa Example",
                                      "persona": "compliance"})
            self.assertEqual(status, 200)
        self.assertEqual(hitl.settings(self.factory).get("enforcement"), {})


class HoldsTest(Loop, CockpitTestCase):
    def test_FR_HITL2_AC_7_a_required_answer_shows_in_the_now_line_and_the_project_payload(self):
        p = self.new(title="Tool loans")
        self.legal(p)
        self.assertNotIn("hitl", now(p))                                   # advised: it waits in the view
        hitl.set_level(p, "legal", "require", person="Kaisa", persona="compliance")
        n = now(p)
        self.assertEqual(n["state"], "waiting_on_you")
        self.assertIn("Delivery waits on 1 required answer(s) in People in the loop: HQ-001 (legal, for Compliance)",
                      n["line"])
        self.assertEqual([(a["id"], a["to"]) for a in n["hitl"]], [("HQ-001", "Compliance")])
        status, view, _ = self.call("GET", f"/api/projects/{p.pid}")
        self.assertEqual(view["now"]["hitl"][0]["id"], "HQ-001")
        status, rows, _ = self.call("GET", "/api/projects")
        mine = next(r for r in rows if r["id"] == p.pid)
        self.assertEqual(mine["now"]["hitl"][0]["family"], "legal")
        hitl.answer(p, "HQ-001", answer="Yes", person="Kaisa", persona="compliance")
        self.assertNotIn("hitl", now(p))


class NotYoursTest(Loop, FactoryTestCase):
    def test_FR_HITL2_AC_8_answering_as_another_persona_says_how_in_words(self):
        p = self.new()
        hitl.ask(p, text="Is TLS on?", family="security", **AINO)
        with self.assertRaises(DecisionRefused) as no:
            hitl.answer(p, "HQ-001", answer="Yes", person="Aino Example", persona="business_owner")
        said = str(no.exception)
        self.assertIn("HQ-001 is put to IT / partner, and you are signed in as Business owner", said)
        self.assertIn("switch to it in the person menu", said)
        self.assertNotIn("business_owner", said)
        self.assertNotIn("the it", said)


class ProxyTest(Loop, CockpitTestCase):
    def test_FR_HITL2_AC_9_guessing_behind_one_proxy_never_locks_a_real_link_or_another_visitor_out(self):
        p = self.new(title="Tool loans")
        self.legal(p)
        token = self.link(p)["token"]
        with mock.patch.object(hitl_page, "OPENS_PER_MINUTE", 3):
            hitl_page._FAILS.clear()
            self.addCleanup(hitl_page._FAILS.clear)
            codes = [opened(self.origin, "rv_" + "g" * 43, forwarded="203.0.113.5") for _ in range(4)]
            self.assertEqual(codes, [403, 403, 403, 429])                  # that visitor's guessing waits
            self.assertEqual(opened(self.origin, "rv_" + "h" * 43, forwarded="203.0.113.9"), 403)   # not another's
            self.assertEqual(opened(self.origin, token, forwarded="203.0.113.5"), 200)  # a real link always opens

    def test_FR_HITL2_AC_9_the_forwarded_address_counts_only_behind_a_local_or_private_proxy(self):
        def handler(peer, fwd):
            return type("H", (), {"client_address": (peer, 1), "headers": {"X-Forwarded-For": fwd}})()

        self.assertEqual(hitl_page.client_of(handler("127.0.0.1", "198.51.100.1, 203.0.113.5")),
                         "127.0.0.1>203.0.113.5")
        self.assertEqual(hitl_page.client_of(handler("10.0.0.2", "203.0.113.5")), "10.0.0.2>203.0.113.5")
        self.assertEqual(hitl_page.client_of(handler("93.184.216.34", "203.0.113.5")), "93.184.216.34")  # spoofed
        self.assertTrue(hitl_links.local_only("http://127.0.0.1:9045"))
        self.assertTrue(hitl_links.local_only("http://localhost:9045/"))
        self.assertFalse(hitl_links.local_only("https://review.example.org"))


if __name__ == "__main__":
    unittest.main()
