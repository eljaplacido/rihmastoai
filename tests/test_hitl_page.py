"""FR-HITL1 over the wire: the reviewer page a person outside opens (its strict policy, one use, its own project
only), the cockpit's routes, the relay's channels and WhatsApp through a stand-in on this machine. Nothing is ever
sent anywhere but 127.0.0.1."""

import email
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from integration_fakes import FakeSmtp, Receiver  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from embed.server import make_server as embed_server  # noqa: E402
from kernel import hitl, hitl_links, hitl_nudge, hitl_page, hitl_send, relay  # noqa: E402

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
KEY = "wa-test-key-0123456789-not-real"


def http(base, method, path, body=None, *, origin="same", ctype="application/json"):
    headers = {}
    if origin:
        headers["Origin"] = base if origin == "same" else origin
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = ctype
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with _DIRECT.open(req, timeout=10) as res:
            return res.status, res.read(), res.headers
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read(), exc.headers


def as_json(raw):
    return json.loads(raw) if raw else None


class PageCase(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.new(title="Tool loans"), self.new(title="Room bookings")
        hitl.ask(self.a, text="May we keep loan history for two years?", kind="decision", family="legal",
                 options=["Yes", "No"], person="Aino Example", persona="business_owner")
        hitl.ask(self.a, text="An ask not on the link", family="legal", person="Aino", persona="business_owner")
        hitl.ask(self.b, text="Room bookings' private ask", family="legal", person="Aino", persona="business_owner")

    def give(self, **kw):
        body = {"name": "Maria Example", "role": "External legal counsel", "asks": ["HQ-001"], "person": "Aino Example",
                "persona": "business_owner"} | kw
        status, out, _ = self.call("POST", f"/api/projects/{self.a.pid}/hitl/links", body)
        self.assertEqual(status, 201, out)
        return out


class ReviewerPageTest(PageCase):
    def test_FR_HITL1_AC_3_the_page_has_a_strict_policy_and_serves_only_its_own_files(self):
        status, raw, headers = http(self.origin, "GET", "/r/", origin=None)
        self.assertEqual(status, 200)
        csp = headers["Content-Security-Policy"]
        for part in ("default-src 'none'", "script-src 'self'", "style-src 'self'", "connect-src 'self'",
                     "frame-ancestors 'none'", "form-action 'none'", "base-uri 'none'"):
            self.assertIn(part, csp)
        self.assertNotIn("unsafe", csp)
        self.assertEqual((headers["Referrer-Policy"], headers["X-Frame-Options"], headers["Cache-Control"]),
                         ("no-referrer", "DENY", "no-store"))
        page = raw.decode("utf-8")
        self.assertNotIn("<script>", page)                               # no inline script
        self.assertNotIn("style=", page)
        for path in ("/r/reviewer.js", "/r/reviewer.css"):
            self.assertEqual(http(self.origin, "GET", path, origin=None)[0], 200, path)
        for path in ("/r/../cockpit/server.py", "/r/%2e%2e/kernel/hitl.py", "/r/static/app.js", "/r/api/items"):
            self.assertIn(http(self.origin, "GET", path, origin=None)[0], (404, 405), path)

    def test_FR_HITL1_AC_2_a_person_outside_opens_once_answers_and_is_signed_by_name(self):
        out = self.give()
        url = out["url"]
        self.assertTrue(url.startswith(self.origin + "/r/#rv_"), url)  # the token after #: never sent to a server
        token = url.split("#", 1)[1]
        status, view, _ = self.call("GET", f"/api/projects/{self.a.pid}/hitl")
        self.assertNotIn(token, json.dumps(view))                        # shown once, then never
        self.assertEqual(view["links"][0]["state"], "active")
        status, raw, _ = http(self.origin, "POST", "/r/api/open", {"link": token})
        self.assertEqual(status, 200, raw)
        session = as_json(raw)["session"]
        status, raw, _ = http(self.origin, "POST", "/r/api/open", {"link": token})
        self.assertEqual(status, 403)
        self.assertIn("already opened", as_json(raw)["error"])
        status, raw, _ = http(self.origin, "POST", "/r/api/items", {"session": session})
        items = as_json(raw)
        self.assertEqual([i["id"] for i in items["items"]], ["HQ-001"])
        text = raw.decode("utf-8")
        for secret in ("An ask not on the link", "Room bookings", self.b.pid, self.a.pid, "Tool loans"):
            self.assertNotIn(secret, text)                               # nothing else of either project
        status, raw, _ = http(self.origin, "POST", "/r/api/answer", {"session": session, "ask": "HQ-002",
                                                                     "answer": "Yes"})
        self.assertEqual(status, 403)
        status, raw, _ = http(self.origin, "POST", "/r/api/answer", {"session": session, "ask": "HQ-001",
                                                                     "answer": "No", "comment": "needs consent"})
        self.assertEqual(status, 200, raw)
        given = hitl.get(self.a, "HQ-001")["answers"][0]
        self.assertEqual((given["person"], given["persona"], given["external"]), ("Maria Example", "compliance", True))
        self.assertEqual(hitl.get(self.b, "HQ-001")["state"], "open")
        status, raw, _ = http(self.origin, "POST", "/r/api/answer", {"session": session, "ask": "HQ-001",
                                                                     "answer": "Yes"})
        self.assertEqual(status, 409)                                    # answered once
        status, out2, _ = self.call("POST", f"/api/projects/{self.a.pid}/hitl/revoke",
                                    {"link": out["link"]["id"], "person": "Aino Example", "persona": "business_owner"})
        self.assertEqual(status, 200, out2)
        status, raw, _ = http(self.origin, "POST", "/r/api/items", {"session": session})
        self.assertEqual(status, 403)
        self.assertIn("withdrawn", as_json(raw)["error"])

    def test_FR_HITL1_AC_3_the_page_refuses_another_origin_a_form_post_and_a_guessed_token(self):
        token = self.give()["url"].split("#", 1)[1]
        self.assertEqual(http(self.origin, "POST", "/r/api/open", {"link": token}, origin=None)[0], 403)
        self.assertEqual(http(self.origin, "POST", "/r/api/open", {"link": token}, origin="https://evil.example")[0],
                         403)
        self.assertEqual(http(self.origin, "POST", "/r/api/open", {"link": token}, ctype="text/plain")[0], 400)
        with mock.patch.object(hitl_page, "OPENS_PER_MINUTE", 3):
            hitl_page._FAILS.clear()
            codes = [http(self.origin, "POST", "/r/api/open", {"link": "rv_" + "g" * 43})[0] for _ in range(4)]
            self.assertEqual(codes, [403, 403, 403, 429])                 # guessing waits
            hitl_page._FAILS.clear()
        self.assertEqual(http(self.origin, "POST", "/r/api/open", {"link": token})[0], 200)   # untouched by them

    def test_FR_HITL1_AC_3_the_embed_server_serves_the_same_page_and_nothing_of_the_cockpit(self):
        srv = embed_server(self.factory, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        token = self.give()["url"].split("#", 1)[1]
        status, _, headers = http(base, "GET", "/r/", origin=None)
        self.assertEqual(status, 200)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        status, raw, _ = http(base, "POST", "/r/api/open", {"link": token})
        self.assertEqual(status, 200, raw)
        self.assertEqual(http(base, "GET", "/api/projects", origin=None)[0], 404)


class RoutesTest(PageCase):
    def test_FR_HITL1_AC_4_a_link_goes_by_whatsapp_through_the_provider_named_with_its_key_name_only(self):
        rx = Receiver()
        self.addCleanup(rx.close)
        status, out, _ = self.call("PUT", "/api/hitl/channels",
                                   {"provider": "meta", "url": rx.base + "/v19.0/1/messages", "key_env": "WA_TEST_KEY",
                                    "person": "Ilkka", "persona": "it"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["whatsapp"]["provider"], "meta")
        with mock.patch.dict("os.environ", {"WA_TEST_KEY": KEY}):
            out = self.give(channel="whatsapp", address="+358401234567")
        self.assertEqual(out["sent"]["outcome"], "delivered", out)
        req = rx.requests[-1]
        sent = json.loads(req["body"])
        self.assertEqual((sent["messaging_product"], sent["to"], sent["type"]), ("whatsapp", "358401234567", "text"))
        self.assertIn(out["url"], sent["text"]["body"])
        self.assertEqual(req["headers"]["authorization"], f"Bearer {KEY}")
        home = b"".join(p.read_bytes() for p in Path(self.factory.home).rglob("*") if p.is_file())
        self.assertNotIn(KEY.encode(), home)                             # the key is never kept
        self.assertNotIn(out["url"].split("#")[1].encode(), home)          # nor the link
        # twilio's form, and a missing key says what to do
        self.call("PUT", "/api/hitl/channels", {"provider": "twilio", "url": rx.base + "/Messages.json",
                                                "key_env": "WA_TEST_KEY", "sender": "+14155238886", "person": "Ilkka",
                                                "persona": "it"})
        hitl.ask(self.a, text="Third", family="legal", person="Aino", persona="business_owner")
        with mock.patch.dict("os.environ", {"WA_TEST_KEY": "AC123:secret"}):
            self.give(asks=["HQ-003"], channel="whatsapp", address="+358401234567")
        self.assertIn(b"To=whatsapp%3A%2B358401234567", rx.requests[-1]["body"])
        self.assertTrue(rx.requests[-1]["headers"]["authorization"].startswith("Basic "))
        with mock.patch.dict("os.environ", {}, clear=False):
            missing = self.give(asks=["HQ-002"], channel="whatsapp", address="+358401234567")["sent"]
        self.assertEqual(missing["outcome"], "failed")
        self.assertIn("IT sets that variable", missing["said"])
        status, out, _ = self.call("PUT", "/api/hitl/channels", {"provider": "meta", "url": "http://evil.example/x",
                                                                 "key_env": "K", "person": "Ilkka", "persona": "it"})
        self.assertEqual(status, 400)                                     # https, or http on this machine only
        status, out, _ = self.call("PUT", "/api/hitl/channels",
                                   {"provider": "meta", "url": rx.base, "key_env": "sk-123", "person": "Ilkka",
                                    "persona": "it"})
        self.assertEqual(status, 400)
        self.assertIn("never stores a secret", out["error"])

    def test_FR_HITL1_AC_4_an_ask_goes_to_the_personas_teams_channel_with_one_link_back(self):
        rx = Receiver()
        self.addCleanup(rx.close)
        relay.subscribe(self.factory, sink="teams", url_env="TEAMS_URL", personas=["compliance"], person="Ilkka",
                        persona="it")
        relay.set_cockpit(self.factory, "https://rihmasto.example.org", person="Ilkka", persona="it")
        with mock.patch.dict("os.environ", {"TEAMS_URL": rx.base + "/teams"}):
            status, out, _ = self.call("POST", f"/api/projects/{self.a.pid}/hitl/send",
                                       {"ask": "HQ-001", "person": "Aino Example", "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["results"][0]["outcome"], "delivered")
        card = json.loads(rx.at("/teams")[-1]["body"])["attachments"][0]["content"]
        self.assertEqual(card["actions"][0]["url"], f"https://rihmasto.example.org/#/p/{self.a.pid}/loop")
        self.assertIn("Legal decision for the compliance", card["body"][0]["text"])
        status, out, _ = self.call("POST", f"/api/projects/{self.a.pid}/hitl/send",      # nobody for IT: says so
                                   {"ask": "HQ-002", "person": "Aino Example", "persona": "business_owner"})
        log = relay.deliveries(self.factory)
        self.assertEqual(log[-1]["kind"], "hitl_delivery")
        self.assertNotIn(rx.base, json.dumps(log))                        # the delivery log names no URL

    def test_FR_HITL1_AC_5_the_relay_round_nudges_and_escalates_people_inside(self):
        rx = Receiver()
        self.addCleanup(rx.close)
        relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["compliance", "business_owner"],
                        person="Ilkka", persona="it")
        hitl.set_level(self.a, "legal", "require", person="Kaisa", persona="compliance")
        self.clock.advance(hours=80)
        out = relay.run(self.factory, environ={"SLACK_URL": rx.base + "/slack"})
        self.assertEqual(out["hitl_nudged"], 2)              # solo: the required ones; b's advised ask waits quietly
        self.assertTrue(hitl_nudge.due(self.b)[0]["quiet"])
        heads = [json.loads(r["body"])["text"] for r in rx.at("/slack")]
        self.assertTrue(any("Waiting 3.3 days: legal decision HQ-001" in h for h in heads), heads)
        self.assertEqual(relay.run(self.factory, environ={"SLACK_URL": rx.base + "/slack"}).get("hitl_nudged"), None)
        rec = self.a.ledger().of_kind("hitl_nudged")[-1]["event"]["payload"]
        self.assertEqual((rec["step"], rec["by"]), ("escalate", "the relay"))

    def test_FR_HITL1_AC_5_a_nudge_gives_a_person_outside_a_fresh_link_and_ends_the_old_one(self):
        first = self.give()
        hitl.set_level(self.a, "legal", "require", person="Kaisa", persona="compliance")   # solo: what blocks nudges
        self.clock.advance(hours=30)
        status, out, _ = self.call("POST", f"/api/projects/{self.a.pid}/hitl/nudge",
                                   {"person": "Aino Example", "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        fresh = [r for r in out["nudged"] if r["external"]][0]["results"][0]
        self.assertTrue(fresh["url"].startswith(self.origin + "/r/#rv_"))
        old = first["url"].split("#", 1)[1]
        self.assertEqual(http(self.origin, "POST", "/r/api/open", {"link": old})[0], 403)
        self.assertEqual(http(self.origin, "POST", "/r/api/open", {"link": fresh["url"].split("#", 1)[1]})[0], 200)


class EmailLinkTest(FactoryTestCase):
    def test_FR_HITL1_AC_4_a_link_by_email_goes_to_the_persons_own_address_through_its_mail_relay(self):
        smtp = FakeSmtp()
        self.addCleanup(smtp.close)
        p = self.new()
        relay.subscribe(self.factory, sink="email", personas=["it"], person="Ilkka", persona="it",
                        mail={"host": "127.0.0.1", "port": smtp.port, "from": "rihmasto@example.org",
                              "to": ["it@example.org"]})
        hitl.ask(p, text="Is the server patched?", family="security", person="Aino", persona="business_owner")
        link = hitl_links.create(p, name="Sami Example", persona="it", asks=["HQ-001"], person="Aino",
                                 creator_persona="business_owner", channel="email", address="sami@example.org")
        out = hitl_send.send_link(p, link, hitl_links.url("https://r.example.org", link["token"]), environ={})
        self.assertEqual(out["outcome"], "delivered", out)
        msg = email.message_from_bytes(smtp.messages[-1])
        self.assertEqual(msg["To"], "sami@example.org")
        self.assertIn("https://r.example.org/r/#rv_", msg.get_payload(decode=True).decode("utf-8"))
        self.assertEqual(hitl_nudge.step_of(23.9), None)


if __name__ == "__main__":
    unittest.main()
