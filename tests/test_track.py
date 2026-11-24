"""Staying on track (FR-AP3, D-0017): a project against its approved plan, every figure with its basis,
human checkpoints a person looks at, and a daily digest through the relay. Deterministic: the same
records give the same answer. Every receiver here is a local fake.
"""

import contextlib
import io
import json
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, model, no_findings  # noqa: E402
from integration_fakes import Receiver  # noqa: E402

from kernel import autopilot, relay, roads, track  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dashboard import tracking  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from mcp.server import RihmaMCP  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
COCKPIT = "https://rihmasto.example.org"
URLS = re.compile(r"https?://[^\s\"'<>\\]+")


class TrackCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(roads.stop_started)

    def intake(self, maturity="explore", mode="mixed"):
        p = self.new(mode=mode, maturity=maturity)
        intake(p, IDEA, model=model(), requested_by="Aino")
        return p

    def compiled(self):
        p = self.intake(mode="assume")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def without_at(self, t):
        return json.loads(json.dumps({k: v for k, v in t.items() if k != "at"}))


class FiguresTest(TrackCase):
    def test_FR_AP3_AC_1_every_figure_has_its_basis_and_nothing_measured_is_never_zero_or_passed(self):
        p = self.intake()
        t = track.track(p)
        self.assertEqual(t["state"], "not_measured")
        self.assertIn("no approved plan", t["basis"])
        for key in ("baseline", "tasks", "gate_first_round", "scope", "time", "cost", "posture"):
            fig = t["figures"][key]
            self.assertFalse(fig["measured"], key)
            self.assertIsNone(fig["value"], key)                              # never 0, never passed
            self.assertTrue(fig["basis"], key)
        self.assertEqual(t["figures"]["blocking"]["value"], 1)                # the blocking question, with its age
        self.assertEqual(t["figures"]["blocking"]["cards"][0]["kind"], "question")
        self.assertEqual(t["figures"]["posture"]["basis"],
                         "no posture chosen: the project runs by its mode, maturity and autonomy cap")
        # with a posture, kernel/posture.py's hook says whether the run keeps it, and what drifted
        held = self.factory.new_project("Held", posture={"name": "balanced", "by": "Aino", "persona": "business_owner"})
        fig = track.track(held)["figures"]["posture"]
        self.assertEqual((fig["value"], fig["measured"], fig["posture"]), (True, True, "balanced"))
        held.update_meta(maturity="production")                      # set behind the posture's back
        fig = track.track(held)["figures"]["posture"]
        self.assertEqual((fig["value"], fig["drift"]), (False, ["maturity production is not one Balanced runs at "
                                                                 "(demo, pilot)"]))
        # compiled at a maturity with no plan approval: the first compiled contract is the baseline
        q = self.compiled()
        t = track.track(q)
        self.assertEqual(t["state"], "on_track")
        base = t["figures"]["baseline"]
        self.assertEqual(base["value"], q.meta["contract_revision"])
        self.assertIn("first compiled contract", base["basis"])
        n_tasks = len(q.read("contract.json")["tasks"])
        self.assertEqual((t["figures"]["tasks"]["done"], t["figures"]["tasks"]["left"]), (0, n_tasks))
        self.assertEqual(t["figures"]["scope"]["value"], 0)
        self.assertEqual(t["figures"]["cost"]["basis"], "no cost budget is set (rihmasto tracking set --budget)")

    def test_FR_AP3_AC_2_records_that_put_a_project_at_risk_or_off_track_are_named_with_their_figure(self):
        p = self.compiled()
        canon = Canon(p)
        esc = canon.card("escalation", "T-002 did not pass its gate after 3 round(s)", refs={"task": "T-002"},
                         blocking=True)
        t = track.track(p)
        self.assertEqual(t["state"], "at_risk")
        self.assertEqual(t["reasons"][0]["figure"], "blocking")
        self.assertIn(esc["id"], t["reasons"][0]["why"])
        self.clock.advance(days=4)
        self.assertIn("has waited 4.0 days", " ".join(r["why"] for r in track.track(p)["reasons"]))
        self.clock.advance(days=4)
        self.assertEqual(track.track(p)["state"], "off_track")                 # a week: off track
        canon.close(esc["id"], "resolved for the test", state="resolved")
        canon.add_assumption("Loans are returned within a week", "business", due_days=1)
        self.clock.advance(days=2)
        t = track.track(p)
        self.assertEqual(([r["figure"] for r in t["reasons"]], t["state"]), (["assumption_debt"], "at_risk"))
        for n, verdict in enumerate(("passed", "passed", "failed", "failed")):
            p.log("gate", {"task": f"T-00{n + 1}", "round": 0, "verdict": verdict})
        for n in range(3):
            p.log("change_applied", {"card": f"C-01{n}", "class": "change_request", "changed": ["R-1"]})
        figs = track.track(p)["figures"]
        self.assertEqual((figs["gate_first_round"]["trend"], figs["gate_first_round"]["value"]), ("falling", 0.5))
        self.assertEqual(figs["scope"]["value"], 3)
        track.set_tracking(p, person="Aino", persona="product_owner", due=self.clock.today().isoformat(), amount=4)
        p.log("gnomon_run", {"run": "r1", "cost": {"measured": True, "kind": "cloud", "amount": 5.0}})
        self.clock.advance(days=1)
        t = track.track(p)
        self.assertEqual(t["state"], "off_track")
        figures = {r["figure"] for r in t["reasons"]}
        self.assertTrue({"gate_first_round", "scope", "time", "cost"} <= figures, figures)
        self.assertEqual(t["figures"]["cost"]["share"], 1.25)
        # the posture module's hook decides the posture figure, when it exists
        fake = types.ModuleType("kernel.posture")
        fake.track_posture = lambda project: {"posture": "prototype", "keeps": False, "basis": "a gate was skipped"}
        with mock.patch.dict(sys.modules, {"kernel.posture": fake}):   # the real module is back afterwards
            posture = track.track(p)["figures"]["posture"]
        self.assertEqual((posture["value"], posture["posture"], posture["basis"]), (False, "prototype",
                                                                                     "a gate was skipped"))
        self.assertEqual(self.without_at(track.track(p)), self.without_at(track.track(p)))   # deterministic


class CheckpointTest(TrackCase):
    def test_FR_AP3_AC_3_a_checkpoint_is_due_at_its_stage_holds_the_run_and_lets_it_go_once_a_person_looked(self):
        p = self.new(maturity="explore", mode="assume")
        with self.assertRaises(DecisionRefused):
            track.set_tracking(p, person="Sam", persona="stakeholder", stages=[4])
        with self.assertRaises(ValueError):
            track.set_tracking(p, person="Aino", persona="product_owner", stages=[1])
        track.set_tracking(p, person="Aino", persona="product_owner", stages=[4], hold=True)
        with self.assertRaises(DecisionRefused):
            track.look(p, 4, person="Aino", persona="product_owner")            # not reached yet
        intake(p, IDEA, model=model(), requested_by="Aino")
        kw = dict(model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=generic_cell,
                  verifier_runner=no_findings, deliver_kwargs={})
        out = advance(p, **kw)
        self.assertEqual((out["state"], out["checkpoint"]), ("waiting", 4))     # the spec is written; it holds
        self.assertIn("a person looks before the run goes on", out["why"])
        self.assertFalse(p.path("contract.json").exists())
        t = track.track(p)
        self.assertEqual(t["checkpoints"]["due"], [4])
        self.assertIn("checkpoints", [r["figure"] for r in t["reasons"]])
        self.assertEqual(len(p.ledger().of_kind("checkpoint_reached")), 1)
        advance(p, **kw)
        self.assertEqual(len(p.ledger().of_kind("checkpoint_reached")), 1)    # on record once
        cps = track.look(p, 4, person="Aino", persona="product_owner", note="the spec reads right")
        self.assertEqual(cps["due"], [])
        self.assertEqual(cps["stages"][0]["looked"]["by"], "Aino")
        out = advance(p, **kw)
        self.assertNotEqual(out.get("checkpoint"), 4, out)
        self.assertTrue(p.path("contract.json").exists())                      # it went on after the look


class SurfacesTest(TrackCase):
    def test_FR_AP3_AC_4_the_command_line_dashboard_and_mcp_reads_show_the_same_track(self):
        p = self.compiled()
        autopilot.start(p, until="4h", kinds=["question"], person="Dev", persona="developer")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--home", str(self.factory.home), "track", p.pid]), 0)
        shown, here = json.loads(out.getvalue()), self.without_at(track.track(p))   # the command line's clock is real
        for key in ("project", "figures", "checkpoints"):
            self.assertEqual({k: v for k, v in shown[key].items() if k != "blocking"} if key == "figures" else shown[key],
                             {k: v for k, v in here[key].items() if k != "blocking"} if key == "figures" else here[key])
        self.assertEqual(shown["autopilot"]["id"], "AP-001")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--home", str(self.factory.home), "tracking", "set", p.pid, "--checkpoints", "5",
                                   "--person", "Aino", "--persona", "product_owner"]), 0)
        self.assertEqual(json.loads(out.getvalue())["checkpoints"], [5])
        board = tracking(self.factory)
        self.assertEqual(board["projects"][0]["project"], p.pid)
        self.assertEqual(board["projects"][0]["due"], [5])
        self.assertEqual((board["counts"]["at_risk"], board["autopilots"]), (1, 1))
        mcp = RihmaMCP(self.factory, person="Dev", persona="developer")
        one = mcp.tool_track(p.pid)
        self.assertEqual((one["state"], one["checkpoints"]["due"]), ("at_risk", [5]))
        self.assertEqual(mcp.tool_track()["projects"][0]["state"], "at_risk")
        self.assertEqual(mcp.tool_autopilot(p.pid)["run"]["id"], "AP-001")


class DigestTest(TrackCase):
    def test_FR_AP3_AC_5_a_subscription_that_asks_gets_one_daily_digest_with_one_link(self):
        p = self.compiled()
        self.intake()
        Canon(p).card("escalation", "T-001 did not pass: see evil.example/login", blocking=True)
        rx = Receiver()
        self.addCleanup(rx.close)
        hook = relay.subscribe(self.factory, sink="webhook", url=rx.base + "/events", secret_env="RELAY_SECRET",
                               types=["rihma.card.*"], person="Ilkka", persona="it")
        with self.assertRaises(ValueError):
            relay.mark(self.factory, hook["id"], person="Ilkka", persona="it", digest="daily")
        slack = relay.subscribe(self.factory, sink="slack", url_env="SLACK_IT", personas=["it"], kinds=["trust"],
                                person="Ilkka", persona="it")
        relay.set_cockpit(self.factory, COCKPIT, person="Ilkka", persona="it")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--home", str(self.factory.home), "tracking", "digest", slack["id"], "daily",
                                   "--person", "Ilkka", "--persona", "it"]), 0)
        env = {"SLACK_IT": rx.base + "/slack", "RELAY_SECRET": "whsec_" + "a" * 44}
        rx.status = 500
        out = relay.run(self.factory, environ=env)
        self.assertEqual(next(r for r in out["results"] if r["id"] == slack["id"])["digest"], "retry")
        rx.status = 200
        relay.run(self.factory, environ=env)
        relay.run(self.factory, environ=env)
        sent = [r for r in rx.at("/slack") if r["status"] == 200]
        self.assertEqual(len(sent), 1)                                         # once a day
        body = json.loads(sent[0]["body"])
        text = json.dumps(body)
        self.assertIn("Rihmasto daily track: 1 at risk, 1 not measured", body["text"])
        self.assertEqual(sorted(set(URLS.findall(text))), [COCKPIT + "/#/home"])   # one link, to Home
        self.assertIn("evil[.]example", text)                                  # titles are defanged
        self.assertNotIn("evil.example", text)
        log = [d for d in relay.deliveries(self.factory) if d["kind"] == "digest"]
        self.assertEqual([d["outcome"] for d in log], ["retry", "delivered"])
        self.clock.advance(days=1)
        relay.run(self.factory, environ=env)
        self.assertEqual(len([r for r in rx.at("/slack") if r["status"] == 200]), 2)


if __name__ == "__main__":
    unittest.main()
