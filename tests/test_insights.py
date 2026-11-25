"""Insights (FR-INS1): seven dimensions read from the records of a fixture home built here, never estimated.

The home (tests/insights_fixture.py) holds Gnomon runs ingested with chained trails in a lanes folder, gate
rounds, a decision, a security scan and an accepted risk, spread over ten days, and a second project with no
record at all. The tests compare each figure with what the fixture wrote.
"""

import contextlib
import csv
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from insights_fixture import build, run  # noqa: E402

from kernel import insights  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.insights.export import export  # noqa: E402
from kernel.insights.lines import change, top  # noqa: E402
from kernel.store import Factory, FixedClock, write_json  # noqa: E402


def tiles(model):
    return {t["key"]: t for t in model["tiles"]}


def charts(model):
    return {c["key"]: c for c in model["charts"]}


class InsightsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-insights-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lanes = self.tmp / "lanes"
        env = mock.patch.dict(os.environ, {"GF_LANES": str(self.lanes)})
        env.start()
        self.addCleanup(env.stop)
        self.clock = FixedClock()
        self.factory = Factory(self.tmp / "home", clock=self.clock)
        self.fx = build(self.factory, self.clock, self.lanes)
        self.loans, self.quiet = self.fx["loans"], self.fx["quiet"]

    def read(self, dimension, window="7d", pid=None):
        model = insights.read(self.factory, dimension, window=window, pid=pid)
        json.dumps(model)                                   # plain JSON, as the cockpit sends it
        return model


class ReadModelTest(InsightsCase):
    def test_FR_INS1_AC_1_usage_sums_per_project_role_model_endpoint_runner_and_window(self):
        for window, (t_in, t_out) in (("24h", self.fx["tokens_24h"]), ("7d", self.fx["tokens_7d"]),
                                      ("30d", self.fx["tokens_all"]), ("all", self.fx["tokens_all"])):
            t = tiles(self.read("usage", window))
            self.assertEqual((t["prompt_tokens"]["value"], t["completion_tokens"]["value"]), (t_in, t_out), window)
            self.assertEqual(t["tokens"]["value"], t_in + t_out, window)
        model = self.read("usage")
        t, c = tiles(model), charts(model)
        self.assertAlmostEqual(t["cost"]["value"], self.fx["cost_7d"])
        self.assertEqual(t["tokens"]["delta"]["before"], 1200)                  # the run ten days ago
        self.assertEqual(t["runs"]["value"], 3)
        self.assertEqual((t["tool_calls"]["value"], t["skills_used"]["value"], t["compactions"]["value"]), (6, 2, 1))
        self.assertEqual(t["local_share"]["value"], round(3600 / 10800 * 100, 1))
        by = lambda key: {r["label"]: r["value"] for r in c[key]["rows"]}          # noqa: E731
        self.assertEqual(by("by_model"), {"hosted-large": 7200, "local-small": 3600})
        self.assertEqual(by("by_endpoint"), {"zen": 7200, "local": 3600})
        self.assertEqual(by("by_role"), {"builder": 10800})
        self.assertEqual(by("by_runner"), {"gnomon": 10800})
        self.assertEqual(by("by_project"), {"Equipment loans": 10800})
        self.assertEqual(by("tools"), self.fx["tools_7d"])                     # from the runs' own trails
        self.assertEqual(c["hosting"]["rows"][0]["values"], {"hosted": 7200, "local": 3600})
        over_time = [r for r in c["tokens_over_time"]["rows"] if r["values"]]
        self.assertEqual(sum(r["values"].get("prompt", 0) for r in over_time), 9000)
        self.assertEqual(len(c["tokens_over_time"]["rows"]), 7)                 # one column a day
        self.assertEqual(len(charts(self.read("usage", "24h"))["tokens_over_time"]["rows"]), 24)
        project = tiles(self.read("usage", pid=self.loans.pid))
        self.assertEqual(project["tokens"]["value"], 10800)
        tasks = {r["label"]: r for r in charts(self.read("usage", pid=self.loans.pid))["by_task"]["rows"]}
        self.assertEqual(tasks["T-002"]["value"], 6000)
        self.assertEqual(tasks["T-002"]["href"], f"#/p/{self.loans.pid}/tasks/T-002")

    def test_FR_INS1_AC_1_qa_governance_security_and_health_count_the_records_of_the_window(self):
        qa = tiles(self.read("qa"))
        self.assertEqual((qa["pass_rate"]["value"], qa["pass_rate"]["sub"]), (66.7, "2 of 3 rounds"))
        self.assertEqual(qa["rounds_per_task"]["value"], 1.5)                    # T-002 two rounds, T-003 one
        self.assertEqual(qa["verifier_disagreements"]["value"], 2)
        self.assertEqual(qa["flaky_reruns"]["value"], 1)
        self.assertEqual(tiles(self.read("qa", "all"))["pass_rate"]["value"], 75.0)
        gov = tiles(self.read("governance"))
        self.assertEqual((gov["decisions"]["value"], gov["time_to_decide"]["value"]), (1, 5.0))
        self.assertEqual(gov["waiting"]["value"], 1)                             # the escalation
        self.assertEqual(gov["ledger_integrity"]["value"], 2)
        self.assertIsNone(tiles(self.read("governance", "24h"))["decisions"]["value"])
        sec = tiles(self.read("security"))
        self.assertEqual((sec["open_findings"]["value"], sec["secret_hits"]["value"], sec["redteam"]["value"]), (1, 1, 1))
        comp = tiles(self.read("compliance"))
        self.assertEqual(comp["accepted_risks"]["value"], 1)
        health = tiles(self.read("health"))
        self.assertEqual(health["idle"]["value"], 237.0)                         # the quiet project, created ten days ago
        self.assertIn("Quiet idea", health["idle"]["line"])


class NotMeasuredTest(InsightsCase):
    def test_FR_INS1_AC_2_a_dimension_without_records_is_not_measured_with_why_and_how_never_zero(self):
        for dimension in insights.DIMENSIONS:
            model = self.read(dimension, pid=self.quiet.pid)
            for t in model["tiles"]:
                if not t["measured"]:
                    self.assertIsNone(t["value"], t["key"])
                    self.assertEqual(t["display"], "not measured")
                    self.assertTrue(t["why"] and t["how"], t["key"])
                    self.assertTrue(t["line"].startswith("Not measured:"))
            for c in model["charts"]:
                self.assertTrue(c["measured"] or (not c["rows"] and c["why"] and c["how"]), c["key"])
            self.assertTrue(model["gaps"], dimension)                           # what it cannot measure here
        usage = tiles(self.read("usage", pid=self.quiet.pid))
        for key in ("tokens", "prompt_tokens", "cost", "runs", "tool_calls", "skills_used", "compactions"):
            self.assertIsNone(usage[key]["value"], key)
        qa = tiles(self.read("qa", pid=self.quiet.pid))
        self.assertIsNone(qa["flaky_reruns"]["value"])                          # no round ran: not "0 reruns"
        health = tiles(self.read("health"))
        self.assertIsNone(health["checks"]["value"])                            # no check enabled here
        self.assertIn("Health tab", health["checks"]["how"])
        drift = tiles(self.read("drift"))
        self.assertIsNone(drift["repo_drift"]["value"])                         # repository alignment is not here
        with self.assertRaises(KeyError):
            insights.read(self.factory, "usage", pid="no-such-project")
        with self.assertRaises(ValueError):
            insights.read(self.factory, "usage", window="90d")

    def test_FR_INS1_AC_2_an_unpriced_run_makes_the_cost_not_measured_and_says_the_priced_part(self):
        self.clock.advance(hours=1)
        run(self.loans, self.lanes, "task-unpriced", model="unknown-model", endpoint="zen", tokens=(10, 5),
            task="T-004", round_no=0, tools=[])
        cost = tiles(self.read("usage"))["cost"]
        self.assertIsNone(cost["value"])
        self.assertIn("1 run had no price", cost["why"])
        self.assertIn(str(self.fx["cost_7d"]), cost["why"])
        self.assertIn("kernel/prices.json", cost["how"])


class LinesTest(InsightsCase):
    def test_FR_INS1_AC_3_each_line_is_computed_by_rule_from_its_own_figures(self):
        self.assertEqual(change("Tokens", 2000, 1000, "7d"), "Tokens doubled against the week before (2,000 against 1,000).")
        self.assertIn("grew 9-fold", change("Tokens", 9000, 1000, "7d"))
        self.assertIn("rose by 25%", change("Tokens", 1250, 1000, "7d"))
        self.assertIn("fell by 20%", change("Tokens", 800, 1000, "7d"))
        self.assertIn("halved", change("Tokens", 500, 1000, "30d"))
        self.assertIn("held steady", change("Tokens", 1000, 1000, "24h"))
        self.assertIn("went from none to", change("Tokens", 10, 0, "7d"))
        self.assertIsNone(change("Tokens", 10, 5, "all"))                       # no window before "all"
        self.assertIsNone(change("Tokens", None, 5, "7d"))
        self.assertEqual(top("the tokens", [{"label": "a", "value": 30}, {"label": "b", "value": 10}]),
                         "a leads the tokens with 30, 75% of the whole.")
        usage = tiles(self.read("usage"))
        self.assertEqual(usage["tokens"]["line"],
                         "Builder prompt tokens grew 9-fold against the week before (9,000 against 1,000).")
        for r in range(2, 6):                                                    # a task that needs five rounds
            run(self.loans, self.lanes, f"task-many-{r}", model="local-small", endpoint="local", tokens=(100, 10),
                task="T-002", round_no=r, tools=[])
        line = tiles(self.read("usage"))["tokens"]["line"]
        self.assertIn("1 task needed 5 or more rounds", line)
        waiting = tiles(self.read("governance"))["waiting"]
        self.assertIn("the oldest, C-0002", waiting["line"])
        self.assertEqual(waiting["href"], f"#/p/{self.loans.pid}/inbox/C-0002")
        for model in (self.read(d, w, pid) for d in insights.DIMENSIONS for w in insights.WINDOWS
                      for pid in (None, self.loans.pid, self.quiet.pid)):
            for item in model["tiles"] + model["charts"]:
                self.assertTrue(item["line"], (model["dimension"], model["window"], item["key"]))   # each has its line


class DriftGovernanceTest(InsightsCase):
    def test_FR_INS1_AC_4_drift_and_governance_follow_their_rules(self):
        p = self.loans
        p.log("spec_written", {"requirements": 1, "criteria": 1})
        self.clock.advance(hours=1)
        p.log("merged", {"task": "T-002"})
        p.log("merged", {"task": "T-003"})
        write_json(p.path("contract.json"), {"requirements": [
            {"id": "R-1", "statement": "s", "acceptance": [{"id": "R-1-AC-1", "check": {"kind": "test"}}]},
            {"id": "R-2", "statement": "s", "acceptance": [{"id": "R-2-AC-1", "check": {"kind": "test"}}]}],
            "tasks": [{"id": "T-001", "criteria": ["R-1-AC-1", "R-2-AC-1"]}]})
        canon = Canon(p)
        canon.add_assumption("Loans last a week", "business", due_days=0)
        canon.add_assumption("Two sites", "business", due_days=30)
        self.clock.advance(days=2)
        drift = tiles(self.read("drift"))
        self.assertEqual(drift["merges_since_spec"]["value"], 2)
        self.assertEqual(drift["untested"]["value"], 2)
        self.assertEqual(drift["untested"]["href"], f"#/p/{p.pid}/spec/R-1")
        self.assertEqual(drift["contradictions"]["value"], 1)                    # the overdue assumption
        self.assertEqual(drift["assumptions_settled"]["value"], 0.0)
        self.assertEqual(drift["context_trims"]["value"], 1)                     # the run that trimmed
        use = charts(self.read("drift"))["context_use"]["rows"]
        self.assertEqual(use[0]["value"], round(30000 / 32768 * 100, 1))
        decisions = p.read("canon/decisions.json")
        decisions += [dict(decisions[0], id="D-0002", card=None, delegation="DL-1", at=self.clock.stamp()),
                      dict(decisions[0], id="D-0003", card=None, automation="AU-1", at=self.clock.stamp())]
        write_json(p.path("canon/decisions.json"), decisions)
        gov = charts(self.read("governance"))["over_time"]
        self.assertEqual({s["key"] for s in gov["series"]}, {"person", "delegation", "automation"})
        self.assertEqual(tiles(self.read("governance", "24h"))["delegated_share"]["value"], 100.0)
        ledger = self.quiet.path("ledger.jsonl")
        ledger.write_text(ledger.read_text(encoding="utf-8").replace("Quiet idea", "Rewritten"), encoding="utf-8")
        integrity = tiles(self.read("governance"))["ledger_integrity"]
        self.assertEqual((integrity["value"], integrity["status"]), (1, "critical"))
        self.assertIn("Quiet idea", integrity["line"])


class ExportCliTest(InsightsCase):
    def cli(self, *argv):
        from kernel.cli import main

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue()

    def test_FR_INS1_AC_5_the_command_line_and_the_three_export_formats_send_nothing(self):
        refuse = mock.patch.object(socket.socket, "connect", side_effect=AssertionError("a network connection"))
        refuse.start()
        self.addCleanup(refuse.stop)
        code, text = self.cli("insights", "--dimension", "usage", "--window", "all")
        self.assertEqual(code, 0)
        self.assertIn("Tokens: 12.0K tokens", text)
        self.assertIn("To measure it:", text)
        code, text = self.cli("insights", self.quiet.pid, "--dimension", "qa", "--json")
        self.assertEqual(json.loads(text)["project"], self.quiet.pid)
        code, text = self.cli("insights", "--json")
        self.assertEqual([d["dimension"] for d in json.loads(text)["dimensions"]], list(insights.DIMENSIONS))
        rows = list(csv.DictReader(io.StringIO(export(self.factory, "csv", dimension="usage", window="7d"))))
        tokens = next(r for r in rows if r["kind"] == "tile" and r["key"] == "tokens")
        self.assertEqual((tokens["value"], tokens["measured"]), ("10800", "True"))
        nm = next(r for r in rows if r["kind"] == "tile" and r["key"] == "skills_accepted")
        self.assertEqual((nm["value"], nm["measured"]), ("", "False"))
        self.assertTrue(nm["why"])
        otlp = json.loads(export(self.factory, "otlp-json", window="7d"))
        metrics = {m["name"]: m for m in otlp["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        self.assertEqual(metrics["rihmasto.insights.usage.tokens"]["gauge"]["dataPoints"][0]["asInt"], "10800")
        self.assertNotIn("rihmasto.insights.usage.skills_accepted", metrics)       # not measured: no data point
        spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertEqual(len(spans), 3)
        attrs = {a["key"]: a["value"] for a in spans[-1]["attributes"]}
        self.assertEqual(attrs["gen_ai.request.model"], {"stringValue": "hosted-large"})
        self.assertEqual(attrs["gen_ai.usage.input_tokens"], {"intValue": "4000"})
        self.assertEqual(attrs["gen_ai.usage.output_tokens"], {"intValue": "800"})
        self.assertEqual(attrs["gen_ai.operation.name"], {"stringValue": "invoke_agent"})
        out = self.tmp / "insights.otlp.json"
        code, text = self.cli("insights", "export", self.loans.pid, "--format", "otlp-json", "--out", str(out))
        self.assertEqual(code, 0)
        self.assertIn("nothing was sent anywhere", text)
        self.assertIn("resourceSpans", out.read_text(encoding="utf-8"))
        code, text = self.cli("insights", "export", "--format", "json", "--dimension", "health")
        self.assertEqual(json.loads(text)["dimensions"][0]["dimension"], "health")
        code, _ = self.cli("insights", "no-such-project")
        self.assertEqual(code, 2)


class RoutesTest(InsightsCase):
    def get(self, path):
        import threading
        import urllib.error
        import urllib.request

        from cockpit.server import make_server

        if not hasattr(self, "server"):
            self.server, boot = make_server(self.factory, 0)
            thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(self.server.origin + "/auth", data=json.dumps({"bootstrap": boot}).encode(),
                                         headers={"Content-Type": "application/json", "Origin": self.server.origin})
            with self.opener.open(req, timeout=10) as res:
                self.token = json.loads(res.read())["token"]
        req = urllib.request.Request(self.server.origin + path, headers={"Authorization": "Bearer " + self.token})
        try:
            with self.opener.open(req, timeout=20) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"null")

    def test_FR_INS1_AC_6_the_cockpit_routes_read_the_same_models_and_write_nothing(self):
        before = self.loans.path("ledger.jsonl").read_bytes()
        status, model = self.get("/api/insights?dimension=usage&window=7d")
        self.assertEqual(status, 200)
        self.assertEqual(tiles(model)["tokens"]["value"], 10800)
        self.assertEqual([d["id"] for d in model["dimensions"]], list(insights.DIMENSIONS))
        status, model = self.get(f"/api/insights?dimension=qa&window=all&project={self.loans.pid}")
        self.assertEqual((status, model["project"]), (200, self.loans.pid))
        status, out = self.get(f"/api/insights/tile?dimension=usage&key=cost&window=7d&project={self.loans.pid}")
        self.assertEqual((status, out["tile"]["key"]), (200, "cost"))
        status, out = self.get("/api/insights/export?format=csv&dimension=security&window=all")
        self.assertEqual(status, 200)
        self.assertTrue(out["filename"].endswith(".csv") and out["text"].startswith("dimension,"))
        self.assertEqual(self.get("/api/insights?dimension=nope")[0], 400)
        self.assertEqual(self.get("/api/insights?window=90d")[0], 400)
        self.assertEqual(self.get("/api/insights?project=_factory")[0], 404)
        self.assertEqual(self.get("/api/insights?project=..%2F..")[0], 404)
        self.assertEqual(self.get("/api/insights/tile?dimension=usage&key=nope")[0], 404)
        self.assertEqual(self.get("/api/insights/export?format=xml")[0], 400)
        self.assertEqual(self.loans.path("ledger.jsonl").read_bytes(), before)


class AssistantTest(InsightsCase):
    def test_FR_INS1_AC_7_the_map_leads_to_insights_and_the_snapshot_holds_figures_only(self):
        from kernel.assistant import find_in_map
        from kernel.assistant_rules import CONTROL_PAGES
        from kernel.assistant_snapshot import snapshot

        self.assertEqual(find_in_map("Where do I see token usage per model?")[0]["id"], "insights_all")
        self.assertEqual(find_in_map("show me the context drift")[0]["id"], "insights_all")
        self.assertEqual(CONTROL_PAGES["insights_export"], ("insights", "insights_all"))
        Canon(self.loans).decide("C-0002", "retry", person="Aino Virtanen", persona="developer",
                                 reason="a reason that stays out")
        snap = snapshot(self.factory)
        part = snap["factory"]["insights"]
        self.assertEqual(part["usage"]["tokens"], "10.8K tokens")
        text = json.dumps(part)
        for hidden in ("Equipment loans", "Quiet idea", "a reason that stays out", "leads"):
            self.assertNotIn(hidden, text)
        snap = snapshot(self.factory, project=self.quiet)
        self.assertNotIn("insights", snap["factory"])
        self.assertEqual(snap["project"]["insights"]["usage"]["tokens"], "not measured")


if __name__ == "__main__":
    unittest.main()
