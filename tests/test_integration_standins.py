"""The gate checks a product's declared integrations against stand-ins (FR-DS3).

A real project declares a SQLite integration, is compiled, and a scripted builder cell builds its INT-
task: the gate runs the product's own tests with the integration's setting pointed at a seeded SQLite
stand-in, and its `integrations` signal says whether the data access held to what was declared. The HTTP,
object-store and MCP stand-ins are checked through the gate's suite runner on small product folders.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import SPEC, FactoryTestCase, no_findings, script  # noqa: E402

from kernel import integration_decl, integration_standins  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.gate import run_suite  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.roads import rmtree  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

ORDERS = {"name": "orders_db", "kind": "sqlite", "access": "read", "data_classes": ["internal"],
          "purpose": "reads open orders", "sources": ["request"]}
SEED = "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT, status TEXT);\n" \
       "INSERT INTO orders VALUES (1, 'Pallet Oy', 'open'), (2, 'Hylly Ab', 'closed');\n"
ROUTE = '''

import os as _os
import sqlite3 as _sqlite3


@route("GET", "/orders/open")
def open_orders(req):
    url = _os.environ.get("ORDERS_DB_URL", "")
    if not url.startswith("sqlite:///"):
        return 503, {"error": "orders_db is not reachable"}
    db = _sqlite3.connect("file:" + url[len("sqlite:///"):] + "?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT id, customer FROM orders WHERE status = 'open' ORDER BY id").fetchall()
    finally:
        db.close()
    return 200, [{"id": r[0], "customer": r[1]} for r in rows]
'''
TEST = '''import os
import sqlite3
import unittest

import app.routes  # noqa: F401
from app.server import handle


class OrdersTest(unittest.TestCase):
    def test_INT_ORDERS_DB_AC_1_lists_the_open_orders_read_from_orders_db(self):
        status, body, _ = handle("GET", "/orders/open")
        self.assertEqual(status, 200)
        self.assertEqual([o["customer"] for o in body], ["Pallet Oy"])
'''
WRITES = '''
    def test_it_also_writes_to_orders_db(self):
        db = sqlite3.connect(os.environ["ORDERS_DB_URL"][len("sqlite:///"):])
        db.execute("INSERT INTO orders VALUES (3, 'Uusi Oy', 'open')")
        db.commit()
        db.close()
'''


def analyst(prompt: str, role: str) -> str:
    if "You turn a brief into a software specification" in prompt:
        return "```json\n" + json.dumps(dict(SPEC, integrations=[ORDERS])) + "\n```"
    return script(prompt, role)


def cell(writes: bool):
    def run(lane_path, prompt):
        assert "INT-ORDERS-DB-AC-1" in prompt and "ORDERS_DB_URL" in prompt   # the envelope names it
        root = Path(lane_path)
        (root / "tests" / "standins").mkdir(parents=True, exist_ok=True)
        (root / "tests" / "standins" / "orders_db.sql").write_text(SEED, encoding="utf-8", newline="\n")
        routes = root / "app" / "routes.py"
        routes.write_text(routes.read_text(encoding="utf-8") + ROUTE, encoding="utf-8", newline="\n")
        (root / "tests" / "test_orders_db.py").write_text(TEST + (WRITES if writes else ""), encoding="utf-8",
                                                           newline="\n")
        return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 4, "model": "fake-builder",
                "output": "done"}
    return run


class PipelineStandinTest(FactoryTestCase):
    def compiled(self):
        p = self.new(mode="assume", maturity="demo")
        intake(p, "Show the open orders from our orders database.", model=FakeModel(analyst), requested_by="Aino")
        make_spec(p, model=FakeModel(analyst))
        contract = compile_project(p)
        task = next(t["id"] for t in contract["tasks"] if "INT-ORDERS-DB-AC-1" in t["criteria"])
        return p, task

    def signals(self, out: dict) -> dict:
        return {s["name"]: s for s in out["rounds"][-1]["gate"]["signals"]}

    def test_FR_DS3_AC_1_the_gate_runs_the_products_tests_against_a_seeded_stand_in_and_says_so(self):
        p, task = self.compiled()
        out = build_task(p, task, lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=cell(False),
                         verifier_runner=no_findings)
        self.assertEqual(out["status"], "merged", out)
        sig = self.signals(out)
        self.assertEqual(sig["integrations"]["verdict"], "passed")
        self.assertEqual(sig["integrations"]["native"]["standins"]["orders_db"]["standin"], "sqlite")
        self.assertEqual(sig["trace"]["verdict"], "passed")                  # a test names its criterion
        self.assertEqual(sig["fail_first"]["verdict"], "passed")

    def test_FR_DS3_AC_2_a_product_that_writes_to_an_integration_declared_read_fails_the_gate(self):
        p, task = self.compiled()
        out = build_task(p, task, lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=cell(True),
                         verifier_runner=no_findings, max_rounds=0)
        self.assertNotEqual(out["status"], "merged")
        sig = self.signals(out)["integrations"]
        self.assertEqual(sig["verdict"], "failed")
        self.assertIn("orders_db is declared read and was written", sig["detail"])
        self.assertEqual(self.signals(out)["tests"]["verdict"], "passed")    # the tests alone would let it in


CONTRACT_TASK = "T-009"


def product(root: Path, decl: dict, test_body: str, fixture: dict | None = None, given: str | None = None) -> Path:
    """A small product folder: a contract declaring one integration, a stand-in fixture, and one test."""
    d = integration_decl.normalize(decl, provenance="assumption")
    req = integration_decl.requirement(d)
    if given is not None:
        req["acceptance"][0]["given"] = given
    contract = {"requirements": [req], "tasks": [{"id": CONTRACT_TASK, "title": "x", "criteria": [
        req["acceptance"][0]["id"]]}]}
    (root / "tests" / "standins").mkdir(parents=True)
    (root / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    if fixture is not None:
        (root / "tests" / "standins" / f"{d['name']}.json").write_text(json.dumps(fixture), encoding="utf-8")
    (root / "tests" / "test_reach.py").write_text(
        "import json\nimport os\nimport unittest\nimport urllib.request\n\n"
        "OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({})).open\n\n\n"
        "def call(method, path, body=None):\n"
        f"    url = os.environ['{d['name'].upper()}_URL'] + path\n"
        "    data = json.dumps(body).encode() if body is not None else None\n"
        "    req = urllib.request.Request(url, data=data, method=method,\n"
        "                                 headers={'Content-Type': 'application/json'})\n"
        "    try:\n        with OPEN(req, timeout=10) as r:\n            return r.status, r.read()\n"
        "    except urllib.error.HTTPError as e:\n        return e.code, e.read()\n\n\n"
        "class Reach(unittest.TestCase):\n" + test_body, encoding="utf-8")
    return root


API = {"name": "orders_api", "kind": "rest", "access": "read", "data_classes": ["internal"],
       "credentials": ["ORDERS_API_TOKEN"]}
API_FIXTURE = {"responses": [{"method": "GET", "path": "/orders", "status": 200, "json": [{"id": 1}]}]}


class SuiteStandinTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-standins-"))
        self.addCleanup(rmtree, self.tmp)
        self.n = 0

    def judge(self, decl, body, fixture=None, given=None):
        self.n += 1
        root = product(self.tmp / f"p{self.n}", decl, body, fixture, given)
        contract = json.loads((root / "contract.json").read_text(encoding="utf-8"))
        run = run_suite(root)
        return run, integration_standins.signal(contract, run, CONTRACT_TASK)

    def test_FR_DS3_AC_1_an_http_stand_in_answers_from_the_products_fixture_with_placeholder_credentials(self):
        run, [sig] = self.judge(API, "    def test_INT_ORDERS_API_AC_1_reads(self):\n"
                                     "        self.assertEqual(os.environ['ORDERS_API_TOKEN'], "
                                     f"'{integration_standins.PLACEHOLDER}')\n"
                                     "        self.assertEqual(os.environ['ORDERS_API_ACCESS'], 'read')\n"
                                     "        status, body = call('GET', '/orders')\n"
                                     "        self.assertEqual((status, json.loads(body)), (200, [{'id': 1}]))\n"
                                     "        read = call('POST', '/q', {'statement': 'SELECT 1'})\n"
                                     "        self.assertEqual(read[0], 404)\n",
                                API_FIXTURE)
        self.assertEqual(run["exit"], 0, run.get("tail"))
        self.assertEqual((sig.name, sig.verdict), ("integrations", "passed"), sig.detail)
        self.assertEqual(run["standins"]["orders_api"]["requests"], 2)           # a read query is no write

    def test_FR_DS3_AC_2_every_kind_of_write_to_a_read_integration_is_caught(self):
        writes = {
            "PUT /orders/1": (API, "call('PUT', '/orders/1', {'id': 1})", API_FIXTURE),
            "POST /q": (API, "call('POST', '/q', {'statement': 'DELETE FROM orders'})", API_FIXTURE),
            "PUT /reports/a.csv": ({"name": "files", "kind": "s3", "access": "read", "data_classes": ["internal"]},
                                   "call('PUT', '/reports/a.csv', 'x')", {}),
            "POST /mcp": ({"name": "crm", "kind": "mcp", "access": "read", "data_classes": ["internal"]},
                          "call('POST', '', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', "
                          "'params': {'name': 'insert_contact', 'arguments': {}}})", {"results": {}}),
        }
        for write, (decl, line, fixture) in writes.items():
            with self.subTest(write):
                criterion = integration_decl.requirement_id(decl["name"]).replace("-", "_") + "_AC_1"
                _, [sig] = self.judge(decl, f"    def test_{criterion}_writes(self):\n        {line}\n", fixture)
                self.assertEqual(sig.verdict, "failed", sig.detail)
                self.assertIn(write, sig.detail)

    def test_FR_DS3_AC_2_an_object_store_stand_in_round_trips_for_an_integration_that_may_write(self):
        decl = {"name": "files", "kind": "s3", "access": "read-write", "data_classes": ["internal"]}
        run, [sig] = self.judge(decl, "    def test_INT_FILES_AC_1_writes_then_reads(self):\n"
                                      "        self.assertEqual(call('PUT', '/reports/a.csv', 'x')[0], 200)\n"
                                      "        status, body = call('GET', '/reports?list-type=2&prefix=')\n"
                                      "        self.assertIn(b'<Key>a.csv</Key>', body)\n"
                                      "        self.assertEqual(call('GET', '/reports/a.csv')[1], b'\"x\"')\n", {})
        self.assertEqual(run["exit"], 0, run.get("tail"))
        self.assertEqual(sig.verdict, "passed", sig.detail)

    def test_FR_DS3_AC_3_a_test_that_never_reaches_the_stand_in_proves_nothing_and_no_declaration_adds_nothing(self):
        run, [sig] = self.judge(API, "    def test_INT_ORDERS_API_AC_1_stubbed(self):\n        self.assertTrue(True)\n",
                                API_FIXTURE)
        self.assertEqual(run["exit"], 0)
        self.assertEqual(sig.verdict, "not measured")
        self.assertIn("no request reached its stand-in", sig.detail)
        _, [edited] = self.judge(API, "    def test_x(self):\n        pass\n", API_FIXTURE,
                                 given="whatever a person wrote")
        self.assertEqual(edited.verdict, "not measured")
        self.assertIn("no longer names its integration", edited.detail)
        plain = self.tmp / "plain"
        (plain / "tests").mkdir(parents=True)
        (plain / "tests" / "test_plain.py").write_text(
            "import os\nimport unittest\n\n\nclass P(unittest.TestCase):\n    def test_p(self):\n"
            "        self.assertFalse([k for k in os.environ if k.endswith('_URL') and 'ORDERS' in k])\n",
            encoding="utf-8")
        (plain / "contract.json").write_text(json.dumps({"requirements": [], "tasks": []}), encoding="utf-8")
        run = run_suite(plain)
        self.assertEqual(run["exit"], 0)
        self.assertNotIn("standins", run)
        self.assertEqual(integration_standins.signal({"requirements": [], "tasks": []}, run), [])


if __name__ == "__main__":
    unittest.main()
