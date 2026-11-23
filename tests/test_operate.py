"""Operation: shadow, canary and rollback, probes and incidents (FR-H7, FR-H4, FR-I2).

The products run as real local processes; "bad" and "different" candidates are real commits to
the product's repository. Every process is stopped in cleanup.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_deliver import BAD_ROUTES, LOCAL_ROADS, MORE_ROUTES, UPPER_ROUTES, DeliveryTestCase  # noqa: E402

from kernel import operate  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.deliver import latest_release  # noqa: E402
from kernel.store import write_json  # noqa: E402

TRAFFIC = [("POST", "/items", {"name": "drill"}), ("POST", "/items", {"name": ""}), ("GET", "/items", None)]


class OperateTestCase(DeliveryTestCase):
    maturity = "production"

    def deploy(self, env, slot, revision, release, roads=None):
        road = roadmod.PavedRoads.load(roads or LOCAL_ROADS).road("local")
        artifact = road.build(self.project, revision)
        return road.deploy(self.project, road.package(self.project, env=env, slot=slot, release=release,
                                                      revision=revision, artifact=artifact))

    def traffic(self):
        """Real users' requests to production; the product records them in its traffic log."""
        answers = [self.send("production", m, p, b)["status"] for m, p, b in TRAFFIC]
        self.assertEqual(answers, [201, 400, 200])

    def traffic_log(self) -> str:
        return self.project.path("envs", "production", "traffic.jsonl").read_text(encoding="utf-8")

    def crash(self, env):
        """The product process dies under the factory's feet; its slot still says it runs."""
        proc = roadmod._STARTED[roadmod.slot_state(self.project, env)["pid"]]
        proc.kill()
        proc.wait(5)


class ShadowTest(OperateTestCase):
    def test_FR_H7_AC_1_shadow_reports_every_differing_response(self):
        self.deploy("production", "current", self.main(), 1)
        self.traffic()
        log_before = self.traffic_log()
        self.assertEqual(len(log_before.splitlines()), 3)
        rev2 = self.commit_routes(UPPER_ROUTES, "Names come back upper-cased")
        self.deploy("production", "candidate", rev2, 2)
        report = operate.shadow(self.project, roads=LOCAL_ROADS)
        self.assertEqual((report["verdict"], report["against"], report["replayed"]), ("failed", "twin", 3))
        self.assertEqual(report["differing"], 2)
        self.assertEqual([(d["index"], d["method"], d["path"]) for d in report["differences"]],
                         [(0, "POST", "/items"), (2, "GET", "/items")])
        post, get = report["differences"]
        self.assertEqual(post["differences"], ["body $.name"])
        self.assertEqual((post["current"]["body"], post["candidate"]["body"]),
                         ({"id": "1", "name": "drill"}, {"id": "1", "name": "DRILL"}))
        self.assertEqual(get["differences"], ["body $[0].name"])
        self.assertEqual((get["current"]["status"], get["candidate"]["status"]), (200, 200))
        # The empty name answered 400 on both sides: it agrees, so it is not reported.
        self.assertEqual(report["entries"][1]["differences"], [])
        # The live production slot saw none of the replay: a fresh twin of release 1 answered instead.
        self.assertEqual(self.traffic_log(), log_before)
        self.assertEqual(self.send("production", "GET", "/items")["json"], [{"id": "1", "name": "drill"}])
        self.assertIsNone(roadmod.slot_state(self.project, "production", "twin"))
        self.assertEqual(json.loads(self.project.path("ops", "shadow", "2.json").read_text(encoding="utf-8"))
                         ["differing"], 2)

    def test_FR_H7_AC_1_shadow_reports_nothing_when_candidate_and_current_agree(self):
        self.deploy("production", "current", self.main(), 1)
        self.traffic()
        self.deploy("production", "candidate", self.commit_routes(MORE_ROUTES, "A count route"), 2)
        report = operate.shadow(self.project, roads=LOCAL_ROADS)
        self.assertEqual((report["verdict"], report["replayed"], report["differing"]), ("passed", 3, 0))
        self.assertEqual(report["differences"], [])
        # Volatile keys (id, created, updated, at, version by default) are not differences.
        self.assertEqual(operate.differences({"id": "1", "at": 1, "name": "a"}, {"id": "9", "at": 2, "name": "a"}), [])
        self.assertEqual(operate.differences({"id": "1", "name": "a"}, {"id": "1", "name": "b"}), ["$.name"])
        self.assertEqual(operate.differences({"n": 1}, {"n": True}), ["$.n"])

    def test_FR_H7_AC_1_a_live_shadow_sends_no_write_to_a_current_that_is_not_shadow_safe(self):
        roads = json.loads(json.dumps(LOCAL_ROADS))
        roads["roads"]["local"]["shadow_target"] = "live"
        write_json(self.factory.paved_roads_path, roads)
        self.deploy("production", "current", self.main(), 1, roads)
        self.traffic()
        self.deploy("production", "candidate", self.commit_routes(UPPER_ROUTES, "Upper-case names"), 2, roads)
        report = operate.shadow(self.project, roads=roads)
        self.assertEqual((report["against"], report["safe"], report["sent_to_current"]), ("live", False, 1))
        writes = [e for e in report["entries"] if e["method"] == "POST"]
        self.assertEqual([e["current"] for e in writes], [None, None])
        self.assertEqual([e["recorded_status"] for e in writes], [201, 400])
        self.assertEqual([(d["method"], d["differences"]) for d in report["differences"]], [("GET", ["body $[0].name"])])
        self.assertEqual(self.send("production", "GET", "/items")["json"], [{"id": "1", "name": "drill"}])
        # A live current records the reads replayed to it, so the next shadow replays them too.
        self.assertEqual(len(self.traffic_log().splitlines()), 5)
        roads["roads"]["local"]["shadow_safe"] = ["production"]      # IT says production may take replays
        report = operate.shadow(self.project, roads=roads)
        self.assertTrue(report["safe"])
        self.assertEqual(report["sent_to_current"], report["replayed"])


class CanaryTest(OperateTestCase):
    def test_FR_H4_AC_1_a_canary_with_more_errors_is_rolled_back_with_no_person_involved(self):
        self.assertEqual(self.ship()["state"], "done")
        rev1 = self.main()
        self.traffic()
        self.commit_routes(BAD_ROUTES, "Empty names crash")
        out = self.ship()
        self.assertEqual((out["state"], out["release"], out["failed_step"]), ("failed", 2, "canary:production"))
        canary = self.step(out, "canary:production")["native"]
        self.assertEqual(canary["decision"], "abort")
        self.assertEqual((canary["candidate"]["replay_errors"], canary["current"]["replay_errors"]), (1, 0))
        self.assertGreater(canary["candidate"]["error_rate"], canary["current"]["error_rate"] + canary["tolerance"])
        self.assertGreaterEqual(canary["candidate"]["sample"], canary["min_sample"])
        shadow = self.step(out, "shadow:production")
        self.assertEqual(shadow["outcome"], "differs")
        self.assertEqual([(d["method"], d["current"], d["candidate"]) for d in shadow["native"]["differences"]],
                         [("POST", 400, 500)])
        # Rolled back: release 1 keeps serving production, the candidate is gone.
        self.assertEqual(self.health("production")["version"], rev1[:12])
        self.assertEqual(roadmod.slot_state(self.project, "production")["release"], 1)
        self.assertIsNone(roadmod.slot_state(self.project, "production", "candidate"))
        rollback = latest_release(self.project)["rollback"]
        self.assertEqual(rollback["kept"], {"release": 1, "revision": rev1})
        self.assertIn("no person involved", rollback["by"])
        self.assertTrue(rollback["current_health"]["ok"])
        self.assertEqual(len(self.project.path("ops", "rollbacks.jsonl").read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual([r["event"]["payload"]["release"] for r in self.project.ledger().of_kind("rolled_back")], [2])
        incident = self.canon.get_card(out["incident"])
        self.assertEqual((incident["kind"], incident["state"]), ("incident", "open"))
        self.assertEqual(incident["refs"], {"release": 2, "environment": "production"})
        # People decided only validations and deploy gates; the abort and rollback were the factory's.
        self.assertEqual([d["kind"] for d in self.canon.decisions()], ["validation", "deploy_gate"] * 2)

    def test_FR_H4_AC_1_a_healthy_candidate_is_promoted(self):
        self.ship()
        rev1 = self.main()
        self.traffic()
        rev2 = self.commit_routes(MORE_ROUTES, "A count route")
        out = self.ship()
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(self.step(out, "shadow:production")["outcome"], "passed")
        self.assertEqual(self.step(out, "canary:production")["native"]["decision"], "promote")
        self.assertEqual(self.health("production")["version"], rev2[:12])
        self.assertEqual(roadmod.slot_state(self.project, "production")["release"], 2)
        self.assertIsNone(roadmod.slot_state(self.project, "production", "candidate"))
        # The promoted release serves production's data, recorded under release 1.
        self.assertEqual(self.send("production", "GET", "/items")["json"], [{"id": "1", "name": "drill"}])
        self.assertEqual(self.send("production", "GET", "/count")["json"], {"count": 1})
        self.assertEqual(latest_release(self.project)["promoted"]["previous"], {"release": 1, "revision": rev1})
        self.assertEqual(self.canon.cards(kind="incident"), [])


class IncidentTest(OperateTestCase):
    def test_FR_I2_AC_1_a_failing_probe_opens_one_incident_per_release_and_environment(self):
        self.deploy("production", "current", self.main(), 1)
        first = operate.tick(self.project)
        self.assertTrue(first["probes"][0]["ok"], first)
        self.assertEqual(first["probes"][0]["checks"], 2)                # /health and the R-4-AC-2 probe
        self.assertEqual(first["incidents"], [])
        self.crash("production")
        for _ in range(3):
            self.assertFalse(operate.tick(self.project)["probes"][0]["ok"])
        cards = self.canon.cards(kind="incident")
        self.assertEqual(len(cards), 1)                                   # one card, not one per tick
        self.assertEqual(cards[0]["refs"], {"release": 1, "environment": "production"})
        incidents = json.loads(self.project.path("ops", "incidents.json").read_text(encoding="utf-8"))
        self.assertEqual(incidents["1:production"]["occurrences"], 3)
        self.assertEqual(len(self.project.path("ops", "probes.jsonl").read_text(encoding="utf-8").splitlines()), 4)
        self.assertTrue(self.project.path("ops", "tick.json").exists())
        # Another release in production that fails gets its own card.
        self.deploy("production", "current", self.commit_routes(MORE_ROUTES, "A count route"), 2)
        self.assertTrue(operate.tick(self.project)["probes"][0]["ok"])
        self.crash("production")
        operate.tick(self.project)
        operate.tick(self.project)
        cards = self.canon.cards(kind="incident")
        self.assertEqual([c["refs"]["release"] for c in cards], [1, 2])
        self.assertEqual(len(self.project.ledger().of_kind("probe_failed")), 2)

    def test_FR_I2_AC_1_a_probe_scenario_over_its_latency_limit_is_a_failing_probe(self):
        write_json(self.project.holdouts_dir / "R-4-AC-2.json", {"criterion": "R-4-AC-2", "kind": "probe", "steps": [
            {"method": "GET", "path": "/health", "expect_status": 200, "max_ms": 0.0001}]})
        self.deploy("production", "current", self.main(), 1)
        res = operate.probe(self.project, "production")
        self.assertTrue(res["health"]["ok"])
        self.assertEqual((res["ok"], res["failed"]), (False, 1))
        self.assertIn("ms limit", res["scenarios"][0]["reason"])
        operate.tick(self.project)
        operate.tick(self.project)
        self.assertEqual(len(self.canon.cards(kind="incident")), 1)


if __name__ == "__main__":
    unittest.main()
