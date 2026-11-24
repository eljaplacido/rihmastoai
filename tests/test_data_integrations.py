"""Data integrations a product declares, on its spec and its plan (FR-DS1), and bound by IT on the paved
roads before delivery wires them into the deploy package and the Compose file (FR-DS2).

The declaration tests run the real intake and spec stages with the scripted analyst; the delivery tests
run a real product built once per test run (tests/test_deliver.py's fixture) on local roads.
"""

import contextlib
import copy
import io
import json
import os
import sys
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import SPEC, FactoryTestCase, script  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_deliver import LOCAL_ROADS, DeliveryTestCase, _Health  # noqa: E402

from kernel import integration_bind, integration_decl  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.deliver import deliver  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.plan import required, summary  # noqa: E402
from kernel.roads import road_conflicts  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import write_json  # noqa: E402

IDEA = "Show the picking team which customer orders are open, read from our orders database."
ORDERS = {"name": "orders_db", "kind": "postgres", "access": "read", "data_classes": ["internal"],
          "credentials": ["ORDERS_DB_PASSWORD"], "purpose": "reads open orders", "sources": ["request"]}
DRAFT = dict(SPEC, integrations=[
    ORDERS,
    {"name": "erp", "kind": "openapi", "system": "netsuite", "access": "read-write", "data_classes": ["confidential"],
     "purpose": "posts picking confirmations"},
    {"name": "bad", "kind": "oracle", "access": "read", "data_classes": ["internal"]},
    {"name": "orders_db", "kind": "sqlite", "access": "read", "data_classes": ["internal"]},
])
PROMPTS: list = []


def analyst(draft: dict):
    def answer(prompt: str, role: str) -> str:
        if "You turn a brief into a software specification" in prompt:
            PROMPTS.append(prompt)
            return "```json\n" + json.dumps(draft) + "\n```"
        return script(prompt, role)
    return FakeModel(answer)


def run_cli(home: Path, *argv: str) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--home", str(home), *argv])
    return code, out.getvalue(), err.getvalue()


class DeclarationTest(FactoryTestCase):
    def specced(self, draft=DRAFT, maturity="demo"):
        p = self.new(mode="assume", maturity=maturity)
        intake(p, IDEA, model=analyst(draft), requested_by="Aino")
        make_spec(p, model=analyst(draft))
        return p

    def test_FR_DS1_AC_1_a_declaration_is_validated_and_each_break_is_named_by_its_path(self):
        self.assertEqual(integration_decl.check(ORDERS), [])
        token = "gh" + "p_" + "A1b2C3d4" * 5                                   # the shape of a live token
        cases = {
            "/kind": dict(ORDERS, kind="oracle"),
            "/via": dict(ORDERS, kind="s3", via="sql", credentials=[]),
            "/access": dict(ORDERS, access="write"),
            "/data_classes": dict(ORDERS, data_classes=["secret"]),
            "/system": dict(ORDERS, kind="openapi"),
            "/credentials/0": dict(ORDERS, credentials=["OTHER_PASSWORD"]),
            "/name": dict(ORDERS, name="Orders DB"),
            "/extra": dict(ORDERS, extra=1),
            "/purpose": dict(ORDERS, purpose=token),
        }
        for path, decl in cases.items():
            with self.subTest(path):
                self.assertIn(path, [v["path"] for v in integration_decl.check(decl)])
        for name in ("api_token", "port_db", "rihma_x"):                     # its settings would look like a secret
            self.assertIn("/name", [v["path"] for v in integration_decl.check(dict(ORDERS, name=name))])
        self.assertIn("/credentials/0", [v["path"] for v in integration_decl.check(
            dict(ORDERS, credentials=["ORDERS_DB_URL"]))])                    # a setting is no credential
        self.assertEqual(integration_decl.normalize(ORDERS, provenance="assumption")["via"], "mcp")

    def test_FR_DS1_AC_2_the_analysts_integrations_reach_the_spec_as_requirements_the_plan_and_the_contract(self):
        p = self.specced()
        self.assertIn('"integrations"', PROMPTS[-1])                          # the analyst is told how
        spec = p.read("spec.json")
        self.assertEqual([d["name"] for d in spec["integrations"]], ["orders_db", "erp"])
        orders = spec["integrations"][0]
        self.assertEqual((orders["via"], orders["provenance"], orders["decided_by"]),
                         ("mcp", "customer-endorsed", "Aino"))                # the request said it: Aino's
        self.assertEqual(spec["integrations"][1]["provenance"], "vendor-proposed")
        dropped = {d["statement"]: d["why"] for d in spec["dropped"] if d["what"] == "integration"}
        self.assertIn("/kind", dropped["bad"])
        self.assertIn("declared already", dropped["orders_db"])
        req = next(r for r in spec["requirements"] if r["id"] == "INT-ORDERS-DB")
        crit = req["acceptance"][0]
        self.assertEqual((crit["id"], crit["kind"]), ("INT-ORDERS-DB-AC-1", "test"))
        self.assertIn("ORDERS_DB_URL", crit["then"])
        self.assertIn("nothing writes to orders_db", crit["then"])
        md = p.path("spec.md").read_text(encoding="utf-8")
        self.assertIn("## Data integrations", md)
        self.assertIn("erp: openapi (netsuite) via http, read-write; data classes confidential", md)
        text = summary(spec)
        self.assertIn("Data integrations:", text)
        self.assertIn("credentials ORDERS_DB_PASSWORD", text)
        written = [r for r in p.ledger().records() if r["event"]["kind"] == "spec_written"][-1]["event"]["payload"]
        self.assertEqual([d["name"] for d in written["integrations"]], ["orders_db", "erp"])
        contract = compile_project(p)
        found, problems = integration_decl.from_contract(contract)
        self.assertEqual(problems, [])
        self.assertEqual([(d["name"], d["kind"], d["via"], d["access"]) for d in found],
                         [("orders_db", "postgres", "mcp", "read"), ("erp", "openapi", "http", "read-write")])
        self.assertTrue(any("INT-ORDERS-DB-AC-1" in t["criteria"] for t in contract["tasks"]))

    def test_FR_DS1_AC_2_every_kind_and_way_reads_back_from_the_requirement_the_kernel_writes_for_it(self):
        for kind, spec in integration_decl.KINDS.items():
            for via in spec["vias"]:
                with self.subTest(kind=kind, via=via):
                    decl = dict(ORDERS, kind=kind, via=via, access="read-write", credentials=["ORDERS_DB_KEY"])
                    if kind == "openapi":
                        decl["system"] = "sap"
                    self.assertEqual(integration_decl.check(decl), [])
                    req = integration_decl.requirement(integration_decl.normalize(decl, provenance="assumption"))
                    found, problems = integration_decl.from_contract({"requirements": [req]})
                    self.assertEqual(problems, [])
                    self.assertEqual(road_conflicts({"requirements": [req]}), [])    # no false bind conflict
                    self.assertEqual([(d["kind"], d["via"], d["access"], d["credentials"]) for d in found],
                                     [(kind, via, "read-write", ["ORDERS_DB_KEY"])])

    def test_FR_DS1_AC_3_a_person_declares_one_on_the_open_plan_and_a_writing_or_sensitive_one_needs_approval(self):
        plain = dict(SPEC)
        p = self.specced(plain)
        self.assertFalse(required(p))                                         # a demo with no integration
        integration_decl.declare(p, dict(ORDERS, via="http"), person="Aino", persona="product_owner")
        self.assertFalse(required(p))                                         # reads internal data: no approval
        integration_decl.withdraw(p, "orders_db", person="Aino", persona="product_owner", reason="not yet")
        with self.assertRaises(DecisionRefused):
            integration_decl.declare(p, ORDERS, person="Pekka", persona="it")
        with self.assertRaises(DecisionRefused):
            integration_decl.declare(p, ORDERS, person="assistant", persona="product_owner")
        writes = dict(ORDERS, name="stock", kind="rest", access="read-write", credentials=["STOCK_TOKEN"])
        d = integration_decl.declare(p, writes, person="Aino", persona="product_owner", reason="stock moves")
        self.assertEqual((d["provenance"], d["declared_by"]), ("customer-confirmed", "Aino"))
        self.assertTrue(required(p))                                          # it writes: a person approves
        self.assertEqual(p.meta["spec_version"], 4)                          # declared, withdrawn, declared
        rec = [r for r in p.ledger().records() if r["event"]["kind"] == "integration_declared"][-1]["event"]["payload"]
        self.assertEqual((rec["name"], rec["by"], rec["persona"], rec["reason"], rec["access"]),
                         ("stock", "Aino", "product_owner", "stock moves", "read-write"))
        self.assertTrue(p.path("spec.v1.json").exists())
        make_spec(p, model=analyst(plain))                                    # drafted again: hers stays
        self.assertEqual([x["name"] for x in p.read("spec.json")["integrations"]], ["stock"])
        integration_decl.withdraw(p, "stock", person="Aino", persona="product_owner", reason="not now")
        self.assertNotIn("integrations", p.read("spec.json"))
        self.assertFalse(any(r["id"] == "INT-STOCK" for r in p.read("spec.json")["requirements"]))
        integration_decl.declare(p, dict(ORDERS, data_classes=["restricted"]), person="Aino", persona="developer")
        self.assertTrue(required(p))                                          # restricted data: approval too
        compile_project(p)
        with self.assertRaises(DecisionRefused):                              # compiled: the change loop
            integration_decl.declare(p, ORDERS, person="Aino", persona="product_owner")

    def test_FR_DS1_AC_1_the_command_line_declares_lists_and_refuses_a_broken_declaration(self):
        p = self.specced(dict(SPEC))
        home = self.factory.home
        code, out, _ = run_cli(home, "integration", "kinds")
        self.assertEqual(code, 0)
        self.assertIn("connectors/postgres", out)
        code, out, err = run_cli(home, "integration", "declare", p.pid, "--name", "orders_db", "--kind", "postgres",
                                 "--access", "read", "--data-class", "internal", "--credential", "OTHER",
                                 "--person", "Aino", "--persona", "product_owner")
        self.assertEqual(code, 2, out)
        self.assertIn("/credentials/0", err)
        code, out, _ = run_cli(home, "integration", "declare", p.pid, "--name", "orders_db", "--kind", "postgres",
                               "--via", "http", "--access", "read", "--data-class", "internal", "--credential",
                               "ORDERS_DB_PASSWORD", "--purpose", "open orders", "--person", "Aino",
                               "--persona", "product_owner")
        self.assertEqual(code, 0, out)
        code, out, _ = run_cli(home, "integration", "list", p.pid)
        listing = json.loads(out)
        self.assertEqual([d["name"] for d in listing["integrations"]], ["orders_db"])
        self.assertEqual({b["state"] for b in listing["bindings"]}, {"invalid"})    # no road binds it yet
        self.assertIn("no paved road serves demo", listing["bindings"][0]["problems"])


class CockpitPlanTest(CockpitTestCase):
    def test_FR_DS1_AC_4_the_plan_view_lists_the_integrations_and_ask_rihma_takes_a_person_there(self):
        p = self.new(mode="assume", maturity="demo")
        intake(p, IDEA, model=analyst(DRAFT), requested_by="Aino")
        make_spec(p, model=analyst(DRAFT))
        status, plan, _ = self.call("GET", f"/api/projects/{p.pid}/plan")
        self.assertEqual(status, 200)
        rows = plan["spec"]["integrations"]
        self.assertEqual([(d["name"], d["access"]) for d in rows], [("orders_db", "read"), ("erp", "read-write")])
        self.assertNotIn("value", json.dumps(rows))
        self.assertIn('"data-control": "integrations"', self.page_js())
        for question in ("Where do I see the data integrations?", "Which database does this reach?"):
            out = ask(self.factory, question, persona="product_owner", project_id=p.pid)
            self.assertEqual(out["navigate"], {"route": f"#/p/{p.pid}/plan", "control": "integrations"}, question)


ROADS = copy.deepcopy(LOCAL_ROADS)
ROADS["roads"]["local"]["integrations"] = {"orders_db": {
    "endpoint": "https://orders-data.internal/api",
    "secrets": [{"name": "ORDERS_DB_PASSWORD", "ref": "env:RIHMA_TEST_ORDERS_PASSWORD"}]}}
DECLARED = integration_decl.normalize(dict(ORDERS, via="http"), provenance="customer-confirmed", decided_by="Aino")


class BindingTest(unittest.TestCase):
    def test_FR_DS2_AC_1_a_binding_is_checked_against_its_declaration_before_it_can_be_approved(self):
        good = ROADS["roads"]["local"]["integrations"]["orders_db"]
        self.assertEqual(integration_bind.binding_problems(DECLARED, good, "local"), [])
        cases = {
            "binds no orders_db": None,
            "https": dict(good, endpoint="http://orders-data.internal/api"),
            "password or a token": dict(good, endpoint="https://reader:pw@orders-data.internal/api"),
            "query carries a secret": dict(good, endpoint="https://orders-data.internal/api?sig=abc"),
            "carries a value": dict(good, secrets=[{"name": "ORDERS_DB_PASSWORD", "ref": "env:X", "value": "x"}]),
            "is not given a ref": dict(good, secrets=[]),
            "not a credential the declaration names": dict(good, secrets=good["secrets"] + [{"name": "OTHER",
                                                                                            "ref": "env:O"}]),
            "unknown key": dict(good, password="x"),
        }
        for why, binding in cases.items():
            with self.subTest(why):
                self.assertTrue(any(why in p for p in integration_bind.binding_problems(DECLARED, binding, "local")))
        sql = integration_decl.normalize(dict(ORDERS, via="sql"), provenance="assumption")
        self.assertTrue(integration_bind.binding_problems(sql, good, "local"))            # an https URL via sql
        self.assertEqual(integration_bind.binding_problems(sql, dict(good, endpoint="postgresql://reader@db:5432/o"),
                                                           "local"), [])
        per_env = {"integrations": {"orders_db": {"staging": good, "production": dict(good, endpoint="https://p/a")}}}
        self.assertEqual(integration_bind.binding_of(per_env, "orders_db", "production")["endpoint"], "https://p/a")
        self.assertIsNone(integration_bind.binding_of(per_env, "orders_db", "demo"))
        self.assertNotEqual(integration_bind.pin_of("local", "staging", DECLARED, good),
                            integration_bind.pin_of("local", "staging", DECLARED, dict(good, endpoint="https://q/a")))

    def test_FR_DS2_AC_3_compose_gives_each_setting_and_each_secret_by_name_and_a_tampered_package_is_refused(self):
        pkg = {"schema": roadmod.SITE_PACKAGE_SCHEMA, "project": "P-001", "release": 1, "environment": "production",
               "slot": "current", "road": {"name": "site", "kind": "docker"}, "revision": "0123456789ab" + "c" * 28,
               "contract_revision": "sha256:x", "rules": {}, "target": {}, "secrets": [],
               "settings": {"APP_VERSION": "0123456789ab"},
               "artifact": {"type": "image", "ref": "registry.example/app@sha256:" + "a" * 64,
                            "digest": "sha256:" + "a" * 64},
               "pack": {"format": "x", "version": "1", "content_sha256": "b" * 64, "file": "capability-pack.json",
                        "status_file": "pack-status.json"}}
        rel = {"integrations": {"production": {"orders_db": {
            "state": "approved", "card": "C-0009", "pin": "p" * 64, "by": "Jaana", "declaration": DECLARED,
            "binding": ROADS["roads"]["local"]["integrations"]["orders_db"]}}}}
        integration_bind.wire(pkg, rel, "production")
        self.assertEqual(roadmod.validate_site_package(pkg), [])
        rendered = roadmod.render_compose(pkg)
        self.assertEqual(rendered["problems"], [])
        env = rendered["model"]["services"]["app"]["environment"]
        self.assertEqual(env["ORDERS_DB_URL"], "https://orders-data.internal/api")
        self.assertEqual((env["ORDERS_DB_ACCESS"], env["ORDERS_DB_KIND"]), ("read", "postgres"))
        self.assertTrue(env["ORDERS_DB_PASSWORD"].startswith("${ORDERS_DB_PASSWORD:?"))
        self.assertNotIn("RIHMA_TEST_ORDERS_PASSWORD", rendered["yaml"])          # where it lives stays out too
        tampered = copy.deepcopy(pkg)
        tampered["integrations"][0]["endpoint"] = "https://reader:pw@orders-data.internal/api"
        tampered["settings"]["ORDERS_DB_URL"] = tampered["integrations"][0]["endpoint"]
        problems = roadmod.validate_package(dict(tampered, schema=roadmod.PACKAGE_SCHEMA))
        self.assertTrue(any("password" in p for p in problems))
        unapproved = copy.deepcopy(pkg)
        unapproved["integrations"][0]["card"] = None
        self.assertTrue(any("approved by no card" in p for p in roadmod.render_compose(unapproved)["problems"]))


class BoundDeliveryTest(DeliveryTestCase):
    maturity = "pilot"

    def setUp(self):
        super().setUp()
        spec = self.project.read("spec.json")
        spec["integrations"] = [DECLARED]
        self.project.write("spec.json", spec)
        write_json(self.factory.paved_roads_path, ROADS)

    def road_cards(self):
        cards = Canon(self.project).cards(state=None, kind="road")
        return [c for c in cards if c["refs"].get("scope") == "integration"]

    def test_FR_DS2_AC_2_delivery_waits_for_it_to_approve_each_binding_and_wires_it_into_the_package(self):
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual((card["kind"], card["deciders"], card["payload"]["integration"], card["refs"]["requirement"],
                          card["refs"]["environments"], card["refs"]["roads"]),
                         ("road", ["it"], "orders_db", "INT-ORDERS-DB", ["staging"], ["local"]))
        for shown in ("access READ", "https://orders-data.internal/api", "Data classes: internal",
                      "ORDERS_DB_PASSWORD from env:RIHMA_TEST_ORDERS_PASSWORD"):
            self.assertIn(shown, card["body"])
        self.assertFalse(self.project.path("envs").exists())                  # nothing ran before IT approved
        self.assertEqual(deliver(self.project)["waiting_on"], card["id"])      # one card, not one per call
        self.assertEqual(len(self.road_cards()), 1)
        with self.assertRaises(DecisionRefused):
            self.decide(card["id"], "configured", "developer", person="Pekka")
        self.decide(card["id"], "configured", "it", person="Jaana")
        out = deliver(self.project)
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "validation")
        pkg = self.project.read(self.project.read(f"releases/{out['release']}.json")["packages"]["staging:current"])
        self.assertEqual(roadmod.validate_package(pkg), [])
        item = pkg["integrations"][0]
        self.assertEqual((item["name"], item["card"], item["approved_by"], item["access"]),
                         ("orders_db", card["id"], "Jaana", "read"))
        self.assertEqual(pkg["settings"]["ORDERS_DB_URL"], "https://orders-data.internal/api")
        self.assertIn({"name": "ORDERS_DB_PASSWORD", "ref": "env:RIHMA_TEST_ORDERS_PASSWORD"}, pkg["secrets"])
        self.assertNotIn("value", json.dumps(pkg["secrets"]))
        with mock.patch.dict("os.environ", {"RIHMA_TEST_ORDERS_PASSWORD": "pw-for-a-local-process"}):
            env = integration_bind.env_of(pkg, resolve=True)
        self.assertEqual(env["ORDERS_DB_PASSWORD"], "pw-for-a-local-process")    # a local process gets it ...
        self.assertNotIn("ORDERS_DB_PASSWORD", integration_bind.env_of(pkg))     # ... settings alone hold none
        kinds = [r["event"]["kind"] for r in self.project.ledger().records()]
        self.assertIn("integrations_waiting", kinds)
        self.assertIn("integrations_bound", kinds)

    def test_FR_DS2_AC_2_a_changed_binding_needs_a_new_card_and_a_declined_one_stops_the_release(self):
        first = deliver(self.project)["waiting_on"]
        roads = copy.deepcopy(ROADS)
        roads["roads"]["local"]["integrations"]["orders_db"]["endpoint"] = "https://orders-replica.internal/api"
        write_json(self.factory.paved_roads_path, roads)
        second = deliver(self.project)["waiting_on"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.canon.get_card(first)["state"], "withdrawn")
        self.assertIn("orders-replica", self.canon.get_card(second)["body"])
        roads["roads"]["local"]["integrations"]["orders_db"]["endpoint"] = "http://orders.internal/api"
        write_json(self.factory.paved_roads_path, roads)
        third = self.canon.get_card(deliver(self.project)["waiting_on"])
        self.assertIn("problem", third["title"])                              # a wrong binding is shown, not run
        self.assertIn("https", third["body"])
        self.decide(third["id"], "declined", "it", person="Jaana", reason="not over plain http")
        out = deliver(self.project)
        self.assertEqual((out["state"], out["failed_step"]), ("failed", "integrations"))
        self.assertIn("declined the binding of orders_db", out["reason"])
        self.assertFalse(self.project.path("envs").exists())


class DockerSecretTest(DeliveryTestCase):
    maturity = "pilot"

    def test_FR_DS5_AC_1_a_docker_product_gets_its_credential_by_name_and_the_value_only_in_the_clis_environment(self):
        rev = self.main()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
        server.version = rev[:12]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        calls: list = []

        def runner(argv, timeout, env=None):
            calls.append((list(argv), dict(env or {})))
            return (0, f"127.0.0.1:{server.server_address[1]}\n", "") if argv[1] == "port" else (0, "", "")

        cli = roadmod.DockerCLI(runner=runner)
        road = roadmod.DockerRoad("team", {"kind": "docker", "rules": {"tls": "proxy", "egress": "none"}}, docker=cli)
        self.addCleanup(roadmod.stop_all, self.project, None, docker=cli)
        pkg = road.package(self.project, env="staging", slot="current", release=1, revision=rev,
                           artifact={"type": "image", "ref": f"gf-{self.project.pid}:{rev[:12]}"})
        integration_bind.wire(pkg, {"integrations": {"staging": {"orders_db": {
            "state": "approved", "card": "C-0009", "pin": "p" * 64, "by": "Jaana", "declaration": DECLARED,
            "binding": ROADS["roads"]["local"]["integrations"]["orders_db"]}}}}, "staging")
        value = "pw-" + uuid.uuid4().hex
        with mock.patch.dict("os.environ", {"RIHMA_TEST_ORDERS_PASSWORD": value}):
            road.deploy(self.project, pkg)
        argv, env = next(c for c in calls if c[0][1] == "run")
        self.assertIn("ORDERS_DB_URL=https://orders-data.internal/api", argv)       # the settings as values
        self.assertEqual(argv[argv.index("ORDERS_DB_PASSWORD") - 1], "--env")       # the credential by name
        self.assertNotIn(value, " ".join(argv))
        self.assertEqual(env, {"ORDERS_DB_PASSWORD": value})                       # its value: the CLI's env only
        self.assertEqual([e for a, e in calls if a[1] != "run" and e], [])          # no other command gets it
        for path in self.project.dir.rglob("*"):                                    # no record holds it
            if path.is_file():
                self.assertNotIn(value, path.read_text(encoding="utf-8", errors="replace"), path)
        calls.clear()
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("RIHMA_TEST_ORDERS_PASSWORD", None)
            road.deploy(self.project, pkg)                                          # not on this host: not given
        argv, env = next(c for c in calls if c[0][1] == "run")
        self.assertNotIn("ORDERS_DB_PASSWORD", argv)
        self.assertEqual(env, {})


# A credential the docker CLI gets in its own environment, named like a variable the CLI reads.
STEERING = {"docker": "DOCKER_HOST", "docker_cfg": "DOCKER_CFG_CONFIG", "http": "HTTP_PROXY", "https": "HTTPS_PROXY",
            "no": "NO_PROXY", "ssl": "SSL_CERT_FILE", "ld": "LD_PRELOAD"}


class ToolingNamesTest(unittest.TestCase):
    def test_FR_DS5_AC_2_a_credential_named_like_a_variable_the_deploy_tools_read_never_reaches_them(self):
        for name, cred in STEERING.items():
            decl = {"name": name, "kind": "rest", "access": "read", "data_classes": ["internal"],
                    "credentials": [cred], "purpose": "x"}
            self.assertIn("/name", [r["path"] for r in integration_decl.check(decl)], name)   # never declared
            binding = {"endpoint": "https://api.internal/v1", "secrets": [{"name": cred, "ref": "env:SOME_VAR"}]}
            said = integration_bind.binding_problems(dict(decl, via="http"), binding, "local")
            self.assertTrue([p for p in said if cred in p and "deploy tools" in p], (name, said))  # never approved
        self.assertEqual(integration_decl.check(dict(ORDERS)), [])                   # a plain one still is
        pkg = {"settings": {"DOCKER_URL": "https://api.internal/v1", "DOCKER_ACCESS": "read", "DOCKER_KIND": "rest"},
               "secrets": [{"name": "DOCKER_HOST", "ref": "env:SOME_VAR"}],
               "integrations": [{"name": "docker", "kind": "rest", "via": "http", "access": "read",   # approved before
                                 "endpoint": "https://api.internal/v1", "card": "C-0001", "pin": "p" * 64,
                                 "settings": ["DOCKER_URL", "DOCKER_ACCESS", "DOCKER_KIND"],
                                 "secrets": ["DOCKER_HOST"]}]}
        self.assertTrue([p for p in integration_bind.package_problems(pkg) if "DOCKER_HOST" in p])  # never delivered
        calls: list = []
        cli = roadmod.DockerCLI(runner=lambda argv, timeout, env=None: calls.append(argv) or (0, "", ""))
        for cred in STEERING.values():
            with self.assertRaisesRegex(roadmod.RoadError, cred):                  # and the CLI refuses it
                cli.run("gf-x", "img", publish="127.0.0.1::8000", volume="v:/data", secrets={cred: "tcp://127.0.0.1:9"})
        self.assertEqual(calls, [])                                                # docker never ran
        cli.run("gf-x", "img", publish="127.0.0.1::8000", volume="v:/data", secrets={"ORDERS_DB_PASSWORD": "x"})
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
