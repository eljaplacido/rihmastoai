"""FR-SHR2: observer links fixed after an independent check. A pause stays paused whatever the page's heartbeat says;
following names only what the link covers, in plain words; Ask Rihma answers only questions about observer links; a
guest cannot flood the sharer with comments or suggestions; the docs warn that a tunnel is an ssh login; with access
enforced, the Share page's read, a platform-wide link and a revoke stay within the person's grants. Invented
fixtures only; nothing is ever sent anywhere but 127.0.0.1."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_access import AINO, DEV, EnforcedCockpitCase, access_doc  # noqa: E402
from test_hitl_page import as_json, http  # noqa: E402
from test_observe import SHARER, ObserveCase  # noqa: E402

from kernel import assistant, observe, observe_chat, observe_guard  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.learn import FACTORY_PID  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class PauseAndFollowTest(ObserveCase):
    def following(self, session):
        return as_json(self.view(session)[1])["following"]

    def test_FR_SHR2_AC_1_a_pause_from_ask_rihma_stays_paused_through_the_pages_heartbeat(self):
        session = self.open(self.share()["url"])
        self.call("POST", "/api/observe/presence", {"project": self.a.pid, "view": "plan", **SHARER})
        self.assertEqual(self.following(session)["state"], "here")
        said = assistant.ask(self.factory, "pause sharing my view", persona="product_owner", person="Sari Sharer")
        call = said["propose"][0]["args"]["call"]
        status, out, _ = self.call(call["method"], call["path"], {**call["body"], **SHARER})     # Confirm
        self.assertEqual((status, out["presence"]["paused"]), (200, True), out)
        for _ in range(3):                                   # the page's heartbeat: where the person is, no pause
            status, out, _ = self.call("POST", "/api/observe/presence", {"project": self.a.pid, "view": "overview",
                                                                         "was_paused": False, **SHARER})
            self.assertEqual((status, out["presence"]["paused"]), (200, True))     # the page mirrors this
            self.assertEqual(self.following(session)["state"], "paused")
        said = assistant.ask(self.factory, "resume sharing my view", persona="product_owner", person="Sari Sharer")
        call = said["propose"][0]["args"]["call"]
        self.call(call["method"], call["path"], {**call["body"], **SHARER})
        out = self.call("POST", "/api/observe/presence", {"project": self.a.pid, "view": "plan", "was_paused": True,
                                                          **SHARER})[1]
        self.assertFalse(out["presence"]["paused"])                         # resume from chat is not undone either
        self.assertEqual(self.following(session)["state"], "here")
        observe_guard._PAUSED.clear()                                       # a restart: the page's own word stands
        out = self.call("POST", "/api/observe/presence", {"project": self.a.pid, "view": "plan", "was_paused": True,
                                                          **SHARER})[1]
        self.assertTrue(out["presence"]["paused"])

    def test_FR_SHR2_AC_3_following_names_only_what_the_link_covers_in_plain_words(self):
        session = self.open(self.share()["url"])                            # one project's link
        for view in ("settings", "agents_all", "share", "inbox_all", "home"):
            self.call("POST", "/api/observe/presence", {"view": view, **SHARER})
            f = self.following(session)
            self.assertEqual(f["state"], "elsewhere", view)
            self.assertNotIn("view", f)
        self.call("POST", "/api/observe/presence", {"project": self.a.pid, "view": "plan", **SHARER})
        f = self.following(session)
        self.assertEqual((f["state"], f["view"], f["view_words"]), ("here", "plan", "the plan"))
        every = self.open(self.share(scope="platform", project="")["url"])
        self.call("POST", "/api/observe/presence", {"view": "agents_all", **SHARER})
        f = self.following(every)
        self.assertEqual((f["state"], f["view_words"]), ("here", "the agent activity across projects"))
        self.call("POST", "/api/observe/presence", {"view": "settings", **SHARER})
        self.assertEqual(self.following(every)["state"], "elsewhere")
        page = (ROOT / "cockpit" / "static" / "observer.js").read_text(encoding="utf-8")
        self.assertIn("f.view_words", page)                                 # the page shows the words, not the id


class ChatWordsTest(ObserveCase):
    def test_FR_SHR2_AC_4_ask_rihma_answers_only_questions_about_observer_links(self):
        for other in ("How do I share work items with the team?", "let the agents watch the repository for changes",
                      "who is following the plan?", "share the work breakdown with stakeholders",
                      "who are the people following up on this?"):
            self.assertIsNone(observe_chat.answer(self.factory, other, self.a, "product_owner", "Sari Sharer"), other)
        for ours in ("share my screen with a colleague for an hour", "let Maria Example watch all projects for a week",
                     "who is watching?", "who is watching my work right now", "share what I'm doing with Maria",
                     "invite Olli Example to follow along"):
            self.assertIsNotNone(observe_chat.answer(self.factory, ours, self.a, "product_owner", "Sari Sharer"), ours)


class FloodTest(ObserveCase):
    def test_FR_SHR2_AC_5_a_guest_cannot_flood_the_sharer_with_comments_or_suggestions(self):
        session = self.open(self.share(intake=True)["url"])
        for n in range(observe_guard.PER_WINDOW):
            status, raw, _ = http(self.origin, "POST", "/o/api/comment", {"session": session, "project": self.a.pid,
                                                                           "text": f"note {n}"})
            self.assertEqual(status, 201, raw)
        status, raw, _ = http(self.origin, "POST", "/o/api/comment", {"session": session, "project": self.a.pid,
                                                                       "text": "one more"})
        self.assertEqual(status, 429, raw)
        self.assertIn("wait a few minutes", as_json(raw)["error"])
        self.assertEqual(len(self.a.ledger().of_kind("observe_comment")), observe_guard.PER_WINDOW)
        for n in range(observe_guard.PER_WINDOW):
            q = Canon(self.a).add_question(f"Loan rule {n}?", "business")["id"]
            self.assertEqual(http(self.origin, "POST", "/o/api/suggest", {"session": session, "question": q,
                                                                           "text": "Yes"})[0], 201)
        status, raw, _ = http(self.origin, "POST", "/o/api/suggest", {"session": session, "question": self.q,
                                                                       "text": "Foremen"})
        self.assertEqual(status, 429, raw)
        self.clock.advance(minutes=observe_guard.WINDOW_MINUTES + 1)
        self.assertEqual(http(self.origin, "POST", "/o/api/comment", {"session": session, "project": self.a.pid,
                                                                       "text": "later"})[0], 201)


class TunnelWordsTest(unittest.TestCase):
    def test_FR_SHR2_AC_7_the_docs_and_the_share_page_warn_that_a_tunnel_is_an_ssh_login(self):
        guide = (ROOT / "docs" / "guides" / "observer-links.md").read_text(encoding="utf-8")
        share = (ROOT / "cockpit" / "static" / "share.js").read_text(encoding="utf-8")
        chat = (ROOT / "kernel" / "observe_chat.py").read_text(encoding="utf-8")
        for text in (guide, share, chat):
            self.assertNotIn("same ssh tunnel you use", text.lower())
        self.assertIn("far more than read only", guide)
        self.assertIn('restrict,port-forwarding,permitopen="127.0.0.1:', guide)
        self.assertIn("far more than read only", share)
        self.assertIn("an ssh login", chat)


class TeamModeTest(EnforcedCockpitCase):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.new(title="Tool loans"), self.new(title="Room bookings")
        doc = access_doc()
        doc["bindings"].append({"subject": DEV, "persona": "developer", "scope": [self.a.pid, FACTORY_PID]})
        self.enforce(doc)
        self.sign_in(AINO)
        self.sign_in(DEV)

    def link(self, who, name, persona, **body):
        status, out = self.pcall("POST", "/api/observe/links", {"hours": 1, "person": name, "persona": persona,
                                                                **body}, who=who)
        self.assertEqual(status, 201, out)
        return out["link"]

    def test_FR_SHR2_AC_8_with_access_enforced_sharing_stays_within_each_persons_grants(self):
        aino_b = self.link(AINO, "Aino Example", "product_owner", scope="project", project=self.b.pid)
        aino_all = self.link(AINO, "Aino Example", "product_owner", scope="platform")
        dev_all = self.link(DEV, "Dev Example", "developer", scope="platform")
        shown = observe.in_scope(self.factory, observe.find(self.factory, dev_all["id"]))
        self.assertEqual([p.pid for p in shown], [self.a.pid])               # only what Dev is granted
        self.assertEqual({p.pid for p in observe.in_scope(self.factory, observe.find(self.factory, aino_all["id"]))},
                         {self.a.pid, self.b.pid})
        made = observe.create(self.factory, scope="project", project=self.b.pid, hours=1, guest="Gita Guest",
                              person="Aino Example", persona="product_owner")
        session = observe.open_link(self.factory, made["token"])["session"]
        observe.comment(self.factory, observe.session(self.factory, session), self.b.pid, "On room bookings")
        status, seen = self.pcall("GET", "/api/observe", who=DEV)
        self.assertEqual(status, 200, seen)
        self.assertEqual([r["id"] for r in seen["links"]], [dev_all["id"]])
        self.assertEqual(seen["comments"], [])
        self.assertEqual([p["pid"] for p in seen["projects"]], [self.a.pid])
        self.assertNotIn("Room bookings", json.dumps(seen))
        status, everything = self.pcall("GET", "/api/observe", who=AINO)
        self.assertEqual({r["id"] for r in everything["links"]}, {aino_b["id"], aino_all["id"], dev_all["id"],
                                                                  made["id"]})
        self.assertEqual(len(everything["comments"]), 1)
        status, out = self.pcall("POST", "/api/observe/revoke", {"link": aino_all["id"], "person": "Dev Example",
                                                                 "persona": "developer"}, who=DEV)
        self.assertEqual(status, 403, out)
        self.assertEqual(observe.state_of(self.factory, observe.find(self.factory, aino_all["id"])), "active")
        status, out = self.pcall("POST", "/api/observe/revoke", {"link": dev_all["id"], "person": "Dev Example",
                                                                 "persona": "developer"}, who=DEV)
        self.assertEqual(status, 200, out)                                   # their own
        status, out = self.pcall("POST", "/api/observe/revoke", {"link": aino_b["id"], "person": "Aino Example",
                                                                 "persona": "product_owner"}, who=AINO)
        self.assertEqual(status, 200, out)


if __name__ == "__main__":
    unittest.main()
