"""FR-ITO1: what IT checks, per project and solution type: infrastructure check families, check sets, automations that
run any assessment, eval sets, and incidents from a failing check (tests/itops_fixture.py).

The owner (2026-11-25): "IT maintenance view should include typical infrastructure checks done for apps, databases,
networks, integrations by agents. Remember to also update automations that are suggested from this context. Also in
regards to automations there should be able to run assessments of any area if requested. Don't forget the eval sets
enabled by Gnomon." And: "think what they would be per project and solution type too".

Every system here is a stand-in on this machine; every way a check goes out is replaced (itops_fixture.guard).
"""

import datetime as dt
import os
import sys
import tempfile
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
    immune,
    incidents,
    itops,
    itops_assess,
    itops_chat,
    itops_evals,
    itops_heal,
)
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.checks import catalogue, infra  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.store import Factory, FixedClock, updating_json  # noqa: E402

IT = fx.PERSON


class ItOpsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ito-")).resolve()
        isolated_routing(self, self.tmp)
        self.s = fx.Standins()
        self.addCleanup(self.s.stop)
        self.factory = Factory(self.tmp / "home", clock=FixedClock("2026-11-25T09:00:00Z"))
        w = fx.populate(self.factory, self.s, self.tmp / "data")
        self.project, self.docs, self.db = w["project"], w["docs"], w["db"]
        self.calls = []
        for name, fake in fx.guard(self.calls).items():
            patcher = mock.patch.object(infra, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def enable(self, key, project=None, **config):
        cstore.enable(project or self.project, key, person=IT[0], persona=IT[1], config=config or None)

    def run_check(self, key, project=None):
        return cstore.run(project or self.project, key, person=IT[0], persona=IT[1])

    def assert_offline(self):
        out = [c for c in self.calls if c[0] in ("fetch", "connect") and "127.0.0.1" not in str(c[1])
               and "localhost" not in str(c[1])]
        self.assertTrue(all("example" in str(c[1]) or "invalid" in str(c[1]) for c in out), out)


class FamiliesTest(ItOpsCase):
    def test_FR_ITO1_AC_1_every_family_is_in_the_catalogue_and_measures_nothing_without_a_target(self):
        kinds = set(catalogue())
        self.assertTrue({"app", "tls", "dns", "database", "integration", "job", "ml", "agent"} <= kinds)
        for kind in ("app", "tls", "dns", "ml", "agent", "job"):
            self.enable(kind, self.docs)
            row = self.run_check(kind, self.docs)
            self.assertEqual(row["verdict"], "not measured", (kind, row))
            self.assertTrue(row["summary"].startswith("not measured: "), row["summary"])
        self.enable("database", self.docs)
        self.assertIn("declares no database", self.run_check("database", self.docs)["summary"])

    def test_FR_ITO1_AC_1_app_reads_status_latency_against_a_budget_and_the_version(self):
        self.enable("app", url=self.s.base + "/health", max_ms=2000)
        row = self.run_check("app")
        self.assertEqual(row["verdict"], "passed", row)
        self.assertEqual(row["targets"][0]["version"], "1.4.2")
        self.assertIn("version 1.4.2", " ".join(row["evidence"]))
        self.enable("app:slow", url=self.s.base + "/slow", max_ms=100)
        self.s.slow = 0.3
        slow = self.run_check("app:slow")
        self.assertEqual(slow["verdict"], "failed")
        self.assertIn("over the 100 ms budget", slow["summary"])
        self.enable("app:down", url=self.s.base + "/down")
        self.assertIn("status 503, expected 200", self.run_check("app:down")["summary"])
        self.assertEqual(len(cstore.results(self.project, "app")), 1, "history is kept per check")

    def test_FR_ITO1_AC_1_tls_warns_then_fails_before_a_certificate_expires(self):
        self.enable("tls", targets=["https://shop.example.org", "https://soon.example.org"])
        ok = self.run_check("tls")
        self.assertEqual(ok["verdict"], "passed")
        self.assertIn("soon.example.org expires in 15.0 days (under 21", ok["summary"])
        self.enable("tls:edge", targets=["https://expiring.example.org"])
        bad = self.run_check("tls:edge")
        self.assertEqual(bad["verdict"], "failed")
        self.assertEqual(bad["certificates"], [{"host": "expiring.example.org", "port": 443, "days": 3.0}])
        self.enable("tls:none", targets=["http://plain.example.org"])
        self.assertEqual(self.run_check("tls:none")["verdict"], "not measured")

    def test_FR_ITO1_AC_1_dns_resolves_and_connects_each_host_its_bindings_name(self):
        self.enable("dns")
        row = self.run_check("dns")
        self.assertEqual(row["verdict"], "passed", row)
        self.assertEqual({r["port"] for r in row["reached"]}, {self.s.pg_port, self.s.http.server_address[1]})
        self.enable("dns:gone", hosts=["gone.invalid:443"])
        gone = self.run_check("dns:gone")
        self.assertEqual(gone["verdict"], "failed")
        self.assertIn("gone.invalid does not resolve", gone["summary"])
        self.enable("dns:shut", hosts=["shop.example.org:443"])
        self.assertIn("resolves but nothing answers", self.run_check("dns:shut")["summary"])
        self.assert_offline()

    def test_FR_ITO1_AC_1_database_round_trip_backup_recency_and_storage_growth(self):
        self.enable("database")                                         # the first database: orders_db (postgres)
        pg = self.run_check("database")
        self.assertEqual(pg["verdict"], "passed", pg)
        self.assertIn("PostgreSQL answered its SSL request (no TLS)", " ".join(pg["evidence"]))
        self.assertIn("not measured (Rihmasto signs in to no database server)", " ".join(pg["evidence"]))
        self.assertIn("its reference connector is postgres", " ".join(pg["evidence"]))
        backups = self.tmp / "backups"
        backups.mkdir()
        old = backups / "ledger-2026-11-20.sql"
        old.write_text("dump", encoding="utf-8")
        stale = (self.factory.clock.now() - dt.timedelta(hours=100)).timestamp()
        os.utime(old, (stale, stale))
        self.enable("database:ledger", binding="ledger_db", backup_dir=str(backups), growth_pct=50)
        first = self.run_check("database:ledger")
        self.assertEqual(first["verdict"], "failed")
        self.assertIn("the newest backup is 100 hours old (over 26)", first["summary"])
        self.assertEqual(first["remedy"], "backup")
        fresh = backups / "ledger-2026-11-25.sql"
        fresh.write_text("dump", encoding="utf-8")
        now = self.factory.clock.now().timestamp()
        os.utime(fresh, (now, now))
        self.assertEqual(self.run_check("database:ledger")["verdict"], "passed")
        import sqlite3

        con = sqlite3.connect(self.db)
        con.executemany("INSERT INTO entries (amount) VALUES (?)", [(i,) for i in range(4000)])
        con.commit()
        con.close()
        grown = self.run_check("database:ledger")
        self.assertEqual(grown["verdict"], "failed")
        self.assertRegex(grown["summary"], r"storage grew \d+% since the last run \(over 50%\)")
        self.enable("database:my", endpoint=f"mysql://127.0.0.1:{self.s.my_port}/shop")
        self.assertIn("MySQL greeted with version 8.0.36-standin", " ".join(self.run_check("database:my")["evidence"]))

    def test_FR_ITO1_AC_1_integration_health_credential_expiry_and_quota_headroom(self):
        self.enable("integration", integrations=["stock_api"], expires=["STOCK_API_TOKEN=2027-03-01"])
        row = self.run_check("integration")
        self.assertEqual(row["verdict"], "passed", row)
        said = " ".join(row["evidence"])
        self.assertIn("401", said)
        self.assertIn("no credential sent", said)
        self.assertIn("quota headroom 80 of 100 (80%)", said)
        self.s.quota = (5, 100)
        low = self.run_check("integration")
        self.assertEqual(low["verdict"], "failed")
        self.assertIn("5% of its quota left (under 10%)", low["summary"])
        self.s.quota = (80, 100)
        self.enable("integration:soon", integrations=["stock_api"], expires=["STOCK_API_TOKEN=2026-11-30"])
        self.assertIn("STOCK_API_TOKEN expires in 5 days", self.run_check("integration:soon")["summary"])

    def test_FR_ITO1_AC_1_job_last_run_failures_in_a_row_duration_and_output_freshness(self):
        a = automations.add(self.factory, {"name": "Nightly export", "trigger": {"kind": "schedule", "daily": "02:00"},
                                           "action": {"kind": "signal", "text": "export"},
                                           "scope": {"kind": "project", "projects": [self.project.pid]}},
                            person=IT[0], persona=IT[1])
        out = self.tmp / "exports"
        out.mkdir()
        (out / "orders.csv").write_text("id\n", encoding="utf-8")
        now = self.factory.clock.now().timestamp()
        os.utime(out / "orders.csv", (now, now))
        self.enable("job", output=str(out))
        self.assertEqual(self.run_check("job")["verdict"], "passed")
        for _ in range(2):
            self.project.log("automation_ran", {"id": a["id"], "outcome": "failed", "action": "signal",
                                                "person": IT[0], "persona": IT[1]})
        failed = self.run_check("job")
        self.assertEqual(failed["verdict"], "failed")
        self.assertIn(f"{a['id']} failed 2 times in a row", failed["summary"])

    def test_FR_ITO1_AC_1_ml_reads_the_latest_eval_and_its_drift(self):
        rows = [{"eval": "eval", "verdict": "passed", "summary": "pass rate", "at": f"2026-11-2{i}T00:00:00Z",
                 "scores": {"pass_rate": v}} for i, v in enumerate((90, 91, 89, 70))]
        with updating_json(self.project.path("evals", "results.json"), {}) as kept:
            kept["eval"] = rows
        self.enable("ml")
        row = self.run_check("ml")
        self.assertEqual(row["verdict"], "failed", row)
        self.assertIn("drifted 20.0 points the wrong way", row["summary"])

    def test_FR_ITO1_AC_1_agent_tool_errors_refusals_and_cost_from_run_records(self):
        for i in range(4):
            self.project.log("model_run", {"role": "assistant", "model": "local-a", "tool_calls": 10,
                                           "tool_errors": 3 if i == 0 else 0, "verdict": "refused" if i == 1 else "ok",
                                           "tokens": {"in": 100, "out": 20}})
        self.enable("agent", max_refusal_pct=30)
        row = self.run_check("agent")
        self.assertEqual(row["verdict"], "passed", row)
        self.assertEqual((row["runs"], row["tool_calls"], row["tool_errors"], row["refused"]), (4, 40, 3, 1))
        self.assertIn("tool errors: 3 of 40 tool calls (7.5%", " ".join(row["evidence"]))
        self.enable("agent:strict", max_tool_error_pct=5)
        self.assertIn("of tool calls failed (over 5%)", self.run_check("agent:strict")["summary"])


class CheckSetTest(ItOpsCase):
    def test_FR_ITO1_AC_2_a_project_gets_a_check_set_from_its_type_and_what_was_found_with_why_and_scope(self):
        s = itops.check_set(self.project)
        types = {t["id"]: t["why"] for t in s["types"]}
        self.assertEqual(set(types), {"web_service", "database", "integration"})
        self.assertIn("its work profile is web service", types["web_service"])
        self.assertIn("it declares orders_db (postgres)", types["database"])
        rows = {r["check"]: r for r in s["checks"]}
        self.assertTrue({"app", "tls", "dns", "database", "integration", "destinations", "dependencies"} <= set(rows))
        self.assertEqual(rows["database"]["scope"], "platform default")
        self.assertIn("Database-backed", rows["database"]["why"][0])
        self.assertEqual(rows["app"]["state"], "not enabled")
        docs = itops.check_set(self.docs)
        self.assertEqual(docs["checks"], [])
        self.assertIn("runs nothing, so there is no infrastructure to check", docs["none"])
        self.assertTrue(docs["line"].startswith("No infrastructure check: it holds documents"))

    def test_FR_ITO1_AC_2_platform_defaults_and_project_overrides_are_shown_as_such(self):
        itops.change_default(self.factory, "web_service", "secrets", "add", person=IT[0], persona=IT[1],
                             why="every web service is scanned for leaked keys")
        itops.change_default(self.factory, "web_service", "destinations", "remove", person=IT[0], persona=IT[1])
        itops.change(self.project, "licences", "add", person=IT[0], persona=IT[1], why="sold to customers")
        itops.change(self.project, "dns", "remove", person=IT[0], persona=IT[1])
        s = itops.check_set(self.project)
        rows = {r["check"]: r for r in s["checks"]}
        self.assertEqual(rows["secrets"]["scope"], "platform default (changed by IT)")
        self.assertIn("every web service is scanned for leaked keys", rows["secrets"]["why"][0])
        self.assertNotIn("destinations", rows)
        self.assertEqual(rows["licences"]["scope"], "project override")
        self.assertNotIn("dns", rows)
        self.assertEqual(s["removed"], [{"check": "dns", "why": "taken away for this project",
                                         "scope": "project override"}])
        p = itops.platform(self.factory)
        web = next(t for t in p["types"] if t["id"] == "web_service")
        self.assertEqual(web["scope"], "platform default (changed by IT)")
        self.assertEqual(web["removed"], ["destinations"])
        mine = next(x for x in p["projects"] if x["project"] == self.project.pid)
        self.assertTrue(mine["overridden"])
        with self.assertRaises(DecisionRefused):
            itops.change_default(self.factory, "web_service", "tls", "remove", person=IT[0], persona="developer")
        with self.assertRaises(DecisionRefused):
            itops.change(self.project, "tls", "remove", person=IT[0], persona="end_user")
        kinds = [r["event"]["kind"] for r in self.project.ledger().records()]
        self.assertIn("itops_override_changed", kinds)

    def test_FR_ITO1_AC_2_apply_turns_on_the_set_with_its_schedules_and_run_runs_the_infrastructure_ones(self):
        itops.set_types(self.project, ["database"], person=IT[0], persona=IT[1])
        out = itops.apply(self.project, person=IT[0], persona=IT[1])
        self.assertEqual(sorted(out["enabled"]), ["database", "dns"])
        enabled = cstore.enabled(self.project)
        self.assertEqual((enabled["database"]["every"], enabled["dns"]["every"]), ("1d", "1h"))
        ran = itops.run(self.project, person=IT[0], persona=IT[1])
        self.assertEqual({r["check"]: r["verdict"] for r in ran["ran"]}, {"database": "passed", "dns": "passed"})
        self.assertEqual(ran["set"]["line"], "2 of 2 IT checks enabled")
        with self.assertRaises(DecisionRefused):
            itops.apply(self.project, person=IT[0], persona="stakeholder")


class AutomationsTest(ItOpsCase):
    def test_FR_ITO1_AC_3_automations_are_suggested_from_the_it_context(self):
        itops.apply(self.project, person=IT[0], persona=IT[1], only=["dns"])
        scan = automation_suggest.scan(self.factory, self.project.pid)
        mine = {s["id"]: s for s in scan["suggestions"] if s["id"].startswith("it_")}
        self.assertTrue({"it_db_nightly", "it_integration_alert", "it_infra_weekly"} <= set(mine), mine)
        self.assertNotIn("it_tls_weekly", mine, "nothing it runs or reaches is https")
        self.assertIn("orders_db", mine["it_db_nightly"]["reason"])
        self.assertEqual(mine["it_db_nightly"]["state"], "unavailable", "it would run a check that is not on (FR-ITO2)")
        self.assertIn("Database check is not on", mine["it_db_nightly"]["why"])
        itops.apply(self.project, person=IT[0], persona=IT[1], only=["database"])
        mine = {s["id"]: s for s in automation_suggest.scan(self.factory, self.project.pid)["suggestions"]
                if s["id"].startswith("it_")}
        self.assertTrue(all(s["state"] == "offered" for s in mine.values()), mine)
        got =automation_suggest.accept(self.factory, self.project.pid, "it_db_nightly", person=IT[0], persona=IT[1])
        self.assertEqual(got["automation"]["action"], {"kind": "run_check", "check": "database"})
        again = {s["id"]: s["state"] for s in automation_suggest.scan(self.factory, self.project.pid)["suggestions"]}
        self.assertEqual(again["it_db_nightly"], "set_up")
        self.assertEqual(again["it_infra_weekly"], "offered", "a run_check of another check is not this one")
        self.assertNotIn("it_db_nightly", {s["id"] for s in automation_suggest.scan(self.factory, self.docs.pid)
                                           ["suggestions"]})

    def test_FR_ITO1_AC_3_run_assessment_runs_any_area_with_the_owners_rights(self):
        self.assertIn("run_assessment", automations.ACTIONS)
        self.enable("tls", targets=["https://shop.example.org"])
        a = automations.add(self.factory, {"name": "Weekly TLS", "trigger": {"kind": "schedule", "weekly": "mon 06:00"},
                                           "action": {"kind": "run_assessment", "target": "family:tls"},
                                           "scope": {"kind": "project", "projects": [self.project.pid]}},
                            person=IT[0], persona=IT[1])
        self.assertEqual(a["action"], {"kind": "run_assessment", "target": "family:tls"})
        done = itops_assess.handle(self.factory, a, {"project": self.project.pid}, None)
        self.assertEqual((done["outcome"], done["verdict"]), ("done", "passed"), done)
        last = cstore.results(self.project, "tls", 1)[-1]
        self.assertEqual((last["via"], last["by"]["person"]), (f"automation {a['id']}", IT[0]))
        for target, outcome in (("code", "nothing"), ("alignment", "nothing"), ("check:dns", "nothing"),
                                ("infra", "done")):
            got = itops_assess.run(self.project, target, person=IT[0], persona=IT[1])
            self.assertEqual(got["outcome"], outcome, (target, got))
        opt = itops_assess.run(self.project, "optimise", person="Aino Example", persona="ai_architect")
        self.assertEqual(opt["outcome"], "done")
        with self.assertRaises(ValueError):
            itops_assess.parse("decide")
        with self.assertRaises(ValueError):
            automations._checked(self.factory, {"name": "x", "trigger": {"kind": "schedule", "every": "1d"},
                                                "action": {"kind": "run_assessment", "target": "nonsense"},
                                                "scope": {"kind": "factory"}})
        with self.assertRaises(DecisionRefused):            # the optimise audit's own rule: not a stakeholder's
            itops_assess.run(self.project, "optimise", person=IT[0], persona="stakeholder")
        kinds = [r["event"]["payload"].get("target") for r in self.project.ledger().of_kind("assessment_ran")]
        self.assertIn("optimise", kinds)


class EvalSetsTest(ItOpsCase):
    def test_FR_ITO1_AC_4_eval_sets_list_gnomons_per_project_and_the_role_evals_platform_wide(self):
        view = itops_evals.view(self.project)
        ids = {r["id"]: r for r in view["sets"]}
        self.assertTrue({"gnomon:security", "gnomon:eval", "gnomon:chaos", "role:ask_answers",
                         "role:spec_testability"} <= set(ids))
        self.assertEqual(ids["gnomon:security"]["scope"], "per project")
        self.assertEqual(ids["role:ask_answers"]["scope"], "platform (Rihma's own roles)")
        self.assertEqual(ids["gnomon:security"]["run"]["path"], f"/api/projects/{self.project.pid}/evals/security/run")
        itops_evals.toggle(self.project, "gnomon:security", True, person=IT[0], persona=IT[1])
        self.assertEqual(cstore.enabled(self.project)["gnomon_security"]["every"], "7d")
        itops_evals.toggle(self.project, "role:ask_answers", True, person=IT[0], persona=IT[1])
        with updating_json(self.project.path("evals", "results.json"), {}) as kept:
            kept["security"] = [{"eval": "security", "verdict": v, "at": f"2026-11-2{i}T00:00:00Z", "summary": "",
                                 "scores": {"issues": i}} for i, v in enumerate(("passed", "failed"))]
        view = itops_evals.view(self.project)
        sec = next(r for r in view["sets"] if r["id"] == "gnomon:security")
        self.assertEqual([t["verdict"] for t in sec["trend"]], ["passed", "failed"])
        self.assertEqual(view["line"], f"2 of {len(view['sets'])} eval sets enabled; failing: Security posture")
        trends = {(t["project"], t["set"]) for t in itops_evals.trends(self.factory)}
        self.assertIn((self.project.pid, "gnomon:security"), trends)
        self.assertIn((self.project.pid, "role:ask_answers"), trends)
        row = {"eval": "security", "label": "Security posture", "verdict": "passed", "summary": "held"}
        with mock.patch("kernel.gnomon_evals_run.run", return_value=row) as ran:     # an eval set from an automation
            got = itops_assess.run(self.project, "evalset:gnomon:security", person=IT[0], persona=IT[1],
                                   via="automation AU-001")
        self.assertEqual((got["outcome"], got["verdict"]), ("done", "passed"))
        self.assertEqual((ran.call_args.args[1], ran.call_args.kwargs["via"]), ("security", "automation AU-001"))
        itops_evals.toggle(self.project, "gnomon:security", False, person=IT[0], persona=IT[1])
        self.assertNotIn("gnomon_security", cstore.enabled(self.project))
        with self.assertRaises(DecisionRefused):
            itops_evals.toggle(self.project, "gnomon:security", True, person=IT[0], persona="end_user")
        with self.assertRaises(ValueError):
            itops_evals.toggle(self.project, "role:nonsense", True, person=IT[0], persona=IT[1])


class IncidentTest(ItOpsCase):
    def test_FR_ITO1_AC_5_a_failing_infrastructure_check_opens_an_incident_with_its_evidence_and_remedy(self):
        self.enable("tls", targets=["https://expiring.example.org"])
        row = self.run_check("tls")
        self.assertEqual(row["verdict"], "failed")
        doc = incidents.get(self.factory, row["incident"])
        self.assertEqual((doc["kind"], doc["where"], doc["project"]), ("check_failed", "check:tls", self.project.pid))
        self.assertIn("expiring.example.org:443: the certificate expires in 3.0 days", doc["context"]["trace"])
        self.assertIn("Renew the certificate", doc["context"]["remedy"])
        cls = immune.classify(doc)
        self.assertEqual(cls["id"], "infra_tls")
        self.assertEqual([r["kind"] for r in cls["remedies"]], ["explain", "link", "investigate"])
        again = self.run_check("tls")
        self.assertNotIn("incident", again, "once per change to failed, never once per run")
        failed = list(self.project.ledger().of_kind("infra_check_failed"))
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["event"]["payload"]["source"], "tls")
        from kernel import heal_wiring

        heal_wiring.sweep(self.factory)                      # the sweep's own incident is this one, counted
        same = [i for i in incidents.incidents(self.factory, pid=self.project.pid) if i["where"] == "check:tls"]
        self.assertEqual(len(same), 1)
        self.assertIsNone(itops_heal.on_result(self.project, "tests", {"kind": "tests"}, {"verdict": "failed"}, None))


class ChatTest(ItOpsCase):
    def test_FR_ITO1_AC_6_ask_rihma_says_what_it_checks_and_proposes_the_same_signed_writes(self):
        out = assistant.ask(self.factory, "What should IT check for this project?", persona="it",
                            project_id=self.project.pid)
        self.assertIn("Database-backed", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.project.pid}/itops", "control": "itops_set"})
        ops = [p for p in out["propose"] if p["action"] == "act"]
        self.assertEqual(ops[0]["args"]["call"]["path"], f"/api/projects/{self.project.pid}/itops/apply")
        run = assistant.ask(self.factory, "Run the IT checks", persona="it", project_id=self.project.pid)
        self.assertEqual(run["propose"][1]["args"]["op"], "run_it_checks")
        assess = itops_chat.answer(self.factory, "run the optimise audit", self.project, "ai_architect")
        self.assertEqual(assess["propose"][1]["args"]["call"]["body"], {"target": "optimise"})
        sets = itops_chat.answer(self.factory, "Which eval sets can I run?", self.project, "it")
        self.assertIn("Security posture (per project", sets["answer"])
        on = itops_chat.answer(self.factory, "enable the chaos eval set", self.project, "it")
        self.assertEqual(on["propose"][1]["args"]["call"]["body"], {"set": "gnomon:chaos", "on": True})
        self.assertIsNone(itops_chat.answer(self.factory, "What does it check?", self.project, "it"))
        platform = itops_chat.answer(self.factory, "What should IT check?", None, "it")
        self.assertIn("Documents only: none", platform["answer"])
