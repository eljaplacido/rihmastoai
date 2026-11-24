"""The one contract every connector passes (FR-IG4-AC-4).

It runs over every folder under connectors/ that holds a connector.json, so a new connector is held to
it the moment it is added. Each one must:

- validate against the schema, under its own folder's name, with fixtures, a mapping and a setup page;
- pin a tools/list that matches its fixture, and catch its rug-pull fixture (a changed tools/list);
- map every injection sample to a proposal whose text is quoted, untrusted data with no HTML and no
  hidden characters, without opening a socket;
- when it ships a narrow `server.py`: pin that file's sha256, answer the pinned tools/list over MCP
  stdio, map what each read tool returns to valid proposals, and be caught when it rug-pulls. A server
  that reaches a system runs against its folder's local fake of that system (`fake.py` `backend()`);
- the data-system connectors (FR-DS4): a pinned vendor server is faked in process (`fake.py`
  `FakeServer`), answers its pin, its reads map and a write is refused; a narrow server reads its fake
  backend, signed, and no write ever reaches the backend.

The servers run as local child processes over stdio, from their own folder; nothing reaches a network.
"""

import contextlib
import importlib.util
import itertools
import json
import os
import socket
import subprocess
import sys
import threading
import unittest
from unittest import mock

from kernel import connectors

ROOT = connectors.DEFAULT_ROOT
HIDDEN = ("​", "‌", "‍", "⁠", "‮", "‬", "\U000e0041", "\x07", "\x1b")
FIXTURES = ("tools.json", "rugpull-tools.json", "injection.json")


def mapping_of(system: str, name: str = "mapping"):
    spec = importlib.util.spec_from_file_location(f"connector_{name}_{system.replace('-', '_')}",
                                                  ROOT / system / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def backend_of(system: str):
    """The folder's local fake of the system its narrow server reaches, running; or nothing to run."""
    fake = mapping_of(system, "fake") if (ROOT / system / "fake.py").is_file() else None
    if fake is not None and hasattr(fake, "backend"):
        return fake.backend()
    return contextlib.nullcontext({"env": {}, "store": None})


def fixture(system: str, name: str):
    return json.loads((ROOT / system / "fixtures" / name).read_text(encoding="utf-8"))


class StdioServer:
    """A connector's narrow server as a child process, spoken to as an MCP client would over stdio."""

    def __init__(self, system: str, *args: str, env: dict | None = None) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
        self.proc = subprocess.Popen([sys.executable, str(ROOT / system / "server.py"), *args], cwd=ROOT / system,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", env=env)
        self.watchdog = threading.Timer(60, self.proc.kill)
        self.watchdog.start()
        self.next_id = 0

    def send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        answer = json.loads(self.proc.stdout.readline())
        assert answer.get("id") == self.next_id, answer
        return answer

    def __enter__(self) -> "StdioServer":
        init = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "rihmasto-contract-suite", "version": "1"}})
        assert "result" in init, init
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def __exit__(self, *exc) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=30)
        self.proc.stdout.close()
        self.watchdog.cancel()


def no_network(*args, **kwargs):
    raise AssertionError("a mapping opened a socket")


class ConnectorContractTest(unittest.TestCase):
    def systems(self) -> list:
        found = connectors.discover(ROOT)
        self.assertIn("example", found)
        return found

    def test_FR_IG4_AC_4_every_connector_folder_validates_with_its_fixtures_mapping_and_setup(self):
        for system in self.systems():
            with self.subTest(system):
                doc = json.loads((ROOT / system / "connector.json").read_text(encoding="utf-8"))
                self.assertEqual(connectors.validate(doc, system), [])
                for name in FIXTURES:
                    self.assertTrue((ROOT / system / "fixtures" / name).is_file(), name)
                self.assertTrue((ROOT / system / doc.get("setup", "README.md")).is_file())
                mapping = mapping_of(system)
                self.assertTrue(callable(mapping.to_proposal) and callable(mapping.from_result))
                allowed = {t["name"] for t in doc["read_tools"] + doc["write_tools"]}
                self.assertFalse(allowed & set(doc["forbidden_tools"]))

    def test_FR_IG4_AC_4_every_pinned_tools_list_matches_and_every_rug_pull_is_caught(self):
        for system in self.systems():
            with self.subTest(system):
                doc = connectors.load(ROOT, system)
                self.assertEqual(connectors.check_tools(doc, fixture(system, "tools.json")["tools"]),
                                 doc["tools_sha256"])
                with self.assertRaises(connectors.ToolsChanged) as caught:
                    connectors.check_tools(doc, fixture(system, "rugpull-tools.json")["tools"])
                self.assertEqual(caught.exception.pinned, doc["tools_sha256"])

    def test_FR_IG4_AC_4_every_injection_sample_maps_to_quoted_data_and_no_mapping_opens_a_socket(self):
        for system in self.systems():
            doc, mapping = connectors.load(ROOT, system), mapping_of(system)
            samples = fixture(system, "injection.json")["samples"]
            self.assertGreaterEqual(len(samples), 3)
            with mock.patch.object(socket, "socket", no_network), \
                    mock.patch.object(socket, "create_connection", no_network):
                proposals = [mapping.to_proposal(s) for s in samples]
            for sample, proposal in zip(samples, proposals, strict=True):
                with self.subTest(system=system, sample=sample.get("key")):
                    self.assertEqual(connectors.check_proposal(doc, proposal), [])
                    for ch in HIDDEN:
                        self.assertNotIn(ch, proposal["text"])
                    self.assertNotIn("<script", proposal["text"].lower())
                    self.assertNotIn("<img", proposal["text"].lower())

    def test_FR_IG4_AC_4_every_narrow_server_answers_its_pin_over_stdio_and_its_reads_map_to_proposals(self):
        served = [s for s in self.systems() if (ROOT / s / "server.py").is_file()]
        self.assertIn("example", served)
        for system in served:
            with self.subTest(system):
                doc, mapping = connectors.load(ROOT, system), mapping_of(system)
                self.assertEqual(doc["server"]["pin"]["sha256"], connectors.file_sha256(ROOT / system / "server.py"))
                with backend_of(system) as backend, StdioServer(system, *doc["server"]["command"][2:],
                                                                env=backend["env"]) as srv:
                    tools = srv.request("tools/list")["result"]["tools"]
                    self.assertEqual(connectors.check_tools(doc, tools), doc["tools_sha256"])
                    for tool in doc["read_tools"]:
                        result = srv.request("tools/call", {"name": tool["name"],
                                                            "arguments": tool.get("example_args", {})})["result"]
                        self.assertFalse(result["isError"], tool["name"])
                        proposals = mapping.from_result(tool["name"], json.loads(result["content"][0]["text"]))
                        self.assertTrue(proposals, tool["name"])
                        for proposal in proposals:
                            self.assertEqual(connectors.check_proposal(doc, proposal), [], proposal)
                            self.assertEqual(proposal["kind"], tool["maps_to"])
                with StdioServer(system, "--rug-pull") as srv:
                    with self.assertRaises(connectors.ToolsChanged):
                        connectors.check_tools(doc, srv.request("tools/list")["result"]["tools"])


DATA_SYSTEMS = ("postgres", "snowflake", "s3", "openapi")


_IDS = itertools.count(1)


def rpc(server, method: str, params: dict | None = None) -> dict:
    return server.handle({"jsonrpc": "2.0", "id": next(_IDS), "method": method, "params": params or {}})


class DataSystemConnectorTest(unittest.TestCase):
    """The reference connectors for data systems (FR-DS4), each against a local fake of its system."""

    def test_FR_DS4_AC_1_each_data_system_folder_is_a_connector_read_only_with_credentials_by_reference(self):
        found = connectors.discover(ROOT)
        for system in DATA_SYSTEMS:
            with self.subTest(system):
                self.assertIn(system, found)
                doc = connectors.load(ROOT, system)
                self.assertEqual(doc["write_tools"], [])                       # read-only first
                self.assertTrue(doc["forbidden_tools"])
                self.assertTrue(all(c["ref"].split(":")[0] in ("env", "os", "cmd") for c in doc["credentials"]))
                self.assertTrue((ROOT / system / "fake.py").is_file())         # a local fake of its system
        self.assertIn("--access-mode=restricted", connectors.load(ROOT, "postgres")["server"]["command"])
        snow = connectors.load(ROOT, "snowflake")
        self.assertEqual(snow["server"]["pin"]["sha256"],
                         connectors.file_sha256(ROOT / "snowflake" / "tools_config.yaml"))
        self.assertIn("UNVERIFIED", snow["notes"])
        self.assertIn("UNVERIFIED", connectors.load(ROOT, "postgres")["notes"])

    def test_FR_DS4_AC_2_a_vendor_server_faked_in_process_answers_its_pin_maps_its_reads_and_refuses_a_write(self):
        vendors = [s for s in DATA_SYSTEMS if hasattr(mapping_of(s, "fake"), "FakeServer")]
        self.assertEqual(vendors, ["postgres", "snowflake"])
        for system in vendors:
            with self.subTest(system):
                doc, mapping, fake = connectors.load(ROOT, system), mapping_of(system), mapping_of(system, "fake")
                with mock.patch.object(socket, "socket", no_network), \
                        mock.patch.object(socket, "create_connection", no_network):
                    server, rugpull = fake.FakeServer(), fake.FakeServer(rug_pull=True)
                    self.addCleanup(server.db.close)
                    self.addCleanup(rugpull.db.close)
                    self.assertIn("result", rpc(server, "initialize", {"protocolVersion": "2025-06-18"}))
                    tools = rpc(server, "tools/list")["result"]["tools"]
                    self.assertEqual(connectors.check_tools(doc, tools), doc["tools_sha256"])
                    for tool in doc["read_tools"]:
                        result = rpc(server, "tools/call", {"name": tool["name"],
                                                            "arguments": tool.get("example_args", {})})["result"]
                        self.assertFalse(result["isError"], (tool["name"], result))
                        proposals = mapping.from_result(tool["name"], json.loads(result["content"][0]["text"]))
                        self.assertTrue(proposals, tool["name"])
                        for proposal in proposals:
                            self.assertEqual(connectors.check_proposal(doc, proposal), [], proposal)
                            self.assertEqual(proposal["kind"], tool["maps_to"])
                    refused = rpc(server, "tools/call", fake.WRITE_PROBE)["result"]
                    self.assertTrue(refused["isError"], refused)                 # a write never runs
                    for name in doc["forbidden_tools"][:1]:
                        self.assertTrue(rpc(server, "tools/call", {"name": name, "arguments": {}})["result"]["isError"])
                    rugged = rpc(rugpull, "tools/list")["result"]["tools"]
                    with self.assertRaises(connectors.ToolsChanged):
                        connectors.check_tools(doc, rugged)

    def test_FR_DS4_AC_2_a_narrow_server_reads_its_fake_backend_signed_and_no_write_reaches_it(self):
        for system in ("s3", "openapi"):
            with self.subTest(system):
                doc = connectors.load(ROOT, system)
                with backend_of(system) as backend, StdioServer(system, *doc["server"]["command"][2:],
                                                                env=backend["env"]) as srv:
                    for tool in doc["read_tools"]:
                        result = srv.request("tools/call", {"name": tool["name"],
                                                            "arguments": tool.get("example_args", {})})["result"]
                        self.assertFalse(result["isError"], (tool["name"], result))
                    for name in doc["forbidden_tools"]:
                        result = srv.request("tools/call", {"name": name, "arguments": {"key": "x", "body": "y"}})
                        self.assertTrue(result["result"]["isError"], name)
                    if system == "openapi":                                       # only GET operations exist
                        result = srv.request("tools/call", {"name": "call_operation",
                                                            "arguments": {"operation_id": "createOrder"}})
                        self.assertTrue(result["result"]["isError"])
                    store = backend["store"]
                    self.assertTrue(store.requests)                               # it reached the fake ...
                    self.assertEqual(store.writes, [])                            # ... and never wrote
                    self.assertTrue(all(r.split()[0] in ("GET", "HEAD") for r in store.requests), store.requests)
                with backend_of(system) as backend:                               # the wrong key or token
                    env = dict(backend["env"], S3_SECRET_ACCESS_KEY="another", OPENAPI_TOKEN="another")
                    with StdioServer(system, *doc["server"]["command"][2:], env=env) as srv:
                        tool = doc["read_tools"][-1]
                        result = srv.request("tools/call", {"name": tool["name"], "arguments": tool["example_args"]})
                        self.assertTrue(result["result"]["isError"], result)      # is refused by the system

    def test_FR_DS4_AC_2_a_narrow_server_reaches_no_endpoint_that_is_not_https_or_loopback(self):
        for system, env in (("s3", {"S3_ENDPOINT_URL": "http://storage.example.invalid", "S3_BUCKET": "b",
                                    "S3_ACCESS_KEY_ID": "k", "S3_SECRET_ACCESS_KEY": "s"}),
                            ("openapi", {"OPENAPI_BASE_URL": "http://erp.example.invalid/api"})):
            with self.subTest(system):
                doc = connectors.load(ROOT, system)
                with StdioServer(system, *doc["server"]["command"][2:], env=env) as srv:
                    tool = doc["read_tools"][-1]
                    result = srv.request("tools/call", {"name": tool["name"], "arguments": tool["example_args"]})
                    self.assertTrue(result["result"]["isError"])
                    self.assertIn("https", result["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
