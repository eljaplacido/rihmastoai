"""FR-AOP3: Agent operations and Who acted, fixed after the AI architect's acceptance test. Fixtures: neutral, made-up
builder rounds below (a stand-in builder, a stand-in verifier, a task whose gate failed three rounds and passed on a
retry), tests/agentops_fakes.py and test_context's planned project; never a real project's.

- AC-1: every builder round is an agent run, by role, harness and model, with its tool calls, once;
- AC-2: a model call's harness comes from its own record: a stand-in is never labelled Gnomon's lane;
- AC-3: Who acted lists every build attempt in the ledger with its gate, and Ask Rihma summarises distinct runs;
- AC-4: a cockpit opened on a demo home keeps its own lanes and the map assistant;
- AC-5: the AI architect's questions reach Agent operations, Optimise and the Agent channel by rule;
- AC-6: the harness overhead answer names every role, the largest share first;
- AC-7: Optimise ranks by the saving over the period, a role with no runs is not measured, one reorder per pack;
- AC-8: runs that recorded no tokens are said apart from a model without a price;
- AC-9: Home's Spend reads the runs and the price table Agent operations reads;
- AC-10: a price proposal is labelled for every project, and the map footer says what Confirm does;
- AC-11: a zero duration is not a measurement;
- AC-12: each run carries the gate its work fed, and failed gates are counted;
- AC-13: the project header counts every open card that waits on a person, as the Inbox lists them;
- AC-14: Ask Rihma suggests the AI architect's own questions (the browser test: tests/test_ui_agentops_arch.py).
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import agentops_fakes as fakes  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_context import planned  # noqa: E402

from kernel import (  # noqa: E402
    agentops,
    agentops_actions,
    agentops_cache,
    agentops_chat,
    agentops_prices,
    assistant,
    git_memo,
    neverlost_chat,
    status,
    who_acted,
)
from kernel.canon import Canon  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "cockpit" / "static"
STAND_IN = {"name": "scripted", "label": "scripted", "version": None, "assurance": "after_run",
            "assurance_label": "in-run policy not enforced by this harness; checked after the run"}


def cell(task, rnd, steps, *, runner=None):
    """A builder round's ``cell_ran`` as kernel/dispatch.py writes it, without a Gnomon record of its own."""
    return {"task": task, "round": rnd, "head": f"{rnd:040d}", "code": 0, "bucket": "result", "stop_reason": "answered",
            "tool_steps": steps, "model": "example-builder", "final_model": "example-builder", "escalated": False,
            "runner": runner or STAND_IN}


def verifier(task):
    """A stand-in verifier's ``model_run`` as kernel/model_usage.py ``timed`` writes it: no tokens, zero seconds."""
    return {"run": None, "task": task, "role": "verifier", "model": "example-large", "endpoint": "example-endpoint",
            "runner": "scripted", "tokens": {"in": None, "out": None, "cached": None, "calls": None},
            "cost": {"measured": False, "why": "the run recorded no token counts"}, "context": {}, "seconds": 0.0,
            "verdict": "passed"}


def rounds(project, task="T-002"):
    """Three failed rounds that escalated, then a retry (its rounds numbered from 0 again) that passed."""
    for rnd, (steps, verdict) in enumerate([(3, "failed"), (3, "failed"), (3, "failed")]):
        project.log("cell_ran", cell(task, rnd, steps))
        project.log("model_run", verifier(task))
        project.log("gate", {"task": task, "round": rnd, "verdict": verdict, "objections": []})
    project.log("escalated", {"task": task, "card": "C-0001"})
    project.log("cell_ran", cell(task, 0, 9))
    project.log("model_run", verifier(task))
    project.log("gate", {"task": task, "round": 0, "verdict": "passed", "objections": []})


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
        self.p = self.new(title="Order intake")
        rounds(self.p)


class RunsTest(Case):
    def test_FR_AOP3_AC_1_every_builder_round_is_an_agent_run_by_role_harness_and_model_with_its_tool_calls(self):
        v = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        roles = {r["role"]: r for r in v["by_role"]}
        b = roles["builder"]
        self.assertEqual((b["harness"], b["model"], b["runs"], b["tool_calls"]), ("scripted", "example-builder", 4, 18))
        self.assertEqual(v["totals"]["tool_calls"], 18)
        self.assertFalse(any(g["what"] == "agent runs" for g in v["gaps"]))
        # the platform view too, and a round Gnomon's record was ingested for is counted once, from that record
        q = self.new(title="Room bookings")
        q.log("gnomon_run", fakes.gnomon_run("T-001", 0, 1000, 200))
        q.log("cell_ran", cell("T-001", 0, 5, runner={"name": "gnomon", "label": "Gnomon"}))
        w = agentops.build(self.factory, window="all", context=False)
        builders = [r for r in w["runs"] if r["role"] == "builder"]
        self.assertEqual(len(builders), 5)
        self.assertEqual([r["tokens"] for r in builders if r["project"] == q.pid], [1200])
        # Agent operations and Who acted name the builder alike
        rows = who_acted.runs(self.factory, self.p)
        self.assertEqual({r["harness"] for r in rows if r["role"] == "builder"}, {b["harness"]})

    def test_FR_AOP3_AC_2_a_stand_in_model_call_is_never_labelled_as_gnomons_lane(self):
        rows = [r for r in who_acted.runs(self.factory, self.p) if r["role"] == "verifier"]
        self.assertEqual(len(rows), 4)
        for r in rows:
            self.assertEqual((r["harness"], r["where"], r["applied"]), ("scripted", "on this machine", False))
            self.assertNotIn("the call is in Gnomon's audit trail", r["gnomon"])
            self.assertIn("no Gnomon audit trail", r["gnomon"])
            self.assertIn("no model was called", r["gnomon"])
        v = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        self.assertEqual({r["harness"] for r in v["by_role"] if r["role"] == "verifier"}, {"scripted"})
        # a call through Gnomon's lane still says so
        self.p.log("model_run", fakes.model_run("analyst", "example-large", 100, 10, 1.0))
        self.assertIn("the call is in Gnomon's audit trail", who_acted.runs(self.factory, self.p)[-1]["gnomon"])

    def test_FR_AOP3_AC_2_a_stand_in_names_its_own_model_never_the_routings(self):
        from kernel import model_usage

        def review(prompt):
            return "no objection"

        with model_usage.for_project(self.p, task="T-009"):
            model_usage.timed(review, "verifier")("x")
            review.model = "example-stand-in"
            model_usage.timed(review, "verifier")("x")
        made = [r["event"]["payload"] for r in self.p.ledger().of_kind("model_run")][-2:]
        self.assertEqual([(m["model"], m["endpoint"], m["runner"]) for m in made],
                         [(None, None, "scripted"), ("example-stand-in", None, "scripted")])

    def test_FR_AOP3_AC_3_who_acted_lists_every_build_attempt_with_its_gate_and_ask_rihma_summarises(self):
        builds = [r for r in who_acted.runs(self.factory, self.p) if r["role"] == "builder"]
        self.assertEqual([(r["what"], r["gate"]) for r in builds],
                         [("Build T-002, attempt 1", "failed"), ("Build T-002, attempt 2", "failed"),
                          ("Build T-002, attempt 3", "failed"), ("Build T-002, attempt 4", "passed")])
        self.assertEqual(len({r["id"] for r in builds}), 4)
        verifier_gates = [r["gate"] for r in who_acted.runs(self.factory, self.p) if r["role"] == "verifier"]
        self.assertEqual(verifier_gates, ["failed", "failed", "failed", "passed"])
        out = neverlost_chat.who_answer(self.factory, self.p, "who acted on T-002?")
        said = out["answer"]
        self.assertIn("8 runs on T-002", said)
        self.assertIn("4 build attempts by the builder cell", said)
        self.assertIn("Build T-002, attempt 4 (gate passed)", said)
        self.assertIn("4 answers by Rihma's verifier through scripted", said)
        sentences = [s.strip() for s in said.split(";") if s.strip()]
        self.assertEqual(len(sentences), len(set(sentences)), said)           # no line repeated

    def test_FR_AOP3_AC_11_a_zero_duration_is_not_a_measurement(self):
        v = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        self.assertIsNone(v["totals"]["seconds_median"])
        self.assertTrue(all(r["seconds"] is None for r in v["runs"]))
        self.assertTrue(all(r["stand_in"] for r in v["runs"]))
        gap = next(g for g in v["gaps"] if g["what"] == "latency")
        self.assertIn("stand-in", gap["why"])
        self.p.log("model_run", fakes.model_run("analyst", "example-large", 100, 10, 2.5))
        w = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        self.assertEqual(w["totals"]["seconds_median"], 2.5)

    def test_FR_AOP3_AC_12_each_run_carries_the_gate_its_work_fed_and_failed_gates_are_counted(self):
        v = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        self.assertEqual((v["totals"]["failed"], v["totals"]["gate_failed"], v["totals"]["gated"]), (0, 6, 8))
        self.assertEqual(sorted(r["gate"] for r in v["runs"] if r["role"] == "builder"),
                         ["failed", "failed", "failed", "passed"])
        roles = {r["role"]: r for r in v["by_role"]}
        self.assertEqual((roles["verifier"]["gate_failed"], roles["verifier"]["failed"]), (3, 0))
        js = (STATIC / "agentops.js").read_text(encoding="utf-8")
        self.assertIn('pick("Call", "Call outcome")', js)                      # the call's outcome, apart
        self.assertIn('pick("Check of the work", "Gate")', js)                # from the gate it fed

    def test_FR_AOP3_AC_8_runs_without_tokens_are_said_apart_from_a_model_without_a_price(self):
        agentops_prices.set_price(self.factory, model="example-large", input=1, output=2, person="Aino",
                                  persona="ai_architect")
        self.p.log("model_run", fakes.model_run("analyst", "example-large", 4000, 1000, 2.0)
                   | {"model": "example-new", "cost": {"measured": False, "why": "not in the price table"}})
        v = agentops.build(self.factory, pid=self.p.pid, window="all", context=False)
        models = {m["model"]: m for m in v["pricing"]["models"]}
        self.assertEqual((models["example-new"]["unpriced"], models["example-new"]["no_tokens"]), (1, 0))
        self.assertEqual((models["example-large"]["unpriced"], models["example-large"]["no_tokens"]), (4, 4))
        self.assertTrue(models["example-large"]["priced"])
        gap = next(g for g in v["gaps"] if g["what"] == "cost")
        self.assertIn("1 of 9 runs have no price for their model, and 8 recorded no token counts", gap["why"])
        js = (STATIC / "agentops_prices.js").read_text(encoding="utf-8")
        self.assertIn('"data-lede": "no-tokens"', js)
        self.assertIn("whatever the price", js)


class AskTest(Case):
    def ask(self, q, pid=None, persona="ai_architect"):
        return assistant.ask(self.factory, q, persona=persona, project_id=pid)

    def test_FR_AOP3_AC_5_the_ai_architects_questions_reach_agent_operations_optimise_and_the_channel(self):
        for pid, route in ((None, "#/agentops"), (self.p.pid, f"#/p/{self.p.pid}/agentops")):
            out = self.ask("How are my agents performing?", pid)
            self.assertEqual((out["navigate"]["route"], out["matches"]), (route, ["agentops"]), out["answer"])
            self.assertIn("the gate failed 6 of the 8 rounds", out["answer"])
            self.assertIn("builder (scripted, example-builder): 4 runs", out["answer"])
            out = self.ask("Run the optimise audit for agent operations", pid)
            self.assertEqual(out["navigate"]["route"], route, out["answer"])
            self.assertIn("record_agent_ops_audit", [p["args"]["op"] for p in out["propose"]])
            out = self.ask("Where is the token use highest?", pid)
            self.assertEqual(out["navigate"]["route"], route)
            self.assertIn("By project: 1. Order intake", out["answer"])
            self.assertIn("By role: 1.", out["answer"])
        out = self.ask("show me what the agents said to each other", self.p.pid)
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.p.pid}/agents", "control": "channel_trace"})
        out = self.ask("show me what the agents said to each other")
        self.assertEqual(out["navigate"], {"route": "#/agents", "control": "agent_activity"})
        # the narrow rules still leave ordinary questions to the model (FR-AOP2-AC-3)
        for q in ("save the context of this project", "what does the ai architect persona do"):
            self.assertIsNone(agentops_chat.asks(q), q)

    def test_FR_AOP3_AC_6_the_harness_overhead_answer_names_every_role_the_largest_first(self):
        view = {"project": None, "window_words": "the last 30 days", "drift": [], "how_runs": "run something",
                "overhead": {"roles": [{"role": r, "system_share": s} for r, s in
                                       (("analyst", 14.7), ("assistant", 3.7), ("builder", 51.3),
                                        ("holdout_author", 16.5), ("verifier", 76.4))]}}
        said = agentops_chat._drift(view)
        self.assertIn("verifier 76.4%; builder 51.3%; holdout_author 16.5%; analyst 14.7%; assistant 3.7%", said)


class OptimiseTest(Case):
    def test_FR_AOP3_AC_7_optimise_ranks_by_the_saving_over_the_period_and_merges_one_packs_reorders(self):
        p = planned(self, title="Room bookings")
        v = agentops_actions.read(self.factory, pid=p.pid, window="all")
        found = v["proposals"]
        reorders = [x for x in found if x["kind"] == "reorder"]
        self.assertTrue(reorders)
        packs = [x["id"] for x in reorders]
        self.assertEqual(len(packs), len(set(packs)))
        self.assertEqual(len({(x["role"], x["title"]) for x in reorders}), len(reorders))   # one per pack
        for x in reorders:
            self.assertIn("Send the parts in this order:", x["detail"])
        builder = [x for x in found if x["role"] == "builder" and x["kind"] in ("reorder", "context_cut")]
        for x in builder:                                  # no builder ran here: its saving is not measured
            self.assertIsNone(x["saving"]["tokens"])
            self.assertEqual(x["saving"]["unmeasured"], "no runs yet, saving not measured")
        # what is measured over the period first, whatever a per-call figure says
        from kernel import agentops_optimise as opt

        ranked = sorted([{"saving": {"tokens": None, "cost": None, "per_call": 733, "unmeasured": opt.NO_RUNS}},
                         {"saving": {"tokens": None, "cost": None, "seconds": 0.5}},
                         {"saving": {"tokens": 40, "cost": None}}], key=opt._rank)
        self.assertEqual([x["saving"].get("unmeasured") for x in ranked], [None, None, opt.NO_RUNS])
        said = agentops_chat._cut(v)
        self.assertNotIn("tokens per call)", said)
        self.assertIn("Together over the period", said)


class SpendTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        agentops_cache.forget()
        lanes = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        lanes.start()
        self.addCleanup(lanes.stop)
        self.p = self.factory.new_project("Order intake", mode="assume", maturity="demo")
        rounds(self.p)
        self.p.log("model_run", fakes.model_run("analyst", "example-large", 4000, 1000, 2.0)
                   | {"model": "example-new", "cost": {"measured": False, "why": "not in the price table"}})

    def test_FR_AOP3_AC_9_homes_spend_reads_the_runs_and_prices_agent_operations_reads(self):
        status_, dash, _ = self.call("GET", "/api/dashboard")
        self.assertEqual(status_, 200, dash)
        _, ops, _ = self.call("GET", "/api/agent-ops?window=30d&context=0")
        s = dash["spend"]
        self.assertEqual(s["runs"], ops["totals"]["runs"])
        self.assertEqual((s["runs"], s["unmeasured_runs"], s["untokened"], s["cloud"]), (9, 9, 8, None))
        status_, out, _ = self.call("POST", "/api/agent-ops/prices", {"model": "example-new", "input": 1, "output": 2,
                                                                      "person": "Aino", "persona": "ai_architect"})
        self.assertEqual(status_, 200, out)
        _, dash, _ = self.call("GET", "/api/dashboard")
        self.assertEqual((dash["spend"]["unmeasured_runs"], dash["spend"]["cloud_measured_part"]), (8, 0.006))
        js = (STATIC / "widgets.js").read_text(encoding="utf-8")
        self.assertNotIn("kernel/prices.json", js)

    def test_FR_AOP3_AC_10_a_price_proposal_is_for_every_project_and_the_footer_says_what_confirm_does(self):
        out = assistant.ask(self.factory, "set the price of example-new to 1 and 3 per million tokens",
                            persona="ai_architect", project_id=self.p.pid)
        [prop] = out["propose"]
        self.assertEqual((prop["project"], prop["scope"]), (None, "platform"))
        self.assertIn("kept for every project", out["answer"])
        # an operation on the open project still names it
        from kernel import assistant_ops

        op = assistant_ops.proposal(self.factory, "run_assessment", {}, persona="ai_architect", project=self.p)
        self.assertEqual((op["project"], op["scope"]), (self.p.pid, "project"))
        js = (STATIC / "assistant.js").read_text(encoding="utf-8")
        self.assertNotIn("It points the way and changes nothing.", js)
        self.assertIn('p.scope === "platform" ? "on Rihmasto · every project"', js)


class HeaderTest(FactoryTestCase):
    def test_FR_AOP3_AC_13_the_header_counts_every_open_card_that_waits_on_a_person(self):
        p = self.new(title="Order intake")
        canon = Canon(p)
        canon.card("change", "A change that needs a decision", payload={"triage": {"needs_decision": True}})
        canon.card("change", "An optimisation filed as a change", payload={"triage": {"needs_decision": False}})
        canon.card("update", "An update to apply")
        now = status.now(p)
        self.assertEqual(now["state"], "waiting_on_you")
        self.assertEqual(len(now["cards"]), len(canon.cards()))
        self.assertTrue(now["line"].startswith("3 decision(s) waiting: change, update"), now["line"])


class DemoHomeTest(FactoryTestCase):
    def test_FR_AOP3_AC_4_a_cockpit_on_a_demo_home_keeps_its_own_lanes_and_the_map_assistant(self):
        from cockpit import server
        from kernel import demo_home

        env = {"GF_LANES": str(self.tmp / "real-lanes")}
        self.assertEqual(demo_home.contain(self.factory, None, env), (None, []))       # a real home: unchanged
        self.assertEqual(env["GF_LANES"], str(self.tmp / "real-lanes"))
        self.factory.home.mkdir(parents=True, exist_ok=True)
        (self.factory.home / demo_home.MARKER).write_text("{}", encoding="utf-8")
        choice, notes = demo_home.contain(self.factory, None, env)
        self.assertEqual((choice, env["GF_LANES"]), ("map", str(self.factory.home / "lanes")))
        self.assertTrue(notes)
        self.assertEqual(demo_home.contain(self.factory, "gnomon", env)[0], "gnomon")    # asked for: kept
        # the cockpit's own start uses it before the assistant's lane is prepared
        chosen = []
        with mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "real-lanes")}), \
                mock.patch.object(server, "assistant_model_for",
                                  side_effect=lambda c: chosen.append((c, os.environ["GF_LANES"])) or (None, "")), \
                mock.patch.object(server, "make_server", side_effect=ValueError("stop here")), \
                redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(server.main(["--home", str(self.factory.home)]), 2)
        self.assertEqual(chosen, [("map", str(self.factory.home / "lanes"))])


if __name__ == "__main__":
    unittest.main()
