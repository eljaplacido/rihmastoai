"""Factory fixes the live dogfood runs found (FR-DF1 to FR-DF5).

- FR-DF1: a spec requirement contradicted the paved road ("localhost-only"), the builder bound
  127.0.0.1 inside the container and replaced /health, every test passed and delivery failed its
  health check with an empty "logs". The prompts now state the road's platform facts, the scaffold
  ships road-contract tests no cell may change, the plan review flags a conflicting requirement,
  and a failed health check keeps the container's log tail, its listening sockets and a diagnosis.
- FR-DF2: holdouts could not sign a request a spec requires to be signed.
- FR-DF3: a defect whose triage named no requirement was filed against R-1.
- FR-DF4: the profile proposal matched keywords inside other words ('train' in 'trainees').
- FR-DF5: an adoption baseline had no per-suite limit of its own.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import GOOD_ROUTES, FactoryTestCase, model, no_findings, script  # noqa: E402
from test_adopt import leaking_suite, make_repo  # noqa: E402
from test_deliver import LOCAL_ROADS, DeliveryTestCase, FakeDocker  # noqa: E402

from kernel import holdouts, plan, scaffold  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.adopt import SUITE_TIMEOUT, adopt, run_baseline  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.change import (  # noqa: E402
    NEW_REQUIREMENT,
    WHICH_REQUIREMENT,
    RequirementUnknown,
    _regression,
    apply_change,
    submit,
    triage,
)
from kernel.compile import author_holdouts, compile_project, holdout_prompt  # noqa: E402
from kernel.deliver import deliver, latest_release  # noqa: E402
from kernel.dispatch import build_task, envelope  # noqa: E402
from kernel.gate import run_suite  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import GIT_ID, PROTECTED, Lanes, _git, protected_paths  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.operate import run_holdouts, run_scenario  # noqa: E402
from kernel.profiles import PROFILE_QUESTION, keyword_pattern, propose_profile  # noqa: E402
from kernel.spec import make_spec, spec_prompt  # noqa: E402
from kernel.store import write_json, write_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
SPEC_PROMPT = "You turn a brief into a software specification"
SECRET = "test-only-signing-key-7f3a"   # a test secret, never a real one
# Run 4's spec, in short: the requirement the analyst wrote, and a criterion that redefines /health.
LOCAL_ONLY = {
    "title": "Ledger explorer", "summary": "Browse ledger entries.", "users": ["analysts"],
    "requirements": [
        {"statement": "Analysts can list ledger entries.", "sources": ["request"], "priority": "must",
         "acceptance": [{"given": "entries", "when": "GET /entries", "then": "200 with the entries", "kind": "test"}]},
        {"statement": "The service is localhost-only: it binds 127.0.0.1.", "sources": ["request"], "priority": "must",
         "acceptance": [{"given": "-", "when": "GET /health", "then": 'it returns {"status": "ok"}', "kind": "test"},
                        {"given": "-", "when": "GET /health", "then": "answers in under 500 ms", "kind": "probe"}]},
        {"statement": "It listens on port 5000.", "sources": ["proposed"], "priority": "could",
         "acceptance": [{"given": "-", "when": "GET /entries?limit=1", "then": "200 with one entry", "kind": "test"}]},
    ],
    "out_of_scope": [],
}


def scripted(**answers: Any) -> FakeModel:
    """The shared script, with the answers to some prompts replaced (keyed by words the prompt holds)."""
    def answer(prompt: str, role: str) -> str:
        for words, reply in answers.items():
            if words.replace("_", " ") in prompt:
                return "```json\n" + json.dumps(reply) + "\n```"
        return script(prompt, role)
    return FakeModel(answer)


def specced(case: FactoryTestCase, *, spec: dict | None = None, maturity: str = "demo"):
    p = case.new(mode="assume", maturity=maturity)
    intake(p, IDEA, model=model(), requested_by="Aino")
    make_spec(p, model=scripted(**{SPEC_PROMPT: spec}) if spec else model())
    return p


def product_tree(root: Path, **changes: str) -> Path:
    """The paved-road template as a git repository, with some of its files changed."""
    root.mkdir(parents=True)
    for rel, text in {**scaffold.files("T", "p", "explore"), **changes}.items():
        write_text(root / rel, text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, *GIT_ID, "commit", "-q", "-m", "template")
    return root


def road_outcomes(run: dict) -> dict[str, str]:
    return {n: o for n, o in run["tests"].items() if n.startswith("test_ROAD_")}


# -- FR-DF1: the paved road's platform facts ---------------------------------------------------------

class RoadFactsInPromptsTest(FactoryTestCase):
    def test_FR_DF1_AC_1_the_spec_prompt_and_the_builders_envelope_state_the_roads_platform_facts(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        analyst = spec_prompt(p)
        for fact in roadmod.ROAD_FACTS.values():
            self.assertIn(fact, analyst)
        self.assertIn("HOST", analyst)
        self.assertIn("(default 0.0.0.0)", analyst)
        self.assertIn('"localhost-only"', analyst)                   # where that wish goes instead
        self.assertIn("out_of_scope", analyst)
        make_spec(p, model=model())
        contract = compile_project(p)
        builder = envelope(p, contract, "T-001", base="0" * 40)
        section = builder.split("## The paved road's platform facts", 1)[1].split("## Rules", 1)[0]
        for fact in roadmod.ROAD_FACTS.values():
            self.assertIn(fact, section)
        self.assertIn("Never set HOST", section)
        self.assertIn("Never register, replace or change GET /health", section)
        self.assertIn(f"`{scaffold.ROAD_CONTRACT_TESTS}`", section)
        self.assertIn("never edit or remove it", section)


class RoadContractTestsTest(FactoryTestCase):
    def test_FR_DF1_AC_2_the_template_ships_road_contract_tests_that_pass_on_it(self):
        files = scaffold.files("T", "p", "explore")
        self.assertIn(scaffold.ROAD_CONTRACT_TESTS, files)
        self.assertEqual(scaffold.ROAD_CONTRACT_TESTS, "tests/test_road_contract.py")
        run = run_suite(product_tree(self.tmp / "template"))
        self.assertEqual(run["exit"], 0, run)
        self.assertEqual(road_outcomes(run), {
            "test_ROAD_health_answers_ok_with_the_release_version": "ok",
            "test_ROAD_the_service_binds_every_interface_unless_HOST_says_otherwise": "ok",
            "test_ROAD_the_service_binds_the_HOST_and_PORT_the_road_gives": "ok"})

    def test_FR_DF1_AC_2_the_road_contract_tests_fail_a_product_bound_to_loopback_or_without_its_health(self):
        loopback = run_suite(product_tree(self.tmp / "loopback", **{
            "app/__init__.py": 'import os\n\nos.environ["HOST"] = "127.0.0.1"\n'}))
        self.assertEqual(loopback["exit"], 1)
        self.assertEqual(road_outcomes(loopback)["test_ROAD_the_service_binds_every_interface_unless_HOST_says_otherwise"],
                         "FAIL")
        replaced = GOOD_ROUTES + (
            "\n\nfrom app.server import ROUTES\n\n"
            "ROUTES[:] = [r for r in ROUTES if r[1].pattern != '^/health$']\n\n\n"
            "@route(\"GET\", \"/health\")\ndef plain_health(req):\n    return 200, {\"status\": \"ok\"}\n")
        health = run_suite(product_tree(self.tmp / "health", **{"app/routes.py": replaced}))
        self.assertEqual(health["exit"], 1)
        self.assertEqual(road_outcomes(health)["test_ROAD_health_answers_ok_with_the_release_version"], "FAIL")
        docker = run_suite(product_tree(self.tmp / "dockerfile", **{
            "Dockerfile": scaffold.DOCKERFILE.replace("ENV PORT=8080", "ENV HOST=127.0.0.1 PORT=8080")}))
        self.assertEqual(road_outcomes(docker)["test_ROAD_the_service_binds_the_HOST_and_PORT_the_road_gives"], "FAIL")

    def test_FR_DF1_AC_2_a_cell_that_edits_or_removes_the_road_contract_tests_is_a_protected_path_violation(self):
        self.assertIn(scaffold.ROAD_CONTRACT_TESTS, PROTECTED)
        repo = product_tree(self.tmp / "repo")
        base = _git(repo, "rev-parse", "HEAD")
        (repo / scaffold.ROAD_CONTRACT_TESTS).unlink()
        _git(repo, "add", "-A")
        _git(repo, *GIT_ID, "commit", "-q", "-m", "drop the road's tests")
        self.assertEqual(protected_paths(repo, base, "HEAD"), [scaffold.ROAD_CONTRACT_TESTS])
        p = specced(self)
        compile_project(p)
        main = _git(p.path("repo.git"), "rev-parse", "main")

        def editing_cell(lane_path, prompt):
            road_tests = Path(lane_path, scaffold.ROAD_CONTRACT_TESTS)
            road_tests.write_text("import unittest\n", encoding="utf-8", newline="\n")
            Path(lane_path, "app", "routes.py").write_text(GOOD_ROUTES, encoding="utf-8", newline="\n")
            return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 3, "model": "fake-builder",
                    "output": "done"}

        out = build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=editing_cell,
                         verifier_runner=no_findings, max_rounds=0)
        signals = {s["name"]: s["verdict"] for s in out["rounds"][-1]["gate"]["signals"]}
        self.assertEqual((out["status"], signals["protected"]), ("escalated", "violation"))
        self.assertEqual(_git(p.path("repo.git"), "rev-parse", "main"), main)    # nothing merged
        system = _git(p.path("repo.git"), "show", "main:.gnomon/system.md")
        self.assertIn("`tests/test_road_contract.py` is the paved road's own check: read-only too.", system)


class RoadConflictReviewTest(FactoryTestCase):
    def test_FR_DF1_AC_3_the_plan_review_flags_each_requirement_that_contradicts_the_road(self):
        p = specced(self, spec=LOCAL_ONLY, maturity="demo")
        conflicts = roadmod.road_conflicts(p.read("spec.json"))
        self.assertEqual([(c["requirement"], c["criterion"], c["fact"]) for c in conflicts],
                         [("R-2", None, "bind"), ("R-2", "R-2-AC-1", "health"), ("R-3", None, "port")])
        self.assertIn(roadmod.ROAD_FACTS["bind"], conflicts[0]["road"])
        self.assertIn(roadmod.ROAD_FACTS["health"], conflicts[1]["road"])
        self.assertTrue(plan.required(p))                                   # a demo needs no review, except now
        waiting = plan.gate(p, model=model())
        card = Canon(p).get_card(waiting["waiting_on"][0])
        self.assertIn("3 conflicts with the paved road", card["title"])
        self.assertIn("Conflicts with the paved road", card["body"])
        self.assertIn('R-2 says "localhost-only"', card["body"])
        self.assertIn("R-2-AC-1 says", card["body"])
        self.assertEqual(len(card["payload"]["road_conflicts"]), 3)
        self.assertIn("## Conflicts with the paved road", p.path("spec.md").read_text(encoding="utf-8"))
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        self.assertIn("spec_road_conflicts", kinds)

    def test_FR_DF1_AC_3_a_spec_the_road_can_serve_has_no_conflict_and_keeps_its_maturitys_review(self):
        p = specced(self)                                     # its probe names /health's latency: no conflict
        self.assertEqual(roadmod.road_conflicts(p.read("spec.json")), [])
        self.assertFalse(plan.required(p))
        for text in ("GET /health answers 200 with the status and the version", "The page loads in a second",
                     "Reports are only on the local network share", "It runs on port 8080"):
            self.assertEqual(roadmod.road_conflicts({"requirements": [{"id": "R-1", "statement": text,
                                                                       "acceptance": []}]}), [], text)
        for text in ("Listens only on localhost", "binds to loopback", "HOST=127.0.0.1",
                     "GET /health returns only the status, without the version"):
            self.assertTrue(roadmod.road_conflicts({"requirements": [{"id": "R-1", "statement": text,
                                                                      "acceptance": []}]}), text)

    def test_FR_DF1_AC_5_the_plan_review_finds_a_road_conflict_in_its_common_phrasings(self):
        def facts(text: str) -> list[str]:
            spec = {"requirements": [{"id": "R-1", "statement": text, "acceptance": []}]}
            return [c["fact"] for c in roadmod.road_conflicts(spec)]

        flagged = {   # the phrasings an independent check found the first rules missed, and their kin
            "bind": ("The service must only be accessible from localhost", "The server binds 127.0.0.1",
                     "Restrict access to localhost", "Set HOST to 127.0.0.1", "Limit the API to localhost",
                     "The service must not be exposed beyond localhost", "Serve the app from 127.0.0.1",
                     "It calls the API and is accessible only from localhost"),
            "port": ("Set PORT to 5000", "The app listens on 0.0.0.0:5000",
                     "The service runs on port 5000 and connects to the database on 5432",
                     "The service stores data in the database and listens on port 5000"),
            "health": ("The /health endpoint must not disclose the version",
                       "The /health endpoint must not expose the application version",
                       "GET /health answers 200 with an empty body", "GET /health answers 204",
                       "The version must not be shown on /health"),
        }
        for fact, texts in flagged.items():
            for text in texts:
                self.assertEqual(facts(text)[:1], [fact], text)
        for text in ("The database runs on port 5432", "Redis, which caches sessions, listens on port 6379",
                     "The service connects to Postgres on port 5432",                  # another component's port
                     "The service calls the model server at localhost:11434",          # egress, not a bind
                     "The service only calls the model server at localhost",
                     "Only admins sign in. Tests run against localhost.",               # two sentences
                     "GET /health returns 200 when the database is empty",
                     "GET /health answers with the version; it must not expose secrets"):
            self.assertEqual(facts(text), [], text)
        spec = {"requirements": [{"id": "R-1", "statement": "The service is for the IT team.", "acceptance": [
            {"id": "R-1-AC-1", "given": "-", "when": "GET /health",
             "then": "it must not disclose the version", "kind": "test"}]}]}
        self.assertEqual(roadmod.conflict_lines(spec),
                         [f"- R-1-AC-1 says \"not disclose the version\": {roadmod.ROAD_FACTS['health']}"])


class LoopbackDocker(FakeDocker):
    """A docker CLI whose container listens on loopback only and logs its start on stderr."""

    def __init__(self, port, listening=" 0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000\n"):
        super().__init__(port=port)
        self.listening = listening

    def __call__(self, argv, timeout):
        if argv[1] == "logs":
            self.calls.append(list(argv))
            return 0, "", "serving on 127.0.0.1:8080\n"
        if argv[1:3] == ["exec", argv[2]] and argv[3:5] == ["cat", "/proc/net/tcp"]:
            self.calls.append(list(argv))
            header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid\n"
            return 0, header + self.listening, ""
        return super().__call__(argv, timeout)


class _NoVersion(BaseHTTPRequestHandler):
    def do_GET(self):
        data = b'{"status": "ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        return


class HealthEvidenceTest(DeliveryTestCase):
    maturity = "pilot"

    def docker_roads(self) -> None:
        write_json(self.factory.paved_roads_path, {
            "schema": roadmod.SCHEMA, "maturity": {"pilot": "team-docker"},
            "roads": {"team-docker": {"kind": "docker", "configured": True, "environments": ["staging", "production"],
                                      "start_timeout": 1, "rules": {"tls": "proxy", "egress": "none"}}}})

    def deploy_step(self) -> dict:
        rel = latest_release(self.project)
        return next(s for s in rel["steps"] if s["step"] == "deploy:staging")

    def test_FR_DF1_AC_4_a_failed_health_check_keeps_the_log_tail_the_listening_sockets_and_why(self):
        self.docker_roads()
        fake = LoopbackDocker(port=roadmod.free_port())                      # nothing answers there
        out = deliver(self.project, docker=roadmod.DockerCLI(runner=fake))
        self.assertEqual((out["state"], out["failed_step"]), ("failed", "deploy:staging"))
        native = self.deploy_step()["native"]
        self.assertIn("serving on 127.0.0.1:8080", native["logs"])          # the container's stderr, not ""
        self.assertEqual(native["listening"], ["127.0.0.1:8080"])
        self.assertIn("listens on loopback inside the container only", native["diagnosis"])
        self.assertIn(roadmod.ROAD_FACTS["bind"], native["diagnosis"])
        name = f"gf-{self.project.pid}-staging-current"
        self.assertIn(["docker", "exec", name, "cat", "/proc/net/tcp", "/proc/net/tcp6"], fake.calls)

    def test_FR_DF1_AC_4_a_health_answer_without_the_release_version_is_named_as_the_cause(self):
        self.docker_roads()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _NoVersion)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        everywhere = " 0: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000\n"
        docker = roadmod.DockerCLI(runner=LoopbackDocker(server.server_address[1], everywhere))
        out = deliver(self.project, docker=docker)
        self.assertEqual(out["failed_step"], "deploy:staging")
        native = self.deploy_step()["native"]
        self.assertEqual(native["listening"], ["0.0.0.0:8080"])
        self.assertIn("not the release version", native["diagnosis"])
        self.assertIn(roadmod.ROAD_FACTS["health"], native["diagnosis"])

    def test_FR_DF1_AC_4_the_local_road_gives_the_product_a_loopback_host(self):
        seen: dict = {}

        def capture(argv, **kwargs):
            seen.update(kwargs["env"])
            raise OSError("stopped by the test before it started")

        road = roadmod.PavedRoads.load(LOCAL_ROADS).road("local")
        art = road.build(self.project, self.main())
        pkg = road.package(self.project, env="staging", slot="twin", release=9, revision=self.main(), artifact=art)
        with mock.patch.dict(os.environ, {"HOST": "0.0.0.0"}), \
                mock.patch.object(roadmod.subprocess, "Popen", side_effect=capture), \
                self.assertRaises(roadmod.RoadError):
            road.deploy(self.project, pkg)
        self.assertEqual(seen["HOST"], "127.0.0.1")
        self.assertEqual(roadmod.listening_sockets(
            " 1: 00000000000000000000000001000000:1F90 00000000000000000000000000000000:0000 0A x\n"
            " 2: 00000000000000000000000000000000:0050 00000000000000000000000000000000:0000 0A x\n"
            " 3: 0100007F:1F91 0100007F:9C40 01 x\n"), ["[::1]:8080", "[::]:80"])


# -- FR-DF2: holdouts that sign their requests -------------------------------------------------------

class _Signed(BaseHTTPRequestHandler):
    """A webhook that answers 401 to a request without a valid HMAC signature, as Run 2's did."""

    seen: list = []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        want = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        got = self.headers.get("X-Carrier-Signature")
        type(self).seen.append({"raw": raw, "signature": got, "type": self.headers.get("Content-Type")})
        status, data = (202, b'{"accepted": true}') if got == want else (401, b'{"error": "missing HMAC signature"}')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        return


SIGNED_STEP = {"method": "POST", "path": "/carriers/a/events", "body": {"event": "delivered", "ref": "R-1-AC-2"},
               "sign": {"header": "X-Carrier-Signature", "secret": "CARRIER_WEBHOOK_SECRET", "prefix": "sha256="},
               "expect_status": 202, "expect_json": {"accepted": True}}


class SignedHoldoutTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        _Signed.seen = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Signed)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def test_FR_DF2_AC_1_a_signed_step_carries_hmac_sha256_over_the_exact_body_it_sends(self):
        scenario = {"criterion": "R-1-AC-2", "steps": [SIGNED_STEP]}
        result = run_scenario(self.url, scenario, secrets={"CARRIER_WEBHOOK_SECRET": SECRET})
        self.assertEqual(result["verdict"], "passed", result)
        sent = _Signed.seen[-1]
        self.assertEqual(json.loads(sent["raw"]), SIGNED_STEP["body"])
        digest = hmac.new(SECRET.encode(), sent["raw"], hashlib.sha256).hexdigest()
        self.assertEqual(sent["signature"], "sha256=" + digest)
        self.assertEqual(sent["type"], "application/json")
        unsigned = run_scenario(self.url, {"criterion": "R-1-AC-2", "steps": [
            {k: v for k, v in SIGNED_STEP.items() if k != "sign"}]})
        self.assertEqual((unsigned["verdict"], unsigned["observed"]["status"]), ("failed", 401))   # Run 2's 401

    def test_FR_DF2_AC_1_a_step_that_cannot_be_signed_is_not_measured_and_no_value_is_kept(self):
        cases = [({}, "name no secret CARRIER_WEBHOOK_SECRET"),
                 ({"CARRIER_WEBHOOK_SECRET": None}, "cannot read it"),
                 ({"CARRIER_WEBHOOK_SECRET": SECRET}, "never by its value")]
        for secrets, why in cases:
            step = dict(SIGNED_STEP, sign=dict(SIGNED_STEP["sign"], secret=SECRET)) if "value" in why else SIGNED_STEP
            result = run_scenario(self.url, {"criterion": "R-1-AC-2", "steps": [step]}, secrets=secrets)
            self.assertEqual(result["verdict"], "not measured", why)
            self.assertIn(why, result["reason"])
            self.assertNotIn(SECRET, json.dumps(result["reason"]))
        self.assertEqual(_Signed.seen, [])                                   # nothing unsigned went out
        cleaned = holdouts.clean_step(dict(SIGNED_STEP, sign={"header": "X-Sig", "secret": SECRET}))
        self.assertNotIn(SECRET, json.dumps(cleaned))                       # a value never enters custody
        road = roadmod.LocalProcessRoad("local", {"secrets": [
            {"name": "CARRIER_WEBHOOK_SECRET", "ref": "env:RIHMA_TEST_CARRIER_SECRET"},
            {"name": "VAULTED", "ref": "https://vault.example.invalid/secrets/x"}]})
        with mock.patch.dict(os.environ, {"RIHMA_TEST_CARRIER_SECRET": SECRET}):
            self.assertEqual(holdouts.environment_secrets(road), {"CARRIER_WEBHOOK_SECRET": SECRET, "VAULTED": None})
        report = run_holdouts(self.compiled_with([SIGNED_STEP]), self.url, kinds=("holdout",),
                              secrets={"CARRIER_WEBHOOK_SECRET": SECRET})
        self.assertEqual(report["passed"], 1)
        self.assertNotIn(SECRET, json.dumps(report))

    def test_FR_DF2_AC_3_a_sign_with_a_bad_prefix_or_header_is_not_measured_and_nothing_is_sent(self):
        secrets = {"CARRIER_WEBHOOK_SECRET": SECRET}
        for sign, why in (
                ({"prefix": "a\r\nX-Evil: 1\r\n"}, "no line break"),               # would start a header of its own
                ({"prefix": "sha256=\n"}, "no line break"),
                ({"header": "Content-Length"}, "Content-Length is a header HTTP itself sends"),
                ({"header": "Host"}, "Host is a header HTTP itself sends"),
                ({"header": "content-type"}, "content-type is a header HTTP itself sends"),
                ({"header": "Proxy-Signature"}, "Proxy-Signature is a header HTTP itself sends"),
                ({"header": "X Sig"}, "names the header the signature goes in")):
            step = dict(SIGNED_STEP, sign=dict(SIGNED_STEP["sign"], **sign))
            result = run_scenario(self.url, {"criterion": "R-1-AC-2", "steps": [step]}, secrets=secrets)
            self.assertEqual(result["verdict"], "not measured", sign)
            self.assertIn(why, result["reason"], sign)
            self.assertNotIn(SECRET, json.dumps(result))
            self.assertIn("refused", holdouts.clean_step(step)["sign"])            # refused before custody too
            self.assertNotIn("X-Evil", json.dumps(holdouts.clean_step(step)))
        self.assertEqual(_Signed.seen, [])                                        # nothing went out
        fine = dict(SIGNED_STEP, sign=dict(SIGNED_STEP["sign"], prefix="v1 sha256="))
        self.assertEqual(run_scenario(self.url, {"criterion": "R-1-AC-2", "steps": [fine]},
                                      secrets=secrets)["observed"]["status"], 401)  # sent: the server judges it

    def test_FR_DF2_AC_3_a_scenario_the_runner_cannot_send_is_not_measured_and_the_others_still_run(self):
        p = self.compiled_with([SIGNED_STEP])
        write_json(p.holdouts_dir / "R-2-AC-2.json", {"criterion": "R-2-AC-2", "kind": "holdout",
                                                      "steps": ["not a step"]})
        write_json(p.holdouts_dir / "R-3-AC-2.json", {"criterion": "R-3-AC-2", "kind": "holdout", "steps": [
            {"method": "POST", "path": "/refused", "body": {}, "expect_status": 401}]})
        real = roadmod.http_request

        def refusing(method, url, body=None, **kwargs):
            if url.endswith("/refused"):   # what http.client says of a header it will not send
                raise ValueError(f"Invalid header value b'{SECRET}'")
            return real(method, url, body, **kwargs)

        with mock.patch("kernel.operate.http_request", side_effect=refusing):
            report = run_holdouts(p, self.url, kinds=("holdout",), secrets={"CARRIER_WEBHOOK_SECRET": SECRET})
        verdicts = {r["criterion"]: (r["verdict"], r.get("reason", "")) for r in report["results"]}
        self.assertEqual(verdicts["R-1-AC-2"][0], "passed")                      # the others still ran
        self.assertEqual(verdicts["R-2-AC-2"], ("not measured", "not measured: the holdout runner could not send "
                                                                "this scenario (AttributeError)"))
        self.assertEqual(verdicts["R-3-AC-2"], ("not measured", "not measured: the holdout runner could not send "
                                                                "this scenario (ValueError)"))
        self.assertEqual(report["verdict"], "not measured")
        self.assertNotIn(SECRET, json.dumps(report))                              # the error's text is not kept

    def compiled_with(self, steps: list) -> Any:
        p = specced(self)
        compile_project(p)
        write_json(p.holdouts_dir / "R-1-AC-2.json", {"criterion": "R-1-AC-2", "kind": "holdout", "steps": steps})
        return p

    def test_FR_DF2_AC_2_the_holdout_author_is_told_how_to_sign_by_name_and_the_builder_sees_none_of_it(self):
        p = specced(self)
        compile_project(p)
        roads = json.loads(json.dumps(LOCAL_ROADS))
        roads["roads"]["local"]["secrets"] = [{"name": "CARRIER_WEBHOOK_SECRET",
                                               "ref": "env:RIHMA_TEST_CARRIER_SECRET"}]
        write_json(self.factory.paved_roads_path, roads)
        canary = "signed-canary-4411"
        author = scripted(You_write_acceptance_scenarios={"scenarios": [{"criterion": "R-1-AC-2", "steps": [
            dict(SIGNED_STEP, body={"event": canary}, sign={"header": "X-Carrier-Signature", "secret": SECRET})]}, {
            "criterion": "R-4-AC-2", "steps": [dict(SIGNED_STEP, body={"event": canary})]}]})
        with mock.patch.dict(os.environ, {"RIHMA_TEST_CARRIER_SECRET": SECRET}):
            author_holdouts(p, model=author)
        prompt = next(text for role, text in author.calls if role == "holdout_author")
        section = prompt.split("Use exactly these methods and paths:", 1)[1].split("Write one scenario", 1)[0]
        interface = " ".join(section.split())
        self.assertIn('"sign": {"header"', interface)
        self.assertIn("hex HMAC-SHA256", interface)
        self.assertIn("Never write a secret's value in a scenario: name it.", interface)
        self.assertIn("name these secrets: CARRIER_WEBHOOK_SECRET.", interface)
        self.assertNotIn("RIHMA_TEST_CARRIER_SECRET", prompt)                # where it lives is not the author's
        self.assertNotIn(SECRET, prompt)
        kept = json.loads((p.holdouts_dir / "R-1-AC-2.json").read_text(encoding="utf-8"))
        self.assertNotIn(SECRET, json.dumps(kept))                           # the value the author wrote is dropped
        self.assertIn("refused", kept["steps"][0]["sign"])
        signed = json.loads((p.holdouts_dir / "R-4-AC-2.json").read_text(encoding="utf-8"))["steps"][0]["sign"]
        self.assertEqual(signed, {"header": "X-Carrier-Signature", "secret": "CARRIER_WEBHOOK_SECRET",
                                  "algorithm": "hmac-sha256", "prefix": "sha256="})
        builder = envelope(p, p.read("contract.json"), "T-001", base="0" * 40)
        for held in (canary, "X-Carrier-Signature", "CARRIER_WEBHOOK_SECRET", SECRET):
            self.assertNotIn(held, builder)
        self.assertIn("settings name no secret yet", " ".join(holdout_prompt(p.read("spec.json"), []).split()))


class SignedDeliveryTest(DeliveryTestCase):
    maturity = "demo"

    def test_FR_DF2_AC_1_delivery_signs_with_the_secret_its_road_names_and_records_only_names(self):
        roads = json.loads(json.dumps(LOCAL_ROADS))
        roads["roads"]["local"]["secrets"] = [{"name": "ITEMS_SECRET", "ref": "env:RIHMA_TEST_ITEMS_SECRET"}]
        write_json(self.factory.paved_roads_path, roads)
        write_json(self.project.holdouts_dir / "R-1-AC-2.json", {"criterion": "R-1-AC-2", "kind": "holdout", "steps": [
            {"method": "POST", "path": "/items", "body": {"name": "signed drill"}, "expect_status": 201,
             "sign": {"header": "X-Items-Signature", "secret": "ITEMS_SECRET"}}]})
        with mock.patch.dict(os.environ, {"RIHMA_TEST_ITEMS_SECRET": SECRET}):
            out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)                       # on the owner's acceptance
        rel = latest_release(self.project)
        self.assertEqual((rel["holdouts"]["verdict"], rel["holdouts"]["passed"]), ("passed", 2))
        ledger = self.project.path("ledger.jsonl")
        for text in (json.dumps(rel), ledger.read_text(encoding="utf-8") if ledger.exists() else ""):
            self.assertNotIn(SECRET, text)
        secrets = holdouts.environment_secrets(roadmod.PavedRoads.load(self.factory).road("local"))
        self.assertEqual(secrets, {"ITEMS_SECRET": None})                    # the value is gone: not measured
        report = run_holdouts(self.project, roadmod.slot_state(self.project, "demo")["base_url"], secrets=secrets)
        self.assertEqual(report["verdict"], "not measured")
        self.assertIn("cannot read it", next(r for r in report["results"] if r["criterion"] == "R-1-AC-2")["reason"])

    def test_FR_DF2_AC_3_in_delivery_a_sign_with_a_line_break_is_not_measured_and_the_other_scenarios_run(self):
        roads = json.loads(json.dumps(LOCAL_ROADS))
        roads["roads"]["local"]["secrets"] = [{"name": "ITEMS_SECRET", "ref": "env:RIHMA_TEST_ITEMS_SECRET"}]
        write_json(self.factory.paved_roads_path, roads)
        write_json(self.project.holdouts_dir / "R-1-AC-2.json", {"criterion": "R-1-AC-2", "kind": "holdout", "steps": [
            {"method": "POST", "path": "/items", "body": {"name": "signed drill"}, "expect_status": 201,
             "sign": {"header": "X-Items-Signature", "secret": "ITEMS_SECRET", "prefix": "a\r\nX-Evil: 1\r\n"}}]})
        with mock.patch.dict(os.environ, {"RIHMA_TEST_ITEMS_SECRET": SECRET}):
            out = deliver(self.project)
        self.assertEqual(out["state"], "failed", out)
        rel = latest_release(self.project)
        step = next(s for s in rel["steps"] if s["step"].startswith("holdouts"))
        self.assertNotIn("traceback", json.dumps(step["native"]).lower())           # a verdict, not a crash
        self.assertIn("holdout R-1-AC-2 failed at step 1: not measured", step["native"]["why"])
        self.assertIn("no line break", step["native"]["why"])
        self.assertEqual((rel["holdouts"]["verdict"], rel["holdouts"]["scenarios"]), ("not measured", 2))
        self.assertTrue([c for c in step["native"]["ran"] if c != "R-1-AC-2"])      # the other scenario ran
        self.assertNotIn(SECRET, json.dumps(rel))


# -- FR-DF3: a defect that names no requirement -------------------------------------------------------

class UnnamedDefectTest(FactoryTestCase):
    def compiled(self):
        p = specced(self)
        compile_project(p)
        return p

    def defect(self, p, text="Something is wrong when the page opens"):
        card = submit(p, persona="end_user", person="Eeva", text=text)
        return card, triage(p, card["id"], model=None)

    def test_FR_DF3_AC_1_a_defect_naming_no_requirement_asks_which_one_and_never_defaults_to_r1(self):
        p = self.compiled()
        card, tri = self.defect(p, "Something is wrong: the lost items report shows nothing")
        self.assertEqual((tri["class"], tri["requirements"]), ("defect", []))
        canon = Canon(p)
        q = canon.question(tri["needs_requirement"]["question"])
        self.assertTrue(q["text"].startswith(WHICH_REQUIREMENT))
        self.assertEqual(q["options"][-1], NEW_REQUIREMENT)
        self.assertTrue(q["options"][0].startswith("R-3:"))                  # the closest requirement first
        self.assertEqual(canon.get_card(tri["needs_requirement"]["card"])["state"], "open")
        before = p.read("spec.json")
        with self.assertRaises(RequirementUnknown) as refused:
            apply_change(p, card["id"])
        self.assertIn(q["id"], str(refused.exception))
        self.assertEqual(p.read("spec.json"), before)                        # R-1 got no regression criterion
        with self.assertRaises(ValueError):
            _regression(before, {"requirements": []}, "x")
        canon.answer(q["id"], "R-3: the report is the one", person="Aino", persona="business_owner")
        out = apply_change(p, card["id"])
        self.assertEqual((out["class"], out["changed"]), ("defect", ["R-3"]))
        reqs = {r["id"]: r for r in p.read("spec.json")["requirements"]}
        had = {r["id"]: r for r in before["requirements"]}
        self.assertEqual(len(reqs["R-1"]["acceptance"]), len(had["R-1"]["acceptance"]))      # R-1 untouched
        self.assertEqual(reqs["R-3"]["acceptance"][-1]["id"], "R-3-AC-2")
        applied = p.ledger().of_kind("change_applied")[-1]["event"]["payload"]
        self.assertEqual(applied["requirement_from"], "Aino")

    def test_FR_DF3_AC_1_no_requirement_named_files_a_new_requirement_through_the_business_decision(self):
        p = self.compiled()
        card, tri = self.defect(p)
        canon = Canon(p)
        canon.answer(tri["needs_requirement"]["question"], NEW_REQUIREMENT, person="Aino", persona="business_owner")
        with self.assertRaises(PermissionError):                             # a new requirement needs an accept
            apply_change(p, card["id"])
        canon.decide(card["id"], "accept", person="Aino", persona="business_owner", reason="yes, add it")
        analyst = scripted(Amend_a_software_specification={"add": [{
            "statement": "The page opens without an error.", "acceptance": [
                {"given": "-", "when": "GET /items", "then": "200", "kind": "test"}]}], "modify": [], "withdraw": []})
        out = apply_change(p, card["id"], model=analyst)
        self.assertEqual((out["class"], out["changed"]), ("new_requirement", ["R-5"]))
        r5 = p.read("spec.json")["requirements"][-1]
        self.assertEqual((r5["provenance"], r5["decided_by"]), ("customer-confirmed", "Aino"))
        # accepted while the question is open: the requirement the accept names, else a new one
        card2, tri2 = self.defect(p, "Something is wrong when I lend a drill")
        canon.decide(card2["id"], "accept", person="Aino", persona="business_owner", reason="it breaks R-2")
        self.assertEqual(apply_change(p, card2["id"])["changed"], ["R-2"])

    def test_FR_DF3_AC_1_a_ruled_defect_takes_its_rulings_requirement_without_asking(self):
        from kernel.change import ruling_defect_text

        p = self.compiled()
        canon = Canon(p)
        ruling = canon.card("holdout_ruling", "Release 1: 1 holdout(s) failed", refs={
            "release": 1, "criteria": ["R-1-AC-2"], "requirements": ["R-1"]}, payload={"failing": []})
        canon.decide(ruling["id"], "product_defect", person="Aino", persona="business_owner", reason="the product")
        card = submit(p, persona="business_owner", person="Aino", text=ruling_defect_text(canon.get_card(ruling["id"])),
                      kind_hint="defect")
        tri = triage(p, card["id"], model=None)
        self.assertEqual((tri["requirements"], tri.get("needs_requirement")), (["R-1"], None))
        self.assertFalse([q for q in canon.questions() if q["text"].startswith(WHICH_REQUIREMENT)])


# -- FR-DF4: profile proposals on word boundaries ----------------------------------------------------

class ProfileWordsTest(FactoryTestCase):
    def test_FR_DF4_AC_1_keywords_match_on_word_boundaries_and_this_readme_is_uncertain(self):
        trainees = propose_profile("A portal where our trainees book courses and see their html certificates")
        self.assertEqual(trainees["scores"]["ml_pipeline"], 0, trainees)        # not 'train' in 'trainees'
        self.assertEqual(trainees["profile"], "web_service")
        for keyword, text, found in (("train", "trainees", False), ("train", "train it", True),
                                     ("ml", "an html page", False), ("model", "two models", True),
                                     ("app store", "the app stores", True), ("palvelu*", "palvelun tila", True),
                                     ("orchestrat*", "orchestration", True), ("data", "database", False)):
            self.assertEqual(bool(keyword_pattern(keyword).search(text)), found, (keyword, text))
        self.assertEqual(propose_profile("Run an agent workflow that orchestrates tools")["basis"],
                         ["agent", "orchestrat", "workflow"])                 # a stem reads without its mark
        readme = (ROOT / "tests" / "fixtures" / "readme_many_kinds.txt").read_text(encoding="utf-8")   # mixed signals
        own = propose_profile(readme)
        self.assertEqual(own["confidence"], "uncertain", own)
        self.assertNotEqual(own["profile"], "ml_pipeline", own)               # the dogfood misfire
        self.assertGreaterEqual(len(own["candidates"]), 2)
        self.assertEqual(own["candidates"][0], own["profile"])

    def test_FR_DF4_AC_2_intake_asks_a_person_with_the_top_candidates_and_their_answer_shapes_the_spec(self):
        p = self.new(mode="assume")
        out = intake(p, "An app with an agent that answers questions on the team's page", model=model(),
                     requested_by="Aino")
        basis = p.ledger().of_kind("profile_chosen")[-1]["event"]["payload"]["basis"]
        self.assertEqual((basis["by"], basis["confidence"]), ("rule", "uncertain"))
        self.assertGreaterEqual(len(basis["candidates"]), 2)
        canon = Canon(p)
        q = next(q for q in canon.questions() if q["text"] == PROFILE_QUESTION)
        self.assertIn(q["card"], out["asked"])                              # asked even in assume mode
        self.assertIn("Agent or assistant (agentic_workflow)", q["options"])
        canon.answer(q["id"], "Agent or assistant (agentic_workflow)", person="Aino", persona="product_owner")
        m = model()
        make_spec(p, model=m)
        self.assertEqual(p.meta["profile"], "agentic_workflow")
        chosen = p.ledger().of_kind("profile_chosen")[-1]["event"]["payload"]
        self.assertEqual(chosen["basis"], {"by": "Aino", "question": q["id"]})
        prompt = next(text for _, text in m.calls if SPEC_PROMPT in text)
        self.assertIn("This is a **Agent or assistant** project", prompt)
        for title, text in (("Loans", IDEA), ("Page", "A page where the team tracks its loans")):
            other = self.new(mode="assume", title=title)                       # no keyword, or one profile's only
            intake(other, text, model=model(), requested_by="Aino")
            self.assertFalse([q for q in Canon(other).questions() if q["text"] == PROFILE_QUESTION], text)
            self.assertEqual(other.ledger().of_kind("profile_chosen")[-1]["event"]["payload"]["basis"]["confidence"],
                             "uncertain")
            self.assertEqual(other.meta["profile"], "web_service")

    def test_FR_DF4_AC_3_the_profile_question_holds_the_spec_in_every_mode_until_a_person_answers(self):
        from kernel import pipeline

        for mode in ("assume", "mixed", "socratic"):
            p = self.new(mode=mode, title=f"Unsure {mode}")
            intake(p, "An app with an agent that answers questions on the team's page", model=model(),
                   requested_by="Aino")
            canon = Canon(p)
            q = next(q for q in canon.questions() if q["text"] == PROFILE_QUESTION)
            self.assertTrue(q["blocking"], mode)
            for other in canon.questions("open"):          # the panel's own blocking questions, answered
                if other["id"] != q["id"] and other["blocking"]:
                    canon.answer(other["id"], "yes", person="Aino", persona="business_owner")
            waiting = pipeline._shape(p, model(), [])
            self.assertEqual((waiting["state"], waiting["stage"], waiting["waiting_on"]),
                             ("waiting", 2, [q["card"]]), mode)
            self.assertFalse(p.path("spec.json").exists(), mode)      # not shaped on the rule's guess
            canon.answer(q["id"], "Agent or assistant (agentic_workflow)", person="Aino", persona="product_owner")
            self.assertEqual(pipeline._shape(p, model(), []), pipeline.AGAIN, mode)
            self.assertTrue(p.path("spec.json").exists(), mode)
            self.assertEqual(p.meta["profile"], "agentic_workflow", mode)

    def test_FR_DF4_AC_3_an_answer_after_the_spec_never_changes_the_profile_at_a_later_spec(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)                                   # a question an earlier version left open, not blocking
        q = canon.add_question(PROFILE_QUESTION, "business", blocking=False,
                               options=["Web app or service (web_service)", "Agent or assistant (agentic_workflow)"])
        make_spec(p, model=model())
        canon.answer(q["id"], "Agent or assistant (agentic_workflow)", person="Aino", persona="product_owner")
        m = model()
        make_spec(p, model=m, feedback="Aino rejected the previous plan: too broad")   # a plan redo
        self.assertEqual(p.meta["profile"], "web_service")
        self.assertEqual([e["event"]["payload"]["profile"] for e in p.ledger().of_kind("profile_chosen")],
                         ["web_service"])
        late = p.ledger().of_kind("profile_answer_late")
        self.assertEqual([e["event"]["payload"] for e in late],
                         [{"question": q["id"], "by": "Aino", "named": "agentic_workflow", "kept": "web_service"}])
        prompt = next(text for _, text in m.calls if SPEC_PROMPT in text)
        self.assertIn("This is a **Web app or service** project", prompt)
        make_spec(p, model=model())
        self.assertEqual(len(p.ledger().of_kind("profile_answer_late")), 1)            # recorded once


# -- FR-DF5: the adoption baseline's per-suite limit -------------------------------------------------

class SuiteTimeoutTest(FactoryTestCase):
    def test_FR_DF5_AC_1_a_suite_past_its_limit_is_not_measured_timed_out_and_adoption_goes_on(self):
        self.assertEqual(SUITE_TIMEOUT, 300)
        pidfile = self.tmp / "helper.pid"
        test = leaking_suite(self.tmp / "hang", pidfile, hang=True)
        started = time.monotonic()
        run = run_baseline(self.tmp / "hang", test, timeout=3)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual((run["verdict"], run["limit_s"]), ("not measured", 3))
        self.assertTrue(run["reason"].startswith("not measured: timed out"), run)
        src = make_repo(self.tmp / "slow", {
            "README.md": "# Slow\n\nA small service.\n",
            "tests/test_slow.py": "import time\nimport unittest\n\n\nclass Slow(unittest.TestCase):\n"
                                  "    def test_waits(self):\n        time.sleep(60)\n"})
        started = time.monotonic()
        p = adopt(self.factory, "Slow", source=str(src), intent="maintain", person="Aino", persona="developer",
                  which=lambda name: None, timeout=120, suite_timeout=3)
        self.assertLess(time.monotonic() - started, 50, "the git timeout, not the suite's, bounded the run")
        baseline = p.read("baseline.json")
        self.assertEqual(baseline["verdict"], "not measured")
        self.assertIn("not measured: timed out: the suite did not finish in 3s", baseline["reason"])
        self.assertEqual((p.meta.get("adoption"), p.meta["stage"]), (None, 5))     # adopted, not failed


if __name__ == "__main__":
    unittest.main()
