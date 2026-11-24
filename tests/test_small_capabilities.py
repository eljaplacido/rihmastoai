"""Small capabilities end to end (FR-SC1 to FR-SC6; docs/guides/small-capabilities.md).

The capability here is real: a need for a nightly digest goes through intake, spec and compile on the
automation profile's capability template, a scripted builder cell writes its job and declaration, the
kernel's gate runs its suite (the road's capability checks included), and delivery lands it on the local
preview road. Its faces are then reached as a site and a person reach them: MCP over stdio and Streamable
HTTP, the OpenAI-compatible chat (also through the capability gateway), the website embed and HTTP, each
behind the pack guard; a verified webhook, a relay event and a schedule run it, and its result goes out as
an event the factory's own doorbell accepts. Every process listens on 127.0.0.1 and is stopped afterwards.
"""

import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, no_findings, script  # noqa: E402

from gateway.config import parse_config  # noqa: E402
from gateway.packs import agent_workloads, workloads_from_pack  # noqa: E402
from gateway.packs import check as gateway_check  # noqa: E402
from gateway.router import Gateway  # noqa: E402
from kernel import bundle, hooks, relay, scaffold, signals  # noqa: E402
from kernel import faces as kfaces  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.assistant import ask, ui_map  # noqa: E402
from kernel.assistant_rules import CONTROL_PAGES  # noqa: E402
from kernel.cli import main as cli  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.deliver import deliver  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.gate import run_suite  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import GIT_ID, PROTECTED, Lanes, _git  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.packs import build_pack, content_sha256  # noqa: E402
from kernel.profiles import PROFILES, propose_profile  # noqa: E402
from kernel.redteam import static  # noqa: E402
from kernel.runtime_decl import for_pack, validate  # noqa: E402
from kernel.spec import make_spec, spec_prompt  # noqa: E402
from kernel.store import Factory, FixedClock, write_text  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
NEED = ("Every night, count yesterday's failed shipment deliveries the stock system reports, as a scheduled job "
        "with no screens. Make it reachable over MCP.")
SPEC_PROMPT = "You turn a brief into a software specification"
KEY = "test-only-trigger-key-41c9"            # a test secret, never a real one
RESULTS_KEY = "test-only-results-key-77ad"   # likewise
TOKEN = "test-only-faces-token-0b52"         # likewise
SHIPMENTS = [{"id": "S1", "state": "failed"}, {"id": "S2", "state": "delivered"}, {"id": "S3", "state": "failed"}]
DIGEST = "sha256:" + "cd" * 32
SPEC = {
    "title": "Shipment failure digest", "summary": "Counts failed shipments for operations, every night.",
    "users": ["operations"],
    "requirements": [{"statement": "A run counts the failed shipments it is given.", "sources": ["request"],
                      "priority": "must",
                      "acceptance": [{"given": "three shipments, two of them failed",
                                      "when": "POST /capability/run with the shipments",
                                      "then": "the run's result counts 2 failures", "kind": "test"},
                                     {"given": "three shipments, two of them failed",
                                      "when": "the count_failures tool is called with them", "then": "it answers 2",
                                      "kind": "test"}]}],
    "out_of_scope": ["screens"],
}
RUNTIME = {
    "format": "rihma.runtime/1", "name": "shipment-digest", "kind": "automation",
    "summary": "Counts failed shipment deliveries for operations.",
    "trigger": {"kind": "webhook", "source": "stock", "secret": "DIGEST_HOOK_SECRET"},
    "faces": ["mcp", "openai", "http"],
    "tools": [{"name": "count_failures", "description": "How many of the given shipments failed.", "effect": "read",
               "input": {"type": "object", "properties": {"shipments": {"type": "array"}}, "required": ["shipments"]}}],
    "model_roles": [{"role": "summariser", "workload": "digest-summary", "class": "batch", "model": "small-local"}],
    "integrations": [{"system": "stock-system", "via": "webhook", "purpose": "it reports each delivery's state",
                      "writes": False, "secrets": ["DIGEST_HOOK_SECRET"]}],
    "secrets": [{"name": "DIGEST_HOOK_SECRET", "ref": "env:DIGEST_HOOK_SECRET"}], "timeout_seconds": 30,
}
JOB = '''"""The shipment digest's work."""


def count_failures(shipments):
    return sum(1 for s in shipments or [] if isinstance(s, dict) and s.get("state") == "failed")


def run(trigger):
    data = trigger.get("input")
    shipments = data.get("shipments") if isinstance(data, dict) else None
    return {"failures": count_failures(shipments), "trigger": trigger.get("kind")}


def chat(messages):
    return "I count failed shipments. You asked: " + str(messages[-1].get("content", ""))[:80]
'''
CRITERIA_TESTS = '''import unittest

import app.job
import app.routes  # noqa: F401
from app.server import handle

SHIPMENTS = [{"id": "S1", "state": "failed"}, {"id": "S2", "state": "delivered"}, {"id": "S3", "state": "failed"}]


class DigestTest(unittest.TestCase):
    def test_R_1_AC_1_a_run_counts_the_failed_shipments(self):
        status, body, _ = handle("POST", "/capability/run", {"shipments": SHIPMENTS})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["failures"], 2)

    def test_R_1_AC_2_the_count_failures_tool_answers(self):
        self.assertEqual(app.job.count_failures(SHIPMENTS), 2)
'''


def capability_cell(lane_path, prompt):
    """A builder cell that writes the digest: its job, its declaration and a test per criterion."""
    write_text(Path(lane_path, "app", "job.py"), JOB)
    write_text(Path(lane_path, "app", "runtime.json"), json.dumps(RUNTIME, indent=2) + "\n")
    write_text(Path(lane_path, "tests", "test_digest.py"), CRITERIA_TESTS)
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 6, "model": "fake-builder",
            "output": "done"}


def scripted() -> FakeModel:
    def answer(prompt: str, role: str) -> str:
        if SPEC_PROMPT in prompt:
            return "```json\n" + json.dumps(SPEC) + "\n```"
        return script(prompt, role)
    return FakeModel(answer)


_BUILT: dict = {}


def built_capability() -> tuple:
    """One capability, built through the gate and delivered on the local preview road, once per run."""
    if not _BUILT:
        root = Path(tempfile.mkdtemp(prefix="gf-capability-"))
        atexit.register(roadmod.rmtree, root)
        factory = Factory(root / "home", clock=FixedClock())
        p = factory.new_project("Shipment failure digest", mode="assume", maturity="explore", profile="automation")
        intake(p, NEED, model=scripted(), requested_by="Aino")
        make_spec(p, model=scripted())
        compile_project(p)
        out = build_task(p, "T-001", lanes=Lanes(root / "lanes", size=1), cell_runner=capability_cell,
                         verifier_runner=no_findings)
        if out["status"] != "merged":
            raise AssertionError(f"the capability did not build: {out}")
        delivered = deliver(p)
        roadmod.stop_all(p)
        if delivered["state"] != "done":
            raise AssertionError(f"the capability was not delivered: {delivered}")
        _BUILT.update(root=root, home=root / "home", pid=p.pid, gate=out)
    return _BUILT["home"], _BUILT["pid"]


def call(method: str, url: str, body=None, headers: dict | None = None, raw: bytes | None = None) -> tuple:
    """(status, parsed JSON or text, response headers) of one request to a loopback server."""
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers={
        **({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=30) as resp:
            status, text, got = resp.status, resp.read().decode("utf-8"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        status, text, got = exc.code, exc.read().decode("utf-8"), dict(exc.headers)
        exc.close()
    try:
        return status, json.loads(text), got
    except ValueError:
        return status, text, got


def clean_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("RIHMA_") and k not in ("DATA_DIR", "PORT", "HOST", "APP_VERSION", "TRAFFIC_LOG",
                                                       "DIGEST_HOOK_SECRET")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", **{k: str(v) for k, v in extra.items()})
    return env


def signed(body: bytes, key: str = KEY, msg_id: str = "msg-1", stamp: int | None = None) -> dict:
    """Standard Webhooks headers for ``body``, made by the factory's own signer (kernel/hooks.py)."""
    stamp = int(time.time()) if stamp is None else stamp
    return {"Content-Type": "application/json", "webhook-id": msg_id, "webhook-timestamp": str(stamp),
            "webhook-signature": hooks.sign_standard(hooks.secret_bytes(key), msg_id, stamp, body)}


def fresh(doc: dict, **delta) -> dict:
    """A status as issued, expiring a day from the real now (the fixture's clock is fixed)."""
    return dict(doc, expires_at=(datetime.now(UTC) + timedelta(**(delta or {"days": 1}))).isoformat())


class CapabilityCase(unittest.TestCase):
    """A copy of the delivered capability per test; every process it starts is stopped afterwards."""

    def setUp(self):
        home, pid = built_capability()
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-cap-test-"))
        self.addCleanup(roadmod.rmtree, self.tmp)
        shutil.copytree(home, self.tmp / "home")
        self.home = self.tmp / "home"
        self.factory = Factory(self.home, clock=FixedClock())
        self.project = self.factory.project(pid)
        self.release = self.project.read("releases/1.json")
        self.checkout = self.project.dir / self.release["artifacts"]["local-preview"]["checkout"]
        self.addCleanup(roadmod.stop_started)

    def product(self, name: str = "cap", runtime: dict | None = None) -> Path:
        """A copy of the delivered product's files, its declaration replaced when ``runtime`` is given."""
        root = self.tmp / name
        shutil.copytree(self.checkout, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        if runtime is not None:
            write_text(root / "app" / "runtime.json", json.dumps(runtime, indent=2) + "\n")
        return root

    def data(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="cap-data-", dir=self.tmp))

    def start(self, root: Path, *argv: str, **env) -> str:
        """factory/faces.py from ``root`` on a free loopback port; its base URL, from its listening line."""
        log = open(self.tmp / f"faces-{len(os.listdir(self.tmp))}.log", "w", encoding="utf-8")
        self.addCleanup(log.close)
        env.setdefault("DATA_DIR", self.data())
        proc = subprocess.Popen([sys.executable, "factory/faces.py", "--port", "0", *argv], cwd=root,
                                env=clean_env(**env), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=log, text=True)
        self.addCleanup(roadmod._terminate, proc)
        self.addCleanup(proc.stdout.close)
        line = proc.stdout.readline()
        if not line:
            raise AssertionError("the faces did not start: " + Path(log.name).read_text(encoding="utf-8")[-1500:])
        return json.loads(line)["listening"]

    def stdio(self, root: Path, messages: list, argv: tuple = ("--face", "mcp", "--stdio"), **env) -> list:
        """MCP over stdio from ``root``: every line the faces wrote to stdout, parsed."""
        lines = "\n".join(m if isinstance(m, str) else json.dumps(m) for m in messages) + "\n"
        proc = subprocess.run([sys.executable, "factory/faces.py", *argv], cwd=root,
                              env=clean_env(DATA_DIR=self.data(), **env), input=lines, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in proc.stdout.splitlines()]


# -- FR-SC1: the automation profile and its template ---------------------------------------------------

class TemplateTest(FactoryTestCase):
    def tree(self, name: str, **changes: str) -> Path:
        root = self.tmp / name
        for rel, text in {**scaffold.files("Digest", "digest-a1b2c3", "explore", template="capability"),
                          **changes}.items():
            write_text(root / rel, text)
        return root

    def test_FR_SC1_AC_1_a_scheduled_job_gets_the_automation_profile_and_its_capability_template(self):
        proposal = propose_profile(NEED)
        self.assertEqual((proposal["profile"], proposal["confidence"]), ("automation", "clear"), proposal)
        profile = PROFILES["automation"]
        self.assertEqual((profile["deliverable"], profile["template"], profile["status"], profile["screens"]),
                         ("capability_pack", "capability", "ready", False))
        p = self.new(mode="assume")
        intake(p, NEED, model=scripted(), requested_by="Aino")
        self.assertEqual(p.meta["profile"], "automation")
        self.assertIn(profile["spec_guidance"], spec_prompt(p))
        files = scaffold.files("Digest", "digest-a1b2c3", "explore", template="capability")
        for name in ("app/runtime.json", "app/job.py", "factory/faces.py", "factory/faces_http.py",
                     "factory/runtime_decl.py", "factory/pack_guard.py"):
            self.assertIn(name, files)
        self.assertEqual(validate(json.loads(files["app/runtime.json"])), [])
        self.assertIn("import factory.faces_http", files["app/routes.py"])
        self.assertIn("COPY factory/faces.py factory/faces_http.py factory/runtime_decl.py ./factory/",
                      files["Dockerfile"])
        self.assertTrue(files["Dockerfile"].rstrip().endswith('CMD ["python3", "factory/pack_guard.py"]'))
        self.assertLessEqual({"factory/faces.py", "factory/faces_http.py", "factory/runtime_decl.py"},
                             set(bundle.RUNTIME_FILES))                       # the pack pins them
        self.assertIn("factory/", PROTECTED)                                    # no builder cell may change them
        self.assertNotIn("app/runtime.json", scaffold.files("Loans", "loans-a1", "explore"))   # the web template
        root = self.tree("template")
        run = run_suite(root)
        self.assertEqual(run["exit"], 0, run)
        ours = {n for n in run["tests"] if n.startswith("test_ROAD_CAPABILITY_")}
        self.assertEqual(len(ours), 4, run["tests"])
        report = static.scan([root], which=lambda tool: None)                   # Rihmasto's own red team (D-0014)
        rootless = re.search(r"(?m)^USER\s+(?!root\b|0\b)", files["Dockerfile"])   # as the web template's test
        self.assertEqual([(f.rule, f.path) for f in report.findings], [] if rootless else [("RT-DOCKER-ROOT", "Dockerfile")])

    def test_FR_SC2_AC_3_a_word_like_desk_or_risk_is_a_name_and_not_a_live_token(self):
        for title, pid in (("Help desk triage", "help-desk-triage-a1b2c3"), ("Risk digest", "risk-digest-d4e5f6"),
                           ("Task sweep", "task-sweep-0a1b2c")):
            files = scaffold.files(title, pid, "explore", template="capability")
            self.assertEqual(validate(json.loads(files["app/runtime.json"])), [], title)
        root = self.tree("desk", **{"app/runtime.json": scaffold.files(
            "Help desk triage", "help-desk-triage-a1b2c3", "explore", template="capability")["app/runtime.json"]})
        run = run_suite(root)
        self.assertEqual(run["exit"], 0, run)                                  # the road's checks pass
        worded = dict(RUNTIME, name="desk-assistant", summary="Scores risk-assessment results for the help desk.")
        self.assertEqual(validate(worded), [])
        token = "sk-" + "a1b2c3d4e5f6g7h8"
        for summary in (token, "uses " + token, "key=" + token):              # a token that starts a word
            self.assertTrue(any(p.startswith("/summary: holds what looks like a live token")
                                for p in validate(dict(RUNTIME, summary=summary))), summary)

    def test_FR_SC1_AC_3_the_road_checks_fail_a_capability_that_breaks_its_declaration_its_job_or_its_faces(self):
        broken_decl = self.tree("decl", **{"app/runtime.json": json.dumps(dict(RUNTIME, faces=["fax"])) + "\n"})
        run = run_suite(broken_decl)
        self.assertEqual(run["tests"]["test_ROAD_CAPABILITY_the_runtime_declaration_is_valid"], "FAIL")
        no_tool = self.tree("tool", **{"app/runtime.json": json.dumps(RUNTIME) + "\n"})
        run = run_suite(no_tool)
        self.assertEqual(run["tests"]["test_ROAD_CAPABILITY_the_job_runs_and_has_a_function_for_every_declared_tool"],
                         "FAIL")
        no_faces = self.tree("faces", **{"app/routes.py": "from app.server import load_data, route, save_data\n"})
        run = run_suite(no_faces)
        self.assertEqual(run["tests"]["test_ROAD_CAPABILITY_every_declared_face_answers_and_no_other"], "FAIL")
        self.assertEqual(run["exit"], 1)


class DeliveredTest(CapabilityCase):
    def test_FR_SC1_AC_2_an_automation_is_built_through_the_gate_and_delivered_on_the_local_road(self):
        gate = _BUILT["gate"]
        self.assertEqual(gate["status"], "merged", gate)
        tasks = self.project.read("tasks.json")
        verdicts = [r["event"]["payload"]["verdict"] for r in self.project.ledger().of_kind("gate")]
        self.assertEqual((tasks["T-001"]["status"], verdicts[-1]), ("merged", "passed"))
        self.assertEqual((self.release["state"], self.release["maturity"]), ("done", "explore"))
        self.assertEqual(_git(self.checkout, "show", "HEAD:app/runtime.json").count("shipment-digest"), 1)
        out = deliver(self.project, new=True)                      # the preview runs it as the road runs it
        self.addCleanup(roadmod.stop_all, self.project)
        self.assertEqual(out["state"], "done", out)
        base = roadmod.slot_state(self.project, "preview")["base_url"]
        status, body, _ = call("POST", base + "/capability/run", {"shipments": SHIPMENTS})
        self.assertEqual((status, body["result"]["failures"], body["state"]), (200, 2, "succeeded"))
        status, body, _ = call("POST", base + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual([t["name"] for t in body["result"]["tools"]],
                         ["capability_describe", "capability_runs", "count_failures"])

    def test_FR_SC2_AC_2_the_pack_declares_the_runtime_secrets_by_name_and_a_changed_declaration_is_a_new_version(self):
        pack = build_pack(self.project)
        runtime = pack["runtime"]
        self.assertTrue(pack["acceptance"]["valid"], pack["acceptance"])
        self.assertEqual((runtime["declared"], runtime["name"], runtime["faces"]),
                         (True, "shipment-digest", ["mcp", "openai", "http"]))
        self.assertEqual(runtime["trigger"], RUNTIME["trigger"])
        self.assertEqual(runtime["workloads"], [{"name": "digest-summary", "class": "batch", "data_class": "internal",
                                                 "model": "small-local"}])
        self.assertEqual((runtime["secrets"], runtime["agent"]), (["DIGEST_HOOK_SECRET"],
                                                                  {"model": "shipment-digest", "data_class": "internal"}))
        self.assertNotIn("env:DIGEST_HOOK_SECRET", json.dumps(pack))           # names only, never a reference or value
        self.assertEqual(runtime, for_pack(RUNTIME))                            # deterministic
        self.assertEqual(build_pack(self.project)["version"], pack["version"])  # the same content keeps its version
        changed = json.loads(json.dumps(pack))
        changed["runtime"] = for_pack(dict(RUNTIME, faces=["mcp"]))
        self.assertNotEqual(content_sha256(changed), pack["content_sha256"])   # behaviour changed: a new version
        work = self.tmp / "w"
        _git(self.tmp, "clone", "-q", str(self.project.path("repo.git")), "w")
        (work / "app" / "runtime.json").unlink()
        _git(work, *GIT_ID, "commit", "-q", "-am", "no declaration")
        bare = _git(work, "rev-parse", "HEAD")
        write_text(work / "app" / "runtime.json", json.dumps(dict(RUNTIME, secrets=[
            {"name": "DIGEST_HOOK_SECRET", "ref": "whsec_dGhpcy1pcy1ub3QtYS1rZXk="}])) + "\n")
        _git(work, "add", "-A")
        _git(work, *GIT_ID, "commit", "-q", "-m", "a value instead of a reference")
        _git(work, "push", "-q", "origin", "HEAD:refs/heads/scratch")
        self.assertEqual(kfaces.pack_runtime(self.project, bare), kfaces.NOT_DECLARED)   # a web-service product
        bad = kfaces.pack_runtime(self.project, _git(work, "rev-parse", "HEAD"))
        self.assertFalse(bad["declared"])
        self.assertTrue(any(p.startswith("/secrets/0/ref:") for p in bad["problems"]), bad)


# -- FR-SC2: the runtime declaration, judged with no model --------------------------------------------

class DeclarationTest(unittest.TestCase):
    def test_FR_SC2_AC_1_every_mistake_in_a_declaration_names_its_json_path(self):
        self.assertEqual(validate(RUNTIME), [])
        cases = {
            "/: unknown keys ['colour']": dict(RUNTIME, colour="teal"),
            "/trigger/secret:": dict(RUNTIME, trigger={"kind": "webhook", "secret": "NOT_DECLARED"}),
            "/trigger/every_minutes:": dict(RUNTIME, trigger={"kind": "schedule", "every_minutes": 0}),
            "/trigger/types:": dict(RUNTIME, trigger={"kind": "event", "types": ["card.*"], "secret": "DIGEST_HOOK_SECRET"}),
            "/secrets/0/ref:": dict(RUNTIME, secrets=[{"name": "DIGEST_HOOK_SECRET", "ref": "hunter2"}]),
            "/tools/0/name: a capability offers no tool that may": dict(RUNTIME, tools=[
                dict(RUNTIME["tools"][0], name="approve_refund")]),
            "/model_roles/0/class:": dict(RUNTIME, model_roles=[dict(RUNTIME["model_roles"][0], **{"class": "fast"})]),
            "/embed/origins:": dict(RUNTIME, faces=["embed"]),
            "/integrations/0/secrets:": dict(RUNTIME, integrations=[dict(RUNTIME["integrations"][0], secrets=["X_KEY"])]),
            "/faces:": dict(RUNTIME, faces=["mcp", "mcp"]),
            "/summary: holds what looks like a live token": dict(RUNTIME, summary="uses sk-" + "a1b2c3d4e5f6g7h8"),
        }
        for expected, decl in cases.items():
            problems = validate(decl)
            self.assertTrue(any(p.startswith(expected) for p in problems), (expected, problems))
        self.assertEqual(validate([]), ["/: expected a JSON object"])
        self.assertEqual(for_pack(dict(RUNTIME, faces=["fax"]))["declared"], False)
        self.assertEqual(for_pack(RUNTIME)["declaration_sha256"], for_pack(json.loads(json.dumps(RUNTIME)))[
            "declaration_sha256"])


# -- FR-SC3: one image, several faces, each behind the pack guard -------------------------------------

class FacesTest(CapabilityCase):
    def test_FR_SC3_AC_1_mcp_over_stdio_and_streamable_http_offers_the_reads_and_its_own_tools_only(self):
        root = self.product()
        answers = self.stdio(root, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "count_failures", "arguments": {"shipments": SHIPMENTS}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "deploy", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
             "params": {"name": "count_failures", "arguments": {"shipments": "all"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "server/discover"}, "not json",
            {"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "capability_runs", "arguments": {}}}])
        by_id = {a.get("id"): a for a in answers}
        self.assertEqual(len(answers), 9)                                      # the notification has no answer
        self.assertEqual((by_id[1]["result"]["protocolVersion"], by_id[1]["result"]["serverInfo"]["name"]),
                         ("2025-06-18", "shipment-digest"))
        self.assertEqual(by_id[7]["result"]["protocolVersion"], "2025-11-25")
        listed = by_id[2]["result"]
        self.assertEqual([t["name"] for t in listed["tools"]], ["capability_describe", "capability_runs", "count_failures"])
        self.assertEqual(listed["_meta"]["rihmasto/pack"], "no pack mounted")
        self.assertEqual(by_id[3]["result"]["structuredContent"]["result"], 2)
        self.assertEqual(by_id[4]["error"]["code"], -32602)                    # not its own tool: refused
        self.assertTrue(by_id[5]["result"]["isError"])                          # a wrong argument type
        self.assertEqual(by_id[6]["error"]["code"], -32601)
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertEqual(by_id[8]["result"]["structuredContent"]["runs"][0]["trigger"]["tool"], "count_failures")
        base = self.start(root, RIHMA_FACES_TOKEN=TOKEN)
        auth = {"Authorization": "Bearer " + TOKEN}
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        self.assertEqual(call("POST", base + "/mcp", init)[0], 401)              # the token, when one is set
        status, body, got = call("POST", base + "/mcp", init, auth)
        self.assertEqual((status, body["result"]["serverInfo"]["name"]), (200, "shipment-digest"))
        self.assertEqual((got.get("Cache-Control"), got.get("X-Content-Type-Options")), ("no-store", "nosniff"))
        self.assertEqual(call("POST", base + "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"},
                              auth)[:2], (202, ""))
        self.assertEqual(call("GET", base + "/mcp", None, auth)[0], 405)        # no stream is offered
        self.assertEqual(call("POST", base + "/mcp", init, {**auth, "MCP-Protocol-Version": "1999-01-01"})[0], 400)
        self.assertEqual(call("POST", base + "/mcp", init, {**auth, "Origin": "https://evil.example"})[0], 403)

    def test_FR_SC3_AC_2_the_openai_face_answers_as_the_capability_and_the_gateway_routes_to_it(self):
        base = self.start(self.product(), RIHMA_FACES_TOKEN=TOKEN)
        auth = {"Authorization": "Bearer " + TOKEN}
        status, body, _ = call("GET", base + "/v1/models", None, auth)
        self.assertEqual([m["id"] for m in body["data"]], ["shipment-digest"])
        ask_it = {"model": "shipment-digest", "messages": [{"role": "user", "content": "How many failed?"}]}
        status, body, _ = call("POST", base + "/v1/chat/completions", ask_it, auth)
        self.assertEqual(status, 200, body)
        self.assertIn("You asked: How many failed?", body["choices"][0]["message"]["content"])
        self.assertEqual(call("POST", base + "/v1/chat/completions", dict(ask_it, model="gpt-x"), auth)[0], 404)
        pack = build_pack(self.project)
        workloads = {**workloads_from_pack(pack, "digest"), **agent_workloads(pack, "digest")}
        config = parse_config({"site": {"mode": "air-gapped"}, "upstreams": {"digest": {
            "url": base + "/v1", "api_key_env": "DIGEST_FACES_TOKEN"}}, "workloads": workloads,
            "audit": {"path": "audit.jsonl"}}, self.tmp)
        self.assertEqual(gateway_check(config, pack), [])                       # --check-pack passes
        reply = Gateway(config, env={"DIGEST_FACES_TOKEN": TOKEN}).complete(ask_it)
        self.assertEqual(reply.status, 200, reply.body)
        self.assertEqual(reply.body["gateway"]["workload"], "shipment-digest")
        self.assertIn("You asked: How many failed?", reply.body["choices"][0]["message"]["content"])
        refused = Gateway(config, env={"DIGEST_FACES_TOKEN": "wrong"}).complete(ask_it)
        self.assertEqual((refused.status, refused.body["error"]["attempts"][0]["outcome"]), (503, "http 401"))
        drifted = parse_config({"upstreams": {"digest": {"url": base + "/v1"}}, "workloads": {"shipment-digest": {
            "class": "interactive", "ladder": {"L1": [{"upstream": "digest", "model": "another-model"}]}}}}, self.tmp)
        self.assertTrue(any("not the capability itself" in p for p in gateway_check(drifted, pack)))

    def test_FR_SC3_AC_2_a_model_role_reaches_the_gateway_workload_its_declaration_names(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        from gateway.server import make_server

        asked = []

        class Model(BaseHTTPRequestHandler):            # a local OpenAI-compatible model server
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                asked.append(body["model"])
                data = json.dumps({"choices": [{"index": 0, "message": {"role": "assistant",
                                                                         "content": "2 failed overnight"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                return

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Model)
        pack = build_pack(self.project)
        config = parse_config({"upstreams": {"local": {"url": f"http://127.0.0.1:{upstream.server_address[1]}/v1"}},
                               "workloads": workloads_from_pack(pack, "local"), "audit": {"path": "audit.jsonl"}},
                              self.tmp)
        gateway = make_server(Gateway(config), 0)
        for srv in (upstream, gateway):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
        root = self.product("agentic")
        write_text(root / "app" / "job.py", JOB + '''

def chat(messages):
    from factory.faces import model
    return "Summary: " + model("summariser", messages)
''')
        base = self.start(root, RIHMA_GATEWAY_URL=f"http://127.0.0.1:{gateway.server_address[1]}/v1")
        status, body, _ = call("POST", base + "/v1/chat/completions",
                               {"model": "shipment-digest", "messages": [{"role": "user", "content": "Summarise"}]})
        self.assertEqual((status, body["choices"][0]["message"]["content"]), (200, "Summary: 2 failed overnight"))
        self.assertEqual(asked, ["small-local"])                                  # the model the pack was accepted with
        audit = [json.loads(line) for line in (self.tmp / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(audit[-1]["event"]["payload"]["workload"], "digest-summary")

    def test_FR_SC3_AC_3_the_embed_face_answers_only_its_declared_origins_and_an_undeclared_face_is_404(self):
        site = "http://localhost:8000"
        base = self.start(self.product(runtime=dict(RUNTIME, faces=["embed"], embed={"origins": [site]})))
        status, widget, got = call("GET", base + "/embed/widget.js")
        self.assertEqual(status, 200)
        self.assertIn("textContent", widget)
        self.assertNotIn("innerHTML", widget)                                   # it writes no HTML from data
        status, _, got = call("OPTIONS", base + "/embed/messages", None, {"Origin": site})
        self.assertEqual((status, got.get("Access-Control-Allow-Origin")), (204, site))
        status, _, got = call("OPTIONS", base + "/embed/messages", None, {"Origin": "https://evil.example"})
        self.assertEqual((status, got.get("Access-Control-Allow-Origin")), (403, None))
        turn = {"messages": [{"role": "user", "content": "Hello"}]}
        status, body, _ = call("POST", base + "/embed/messages", turn, {"Origin": site})
        self.assertEqual(status, 200)
        self.assertIn("You asked: Hello", body["reply"])
        self.assertEqual(call("POST", base + "/embed/messages", turn, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(call("POST", base + "/embed/messages", turn)[0], 403)  # no origin: not a website
        self.assertEqual(call("GET", base + "/v1/models")[0], 404)              # not declared here
        self.assertEqual(call("POST", base + "/capability/run", {})[0], 404)

    def test_FR_SC3_AC_4_every_face_answers_503_until_the_guard_passes_and_again_once_the_pack_is_withdrawn(self):
        pack = build_pack(self.project)
        site = self.tmp / "site"
        site.mkdir()
        write_text(site / "capability-pack.json", json.dumps(pack))
        write_text(site / "pack-status.json", json.dumps(fresh(bundle.status_document(self.project, pack))))
        env = {"RIHMA_PACK": site / "capability-pack.json", "RIHMA_PACK_STATUS": site / "pack-status.json",
               "RIHMA_PACK_SHA256": pack["content_sha256"], "RIHMA_PACK_STATUS_EVERY": "0.2"}
        edited = self.product("edited")
        write_text(edited / "app" / "job.py", JOB + "\n# an edit after the release\n")
        refused = self.stdio(edited, [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}], **env)
        self.assertEqual(refused[0]["error"]["code"], -32000)
        self.assertIn("the app files differ", refused[0]["error"]["message"])
        root, port = self.product("guarded"), roadmod.free_port()
        proc = subprocess.Popen([sys.executable, "factory/pack_guard.py"], cwd=root, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=clean_env(PORT=port, HOST="127.0.0.1", DATA_DIR=self.data(), **env))
        self.addCleanup(roadmod._terminate, proc)
        base = f"http://127.0.0.1:{port}"
        roadmod.wait_healthy(base, timeout=30)
        probes = [("POST", "/capability/run", {"shipments": SHIPMENTS}), ("GET", "/v1/models", None),
                  ("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})]
        for method, path, body in probes:
            self.assertEqual(call(method, base + path, body)[0], 200, path)
        self.assertEqual(call("GET", base + "/v1/models")[1]["data"][0]["pack"], pack["version"])
        withdrawn = dict(fresh(bundle.status_document(self.project, pack)), state="withdrawn", reason="a test",
                         issued_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat())
        write_text(site / "pack-status.json", json.dumps(withdrawn))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and call("GET", base + "/health")[0] != 503:
            time.sleep(0.1)
        for method, path, body in probes:
            status, answer, _ = call(method, base + path, body)
            self.assertEqual(status, 503, path)
            self.assertTrue(any("withdrawn" in r for r in answer["guard"]), answer)

    def test_FR_SC3_AC_5_the_openai_face_counts_no_tokens_and_the_gateway_records_them_as_not_measured(self):
        base = self.start(self.product(), RIHMA_FACES_TOKEN=TOKEN)
        ask_it = {"model": "shipment-digest", "messages": [{"role": "user", "content": "How many failed?"}]}
        status, body, _ = call("POST", base + "/v1/chat/completions", ask_it, {"Authorization": "Bearer " + TOKEN})
        self.assertEqual(status, 200, body)
        self.assertIsNone(body["usage"])                                         # no count, never zeros
        self.assertEqual(body["rihmasto"]["usage"], "not measured")
        pack = build_pack(self.project)
        config = parse_config({"site": {"mode": "air-gapped"}, "upstreams": {"digest": {
            "url": base + "/v1", "api_key_env": "DIGEST_FACES_TOKEN"}}, "workloads": agent_workloads(pack, "digest"),
            "audit": {"path": "faces-audit.jsonl"}}, self.tmp)
        reply = Gateway(config, env={"DIGEST_FACES_TOKEN": TOKEN}).complete(ask_it)
        self.assertEqual(reply.status, 200, reply.body)
        audit = [json.loads(line) for line in (self.tmp / "faces-audit.jsonl").read_text(encoding="utf-8").splitlines()]
        payload = audit[-1]["event"]["payload"]
        self.assertEqual((payload["status"], payload["tokens"]), ("answered", "not measured"))

    def test_FR_SC3_AC_6_mcp_over_stdio_answers_only_when_the_declaration_names_it_and_nothing_narrows_it_away(self):
        asks = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]

        def refused(answers):
            return [a.get("error", {}).get("code") for a in answers] == [-32001, -32001]

        no_mcp = self.product("no-mcp", runtime=dict(RUNTIME, faces=["embed", "http"],
                                                      embed={"origins": ["http://localhost:8000"]}))
        for argv in (("--face", "mcp", "--stdio"), ("--stdio",), ()):
            answers = self.stdio(no_mcp, asks, argv=argv)
            self.assertTrue(refused(answers), (argv, answers))
        root = self.product()
        self.assertTrue(refused(self.stdio(root, asks, RIHMA_FACES="http,openai")))    # narrowed away
        self.assertTrue(refused(self.stdio(root, asks, argv=("--face", "openai", "--stdio"))))
        answers = self.stdio(root, asks, argv=("--stdio",))                            # declared: it answers
        self.assertEqual(answers[1]["result"]["tools"][0]["name"], "capability_describe", answers)


# -- FR-SC4: the trigger path and the result out ------------------------------------------------------

class TriggerTest(CapabilityCase):
    def test_FR_SC4_AC_1_a_verified_webhook_runs_the_capability_once_and_anything_else_runs_nothing(self):
        base = self.start(self.product(), DIGEST_HOOK_SECRET=KEY)
        body = json.dumps({"type": "deliveries.failed", "data": {"shipments": SHIPMENTS}}).encode("utf-8")
        url = base + "/capability/trigger"
        status, out, _ = call("POST", url, raw=body, headers=signed(body))
        self.assertEqual((status, out["accepted"], out["state"]), (202, True, "succeeded"), out)
        self.assertEqual(call("POST", url, raw=body, headers=signed(body))[1],
                         {"accepted": False, "reason": "already received"})          # a replay runs nothing
        self.assertEqual(call("POST", url, raw=body + b" ", headers=signed(body, msg_id="msg-2"))[0], 401)
        self.assertEqual(call("POST", url, raw=body, headers=signed(body, msg_id="msg-3",
                                                                   stamp=int(time.time()) - 3600))[0], 401)
        self.assertEqual(call("POST", url, raw=body, headers=signed(body, key="another-key", msg_id="msg-4"))[0], 401)
        big = json.dumps({"pad": "x" * 70000}).encode("utf-8")
        self.assertEqual(call("POST", url, raw=big, headers=signed(big, msg_id="msg-5"))[0], 413)
        runs = call("GET", base + "/capability/runs")[1]["runs"]
        self.assertEqual([(r["trigger"]["kind"], r["trigger"]["delivery"], r["result"]["failures"]) for r in runs],
                         [("webhook", "msg-1", 2)])
        unset = self.start(self.product("unset"))
        self.assertEqual(call("POST", unset + "/capability/trigger", raw=body, headers=signed(body))[0], 503)

    def test_FR_SC4_AC_2_a_relay_event_runs_it_and_its_result_goes_out_to_the_factorys_doorbell(self):
        from embed.webhooks import make_server

        live = Factory(self.home)                       # signing and verifying read the real clock
        hooks.add_source(live, "capability-results", scheme="standard", secret_env="CAP_RESULTS_SECRET",
                         person="Jaana", persona="it")
        with mock.patch.dict(os.environ, {"CAP_RESULTS_SECRET": RESULTS_KEY}):
            doorbell = make_server(live, 0)
            threading.Thread(target=doorbell.serve_forever, daemon=True).start()
            self.addCleanup(doorbell.server_close)
            self.addCleanup(doorbell.shutdown)
            event_runtime = dict(RUNTIME, trigger={"kind": "event", "types": ["rihma.signal.received"],
                                                   "secret": "DIGEST_HOOK_SECRET"})
            base = self.start(self.product(runtime=event_runtime), DIGEST_HOOK_SECRET=KEY,
                              RIHMA_RESULT_URL=f"http://127.0.0.1:{doorbell.server_address[1]}/hooks/capability-results",
                              RIHMA_RESULT_SECRET=RESULTS_KEY)
            relay.subscribe(live, sink="webhook", url=base + "/capability/trigger", secret_env="DIGEST_HOOK_SECRET",
                            types=["rihma.*"], person="Jaana", persona="it")
            signals.receive(live, "Shipments failed again last night", channel="chat", source="ops-chat")
            out = relay.run(live, environ={"DIGEST_HOOK_SECRET": KEY})
        self.assertEqual(out["results"][0]["state"], "up to date", out)
        runs = call("GET", base + "/capability/runs")[1]["runs"]
        self.assertEqual([(r["trigger"]["kind"], r["trigger"]["event"]) for r in runs],
                         [("event", "rihma.signal.received")])                  # other event types run nothing
        self.assertEqual(runs[0]["sent"], "sent: http 202")
        came = [s for s in signals.signals(live) if s.get("ref") == f"capability-results:{runs[0]['id']}"]
        self.assertEqual(len(came), 1, signals.signals(live))
        received = live.project("_factory").ledger().of_kind("hook_received")
        self.assertEqual(received[-1]["event"]["payload"]["ref"], f"capability-results:{runs[0]['id']}")

    def test_FR_SC4_AC_3_a_scheduled_capability_runs_on_its_own_and_only_while_every_check_passes(self):
        nightly = dict(RUNTIME, trigger={"kind": "schedule", "every_minutes": 1440})
        base = self.start(self.product(runtime=nightly), "--schedule")
        deadline, runs = time.monotonic() + 20, []
        while time.monotonic() < deadline and not runs:
            runs = call("GET", base + "/capability/runs")[1]["runs"]
            time.sleep(0.1)
        self.assertEqual([r["trigger"]["kind"] for r in runs], ["schedule"])
        quiet = self.data()
        held = self.start(self.product("held", runtime=nightly), "--schedule", DATA_DIR=quiet,
                          RIHMA_PACK=self.tmp / "no-such-pack.json")
        time.sleep(1.5)
        status, body, _ = call("GET", held + "/capability/runs")
        self.assertEqual(status, 503)                                            # the guard holds every face
        self.assertTrue(any("no readable pack" in r for r in body["guard"]), body)
        self.assertFalse((quiet / "capability-runs.jsonl").exists())            # and the schedule runs nothing


# -- FR-SC5: local serve, check and Compose ----------------------------------------------------------

class ServeTest(CapabilityCase):
    def cli_proc(self, *argv: str, **kw) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "kernel.cli", "--home", str(self.home), *argv], cwd=REPO,
                              env=clean_env(), capture_output=True, text=True, timeout=180, **kw)

    def test_FR_SC5_AC_1_capability_serve_runs_the_delivered_release_behind_its_guard_and_records_the_trace(self):
        lines = "\n".join(json.dumps(m) for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "count_failures", "arguments": {"shipments": SHIPMENTS}}}]) + "\n"
        proc = self.cli_proc("capability", "serve", self.project.pid, "--face", "mcp", input=lines)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        answers = [json.loads(line) for line in proc.stdout.splitlines()]       # stdout: protocol lines only
        pack = build_pack(self.project)
        self.assertEqual(answers[0]["result"]["serverInfo"], {"name": "shipment-digest", "version": pack["version"]})
        self.assertEqual(answers[1]["result"]["structuredContent"]["result"], 2)
        note = json.loads(proc.stderr.strip().splitlines()[0])
        self.assertEqual((note["serving"], note["pack_status"]), ("mcp", "valid"))
        trace = self.project.ledger().of_kind("capability_served")[-1]["event"]["payload"]
        self.assertTrue(trace["by"].startswith("local:"))
        self.assertEqual((trace["decided"]["pack_status"], trace["proof"]["pack_sha256"], trace["transport"]),
                         ("valid", pack["content_sha256"], "stdio"))
        self.assertEqual(trace["proof"]["declaration_sha256"], pack["runtime"]["declaration_sha256"])
        self.assertTrue(any("DIGEST_HOOK_SECRET" in a for a in trace["assumed"]), trace["assumed"])
        http = subprocess.Popen([sys.executable, "-m", "kernel.cli", "--home", str(self.home), "capability", "serve",
                                 self.project.pid, "--face", "openai", "--port", "0"], cwd=REPO, env=clean_env(),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(roadmod._terminate, http)
        self.addCleanup(http.stdout.close)
        listening = json.loads(http.stdout.readline())["listening"]
        self.assertTrue(listening.startswith("http://127.0.0.1:"))
        ask_it = {"model": "shipment-digest", "messages": [{"role": "user", "content": "Any failures?"}]}
        status, body, _ = call("POST", listening + "/v1/chat/completions", ask_it)
        self.assertEqual((status, body["rihmasto"]["pack"]), (200, pack["version"]), body)
        self.assertEqual(call("POST", listening + "/capability/run", {})[0], 404)   # only the face asked for

    def test_FR_SC5_AC_1_a_face_it_does_not_offer_or_a_release_it_does_not_have_is_refused_and_writes_nothing(self):
        before = len(self.project.ledger().records())
        for argv in (("--face", "embed", "--port", "0"), ("--face", "openai"), ("--face", "mcp", "--release", "9")):
            proc = self.cli_proc("capability", "serve", self.project.pid, *argv)
            self.assertEqual(proc.returncode, 2, (argv, proc.stdout, proc.stderr))
            self.assertIn("rihmasto capability serve:", proc.stderr)
        self.assertEqual(len(self.project.ledger().records()), before)
        self.assertFalse(self.project.path("capability").exists())

    def test_FR_SC5_AC_4_only_the_schedule_flag_starts_the_schedule_and_the_trace_says_whether_it_runs(self):
        with mock.patch.dict(os.environ, {"RIHMA_SCHEDULE": "on", "RIHMA_FACES": "http"}):
            info = kfaces.plan(self.project, face="mcp")
            inherited = {"RIHMA_SCHEDULE", "RIHMA_FACES"} & set(info["env"])  # names only: a failure prints no value
            self.assertEqual(inherited, set())                                # the shell's settings stay behind
            trace = kfaces.record_served(self.project, info, "local:tester")
        self.assertIs(trace["schedule"], False)
        logged = self.project.ledger().of_kind("capability_served")[-1]["event"]["payload"]
        self.assertIs(logged["schedule"], False)
        flagged = kfaces.plan(self.project, face="mcp", schedule=True)
        self.assertIn("--schedule", flagged["argv"])
        self.assertIs(kfaces.record_served(self.project, flagged, "local:tester")["schedule"], False)  # no schedule
        scheduled = dict(flagged, pack=dict(flagged["pack"], runtime=dict(
            flagged["pack"]["runtime"], trigger={"kind": "schedule", "every_minutes": 60})))
        self.assertIs(kfaces.record_served(self.project, scheduled, "local:tester")["schedule"], True)

    def test_FR_SC5_AC_2_capability_check_judges_the_declaration_at_a_release_and_writes_nothing(self):
        before = len(self.project.ledger().records())
        out = self.cli_proc("capability", "check", self.project.pid)
        self.assertEqual(out.returncode, 0, out.stderr)
        shown = json.loads(out.stdout)
        self.assertEqual((shown["release"], shown["runtime"]), (1, for_pack(RUNTIME)))
        self.assertEqual(len(self.project.ledger().records()), before)
        self.assertEqual(cli(["--home", str(self.home), "capability", "check", self.project.pid, "--release", "5"]), 2)

    def test_FR_SC5_AC_3_the_compose_file_carries_the_faces_with_secrets_and_the_token_by_name_only(self):
        pack = build_pack(self.project)
        rev = "a" * 40
        pkg = {"schema": roadmod.SITE_PACKAGE_SCHEMA, "project": self.project.pid, "release": 1, "environment": "demo",
               "slot": "current", "road": {"name": "team-docker", "kind": "docker"}, "revision": rev,
               "artifact": {"type": "image", "ref": f"registry.example:5000/team/digest@{DIGEST}", "digest": DIGEST},
               "settings": {"APP_VERSION": rev[:12]}, "rules": {}, "target": {}, "secrets": [],
               "pack": {"format": pack["format"], "version": pack["version"], "content_sha256": pack["content_sha256"],
                        "file": "capability-pack.json", "status_file": "pack-status.json"}}
        plain = roadmod.render_compose(pkg)
        self.assertNotIn("RIHMA_FACES", plain["model"]["services"]["app"]["environment"])   # a web product: none
        out = roadmod.render_compose(pkg, pack["runtime"])
        self.assertEqual(out["problems"], [])
        app = out["model"]["services"]["app"]
        env = app["environment"]
        self.assertEqual(env["RIHMA_FACES"], "mcp,openai,http")
        for name in ("DIGEST_HOOK_SECRET", "RIHMA_FACES_TOKEN", "RIHMA_GATEWAY_URL"):
            self.assertEqual(env[name], roadmod.secret_from_env(name))
        self.assertEqual(env["RIHMA_RESULT_SECRET"], "${RIHMA_RESULT_SECRET}")
        self.assertNotIn("RIHMA_SCHEDULE", env)                                  # a webhook starts it, not a clock
        self.assertEqual(app["labels"]["gnomonfactory.faces"], "mcp,openai,http")
        self.assertEqual((roadmod.validate_compose(out["model"]), roadmod.secret_leaks(out["model"])), ([], []))
        self.assertEqual(roadmod.from_yaml(out["yaml"]), out["model"])
        self.assertIn("docker compose run --rm -T app python3 factory/faces.py --face mcp --stdio", out["yaml"])
        self.assertIn("POST /capability/trigger, verified with Standard Webhooks", out["yaml"])
        nightly = roadmod.render_compose(pkg, for_pack(dict(RUNTIME, trigger={"kind": "schedule", "every_minutes": 60})))
        self.assertEqual(nightly["model"]["services"]["app"]["environment"]["RIHMA_SCHEDULE"], "on")


# -- FR-SC6: learnable and reachable ------------------------------------------------------------------

class ReachableTest(CapabilityCase):
    def test_FR_SC6_AC_1_the_assistant_explains_the_faces_and_takes_a_person_to_the_releases_tab(self):
        controls = {c["id"]: c for c in ui_map()["controls"]}
        self.assertIn("capability_faces", controls)
        self.assertEqual(CONTROL_PAGES["capability_faces"], ("releases", None))
        out = ask(self.factory, "Where do I see how the capability is reached over MCP?", persona="developer",
                  project_id=self.project.pid)
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.project.pid}/releases", "control": "capability_faces"})
        js = (REPO / "cockpit" / "static" / "project.js").read_text(encoding="utf-8")
        self.assertIn('"data-control": "capability_faces"', js)
        guide = (REPO / "docs" / "guides" / "small-capabilities.md").read_text(encoding="utf-8")
        for heading in ("## Tutorial", "## What is built and what is planned"):
            self.assertIn(heading, guide)
        self.assertIn("rihmasto capability serve", guide)


if __name__ == "__main__":
    unittest.main()
