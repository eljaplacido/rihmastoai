"""Automations on the life-cycle steps and their transitions (FR-AUT1-AC-17; D-0023: "Every transition is
visible, recorded, and can trigger an automation").

Each transition has a clear record an event trigger names (kernel/automations_events.py), and the four life-cycle
templates (kernel/automations_text.py) each fire on their event. Notices go to a fake transport; no network.
"""

import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_automations import AutoCase  # noqa: E402
from test_project_change import ChangeCase  # noqa: E402

from kernel import automations as au  # noqa: E402
from kernel import automations_run as run  # noqa: E402
from kernel import automations_text as words  # noqa: E402
from kernel import relay  # noqa: E402
from kernel.automations_events import COMMON_EVENTS, LIFECYCLE, records_of  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.deliver import _Delivery  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

IT = {"person": "Ilkka", "persona": "it"}


class TransitionRecordsTest(ChangeCase):
    def test_FR_AUT1_AC_17_each_life_cycle_transition_has_a_record_an_automation_names(self):
        self.assertEqual(LIFECYCLE, ("concept_validated", "plan_approved", "first_build_passed",
                                     "release_reached_test", "promoted", "rolled_back", "check_failed"))
        self.assertTrue(set(LIFECYCLE) <= set(COMMON_EVENTS))
        self.assertTrue(all(name in words.EVENT_WORDS for name in LIFECYCLE))
        said = {"concept_validated": [{"kind": "created_from_concept"}],
                "plan_approved": [{"kind": "plan_approved"}, {"kind": "go_ahead_given", "verdict": "go"}],
                "first_build_passed": [{"kind": "first_build_passed"}],
                "release_reached_test": [{"kind": "release_reached_test", "environment": "staging"}],
                "promoted": [{"kind": "promoted", "environment": "production"}],
                "rolled_back": [{"kind": "rolled_back"}],
                "check_failed": [{"kind": "probe_failed"}, {"kind": "release_failed"}]}
        for name, events in said.items():
            for ev in events:
                self.assertTrue(run.matches({"kind": "event", "types": [name]}, ev), (name, ev))
        self.assertFalse(run.matches({"kind": "event", "types": ["plan_approved"]},
                                     {"kind": "go_ahead_given", "verdict": "skip"}))   # Skip is no approval
        self.assertEqual(records_of("release_done"), (("release_done", None),))

    def test_FR_AUT1_AC_17_a_release_on_a_test_road_is_recorded_when_its_smoke_check_passes(self):
        logged = []
        stub = SimpleNamespace(rel={"steps": [], "revision": "a" * 40, "release": 1}, now=lambda: "now",
                               log=lambda kind, **payload: logged.append((kind, payload)))
        for step, outcome in (("deploy:staging", "passed"), ("smoke:staging", "failed"), ("smoke:staging", "passed"),
                              ("smoke:production", "passed")):
            _Delivery.record(stub, step, {"outcome": outcome})
        reached = [p for k, p in logged if k == "release_reached_test"]
        self.assertEqual(reached, [{"environment": "staging", "revision": "a" * 40}])

    def test_FR_AUT1_AC_17_the_first_build_that_passes_the_gate_is_recorded_once(self):
        from kernel import dispatch

        p = self.specced(mode="assume")
        compile_project(p)

        def merged(project, task_id, **_):
            dispatch._set_task(project, task_id, status="merged")
            return {"status": "merged"}

        with mock.patch.object(dispatch, "build_task", side_effect=merged):
            self.assertTrue(dispatch.build(p)["all_merged"])
            dispatch.build(p)
        rows = [r["event"]["payload"] for r in p.ledger().of_kind("first_build_passed")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tasks"], len(p.read("contract.json")["tasks"]))


class LifecycleTemplatesTest(AutoCase):
    def setUp(self):
        super().setUp()
        self.posted = []
        self.sub = relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["it"], **IT)
        self.tools = run.Tools(environ={"SLACK_URL": "https://hooks.example/slack"},
                               post=lambda url, body, headers: self.posted.append(body.decode("utf-8")) or 200)

    def template(self, tid: str, **fill) -> dict:
        t = next(t for t in words.TEMPLATES if t["id"] == tid)
        draft = copy.deepcopy(t["draft"])
        if draft.get("notify"):
            draft["notify"]["subscription"] = self.sub["id"]
        if draft["action"].get("subscription") == "":
            draft["action"]["subscription"] = self.sub["id"]
        if draft["scope"]["kind"] == "project":
            draft["scope"]["projects"] = [self.a.pid]
        draft.update(fill)
        return au.add(self.factory, draft, **IT)

    def ran(self, aid: str) -> list:
        return [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("automation_ran")
                if r["event"]["payload"]["id"] == aid]

    def test_FR_AUT1_AC_17_when_a_release_reaches_test_its_checks_run_and_a_channel_is_told(self):
        a = self.template("test_checks")
        self.a.log("release_reached_test", {"release": 1, "environment": "demo", "revision": "b" * 40})
        run.tick(self.factory, self.tools)
        row = self.ran(a["id"])[-1]
        self.assertEqual((row["event"], row["action"], row["project"], row["refs"]["environment"]),
                         ("release_reached_test", "probe", self.a.pid, "demo"))
        self.assertEqual(row["outcome"], "nothing")                       # nothing runs in demo in this test
        self.assertEqual(len(self.posted), 1)
        self.assertIn("Check a release on test", self.posted[0])

    def test_FR_AUT1_AC_17_when_promoted_the_probe_check_is_enabled_and_a_channel_is_told(self):
        a = self.template("production_probe")
        self.a.log("promoted", {"release": 1, "environment": "production", "revision": "c" * 40})
        run.tick(self.factory, self.tools)
        first = self.ran(a["id"])[-1]
        self.assertEqual((first["event"], first["action"], first["refs"]["environment"]),
                         ("promoted", "probe", "production"))
        enabled = self.a.ledger().of_kind("probe_check_enabled")
        self.assertEqual([r["event"]["payload"]["every"] for r in enabled], ["1h"])
        run.tick(self.factory, self.tools)
        self.assertEqual(len(self.ran(a["id"])), 1)                        # not due yet
        self.clock.advance(hours=1, minutes=1)
        run.tick(self.factory, self.tools)
        again = self.ran(a["id"])[-1]
        self.assertEqual((again["trigger"], again["project"], again["action"]), ("probe_check", self.a.pid, "probe"))
        self.assertEqual(len(self.a.ledger().of_kind("probe_check_enabled")), 1)   # enabled once
        self.assertEqual(len(self.posted), 2)

    def test_FR_AUT1_AC_17_when_a_concept_is_validated_the_product_owner_is_told(self):
        a = self.template("concept_validated")
        self.b.log("created_from_concept", {"concept": "C-0001", "signal": "S-001", "validated_by": "Aino"})
        run.tick(self.factory, self.tools)
        row = self.ran(a["id"])[-1]
        self.assertEqual((row["event"], row["action"], row["outcome"]), ("created_from_concept", "notify", "done"))
        self.assertEqual(len(self.posted), 1)
        self.assertIn(f"A concept was validated: {self.b.pid} is made", self.posted[0])

    def test_FR_AUT1_AC_17_when_the_gate_fails_twice_a_change_proposal_opens(self):
        a = self.template("gate_twice_change")
        self.a.log("gate", {"task": "T-001", "round": 1, "verdict": "failed"})
        run.tick(self.factory, self.tools)
        self.assertEqual(self.ran(a["id"]), [])                            # once is not twice
        self.assertEqual(Canon(self.a).cards(kind="change"), [])
        self.a.log("gate", {"task": "T-001", "round": 2, "verdict": "failed"})
        run.tick(self.factory, self.tools)
        row = self.ran(a["id"])[-1]
        self.assertEqual((row["event"], row["action"], row["outcome"]), ("gate", "change", "done"))
        cards = Canon(self.a).cards(kind="change")
        self.assertEqual(len(cards), 1)
        self.assertIn("The gate failed twice within a day", cards[0]["payload"]["text"])


if __name__ == "__main__":
    unittest.main()
