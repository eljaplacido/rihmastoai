"""The gcp-cloudrun road: its configuration, its rendering and its refusals (FR-GCP1-AC-1, AC-2, AC-6).

Nothing here reaches Google Cloud. Where a gcloud is needed, it is the fake the tests write on PATH
(tests/gcp_fakes.py); the deliveries through the deploy gate are in tests/test_roads_gcp_deliver.py.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from gcp_fakes import SCHEDULE, FakeGcloud, job_road, road  # noqa: E402

from kernel import road_settings  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel import roads_gcp_config as gc  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.roads_gcp import GcpCloudRunRoad  # noqa: E402
from kernel.store import Factory, FixedClock, read_json, write_json  # noqa: E402

REV = "0123456789abcdef0123456789abcdef01234567"
ART = {"type": "image", "ref": f"europe-north1-docker.pkg.dev/example-build-123/rihmasto/gf-x:{REV[:12]}",
       "digest": "sha256:" + "ab" * 32}


class GcpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-gcp-"))
        self.addCleanup(roadmod.rmtree, self.tmp)
        self.factory = Factory(self.tmp / "home", clock=FixedClock())
        self.project = self.factory.new_project("Recording transcripts", mode="assume", maturity="production")
        # no gcloud at all unless a test puts the fake first: PATH holds only an empty folder
        empty = self.tmp / "no-tools"
        empty.mkdir()
        patcher = mock.patch.dict("os.environ", {"PATH": str(empty)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake(self, **kw) -> FakeGcloud:
        fake = FakeGcloud(self.tmp / "fake", **kw)
        patcher = mock.patch.dict("os.environ", fake.path_env())
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def package(self, cfg: dict, env: str = "staging", slot: str = "current") -> dict:
        r = GcpCloudRunRoad("gcp", cfg)
        return r.package(self.project, env=env, slot=slot, release=1, revision=REV, artifact=dict(ART))

    def cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()


class ConfigTest(GcpCase):
    def test_FR_GCP1_AC_1_a_whole_road_has_no_problem_and_each_gap_or_unsafe_value_is_named(self):
        self.assertEqual(gc.config_problems(road()), [])
        self.assertEqual(gc.config_problems(job_road()), [])
        cases = {
            "no Google Cloud project for production": road(projects={"staging": "example-test-123"}),
            "is not a Google Cloud project id": road(projects={"staging": "Bad_Project", "production": "example-prod-123"}),
            "is not a Cloud Run region": road(region="north"),
            "Artifact Registry repository": road(repository="docker.io/example"),
            "deployer must name one identity": road(deployer={}),
            "runtime_service_account": road(runtime_service_account="someone@example.org"),
            "schedule.cron": job_road(schedule=dict(SCHEDULE, cron="0 25 * * *")),
            "five fields": job_road(schedule=dict(SCHEDULE, cron="*/5 * * *")),
            "time zone name": job_road(schedule=dict(SCHEDULE, time_zone="Helsinki time")),
            "schedule.retries": job_road(schedule=dict(SCHEDULE, retries=9)),
            "Cloud Scheduler calls the job as": job_road(schedule=dict(SCHEDULE, service_account="")),
            "a schedule runs a job": road(schedule=dict(SCHEDULE)),
            "job.max_retries": job_road(job={"max_retries": 99}),
            "through IT's VPC": road(network={"ingress": "internal"}),
            "routes through a VPC": road(network={"egress": "all-traffic"}),
            "no egress rule": road(rules={"region": "europe-north1"}),
            "carries a value": road(secrets=[{"name": "MODEL_API_KEY", "ref": "sm:k", "value": "s3cr3t"}]),
            "Secret Manager, by name": road(secrets=[{"name": "MODEL_API_KEY", "ref": "env:MODEL_API_KEY"}]),
            "looks like a secret": road(env={"API_TOKEN": "x"}),
            "not a variable a road may set": road(env={"PORT": "9000"}),
        }
        for said, cfg in cases.items():
            problems = gc.config_problems(cfg)
            self.assertTrue(any(said in p for p in problems), (said, problems))

    def test_FR_GCP1_AC_1_it_configures_a_whole_road_signed_and_recorded_and_a_broken_one_writes_nothing(self):
        row = road_settings.configure(self.factory, "company-gcp", job_road(), person="Ilkka", persona="it",
                                      maturity={"pilot": "company-gcp", "production": "company-gcp"})
        self.assertEqual((row["name"], row["kind"], row["configured"]), ("company-gcp", "gcp-cloudrun", True))
        saved = read_json(self.factory.paved_roads_path)
        self.assertEqual(saved["roads"]["company-gcp"]["schedule"], SCHEDULE)
        self.assertEqual(saved["maturity"], {"pilot": "company-gcp", "production": "company-gcp"})
        rec = factory_project(self.factory).ledger().of_kind("road_configured")[-1]["event"]["payload"]
        self.assertEqual((rec["road"], rec["person"], rec["persona"], rec["workload"]), ("company-gcp", "Ilkka", "it", "job"))
        self.assertNotIn("model-api-key", json.dumps(rec))             # the entry by its hash, never its secrets' names
        before = self.factory.paved_roads_path.read_bytes()
        refused = [
            (lambda: road_settings.configure(self.factory, "x-gcp", road(deployer={}), person="Ilkka", persona="it"),
             "deployer"),
            (lambda: road_settings.configure(self.factory, "x-gcp", road(), person="Aino", persona="business_owner"),
             "IT sets them"),
            (lambda: road_settings.configure(self.factory, "x-gcp", road(), person="factory", persona="it"),
             "not a person"),
            (lambda: road_settings.configure(self.factory, "x-gcp", road(kind="docker"), person="Ilkka", persona="it"),
             "other kinds are edited"),
            (lambda: road_settings.configure(self.factory, "x-gcp", road(secrets=[{"name": "K", "ref": "sm:k",
                                                                                   "value": "v"}]),
                                             person="Ilkka", persona="it"), "carries a value"),
            (lambda: road_settings.configure(self.factory, "x-gcp", dict(road(), password="x"), person="Ilkka",
                                             persona="it"), "takes no password"),
        ]
        for fn, said in refused:
            with self.assertRaises(DecisionRefused) as caught:
                fn()
            self.assertIn(said, str(caught.exception))
        self.assertEqual(self.factory.paved_roads_path.read_bytes(), before)

    def test_FR_GCP1_AC_1_it_chooses_a_projects_road_workload_and_schedule_and_a_bad_schedule_is_refused(self):
        write_json(self.factory.paved_roads_path, {"schema": roadmod.SCHEMA, "roads": {"gcp": road()}})
        view = road_settings.choose(self.project, "gcp", person="Ilkka", persona="it", workload="job",
                                    schedule=dict(SCHEDULE))
        self.assertEqual(view["chosen"], "gcp")
        staging = next(e for e in view["environments"] if e["environment"] == "staging")
        self.assertEqual(staging["cloudrun"]["workload"], "job")
        self.assertEqual(self.project.meta["cloudrun"], {"workload": "job", "schedule": SCHEDULE})
        self.assertEqual(self.project.ledger().of_kind("road_chosen")[-1]["event"]["payload"]["person"], "Ilkka")
        with self.assertRaises(DecisionRefused) as caught:
            road_settings.choose(self.project, "gcp", person="Ilkka", persona="it", workload="job",
                                 schedule=dict(SCHEDULE, cron="every morning"))
        self.assertIn("schedule.cron", str(caught.exception))
        with self.assertRaises(DecisionRefused):
            road_settings.choose(self.project, "nowhere", person="Ilkka", persona="it")
        self.assertEqual(self.project.meta["cloudrun"]["schedule"]["cron"], SCHEDULE["cron"])   # unchanged


class RenderTest(GcpCase):
    def test_FR_GCP1_AC_2_a_service_renders_a_knative_service_and_the_exact_gcloud_commands_and_validates(self):
        pkg = self.package(road())
        self.assertEqual(roadmod.validate_package(pkg), [])
        r = pkg["rendered"]
        model = r["model"]
        self.assertEqual((model["apiVersion"], model["kind"]), ("serving.knative.dev/v1", "Service"))
        name = model["metadata"]["name"]
        self.assertTrue(name.startswith("gf-") and name.endswith("-st"), name)
        tpl = model["spec"]["template"]
        self.assertEqual(tpl["metadata"]["name"], f"{name}-r1-{REV[:7]}")
        self.assertEqual(tpl["metadata"]["annotations"]["autoscaling.knative.dev/maxScale"], "1")
        self.assertEqual(tpl["metadata"]["annotations"]["run.googleapis.com/vpc-access-egress"], "all-traffic")
        spec = tpl["spec"]
        self.assertEqual(spec["serviceAccountName"], "runtime@example-prod-123.iam.gserviceaccount.com")
        c = spec["containers"][0]
        self.assertEqual(c["image"], ART["ref"].rsplit(":", 1)[0] + "@" + ART["digest"])     # pinned by digest
        env = {e["name"]: e for e in c["env"]}
        self.assertNotIn("PORT", env)                                     # Cloud Run sets it
        self.assertEqual(env["APP_VERSION"]["value"], REV[:12])
        self.assertEqual(env["LOG_LEVEL"]["value"], "info")
        self.assertEqual(env["MODEL_API_KEY"], {"name": "MODEL_API_KEY", "valueFrom": {"secretKeyRef": {
            "name": "model-api-key", "key": "3"}}})
        self.assertEqual(model["spec"]["traffic"], [{"revisionName": tpl["metadata"]["name"], "percent": 100}])
        self.assertEqual(roadmod.from_yaml(r["yaml"]), model)
        imp = "--impersonate-service-account=deployer@example-ops-123.iam.gserviceaccount.com"
        where = ["--project", "example-test-123", "--region", "europe-north1", imp]
        self.assertEqual(r["commands"]["deploy"], ["gcloud", "run", "services", "replace", "<yaml>", *where, "--format=json"])
        self.assertEqual(r["commands"]["describe"], ["gcloud", "run", "services", "describe", name, *where, "--format=json"])
        self.assertEqual(r["commands"]["traffic_to"][:7], ["gcloud", "run", "services", "update-traffic", name,
                                                           "--to-revisions", "<revision>=100"])
        self.assertIsNone(r["scheduler"])
        self.assertNotIn("s3cr3t", json.dumps(pkg))
        prod = self.package(road(), env="production")
        self.assertIn("example-prod-123", prod["rendered"]["commands"]["deploy"])

    def test_FR_GCP1_AC_2_a_scheduled_job_renders_a_run_job_and_a_cloud_scheduler_job_in_production_only(self):
        folders = {"RECORDINGS_FOLDER": {"staging": "test-folder-1", "production": "prod-folder-1"}}
        staging, prod = self.package(job_road(env=folders)), self.package(job_road(env=folders), env="production")
        for pkg, folder in ((staging, "test-folder-1"), (prod, "prod-folder-1")):
            self.assertEqual(roadmod.validate_package(pkg), [], pkg["environment"])
            container = pkg["rendered"]["model"]["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]
            self.assertIn({"name": "RECORDINGS_FOLDER", "value": folder}, container["env"])   # each its own folder
        model = prod["rendered"]["model"]
        self.assertEqual((model["apiVersion"], model["kind"]), ("run.googleapis.com/v1", "Job"))
        task = model["spec"]["template"]["spec"]
        self.assertEqual((task["parallelism"], task["taskCount"]), (1, 1))
        inner = task["template"]["spec"]
        self.assertEqual((inner["maxRetries"], inner["timeoutSeconds"]), (1, "1800"))
        self.assertEqual((inner["containers"][0]["command"], inner["containers"][0]["args"]),
                         (["python3"], ["-m", "app.transcribe"]))
        self.assertIsNone(staging["rendered"]["scheduler"])                # the test environment runs it on demand
        s = prod["rendered"]["scheduler"]
        job = model["metadata"]["name"]
        self.assertEqual(s["httpTarget"]["uri"], "https://europe-north1-run.googleapis.com/apis/run.googleapis.com/v1/"
                                                 f"namespaces/example-prod-123/jobs/{job}:run")
        self.assertEqual((s["schedule"], s["timeZone"], s["retryConfig"]), ("0 6 * * 1-5", "Europe/Helsinki",
                                                                             {"retryCount": 2}))
        cmds = prod["rendered"]["commands"]
        self.assertEqual(cmds["scheduler_create"][:6], ["gcloud", "scheduler", "jobs", "create", "http", f"{job}-schedule"])
        for flag, value in (("--schedule", "0 6 * * 1-5"), ("--time-zone", "Europe/Helsinki"), ("--max-retry-attempts", "2"),
                            ("--oauth-service-account-email", SCHEDULE["service_account"]), ("--location", "europe-north1")):
            self.assertEqual(cmds["scheduler_create"][cmds["scheduler_create"].index(flag) + 1], value, flag)
        self.assertEqual(cmds["execute"][:6], ["gcloud", "run", "jobs", "execute", job, "--wait"])
        self.assertIn("--format=json", cmds["executions"])
        self.assertEqual(roadmod.from_yaml(prod["rendered"]["yaml"]), model)

    def test_FR_GCP1_AC_2_a_tampered_stale_or_unsafe_rendering_is_refused_before_anything_runs(self):
        pkg = self.package(job_road(), env="production")
        pkg["rendered"]["yaml"] = pkg["rendered"]["yaml"].replace("python3", "bash")
        self.assertTrue(any("read back" in p for p in roadmod.validate_package(pkg)))
        pkg = self.package(road())
        pkg["settings"]["NEW_SETTING"] = "added after rendering"
        self.assertTrue(any("render it again" in p for p in roadmod.validate_package(pkg)))
        pkg = self.package(road())
        pkg["secrets"].append({"name": "DB_PASSWORD", "ref": "env:DB_PASSWORD"})
        GcpCloudRunRoad("gcp", road()).render(self.project, pkg)
        self.assertTrue(any("Secret Manager by name" in p for p in roadmod.validate_package(pkg)))
        pkg = self.package(road())
        pkg["rendered"]["model"]["spec"]["template"]["spec"]["containers"][0]["env"][0]["value"] = "x"
        pkg["rendered"]["yaml"] = roadmod.to_yaml(pkg["rendered"]["model"])
        self.assertTrue(roadmod.validate_package(pkg))
        bad_region = self.package(road(region="us-central1", rules=dict(road()["rules"], region="us-central1")))
        self.assertTrue(any("not among the road's regions" in p for p in roadmod.validate_package(bad_region)))
        no_digest = GcpCloudRunRoad("gcp", road()).package(self.project, env="staging", slot="current", release=1,
                                                             revision=REV, artifact={"type": "image", "ref": "elsewhere/x:latest"})
        problems = roadmod.validate_package(no_digest)
        self.assertTrue(any("tagged with the revision" in p for p in problems), problems)
        self.assertTrue(any("road's repository" in p for p in problems), problems)


class MissingTest(GcpCase):
    def test_FR_GCP1_AC_6_without_gcloud_or_a_whole_configuration_the_road_says_exactly_what_is_missing(self):
        paved = roadmod.PavedRoads({"schema": roadmod.SCHEMA, "roads": {"gcp": road(), "half": road(configured=False,
                                                                                                   deployer={})}})
        self.assertEqual(paved.missing("gcp", "staging"), ["the gcloud CLI is not on PATH on the deploying host"])
        half = paved.missing("half", "staging")
        self.assertIn("road 'half' is not marked \"configured\": true by IT", half)
        self.assertTrue(any("deployer must name one identity" in m for m in half), half)
        self.assertEqual(paved.missing("gcp", "demo"), ["road 'gcp' does not serve the demo environment",
                                                        "the gcloud CLI is not on PATH on the deploying host"])
        with self.assertRaises(roadmod.RoadError) as caught:
            paved.road("gcp").build(self.project, REV)
        self.assertIn("gcloud CLI is not on PATH", str(caught.exception))
        fake = self.fake(account=None)
        self.assertEqual(paved.missing("gcp", "staging"),
                         ["gcloud is not signed in on the deploying host (gcloud auth list shows no active account)"])
        fake.update(account="deployer@example-ops-123.iam.gserviceaccount.com")
        self.assertEqual(paved.missing("gcp", "staging"), [])
        self.assertTrue(all(c[:2] == ["auth", "list"] for c in fake.calls()))     # asking runs nothing else

    def test_FR_GCP1_AC_6_the_road_list_and_render_commands_name_what_is_missing_and_run_nothing(self):
        write_json(self.factory.paved_roads_path, {"schema": roadmod.SCHEMA, "roads": {"gcp": job_road()},
                                                   "maturity": {"production": "gcp", "pilot": "gcp"}})
        code, out, err = self.cli("road", "list")
        self.assertEqual((code, err), (0, ""))
        row = next(r for r in json.loads(out)["roads"] if r["name"] == "gcp")
        self.assertEqual((row["ready"], row["missing"]), (False, ["the gcloud CLI is not on PATH on the deploying host"]))
        self.assertEqual(row["cloudrun"]["schedule"], SCHEDULE)
        code, out, err = self.cli("road", "render", self.project.pid, "--env", "production")
        self.assertEqual((code, err), (0, ""))
        shown = json.loads(out)
        self.assertEqual((shown["kind"], shown["problems"]), ("gcp-cloudrun", []))
        self.assertIn("kind: \"Job\"", shown["yaml"])
        self.assertEqual(shown["commands"]["scheduler_create"][3], "create")
        self.assertEqual(shown["missing"], ["the gcloud CLI is not on PATH on the deploying host"])
        code, out, err = self.cli("road", "rollback", self.project.pid, "--reason", "r", "--person", "Ilkka",
                                  "--persona", "it")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("nothing runs in production on a Google Cloud road", err)
        code, out, err = self.cli("road", "configure", "gcp2", "--file", str(self.tmp / "missing.json"), "--person",
                                  "Ilkka", "--persona", "it")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
