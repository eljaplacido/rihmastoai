"""FR-AOP2: Agent operations, fixed after its independent check. Fixtures: tests/agentops_fakes.py (neutral, made-up
figures) and test_context's planned project (a request, a spec and a repository; never a real project's).

- AC-1: the context packs are read once while nothing they are built from changed: main's files are asked of git
  once per commit, a project's audit is kept while its files are unchanged, and a period switch reads nothing again;
- AC-2: Ask Rihma's drift and overhead answer reads the packs and says the harness overhead, or that it is not
  measured with why and how;
- AC-3: only questions about the agents' tokens, costs or context are answered by rule;
- AC-4: "how to measure" names no file of the installation, and a model is priced in the cockpit and by Ask Rihma;
- AC-5: a value alone on its line is drawn as a dot (the browser test: tests/test_ui_agentops_fix.py).
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import agentops_fakes as fakes  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_context import planned  # noqa: E402

from kernel import agentops, agentops_actions, agentops_cache, agentops_chat, agentops_prices, git_memo  # noqa: E402
from kernel import agentops_price_chat  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "cockpit" / "static"
PATHS = re.compile(r"kernel/|\.py\b|prices\.json|duration_ms|tool_call")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


class Counting:
    """Every git process started, by its first two words."""

    def __init__(self):
        self.real, self.calls = subprocess.Popen.__init__, []

    def __enter__(self):
        real, calls = self.real, self.calls

        def spy(proc, args, *a, **k):
            if isinstance(args, (list, tuple)) and args and Path(str(args[0])).stem == "git":
                calls.append(" ".join(map(str, args[:3])))
            return real(proc, args, *a, **k)

        self.patch = mock.patch.object(subprocess.Popen, "__init__", spy)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()


class Case(FactoryTestCase):
    def setUp(self):
        super().setUp()
        git_memo.forget()
        agentops_cache.forget()
        self.addCleanup(git_memo.forget)
        self.addCleanup(agentops_cache.forget)
        lanes = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        lanes.start()
        self.addCleanup(lanes.stop)


class ReadOnceTest(Case):
    def setUp(self):
        super().setUp()
        self.p = planned(self, title="Order intake")
        self.q = planned(self, title="Room bookings")
        fakes.seed(self.p)
        fakes.seed(self.q, days=2)

    def test_FR_AOP2_AC_1_main_is_asked_once_per_commit_and_a_period_switch_reads_nothing_again(self):
        with Counting() as first:
            v = agentops_actions.read(self.factory, window="30d")
        self.assertTrue(v["context"]["measured"])
        with Counting() as again, mock.patch("kernel.context_audit.project_audit",
                                             side_effect=AssertionError("built again")):
            for window in ("7d", "all", "30d"):
                w = agentops_actions.read(self.factory, window=window)
                self.assertEqual(len(w["context"]["packs"]), len(v["context"]["packs"]))
            agentops_actions.read(self.factory, pid=self.p.pid, window="24h")
        self.assertEqual(again.calls, [], "a period switch asked git again")
        self.assertLess(len(first.calls), 40, first.calls)         # was about 50 per project
        # one git process reads every test name on main, not one per file
        self.assertLessEqual(sum(1 for c in first.calls if c.startswith("git show")), 0, first.calls)

    def test_FR_AOP2_AC_1_a_new_record_or_a_moved_main_reads_again(self):
        agentops_actions.read(self.factory, pid=self.p.pid, window="all")
        built = []
        from kernel import context_audit

        keep = context_audit.project_audit

        def count(*a, **k):
            built.append(a[1].pid)
            return keep(*a, **k)

        with mock.patch.object(context_audit, "project_audit", side_effect=count):
            agentops_actions.read(self.factory, pid=self.p.pid, window="all")
            self.assertEqual(built, [])
            self.p.log("change_submitted", {"card": "C-0001", "persona": "developer", "person": "Aino"})
            agentops_actions.read(self.factory, pid=self.p.pid, window="all")
            self.assertEqual(built, [self.p.pid])
        # main's commit is read from the ref files, loose or packed; a new commit is a new key
        repo = self.p.path("repo.git")
        sha = git_memo.main_commit(repo)
        self.assertRegex(sha or "", r"\A[0-9a-f]{40}\Z")
        asked = []
        self.assertEqual(git_memo.on_main(repo, "x", lambda: asked.append(1) or ["a"]), ["a"])
        self.assertEqual(git_memo.on_main(repo, "x", lambda: asked.append(1) or ["b"]), ["a"])
        ref = repo / "refs" / "heads" / "main"
        ref.unlink()
        (repo / "packed-refs").write_text(f"# pack-refs\n{'0' * 40} refs/heads/main\n", encoding="utf-8")
        self.assertEqual(git_memo.main_commit(repo), "0" * 40)
        self.assertEqual(git_memo.on_main(repo, "x", lambda: asked.append(1) or ["c"]), ["c"])
        self.assertEqual(len(asked), 2)

    def test_FR_AOP2_AC_2_the_drift_answer_says_the_harness_overhead(self):
        from kernel import assistant

        out = assistant.ask(self.factory, "What is the context drift and harness overhead?", persona="ai_architect",
                            project_id=self.p.pid)
        self.assertIn("Context drift for Order intake", out["answer"])
        self.assertRegex(out["answer"], r"Harness overhead \(the system prompt's share of what a role is given\): "
                                        r"\w+ \d+(\.\d+)?%")


class OverheadNotMeasuredTest(Case):
    def test_FR_AOP2_AC_2_overhead_not_measured_says_why_and_how(self):
        from kernel import assistant

        p = self.new(title="Fresh idea")
        p.log("model_run", fakes.model_run("analyst", "example-large", 100, 10, 1.0))
        none = {"audits": [], "skipped": [], "health": [], "read": [p.pid], "platform": False}   # no pack built
        with mock.patch("kernel.agentops_more.audit", return_value=none):
            out = assistant.ask(self.factory, "Is there context drift?", persona="ai_architect", project_id=p.pid)
        self.assertRegex(out["answer"], r"Harness overhead: not measured: .+\. How: .+")


class NarrowQuestionsTest(Case):
    ASKED = {"Where can I cut tokens?": "cut", "How can we reduce token usage?": "cut",
             "Reduce the agents' costs": "cut", "Cut AI spend": "cut", "Optimise my agents": "cut",
             "Shrink the context packs": "cut", "Lower the cost of our agents": "cut",
             "How much do my agents cost?": "cost", "Which tool is slow?": "slow",
             "What is the context drift and harness overhead?": "drift"}
    NOT_ASKED = ("save the context of this project", "what does the ai architect persona do",
                 "reduce the project's costs", "save the agents list", "save the access token",
                 "reduce delivery costs", "cut the scope to save time", "how do we reduce costs",
                 "who is the ai architect", "set the price of oranges to 3 and 4")

    def test_FR_AOP2_AC_3_only_questions_about_the_agents_tokens_costs_or_context_are_answered_by_rule(self):
        for q, kind in self.ASKED.items():
            self.assertEqual(agentops_chat.asks(q), kind, q)
        p = self.new(title="Order intake")
        for q in self.NOT_ASKED:
            self.assertIsNone(agentops_chat.asks(q), q)
            for persona in ("developer", "business_owner"):
                self.assertIsNone(agentops_chat.answer(self.factory, q, p, persona), (q, persona))


class PricingTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        agentops_cache.forget()
        self.p = self.factory.new_project("Order intake", mode="assume", maturity="demo")
        fakes.seed(self.p)
        self.p.log("model_run", fakes.model_run("analyst", "example-large", 4000, 1000, 2.0) | {"model": "example-new", "cost": {
            "measured": False, "why": "'example-new' is not in the price table"}})

    def test_FR_AOP2_AC_4_how_to_measure_names_no_file_of_the_installation(self):
        empty = self.factory.new_project("Fresh idea", mode="assume", maturity="demo")
        empty.log("model_run", fakes.model_run("analyst", "example-large", 100, 10, None) | {"model": "example-new", "cost": {"measured": False}})
        for pid in (self.p.pid, empty.pid, None):
            v = agentops_actions.read(self.factory, pid=pid, window="all")
            cost = next(g for g in v["gaps"] if g["what"] == "cost")       # each has an unpriced run
            self.assertIn("Price a model on Agent operations", cost["how"])
            hows = [g["how"] for g in v["gaps"]] + [v["how_runs"], v["context"]["how"], v["overhead"]["how"],
                                                    v["hub"].get("how") or ""]
            for text in hows:
                self.assertIsNone(PATHS.search(text), text)
            self.assertFalse([s for s in strings(agentops.public(v)) if "kernel/" in s or "prices.json" in s])
        from kernel import agentops_more

        for text in (agentops.HOW_PRICE, agentops.HOW_SECONDS, agentops_more.HOW_TRAILS, agentops_more.HOW_TOOL_TIME):
            self.assertIsNone(PATHS.search(text), text)
            self.assertNotIn("harness", text)          # a business owner's jargon list

    def test_FR_AOP2_AC_4_a_model_is_priced_in_the_cockpit_and_its_runs_are_then_measured(self):
        status, before, _ = self.call("GET", f"/api/projects/{self.p.pid}/agent-ops?window=all&context=0")
        self.assertEqual(status, 200, before)
        self.assertIsNone(before["totals"]["cost"])
        new = next(m for m in before["pricing"]["models"] if m["model"] == "example-new")
        self.assertEqual((new["priced"], new["unpriced"], new["runs"]), (False, 1, 1))
        self.assertEqual(before["pricing"]["models"][0]["model"], "example-new")      # what needs a price first
        body = {"model": "example-new", "input": "1.5", "output": 6, "person": "Aino", "persona": "ai_architect"}
        status, out, _ = self.call("POST", "/api/agent-ops/prices", body)
        self.assertEqual(status, 200, out)
        self.assertEqual(out["price"], {"input": 1.5, "output": 6.0})
        kept = json.loads((self.factory.home / agentops_prices.HOME_FILE).read_text(encoding="utf-8"))
        self.assertEqual(kept["models"]["example-new"]["set_by"], "Aino")
        rec = factory_project(self.factory).ledger().of_kind("model_price_set")[-1]["event"]["payload"]
        self.assertEqual((rec["model"], rec["input"], rec["person"], rec["persona"]),
                         ("example-new", 1.5, "Aino", "ai_architect"))
        status, after, _ = self.call("GET", f"/api/projects/{self.p.pid}/agent-ops?window=all&context=0")
        self.assertIsNotNone(after["totals"]["cost"])
        run = next(r for r in after["runs"] if r["model"] == "example-new")
        self.assertEqual(run["cost"], round((4000 * 1.5 + 1000 * 6) / 1e6, 6))
        self.assertTrue(run["priced_now"])
        self.assertFalse(any(g["what"] == "cost" for g in after["gaps"]))
        # a model on the person's own machine: no API money
        status, out, _ = self.call("POST", "/api/agent-ops/prices", {"model": "example-new", "local": True,
                                                                     "person": "Aino", "persona": "it"})
        self.assertEqual((status, out["price"]), (200, {"local": True}), out)
        # refused: a persona that does not price, a figure that is not a price, a hosted model without both
        status, out, _ = self.call("POST", "/api/agent-ops/prices", {"model": "m", "input": 1, "output": 2,
                                                                     "person": "Aino", "persona": "end_user"})
        self.assertEqual(status, 403, out)
        for bad in ({"model": "m", "input": -1, "output": 2}, {"model": "m", "input": 1},
                    {"model": "two words", "input": 1, "output": 2}, {"model": "m", "input": "x", "output": 2}):
            status, out, _ = self.call("POST", "/api/agent-ops/prices", bad | {"person": "Aino",
                                                                               "persona": "ai_architect"})
            self.assertEqual(status, 400, (bad, out))

    def test_FR_AOP2_AC_4_ask_rihma_prices_a_model_for_the_person_to_confirm(self):
        from kernel import assistant

        out = assistant.ask(self.factory, "Set the price of example-new to 1.5 and 6 per million tokens",
                            persona="ai_architect", project_id=self.p.pid)
        self.assertEqual(out["navigate"], {"route": "#/agentops", "control": "agent_ops_price"})
        self.assertIn("example-new costs 1.5 USD per million tokens in and 6 out", out["answer"])
        op = out["propose"][0]["args"]
        self.assertEqual(op["op"], "set_model_price")
        self.assertEqual(op["call"], {"method": "POST", "path": "/api/agent-ops/prices",
                                      "body": {"model": "example-new", "input": 1.5, "output": 6.0}})
        self.assertFalse(factory_project(self.factory).ledger().of_kind("model_price_set"))   # Rihma wrote nothing
        local = agentops_price_chat.parse("Mark example-new as local")
        self.assertEqual(local, {"model": "example-new", "local": True})
        out = assistant.ask(self.factory, "How do I price a model?", persona="business_owner")
        self.assertIn("Price a model", out["answer"])
        self.assertEqual(out["navigate"]["control"], "agent_ops_price")
        out = assistant.ask(self.factory, "Set the price of example-new to 1 and 2 per million tokens",
                            persona="end_user")
        self.assertEqual(out["propose"], [])
        self.assertIn("may not price a model", out["answer"])

    def test_FR_AOP2_AC_4_pricing_is_wired_to_the_map_parity_and_access(self):
        from cockpit import solo_routes
        from kernel import assistant_ops, parity
        from kernel.assistant_rules import ui_map
        from kernel.control_pages import CONTROL_PAGES

        self.assertIn("agent_ops_price", {c["id"] for c in ui_map()["controls"]})
        self.assertEqual(CONTROL_PAGES["agent_ops_price"], ("agentops", "agentops_all"))
        self.assertEqual(parity.CHAT["agent_ops_price"], ("op", "set_model_price"))
        self.assertEqual(assistant_ops.OPS["set_model_price"][5], "agent_ops_price")
        self.assertEqual(solo_routes.NEEDS["post_agent_ops_price"](None, {}, {})[0], "ai_architect")
        js = (STATIC / "agentops_prices.js").read_text(encoding="utf-8")
        self.assertIn('"data-control": "agent_ops_price"', js)
        self.assertIn('emptyState("agentops_prices"', js)
        self.assertIn("pricesCard(d, redraw)", (STATIC / "agentops.js").read_text(encoding="utf-8"))


class LoneValueTest(unittest.TestCase):
    def test_FR_AOP2_AC_5_a_value_alone_on_its_line_is_drawn_as_a_dot(self):
        js = (STATIC / "agentops_charts.js").read_text(encoding="utf-8")
        self.assertIn('class: "aol-pt"', js)
        self.assertIn("!has(s, i - 1) && !has(s, i + 1)", js)
        css = (STATIC / "agentops.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.aol-pt \{[^}]*width: 6px")


if __name__ == "__main__":
    unittest.main()
