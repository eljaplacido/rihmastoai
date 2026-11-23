"""Delivery on the paved road (FR-A8, FR-A8-AC-2, FR-Q4, FR-H3, FR-Q5).

Every product here is real: intake, spec, compile and a builder cell (the fakes) make it, and
delivery runs it as local processes on loopback ports. The processes are stopped in cleanup,
also when a test fails.
"""

import atexit
import json
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import GOOD_ROUTES, good_cell, model, no_findings  # noqa: E402

from kernel import roads as roadmod  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.compile import author_holdouts, compile_project  # noqa: E402
from kernel.deliver import deliver, delivery_plan, latest_release, releases  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import GIT_ID, Lanes, _git  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import MATURITIES, Factory, FixedClock, write_json  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
LOCAL_ROADS = {
    "schema": roadmod.SCHEMA,
    "roads": {"local": {"kind": "local-process", "configured": True, "environments": list(roadmod.ENVIRONMENTS),
                        "rules": {"tls": "none: loopback only", "egress": "none"}}},
    "maturity": {m: "local" for m in MATURITIES},
}
# A product revision whose POST /items crashes (500) on an empty name instead of answering 400.
BAD_ROUTES = GOOD_ROUTES.replace('        return 400, {"error": "name is required"}',
                                 '        raise ValueError("name is required")')
# A product revision whose answers differ: names come back upper-cased.
UPPER_ROUTES = GOOD_ROUTES.replace('"name": name}', '"name": name.upper()}')
# A product revision that behaves the same, plus a route nobody's traffic uses.
MORE_ROUTES = GOOD_ROUTES + '''

@route("GET", "/count")
def count_items(req):
    return 200, {"count": len(load_data("items", []))}
'''
assert BAD_ROUTES != GOOD_ROUTES and UPPER_ROUTES != GOOD_ROUTES

_TEMPLATES: dict = {}
_ROOT: list = []


def built_product(maturity: str):
    """A real product per maturity, built once per test run and copied into each test."""
    if maturity not in _TEMPLATES:
        if not _ROOT:
            _ROOT.append(Path(tempfile.mkdtemp(prefix="gf-deliver-templates-")))
            atexit.register(roadmod.rmtree, _ROOT[0])
        root = _ROOT[0] / maturity
        factory = Factory(root / "home", clock=FixedClock())
        p = factory.new_project("Equipment loans", mode="assume", maturity=maturity)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        out = build_task(p, "T-001", lanes=Lanes(root / "lanes", size=1), cell_runner=good_cell,
                         verifier_runner=no_findings)
        if out["status"] != "merged":
            raise AssertionError(f"the fixture product did not build: {out}")
        author_holdouts(p, model=model())
        _TEMPLATES[maturity] = (root / "home", p.pid)
    return _TEMPLATES[maturity]


class FakeDocker:
    """Stands in for the docker CLI: records each command and answers like docker would."""

    def __init__(self, port=None):
        self.calls, self.port = [], port

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if argv[1:3] == ["image", "inspect"]:
            return 0, "sha256:" + "ab" * 32 + "\n", ""
        if argv[1] == "port":
            return 0, f"127.0.0.1:{self.port}\n", ""
        return 0, "", ""


class DeliveryTestCase(unittest.TestCase):
    """A copy of a built product per test, local roads, and every process stopped afterwards."""

    maturity = "production"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-deliver-"))
        self.addCleanup(roadmod.rmtree, self.tmp)
        home, pid = built_product(self.maturity)
        shutil.copytree(home, self.tmp / "home")
        self.clock = FixedClock()
        self.factory = Factory(self.tmp / "home", clock=self.clock)
        self.project = self.factory.project(pid)
        self.canon = Canon(self.project)
        write_json(self.factory.paved_roads_path, LOCAL_ROADS)
        self.addCleanup(roadmod.stop_started)                 # runs second: anything left over
        self.addCleanup(roadmod.stop_all, self.project, LOCAL_ROADS)  # runs first: every slot

    def main(self) -> str:
        return _git(self.project.path("repo.git"), "rev-parse", "main")

    def commit_routes(self, text: str, message: str) -> str:
        work = Path(tempfile.mkdtemp(prefix="edit-", dir=self.tmp))
        _git(work, "clone", "-q", str(self.project.path("repo.git")), "w")
        (work / "w" / "app" / "routes.py").write_text(text, encoding="utf-8", newline="\n")
        _git(work / "w", *GIT_ID, "commit", "-q", "-am", message)
        _git(work / "w", "push", "-q", "origin", "main")
        return _git(work / "w", "rev-parse", "HEAD")

    def decide(self, card_id, verdict, persona, person="Aino", reason=""):
        return self.canon.decide(card_id, verdict, person=person, persona=persona, reason=reason)

    def ship(self, **kwargs) -> dict:
        """Deliver, deciding each card the way its owner would approve it."""
        approve = {"validation": ("accept", "business_owner"), "deploy_gate": ("approve", "it"),
                   "approval": ("approve", "business_owner")}
        for _ in range(6):
            out = deliver(self.project, **kwargs)
            if out["state"] != "waiting":
                return out
            card = self.canon.get_card(out["waiting_on"])
            verdict, persona = approve[card["kind"]]
            self.decide(card["id"], verdict, persona, person="Jaana" if persona == "it" else "Aino")
        raise AssertionError("delivery did not finish")

    def health(self, env: str, slot: str = "current") -> dict:
        state = roadmod.slot_state(self.project, env, slot)
        return roadmod.http_request("GET", state["base_url"] + "/health")["json"]

    def send(self, env: str, method: str, path: str, body=None) -> dict:
        state = roadmod.slot_state(self.project, env, "current")
        return roadmod.http_request(method, state["base_url"] + path, body)

    def step(self, out: dict, name: str) -> dict:
        return next(s for s in out["steps"] if s["step"] == name)


class PlanTest(unittest.TestCase):
    def test_FR_A8_AC_1_explore_plan_is_build_preview_smoke(self):
        self.assertEqual(delivery_plan("explore"), ["build_image", "deploy:preview", "smoke:preview"])

    def test_FR_A8_AC_1_demo_plan_adds_holdouts_on_demo_and_the_owner_acceptance(self):
        self.assertEqual(delivery_plan("demo"), ["build_image", "deploy:demo", "smoke:demo", "holdouts:demo",
                                                 "owner_acceptance"])

    def test_FR_A8_AC_1_pilot_plan_runs_holdouts_on_staging_then_user_validation(self):
        self.assertEqual(delivery_plan("pilot"), ["build_image", "deploy:staging", "smoke:staging",
                                                  "holdouts:staging", "user_validation"])

    def test_FR_A8_AC_1_production_plan_is_pilot_then_gate_candidate_shadow_canary_promote(self):
        self.assertEqual(delivery_plan("production"), delivery_plan("pilot") + [
            "deploy_gate", "deploy_candidate:production", "shadow:production", "canary:production",
            "promote:production"])
        with self.assertRaises(ValueError):
            delivery_plan("moonshot")


class ExploreDeliveryTest(DeliveryTestCase):
    maturity = "explore"

    def test_FR_A8_AC_1_explore_lands_a_local_preview_process_without_any_road_from_it(self):
        self.factory.paved_roads_path.unlink()  # the built-in local preview needs nothing from IT
        out = deliver(self.project)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual((out["env"], out["release"], out["waiting_on"]), ("preview", 1, None))
        self.assertEqual([s["step"] for s in out["steps"]], delivery_plan("explore"))
        self.assertEqual(self.health("preview")["version"], self.main()[:12])
        rel = latest_release(self.project)
        art = rel["artifacts"]["local-preview"]
        self.assertEqual((art["type"], art["ref"]), ("process", f"repo.git@{self.main()}"))
        self.assertEqual(art["command"][1:], roadmod.LAUNCH)   # app.server imported once: see LAUNCH
        self.assertEqual(self.canon.cards(), [])                   # no human gate beyond intake
        self.assertEqual(deliver(self.project)["release"], 1)      # nothing new on main: nothing new


class DemoDeliveryTest(DeliveryTestCase):
    maturity = "demo"

    def test_FR_A8_AC_1_demo_runs_holdouts_on_demo_and_waits_for_the_business_owner(self):
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        self.assertEqual(out["env"], "demo")
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual((card["kind"], card["refs"]["release"]), ("approval", 1))
        self.assertEqual(self.step(out, "holdouts:demo")["native"]["verdict"], "passed")
        self.assertEqual(latest_release(self.project)["holdouts"]["environment"], "demo")
        self.decide(card["id"], "approve", "developer", person="Pekka")  # not the owner: asked again
        again = deliver(self.project)
        self.assertEqual(again["state"], "waiting")
        self.assertNotEqual(again["waiting_on"], card["id"])
        self.decide(again["waiting_on"], "approve", "business_owner")
        done = deliver(self.project)
        self.assertEqual(done["state"], "done", done)
        self.assertEqual(self.step(done, "owner_acceptance")["native"]["persona"], "business_owner")
        self.assertEqual(self.health("demo")["version"], self.main()[:12])


class RoadRefusalTest(DeliveryTestCase):
    maturity = "pilot"

    def test_FR_A8_AC_2_an_unconfigured_road_opens_a_road_card_for_it_and_deploys_nothing(self):
        docker = FakeDocker()
        write_json(self.factory.paved_roads_path, {
            "schema": roadmod.SCHEMA,
            "roads": {"team-docker": {"kind": "docker", "configured": False, "environments": ["staging", "production"],
                                      "rules": {"tls": "reverse proxy", "egress": "none"}}},
            "maturity": {"pilot": "team-docker"}})
        cli = roadmod.DockerCLI(runner=docker)
        out = deliver(self.project, docker=cli)
        self.assertEqual(out["state"], "waiting", out)
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual(card["kind"], "road")
        self.assertEqual(card["deciders"], ["it"])
        self.assertIn("configured", " ".join(card["payload"]["missing"]["staging"]))
        self.assertEqual(out["steps"], [])
        self.assertEqual(docker.calls, [])                               # no image, no container
        self.assertFalse(self.project.path("envs").exists())
        self.assertFalse(self.project.path("builds").exists())
        self.assertEqual(deliver(self.project, docker=cli)["waiting_on"], card["id"])  # one card, not one per call
        self.assertEqual(len(self.canon.cards(kind="road")), 1)
        with self.assertRaises(DecisionRefused):
            self.decide(card["id"], "configured", "developer", person="Pekka")
        write_json(self.factory.paved_roads_path, LOCAL_ROADS)           # IT configures a road ...
        self.decide(card["id"], "configured", "it", person="Jaana")      # ... and says so
        out = deliver(self.project, docker=cli)
        self.assertEqual(out["state"], "waiting")
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "validation")
        self.assertEqual(self.health("staging")["version"], self.main()[:12])

    def test_FR_A8_AC_2_without_paved_roads_json_the_factory_does_not_guess(self):
        self.factory.paved_roads_path.unlink()
        out = deliver(self.project)
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual((out["state"], card["kind"]), ("waiting", "road"))
        self.assertIn("no paved road is named for the staging environment", card["body"])
        self.assertFalse(self.project.path("envs").exists())
        self.decide(card["id"], "declined", "it", person="Jaana", reason="not this quarter")
        out = deliver(self.project)
        self.assertEqual((out["state"], out["failed_step"]), ("failed", "road"))
        self.assertIn("declined", out["reason"])

    def test_FR_A8_AC_2_azure_deploys_only_when_configured_with_an_identity_and_the_az_cli(self):
        roads = json.loads(json.dumps(LOCAL_ROADS))
        roads["roads"]["azure"] = dict(AZURE, configured=True)
        roads["roads"]["azure"].pop("identity")
        roads["maturity"]["pilot"] = "azure"
        write_json(self.factory.paved_roads_path, roads)
        out = deliver(self.project)
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual((out["state"], card["kind"]), ("waiting", "road"))
        missing = " ".join(card["payload"]["missing"]["staging"])
        self.assertIn("identity", missing)
        if shutil.which("az") is None:
            self.assertIn("az CLI is not on PATH", missing)
        self.assertFalse(self.project.path("envs").exists())


AZURE = {
    "kind": "azure-containerapps", "configured": False, "environments": ["staging", "production"],
    "identity": "/subscriptions/0000/resourceGroups/rg-gf/providers/Microsoft.ManagedIdentity/"
                "userAssignedIdentities/gf-deployer",
    "subscription": "0000", "resource_group": "rg-gf", "environment": "cae-gf", "registry": "gfacr.azurecr.io",
    "storage": "gf-data",
    "rules": {"region": "swedencentral", "regions": ["swedencentral", "westeurope"], "tls": "required",
              "ingress": {"external": True, "transport": "auto"}, "egress": {"default": "deny", "allow": []}},
    "secrets": [{"name": "API_TOKEN", "ref": "https://kv-gf.vault.azure.net/secrets/api-token"}],
}


class PackageTest(DeliveryTestCase):
    maturity = "pilot"
    ART = {"type": "image", "ref": "gfacr.azurecr.io/gf-x:0123456789ab"}

    def package(self, road, env="production", slot="current", artifact=None):
        rev = "0123456789ab" + "c" * 28
        return road.package(self.project, env=env, slot=slot, release=3, revision=rev,
                            artifact=artifact or self.ART, contract_revision="sha256:abc")

    def test_FR_Q4_AC_1_local_and_docker_packages_hold_the_artifact_the_settings_and_the_rules(self):
        paved = roadmod.PavedRoads.load(LOCAL_ROADS)
        local = self.package(paved.road("local"), env="staging", artifact={
            "type": "process", "ref": "repo.git@0123456789ab", "checkout": "builds/0123456789ab",
            "command": ["python3", "-m", "app.server"]})
        self.assertEqual(roadmod.validate_package(local), [])
        self.assertEqual(local["artifact"]["command"], ["python3", "-m", "app.server"])
        self.assertEqual(local["settings"], {"APP_VERSION": "0123456789ab", "PORT": "auto",
                                             "DATA_DIR": "envs/staging/data", "TRAFFIC_LOG": "envs/staging/traffic.jsonl"})
        self.assertEqual(local["rules"], LOCAL_ROADS["roads"]["local"]["rules"])
        self.assertEqual((local["environment"], local["slot"], local["release"]), ("staging", "current", 3))
        docker_road = roadmod.DockerRoad("team", {"kind": "docker", "rules": {"tls": "proxy", "egress": "none"}},
                                         docker=roadmod.DockerCLI(runner=FakeDocker()))
        pkg = self.package(docker_road, slot="candidate", artifact={"type": "image", "ref": "gf-x:0123456789ab"})
        self.assertEqual(roadmod.validate_package(pkg), [])
        self.assertEqual(pkg["artifact"]["ref"], "gf-x:0123456789ab")
        self.assertEqual(pkg["settings"]["TRAFFIC_LOG"], "/data/traffic.jsonl")
        pid = self.project.pid
        self.assertEqual((pkg["target"]["container"], pkg["target"]["volume"]),
                         (f"gf-{pid}-production-candidate", f"gf-{pid}-production-candidate-data"))
        self.assertEqual(pkg["rules"], {"tls": "proxy", "egress": "none"})

    def test_FR_Q4_AC_1_the_azure_package_is_rendered_validated_and_holds_no_secret_value(self):
        road = roadmod.AzureContainerAppsRoad("azure", AZURE)
        pkg = self.package(road)
        self.assertEqual(roadmod.validate_package(pkg), [])
        model, text = pkg["rendered"]["model"], pkg["rendered"]["yaml"]
        self.assertEqual(roadmod.from_yaml(text), model)               # the YAML reads back as rendered
        self.assertEqual(model["location"], "swedencentral")
        conf = model["properties"]["configuration"]
        self.assertIs(conf["ingress"]["allowInsecure"], False)          # the road's TLS rule
        self.assertEqual(pkg["rules"]["egress"], {"default": "deny", "allow": []})
        self.assertEqual(model["properties"]["template"]["containers"][0]["image"], self.ART["ref"])
        env = {e["name"]: e for e in model["properties"]["template"]["containers"][0]["env"]}
        self.assertEqual(env["APP_VERSION"]["value"], "0123456789ab")
        self.assertEqual(env["API_TOKEN"], {"name": "API_TOKEN", "secretRef": "api-token"})
        self.assertEqual(conf["secrets"][0]["keyVaultUrl"], AZURE["secrets"][0]["ref"])
        self.assertIn(AZURE["identity"], model["identity"]["userAssignedIdentities"])
        self.assertLessEqual(len(model["name"]), 32)
        self.assertIn(["az", "containerapp", "create", "--name", model["name"], "--resource-group", "rg-gf",
                       "--yaml", pkg["target"]["yaml"]], pkg["rendered"]["commands"].values())
        # A secret value written into the road never reaches a package, and the package says why.
        leaky = json.loads(json.dumps(AZURE))
        leaky["secrets"][0]["value"] = "s3cr3t-do-not-ship"
        pkg = self.package(roadmod.AzureContainerAppsRoad("azure", leaky))
        self.assertNotIn("s3cr3t-do-not-ship", json.dumps(pkg))
        self.assertTrue(any("carries a value" in p for p in roadmod.validate_package(pkg)))
        # A package someone edited to carry a value, or with a broken YAML, fails validation.
        pkg = self.package(road)
        pkg["rendered"]["model"]["properties"]["configuration"]["secrets"][0]["value"] = "s3cr3t"
        self.assertTrue(roadmod.validate_package(pkg))
        pkg = self.package(road)
        pkg["rendered"]["yaml"] += "\tbad: 1\n"
        self.assertTrue(any("YAML" in p for p in roadmod.validate_package(pkg)))
        insecure = self.package(roadmod.AzureContainerAppsRoad("azure", dict(AZURE, rules=dict(AZURE["rules"], tls="none"))))
        self.assertTrue(any("TLS" in p for p in roadmod.validate_containerapp(dict(insecure, rules=AZURE["rules"]))))

    def test_FR_Q4_AC_1_the_docker_road_builds_runs_and_stops_with_these_commands(self):
        rev = self.main()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
        server.version = rev[:12]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        fake = FakeDocker(port=server.server_address[1])
        road = roadmod.DockerRoad("team", {"kind": "docker", "rules": {"tls": "proxy", "egress": "none"}},
                                  docker=roadmod.DockerCLI(runner=fake))
        self.addCleanup(roadmod.stop_all, self.project, None, docker=roadmod.DockerCLI(runner=fake))
        pid = self.project.pid
        art = road.build(self.project, rev)
        self.assertEqual(art, {"type": "image", "ref": f"gf-{pid}:{rev[:12]}", "id": "sha256:" + "ab" * 32})
        checkout = str(self.project.path("builds", rev[:12]))
        self.assertEqual(fake.calls[0], ["docker", "build", "--tag", f"gf-{pid}:{rev[:12]}",
                                         "--label", f"gnomonfactory.project={pid}",
                                         "--label", f"gnomonfactory.revision={rev}", checkout])
        self.assertTrue(Path(checkout, "Dockerfile").exists())
        fake.calls.clear()
        state = road.deploy(self.project, road.package(self.project, env="staging", slot="current", release=1,
                                                       revision=rev, artifact=art))
        name = f"gf-{pid}-staging-current"
        self.assertEqual(fake.calls[0], ["docker", "rm", "--force", name])
        self.assertEqual(fake.calls[1], [
            "docker", "run", "--detach", "--name", name, "--restart", "unless-stopped",
            "--publish", "127.0.0.1::8080", "--volume", f"gf-{pid}-staging-data:/data",
            "--env", f"APP_VERSION={rev[:12]}", "--env", "TRAFFIC_LOG=/data/traffic.jsonl",
            "--label", f"gnomonfactory.project={pid}", "--label", "gnomonfactory.env=staging",
            "--label", "gnomonfactory.slot=current", "--label", "gnomonfactory.release=1", f"gf-{pid}:{rev[:12]}",
            "python3", "-c", "from app.server import main; main()"])
        self.assertEqual(fake.calls[2], ["docker", "port", name, "8080/tcp"])
        self.assertEqual(state["base_url"], f"http://127.0.0.1:{server.server_address[1]}")
        self.assertEqual(state["health"]["body"]["version"], rev[:12])
        fake.calls.clear()
        road.deploy(self.project, road.package(self.project, env="production", slot="candidate", release=1,
                                               revision=rev, artifact=art))
        self.assertIn(["docker", "volume", "rm", "--force", f"gf-{pid}-production-candidate-data"], fake.calls)
        fake.calls.clear()
        road.stop(self.project, "production", "candidate")
        self.assertEqual(fake.calls, [["docker", "rm", "--force", f"gf-{pid}-production-candidate"],
                                      ["docker", "volume", "rm", "--force", f"gf-{pid}-production-candidate-data"]])
        self.assertIsNone(roadmod.slot_state(self.project, "production", "candidate"))


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "ok", "version": self.server.version}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


class HoldoutTest(DeliveryTestCase):
    maturity = "pilot"

    def test_FR_H3_AC_1_a_pilot_is_validated_only_after_every_holdout_passes_on_staging(self):
        write_json(self.project.holdouts_dir / "X-PREV.json", {"criterion": "X-PREV", "kind": "holdout", "steps": [
            {"method": "POST", "path": "/items", "body": {"name": "saw"}, "expect_status": 201},
            {"method": "POST", "path": "/items", "body": {"name": "copy of {{prev.name}}"}, "expect_status": 201,
             "expect_json": {"name": "copy of saw"}},
            {"method": "GET", "path": "/items", "expect_status": 200, "expect_json": [{"name": "copy of saw"}],
             "max_ms": 2000}]})
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual(card["kind"], "validation")
        self.assertEqual(card["verdicts"], ["accept", "fix", "change", "keep"])
        rel = latest_release(self.project)
        self.assertEqual(rel["holdouts"]["environment"], "staging")
        self.assertEqual(rel["holdouts"]["verdict"], "passed")
        self.assertEqual(sorted(r["criterion"] for r in rel["holdouts"]["results"]), ["R-1-AC-2", "R-4-AC-2", "X-PREV"])
        self.assertEqual([s["step"] for s in out["steps"]], delivery_plan("pilot"))
        self.decide(card["id"], "accept", "business_owner")
        done = deliver(self.project)
        self.assertEqual(done["state"], "done", done)
        self.assertEqual(self.step(done, "user_validation")["native"]["verdict"], "accept")
        self.assertEqual(latest_release(self.project)["cards"][-1]["decision"]["verdict"], "accept")

    def test_FR_H3_AC_1_a_validation_asking_for_a_fix_stops_the_release_and_hands_the_card_on(self):
        out = deliver(self.project)
        self.decide(out["waiting_on"], "fix", "product_owner", person="Pekka", reason="the list is unsorted")
        out2 = deliver(self.project)
        self.assertEqual((out2["state"], out2["waiting_on"]), ("failed", out["waiting_on"]))
        self.assertEqual(out2["handoff"], {"to": "change", "card": out["waiting_on"], "verdict": "fix"})


class FailingHoldoutTest(DeliveryTestCase):
    maturity = "production"

    def test_FR_H3_AC_1_a_failing_holdout_stops_the_release_with_its_first_failing_step(self):
        write_json(self.project.holdouts_dir / "R-1-AC-2.json", {"criterion": "R-1-AC-2", "kind": "holdout", "steps": [
            {"method": "POST", "path": "/items", "body": {"name": "drill"}, "expect_status": 201},
            {"method": "GET", "path": "/items", "expect_status": 200, "expect_contains": "hammer"},
            {"method": "GET", "path": "/never-reached", "expect_status": 200}]})
        out = deliver(self.project)
        self.assertEqual((out["state"], out["failed_step"], out["waiting_on"]), ("failed", "holdouts:staging", None))
        rel = latest_release(self.project)
        failing = [r for r in rel["holdouts"]["results"] if r["verdict"] == "failed"]
        self.assertEqual(len(failing), 1)
        f = failing[0]
        self.assertEqual((f["criterion"], f["failed_step"]), ("R-1-AC-2", 2))
        self.assertEqual(f["observed"]["status"], 200)
        self.assertEqual(f["observed"]["body"], [{"id": "1", "name": "drill"}])    # the native body
        self.assertEqual(f["expected"], {"expect_status": 200, "expect_contains": "hammer"})
        self.assertIn("hammer", out["reason"])
        self.assertEqual(self.canon.cards(kind="validation"), [])     # no validation without the holdouts
        self.assertIsNone(roadmod.slot_state(self.project, "production", "current"))
        again = deliver(self.project)                                  # the same revision is not retried
        self.assertEqual((again["release"], again["state"]), (1, "failed"))
        self.assertEqual(len(releases(self.project)), 1)


class DeployGateTest(DeliveryTestCase):
    maturity = "production"

    def to_the_gate(self) -> dict:
        out = deliver(self.project)
        self.decide(out["waiting_on"], "accept", "business_owner")
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        return self.canon.get_card(out["waiting_on"])

    def test_FR_Q5_AC_1_refuse_at_the_deploy_gate_stops_the_release(self):
        gate = self.to_the_gate()
        self.assertEqual((gate["kind"], gate["deciders"]), ("deploy_gate", ["it"]))
        self.assertEqual(gate["payload"]["artifact"], f"repo.git@{self.main()}")
        self.assertEqual(gate["payload"]["rules"], LOCAL_ROADS["roads"]["local"]["rules"])
        with self.assertRaises(DecisionRefused):
            self.decide(gate["id"], "approve", "business_owner")      # only IT opens the gate
        self.decide(gate["id"], "refuse", "it", person="Jaana", reason="change freeze")
        out = deliver(self.project)
        self.assertEqual((out["state"], out["failed_step"]), ("failed", "deploy_gate"))
        self.assertIn("refuse", out["reason"])
        self.assertIsNone(roadmod.slot_state(self.project, "production", "current"))
        self.assertIsNone(roadmod.slot_state(self.project, "production", "candidate"))

    def test_FR_Q5_AC_1_approve_at_the_deploy_gate_lets_the_next_deliver_continue(self):
        gate = self.to_the_gate()
        self.assertIsNone(roadmod.slot_state(self.project, "production", "candidate"))  # waits: nothing deployed
        self.decide(gate["id"], "approve", "it", person="Jaana")
        out = deliver(self.project)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual([s["step"] for s in out["steps"]], delivery_plan("production"))
        self.assertEqual(self.step(out, "deploy_gate")["native"]["persona"], "it")
        self.assertEqual(self.step(out, "shadow:production")["outcome"], "not applicable")  # no current yet
        self.assertEqual(self.step(out, "canary:production")["native"]["decision"], "promote")
        self.assertEqual(self.health("production")["version"], self.main()[:12])
        self.assertIsNone(roadmod.slot_state(self.project, "production", "candidate"))
        rel = latest_release(self.project)
        self.assertEqual([c["kind"] for c in rel["cards"]], ["validation", "deploy_gate"])
        self.assertEqual(rel["contract_revision"], self.project.read("contract.json")["revision"])
        self.assertEqual(rel["revision"], self.main())

    def test_FR_Q5_AC_1_a_gate_waiting_on_an_old_revision_is_withdrawn_when_main_moves(self):
        gate = self.to_the_gate()
        rev2 = self.commit_routes(MORE_ROUTES, "A count route")
        out = deliver(self.project)                       # an approval is for one revision
        self.assertEqual((out["release"], out["revision"], out["state"]), (2, rev2, "waiting"))
        self.assertEqual(self.canon.get_card(gate["id"])["state"], "withdrawn")
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "validation")
        old = releases(self.project)[0]
        self.assertEqual((old["state"], old["superseded_by"]["revision"]), ("superseded", rev2))
        with self.assertRaises(DecisionRefused):
            self.decide(gate["id"], "approve", "it", person="Jaana")


if __name__ == "__main__":
    unittest.main()
