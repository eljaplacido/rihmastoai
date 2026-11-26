"""FR-HITL1: people in the loop. Asks put to the persona responsible and answered signed; one-use links for people
outside the system; enforcement per check family, advise or require; nudges escalating by age; Ask Rihma's rules.
The reviewer page over HTTP, the channels and WhatsApp's stand-in are in tests/test_hitl_page.py."""

import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import hitl, hitl_chat, hitl_links, hitl_nudge, relay  # noqa: E402
from kernel.assistant import ask as rihma  # noqa: E402
from kernel.autonomy import cleared_to_deliver  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.posture_rules import Held  # noqa: E402


def files_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*") if p.is_file())


class LoopCase(FactoryTestCase):
    def legal(self, p, text="May we keep the loan history for two years?", **kw):
        args = {"kind": "decision", "family": "legal", "options": ["Yes", "No"]} | kw
        return hitl.ask(p, text=text, person="Aino Example", persona="business_owner", **args)


class AskTest(LoopCase):
    def test_FR_HITL1_AC_1_an_ask_goes_to_the_persona_responsible_and_is_answered_signed_by_it(self):
        p = self.new()
        item = self.legal(p)
        self.assertEqual((item["id"], item["to"]["persona"], item["state"]), ("HQ-001", "compliance", "open"))
        sec = hitl.ask(p, text="Is the admin page behind sign-in?", family="security", person="Aino Example",
                       persona="business_owner")
        self.assertEqual(sec["to"]["persona"], "it")                      # security is IT's by default
        with self.assertRaises(DecisionRefused):                          # not the persona it is put to
            hitl.answer(p, "HQ-001", answer="Yes", person="Dev Example", persona="developer")
        with self.assertRaises(ValueError):                               # a decision is one of its options
            hitl.answer(p, "HQ-001", answer="Maybe", person="Kaisa Example", persona="compliance")
        with self.assertRaises(DecisionRefused):                          # never the factory or a model
            hitl.answer(p, "HQ-001", answer="Yes", person="assistant", persona="compliance")
        done = hitl.answer(p, "HQ-001", answer="Yes", comment="two years is fine", person="Kaisa Example",
                           persona="compliance")
        self.assertEqual(done["state"], "answered")
        self.assertEqual(done["answers"][0] | {"at": None}, {"answer": "Yes", "comment": "two years is fine",
                                                             "person": "Kaisa Example", "persona": "compliance",
                                                             "external": False, "via": None, "at": None})
        with self.assertRaises(DecisionRefused):                          # answered once
            hitl.answer(p, "HQ-001", answer="No", person="Kaisa Example", persona="compliance")
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        self.assertIn("hitl_asked", kinds)
        self.assertIn("hitl_answered", kinds)
        with self.assertRaises(ValueError):
            hitl.ask(p, text="Pick one", kind="decision", family="legal", person="Aino", persona="business_owner")
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_HITL1_AC_1_who_has_not_answered_lists_open_asks_oldest_first(self):
        p = self.new()
        self.legal(p)
        self.clock.advance(hours=5)
        hitl.ask(p, text="Is the copy clear?", family="quality", person="Aino", persona="business_owner")
        rows = hitl.who_has_not_answered(p)
        self.assertEqual([r["id"] for r in rows], ["HQ-001", "HQ-002"])
        self.assertEqual(rows[0]["hours"], 5.0)
        self.assertEqual(rows[1]["persona"], "product_owner")


class EnforceTest(LoopCase):
    def test_FR_HITL1_AC_6_a_family_is_advised_unless_required_here_platform_wide_or_by_the_enforcement_settings(self):
        p = self.new()
        self.assertEqual(hitl.level(p, "legal"), ("advise", "default"))
        hitl.set_level(p, "legal", "require", person="Kaisa", persona="compliance", scope="platform")
        self.assertEqual(hitl.level(p, "legal"), ("require", "platform-wide"))
        hitl.set_level(p, "legal", "advise", person="Kaisa", persona="compliance")
        self.assertEqual(hitl.level(p, "legal"), ("advise", "this project"))
        with self.assertRaises(DecisionRefused):
            hitl.set_level(p, "legal", "require", person="Dev", persona="developer")
        # the enforcement module, when present, is read by name with a default: its names for "require" count
        fake = types.ModuleType("kernel.enforce")
        fake.level_of = lambda project, name: {"legal": "block", "security": None}.get(name, "warn")
        with mock.patch.dict(sys.modules, {"kernel.enforce": fake}):
            self.assertEqual(hitl.level(p, "legal"), ("require", "enforcement settings"))
            self.assertEqual(hitl.level(p, "security"), ("advise", "default"))       # None: falls through
            self.assertEqual(hitl.level(p, "quality"), ("advise", "enforcement settings"))
        self.assertEqual(hitl.normal("REQUIRED"), "require")
        self.assertEqual(hitl.normal(types.SimpleNamespace(name="force")), "require")

    def test_FR_HITL1_AC_6_a_required_family_holds_delivery_until_answered_and_says_what_to_do(self):
        p = self.new()
        self.legal(p)
        cleared_to_deliver(p)                                             # advised: nothing waits
        hitl.set_level(p, "legal", "require", person="Kaisa", persona="compliance")
        with self.assertRaises(Held) as held:
            cleared_to_deliver(p)
        said = str(held.exception)
        self.assertIn("delivering to demo waits on 1 required answer(s): HQ-001 (legal", said)
        self.assertIn("Answer them in People in the loop", said)
        hitl.answer(p, "HQ-001", answer="No", person="Kaisa", persona="compliance")
        cleared_to_deliver(p)


class LinkTest(LoopCase):
    def link(self, p, **kw):
        args = {"name": "Maria Example", "persona": "compliance", "asks": ["HQ-001"], "person": "Aino Example",
                "creator_persona": "business_owner", "role": "External legal counsel"} | kw
        return hitl_links.create(p, **args)

    def test_FR_HITL1_AC_2_a_one_use_link_is_kept_as_a_hash_opens_once_and_shows_only_its_asks(self):
        p = self.new()
        self.legal(p)
        self.legal(p, text="Can the export include phone numbers?")
        link = self.link(p)
        token = link["token"]
        self.assertTrue(token.startswith("rv_"))
        self.assertNotIn(token, files_text(self.factory.home))           # only its sha256 is kept
        self.assertIn("https://r.example/r/#rv_", hitl_links.url("https://r.example/", token))
        opened = hitl_links.redeem(self.factory, token)
        with self.assertRaises(hitl_links.LinkRefused) as again:          # one use
            hitl_links.redeem(self.factory, token)
        self.assertIn("already opened", str(again.exception))
        mine = hitl_links.session(self.factory, opened["session"])
        view = hitl_links.items(self.factory, mine)
        self.assertEqual([i["id"] for i in view["items"]], ["HQ-001"])   # HQ-002 is not on the link
        self.assertEqual(set(view), {"name", "role", "context", "from", "expires", "items", "open"})
        with self.assertRaises(hitl_links.LinkRefused):
            hitl_links.answer(self.factory, mine, "HQ-002", "Yes")
        after = hitl_links.answer(self.factory, mine, "HQ-001", "No", "not without consent")
        self.assertEqual(after["items"][0]["answer"], "No")
        given = hitl.get(p, "HQ-001")["answers"][0]
        self.assertEqual((given["person"], given["persona"], given["external"], given["via"]),
                         ("Maria Example", "compliance", True, "RL-001"))
        rec = p.ledger().of_kind("hitl_answered")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["external"], rec["via"]), ("Maria Example", True, "RL-001"))

    def test_FR_HITL1_AC_2_a_link_expires_is_revocable_and_its_session_ends_with_it(self):
        p = self.new()
        self.legal(p)
        self.legal(p, text="Second?")
        short = self.link(p, hours=1)
        self.clock.advance(hours=2)
        with self.assertRaises(hitl_links.LinkRefused) as late:
            hitl_links.redeem(self.factory, short["token"])
        self.assertIn("expired", str(late.exception))
        live = self.link(p, asks=["HQ-002"])
        opened = hitl_links.redeem(self.factory, live["token"])
        hitl_links.revoke(p, live["id"], person="Aino Example", persona="business_owner")
        with self.assertRaises(hitl_links.LinkRefused) as gone:
            hitl_links.session(self.factory, opened["session"])
        self.assertIn("withdrawn", str(gone.exception))
        with self.assertRaises(DecisionRefused):
            hitl_links.revoke(p, live["id"], person="Dev", persona="developer")
        with self.assertRaises(ValueError):                               # only asks put to that persona
            self.link(p, persona="it", asks=["HQ-002"])
        public = hitl_links.public(self.factory, hitl_links.links(self.factory)[-1])
        self.assertNotIn("link_sha256", public)
        self.assertNotIn("contact", public)

    def test_FR_HITL1_AC_3_a_session_reaches_its_own_project_only(self):
        a, b = self.new(title="Tool loans"), self.new(title="Room bookings")
        self.legal(a)
        self.legal(b, text="Secret of another project")                  # the same id, HQ-001, in project b
        opened = hitl_links.redeem(self.factory, self.link(a)["token"])
        mine = hitl_links.session(self.factory, opened["session"])
        view = hitl_links.items(self.factory, mine)
        self.assertNotIn("Secret of another project", json.dumps(view))
        hitl_links.answer(self.factory, mine, "HQ-001", "Yes")
        self.assertEqual(hitl.get(b, "HQ-001")["state"], "open")          # b's HQ-001 is untouched
        s = opened["session"]
        for bad in ("", "rv_short", "rs_" + "x" * 43, s[:-1] + ("A" if s[-1] != "A" else "B"), "../" * 10):
            with self.assertRaises(hitl_links.LinkRefused):
                hitl_links.session(self.factory, bad)


class NudgeTest(LoopCase):
    def test_FR_HITL1_AC_5_open_asks_are_nudged_then_escalated_once_per_step_and_solo_only_for_what_blocks(self):
        p = self.new()
        self.legal(p)
        self.assertEqual(hitl_nudge.due(p, solo=False)[0]["step"], None)
        self.clock.advance(hours=25)
        row = hitl_nudge.due(p, solo=False)[0]
        self.assertEqual((row["step"], row["to"], row["to_send"]), ("nudge", ["compliance"], True))
        self.assertFalse(hitl_nudge.due(p, solo=True)[0]["to_send"])     # solo: an advised ask waits quietly
        relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["compliance"], person="Ilkka",
                        persona="it")
        env, ok = {"SLACK_URL": "http://127.0.0.1:9/slack"}, (lambda url, body, headers: 200)
        out = hitl_nudge.nudge(p, person="Aino", persona="business_owner", base="", solo=False, environ=env, post=ok)
        self.assertEqual(out["count"], 1)
        self.assertEqual(hitl_nudge.nudge(p, person="Aino", persona="business_owner", base="", solo=False,
                                          environ=env, post=ok)["count"], 0)       # once per step
        self.clock.advance(hours=50)
        row = hitl_nudge.due(p, solo=False)[0]
        self.assertEqual((row["step"], row["to"]), ("escalate", ["compliance", "business_owner"]))
        hitl.set_level(p, "legal", "require", person="Kaisa", persona="compliance")
        self.assertTrue(hitl_nudge.due(p, solo=True)[0]["to_send"])      # solo: what blocks work nudges
        self.clock.advance(hours=100)
        self.assertEqual(hitl_nudge.due(p, solo=False)[0]["step"], "overdue")
        steps = [r["event"]["payload"]["step"] for r in p.ledger().of_kind("hitl_nudged")]
        self.assertEqual(steps, ["nudge"])
        self.assertEqual(hitl_nudge.escalation("business_owner"), "product_owner")


class ChatTest(LoopCase):
    def say(self, question, project=None, persona="business_owner"):
        return rihma(self.factory, question, persona=persona, project_id=project.pid if project else None)

    def test_FR_HITL1_AC_7_ask_rihma_says_who_has_not_answered_and_proposes_to_nudge(self):
        p = self.new()
        out = self.say("Who hasn't answered?", p)
        self.assertIn("Nobody", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{p.pid}/loop", "control": "hitl_ask"})
        self.legal(p)
        out = self.say("who has not answered yet?", p)
        self.assertIn("HQ-001", out["answer"])
        self.assertEqual(out["navigate"]["control"], "hitl_waiting")
        self.assertEqual(out["propose"][0]["args"]["call"],
                         {"method": "POST", "path": f"/api/projects/{p.pid}/hitl/nudge", "body": {}})
        across = self.say("Who hasn't answered?")                          # every project, without one open
        self.assertIn("Equipment loans: HQ-001", across["answer"])

    def test_FR_HITL1_AC_7_send_this_question_to_the_legal_reviewer_is_a_signed_proposal(self):
        p = self.new()
        out = self.say("Send this question to the legal reviewer", p)
        self.assertIn("Which question?", out["answer"])                   # no words: it asks which
        self.assertEqual(out["propose"], [])
        out = self.say("send this question to the legal reviewer: Can we keep emails for two years?", p)
        call = out["propose"][0]["args"]["call"]
        self.assertEqual(call["path"], f"/api/projects/{p.pid}/hitl/asks")
        self.assertEqual(call["body"], {"text": "Can we keep emails for two years?", "kind": "question",
                                        "family": "legal", "to_persona": "compliance"})
        self.assertEqual(hitl.asks(p), [])                                # proposing writes nothing
        self.legal(p, text="Is the retention period documented?", kind="question", options=None)
        out = self.say("Ask the security reviewer about HQ-001", p)          # a named ask is sent, not copied
        self.assertEqual(out["propose"][0]["args"]["call"], {"method": "POST", "path": f"/api/projects/{p.pid}/hitl/send",
                                                             "body": {"ask": "HQ-001"}})

    def test_FR_HITL1_AC_7_ask_rihma_sets_a_level_and_gives_an_outside_reviewer_a_link(self):
        p = self.new()
        out = self.say("Require legal sign-off checks on this project", p)
        self.assertEqual(out["propose"][0]["args"]["call"]["body"], {"family": "legal", "level": "require",
                                                                     "scope": "project"})
        out = self.say("make security checks advise only", p)
        self.assertEqual(out["propose"][0]["args"]["call"]["body"]["level"], "advise")
        self.legal(p)
        out = self.say("Give Maria Example a link for the legal questions", p)
        self.assertEqual(out["propose"][0]["args"]["call"]["body"], {"name": "Maria Example", "asks": ["HQ-001"],
                                                                     "channel": "copy"})
        self.assertEqual(hitl_links.links(self.factory), [])
        self.assertIsNone(hitl_chat.answer(self.factory, "What is the weather?", p, "business_owner"))


class TablesTest(unittest.TestCase):
    def test_FR_HITL1_AC_9_every_route_control_and_operation_has_its_other_half(self):
        from cockpit import server, solo_routes
        from kernel import assistant_ops, control_pages, parity
        from kernel.assistant_rules import ui_map

        writes = {name for method, _, name in server.ROUTES if method != "GET" and "hitl" in name}
        self.assertEqual(len(writes), 8)
        self.assertTrue(writes <= set(solo_routes.NEEDS))
        controls = {c["id"] for c in ui_map()["controls"] if c["id"].startswith("hitl_")}
        self.assertEqual(len(controls), 10)
        for cid in controls:
            self.assertEqual(control_pages.CONTROL_PAGES[cid], ("loop", None), cid)
            self.assertTrue(cid in parity.READS or cid in parity.CHAT, cid)
        for op in hitl_chat.OPS:
            label, method, path, *_ = assistant_ops.OPS[op]
            self.assertIsNotNone(server._route(method, path.format(pid="loans-0a1b2c")), op)
        self.assertIn(("loop", "#/p/{pid}/loop"), [(v["id"], v.get("route")) for v in ui_map()["views"]])


if __name__ == "__main__":
    unittest.main()
