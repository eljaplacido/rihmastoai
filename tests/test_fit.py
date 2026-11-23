"""Measured fit (FR-F9): rows come only from records, a rule recommends per workload class, and the
report says what was not measured and what would change each recommendation."""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from adapters.gnomon_ingest import ingest  # noqa: E402
from kernel.fit import (NO_DURATION, assess, fit_report, import_eval_report, map_use_case, registry,  # noqa: E402
                        workload_of)

FIX = Path(__file__).parent / "fixtures" / "gnomon"


def eval_report(**changes) -> dict:
    """A `gnomon eval --json` report shaped as Gnomon 0.6.6 writes it (schema gnomon.eval/3, CONTRACTS
    section 47 and the EvalReport type in packages/gnomon-core/src/eval.ts)."""
    arm = {"kind": "head", "label": "head", "profile": None, "surface_commit": "a" * 40, "surface_hash": "b" * 64,
           "cell_surface_hash": "c" * 64, "model": "qwen3.6-35b", "endpoint": "local"}
    report = {
        "schema": "gnomon.eval/3", "mode": "paired",
        "spec": {"name": "chat-answers", "path": ".gnomon/trials/chat-answers.toml", "sha256": "1" * 64},
        "harness": "gnomon/0.6.6", "role": "assistant",
        "arms": {"base": arm, "candidate": dict(arm, kind="profile", label="profile:cloud", profile="cloud",
                                                model="glm-5.3", endpoint="go"), "differ": []},
        "pairs": {"planned": 8, "run": 8, "valid": 8},
        "cells": {"total": 16, "result": 16, "refusal": 0, "apparatus_failure": 0},
        "endpoints": {"pass": {"base": {"passes": 7, "n": 8, "wilson": [0.53, 0.98]},
                               "candidate": {"passes": 8, "n": 8, "wilson": [0.68, 1.0]},
                               "base_only": 0, "candidate_only": 1, "gain": 1, "mcnemar_p": 1.0},
                      "output_tokens": {"base": 4000, "candidate": 3200, "gain": -800, "sign": None},
                      "requests": {"base": 8, "candidate": 8, "sign": None},
                      "wall_ms": {"base": 16000, "candidate": 40000, "sign": None}},
        "mde": None, "thresholds": {}, "budget": {"requests_used": 16, "cost_enforced": False},
        "trust": {"base": "granted", "candidate": "granted"}, "leftovers": [], "status": "complete",
        "meets_thresholds": True, "reasons": []}
    report.update(changes)
    return report


class FitTestCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        audit = self.tmp / "audit"
        shutil.copytree(FIX, audit)
        self.trail = audit / "analyst-run.jsonl"
        self.record = json.loads((audit / "analyst-run.record.json").read_text(encoding="utf-8"))

    def run_as(self, project, n, **changes):
        """Ingest ``n`` real Gnomon runs (the fixture record, re-verified against its trail) with changes."""
        for _ in range(n):
            ingest(project, dict(self.record, **changes), self.trail)

    def write_report(self, name, report) -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def builder_rounds(self, project, model, verdicts, author=None):
        """The cell and gate events dispatch writes for each task's first round."""
        for i, verdict in enumerate(verdicts, 1):
            task = f"T-{i:03d}"
            project.log("cell_ran", {"task": task, "round": 0, "head": "h", "final_model": model, "model": model})
            project.log("gate", {"task": task, "round": 0, "verdict": verdict, **({"author": author} if author else {})})


class RowsTest(FitTestCase):
    def test_FR_F9_AC_1_rows_come_only_from_records_nothing_is_estimated_and_unmeasured_is_said(self):
        one, two = self.new(title="Loans"), self.new(title="Pallets")
        self.run_as(one, 5, verify="passed")
        self.run_as(one, 1, verify="failed")
        self.run_as(one, 1, bucket="apparatus_failure", code=10, stop_reason="endpoint_error")
        self.run_as(two, 3, model="glm-5.3", verify="passed")
        self.run_as(two, 2, role="translator", model="small-mt")
        self.builder_rounds(one, "deepseek-v4-pro", ["passed", "passed", "failed"])
        self.builder_rounds(two, "deepseek-v4-pro", ["passed"], author={"person": "Pekka"})   # a person's work
        rows = registry(self.factory)["rows"]
        analyst = next(r for r in rows if r["model"] == "deepseek-v4-pro" and r["role"] == "analyst")
        self.assertEqual((analyst["workload"], analyst["runs"], analyst["measured"], analyst["passed"]), ("batch", 7, 6, 5))
        self.assertAlmostEqual(analyst["pass_rate"], 5 / 6)
        self.assertEqual(analyst["apparatus_failures"], 1)                        # beside the rate, never in it
        self.assertEqual(analyst["tokens"]["out"], 7 * self.record["volatile"]["tokens_out"])
        self.assertEqual(analyst["endpoint"], "go")
        # Gnomon's record has its duration, but the ledger does not keep it: latency is not measured,
        # never estimated from the record's other numbers.
        self.assertEqual(self.record["volatile"]["duration_ms"], 121284)
        self.assertIsNone(analyst["latency"])
        self.assertIsNone(analyst["throughput_tokens_per_s"])
        self.assertIn(NO_DURATION, analyst["not_measured"])
        self.assertNotIn("121284", json.dumps(rows))
        gate = next(r for r in rows if r["source"].startswith("ledger: gate"))
        self.assertEqual((gate["role"], gate["model"], gate["measured"], gate["passed"]), ("builder", "deepseek-v4-pro", 3, 2))
        self.assertIn("endpoint: the record does not name it", gate["not_measured"])
        rebuilt = self.new(title="Rebuilt")                                       # the same task, built again later
        self.builder_rounds(rebuilt, "glm-5.3", ["passed"])
        self.builder_rounds(rebuilt, "qwen3.6-35b", ["failed"])
        gates = {r["model"]: (r["passed"], r["measured"]) for r in registry(self.factory)["rows"]
                 if r["source"].startswith("ledger: gate")}
        self.assertEqual((gates["glm-5.3"], gates["qwen3.6-35b"]), ((1, 1), (0, 1)))
        translator = next(r for r in rows if r["role"] == "translator")
        self.assertIsNone(translator["workload"])                                 # no rule: said, not guessed
        self.assertIsNone(translator["pass_rate"])                                # no verify: not measured
        self.assertTrue(any("no rule maps the role 'translator'" in g for g in translator["not_measured"]))
        named = registry(self.factory, roles={"translator": "specialist"})["rows"]
        self.assertEqual(next(r for r in named if r["role"] == "translator")["workload"], "specialist")
        self.assertEqual((workload_of("builder"), workload_of("verifier"), workload_of("analyst"),
                          workload_of("assistant"), workload_of("embed"), workload_of("nobody")),
                         ("batch", "batch", "batch", "interactive", "interactive", None))
        # an eval report in its documented format is imported read-only; any other file is not
        good = self.write_report("eval.json", eval_report())
        before = good.read_bytes()
        imported = import_eval_report(good)
        self.assertEqual(good.read_bytes(), before)
        base = imported["rows"][0]
        self.assertEqual((base["model"], base["endpoint"], base["workload"], base["measured"], base["passed"]),
                         ("qwen3.6-35b", "local", "interactive", 8, 7))
        self.assertEqual(base["latency"]["mean_ms"], 2000.0)                       # 16000 ms over 8 valid cells
        self.assertEqual(base["throughput_tokens_per_s"], 250.0)                   # 4000 tokens in 16 s
        command = eval_report(arms={"base": {"kind": "command", "label": "command:claude", "model": None,
                                             "endpoint": None}, "candidate": None, "differ": []})
        command["endpoints"]["output_tokens"]["base"] = None
        cmd = import_eval_report(self.write_report("cmd.json", command))["rows"][0]
        self.assertEqual(cmd["model"], "command:claude")
        self.assertIsNone(cmd["tokens"]["out"])
        self.assertIn("tokens: Gnomon does not meter a command arm", cmd["not_measured"])
        other = import_eval_report(self.write_report("bench.json", {"runs": [{"task": "x", "passed": True}]}))
        self.assertEqual(other["rows"], [])
        self.assertIn("is not gnomon.eval/3", other["not_imported"])
        self.assertIn("could not be read", import_eval_report(self.tmp / "missing.json")["not_imported"])
        fit = assess(self.factory, ["Classify incoming invoices"], eval_reports=[good, self.tmp / "bench.json"])
        self.assertTrue(any("bench.json" in m and "not gnomon.eval/3" in m for m in fit["not_measured"]))
        self.assertIn("specialist: no measured row", fit["not_measured"])
        bare = assess(self.factory, [])
        self.assertIn("benchmarks: no Gnomon eval report was imported, so no benchmark row is measured",
                      bare["not_measured"])

    def test_FR_F9_AC_1_an_empty_factory_has_no_rows_and_recommends_nothing(self):
        fit = assess(self.factory, ["Answer questions in the website chat"])
        self.assertEqual(fit["rows"], [])
        for rec in fit["recommendations"].values():
            self.assertIsNone(rec["choice"])
            self.assertEqual(rec["why"], "no record for this workload class")


class RecommendationTest(FitTestCase):
    def test_FR_F9_AC_2_the_report_recommends_per_workload_class_by_rule_and_says_what_would_change_it(self):
        one, two = self.new(title="Loans"), self.new(title="Pallets")
        self.run_as(one, 5, verify="passed")
        self.run_as(one, 1, verify="failed")
        self.run_as(two, 3, model="glm-5.3", verify="passed")
        self.builder_rounds(one, "deepseek-v4-pro", ["passed", "passed", "passed", "passed", "failed"])
        report = self.write_report("eval.json", eval_report())
        cases = ["Answer customers' questions in the website chat", "Nightly report of overdue loans",
                 "Classify incoming invoices", "Make things better", "Live report",
                 {"name": "Tag photos", "workload": "specialist"}, {"name": "Help staff", "role": "assistant"}]
        fit = assess(self.factory, cases, eval_reports=[report])
        mapped = {m["use_case"]: m["workload"] for m in fit["use_cases"]}
        self.assertEqual(mapped, {"Answer customers' questions in the website chat": "interactive",
                                  "Nightly report of overdue loans": "batch", "Classify incoming invoices": "specialist",
                                  "Make things better": None, "Live report": None, "Tag photos": "specialist",
                                  "Help staff": "interactive"})
        self.assertIn("equally", map_use_case("Live report")["basis"])
        recs = fit["recommendations"]
        # batch: the best pass rate over at least five measured runs
        self.assertEqual(recs["batch"]["choice"], "deepseek-v4-pro@go as analyst")
        changes = " ".join(recs["batch"]["would_change"])
        self.assertIn("deepseek-v4-pro@? as builder would lead if its pass rate rose above 0.83", changes)
        self.assertIn("glm-5.3@go as analyst has 3 of the 5 measured runs", changes)
        # interactive: the cloud arm passes more; the local one is faster but below the level band
        self.assertEqual(recs["interactive"]["choice"], "glm-5.3@go as assistant")
        self.assertIn("qwen3.6-35b@local as assistant would be weighed on latency if its pass rate rose to 0.95",
                      " ".join(recs["interactive"]["would_change"]))
        self.assertIsNone(recs["specialist"]["choice"])
        self.assertEqual(recs["specialist"]["why"], "no record for this workload class")
        text = fit_report(self.factory, cases, eval_reports=[report])
        for words in ("# Measured fit", "## Use cases", "## Measured candidates", "## Recommendations",
                      "**Recommended: glm-5.3@go as assistant**", "What would change it:", "## Not measured",
                      "| Make things better | not mapped |", "**No recommendation**: no record for this workload class"):
            self.assertIn(words, text)
        self.assertIn(NO_DURATION, text)
        # Measured latency among candidates level on pass rate decides an interactive choice. A ledger run
        # carries `duration_ms` when the ingest keeps Gnomon's duration.
        for _ in range(8):
            one.log("gnomon_run", {"role": "assistant", "model": "qwen3.6-35b", "endpoint": "gx", "verdict": "passed",
                                   "apparatus_failure": False, "tokens": {"in": 100, "out": 50}, "duration_ms": 1000})
        recs = assess(self.factory, cases, eval_reports=[report])["recommendations"]
        self.assertEqual(recs["interactive"]["choice"], "qwen3.6-35b@gx as assistant")
        self.assertIn("mean latency 1000.0 ms", recs["interactive"]["why"])
        self.assertIn("glm-5.3@go as assistant would lead if its mean latency fell below 1000.0 ms (it is 5000.0 ms)",
                      recs["interactive"]["would_change"])
        # a higher minimum leaves nothing qualified, and says what would change that
        strict = assess(self.factory, cases, eval_reports=[report], min_runs=50)["recommendations"]["batch"]
        self.assertIsNone(strict["choice"])
        self.assertEqual(strict["why"], "no candidate has 50 measured runs")
        self.assertTrue(any("reaching 50 measured runs" in c for c in strict["would_change"]))


if __name__ == "__main__":
    unittest.main()
