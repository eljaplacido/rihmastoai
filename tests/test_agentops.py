"""FR-AOP1: the AI architect persona and Agent operations, across the platform and per project, with the Optimise
audit, recorded and filed as changes, and Ask Rihma answering by rule. Fixtures: tests/agentops_fakes.py (neutral,
made-up figures; never a real project's)."""

import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import agentops_fakes as fakes  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agentops, agentops_actions, agentops_chat, agentops_more, agentops_optimise  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import write_json  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "cockpit" / "static"


def role_evals(factory) -> None:
    """The role evals' scores: the small model within a point of the large one for the analyst."""
    rows = [{"set": "spec_testability", "role": "analyst", "candidate": c, "model": m, "endpoint": "example-endpoint",
             "local": False, "cases": 10, "correct": n, "score_pct": n * 10.0}
            for c, m, n in (("large", "example-large", 9), ("small", "example-small", 9))]
    write_json(factory_project(factory).path("evals", "roles.json"), {"runs": rows})


class AgentOpsModelTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order intake")
        self.q = self.new(title="Room bookings")
        fakes.seed(self.p)
        self.q.log("model_run", fakes.model_run("assistant", "example-small", 2000, 200, 1.2))
        lanes = self.tmp / "lanes"
        fakes.trail(lanes)
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(lanes)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_FR_AOP1_AC_1_runs_per_role_harness_and_model_with_tokens_cost_latency_and_tools(self):
        v = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        t = v["totals"]
        self.assertEqual(t["runs"], 6 * 3 + 3 + 1)
        self.assertGreater(t["tokens"], t["in"] - 1)
        self.assertIsNotNone(t["cost"])                   # every run priced (the fixture's own costs)
        self.assertIsNotNone(t["seconds_median"])
        roles = {(r["role"], r["harness"], r["model"]) for r in v["by_role"]}
        self.assertIn(("verifier", "claude-code", "example-large"), roles)     # a coding agent through its harness
        self.assertIn(("builder", "gnomon", "example-large"), roles)
        tools = {x["tool"]: x for x in v["tools"]["tools"]}
        self.assertEqual(tools["run_tests"]["calls"], 3)
        self.assertEqual(tools["run_tests"]["median_ms"], 4200)
        self.assertTrue(v["tools"]["timed"])
        # every run is there for the drill-down, with what a row of it shows
        self.assertEqual({"id", "project", "title", "role", "harness", "model", "tokens", "cost", "seconds",
                          "verdict", "at"} - set(v["runs"][0]), set())

    def test_FR_AOP1_AC_1_what_is_not_measured_says_why_and_how_never_zero(self):
        empty = self.new(title="Fresh idea")
        v = agentops.build(self.factory, pid=empty.pid, window="7d", context=False)
        self.assertEqual(v["totals"]["runs"], 0)
        for key in ("tokens", "cost", "seconds_median", "tool_calls", "cached_share"):
            self.assertIsNone(v["totals"][key], key)
        self.assertTrue(v["gaps"] and all(g["why"] and g["how"] for g in v["gaps"]))
        self.assertFalse(v["hub"]["measured"])
        self.assertTrue(v["hub"]["why"] and v["hub"]["how"])
        # a run without a price makes the total not measured, the priced part said beside it
        empty.log("model_run", fakes.model_run("analyst", "example-large", 100, 10, 1.0) | {"cost": {"measured": False}})
        empty.log("model_run", fakes.model_run("analyst", "example-large", 100, 10, 1.0))
        t = agentops.build(self.factory, pid=empty.pid, window="all", context=False)["totals"]
        self.assertIsNone(t["cost"])
        self.assertGreater(t["cost_priced"], 0)
        self.assertEqual(t["unpriced"], 1)

    def test_FR_AOP1_AC_2_the_platform_reads_every_project_with_a_role_by_project_heatmap_and_a_trend(self):
        v = agentops.build(self.factory, window="all", context=False)
        self.assertEqual(v["scope"], "factory")
        self.assertEqual({r["project"] for r in v["by_project"]}, {self.p.pid, self.q.pid})
        hm = v["heatmap"]
        self.assertEqual(hm["by"], "project")
        self.assertIn("assistant", hm["rows"])
        self.assertEqual({c["col"] for c in hm["cells"] if c["role"] == "assistant"}, {self.p.pid, self.q.pid})
        self.assertTrue(v["trend"]["measured"])
        days = [pt for pt in v["trend"]["points"] if pt["tokens"]]
        self.assertGreaterEqual(len(days), 6)               # one point per day the agents ran
        one = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        self.assertEqual(one["heatmap"]["by"], "day")

    def test_FR_AOP1_AC_3_overhead_context_drift_and_the_hubs_figures(self):
        v = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        over = {r["role"]: r for r in v["overhead"]["roles"]}
        self.assertEqual(over["analyst"]["calls_per_run"], 2.0)
        self.assertEqual(over["analyst"]["trims"], 6)
        drift = {r["role"]: r for r in v["drift"]}
        self.assertEqual(drift["analyst"]["state"], "fresh")
        self.clock.advance(hours=1)
        Canon(self.p).card("change", "Show overdue loans first")
        self.p.log("change_submitted", {"card": "C-0001", "persona": "developer", "person": "Aino"})
        drift = {r["role"]: r for r in agentops.build(self.factory, pid=self.p.pid, window="all", context=False)["drift"]}
        self.assertEqual((drift["analyst"]["state"], drift["analyst"]["changes_since"]), ("behind", 1))
        self.p.log("agent_sessions_observed", {"measured": True, "sessions": 4, "by_harness": {"claude-code": 4},
                                               "unrecovered_sessions": ["s1"], "rework_heavy": [], "person": "Aino"})
        hub = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)["hub"]
        self.assertEqual((hub["measured"], hub["sessions"], hub["unrecovered"]), (True, 4, 1))

    def test_FR_AOP1_AC_4_the_optimise_rules_propose_concrete_savings(self):
        role_evals(self.factory)
        with mock.patch("kernel.pricing.load_prices", return_value=fakes.PRICES):
            v = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
            found = agentops_optimise.proposals(v)
        kinds = {p["kind"]: p for p in found}
        self.assertEqual(kinds["retries"]["title"], "T-009 needed 3 rounds")
        self.assertEqual(kinds["retries"]["saving"]["tokens"], 21000 + 2500 + 23000 + 2500)
        self.assertGreater(kinds["retries"]["saving"]["cost"], 0)
        self.assertEqual(kinds["slow_tool"]["drill"], {"tool": "run_tests"})
        self.assertEqual(kinds["slow_tool"]["saving"]["seconds"], round((4200 - 1000) * 3 / 1000, 1))
        cheaper = kinds["cheaper_model"]
        self.assertIn("example-small", cheaper["title"])
        self.assertEqual(cheaper["act"]["route"], "#/models")
        self.assertGreater(cheaper["saving"]["cost"], 0)
        for p in found:
            self.assertRegex(p["id"], r"\AOPT-[0-9a-f]{10}\Z")
            self.assertTrue(p["saving"]["basis"], p)
        costs = [p["saving"].get("cost") or 0 for p in found]
        self.assertEqual(costs, sorted(costs, reverse=True))     # the largest saving first

    def test_FR_AOP1_AC_4_context_packs_are_cut_reordered_and_cached_by_rule(self):
        pack = {"id": "spec", "label": "Spec", "role": "analyst", "over_budget": True, "tokens": 9000,
                "with_system": {"tokens": 9500}, "budget": {"tokens": 6000}, "prefix": {"ratio": 0.8},
                "shared": {"ratio": 0.5}, "violations": [{"part": "The brief", "stability": "call",
                                                          "before": ["The rules"], "chars_behind": 4000}],
                "parts": [{"name": "Conventions", "kind": "conventions", "chars": 2000, "content": "x" * 2000}]}
        audit = {"audits": [{"project": self.p.pid, "title": "Order intake", "_packs": [pack], "findings": []}],
                 "skipped": [], "health": [], "read": [self.p.pid], "platform": False}
        with mock.patch.object(agentops_more, "audit", return_value=audit):
            v = agentops.build(self.factory, pid=self.p.pid, window="all")
        found = agentops_optimise.proposals(v)
        by = {(p["kind"], p["title"].split(":")[0]): p for p in found}
        cut = [p for p in found if p["kind"] == "context_cut"]
        self.assertEqual({p["saving"]["per_call"] for p in cut}, {3500, 500})   # over budget, conventions
        self.assertEqual(cut[0]["saving"]["tokens"], cut[0]["saving"]["per_call"] * 6)   # x the analyst's 6 runs
        self.assertIn(("reorder", "Reorder the Spec pack"), by)
        self.assertIn("cache_prefix", {p["kind"] for p in found})
        self.assertEqual(cut[0]["act"], {"route": f"#/p/{self.p.pid}/context", "control": "context_pack",
                                         "label": "Open the context pack"})

    def test_FR_AOP1_AC_5_the_audit_is_recorded_and_a_proposal_filed_as_a_change_signed(self):
        out = agentops_actions.record(self.factory, pid=self.p.pid, window="all", person="Aino Example",
                                      persona="ai_architect")
        rec = self.p.ledger().of_kind("agent_ops_audited")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"], rec["scope"]), ("Aino Example", "ai_architect", self.p.pid))
        self.assertEqual([p["id"] for p in rec["proposals"]], [p["id"] for p in out["proposals"]][:40])
        oid = out["proposals"][0]["id"]
        filed = agentops_actions.file_change(self.factory, pid=self.p.pid, oid=oid, person="Aino Example",
                                             persona="ai_architect", window="all")
        self.assertFalse(filed["already"])
        card = Canon(self.p).get_card(filed["card"]["id"])
        self.assertEqual(card["kind"], "change")
        self.assertIn("Expected saving", card["body"])
        self.assertEqual(self.p.ledger().of_kind("agent_ops_change_filed")[-1]["event"]["payload"]["card"], card["id"])
        again = agentops_actions.file_change(self.factory, pid=self.p.pid, oid=oid, person="Aino Example",
                                             persona="ai_architect", window="all")
        self.assertTrue(again["already"])
        view = agentops_actions.read(self.factory, pid=self.p.pid, window="all", context=False)
        self.assertEqual(next(p for p in view["proposals"] if p["id"] == oid)["card"], card["id"])
        with self.assertRaises(DecisionRefused):
            agentops_actions.record(self.factory, pid=self.p.pid, window="all", person="agent", persona="developer")
        with self.assertRaises(DecisionRefused):
            agentops_actions.record(self.factory, pid=None, window="all", person="Aino", persona="end_user")
        with self.assertRaises(KeyError):
            agentops_actions.file_change(self.factory, pid=self.p.pid, oid="OPT-0000000000", person="Aino",
                                         persona="developer", window="all")
        # the platform's audit is kept in Rihmasto's own canon
        agentops_actions.record(self.factory, pid=None, window="all", person="Aino", persona="it")
        self.assertTrue(factory_project(self.factory).ledger().of_kind("agent_ops_audited"))

    def test_FR_AOP1_AC_6_ask_rihma_answers_cost_cuts_slow_tools_and_drift_by_rule(self):
        from kernel import assistant

        self.assertEqual(agentops_chat.asks("How much do my agents cost?"), "cost")
        self.assertEqual(agentops_chat.asks("Where can I cut tokens?"), "cut")
        self.assertEqual(agentops_chat.asks("Which tool is slow?"), "slow")
        self.assertEqual(agentops_chat.asks("Is there context drift?"), "drift")
        self.assertIsNone(agentops_chat.asks("Test the access token"))
        self.assertIsNone(agentops_chat.asks("What waits on me?"))
        out = assistant.ask(self.factory, "How much do my agents cost?", persona="ai_architect", project_id=self.p.pid)
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/agentops")
        self.assertRegex(out["answer"], r"22 runs, .* tokens .* cost .*USD")
        out = assistant.ask(self.factory, "Which tool is slow?", persona="developer")
        self.assertEqual(out["navigate"]["route"], "#/agentops")
        self.assertIn("run_tests: median 4.2 s", out["answer"])
        out = assistant.ask(self.factory, "Where can I cut tokens?", persona="ai_architect", project_id=self.p.pid)
        self.assertIn("ways to save", out["answer"])
        ops = {p["args"]["op"]: p for p in out["propose"]}
        self.assertEqual(set(ops), {"file_agent_optimisation", "record_agent_ops_audit"})
        call = ops["file_agent_optimisation"]["args"]["call"]
        self.assertRegex(call["path"], rf"\A/api/projects/{self.p.pid}/agent-ops/proposals/OPT-[0-9a-f]{{10}}/change\Z")
        out = assistant.ask(self.factory, "What is the harness overhead?", persona="ai_architect")
        self.assertIn("Context drift across your projects", out["answer"])
        # nothing recorded: not measured, with how
        fresh = self.new(title="Quiet one")
        out = assistant.ask(self.factory, "How much do my agents cost?", persona="ai_architect", project_id=fresh.pid)
        self.assertIn("not measured. How:", out["answer"])


class AiArchitectPersonaTest(unittest.TestCase):
    def test_FR_AOP1_AC_7_the_ai_architect_persona_its_lens_words_and_capsule(self):
        from cockpit.server import PERSONA_INFO
        from kernel.lenses import LENSES, lens_for
        from kernel.people import PERSONAS

        self.assertIn("ai_architect", PERSONAS)
        self.assertEqual(PERSONA_INFO["ai_architect"][0], "AI architect")
        self.assertEqual(lens_for("ai_architect"), "insight")
        self.assertEqual(LENSES["insight"]["views"][0], "agentops")
        caps = (STATIC / "capsules.js").read_text(encoding="utf-8")
        self.assertIn('ai_architect: "agents"', caps)
        self.assertRegex(caps, r'id: "agentops", capsule: "agents".*personas: \["ai_architect"\]')
        words = (STATIC / "words.js").read_text(encoding="utf-8")
        self.assertRegex(words, r'TECH = new Set\(\[[^\]]*"ai_architect"')
        for key in ("agentops:", "agentops_all:"):
            self.assertIn("  " + key + " [[", words)
        core = (STATIC / "core.js").read_text(encoding="utf-8")
        self.assertIn('"agentops_all": "#/agentops", "agentops": "#/p/{pid}/agentops"', core)

    def test_FR_AOP1_AC_7_its_routes_controls_and_chat_paths_are_wired(self):
        from cockpit import solo_routes
        from kernel import assistant_ops, parity
        from kernel.assistant_rules import ui_map
        from kernel.control_pages import CONTROL_PAGES

        m = ui_map()
        self.assertTrue({"agentops", "agentops_all"} <= {v["id"] for v in m["views"]})
        controls = {"agent_ops_window", "agent_ops_drill", "agent_ops_audit", "agent_ops_change"}
        self.assertTrue(controls <= {c["id"] for c in m["controls"]})
        for c in controls:
            self.assertEqual(CONTROL_PAGES[c], ("agentops", "agentops_all"))
        self.assertEqual(parity.CHAT["agent_ops_audit"], ("op", "record_agent_ops_audit"))
        self.assertEqual(parity.CHAT["agent_ops_change"], ("op", "file_agent_optimisation"))
        self.assertIn("agent_ops_drill", parity.READS)
        self.assertEqual(assistant_ops.OPS["file_agent_optimisation"][5], "agent_ops_change")
        for name in ("post_agent_ops_audit", "post_agent_ops_change"):
            self.assertEqual(solo_routes.NEEDS[name](None, {}, {})[0], "ai_architect")
        js = (STATIC / "agentops.js").read_text(encoding="utf-8")
        for c in controls:
            self.assertRegex(js + (STATIC / "agentops_charts.js").read_text(encoding="utf-8"),
                             rf'"data-control"[,:]? ?"{c}"|"{c}"')


class AgentOpsRoutesTest(CockpitTestCase):
    def test_FR_AOP1_AC_8_the_cockpit_reads_the_platform_and_a_project_and_signs_the_writes(self):
        p = self.factory.new_project("Order intake", mode="assume", maturity="demo")
        fakes.seed(p)
        status, out, _ = self.call("GET", "/api/agent-ops?window=all&context=0")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["schema"], "rihmasto.agent-ops/1")
        self.assertNotIn("_rows", out)
        json.dumps(out)
        status, one, _ = self.call("GET", f"/api/projects/{p.pid}/agent-ops?window=all")
        self.assertEqual((status, one["project"]), (200, p.pid))
        self.assertTrue(one["proposals"])
        status, err, _ = self.call("GET", "/api/agent-ops?window=year")
        self.assertEqual(status, 400, err)
        status, err, _ = self.call("GET", "/api/projects/no-such/agent-ops")
        self.assertEqual(status, 404, err)
        status, out, _ = self.call("POST", "/api/agent-ops/audit", {"project": p.pid, "window": "all",
                                                                     "person": "Aino", "persona": "ai_architect"})
        self.assertEqual(status, 200, out)
        oid = out["proposals"][0]["id"]
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/agent-ops/proposals/{oid}/change",
                                   {"window": "all", "person": "Aino", "persona": "ai_architect"})
        self.assertEqual((status, out["already"]), (201, False), out)
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/agent-ops/proposals/OPT-0123456789/change",
                                   {"window": "all", "person": "Aino", "persona": "ai_architect"})
        self.assertEqual(status, 404, out)
        status, out, _ = self.call("POST", "/api/agent-ops/audit", {"person": "Aino", "persona": "end_user"})
        self.assertEqual(status, 403, out)
        self.assertTrue(re.search(r"does not audit agent operations", out["error"]))


if __name__ == "__main__":
    unittest.main()
