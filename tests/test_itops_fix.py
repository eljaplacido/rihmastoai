"""FR-ITO2: the IT checks hold up under what a real estate throws at them (tests/itops_fixture.py, and the stand-ins
here): a port that answers with something other than HTTP, a check set turned on for a project that runs nowhere, an
automation that only watches, a wrong port for a database, a phone's lowercase question, a persona that may not, a
bad setting, an assessment's honest verdict and a suggestion that would run nothing.

Every system is a stand-in on this machine; every way a check goes out is replaced (itops_fixture.guard).
"""

import dataclasses
import socket
import socketserver
import ssl
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import itops_fixture as fx  # noqa: E402
from factory_fakes import isolated_routing  # noqa: E402

from kernel import (  # noqa: E402
    assistant,
    automation_suggest,
    automations,
    heal_wiring,
    incidents,
    itops,
    itops_assess,
    itops_chat,
    itops_heal,
    itops_jobs,
    itops_suggest,
)
from kernel.checks import infra, infra_settings, tick_guard  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.store import Factory, FixedClock, updating_json  # noqa: E402

IT = fx.PERSON


class _Banner(socketserver.BaseRequestHandler):
    """An SSH-like server: it speaks first, a banner, as an SSH or SMTP port does."""

    def handle(self) -> None:
        self.request.sendall(b"SSH-2.0-OpenSSH_9.6 stand-in\r\n")
        self.request.settimeout(1.0)
        try:
            self.request.recv(64)
        except OSError:
            return


class _Words(socketserver.BaseRequestHandler):
    """A server that answers whatever it is sent with words, never HTTP and never PostgreSQL's one byte."""

    def handle(self) -> None:
        self.request.settimeout(1.0)
        try:
            if self.request.recv(64):
                self.request.sendall(b"NOT HTTP\r\n")
        except OSError:
            return


class Others:
    """The banner and words servers, each on its own loopback port, and a port nothing listens on."""

    def __init__(self) -> None:
        self.servers = [socketserver.ThreadingTCPServer(("127.0.0.1", 0), h) for h in (_Banner, _Words)]
        for srv in self.servers:
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.closed = s.getsockname()[1]        # free again once closed: nothing listens there

    @property
    def banner(self) -> int:
        return int(self.servers[0].server_address[1])

    @property
    def words(self) -> int:
        return int(self.servers[1].server_address[1])

    def stop(self) -> None:
        for srv in self.servers:
            srv.shutdown()
            srv.server_close()


class FixCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ito2-")).resolve()
        isolated_routing(self, self.tmp)
        self.s, self.o = fx.Standins(), Others()
        self.addCleanup(self.s.stop)
        self.addCleanup(self.o.stop)
        self.factory = Factory(self.tmp / "home", clock=FixedClock("2026-11-25T09:00:00Z"))
        w = fx.populate(self.factory, self.s, self.tmp / "data")
        self.project, self.docs = w["project"], w["docs"]
        self.calls = []
        for name, fake in fx.guard(self.calls).items():
            patcher = mock.patch.object(infra, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def enable(self, key, project=None, every=None, **config):
        cstore.enable(project or self.project, key, person=IT[0], persona=IT[1], config=config or None, every=every)

    def run_check(self, key, project=None):
        return cstore.run(project or self.project, key, person=IT[0], persona=IT[1])


class NotHttpTest(FixCase):
    def test_FR_ITO2_AC_1_a_port_that_answers_without_http_fails_the_check_and_never_stops_the_tick(self):
        banner = f"http://127.0.0.1:{self.o.banner}/health"
        self.enable("app", url=banner, every="15m")
        row = self.run_check("app")
        self.assertEqual(row["verdict"], "failed", row)
        self.assertIn("not with HTTP", row["summary"])
        self.enable("integration:words", integrations=["stock_api"])
        beta = self.factory.new_project("Beta", mode="assume", maturity="pilot", profile="web_service")
        self.enable("dns", beta, every="1h", hosts=[f"127.0.0.1:{self.s.pg_port}"])
        self.enable("database", beta, every="1d", endpoint=f"postgres://127.0.0.1:{self.s.pg_port}/x")
        with updating_json(self.project.path("checks", "results.json"), {}) as kept:
            kept.clear()                                          # the app check is due again
        ticked = cstore.tick(self.factory)
        by = {(t["project"], t["check"]): t["verdict"] for t in ticked}
        self.assertEqual(by[(self.project.pid, "app")], "failed", ticked)
        self.assertEqual((by[(beta.pid, "dns")], by[(beta.pid, "database")]), ("passed", "passed"), ticked)
        self.assertEqual(cstore.due(self.factory), [], "every check recorded: none stays due to block the next tick")
        itops.set_types(self.project, ["web_service"], person=IT[0], persona=IT[1])
        ran = itops.run(self.project, person=IT[0], persona=IT[1])
        self.assertEqual({r["check"]: r["verdict"] for r in ran["ran"]}["app"], "failed")
        out = itops_assess.run(self.project, "family:app", person=IT[0], persona=IT[1])
        self.assertEqual(out["verdict"], "failed", out)

    def test_FR_ITO2_AC_1_a_check_that_breaks_is_recorded_and_the_tick_goes_on(self):
        self.enable("dns", every="1h")
        beta = self.factory.new_project("Beta", mode="assume", maturity="pilot", profile="web_service")
        self.enable("dns", beta, every="1h", hosts=[f"127.0.0.1:{self.s.pg_port}"])
        real = cstore.scheduled

        def flaky(project, key):
            if project.pid == self.project.pid:
                raise RuntimeError("a bug in Rihmasto")
            return real(project, key)

        with mock.patch.object(cstore, "scheduled", flaky):
            ticked = cstore.tick(self.factory)
        by = {t["project"]: t for t in ticked}
        self.assertEqual(by[self.project.pid]["verdict"], "not measured")
        self.assertIn("RuntimeError", by[self.project.pid]["error"])
        self.assertEqual(by[beta.pid]["verdict"], "passed")
        self.assertIn("broke", cstore.results(self.project, "dns", 1)[-1]["summary"])
        self.assertEqual(tick_guard.one(beta, "dns", lambda p, k: {"verdict": "passed"})["verdict"], "passed")
        broken = cstore.catalogue()["dns"]
        known = cstore.catalogue() | {"dns": dataclasses.replace(broken, run=lambda ctx: ctx.no_such_thing)}
        with mock.patch.object(cstore, "catalogue", return_value=known):
            row = cstore.run(beta, "dns", person=IT[0], persona=IT[1])
        self.assertEqual(row["verdict"], "not measured")
        self.assertIn("the check itself broke (AttributeError", row["summary"])


class HonestIncidentsTest(FixCase):
    def test_FR_ITO2_AC_2_a_check_set_on_a_project_that_runs_nowhere_opens_no_incident(self):
        for kind in ("app", "tls", "dns", "job"):
            self.enable(kind, self.docs)
            self.assertEqual(self.run_check(kind, self.docs)["verdict"], "not measured")
        heal_wiring.sweep(self.factory)
        self.assertEqual(incidents.incidents(self.factory, pid=self.docs.pid), [], "not measured is no failure")
        self.enable("app", url=self.s.base + "/down")
        self.run_check("app")
        heal_wiring.sweep(self.factory)
        opened = incidents.incidents(self.factory, pid=self.project.pid)
        self.assertEqual([i["where"] for i in opened], ["check:app"], opened)
        self.assertTrue(itops_heal.swept({"kind": "tests", "check": "tests", "verdict": "not measured"}),
                        "another kind of check that could not measure still opens one")
        self.assertTrue(itops_heal.swept({"kind": "dns", "verdict": "not measured",
                                          "summary": "not measured: the check itself broke (AttributeError: x)"}))
        self.assertFalse(itops_heal.swept({"kind": "dns", "verdict": "not measured", "summary": "nothing to do"}))
        dns_class = next(c for c in itops_heal.classes() if c["id"] == "infra_dns")
        self.assertFalse(dns_class["match"]({"kind": "check_failed", "where": "check:dns",
                                             "message": "not measured: not measured: no host"}))
        self.assertTrue(dns_class["match"]({"kind": "check_failed", "where": "check:dns", "message": "failed: x"}))


class JobsTest(FixCase):
    def add(self, action, scope=None, trigger=None):
        return automations.add(self.factory, {"name": "A job", "trigger": trigger or {"kind": "schedule",
                                                                                     "daily": "02:00"},
                                              "action": action, "scope": scope or {"kind": "project",
                                                                                   "projects": [self.project.pid]}},
                               person=IT[0], persona=IT[1])

    def test_FR_ITO2_AC_3_only_the_projects_own_active_scheduled_work_makes_it_a_job(self):
        self.add({"kind": "run_assessment", "target": "infra"})
        self.add({"kind": "signal", "text": "every project"}, scope={"kind": "factory"})
        self.assertNotIn("job", itops.detected(self.project), "watching it, or every project alike, is no job")
        paused = self.add({"kind": "signal", "text": "export"})
        automations.pause(self.factory, paused["id"], person=IT[0], persona=IT[1], reason="holiday")
        self.assertNotIn("job", itops.detected(self.project), "a paused automation is not a job")
        self.assertEqual([a["id"] for a in itops_jobs.paused(self.project)], [paused["id"]])
        self.project.log("automation_ran", {"id": paused["id"], "outcome": "ok", "action": "signal",
                                            "person": IT[0], "persona": IT[1]})
        self.factory.clock = FixedClock("2026-12-05T09:00:00Z")
        self.enable("job")
        row = self.run_check("job")
        self.assertNotIn("missed its schedule", row["summary"], row)
        self.assertTrue(any("paused, so not expected to run" in e for e in row["evidence"]), row)
        own = self.add({"kind": "signal", "text": "nightly export"})
        self.assertIn("job", itops.detected(self.project))
        self.assertIn(own["id"], [a["id"] for a in itops_jobs.own_jobs(self.project)])


class DatabaseTest(FixCase):
    def db(self, port, kind="postgres"):
        self.enable("database:x", endpoint=f"{kind}://127.0.0.1:{port}/x")
        return self.run_check("database:x")

    def test_FR_ITO2_AC_4_only_postgresql_passes_as_postgresql_and_a_refused_port_says_so(self):
        self.assertEqual(self.db(self.s.pg_port)["verdict"], "passed")
        for port in (self.o.banner, self.o.words):
            row = self.db(port)
            self.assertEqual(row["verdict"], "failed", row)
            self.assertIn("not as PostgreSQL does", row["summary"])
        refused = self.db(self.o.closed)
        self.assertEqual(refused["verdict"], "failed")
        self.assertIn("refused", refused["summary"], refused)
        self.assertNotIn("TimeoutError", refused["summary"])


class ChatTest(FixCase):
    def act(self, out):
        return [p for p in out["propose"] if p.get("action") == "act"]

    def test_FR_ITO2_AC_5_a_phones_words_are_understood_and_a_persona_is_told_whose_it_is(self):
        tls = itops_chat.answer(self.factory, "run the TLS checks", self.project, "it")
        self.assertEqual(self.act(tls)[0]["args"]["target"], "family:tls", tls)
        run = itops_chat.answer(self.factory, "run the it checks", self.project, "it")
        self.assertEqual(self.act(run)[0]["args"]["op"], "run_it_checks", run)
        ask = itops_chat.answer(self.factory, "what should it check for this project?", self.project, "it")
        self.assertEqual(ask["navigate"]["control"], "itops_set", ask)
        self.assertIsNone(itops_chat.answer(self.factory, "what does it check before saving?", self.project, "it"))
        owner = itops_chat.answer(self.factory, "run the IT checks", self.project, "business_owner")
        self.assertEqual(self.act(owner), [], "never offered a Confirm that is refused")
        self.assertIn("is for IT", owner["answer"])
        family = itops_chat.answer(self.factory, "run the database checks", self.project, "business_owner")
        self.assertEqual(self.act(family), [])
        self.assertIn("is run by", family["answer"])
        listing = itops_chat.answer(self.factory, "What should IT check for this project?", self.project,
                                    "business_owner")
        self.assertEqual(self.act(listing), [])
        self.assertIn("turning them on is for IT", listing["answer"])
        self.assertTrue(self.act(itops_chat.answer(self.factory, "run the database checks", self.project, "it")))
        whole = assistant.ask(self.factory, "run the TLS checks", persona="it", project_id=self.project.pid)
        self.assertEqual(self.act(whole)[0]["args"]["target"], "family:tls", "Ask Rihma itself, not only the rule")


class SettingsTest(FixCase):
    def test_FR_ITO2_AC_6_a_bad_setting_is_refused_and_an_old_one_said_never_mislabelled(self):
        for key, config in (("integration", {"expires": ["STOCK_API_TOKEN=notadate"]}),
                            ("dns", {"hosts": ["foo:bar"]}), ("tls", {"targets": ["https://"]}),
                            ("app", {"url": "ftp://x.example.org"})):
            with self.assertRaises(ValueError, msg=key) as said:
                self.enable(key, **config)
            self.assertIn("is not", str(said.exception))
        self.enable("dns")
        with updating_json(self.project.path("checks.json"), {}) as kept:
            kept["enabled"]["dns"]["config"] = {"hosts": ["foo:bar"]}       # set before the rule
        row = self.run_check("dns")
        self.assertEqual(row["verdict"], "not measured")
        self.assertIn("'foo:bar' is not a host", row["summary"])
        self.assertNotIn("runs nowhere", row["summary"])
        self.assertEqual(infra_settings.problems("probe", {"hosts": "foo:bar"}), [], "other kinds are their own")
        self.enable("integration", expires=["STOCK_API_TOKEN=2026-12-31"])

    def test_FR_ITO2_AC_6_an_expired_or_untrusted_certificate_is_said_as_such(self):
        def refuse(code, message):
            def fake(host, port, timeout=10):
                exc = ssl.SSLCertVerificationError(1, message)
                exc.verify_code, exc.verify_message = code, message
                raise exc
            return fake

        self.enable("tls", targets=["https://shop.example.org"])
        with mock.patch.object(infra, "tls_days", refuse(10, "certificate has expired")):
            row = self.run_check("tls")
        self.assertEqual((row["verdict"], row["remedy"]), ("failed", "renew"))
        self.assertIn("the certificate has expired", row["summary"])
        with mock.patch.object(infra, "tls_days", refuse(20, "unable to get local issuer certificate")):
            row = self.run_check("tls")
        self.assertIn("is not trusted", row["summary"])
        self.assertEqual(row["remedy"], "tls")
        self.assertNotIn("Renew", itops_heal.REMEDY["tls"].split(":")[0])


class AssessTest(FixCase):
    def test_FR_ITO2_AC_7_a_code_assessment_fails_only_on_a_serious_finding_and_optimise_says_no_runs(self):
        rec = {"id": "AS-1", "counts": {"findings": 10, "by_severity": {"critical": 0, "high": 0, "medium": 4,
                                                                        "low": 6, "info": 0}}}
        detail, verdict = itops_assess.code_verdict(rec)
        self.assertEqual(verdict, "passed")
        self.assertIn("10 finding(s) (4 medium, 6 low); none critical or high", detail)
        rec["counts"]["by_severity"]["high"] = 1
        self.assertEqual(itops_assess.code_verdict(rec)[1], "failed")
        got = {"proposals": [{}] * 5, "totals": {"runs": 0}, "audit": {"seq": 3}}
        with mock.patch("kernel.agentops_actions.record", return_value=got):
            out = itops_assess._optimise((self.project, "", IT[0], IT[1], "person"))
        self.assertEqual(out["verdict"], "not measured")
        self.assertIn("no agent run in the last 30 days", out["detail"])
        self.assertNotIn("over 0 run", out["detail"])


class SuggestTest(FixCase):
    def test_FR_ITO2_AC_8_a_suggestion_that_would_run_nothing_says_what_to_turn_on_first(self):
        f = {"pid": self.project.pid, "https": True, "it_types": ["ml"], "checks_on": [], "evalsets_on": []}
        tls = itops_suggest._tls_weekly(f, None)
        self.assertIn("TLS check is not on", tls["blocked"])
        self.assertNotIn("blocked", itops_suggest._tls_weekly(f | {"checks_on": ["tls"]}, None))
        evals = itops_suggest._evals_weekly(f, None)
        self.assertEqual(evals["draft"]["action"], {"kind": "run_assessment", "target": "evalsets"})
        self.assertIn("no eval set is turned on", evals["blocked"])
        nothing = itops_assess.run(self.project, "evalsets", person=IT[0], persona=IT[1])
        self.assertEqual(nothing["outcome"], "nothing")
        from kernel import itops_evals

        itops_evals.toggle(self.project, "role:goal_plans", True, person=IT[0], persona=IT[1])
        with mock.patch("kernel.role_evals.run", return_value={"runs": [{"score_pct": 90}], "lines": ["ok"]}):
            ran = itops_assess.run(self.project, "evalsets", person=IT[0], persona=IT[1])
        self.assertEqual((ran["outcome"], ran["verdict"]), ("done", "passed"), ran)
        scan = {s["id"]: s for s in automation_suggest.scan(self.factory, self.project.pid)["suggestions"]}
        self.assertEqual(scan["it_db_nightly"]["state"], "unavailable")
        with self.assertRaises(ValueError):
            automation_suggest.accept(self.factory, self.project.pid, "it_db_nightly", person=IT[0], persona=IT[1])


if __name__ == "__main__":
    unittest.main()
