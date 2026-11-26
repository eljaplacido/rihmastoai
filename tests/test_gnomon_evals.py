"""FR-EVL1: Gnomon's capability-based audits, benchmarks and evals, run on a project's repository.

A fake `gnomon` on PATH (tests/gnomon_fakes.py) answers as Gnomon 0.6.5's commands do, with their report shapes and
exit codes, and a fake source checkout holds the benchmark scripts: the real Gnomon, its benchmarks and any model
never run here. The catalogue, a run as a cockpit job carried out by `rihmasto evals carry`, the results recorded and
trended, the check kinds and their schedule, the automation action, Insights and Review, findings made change
proposals, goal help and Ask Rihma's proposal, and the command line.
"""

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import gnomon_fakes as gf  # noqa: E402
from console_fakes import PERSON, attached, git_repo  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import gnomon_evals as ge  # noqa: E402
from kernel import gnomon_evals_run as gr  # noqa: E402
from kernel import gnomon_evals_view as gv  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.checks import health as chealth  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.cli import main  # noqa: E402

REPO_FILES = {"README.md": "# Shop\n", "app.py": "def total(items):\n    return sum(items)\n",
              ".gnomon/config.toml": "[routing]\ndefault = \"builder\"\n",
              "REPORT.md": "I fixed total() in app.py:2. 12 passed.\n"}


class EvalsCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = gf.install(self, self.tmp / "bin")
        self.repo = git_repo(self.tmp / "shop", REPO_FILES)
        self.p = attached(self.factory, self.repo, "Shop")

    def run_eval(self, eid, persona="developer", **config):
        lines = []
        row = gr.run(self.p, eid, person=PERSON, persona=persona, config=config or None, emit=lines.append)
        return row, lines

    def ledger(self, kind):
        """The payloads of the project's ledger records of ``kind``, oldest first."""
        records = self.p.ledger().records()
        return [r["event"]["payload"] for r in records if r["event"]["kind"] == kind]

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()


class CatalogueTest(EvalsCase):
    def test_FR_EVL1_AC_1_the_catalogue_says_what_each_measures_needs_costs_and_whether_it_runs_here(self):
        gf.source(self, self.tmp / "gnomon-src", self.tmp / "bin")
        rows = {e["id"]: e for e in ge.public(self.p)}
        self.assertEqual(set(rows), {"security", "security_test", "compliance", "dataflow", "metrics", "audit_verify",
                                     "check", "eval", "chaos", "doctor", "claim_check", "context_cost", "degradation"})
        for e in rows.values():
            for key in ("measures", "inputs", "duration", "models", "reads", "dimension", "check"):
                self.assertTrue(e[key], (e["id"], key))
            self.assertTrue(e["available"], (e["id"], e["why_not"]))
            self.assertEqual(e["check"], "gnomon_" + e["id"])
        self.assertEqual((rows["eval"]["models"], rows["eval"]["roles"]), ("roles", ["builder"]))
        self.assertEqual(rows["security"]["models"], "none")
        self.assertIn(rows["eval"]["duration"], ge.DURATIONS)
        self.assertEqual(ge.detect()["version"], "0.6.5+fake")          # read from the help listing
        # an older Gnomon without these commands, and none at all: not available, with why
        gf.answer(self.fake)
        with mock.patch.object(ge, "detect", return_value={"found": True, "version": "0.2.3", "help": "audit [show|"
                                                           "verify] [--dir <path>]", "command": ["gnomon"]}):
            older = {e["id"]: e for e in ge.public()}
        self.assertTrue(older["audit_verify"]["available"])
        self.assertFalse(older["security"]["available"])
        self.assertIn("0.6.5 or later", older["security"]["why_not"])
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "empty"), "GNOMON_SOURCE": str(self.tmp / "none")}):
            ge._CACHE.clear()
            gone = {e["id"]: e for e in ge.public()}
        self.assertIn("not installed", gone["security"]["why_not"])
        self.assertIn("source checkout", gone["claim_check"]["why_not"])
        ge._CACHE.clear()
        code, out, _ = self.cli("evals", "list", self.p.pid)
        self.assertEqual(code, 0)
        listed = json.loads(out)
        self.assertEqual(listed["gnomon"]["version"], "0.6.5+fake")
        self.assertIn("ask_answers", [s["id"] for s in listed["role_sets"]])


class RunAndRecordTest(EvalsCase):
    def test_FR_EVL1_AC_2_a_run_is_signed_streamed_and_recorded_without_prompts_or_source(self):
        row, lines = self.run_eval("security")
        self.assertEqual(row["verdict"], "passed")
        self.assertIn("0 risk(s), 1 advice", row["summary"])
        self.assertTrue(any("running security" in line for line in lines), lines)      # Gnomon's own output, streamed
        call = gf.calls(self.fake)[-1]
        self.assertEqual(call["argv"][:2], ["security", "--json"])
        self.assertEqual(Path(call["argv"][-1]).resolve(), self.repo.resolve())        # run in the repository
        ran = self.ledger("eval_ran")[-1]
        self.assertEqual((ran["eval"], ran["verdict"], ran["person"], ran["persona"]),
                         ("security", "passed", PERSON, "developer"))
        text = json.dumps(ran)
        self.assertNotIn("sum(items)", text)
        self.assertNotIn("prompt", text)
        self.assertEqual(gr.results(self.p, "security")[-1]["findings"][0]["severity"], "advice")
        with self.assertRaises(gr.EvalsRefused):
            gr.run(self.p, "security", person="factory", persona="developer")
        with self.assertRaises(gr.EvalsRefused):
            gr.run(self.p, "security", person=PERSON, persona="end_user")
        with self.assertRaises(ValueError):
            gr.run(self.p, "eval", person=PERSON, persona="developer", config={"nonsense": 1})

    def test_FR_EVL1_AC_2_the_cockpit_records_a_signed_request_and_its_job_carries_it_out(self):
        req = gr.request(self.p, "compliance", person=PERSON, persona="compliance")
        self.assertEqual(self.ledger("eval_requested")[-1]["request"], req["request"])
        code, out, err = self.cli("evals", "carry", self.p.pid, req["request"])
        self.assertEqual(code, 0, err)
        self.assertIn("running compliance", out)                                    # the job's log: streamed
        self.assertEqual(json.loads(out[out.rindex("\n{"):])["verdict"], "failed")
        ran = self.ledger("eval_ran")[-1]
        self.assertEqual((ran["request"], ran["via"], ran["person"]), (req["request"], "cockpit", PERSON))
        code, _, err = self.cli("evals", "carry", self.p.pid, req["request"])         # once only
        self.assertEqual(code, 2)
        self.assertIn("already carried out", err)

    def test_FR_EVL1_AC_3_every_report_is_read_into_a_verdict_scores_and_findings_and_trended(self):
        gf.source(self, self.tmp / "gnomon-src", self.tmp / "bin")
        cases = {"security_test": ("passed", "held_pct", 100.0), "compliance": ("failed", "evidence_pct", 75.0),
                 "dataflow": ("passed", "hosted", 0), "metrics": ("passed", "verified_pct", 75.0),
                 "audit_verify": ("passed", "intact_pct", 100.0), "check": ("passed", "passed_pct", 100.0),
                 "eval": ("passed", "pass_rate", 80.0), "chaos": ("passed", "announced_pct", 100.0),
                 "doctor": ("passed", "problems", 0), "context_cost": ("passed", "total_bytes", 48200),
                 "degradation": ("failed", "complete_pct", 93.3)}
        for eid, (verdict, score, value) in cases.items():
            row, _ = self.run_eval(eid)
            self.assertEqual((row["verdict"], row["scores"].get(score)), (verdict, value), (eid, row["summary"]))
        row, _ = self.run_eval("claim_check", report="REPORT.md")
        self.assertEqual((row["verdict"], row["scores"]["accuracy"]), ("failed", 50.0))
        self.assertIn("refuted test_count", row["findings"][0]["title"])
        # not measured, with why: nothing to verify, a void chaos run, an undetermined eval, a missing report
        gf.answer(self.fake, audit_verify={"exit": 1, "text": "", "err": "gnomon audit verify: nothing to verify.\n"},
                  chaos=dict(gf.chaos(), exit=2), eval=gf.eval_report(meets="undetermined"))
        for eid in ("audit_verify", "chaos", "eval"):
            row, _ = self.run_eval(eid)
            self.assertEqual(row["verdict"], "not measured", eid)
            self.assertTrue(row["summary"].startswith("not measured"), row["summary"])
        row, _ = self.run_eval("claim_check", report="NOPE.md")
        self.assertEqual(row["verdict"], "not measured")
        # the trend, new and resolved findings
        self.run_eval("security")
        gf.answer(self.fake, security=gf.risky_security())
        row, _ = self.run_eval("security")
        self.assertEqual((row["verdict"], row["issues"], row["new_findings"]), ("failed", 3, 3))
        gf.answer(self.fake, security=gf.security())
        row, _ = self.run_eval("security")
        self.assertEqual((row["new_findings"], row["resolved"]), (0, 3))
        view = {e["id"]: e for e in gv.project_view(self.p)["evals"]}
        self.assertEqual([t["verdict"] for t in view["security"]["trend"]], ["passed", "failed", "passed"])
        self.assertEqual(len(gv.history(self.p, "security")), 3)


class ChecksAutomationsTest(EvalsCase):
    def test_FR_EVL1_AC_4_each_eval_is_a_check_kind_scheduled_weekly_and_an_automation_action(self):
        from kernel import automations as au
        from kernel import automations_text

        cstore.enable(self.p, "gnomon_security", person=PERSON, persona="developer", every="7d")
        self.assertEqual([r["check"] for r in cstore.tick(self.factory)], ["gnomon_security"])   # due: never ran
        health = chealth.project_health(self.p)
        self.assertEqual(health["checks"][0]["state"], "passed")
        self.assertIn("Gnomon Security posture", health["checks"][0]["last"]["summary"])
        self.assertEqual(self.ledger("eval_ran")[-1]["via"], "check")
        self.assertEqual(cstore.tick(self.factory), [])                                   # not due for a week
        tpl = next(t for t in automations_text.TEMPLATES if t["id"] == "weekly_gnomon_audit")
        self.assertEqual(tpl["draft"]["trigger"], {"kind": "schedule", "weekly": "mon 03:00"})
        self.assertIn("run_eval", au.ACTIONS)
        from kernel.gnomon_evals_auto import handle
        out = handle(self.factory, {"id": "AUT-001", "owner": {"person": PERSON, "persona": "operations"},
                                    "action": {"kind": "run_eval", "eval": "doctor"}}, {"project": self.p.pid}, None)
        self.assertEqual((out["outcome"], out["verdict"]), ("done", "passed"))
        self.assertEqual(self.ledger("eval_ran")[-1]["via"], "automation AUT-001")


class InsightsReviewChangeTest(EvalsCase):
    def test_FR_EVL1_AC_5_insights_tiles_per_eval_with_trend_and_review_says_new_issues(self):
        from kernel import insights
        from kernel.review import review

        qa = insights.read(self.factory, "qa", pid=self.p.pid)
        self.assertIn("gnomon_qa", [t["key"] for t in qa["tiles"]])                    # none ran yet: not measured
        self.assertFalse(next(t for t in qa["tiles"] if t["key"] == "gnomon_qa")["measured"])
        self.run_eval("security")
        gf.answer(self.fake, security=gf.risky_security())
        self.run_eval("security")
        self.run_eval("metrics")
        gov = {t["key"]: t for t in insights.read(self.factory, "governance", pid=self.p.pid)["tiles"]}
        self.assertEqual(gov["gnomon_security"]["value"], 3)
        self.assertEqual(gov["gnomon_security"]["sub"], "last runs: passed, failed")
        qa = {t["key"]: t for t in insights.read(self.factory, "qa", pid=self.p.pid)["tiles"]}
        self.assertEqual(qa["gnomon_metrics"]["display"], "75%")
        whole = {t["key"]: t for t in insights.read(self.factory, "governance")["tiles"]}
        self.assertTrue(whole["gnomon_security"]["measured"])
        out = review(self.factory, person=PERSON, persona="developer", since="1d")
        wrong = [i for g in out["groups"] if g["id"] == "wrong" for i in g["items"] if i["kind"] == "eval_ran"]
        self.assertEqual(len(wrong), 1)
        self.assertTrue(wrong[0]["title"].startswith("An audit found 3 new issue(s): Gnomon Security posture"))
        self.assertIn("Audits & evals", [link["label"] for link in wrong[0]["links"]])

    def test_FR_EVL1_AC_6_a_finding_with_its_evidence_becomes_a_change_proposal(self):
        gf.answer(self.fake, security=gf.risky_security())
        self.run_eval("security")
        found = [f for f in gr.findings(self.p) if f["severity"] == "issue"]
        self.assertEqual(len(found), 3)
        made = gr.make_change(self.p, found[0]["id"], person=PERSON, persona="developer")
        card = Canon(self.p).get_card(made["card"])
        self.assertEqual((card["kind"], card["state"]), ("change", "open"))
        self.assertIn(found[0]["title"], card["payload"]["text"])
        self.assertIn("fix:", card["payload"]["text"])                                  # its evidence
        self.assertEqual(self.ledger("eval_finding_changed")[-1]["card"], made["card"])
        self.assertEqual(next(f for f in gr.findings(self.p) if f["id"] == found[0]["id"])["card"], made["card"])
        with self.assertRaises(ValueError):
            gr.make_change(self.p, found[0]["id"], person=PERSON, persona="developer")
        code, out, err = self.cli("evals", "change", self.p.pid, found[1]["id"], "--person", PERSON,
                                  "--persona", "operations")
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["card"].startswith("C-"))


class GoalAndAssistantTest(EvalsCase):
    def test_FR_EVL1_AC_7_goal_help_plans_an_audit_and_ask_rihma_may_propose_running_one(self):
        from kernel import copilot
        from kernel.assistant_rules import check_proposal

        self.assertTrue(copilot.asks_goal("audit this project"))
        plan = copilot.rule_plan(self.factory, self.p, "audit this project")
        self.assertIn("audit", plan["intents"])
        kinds = [(s["action"]["kind"], s["action"].get("check") or s["action"].get("control")) for s in plan["steps"]]
        self.assertIn(("open", "evals_run"), kinds)
        self.assertIn(("enable_check", "gnomon_security"), kinds)
        cost = copilot.rule_plan(self.factory, self.p, "benchmark the context cost")
        self.assertIn("Context cost", cost["steps"][0]["title"])
        self.assertEqual(copilot.catalogue(self.factory, self.p)["evals"]["available"], True)
        ok = {"action": "run_eval", "args": {"eval": "security"}}
        self.assertIsNone(check_proposal(self.factory, self.p, "developer", ok))
        self.assertIn("run by", check_proposal(self.factory, self.p, "end_user", ok))
        self.assertIn("one of", check_proposal(self.factory, self.p, "developer",
                                               {"action": "run_eval", "args": {"eval": "nonsense"}}))


class CommandLineTest(EvalsCase):
    def test_FR_EVL1_AC_9_the_command_line_lists_runs_and_shows_history_and_findings(self):
        code, out, err = self.cli("evals", "run", self.p.pid, "--eval", "check", "--set", "base=HEAD",
                                  "--person", PERSON, "--persona", "developer")
        self.assertEqual(code, 0, err)
        self.assertIn("$ gnomon check --base HEAD", out)
        self.assertEqual(json.loads(out[out.rindex("\n{"):])["verdict"], "passed")
        gf.answer(self.fake, check=gf.check(fail=True))
        code, out, _ = self.cli("evals", "run", self.p.pid, "--eval", "check", "--person", PERSON,
                                "--persona", "developer")
        self.assertEqual(code, 1)                                                          # failed: exit 1
        code, out, _ = self.cli("evals", "history", self.p.pid, "--eval", "check")
        self.assertEqual([r["verdict"] for r in json.loads(out)["results"]], ["passed", "failed"])
        code, out, _ = self.cli("evals", "findings", self.p.pid)
        self.assertIn("verify: fail", json.loads(out)["findings"][0]["title"])
        code, _, err = self.cli("evals", "run", self.p.pid, "--eval", "nonsense", "--person", PERSON,
                                "--persona", "developer")
        self.assertEqual(code, 2)
        self.assertIn("one of", err)


if __name__ == "__main__":
    unittest.main()
