"""FR-MDL1: Models setup. Which model answers for each role, set by a person, tested with a tiny prompt.

The owner (2026-11-24): "is there now way for me to input the model endpoint / api for the platform itself?"

Every test runs on its own copy of the routing (the shipped file and the machine's overlay in a temp folder)
and its own secrets file, so no test touches this checkout's routing or the machine's keys. The only network
is a stub OpenAI-compatible endpoint on 127.0.0.1.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, isolated_routing  # noqa: E402
from test_brief_ln import tree  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import lanes  # noqa: E402
from kernel import models_setup as kmodels  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import REPO_ROOT, write_json  # noqa: E402

KEY = "fake-test-key-0123456789abcdef"


class Stub(BaseHTTPRequestHandler):
    """An OpenAI-compatible chat endpoint on loopback: answers OK, or 401 when told to refuse."""

    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(body)})
        if self.server.refuse:
            out, status = {"error": {"message": "invalid api key"}}, 401
        else:
            out, status = {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}, 200
        data = json.dumps(out).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def stub_server(case) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    server.seen, server.refuse = [], False
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    case.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(5)))
    return server


class Stubbed:
    """Its own routing and keys, and a stub endpoint on loopback."""

    def setUp(self):
        super().setUp()
        self.routing = isolated_routing(self, self.tmp)
        self.stub = stub_server(self)
        self.base = f"http://127.0.0.1:{self.stub.server_address[1]}/v1"


class ModelsKernelTest(Stubbed, FactoryTestCase):
    def ledger(self, kind: str) -> list:
        return [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind(kind)]

    def test_FR_MDL1_AC_1_every_role_of_the_routing_is_shown_with_its_model_endpoint_place_key_and_readiness(self):
        view = kmodels.models_view()
        roles = {r["role"]: r for r in view["roles"]}
        self.assertEqual(set(roles), set(lanes.load_routing()["roles"]))         # as routing.json defines them
        self.assertEqual(set(roles), {"analyst", "holdout_author", "builder", "verifier", "assistant"})
        hosted, local = roles["analyst"], roles["assistant"]
        self.assertFalse(hosted["local"])
        self.assertEqual(hosted["host"], "opencode.ai")
        self.assertEqual(hosted["key"], {"kind": "env", "name": "OPENCODE_API_KEY", "set": False})
        self.assertEqual(hosted["readiness"]["state"], "no_key")
        self.assertTrue(local["local"])
        self.assertEqual(local["host"], "127.0.0.1")
        self.assertEqual(local["key"]["name"], None)
        self.assertIn(local["readiness"]["state"], ("ready", "unreachable"))
        self.assertTrue(all(r["purpose"] and r["model"] and r["family"] for r in view["roles"]))
        self.assertEqual(view["overlay"], {"path": "kernel/routing.local.json", "present": False})
        self.assertEqual([p["id"] for p in view["presets"]][:4], ["llama_cpp", "ollama", "vllm", "opencode_go"])
        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": KEY}):
            again = {r["role"]: r for r in kmodels.models_view()["roles"]}
        self.assertEqual(again["analyst"]["readiness"]["state"], "configured")
        self.assertNotIn(KEY, json.dumps(again))                                  # a key is never shown

    def test_FR_MDL1_AC_2_a_person_sets_a_role_in_the_overlay_only_with_the_key_named_or_stored_outside_the_repo(self):
        shipped = (self.routing / "routing.json").read_bytes()
        view = kmodels.set_role(self.factory, "analyst", base_url=self.base, model="qwen3:32b", key=KEY,
                                person="Aino Example", persona="it")
        self.assertEqual((self.routing / "routing.json").read_bytes(), shipped)    # the shipped file is never written
        overlay = json.loads((self.routing / "routing.local.json").read_text(encoding="utf-8"))
        self.assertEqual(overlay["roles"]["analyst"]["model"], "qwen3:32b")
        self.assertEqual(overlay["endpoints"]["analyst-custom"],
                         {"kind": "openai", "url": self.base + "/chat/completions", "api_key_env": "RIHMASTO_KEY_ANALYST"})
        self.assertEqual(overlay["models"]["qwen3:32b"], {"family": "qwen"})
        self.assertEqual(lanes.load_routing()["roles"]["analyst"]["endpoint"], "analyst-custom")
        secrets = kmodels.secrets_path()
        self.assertFalse(secrets.resolve().is_relative_to(REPO_ROOT.resolve()))
        self.assertEqual(json.loads(secrets.read_text(encoding="utf-8"))["keys"], {"RIHMASTO_KEY_ANALYST": KEY})
        self.assertNotIn(KEY, json.dumps(overlay))
        self.assertNotIn(KEY, json.dumps(view))
        self.assertEqual((view["key"], view["local"], view["host"]),
                         ({"kind": "stored", "name": "RIHMASTO_KEY_ANALYST", "set": True}, True, "127.0.0.1"))
        # the ledger says who set which role to which host, never the key
        record = self.ledger("models_set")[-1]
        self.assertEqual({k: record[k] for k in ("role", "host", "key", "person", "persona", "model")},
                         {"role": "analyst", "host": "127.0.0.1", "key": "stored", "person": "Aino Example",
                          "persona": "it", "model": "qwen3:32b"})
        home_files = [p for p in self.factory.home.rglob("*") if p.is_file()]
        self.assertTrue(home_files)
        self.assertFalse(any(KEY in p.read_text(encoding="utf-8", errors="replace") for p in home_files))
        # Gnomon gets the stored key in the variable the endpoint names; a lane names only the variable
        self.assertEqual(kmodels.gnomon_env({})["RIHMASTO_KEY_ANALYST"], KEY)
        self.assertEqual(kmodels.gnomon_env({"RIHMASTO_KEY_ANALYST": "from-env"})["RIHMASTO_KEY_ANALYST"], "from-env")
        lane = lanes.ensure_analyst_lane(lanes.load_routing(), root=self.tmp / "lanes")
        config = (lane / ".gnomon" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('api_key_env = "RIHMASTO_KEY_ANALYST"', config)
        self.assertNotIn(KEY, config)
        # a key named by its variable, on an endpoint the routing already has, reuses that endpoint
        kmodels.set_role(self.factory, "builder", base_url="https://opencode.ai/zen/go/v1", model="deepseek-v4-pro",
                         key_env="OPENCODE_API_KEY", person="Aino Example", persona="it", keep_fallback=False)
        self.assertEqual(lanes.load_routing()["roles"]["builder"], {"model": "deepseek-v4-pro", "endpoint": "go"})

    def test_FR_MDL1_AC_2_a_change_the_routing_rules_refuse_writes_nothing(self):
        before = tree(self.routing)
        with self.assertRaisesRegex(ValueError, "verifier must be a different model family"):
            kmodels.set_role(self.factory, "builder", base_url=self.base, model="glm-5.3", person="Aino Example",
                             persona="it", keep_fallback=False)
        for bad in ({"base_url": "ftp://x/v1"}, {"base_url": "http://user:pw@127.0.0.1/v1"},
                    {"key_env": "pasted-key-value-abc"}, {"model": " "}):
            args = {"base_url": self.base, "model": "qwen3:32b", **bad}
            with self.assertRaises(ValueError, msg=bad):
                kmodels.set_role(self.factory, "analyst", person="Aino Example", persona="it", **args)
        with self.assertRaises(DecisionRefused):
            kmodels.set_role(self.factory, "analyst", base_url=self.base, model="m", person="kernel", persona="it")
        with self.assertRaisesRegex(ValueError, "no role"):
            kmodels.set_role(self.factory, "poet", base_url=self.base, model="m", person="Aino Example", persona="it")
        self.assertEqual(tree(self.routing), before)
        self.assertEqual(self.ledger("models_set"), [])

    def test_FR_MDL1_AC_3_test_sends_a_tiny_prompt_and_says_the_latency_or_the_error_and_records_nothing(self):
        kmodels.set_role(self.factory, "assistant", base_url=self.base, model="qwen3:32b", key=KEY,
                         person="Aino Example", persona="it")
        home, routing = tree(self.factory.home), tree(self.routing)
        out = kmodels.probe_role("assistant")
        self.assertTrue(out["ok"], out)
        self.assertIsInstance(out["latency_ms"], int)
        self.assertEqual((out["reply"], out["host"], out["model"]), ("OK", "127.0.0.1", "qwen3:32b"))
        seen = self.stub.seen[-1]
        self.assertEqual(seen["path"], "/v1/chat/completions")
        self.assertEqual(seen["auth"], f"Bearer {KEY}")                           # the stored key reached the endpoint
        self.assertEqual(seen["body"]["model"], "qwen3:32b")
        self.stub.refuse = True
        out = kmodels.probe_role("assistant")
        self.assertFalse(out["ok"])
        self.assertIn("HTTP 401", out["error"])
        self.assertNotIn(KEY, json.dumps(out))
        self.assertEqual((tree(self.factory.home), tree(self.routing)), (home, routing))   # a test records nothing
        out = kmodels.probe_role("analyst")                                       # hosted, its key not set: no call
        self.assertEqual((out["ok"], len(self.stub.seen)), (False, 2))
        self.assertIn("OPENCODE_API_KEY", out["error"])
        kmodels.set_role(self.factory, "assistant", base_url="http://127.0.0.1:9/v1", model="m", person="Aino Example",
                         persona="it")
        out = kmodels.probe_role("assistant")
        self.assertFalse(out["ok"])
        self.assertIn("could not reach 127.0.0.1", out["error"])

    def test_FR_MDL1_AC_4_a_role_goes_back_to_the_shipped_routing_with_its_endpoint_and_stored_key(self):
        shipped = lanes.load_routing()["roles"]["analyst"]
        kmodels.set_role(self.factory, "analyst", base_url=self.base, model="qwen3:32b", key=KEY, person="Aino Example",
                         persona="it")
        view = kmodels.remove_role(self.factory, "analyst", person="Ilkka Example", persona="it")
        self.assertEqual(view["endpoint"], shipped["endpoint"])
        self.assertEqual(lanes.load_routing()["roles"]["analyst"], shipped)
        overlay = json.loads((self.routing / "routing.local.json").read_text(encoding="utf-8"))
        self.assertNotIn("endpoints", overlay)
        self.assertEqual(kmodels.stored_keys(), {})
        self.assertEqual(self.ledger("models_removed")[-1]["person"], "Ilkka Example")
        with self.assertRaisesRegex(ValueError, "already uses the shipped routing"):
            kmodels.remove_role(self.factory, "analyst", person="Ilkka Example", persona="it")

    def test_FR_MDL1_AC_5_the_command_line_lists_sets_tests_and_removes_and_never_prints_the_key(self):
        def cli(*argv, stdin=""):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                    mock.patch("sys.stdin", io.StringIO(stdin)):
                code = main(["--home", str(self.factory.home), *argv])
            return code, out.getvalue(), err.getvalue()

        code, out, _ = cli("models", "list", "--no-probe")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["roles"]), 5)
        code, out, err = cli("models", "set", "assistant", "--base-url", self.base, "--model", "qwen3:32b",
                             "--key-stdin", "--person", "Aino Example", "--persona", "it", stdin=KEY + "\n")
        self.assertEqual(code, 0, err)
        self.assertNotIn(KEY, out + err)
        self.assertEqual(kmodels.stored_keys(), {"RIHMASTO_KEY_ASSISTANT": KEY})
        code, out, _ = cli("models", "test", "assistant")
        self.assertEqual((code, json.loads(out)["ok"]), (0, True))
        code, _, err = cli("models", "set", "assistant", "--base-url", self.base, "--model", "m", "--person", "kernel",
                           "--persona", "it")
        self.assertEqual(code, 2)
        self.assertIn("is not a person", err)
        code, out, _ = cli("models", "remove", "assistant", "--person", "Aino Example", "--persona", "it")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["endpoint"], "local")
        self.assertEqual(json.loads(cli("models", "presets")[1])["presets"][0]["id"], "llama_cpp")


class PrivateNetworkTest(Stubbed, FactoryTestCase):
    def test_FR_MDL1_AC_9_a_model_on_the_owners_own_network_counts_as_local_for_confidential_work(self):
        from kernel import confidential as kc

        for where, local in (("http://127.0.0.1:8080/v1/chat/completions", True), ("127.0.0.1", True),
                             ("http://192.168.1.20:8000/v1", True), ("http://100.86.1.2:18080/v1", True),
                             ("http://[fd00::5]:8080/v1", True), ("localhost:11434", True),
                             ("http://gpu.lan:8000/v1", True), ("http://box.home.arpa/v1", True),
                             ("http://gpu-box:18080/v1", False), ("https://api.example.com/v1", False),
                             ("http://100.128.0.1/v1", False), ("http://8.8.8.8/v1", False)):
            self.assertEqual(kc.is_local(where), local, where)
            self.assertEqual(kmodels.is_local(where), local, where)              # one rule, both places
        self.assertTrue(kc.is_local("http://gpu-box:18080/v1", {"private": True}))   # declared by its owner
        self.assertFalse(kc.is_local("http://gpu-box:18080/v1", {"private": "yes"}))  # only a true declaration
        view = kmodels.set_role(self.factory, "analyst", base_url="http://gpu-box:18080/v1", model="qwen3:32b",
                                private=True, person="Aino Example", persona="it")
        self.assertTrue(view["local"])
        overlay = json.loads((self.routing / "routing.local.json").read_text(encoding="utf-8"))
        self.assertIs(overlay["endpoints"]["analyst-custom"]["private"], True)
        analyst = [r for r in kc.routes(["analyst"], lanes.load_routing()) if r["which"] == "primary"]
        self.assertEqual([r["local"] for r in analyst], [True])
        again = kmodels.set_role(self.factory, "analyst", base_url="http://gpu-box:18080/v1", model="qwen3:32b",
                                 person="Aino Example", persona="it")
        self.assertFalse(again["local"])                                              # undeclared: hosted


class ModelsCockpitTest(Stubbed, CockpitTestCase):

    def test_FR_MDL1_AC_6_the_cockpit_sets_tests_and_removes_a_role_signed_and_home_knows_when_no_model_answers(self):
        status, view, _ = self.call("GET", "/api/models")
        self.assertEqual(status, 200)
        self.assertEqual(len(view["roles"]), 5)
        with mock.patch("kernel.models_setup.gnomon_found", return_value=True):
            self.assertFalse(self.call("GET", "/api/models")[1]["ready"])         # Home shows "Set up a model"
        body = {"base_url": self.base, "model": "qwen3:32b", "key": KEY, "person": "Aino Example", "persona": "it"}
        status, out, _ = self.call("PUT", "/api/models/analyst", {**body, "person": "kernel"})
        self.assertEqual(status, 403)
        self.assertFalse((self.routing / "routing.local.json").exists())
        status, out, _ = self.call("PUT", "/api/models/analyst", body)
        self.assertEqual(status, 200, out)
        self.assertEqual((out["role"]["host"], out["role"]["key"]["kind"]), ("127.0.0.1", "stored"))
        self.assertNotIn(KEY, json.dumps(out))
        status, out, _ = self.call("POST", "/api/models/analyst/test", {"person": "Aino Example", "persona": "it"})
        self.assertEqual((status, out["test"]["ok"], out["test"]["reply"]), (200, True, "OK"), out)
        with mock.patch("kernel.models_setup.gnomon_found", return_value=True):
            got = self.call("GET", "/api/models")[1]
        self.assertTrue(got["ready"])                                             # the analyst answers: no card
        self.assertNotIn(KEY, json.dumps(got))
        status, out, _ = self.call("PUT", "/api/models/builder", {**body, "model": "glm-5.3", "keep_fallback": False})
        self.assertEqual(status, 400)
        self.assertIn("different model family", out["error"])
        status, out, _ = self.call("POST", "/api/models/analyst/remove", {"person": "Aino Example", "persona": "it"})
        self.assertEqual((status, out["role"]["endpoint"]), (200, "go"))
        kinds = [r["event"]["kind"] for r in factory_project(self.factory).ledger().records()]
        self.assertEqual([k for k in kinds if k.startswith("models_")], ["models_set", "models_removed"])

    def test_FR_MDL1_AC_6_a_broken_overlay_is_said_not_overwritten(self):
        write_json(self.routing / "routing.local.json", ["not", "an", "object"])
        status, out, _ = self.call("PUT", "/api/models/analyst", {"base_url": self.base, "model": "m",
                                                                  "person": "Aino Example", "persona": "it"})
        self.assertEqual(status, 400)
        self.assertIn("one JSON object", out["error"])
        self.assertEqual(json.loads((self.routing / "routing.local.json").read_text(encoding="utf-8")), ["not", "an", "object"])


class AskRihmaTest(FactoryTestCase):
    def test_FR_MDL1_AC_7_ask_rihma_takes_a_person_to_models_setup(self):
        from kernel.assistant import ask

        cases = {"Where do I set the model endpoint?": {"route": "#/models", "control": None},
                 "Where do I put my API key?": {"route": "#/models", "control": None},
                 "How do I test the model?": {"route": "#/models", "control": "models_test"},
                 "Can I use a local model with ollama?": {"route": "#/models", "control": None}}
        for question, where in cases.items():
            out = ask(self.factory, question, persona="it")
            self.assertEqual(out["navigate"], where, question)
