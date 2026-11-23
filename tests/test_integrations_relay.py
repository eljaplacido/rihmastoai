"""Outbound events and notices (FR-IG1, FR-IG3): the ledgers as CloudEvents over Standard Webhooks,
retried with backoff and logged, and notices with one deep link. Every receiver is a local fake."""

import base64
import contextlib
import email
import http.client
import io
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from integration_fakes import FakeSmtp, Receiver  # noqa: E402

from kernel import relay  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.events import CATALOG, HELD, event_type, held_strings, to_event  # noqa: E402
from kernel.filelock import locked  # noqa: E402
from kernel.hooks import secret_bytes, verify_standard  # noqa: E402
from kernel.store import write_json  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
KEY = b"relay-test-signing-key-0123456789"
SIGNING = "whsec_" + base64.b64encode(KEY).decode("ascii")
CANARY = "zq-canary-" + "held-7741"          # a holdout string no payload may carry
URLS = re.compile(r"https?://[^\s\"'<>\\]+")
COCKPIT = "https://rihmasto.example.org"


def home_bytes(factory) -> bytes:
    return b"".join(p.read_bytes() for p in Path(factory.home).rglob("*") if p.is_file())


class RelayCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new()
        self.rx = Receiver()
        self.addCleanup(self.rx.close)
        self.env = {"RELAY_SECRET": SIGNING}

    def webhook(self, types=("rihma.card.*",)):
        return relay.subscribe(self.factory, sink="webhook", url=self.rx.base + "/events", secret_env="RELAY_SECRET",
                               types=list(types), person="Ilkka", persona="it")

    def run_relay(self, env=None):
        return relay.run(self.factory, environ=self.env if env is None else env)

    def hold(self, text: str) -> None:
        write_json(self.factory.holdouts_dir / self.p.pid / "R-1-AC-2.json",
                   {"criterion": "R-1-AC-2", "steps": [{"method": "GET", "path": "/items", "expect_contains": text}]})

    def ok_ids(self, path="/events"):
        return [r["headers"]["webhook-id"] for r in self.rx.at(path) if r["status"] == 200]


class CatalogTest(RelayCase):
    def test_FR_IG1_AC_1_every_ledger_kind_the_kernel_writes_has_an_event_type(self):
        source = "".join(p.read_text(encoding="utf-8") for d in ("kernel", "adapters") for p in (REPO / d).glob("*.py"))
        kinds = set(re.findall(r'log\(\s*"([a-z][a-z0-9_]*)"', source))
        self.assertGreater(len(kinds), 60)
        for kind in sorted(kinds):
            self.assertRegex(event_type(kind), r"^rihma\.[a-z0-9_]+(\.[a-z0-9_]+)+$", kind)
        self.assertEqual((event_type("card_opened"), event_type("decision")), ("rihma.card.opened", "rihma.card.decided"))
        self.assertTrue(set(CATALOG) & kinds >= {"card_opened", "decision", "release_done", "incident_opened"})
        self.assertEqual(event_type("anything_new"), "rihma.ledger.anything_new")

    def test_FR_IG1_AC_1_a_card_event_carries_its_card_and_link_but_never_its_body_or_a_holdout_string(self):
        self.hold(CANARY)
        card = Canon(self.p).card("deploy_gate", f"Release 2 to production ({CANARY})", body="the body stays home")
        self.p.log("comment", {"card": card["id"], "text": f"a note quoting {CANARY}"})
        records = self.p.ledger().records()
        opened = next(r for r in records if r["event"]["kind"] == "card_opened" and r["event"]["payload"]["id"] == card["id"])
        held = held_strings(self.factory)
        self.assertIn(CANARY, held)
        event = to_event(self.p, opened, cockpit=COCKPIT, held=held)
        self.assertEqual((event["spec_version"], event["event_type"], event["seq"]),
                         ("rihma.event/1", "card.opened", opened["seq"]))
        self.assertEqual(event["card"]["waiting"], ["it"])
        self.assertEqual(event["card"]["link"], f"{COCKPIT}/#/p/{self.p.pid}/inbox/{card['id']}")
        self.assertEqual(event["card"]["title"], f"Release 2 to production ({HELD})")
        comment = to_event(self.p, records[-1], cockpit=COCKPIT, held=held)
        for ev in (event, comment):
            text = json.dumps(ev)
            self.assertNotIn(CANARY, text)
            self.assertNotIn("the body stays home", text)
        self.assertEqual(comment["correlation"], {"card": card["id"]})

    def test_FR_IG1_AC_1_a_held_string_is_redacted_before_the_title_is_cut_and_as_the_title_is_cleaned(self):
        long_held = "zq-secret-holdout-" + "expected-value-7741"
        tagged, spaced = "<h1>Overdue loans: 3 items</h1>", "Total   due:  42 EUR"
        write_json(self.factory.holdouts_dir / self.p.pid / "R-9-AC-1.json",
                   {"criterion": "R-9-AC-1", "steps": [{"method": "GET", "path": "/loans",
                                                        "expect_contains": [long_held, tagged, spaced]}]})
        held = held_strings(self.factory)
        cases = {"A" * 140 + " " + long_held: "A" * 140 + " " + HELD,     # the held string crosses the cut
                 f"Page shows {tagged} now": f"Page shows {HELD} now",    # cleaning strips its tags
                 f"Check {spaced} please": f"Check {HELD} please",        # cleaning collapses its spaces
                 "Page shows <b>Overdue loans: 3 items</b> now": f"Page shows {HELD} now",   # as cleaned
                 "Check Total due: 42 EUR please": f"Check {HELD} please"}
        for title, expected in cases.items():
            card = Canon(self.p).card("deploy_gate", title)
            opened = next(r for r in self.p.ledger().records()
                          if r["event"]["kind"] == "card_opened" and r["event"]["payload"]["id"] == card["id"])
            event = to_event(self.p, opened, cockpit=COCKPIT, held=held)
            with self.subTest(expected=expected[-24:]):
                self.assertEqual(event["card"]["title"], expected)
                for part in ("zq-secret", "Overdue loans", "42 EUR"):
                    self.assertNotIn(part, json.dumps(event))


class SignedDeliveryTest(RelayCase):
    def test_FR_IG1_AC_2_each_event_goes_out_as_a_cloudevent_signed_with_standard_webhooks(self):
        Canon(self.p).card("road", "Configure the staging road")           # before the subscription: not sent
        sub = self.webhook()
        cards = [Canon(self.p).card("deploy_gate", "Release 1 to production"),
                 Canon(self.p).card("incident", "Probe failed on staging")]
        out = self.run_relay()
        self.assertEqual(out["results"][0]["state"], "up to date")
        got = self.rx.at("/events")
        self.assertEqual(len(got), 2)
        for req, card in zip(got, cards, strict=True):
            h = req["headers"]
            self.assertTrue(h["content-type"].startswith("application/cloudevents+json"))
            now = int(self.clock.now().timestamp())
            self.assertEqual(verify_standard(h, req["body"], KEY, now=now), h["webhook-id"])
            ce = json.loads(req["body"])
            self.assertEqual((ce["specversion"], ce["type"], ce["subject"], ce["id"]),
                             ("1.0", "rihma.card.opened", card["id"], h["webhook-id"]))
            self.assertEqual(ce["source"], f"/rihmasto/projects/{self.p.pid}")
            self.assertEqual(ce["data"]["spec_version"], "rihma.event/1")
        self.assertNotIn(SIGNING.encode(), home_bytes(self.factory))
        self.assertNotIn(base64.b64encode(KEY), home_bytes(self.factory))
        self.assertEqual(relay.subscriptions(self.factory)[0]["secret_env"], "RELAY_SECRET")
        self.assertEqual(sub["start"][self.p.pid], len(self.p.ledger().records()) - 3)
        self.assertEqual(self.run_relay()["results"][0]["state"], "up to date")
        self.assertEqual(len(self.rx.at("/events")), 2)                    # nothing is sent twice

    def test_FR_IG1_AC_2_a_whsec_secret_is_base64_and_a_plain_one_is_its_bytes(self):
        self.assertEqual(secret_bytes(SIGNING), KEY)
        self.assertEqual(secret_bytes("plain shared words"), b"plain shared words")


class RetryTest(RelayCase):
    def test_FR_IG1_AC_3_a_receiver_that_was_down_gets_each_event_once_per_webhook_id_in_order(self):
        self.webhook()
        a = Canon(self.p).card("deploy_gate", "Release 1 to production")
        b = Canon(self.p).card("deploy_gate", "Release 2 to production")
        self.rx.status = 503
        first = self.run_relay()["results"][0]
        self.assertEqual((first["state"], first["retry"]), ("waiting", 1))
        self.assertEqual(len(self.rx.requests), 1)
        self.run_relay()                                                   # before the backoff: nothing is tried
        self.assertEqual(len(self.rx.requests), 1)
        self.clock.advance(seconds=relay.BACKOFF[0])
        self.run_relay()
        self.assertEqual(len(self.rx.requests), 2)
        self.rx.status = 200
        self.clock.advance(seconds=relay.BACKOFF[1])
        self.assertEqual(self.run_relay()["results"][0]["state"], "up to date")
        ids = [r["headers"]["webhook-id"] for r in self.rx.requests]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ids[0], ids[2])                                   # the same id on every attempt
        self.assertEqual(len(self.ok_ids()), 2)
        self.assertEqual(len(set(self.ok_ids())), 2)
        subjects = [json.loads(r["body"])["subject"] for r in self.rx.requests if r["status"] == 200]
        self.assertEqual(subjects, [a["id"], b["id"]])
        log = relay.deliveries(self.factory)
        self.assertEqual([d["outcome"] for d in log], ["retry", "retry", "delivered", "delivered"])
        self.assertEqual([d["attempt"] for d in log], [1, 2, 3, 1])
        self.assertTrue(relay.log_intact(self.factory))
        self.assertNotIn(self.rx.base, json.dumps(log))

    def test_FR_IG1_AC_3_after_the_last_attempt_the_event_is_logged_failed_and_the_stream_moves_on(self):
        self.webhook()
        Canon(self.p).card("deploy_gate", "Release 1 to production")
        b = Canon(self.p).card("deploy_gate", "Release 2 to production")
        self.rx.status = 500
        for pause in (0, *relay.BACKOFF):
            self.clock.advance(seconds=pause)
            self.run_relay()
        log = relay.deliveries(self.factory)
        self.assertEqual(len(log), relay.MAX_ATTEMPTS + 1)
        self.assertEqual(log[relay.MAX_ATTEMPTS - 1]["outcome"], "failed")
        self.assertEqual(log[-1]["attempt"], 1)                           # the next event, first attempt
        self.assertEqual(json.loads(self.rx.requests[-1]["body"])["subject"], b["id"])

    def test_FR_IG1_AC_3_a_receiver_that_refuses_the_connection_is_retried_and_logged_without_its_url(self):
        closed = Receiver()
        url = closed.base + "/gone"
        closed.close()
        relay.subscribe(self.factory, sink="webhook", url=url, secret_env="RELAY_SECRET", types=["rihma.card.*"],
                        person="Ilkka", persona="it")
        Canon(self.p).card("deploy_gate", "Release 1 to production")
        self.assertEqual(self.run_relay()["results"][0]["state"], "waiting")
        entry = relay.deliveries(self.factory)[-1]
        self.assertEqual((entry["outcome"], entry["status"]), ("retry", None))
        self.assertTrue(entry["error"])


class ConfigurationTest(RelayCase):
    def test_FR_IG1_AC_4_only_it_subscribes_with_a_secret_named_never_given_and_an_https_receiver(self):
        with self.assertRaises(DecisionRefused):
            relay.subscribe(self.factory, sink="webhook", url=self.rx.base, secret_env="RELAY_SECRET",
                            person="Pekka", persona="developer")
        with self.assertRaisesRegex(ValueError, "environment variable"):
            relay.subscribe(self.factory, sink="webhook", url=self.rx.base, secret_env=SIGNING,
                            person="Ilkka", persona="it")
        with self.assertRaisesRegex(ValueError, "https"):
            relay.subscribe(self.factory, sink="webhook", url="http://receiver.example/hook",
                            secret_env="RELAY_SECRET", person="Ilkka", persona="it")
        with self.assertRaisesRegex(ValueError, "its own secret"):
            relay.subscribe(self.factory, sink="slack", url="https://chat.example/hook", personas=["it"],
                            person="Ilkka", persona="it")
        with self.assertRaisesRegex(ValueError, "personas"):
            relay.subscribe(self.factory, sink="teams", url_env="TEAMS_IT", person="Ilkka", persona="it")
        with self.assertRaisesRegex(ValueError, "STARTTLS"):
            relay.subscribe(self.factory, sink="email", personas=["it"], person="Ilkka", persona="it",
                            mail={"host": "mail.example", "from": "rihmasto@example.org", "to": ["it@example.org"]})
        self.assertFalse((self.factory.home / "relay").exists())
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), "relay", "subscribe", "--sink", "webhook", "--url",
                         self.rx.base, "--secret-env", "RELAY_SECRET", "--person", "Pekka", "--persona", "developer"])
        self.assertEqual((code, out.getvalue()), (2, ""))
        self.assertTrue(err.getvalue().startswith("rihmasto relay subscribe"), err.getvalue())
        sub = self.webhook()
        self.assertEqual((sub["by"], sub["persona"], sub["id"]), ("Ilkka", "it", "SUB-001"))
        ledger = Path(self.factory.projects_dir, "_factory", "ledger.jsonl").read_text(encoding="utf-8")
        kinds = [json.loads(line)["event"]["kind"] for line in ledger.splitlines()]
        self.assertIn("relay_subscribed", kinds)

    def test_FR_IG1_AC_4_the_relay_commands_list_run_and_log_on_the_command_line(self):
        def cli(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                    mock.patch.dict(os.environ, {"RELAY_SECRET": SIGNING}):
                code = main(["--home", str(self.factory.home), "relay", *argv])
            self.assertEqual((code, err.getvalue()), (0, ""), argv)
            return json.loads(out.getvalue())

        sub = cli("subscribe", "--sink", "webhook", "--url", self.rx.base + "/events", "--secret-env", "RELAY_SECRET",
                  "--type", "rihma.card.*", "--person", "Ilkka", "--persona", "it")
        Canon(self.p).card("deploy_gate", "Release 1 to production")
        self.assertEqual(cli("run")["results"][0]["delivered"], 1)
        listed = cli("list")
        self.assertEqual([s["id"] for s in listed["subscriptions"]], [sub["id"]])
        self.assertNotIn(SIGNING, json.dumps(listed))
        log = cli("log", "--subscription", sub["id"])
        self.assertEqual(([d["outcome"] for d in log["deliveries"]], log["log_intact"]), (["delivered"], True))
        self.assertEqual(cli("unsubscribe", sub["id"], "--person", "Ilkka", "--persona", "it")["state"], "removed")
        self.assertEqual(cli("run"), {"subscriptions": 0, "results": []})

    def test_FR_IG1_AC_4_a_broken_ledger_chain_halts_that_stream_at_the_break_and_says_so_once(self):
        self.webhook()
        Canon(self.p).card("deploy_gate", "Release 1 to production")
        Canon(self.p).card("deploy_gate", "Release 2 to production")
        path = self.p.path("ledger.jsonl")
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[-1] = lines[-1].replace("card_opened", "card_closed")         # a rewritten record breaks the chain
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        self.run_relay()
        self.run_relay()
        self.assertEqual(len(self.rx.at("/events")), 1)
        halted = [d for d in relay.deliveries(self.factory) if d["kind"] == "halted"]
        self.assertEqual(len(halted), 1)
        self.assertEqual(halted[0]["broken_seq"], len(lines) - 1)


class FaultTest(RelayCase):
    def test_FR_IG1_AC_5_a_receiver_that_redirects_is_a_failed_attempt_and_its_target_is_never_called(self):
        target = Receiver()
        self.addCleanup(target.close)
        self.rx.location = target.base + "/elsewhere"
        for status in (301, 302, 303, 307, 308):
            self.rx.status = status
            self.assertEqual(relay.post_json(self.rx.base + "/events", b"{}", {"Content-Type": "application/json"}),
                             status)
        self.rx.status = 302
        self.webhook()
        Canon(self.p).card("deploy_gate", "Release 1 to production")
        self.assertEqual(self.run_relay()["results"][0]["state"], "waiting")
        entry = relay.deliveries(self.factory)[-1]
        self.assertEqual((entry["outcome"], entry["status"], entry["error"]), ("retry", 302, "HTTP 302"))
        self.assertEqual(target.requests, [])                                # never followed, as a GET or a POST

    def test_FR_IG1_AC_5_a_malformed_channel_url_is_a_logged_attempt_and_the_next_subscription_still_delivers(self):
        teams = relay.subscribe(self.factory, sink="teams", url_env="TEAMS_X", personas=["it"],
                                person="Ilkka", persona="it")
        relay.subscribe(self.factory, sink="slack", url_env="SLACK_OK", personas=["it"], person="Ilkka", persona="it")
        Canon(self.p).card("deploy_gate", "Release 1 to production")
        env = {"TEAMS_X": "https://127.0.0.1:abc/x", "SLACK_OK": self.rx.base + "/slack"}
        for _ in range(2):
            out = self.run_relay(env)
        self.assertEqual([r["state"] for r in out["results"]], ["waiting", "up to date"])
        self.assertEqual(len(self.rx.at("/slack")), 1)
        bad = [d for d in relay.deliveries(self.factory) if d["subscription"] == teams["id"]]
        self.assertEqual([(d["outcome"], d["status"]) for d in bad], [("retry", None)])
        self.assertIn("port", bad[0]["error"])
        self.assertNotIn("127.0.0.1:abc", json.dumps(bad))
        with self.assertRaisesRegex(ValueError, "port"):
            relay.check_url("https://127.0.0.1:abc/x")
        with self.assertRaisesRegex(ValueError, "space"):
            relay.check_url("https://hooks.example.org/a b")

    def test_FR_IG1_AC_5_the_delivery_log_masks_every_url_and_secret_an_error_quotes(self):
        hook = self.webhook()
        teams = relay.subscribe(self.factory, sink="teams", url_env="TEAMS_IT", personas=["it"],
                                person="Ilkka", persona="it")
        Canon(self.p).card("deploy_gate", "Release 1 to production")
        env = dict(self.env, TEAMS_IT=self.rx.base + "/teams?sig=chat-token-0042")

        def post(url, body, headers):                                     # a transport whose error quotes it all
            key = f" with {SIGNING}" if "webhook-signature" in headers else ""
            raise http.client.InvalidURL(f"cannot post to {url}{key}")

        out = relay.run(self.factory, environ=env, post=post)
        self.assertEqual([r["state"] for r in out["results"]], ["waiting", "waiting"])
        log = relay.deliveries(self.factory)
        errors = {d["subscription"]: d["error"] for d in log}
        self.assertEqual(errors[hook["id"]], "InvalidURL: cannot post to <url> with <$RELAY_SECRET>")
        self.assertEqual(errors[teams["id"]], "InvalidURL: cannot post to <$TEAMS_IT>")
        for secret in (self.rx.base, "chat-token-0042", SIGNING):
            self.assertNotIn(secret, json.dumps(log))

    def test_FR_IG1_AC_5_a_round_while_another_runs_answers_busy_and_sends_nothing(self):
        self.webhook()
        Canon(self.p).card("deploy_gate", "Release 1 to production")
        with locked(self.factory.home / "relay" / "round.lock", blocking=False):
            out = self.run_relay()
        self.assertEqual(out, {"subscriptions": 1, "busy": "another relay round is running"})
        self.assertEqual((self.rx.requests, relay.deliveries(self.factory)), ([], []))
        self.assertEqual(self.run_relay()["results"][0]["delivered"], 1)


class NoticeTest(RelayCase):
    def setUp(self):
        super().setUp()
        self.smtp = FakeSmtp()
        self.addCleanup(self.smtp.close)
        self.env.update(TEAMS_IT=self.rx.base + "/teams", SLACK_IT=self.rx.base + "/slack")
        relay.set_cockpit(self.factory, COCKPIT, person="Ilkka", persona="it")
        for sink in ("teams", "slack"):
            relay.subscribe(self.factory, sink=sink, url_env=f"{sink.upper()}_IT", personas=["it"],
                            person="Ilkka", persona="it")
        relay.subscribe(self.factory, sink="email", personas=["it"], person="Ilkka", persona="it",
                        mail={"host": "127.0.0.1", "port": self.smtp.port, "from": "rihmasto@example.org",
                              "to": ["it-team@example.org"]})
        self.webhook(types=("rihma.*",))

    def payloads(self):
        return {"teams": [r["body"].decode() for r in self.rx.at("/teams")],
                "slack": [r["body"].decode() for r in self.rx.at("/slack")],
                "email": [m.decode() for m in self.smtp.messages],
                "webhook": [r["body"].decode() for r in self.rx.at("/events")]}

    def test_FR_IG3_AC_1_a_card_for_it_reaches_the_it_channels_once_with_one_link_and_no_holdout_string(self):
        self.hold(CANARY)
        gate = Canon(self.p).card("deploy_gate", f"Release 3 to production, checked by {CANARY}")
        Canon(self.p).card("approval", "Approve the plan")                  # a business card: no IT notice
        self.run_relay()
        got = self.payloads()
        self.assertEqual([len(got[k]) for k in ("teams", "slack", "email")], [1, 1, 1])
        link = f"{COCKPIT}/#/p/{self.p.pid}/inbox/{gate['id']}"
        for sink in ("teams", "slack", "email"):
            self.assertEqual(URLS.findall(got[sink][0]), [link], sink)
        for sink, bodies in got.items():
            for body in bodies:
                self.assertNotIn(CANARY, body, sink)
        teams = json.loads(got["teams"][0])["attachments"][0]["content"]
        self.assertEqual([a["type"] for a in teams["actions"]], ["Action.OpenUrl"])
        slack = json.loads(got["slack"][0])
        self.assertEqual([e["type"] for e in slack["blocks"][1]["elements"]], ["button"])
        self.assertNotIn("action_id", json.dumps(slack))
        mail = email.message_from_string(got["email"][0])
        self.assertIn("Deploy gate", mail["Subject"])
        self.assertEqual(mail["Auto-Submitted"], "auto-generated")
        self.assertIn(HELD, mail.get_payload(decode=True).decode())

    def test_FR_IG3_AC_1_a_title_from_outside_cannot_add_a_second_link_in_any_channel(self):
        title = "Damage photos [open them](https://files.example.net/x) or www.files.example.net/y"
        card = Canon(self.p).card("incident", title)                          # its title came from outside
        self.run_relay()
        link = f"{COCKPIT}/#/p/{self.p.pid}/inbox/{card['id']}"
        got = self.payloads()
        for sink in ("teams", "slack", "email"):
            self.assertEqual(len(got[sink]), 1, sink)
            self.assertEqual(URLS.findall(got[sink][0]), [link], sink)
            self.assertNotIn("www.", got[sink][0], sink)
            self.assertNotIn("](", got[sink][0], sink)
        head = json.loads(got["teams"][0])["attachments"][0]["content"]["body"][0]["text"]
        self.assertIn("Damage photos [open them] ((link removed)) or (link removed)", head)

    def test_FR_IG3_AC_1_a_bare_domain_a_mail_address_or_another_scheme_in_a_title_is_no_link(self):
        title = ("Release 9: see evil.com/login or mail boss@evil.com, mailto:x@evil.com, //evil.example/x, "
                 "10.0.0.8/admin or tel:+358401234567")
        card = Canon(self.p).card("incident", title)
        self.run_relay()
        link = f"{COCKPIT}/#/p/{self.p.pid}/inbox/{card['id']}"
        got = self.payloads()
        teams = json.loads(got["teams"][0])["attachments"][0]["content"]["body"]
        slack = json.loads(got["slack"][0])
        mail = email.message_from_string(got["email"][0])
        said = {"teams": " ".join(b["text"] for b in teams),
                "slack": slack["text"] + " " + slack["blocks"][0]["text"]["text"],
                "email": mail["Subject"] + " " + mail.get_payload(decode=True).decode().replace(link, "")}
        # What Teams, Slack and mail clients would make a link of: a domain, a mail address, a scheme, //host.
        linkable = re.compile(r"(?i)[\w-]\.[a-z]{2}|\S@\S|\b(?:mailto|tel):|//\w|\d\.\d+\.\d+\.\d")
        for sink, text in said.items():
            with self.subTest(sink):
                self.assertIn("Release 9", text)
                self.assertEqual(linkable.findall(text), [])
                self.assertEqual(URLS.findall(got[sink][0]), [link])
        self.assertIn("see evil[.]com/login or mail boss[at]evil[.]com, (link removed), (link removed), "
                      "10[.]0[.]0[.]8/admin or (link removed)", said["teams"])

    def test_FR_IG3_AC_1_slack_s_control_characters_in_a_title_are_escaped(self):
        Canon(self.p).card("incident", "R&D budget < plan, ask <!here")
        self.run_relay()
        slack = json.loads(self.payloads()["slack"][0])
        texts = [slack["text"], slack["blocks"][0]["text"]["text"]]
        for text in texts:
            self.assertIn("R&amp;D budget &lt; plan, ask &lt;!here", text)
            self.assertNotIn("<", text)
            self.assertNotRegex(text, r"&(?!amp;|lt;|gt;)")

    def test_FR_IG3_AC_2_a_decision_follows_up_with_who_decided_and_a_channel_url_is_never_stored(self):
        gate = Canon(self.p).card("deploy_gate", "Release 3 to production")
        self.run_relay()
        Canon(self.p).decide(gate["id"], "approve", person="Ilkka", persona="it")
        self.run_relay()
        teams = [json.loads(b) for b in self.payloads()["teams"]]
        self.assertEqual(len(teams), 2)
        follow = json.dumps(teams[1])
        self.assertIn("approve by Ilkka, as IT", follow)
        self.assertEqual(URLS.findall(self.payloads()["slack"][1]), [f"{COCKPIT}/#/p/{self.p.pid}/inbox/{gate['id']}"])
        stored = home_bytes(self.factory)
        self.assertIn(b"TEAMS_IT", stored)
        self.assertNotIn((self.rx.base + "/teams").encode(), stored)
        self.assertNotIn((self.rx.base + "/slack").encode(), stored)

    def test_FR_IG3_AC_2_a_channel_whose_variable_is_missing_waits_and_loses_no_attempt(self):
        Canon(self.p).card("deploy_gate", "Release 3 to production")
        out = self.run_relay(env={"RELAY_SECRET": SIGNING})
        waiting = [r for r in out["results"] if r["state"] == "not configured"]
        self.assertEqual(sorted(r["missing"][0] for r in waiting), ["SLACK_IT", "TEAMS_IT"])
        self.assertEqual(self.payloads()["teams"], [])
        self.run_relay()
        self.assertEqual(len(self.payloads()["teams"]), 1)


class NothingConfiguredTest(RelayCase):
    def test_FR_IG3_AC_2_with_no_subscription_nothing_is_sent_and_nothing_is_written(self):
        Canon(self.p).card("deploy_gate", "Release 3 to production")
        self.assertEqual(self.run_relay(), {"subscriptions": 0, "results": []})
        self.assertEqual(self.rx.requests, [])
        self.assertFalse((self.factory.home / "relay").exists())


if __name__ == "__main__":
    unittest.main()
