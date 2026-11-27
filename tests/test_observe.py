"""FR-SHR1: observer links, a time-limited read-only view of your work for a colleague. The kernel's links (hashed,
expiring, revocable, confidential only when ticked), the guest's page over the wire (strict policy, the views in
scope, following, comments and intake suggestions), every cockpit write refused to a guest, Ask Rihma's proposals
and the command line. Invented fixtures only; nothing is ever sent anywhere but 127.0.0.1."""

import contextlib
import datetime as dt
import io
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402
from test_hitl_page import as_json, http  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from kernel import agent_channel, assistant, observe, observe_view  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.confidential import mark  # noqa: E402

SHARER = {"person": "Sari Sharer", "persona": "product_owner"}
FAKE_TOKEN = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123456789"   # invented, split so no scanner takes it for real


class ObserveCase(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.new(title="Tool loans"), self.new(title="Room bookings")
        self.secret = self.new(title="Payroll rework")
        mark(self.secret, person="Sari Sharer", persona="product_owner")
        self.q = Canon(self.a).add_question("Who borrows the drills most?", "business")["id"]
        agent_channel.post(self.a, author=agent_channel.person("Sari Sharer", "developer"), kind="note",
                           text=f"deploy key {FAKE_TOKEN} is in the vault")

    def share(self, **kw):
        body = {"scope": "project", "project": self.a.pid, "hours": 1, "guest": "Maria Example", **SHARER} | kw
        status, out, _ = self.call("POST", "/api/observe/links", body)
        self.assertEqual(status, 201, out)
        return out

    def open(self, url):
        status, raw, _ = http(self.origin, "POST", "/o/api/open", {"link": url.split("#", 1)[1]})
        self.assertEqual(status, 200, raw)
        return as_json(raw)["session"]

    def view(self, session, project=""):
        return http(self.origin, "POST", "/o/api/view", {"session": session, "project": project})


class LinkTest(ObserveCase):
    def test_FR_SHR1_AC_1_a_link_is_shown_once_kept_as_a_hash_with_its_expiry_and_signed(self):
        out = self.share(hours=24)
        url, token = out["url"], out["url"].split("#", 1)[1]
        self.assertTrue(url.startswith(self.origin + "/o/#ob_"), url)       # this cockpit; the token after #
        self.assertEqual((out["shown_once"], out["once"][0]["reusable"]), (True, True))
        self.assertIn("sends nothing", out["said"])
        kept = (self.factory.projects_dir / "_factory" / observe.FILE).read_text(encoding="utf-8")
        self.assertNotIn(token, kept)
        self.assertIn(observe._sha(token), kept)
        status, listed, _ = self.call("GET", "/api/observe")
        self.assertEqual(status, 200)
        self.assertNotIn(token, json.dumps(listed))
        self.assertNotIn("link_sha256", json.dumps(listed))
        row = listed["links"][0]
        self.assertEqual((row["scope"], row["guest"], row["hours"], row["state"], row["last_opened"]),
                         ("project", "Maria Example", 24, "active", None))
        self.assertEqual(row["expires"], observe._stamp(self.factory.clock.now() + dt.timedelta(hours=24)))
        rec = self.a.ledger().of_kind("observe_link_given")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["guest"], rec["scope"]), ("Sari Sharer", "Maria Example", "project"))
        # every project: on the factory's record; durations are an hour, a day or a week only
        every = self.share(scope="platform", project="")
        self.assertEqual(every["link"]["scope"], "platform")
        for bad in (2, 0, True, "week"):
            self.assertEqual(self.call("POST", "/api/observe/links", {"hours": bad, "project": self.a.pid,
                                                                      **SHARER})[0], 400, bad)
        self.assertEqual(self.call("POST", "/api/observe/links", {"project": self.a.pid, "person": "factory",
                                                                  "persona": "product_owner"})[0], 403)

    def test_FR_SHR1_AC_5_a_confidential_project_needs_its_own_tick_and_is_never_shown_otherwise(self):
        status, out, _ = self.call("POST", "/api/observe/links", {"project": self.secret.pid, "hours": 1, **SHARER})
        self.assertEqual(status, 400)
        self.assertIn("confidential", out["error"])
        every = self.share(scope="platform", project="")
        d = observe_view.view(self.factory, observe.find(self.factory, every["link"]["id"]))
        self.assertEqual({p["title"] for p in d["projects"]}, {"Tool loans", "Room bookings"})
        session = self.open(every["url"])
        status, raw, _ = self.view(session, self.secret.pid)
        self.assertEqual(status, 200)
        self.assertNotIn("Payroll rework", raw.decode("utf-8"))
        status, raw, _ = http(self.origin, "POST", "/o/api/comment", {"session": session, "project": self.secret.pid,
                                                                       "text": "hello"})
        self.assertEqual(status, 403)
        ticked = self.share(project=self.secret.pid, confidential=True)
        self.assertEqual(ticked["link"]["confidential"], True)
        d = observe_view.view(self.factory, observe.find(self.factory, ticked["link"]["id"]))
        self.assertEqual([p["title"] for p in d["projects"]], ["Payroll rework"])

    def test_FR_SHR1_AC_3_an_expired_revoked_or_reused_after_revoke_link_is_refused(self):
        short = self.share()
        self.clock.advance(hours=2)
        status, raw, _ = http(self.origin, "POST", "/o/api/open", {"link": short["url"].split("#", 1)[1]})
        self.assertEqual(status, 403)
        self.assertIn("expired", as_json(raw)["error"])
        live = self.share(hours=168)
        token = live["url"].split("#", 1)[1]
        first, second = self.open(live["url"]), self.open(live["url"])        # opened again: a visit each
        self.assertEqual(self.view(first)[0], 200)
        status, out, _ = self.call("POST", "/api/observe/revoke", {"link": live["link"]["id"], **SHARER})
        self.assertEqual((status, out["link"]["state"]), (200, "revoked"))
        for session in (first, second):                                    # every session ends at once
            status, raw, _ = self.view(session)
            self.assertEqual(status, 403)
            self.assertIn("stopped sharing", as_json(raw)["error"])
        status, raw, _ = http(self.origin, "POST", "/o/api/open", {"link": token})   # reused after the revoke
        self.assertEqual(status, 403)
        self.assertIn("stopped sharing", as_json(raw)["error"])
        for bad in ("ob_" + "x" * 43, "not-a-token", ""):
            self.assertEqual(http(self.origin, "POST", "/o/api/open", {"link": bad})[0], 403, bad)
        with self.assertRaises(DecisionRefused):
            observe.revoke(self.factory, live["link"]["id"], person="factory", persona="it")
        visits = self.a.ledger().of_kind("observe_visit")
        self.assertEqual(len(visits), 2)
        self.assertTrue(all(v["event"]["payload"]["by_guest"] for v in visits))


class GuestPageTest(ObserveCase):
    def test_FR_SHR1_AC_2_the_guest_sees_the_views_in_scope_read_only_with_secrets_masked(self):
        status, raw, headers = http(self.origin, "GET", "/o/", origin=None)
        self.assertEqual(status, 200)
        csp = headers["Content-Security-Policy"]
        for part in ("default-src 'none'", "script-src 'self'", "frame-ancestors 'none'", "form-action 'none'"):
            self.assertIn(part, csp)
        self.assertNotIn("unsafe", csp)
        self.assertEqual((headers["Referrer-Policy"], headers["Cache-Control"]), ("no-referrer", "no-store"))
        self.assertNotIn("<script>", raw.decode("utf-8"))
        out = self.share()
        session = self.open(out["url"])
        status, raw, _ = self.view(session, self.b.pid)                     # another project asked: its own shown
        self.assertEqual(status, 200)
        d = as_json(raw)
        text = raw.decode("utf-8")
        self.assertEqual(([p["pid"] for p in d["projects"]], d["project"]["pid"]), ([self.a.pid], self.a.pid))
        for gone in ("Room bookings", self.b.pid, "Payroll rework", FAKE_TOKEN[:20], "link_sha256",
                     "sessions"):
            self.assertNotIn(gone, text)
        self.assertEqual(set(d["project"]), {"pid", "title", "stage", "stage_name", "now", "plan", "decisions",
                                             "activity", "channel"})
        self.assertIn("ghp_", d["project"]["channel"][0]["text"])           # masked, still readable
        self.assertEqual((d["guest"], d["from"], d["scope"]), ("Maria Example", "Sari Sharer", "project"))
        status, listed, _ = self.call("GET", "/api/observe")
        row = listed["links"][0]
        self.assertEqual((row["opens"], row["watching"]), (1, ["Maria Example"]))
        self.assertIsNotNone(row["last_opened"])
        elsewhere = http(self.origin, "POST", "/o/api/view", {"session": session}, origin="http://evil.example")
        self.assertEqual(elsewhere[0], 403)

    def test_FR_SHR1_AC_4_a_guest_write_is_refused_with_403_on_every_write_route(self):
        out = self.share()
        session = self.open(out["url"])
        writes = [(m, p.pattern.removesuffix(r"/?\Z")) for m, p, _ in cockpit.ROUTES if m in ("POST", "PUT")]
        self.assertGreater(len(writes), 100)
        before = sorted(str(f) for f in self.factory.home.rglob("*") if f.is_file())
        for method, pattern in writes:
            path = pattern.replace("\\", "")
            path = re.sub(r"\(\?P<(\w+)>[^)]*\)", lambda m: self.a.pid if m.group(1) == "pid" else "X-1",
                                        path)
            for token in (session, out["url"].split("#", 1)[1]):
                status, said, _ = self.call(method, path, {"text": "go", **SHARER}, token=token)
                self.assertEqual(status, 403, (method, path, said))
                self.assertIn("only watches", said["error"])
        status, said, _ = self.call("GET", "/api/projects", token=session)
        self.assertEqual(status, 403)
        status, said, _ = self.call("POST", "/api/observe/links", {"project": self.a.pid, "hours": 1, **SHARER},
                                    token=self.token)
        self.assertEqual(status, 201)                                        # the operator's own session still works
        after = sorted(str(f) for f in self.factory.home.rglob("*") if f.is_file())
        self.assertEqual([f for f in after if f not in before], [])

    def test_FR_SHR1_AC_6_following_shows_the_sharers_view_and_latest_actions_and_records_nothing(self):
        out = self.share()
        session = self.open(out["url"])
        self.assertEqual(as_json(self.view(session)[1])["following"]["state"], "away")
        ledger = len(self.a.ledger().records())
        status, said, _ = self.call("POST", "/api/observe/presence", {"project": self.a.pid, "view": "plan", **SHARER})
        self.assertEqual((status, said["sharing"], said["watching"]), (200, 1, ["Maria Example"]))
        self.assertEqual(len(self.a.ledger().records()), ledger)            # in memory only
        Canon(self.a).answer(self.q, "Foremen", person="Sari Sharer", persona="product_owner")
        f = as_json(self.view(session)[1])["following"]
        self.assertEqual((f["state"], f["view"], f["project"]), ("here", "plan", self.a.pid))
        self.assertEqual(f["actions"][0]["kind"], "decision")                # the answer, newest first
        self.call("POST", "/api/observe/presence", {"project": self.b.pid, "view": "plan", **SHARER})
        f = as_json(self.view(session)[1])["following"]
        self.assertEqual(f["state"], "elsewhere")
        self.assertNotIn("project", f)                                      # never says where
        self.call("POST", "/api/observe/presence", {"paused": True, **SHARER})
        self.assertEqual(as_json(self.view(session)[1])["following"]["state"], "paused")

    def test_FR_SHR1_AC_7_comments_are_signed_as_the_guest_and_suggestions_wait_for_a_person(self):
        out = self.share(intake=True)
        session = self.open(out["url"])
        status, raw, _ = http(self.origin, "POST", "/o/api/comment", {"session": session, "project": self.a.pid,
                                                                       "text": "Looks good", "about": "plan"})
        self.assertEqual(status, 201, raw)
        rec = self.a.ledger().of_kind("observe_comment")[-1]["event"]["payload"]
        self.assertEqual((rec["guest"], rec["by_guest"]), ("Maria Example", True))
        status, listed, _ = self.call("GET", "/api/observe")
        self.assertEqual((listed["comments"][0]["guest"], listed["comments"][0]["by_guest"]), ("Maria Example", True))
        d = as_json(self.view(session)[1])
        self.assertEqual([q["id"] for q in d["questions"]], [self.q])
        status, raw, _ = http(self.origin, "POST", "/o/api/suggest", {"session": session, "question": self.q,
                                                                       "text": "The site foremen"})
        self.assertEqual(status, 201, raw)
        self.assertEqual(Canon(self.a).question(self.q)["status"], "open")   # a suggestion is not an answer
        sid = as_json(raw)["suggestion"]["id"]
        status, got, _ = self.call("POST", f"/api/projects/{self.a.pid}/observe/suggestions",
                                   {"suggestion": sid, "verdict": "accept", **SHARER})
        self.assertEqual((status, got["suggestion"]["state"]), (200, "accepted"), got)
        answered = Canon(self.a).question(self.q)
        self.assertEqual((answered["answer"]["text"], answered["answer"]["by"]), ("The site foremen", "Sari Sharer"))
        self.assertEqual(self.call("POST", f"/api/projects/{self.a.pid}/observe/suggestions",
                                   {"suggestion": sid, "verdict": "decline", **SHARER})[0], 403)
        watch = self.share()                                                 # a link for watching only
        other = self.open(watch["url"])
        q2 = Canon(self.a).add_question("Weekend loans?", "business")["id"]
        status, raw, _ = http(self.origin, "POST", "/o/api/suggest", {"session": other, "question": q2, "text": "No"})
        self.assertEqual(status, 403)
        with self.assertRaises(ValueError):
            observe.create(self.factory, scope="platform", project=None, hours=1, intake=True, **SHARER)


class ChatAndCommandTest(ObserveCase):
    def test_FR_SHR1_AC_8_ask_rihma_proposes_the_link_and_the_command_line_makes_one(self):
        said = assistant.ask(self.factory, "share my screen with a colleague for an hour", persona="product_owner",
                             project_id=self.a.pid, person="Sari Sharer")
        self.assertEqual(said["navigate"]["route"], "#/share")
        args = said["propose"][0]["args"]
        self.assertEqual((args["op"], args["scope"], args["hours"], args["project"]), ("observe_link", "project", 1,
                                                                                       self.a.pid))
        call = args["call"]
        status, out, _ = self.call(call["method"], call["path"], {**call["body"], **SHARER})
        self.assertEqual(status, 201, out)
        self.assertTrue(out["once"][0]["url"].startswith(self.origin + "/o/#"))
        week = assistant.ask(self.factory, "let Maria Example watch all projects for a week", persona="product_owner",
                             person="Sari Sharer")["propose"][0]["args"]
        self.assertEqual((week["scope"], week["hours"], week["guest"]), ("platform", 168, "Maria Example"))
        together = assistant.ask(self.factory, "define this project together with Maria for a day",
                                 persona="product_owner", project_id=self.a.pid)["propose"][0]["args"]
        self.assertEqual((together["intake"], together["hours"]), (True, 24))
        refused = assistant.ask(self.factory, "share my screen for an hour", persona="product_owner",
                                project_id=self.secret.pid)
        self.assertEqual(refused["propose"], [])
        self.assertIn("confidential", refused["answer"])
        watching = assistant.ask(self.factory, "who is watching?", persona="product_owner", person="Sari Sharer")
        self.assertIn(out["link"]["id"], watching["answer"])
        stop = assistant.ask(self.factory, "stop sharing", persona="product_owner", person="Sari Sharer")
        self.assertEqual(stop["propose"][0]["args"]["op"], "observe_revoke")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--home", str(self.factory.home), "share", "link", self.b.pid, "--hours", "24", "--guest",
                         "Olli Example", "--person", "Sari Sharer", "--persona", "developer"])
        self.assertEqual(code, 0)
        made = json.loads(buf.getvalue())
        self.assertTrue(made["url"].startswith("http://127.0.0.1:8787/o/#ob_"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--home", str(self.factory.home), "share", "link", self.secret.pid, "--person",
                                   "Sari Sharer", "--persona", "developer"]), 2)
            self.assertEqual(main(["--home", str(self.factory.home), "share", "revoke", made["link"]["id"],
                                   "--person", "Sari Sharer", "--persona", "developer"]), 0)
        self.assertEqual(observe.state_of(self.factory, observe.find(self.factory, made["link"]["id"])), "revoked")


if __name__ == "__main__":
    unittest.main()
