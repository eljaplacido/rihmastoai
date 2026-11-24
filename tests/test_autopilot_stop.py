"""An autopilot's sandbox holds to the end (FR-AP4; D-0017, D-0007).

A pass the autopilot started never leaves its sandbox, even when a person stops the run while the pass is
under way: it delivers nothing, writes through no connector and ends at its next safe point. The daily
Track digest leaves a held project out for receivers outside the sandbox. The track carries every reason
the health reads, so the one answer a project shows is never better than its health. Every receiver here
is a local fake; no model, no network.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, model, no_findings  # noqa: E402
from integration_fakes import Receiver  # noqa: E402

from kernel import autopilot, relay, roads, track  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import write_json  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
COCKPIT = "https://rihmasto.example.test"
DEMO_ROAD = {"kind": "local-process", "configured": True, "environments": ["demo"]}   # not marked sandbox


class Case(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(roads.stop_started)

    def intake(self, maturity="explore", mode="assume", title=None):
        p = self.new(mode=mode, maturity=maturity, **({"title": title} if title else {}))
        intake(p, IDEA, model=model(), requested_by="Aino")
        return p

    def run_kwargs(self, cell=generic_cell):
        return dict(lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=cell, verifier_runner=no_findings,
                    deliver_kwargs={})

    def start(self, p, **kw):
        args = dict(until="8h", kinds=["question", "approval", "escalation"], person="Dev", persona="developer")
        return autopilot.start(p, **(args | kw))

    def kinds(self, p, kind):
        return [r["event"]["payload"] for r in p.ledger().of_kind(kind)]


class StoppedPassTest(Case):
    def test_FR_AP4_AC_1_a_pass_a_person_stops_while_it_runs_delivers_nothing_and_ends_at_its_next_safe_point(self):
        write_json(self.factory.paved_roads_path, {"schema": roads.SCHEMA, "maturity": {"demo": "plain-demo"},
                                                   "roads": {"plain-demo": DEMO_ROAD}})
        p = self.intake(maturity="demo")
        self.start(p)
        seen = {"calls": 0, "write": None}

        def cell(lane, prompt):                       # a person presses Stop while the builder works
            seen["calls"] += 1
            if seen["calls"] == 1:
                autopilot.stop(p, person="Dev", persona="developer", reason="stop now")
                seen["write"] = autopilot.write_hold(p, "example", "create_issue")
            return generic_cell(lane, prompt)

        out = autopilot.run(p, model=model(), **self.run_kwargs(cell))
        self.assertFalse(autopilot.status(p)["holding"])                       # the person stopped it
        self.assertEqual(out["state"], "stopped", out)
        self.assertIn("was stopped by Dev", out["ended"])
        self.assertFalse(p.path("releases").exists())                         # it delivered nowhere
        self.assertIn("connectors read-only", seen["write"])                  # nor wrote through a connector
        tasks = json.loads(p.path("tasks.json").read_text(encoding="utf-8"))
        contract = json.loads(p.path("contract.json").read_text(encoding="utf-8"))
        if len(contract["tasks"]) > 1:                                         # it ended between tasks
            self.assertEqual(seen["calls"], 1, tasks)
        held = [h for h in self.kinds(p, "autopilot_held") if not h["what"].startswith("connector:")]
        self.assertEqual(len(held), 1, held)                                  # the stop, on record once
        self.assertIn(held[0]["what"], ("pass:stopped", "delivery:after_stop"))
        self.assertEqual(held[0]["run"], "AP-001")
        self.assertEqual(self.kinds(p, "autopilot_pass")[-1]["state"], "stopped")
        self.assertIsNone(autopilot.write_hold(p, "example", "create_issue"))  # outside the pass: a person's
        # a pass a person runs afterwards goes on and delivers, in their name
        for _ in range(4):
            if p.path("releases").exists():
                break
            advance(p, model=model(), **self.run_kwargs())
        self.assertTrue(p.path("releases").exists())
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_AP4_AC_1_a_stopped_run_holds_the_delivery_of_its_own_pass_even_into_a_sandbox(self):
        p = self.intake()                                                     # explore: the local preview
        self.start(p)
        autopilot.stop(p, person="Dev", persona="developer")
        self.assertIsNone(autopilot.delivery_hold(p))                         # a person's own pass delivers
        token = autopilot._PASS.set((p.pid, "AP-001"))                        # the autopilot's own pass
        try:
            held = autopilot.delivery_hold(p)
            self.assertEqual(held["state"], "stopped")
            self.assertIn("a person runs the project to deliver", held["why"])
            self.assertEqual(autopilot.pass_stopped(p)["state"], "stopped")
        finally:
            autopilot._PASS.reset(token)
        self.assertIsNone(autopilot.pass_stopped(p))


class DigestTest(Case):
    def test_FR_AP4_AC_2_the_daily_digest_leaves_a_held_project_out_for_receivers_outside_the_sandbox(self):
        held = self.intake(title="Secret borrowing pilot")
        self.intake(title="Visible project")
        self.start(held)
        rx = Receiver()
        self.addCleanup(rx.close)
        outside = relay.subscribe(self.factory, sink="slack", url_env="SLACK_OUT", personas=["it"], kinds=["trust"],
                                  person="Ilkka", persona="it")
        inside = relay.subscribe(self.factory, sink="slack", url_env="SLACK_IN", personas=["it"], kinds=["trust"],
                                 person="Ilkka", persona="it")
        relay.set_cockpit(self.factory, COCKPIT, person="Ilkka", persona="it")
        for sub in (outside, inside):
            relay.mark(self.factory, sub["id"], person="Ilkka", persona="it", digest="daily")
        relay.mark(self.factory, inside["id"], person="Ilkka", persona="it", sandbox=True)
        relay.run(self.factory, environ={"SLACK_OUT": rx.base + "/out", "SLACK_IN": rx.base + "/in"})
        out_text = json.dumps(json.loads(rx.at("/out")[0]["body"]))
        in_text = json.dumps(json.loads(rx.at("/in")[0]["body"]))
        self.assertIn("Visible project", out_text)
        self.assertNotIn("Secret borrowing pilot", out_text)                 # nor its reasons
        self.assertIn("1 more project is bound to an autopilot", out_text)
        self.assertIn("Secret borrowing pilot", in_text)                     # the sandbox receiver sees it
        log = {d["subscription"]: d for d in relay.deliveries(self.factory) if d["kind"] == "digest"}
        self.assertEqual((log[outside["id"]]["sandbox_held"], log[inside["id"]]["sandbox_held"]), ([held.pid], []))
        autopilot.stop(held, person="Dev", persona="developer")
        self.clock.advance(days=1)
        relay.run(self.factory, environ={"SLACK_OUT": rx.base + "/out", "SLACK_IN": rx.base + "/in"})
        self.assertIn("Secret borrowing pilot", json.dumps(json.loads(rx.at("/out")[-1]["body"])))


class OneAnswerTest(Case):
    def test_FR_AP4_AC_3_the_track_carries_the_healths_reasons_a_stale_approval_and_a_stopped_release(self):
        from kernel.status import health

        p = self.intake()
        make_spec(p, model=model())
        compile_project(p)
        self.assertEqual(track.track(p)["figures"]["health"]["value"], 0)
        write_json(p.path("releases") / "1.json", {"number": 1, "state": "failed"})
        self.assertEqual(health(p)["status"], "at_risk")
        t = track.track(p)
        self.assertIn(t["state"], ("at_risk", "off_track"))
        self.assertIn({"level": "at_risk", "figure": "health", "why": "release 1 stopped"}, t["reasons"])
        self.assertEqual(t["figures"]["health"]["release_failed"], 1)


if __name__ == "__main__":
    unittest.main()
