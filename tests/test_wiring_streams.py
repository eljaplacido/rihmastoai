"""The last three streams wired in: the Review reads the records the other streams really write and the agent
channel, its morning digest runs as an automation, the Google Cloud road's scheduled job is seen everywhere a
release is (the life-cycle events, the Review, Health and Insights), goal help plans with the Drive integration
and the Google Cloud road, and Insights counts the agent channel.

Each test names the criterion it shows, appended to the requirement of the feature it joins.
"""

import copy
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from gcp_fakes import job_road, road  # noqa: E402
from test_deliver import MORE_ROUTES  # noqa: E402
from test_harness_models import HarnessCase  # noqa: E402
from test_roads_gcp_deliver import GcpDeliveryCase  # noqa: E402

from kernel import agent_bridge, copilot, insights, relay  # noqa: E402
from kernel import agent_channel as ch  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel import automations_run as run  # noqa: E402
from kernel import automations_text as words  # noqa: E402
from kernel import operate  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.automations_events import LIFECYCLE  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.review import review  # noqa: E402
from kernel.roads_gcp_ops import rollback  # noqa: E402
from kernel.store import write_json  # noqa: E402

IT = {"person": "Ilkka", "persona": "it"}
DEV = {"person": "Aino Virtanen", "persona": "developer"}
AGENT = ch.agent("claude-code", "Aino Virtanen", "developer")


def items(out: dict, group: str) -> list:
    return next(g["items"] for g in out["groups"] if g["id"] == group)


def kinds(out: dict, group: str) -> set:
    return {i["kind"] for i in items(out, group)}


class ReviewStreamsTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Orders")

    def test_FR_REV1_AC_8_every_kind_the_streams_write_shows_in_went_wrong_and_no_guessed_kind_is_left(self):
        from kernel import review_ledger

        for guessed in ("automation_failed", "check_failed", "job_failed", "harness_refused"):
            self.assertNotIn(guessed, review_ledger.WRONG)                 # no record of these kinds is ever written
        self.p.log("automation_ran", {"id": "AU-001", "project": self.p.pid, "action": "gate", "outcome": "failed",
                                      "detail": "the gate could not run"})
        self.p.log("automation_ran", {"id": "AU-002", "project": self.p.pid, "action": "notify", "outcome": "done"})
        self.p.log("check_ran", {"check": "dependencies", "kind": "dependencies", "verdict": "failed",
                                 "summary": "2 vulnerable packages"})
        self.p.log("check_ran", {"check": "secrets", "kind": "secrets", "verdict": "passed", "summary": "none"})
        self.p.log("console_ran", {"command": "make test", "state": "failed", "exit": 2})
        self.p.log("console_ran", {"command": "git status", "state": "done", "exit": 0})
        self.p.log("runner_refused", {"task": "T-001", "why": "claude-code is not installed here"})
        self.p.log("confidential_refused", {"where": "intake", "roles": ["analyst"]})
        fp = factory_project(self.factory)
        fp.log("automation_paused", {"id": "AU-003", "by": "the circuit breaker", "why": "3 failed runs in a row"})
        fp.log("automation_ran", {"id": "AU-001", "project": self.p.pid, "outcome": "failed"})   # said once, above
        out = review(self.factory, person="Aino Virtanen", persona="developer", since="1h")
        wrong = items(out, "wrong")
        self.assertEqual(sorted(i["kind"] for i in wrong),
                         ["automation_paused", "automation_ran", "check_ran", "confidential_refused", "console_ran",
                          "runner_refused"])
        titles = " | ".join(i["title"] for i in wrong)
        for said in ("Automation AU-001 failed", "Check dependencies failed: 2 vulnerable packages",
                     "A console command failed: make test", "T-001 did not run", "AU-003 was paused by its circuit"):
            self.assertIn(said, titles)

    def test_FR_REV1_AC_9_from_agents_shows_progress_proposals_waiting_and_the_gate_results_agents_asked_for(self):
        from kernel import agent_writes

        agent_writes.progress(self.p, AGENT, "Sorted overdue loans first", files=["app/loans.py"])
        ch.post(self.p, author=AGENT, kind="proposal", text="Q-001: weekly is enough", state="open")
        ch.post(self.p, author=ch.SYSTEM, kind="gate_result", text="The gate passed T-002 for claude-code")
        ch.post(self.p, author=ch.person("Aino Virtanen", "developer"), kind="note", text="a person's note")
        out = review(self.factory, person="Aino Virtanen", persona="developer", since="1h")
        self.assertEqual(kinds(out, "agents"), {"channel_progress", "channel_proposal", "channel_gate_result"})
        first = items(out, "agents")[0]
        self.assertEqual(first["kind"], "channel_proposal")                  # what waits on a person comes first
        self.assertIn("waiting on a person", first["title"])
        self.assertIn("from agents", out["headline"])
        feedback = agent_bridge.review_feedback(self.p)                       # the bridge reads the real Review
        self.assertIsInstance(feedback, list)


class DigestAutomationTest(FactoryTestCase):
    def test_FR_REV1_AC_10_the_morning_review_digest_runs_as_an_automation_and_holds_back_when_nothing_happened(self):
        p = self.new(title="Orders")
        posted = []
        tools = run.Tools(environ={"SLACK_URL": "https://hooks.example/slack"},
                          post=lambda url, body, headers: posted.append(body.decode("utf-8")) or 200)
        sub = relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["it"], **IT)
        t = next(t for t in words.TEMPLATES if t["id"] == "morning_review_digest")
        self.assertEqual(t["label"], "Morning review digest")                # the Review's own TEMPLATE
        draft = copy.deepcopy(t["draft"])
        draft["action"]["subscription"] = sub["id"]
        a = au.add(self.factory, draft, **IT)
        run.request_run(self.factory, a["id"], **IT)
        run.tick(self.factory, tools)
        self.assertEqual(posted, [])                                          # nothing happened: held back
        p.log("check_ran", {"check": "dependencies", "verdict": "failed", "summary": "2 vulnerable packages"})
        run.request_run(self.factory, a["id"], **IT)
        run.tick(self.factory, tools)
        self.assertEqual(len(posted), 1)
        self.assertIn("Since you last looked", posted[0])
        rows = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("automation_ran")]
        self.assertEqual([r["outcome"] for r in rows if r["id"] == a["id"]], ["nothing", "done"])


class GcpJobWiredTest(GcpDeliveryCase):
    def entry(self) -> dict:
        return job_road()

    def test_FR_GCP1_AC_8_a_scheduled_job_fires_the_life_cycle_events_and_its_failed_execution_is_seen(self):
        self.ship()
        job = roadmod.slot_state(self.project, "production")["job"]
        cstore.enable(self.project, "executions", **DEV)
        self.assertEqual(cstore.run(self.project, "executions", **DEV)["verdict"], "not measured")
        self.fake.add_execution(job, ok=False, n=1)
        operate.tick(self.project)
        row = cstore.run(self.project, "executions", **DEV)
        self.assertEqual(row["verdict"], "failed")
        self.assertIn(f"{job}-s1", "\n".join(row["evidence"]))
        self.commit_routes(MORE_ROUTES, "A count route")
        self.ship()                                                           # a second release to go back from
        rollback(self.project, "production", person="Jaana", persona="it", reason="the transcripts are empty")
        said = {r["event"]["kind"]: r["event"] for r in self.project.ledger().records()}
        for name in LIFECYCLE:
            if name in ("concept_validated", "plan_approved", "first_build_passed"):
                continue                     # before delivery: the road does not change them
            hits = [ev for ev in [{"kind": k, **(e.get("payload") or {})} for k, e in said.items()]
                    if run.matches({"kind": "event", "types": [name]}, ev)]
            self.assertTrue(hits, f"{name} never fired for the Google Cloud job")
        out = review(self.factory, person="Aino", persona="product_owner", since="2000-01-01T00:00:00Z")
        self.assertTrue({"probe_failed", "incident_opened", "check_ran"} <= kinds(out, "wrong"))
        probes = {t["key"]: t for t in insights.read(self.factory, "health", pid=self.project.pid)["tiles"]}["probes"]
        self.assertEqual((probes["value"], probes["status"]), (0, "critical"))   # its execution failed


class DriveGoalTest(FactoryTestCase):
    def test_FR_CPL1_AC_6_the_drive_goal_on_an_adopted_project_uses_the_drive_integration_and_the_google_cloud_road(self):
        write_json(self.factory.paved_roads_path, {"schema": roadmod.SCHEMA, "roads": {"company-gcp": road()},
                                                   "maturity": {"production": "company-gcp"}})
        p = self.new(title="Invoice archive")
        p.update_meta(source_kind="adopted", intent="improve")
        plan = copilot.plan(self.factory, p, "I want to hook this solution to Google Drive, run in Google Cloud")
        self.assertEqual(plan["gaps"], [])                                    # no "no connector", no "no road"
        steps = {s["title"]: s for s in plan["steps"]}
        declare = steps["Declare the Google Drive integration"]
        self.assertIn("--kind gdrive", declare["action"]["command"])
        self.assertIn("app/gdrive.py", declare["detail"])
        where = steps["Choose where it runs in production"]
        self.assertTrue(where["available"])
        self.assertIn("company-gcp (gcp-cloudrun)", where["detail"])


class ChannelInsightsTest(FactoryTestCase):
    def test_FR_INS1_AC_11_insights_counts_agents_proposals_and_how_they_were_settled_and_rihmas_channel_answers(self):
        from kernel import channel_rihma
        from kernel.model import FakeModel

        p = self.new(title="Orders")
        ch.post(p, author=AGENT, kind="proposal", text="Q-001: weekly", state="open")
        ch.post(p, author=AGENT, kind="proposal", text="Q-002: monthly", state="rejected")
        gov = {t["key"]: t for t in insights.read(self.factory, "governance", pid=p.pid)["tiles"]}["agent_proposals"]
        self.assertEqual((gov["value"], gov["sub"]), (2, "1 waiting"))
        self.assertIn("1 rejected", gov["line"])
        asked = ch.post(p, author=AGENT, kind="question", text="@analyst what does R-1-AC-1 mean, in short?")
        with mock.patch.dict(os.environ, {}):
            channel_rihma.reply(p, asked, model=FakeModel(lambda prompt, role: "It means the list is sorted."))
        usage = {t["key"]: t for t in insights.read(self.factory, "usage", pid=p.pid)["tiles"]}["channel_tokens"]
        self.assertEqual((usage["value"], usage["sub"]), (1, "tokens not recorded"))   # a scripted answer
        self.assertIn("answered agents in the channel 1 time", usage["line"])


class HarnessWiredTest(HarnessCase):
    def test_FR_HMD1_AC_9_the_channel_and_goal_help_go_through_the_harness_recorded_once_per_project(self):
        from kernel import channel_rihma, copilot_catalog, harness_setup
        from kernel import models_setup as kmodels

        nowhere = mock.patch.dict(os.environ, {"GNOMON_CMD": (self.tmp / "no-gnomon-here").as_posix()})
        nowhere.start()                                     # no model is ever asked: only the fake coding agent answers
        self.addCleanup(nowhere.stop)
        self.agent("claude-code")
        self.use()                                          # the text roles answered by Claude Code
        p = self.new(title="Tool loans")
        asked = ch.post(p, author=AGENT, kind="question", text="@analyst what does R-1-AC-1 mean, in short?")
        channel_rihma.reply(p, asked, model=self.model())
        copilot.model_plan(self.factory, p, "I want to run it every night in our cloud", self.model())
        rows = self.runs(p)
        self.assertEqual([(r["harness"], r["task"]) for r in rows], [("claude-code", "channel"), ("claude-code", "goal")])
        self.assertEqual(self.runs(), [])                                     # in the project's ledger, never twice
        usage = insights.read(self.factory, "usage", pid=p.pid)
        self.assertEqual({t["key"]: t for t in usage["tiles"]}["runs"]["value"], 2)
        by_runner = next(c for c in usage["charts"] if c["key"] == "by_runner")
        self.assertIn("claude-code", [r["label"] for r in by_runner["rows"]])  # usage by harness
        with mock.patch.object(kmodels, "models_view", return_value={"ready": False}), \
                mock.patch.object(harness_setup, "found_harnesses",
                                  return_value=[{"id": "claude-code", "label": "Claude Code", "version": "2.1"}]):
            cat = copilot_catalog.catalogue(self.factory, p)
            plan = copilot.rule_plan(self.factory, p, "I want to run it every night in our cloud", cat=cat)
        use = next(s for s in plan["steps"] if s["title"].startswith("Use the coding agent you already have"))
        self.assertEqual((use["action"]["control"], use["action"]["route"]), ("models_use_claude", "#/models"))
        self.assertTrue(use["action"]["command"].startswith("rihmasto models use claude-code"))


if __name__ == "__main__":
    unittest.main()
