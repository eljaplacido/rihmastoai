"""Delivery on the gcp-cloudrun road through IT's deploy gate, against a fake gcloud (FR-GCP1-AC-3 to AC-6).

The product is real (tests/test_deliver.py builds it); the cloud is not. A fake gcloud on PATH
(tests/gcp_fakes.py) answers the road's commands and records them, and the services' URLs it hands out are
a small server on 127.0.0.1 that answers /health with the version of the revision serving there, so the
road's health checks, smoke checks and canary probes are real HTTP. The product's holdouts are set aside:
that server is not the product. Nothing reaches Google Cloud.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from gcp_fakes import SCHEDULE, FakeGcloud, HealthServer, job_road, road  # noqa: E402
from test_deliver import MORE_ROUTES, DeliveryTestCase  # noqa: E402

from kernel import operate  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.deliver import deliver, delivery_plan, latest_release  # noqa: E402
from kernel.roads_gcp_ops import rollback  # noqa: E402
from kernel.store import write_json  # noqa: E402


class GcpDeliveryCase(DeliveryTestCase):
    maturity = "production"

    def entry(self) -> dict:
        return road()

    def setUp(self):
        # the fake first: its PATH outlives every cleanup that stops a slot
        self.fake_dir = Path(tempfile.mkdtemp(prefix="gf-gcloud-"))
        self.addCleanup(roadmod.rmtree, self.fake_dir)
        self.fake = FakeGcloud(self.fake_dir)
        patcher = mock.patch.dict(os.environ, self.fake.path_env())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.health_server = HealthServer(self.fake)
        self.addCleanup(self.health_server.stop)
        super().setUp()
        self.roads = {"schema": roadmod.SCHEMA, "roads": {"gcp": self.entry()},
                      "maturity": {"pilot": "gcp", "production": "gcp"}}
        write_json(self.factory.paved_roads_path, self.roads)
        roadmod.rmtree(self.project.holdouts_dir)       # the URLs answer /health only: no product behind them
        plan = self.project.read("checkplan.json")
        plan["checks"] = [c for c in plan["checks"] if c["kind"] not in ("holdout", "probe")]
        self.project.write("checkplan.json", plan)

    def in_project(self, gcp_project: str) -> list:
        return [c for c in self.fake.calls() if gcp_project in c]

    def to_gate(self) -> dict:
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        validation = self.canon.get_card(out["waiting_on"])
        self.assertEqual(validation["kind"], "validation")
        self.assertEqual(self.in_project("example-prod-123"), [])        # nothing in production yet
        self.decide(validation["id"], "accept", "business_owner")
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        gate = self.canon.get_card(out["waiting_on"])
        self.assertEqual((gate["kind"], gate["deciders"]), ("deploy_gate", ["it"]))
        self.assertEqual(self.in_project("example-prod-123"), [])
        return gate


class ServiceDeliveryTest(GcpDeliveryCase):
    def test_FR_GCP1_AC_3_a_service_goes_to_the_test_project_first_then_through_the_gate_to_production(self):
        rev = self.main()
        gate = self.to_gate()
        calls = [c for c in self.fake.calls() if c[:2] != ["auth", "list"]]
        self.assertEqual(calls[0][:2], ["builds", "submit"])
        self.assertIn("example-build-123", calls[0])
        staging = self.in_project("example-test-123")
        self.assertEqual([c[:3] for c in staging], [["run", "services", "replace"], ["run", "services", "describe"]])
        self.assertEqual((gate["payload"]["kind"], gate["payload"]["package_problems"]), ("gcp-cloudrun", []))
        self.assertEqual(gate["payload"]["rules"]["egress"], "none: all traffic through IT's VPC")
        self.decide(gate["id"], "approve", "it", person="Jaana")
        self.fake.clear()
        out = deliver(self.project)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual([s["step"] for s in out["steps"]], delivery_plan("production"))
        prod = [c[:4] for c in self.in_project("example-prod-123")]
        self.assertEqual(prod, [["run", "services", "replace", str(self.project.dir / "releases/1/cloudrun-service-"
                                                                    "production-candidate.yaml")],
                                ["run", "services", "describe", prod[1][3]],
                                ["run", "services", "update-traffic", prod[1][3]],
                                ["run", "services", "replace", str(self.project.dir / "releases/1/cloudrun-service-"
                                                                    "production-current.yaml")],
                                ["run", "services", "describe", prod[1][3]]])
        self.assertEqual(self.step(out, "shadow:production")["outcome"], "not applicable")  # nothing ran there yet
        self.assertEqual(self.step(out, "canary:production")["native"]["decision"], "promote")
        self.assertEqual(self.health("production")["version"], rev[:12])
        svc = self.fake.state()["services"][prod[1][3]]
        self.assertEqual(svc["traffic"], [{"revisionName": f"{prod[1][3]}-r1-{rev[:7]}", "percent": 100}])
        self.assertEqual(self.project.meta["stage"], 7)
        art = latest_release(self.project)["artifacts"]["gcp"]
        self.assertTrue(art["digest"].startswith("sha256:") and art["ref"].endswith(rev[:12]), art)

    def test_FR_GCP1_AC_4_a_candidate_revision_takes_no_traffic_promotion_moves_it_and_rollback_moves_it_back(self):
        first = self.main()
        self.assertEqual(self.ship()["state"], "done")
        second = self.commit_routes(MORE_ROUTES, "A count route")
        out = self.ship()
        self.assertEqual(out["state"], "done")
        self.assertEqual(self.step(out, "shadow:production")["outcome"], "not measured")  # Cloud Run's traffic is not read
        cand =roadmod.from_yaml((self.project.dir / "releases/2/cloudrun-service-production-candidate.yaml")
                                 .read_text(encoding="utf-8"))
        name = cand["metadata"]["name"]
        old, new = f"{name}-r1-{first[:7]}", f"{name}-r2-{second[:7]}"
        self.assertEqual(cand["spec"]["traffic"], [{"revisionName": old, "percent": 100},
                                                   {"revisionName": new, "percent": 0, "tag": "candidate"}])
        self.assertEqual(self.health("production")["version"], second[:12])
        with self.assertRaises(DecisionRefused):
            rollback(self.project, "production", person="Aino", persona="business_owner", reason="slow")
        self.fake.clear()
        record = rollback(self.project, "production", person="Jaana", persona="operations", reason="slower answers")
        self.assertEqual(self.fake.calls(), [["run", "services", "update-traffic", name, "--to-revisions", f"{old}=100",
                                              "--project", "example-prod-123", "--region", "europe-north1",
                                              "--impersonate-service-account=deployer@example-ops-123.iam."
                                              "gserviceaccount.com"]])
        self.assertEqual((record["from"]["release"], record["to"]["release"]), (2, 1))
        self.assertEqual(self.health("production")["version"], first[:12])
        self.assertEqual(roadmod.slot_state(self.project, "production")["release"], 1)
        rec = self.project.ledger().of_kind("rolled_back")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"], rec["how"]), ("Jaana", "operations", "the previous revision's traffic"))
        rollback(self.project, "production", person="Jaana", persona="it", reason="forward again")
        self.assertEqual(self.health("production")["version"], second[:12])


class JobDeliveryTest(GcpDeliveryCase):
    def entry(self) -> dict:
        return job_road()

    def test_FR_GCP1_AC_3_a_scheduled_job_runs_once_in_the_test_project_then_gets_its_image_and_schedule_in_production(self):
        gate = self.to_gate()
        staging = self.in_project("example-test-123")
        self.assertEqual([c[:3] for c in staging], [["run", "jobs", "replace"], ["run", "jobs", "execute"]])
        validation = self.canon.cards(state=None, kind="validation")[0]      # people follow a job in the console
        self.assertTrue(validation["payload"]["url"].startswith(
            "https://console.cloud.google.com/run/jobs/details/europe-north1/"), validation["payload"]["url"])
        self.assertTrue(validation["payload"]["url"].endswith("/executions?project=example-test-123"))
        self.assertFalse([c for c in self.fake.calls() if c[0] == "scheduler"])   # no schedule in the test project
        rel = latest_release(self.project)
        smoke = next(s for s in rel["steps"] if s["step"] == "smoke:staging")
        self.assertEqual((smoke["outcome"], smoke["native"]["execution"]["state"]), ("passed", "succeeded"))
        self.assertEqual(next(s for s in rel["steps"] if s["step"] == "holdouts:staging")["outcome"], "not applicable")
        self.decide(gate["id"], "approve", "it", person="Jaana")
        out = deliver(self.project)
        self.assertEqual(out["state"], "done", out)
        for step in ("deploy_candidate:production", "shadow:production", "canary:production"):
            self.assertEqual(self.step(out, step)["outcome"], "not applicable", step)
        promoted = self.step(out, "promote:production")["native"]
        self.assertEqual((promoted["schedule"]["cron"], promoted["schedule"]["updated"]), (SCHEDULE["cron"], False))
        state = self.fake.state()
        job = roadmod.slot_state(self.project, "production")["job"]
        sched = state["scheduler"][f"{job}-schedule"]
        self.assertEqual((sched["schedule"], sched["time-zone"], sched["max-retry-attempts"]),
                         ("0 6 * * 1-5", "Europe/Helsinki", "2"))
        self.assertTrue(sched["uri"].endswith(f"/namespaces/example-prod-123/jobs/{job}:run"))
        self.assertEqual(state["jobs"][job]["image"], roadmod.slot_state(self.project, "production")["image"])
        self.assertEqual(self.project.meta["stage"], 7)

    def test_FR_GCP1_AC_3_a_job_whose_test_execution_fails_stops_the_release_before_the_gate(self):
        self.fake.update(execute_outcome="failed")
        out = deliver(self.project)
        self.assertEqual((out["state"], out["failed_step"]), ("failed", "smoke:staging"))
        self.assertIn("failed: Task failed with exit code 1", out["reason"])
        self.assertEqual(self.canon.cards(kind="deploy_gate"), [])

    def test_FR_GCP1_AC_5_the_jobs_executions_feed_the_probe_and_a_failed_one_opens_an_incident(self):
        self.ship()
        job = roadmod.slot_state(self.project, "production")["job"]
        tick = operate.tick(self.project)
        self.assertEqual((tick["probes"][0]["verdict"], tick["incidents"]), ("not measured", []))
        self.fake.add_execution(job, ok=False, n=1)
        tick = operate.tick(self.project)
        probe = tick["probes"][0]
        self.assertEqual((probe["verdict"], probe["failed"]), ("failed", 1))
        self.assertIn(f"{job}-s1 failed", probe["health"]["reason"])
        incident = self.canon.get_card(probe["incident"])
        self.assertEqual(incident["kind"], "incident")
        self.assertIn("Task failed with exit code 1", incident["body"])
        self.assertEqual(self.project.ledger().of_kind("probe_failed")[-1]["event"]["payload"]["card"], incident["id"])
        self.fake.add_execution(job, ok=True, n=2)
        self.assertEqual(operate.tick(self.project)["probes"][0]["verdict"], "passed")
        last = [json.loads(x) for x in self.project.path("ops", "probes.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([p["verdict"] for p in last], ["not measured", "failed", "passed"])
        self.assertTrue(all("executions" in p and p["base_url"] is None for p in last))

    def test_FR_GCP1_AC_4_a_job_keeps_its_previous_image_and_rollback_gives_it_back(self):
        self.ship()
        image1 = roadmod.slot_state(self.project, "production")["image"]
        self.commit_routes(MORE_ROUTES, "A count route")
        out = self.ship()
        self.assertEqual(self.step(out, "promote:production")["native"]["schedule"]["updated"], True)
        image2 = roadmod.slot_state(self.project, "production")["image"]
        self.assertNotEqual(image1, image2)
        self.assertEqual(self.step(out, "promote:production")["native"]["previous"]["image"], image1)
        self.fake.clear()
        record = rollback(self.project, "production", person="Jaana", persona="it", reason="the transcripts are empty")
        job = roadmod.slot_state(self.project, "production")["job"]
        self.assertEqual(self.fake.calls()[0][:5], ["run", "jobs", "update", job, "--image"])
        self.assertEqual(self.fake.state()["jobs"][job]["image"], image1)
        self.assertEqual((record["to"]["release"], record["how"]), (1, "the job's previous image"))


class RefusalTest(GcpDeliveryCase):
    def test_FR_GCP1_AC_6_a_road_card_says_gcloud_is_missing_or_not_signed_in_and_nothing_runs(self):
        with mock.patch.dict(os.environ, {"PATH": str(Path(shutil.which("git")).parent)}):   # git, and no gcloud
            out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual(card["kind"], "road")
        self.assertIn("the gcloud CLI is not on PATH on the deploying host", card["body"])
        self.assertEqual(self.fake.calls(), [])
        self.fake.update(account=None)
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        rel = latest_release(self.project)
        self.assertEqual(rel["roads"]["staging"]["missing"],
                         ["gcloud is not signed in on the deploying host (gcloud auth list shows no active account)"])
        self.assertTrue(all(c[:2] == ["auth", "list"] for c in self.fake.calls()))   # nothing built or deployed
        self.fake.update(account="deployer@example-ops-123.iam.gserviceaccount.com")
        self.decide(card["id"], "configured", "it", person="Jaana")
        out = deliver(self.project)
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "validation")


if __name__ == "__main__":
    unittest.main()
