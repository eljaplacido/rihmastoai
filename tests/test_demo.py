"""`rihmasto demo` (FR-N4-AC-1): one showcase factory home with no keys, no network and no Gnomon.

The demo runs once for the whole class, through the command line, with every way to Gnomon
replaced by a recorder that fails, every model key removed from the environment, and every socket
connection or name lookup beyond loopback refused. The local preview's health check is the only
connection the demo makes, and it stays on 127.0.0.1.

Each piece of the showcase is asserted on what the real kernel recorded: the website feedback chat,
the stakeholder's comment, the example scan and the risk accepted, the evidence pack, the autonomy
cap and the adopted service. The guided tour (docs/demo.md) names only commands the parser has.
"""

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import socket
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from kernel import dashboard, embeds, projections, roads, security
from kernel.adopt import NO_PUSH, is_adopted
from kernel.autonomy import cap_of
from kernel.canon import Canon
from kernel.cli import build_parser, main
from kernel.lanes import ROUTING_FILE, _git
from kernel.learn import factory_project
from kernel.signals import signals, square
from kernel.store import Factory, read_json

LOOPBACK = {"127.0.0.1", "::1", "localhost", None}
REPO = Path(__file__).resolve().parent.parent
TOUR = REPO / "docs" / "demo.md"
WEBHOOK = "Shipment webhook to the stock system"
ACCESS = "Access review check"
STOCK = "Stock levels service"


class DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-demo-test-"))
        cls.home = cls.tmp / "demo"
        cls.gnomon_calls, cls.network = [], []

        def no_gnomon(*args, **kwargs):
            cls.gnomon_calls.append(args[:1])
            raise AssertionError("the demo called Gnomon")

        real_connect, real_lookup = socket.socket.connect, socket.getaddrinfo

        def connect(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in LOOPBACK:
                cls.network.append(("connect", host))
                raise OSError(f"the test refuses a connection to {host}")
            return real_connect(sock, address)

        def lookup(host, *args, **kwargs):
            if host not in LOOPBACK:
                cls.network.append(("lookup", host))
                raise socket.gaierror(f"the test refuses a lookup of {host}")
            return real_lookup(host, *args, **kwargs)

        keys = {ep["api_key_env"] for ep in (read_json(ROUTING_FILE) or {}).get("endpoints", {}).values()
                if isinstance(ep, dict) and ep.get("api_key_env")}
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"GNOMON_CMD": "rihma-demo-test-no-such-gnomon"}))
            for key in keys | {k for k in os.environ if k.endswith("_API_KEY")}:
                os.environ.pop(key, None)
            for target in ("kernel.model.run_gnomon_task", "kernel.gate.run_gnomon_task",
                           "kernel.dispatch.run_gnomon_task", "kernel.model.gnomon_cmd",
                           "kernel.model.GnomonModel.ask", "kernel.dispatch.ingest_latest_run"):
                stack.enter_context(mock.patch(target, side_effect=no_gnomon))
            stack.enter_context(mock.patch.object(socket.socket, "connect", connect))
            stack.enter_context(mock.patch.object(socket, "getaddrinfo", lookup))
            stack.enter_context(contextlib.redirect_stdout(out))
            started = time.monotonic()
            cls.exit = main(["demo", "--home", str(cls.home)])
            cls.seconds = time.monotonic() - started
        cls.output = out.getvalue()
        cls.factory = Factory(cls.home)

    @classmethod
    def tearDownClass(cls):
        roads.stop_started()
        roads.rmtree(cls.tmp)

    def projects(self):
        return {p.meta["title"]: p for p in self.factory.projects() if not p.pid.startswith("_")}

    def kinds(self, project, kind):
        return [r["event"]["payload"] for r in project.ledger().of_kind(kind)]

    def test_FR_N4_AC_1_the_demo_builds_a_home_with_no_keys_no_network_and_no_gnomon(self):
        self.assertEqual(self.exit, 0, self.output)
        self.assertEqual(self.gnomon_calls, [])
        self.assertEqual(self.network, [])
        self.assertLess(self.seconds, 60, f"the demo took {self.seconds:.1f} s")
        self.assertIn(f"rihmasto-cockpit --home {self.home.resolve()}", self.output)
        self.assertNotIn("rihma-cockpit", self.output)                     # one name for the cockpit command
        self.assertIn(f"rihmasto-cockpit --home {self.home.resolve()}",
                      (self.home / "README.md").read_text(encoding="utf-8"))
        self.assertIn("python -m cockpit.server --home", self.output)
        for said in ("website feedback chat (E-001)", "stakeholder's comment", "Example Scanner",
                     "security gate passed", "evidence pack: exports/", "(attestable)", "autonomy cap 3",
                     "adopted to maintain; its own tests at the baseline: passed (3 of 3 passed)"):
            self.assertIn(said, self.output)
        marker = read_json(self.home / "demo.json")
        self.assertEqual(marker["schema"], "rihma.demo/1")
        self.assertEqual(set(marker["projects"]), {"loans", "webhook", "access", "stock"})
        self.assertEqual(marker["scripted"], {"model": "demo-model", "builder": "demo-builder",
                                              "scanner": "Example Scanner"})
        self.assertTrue(all(p.startswith("demo-") for p in marker["people"]), marker["people"])
        for p in self.factory.projects():                                   # nothing half-written or rewritten
            self.assertTrue(p.ledger().verify().intact, p.pid)
        for p in self.projects().values():                                  # the preview was stopped again
            self.assertEqual(roads.running_slots(p), [])

    def test_FR_N4_AC_1_the_dashboard_shows_the_demo_projects_at_their_stages(self):
        projects = self.projects()
        self.assertEqual({t: p.meta["profile"] for t, p in projects.items()},
                         {"Equipment loans": "web_service", WEBHOOK: "integration", ACCESS: "ops_agent",
                          STOCK: "web_service"})
        self.assertEqual({t: p.meta["stage"] for t, p in projects.items()},
                         {"Equipment loans": 2, WEBHOOK: 6, ACCESS: 5, STOCK: 5})
        self.assertEqual(dashboard.pipeline(self.factory)["total"], 4)
        queue = dashboard.queue(self.factory)
        self.assertEqual(queue["by_kind"], {"question": 2, "escalation": 1, "change": 2})
        self.assertGreater(queue["oldest_hours"], 1)                        # ages, not all zero
        trend = dashboard.gate_trend(self.factory)
        self.assertGreater(trend["rounds"], 0)
        self.assertIsNotNone(trend["pass_rate"])
        self.assertTrue(dashboard.activity(self.factory))
        self.assertTrue(dashboard.timeline(projects[ACCESS])["tasks"])
        self.assertEqual(len(dashboard.coverage(self.factory)["projects"]), 3)
        self.assertGreaterEqual(dashboard.catalogue(self.factory)["counts"]["proposed"], 1)
        sq = square(self.factory)
        self.assertEqual(len(sq["concepts_waiting"]), 1)
        self.assertEqual(sq["end_user_feedback_waiting"], 0)                # the chat's message was triaged
        self.assertEqual({s["state"] for s in signals(self.factory)}, {"routed", "concept"})
        # the escalation keeps the gate's objections; the webhook's escalation was retried and merged
        escalation = Canon(projects[ACCESS]).cards(kind="escalation")[0]
        self.assertTrue(any(o.startswith("fail_first:") for o in escalation["payload"]["objections"]))
        webhook = projects[WEBHOOK]
        self.assertEqual({s["status"] for s in webhook.read("tasks.json").values()}, {"merged"})
        self.assertEqual([c["decision"]["verdict"] for c in Canon(webhook).cards(state="decided", kind="escalation")],
                         ["retry"])
        release = webhook.read("releases/1.json")
        self.assertEqual((release["state"], release["maturity"]), ("done", "explore"))
        pack = webhook.read("releases/1/capability-pack.json")
        self.assertEqual((pack["format"], pack["version"]), ("rihma.capability-pack.v1", "1.0.0"))
        self.assertTrue(pack["acceptance"]["valid"])
        self.assertEqual([h["version"] for h in webhook.read("packs.json")], ["1.0.0"])  # a scan changes no version
        self.assertEqual([c["kind"] for c in Canon(webhook).cards()], ["change", "change", "update"])
        holdouts = projects[ACCESS].holdouts_dir
        self.assertTrue(list(holdouts.glob("*.json")))                      # kept in their own custody
        self.assertFalse(str(holdouts).startswith(str(projects[ACCESS].dir)))
        floor = projections.floor(self.factory)                             # what the tour says of Spend
        self.assertEqual(floor["overall"]["runs"], 0)                       # no Gnomon run is recorded
        self.assertEqual((floor["spend"]["cloud"], floor["spend"]["unmeasured_runs"]), (0.0, 0))

    def test_FR_N4_AC_1_a_website_feedback_chat_files_one_end_user_message_as_a_triaged_change(self):
        webhook = self.projects()[WEBHOOK]
        [e] = embeds.embeds(self.factory)
        self.assertEqual((e["kind"], e["project"], e["state"], e["messages"]), ("feedback", webhook.pid, "active", 1))
        self.assertEqual((e["created_by"], e["persona"], e["origins"]),
                         ("demo-product", "product_owner", ["https://warehouse.example"]))
        self.assertNotIn("key", e)                                          # only the key's hash is kept
        self.assertEqual(len(e["key_sha256"]), 64)
        self.assertIsNone(re.search(r"rk_[A-Za-z0-9_-]{24,}", self.output))  # the key is never printed
        [card] = [c for c in Canon(webhook).cards(kind="change") if c["payload"]["source"] == "end_user"]
        self.assertEqual(card["payload"]["person"], f"end user via embed {e['id']}")
        self.assertTrue(card["payload"]["text"].startswith(f"[embed {e['id']}] "))
        self.assertIn("Person: We also need the expected arrival time", card["payload"]["text"])
        triage = card["payload"]["triage"]
        self.assertEqual((triage["by"], triage["class"], triage["needs_decision"]), ("rules", "new_requirement", True))
        filed = self.kinds(factory_project(self.factory), "embed_created")
        self.assertEqual([(x["id"], x["created_by"]) for x in filed], [(e["id"], "demo-product")])

    def test_FR_N4_AC_1_a_stakeholder_comments_on_a_requirement_and_it_decides_nothing(self):
        webhook = self.projects()[WEBHOOK]
        [c] = Canon(webhook).comments({"kind": "requirement", "id": "R-2"})
        self.assertEqual((c["person"], c["persona"], c["promoted_to"]), ("demo-stakeholder", "stakeholder", None))
        self.assertIn("relabelled parcel", c["text"])
        self.assertIn("R-2", {r["id"] for r in webhook.read("spec.json")["requirements"]})
        self.assertEqual([x["id"] for x in self.kinds(webhook, "comment")], [c["id"]])

    def test_FR_N4_AC_1_an_example_scan_is_ingested_and_its_error_accepted_as_a_risk_with_a_reason(self):
        webhook = self.projects()[WEBHOOK]
        sarif = read_json(self.home / "scans" / "example-scanner.sarif")
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertEqual(sarif["runs"][0]["tool"]["driver"]["name"], "Example Scanner")
        found = {f["rule"]: f for f in security.findings(webhook)}
        self.assertEqual({r: (f["level"], f["state"], f["cwe"]) for r, f in found.items()},
                         {"EX-AUTH-001": ("error", "accepted", ["CWE-306"]),
                          "EX-INPUT-002": ("warning", "open", ["CWE-20"])})
        routes = _git(webhook.path("repo.git"), "show", "main:app/routes.py").splitlines()
        for rule, said in (("EX-AUTH-001", '@route("POST", "/webhooks/shipments")'),
                           ("EX-INPUT-002", 'int(item.get("qty", 1))')):
            loc = found[rule]["location"]                                   # each result points at its own line
            self.assertEqual(loc["uri"], "app/routes.py")
            self.assertIn(said, routes[loc["line"] - 1])
        acc = found["EX-AUTH-001"]["acceptance"]
        self.assertEqual((acc["person"], acc["persona"]), ("demo-compliance", "compliance"))
        self.assertIn("Q-003", acc["reason"])
        self.assertGreater(dt.date.fromisoformat(acc["expires"]), dt.date.today())
        self.assertEqual(security.security_gate(webhook, record=False)["verdict"], "passed")
        [scan] = self.kinds(webhook, "security_scan")
        self.assertEqual((scan["by"], scan["persona"], scan["counts"]["error"], scan["counts"]["warning"]),
                         ("demo-dev", "developer", 1, 1))
        gates = [g["verdict"] for g in self.kinds(webhook, "security_gate")]
        self.assertEqual(gates[-1], "passed")
        self.assertIn("not measured", gates[:-1])                          # before the scan: never "passed"
        self.assertEqual([a["person"] for a in self.kinds(webhook, "risk_accepted")], ["demo-compliance"])

    def test_FR_N4_AC_1_the_webhook_evidence_pack_is_exported_into_the_demo_home(self):
        webhook = self.projects()[WEBHOOK]
        [pack] = list((self.home / "exports").glob("*.zip"))
        self.assertTrue(pack.name.startswith(f"{webhook.pid}-evidence-"))
        with zipfile.ZipFile(pack) as z:
            manifest = json.loads(z.read("MANIFEST.json"))
            attestation = json.loads(z.read("attestation.json"))
            sec = json.loads(z.read("security.json"))
            capability = json.loads(z.read("capability-pack.json"))
            names = set(z.namelist())
        self.assertEqual((manifest["exported_by"], manifest["persona"]), ("demo-compliance", "compliance"))
        self.assertEqual(set(manifest["files"]), names - {"MANIFEST.json"})
        self.assertEqual(attestation["verdict"], "attestable")
        self.assertEqual([s["tool"] for s in sec["scans"]], ["Example Scanner"])
        self.assertEqual([(a["rule"], a["person"]) for a in sec["accepted_risks"]],
                         [("EX-AUTH-001", "demo-compliance")])
        self.assertEqual(capability["version"], "1.0.0")
        [exported] = self.kinds(webhook, "evidence_exported")
        self.assertEqual((exported["file"], exported["by"], exported["verdict"]), (pack.name, "demo-compliance",
                                                                                   "attestable"))

    def test_FR_N4_AC_1_the_access_review_autonomy_is_capped_by_a_demo_person_with_a_reason(self):
        access = self.projects()[ACCESS]
        self.assertEqual((cap_of(access), access.meta["autonomy_cap"]), (3, 3))
        [cap] = self.kinds(access, "autonomy_cap_set")
        self.assertEqual((cap["scope"], cap["to"], cap["by"], cap["persona"]), ("project", 3, "demo-compliance",
                                                                                 "compliance"))
        self.assertIn("staging or production", cap["reason"])
        for title, p in self.projects().items():                            # the other projects keep the default
            if title != ACCESS:
                self.assertEqual(cap_of(p), 4, title)

    def test_FR_N4_AC_1_an_existing_local_service_is_adopted_to_maintain_it(self):
        stock = self.projects()[STOCK]
        self.assertTrue(is_adopted(stock))
        adopted = stock.read("adopted.json")
        upstream = self.home / "existing" / "stock-levels"
        self.assertEqual((adopted["intent"], adopted["source_kind"], adopted["default_branch"]),
                         ("maintain", "path", "main"))
        self.assertEqual(Path(adopted["source"]).resolve(), upstream.resolve())
        self.assertEqual(adopted["adopted_by"], {"person": "demo-dev", "persona": "developer"})
        self.assertEqual(_git(stock.path("repo.git"), "config", "remote.upstream.pushurl"), NO_PUSH)
        self.assertEqual(adopted["baseline"], _git(upstream, "rev-parse", "HEAD"))
        baseline = stock.read("baseline.json")                              # its own suite, run once
        self.assertEqual(baseline["verdict"], "passed")
        self.assertEqual(baseline["runs"][0]["runner"], "unittest")
        self.assertEqual(baseline["runs"][0]["counts"], {"ran": 3, "passed": 3, "failed": 0, "errors": 0,
                                                         "skipped": 0})
        self.assertEqual({r["id"]: r["provenance"] for r in stock.read("spec.json")["requirements"]},
                         {"R-1": "observed"})
        self.assertEqual({t["status"] for t in stock.read("tasks.json").values()}, {"merged"})
        self.assertEqual(Canon(stock).cards(), [])                          # nothing to build until a change
        self.assertEqual((stock.meta["maturity"], stock.meta["stage"]), ("production", 5))
        from kernel import asks, machines, wip
        from kernel.gnomon_posture import view as gnomon_posture

        self.assertTrue(gnomon_posture.build(self.factory, stock)["measured"])
        self.assertGreaterEqual(wip.read(stock, fresh=True)["changed"]["total"], 1)
        self.assertTrue(any(m["name"] == "demo-laptop" for m in machines.listed(self.factory)))
        self.assertEqual(len(asks.listed(stock)), 1)

    def test_FR_N4_AC_1_every_decision_in_the_demo_is_made_by_a_demo_persona(self):
        decisions = []
        filed_by_embed = {f"end user via embed {e['id']}" for e in embeds.embeds(self.factory)}
        for p in self.factory.projects():
            decisions += Canon(p).project.read("canon/decisions.json", []) or []
            for rec in p.ledger().records():
                kind, pl = rec["event"]["kind"], rec["event"]["payload"]
                for key in ("person", "by", "chosen_by", "validated_by", "approved_by", "created_by"):
                    if not isinstance(pl.get(key), str) or not pl[key]:
                        continue
                    if kind == "change_submitted" and pl.get("persona") == "end_user" and pl[key] in filed_by_embed:
                        continue                                    # a website visitor's message, not a decision
                    self.assertTrue(pl[key].startswith("demo-"), (p.pid, kind, key, pl[key]))
            for q in Canon(p).questions("answered"):
                self.assertTrue(q["answer"]["by"].startswith("demo-"))
            source = p.read("source.json") or {}
            if source.get("requested_by"):
                self.assertTrue(source["requested_by"].startswith("demo-"))
        self.assertGreaterEqual(len(decisions), 2)
        for d in decisions:
            self.assertTrue(d["person"].startswith("demo-"), d)
        for s in signals(self.factory):
            self.assertTrue(s["person"].startswith("demo-"), s)
        for c in Canon(factory_project(self.factory)).cards(state="decided"):
            self.assertTrue(c["decision"]["person"].startswith("demo-"))

    def test_FR_N4_AC_1_the_demo_never_overwrites_a_folder_that_is_not_a_demo_home(self):
        other = self.tmp / "real-home"
        (other / "projects").mkdir(parents=True)
        keep = other / "paved_roads.json"
        keep.write_text("{}", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = main(["demo", "--home", str(other)])
        self.assertEqual(code, 2)
        self.assertIn("not a demo home", err.getvalue())
        self.assertTrue(keep.exists())
        shutil.rmtree(other)


def _commands(parser: argparse.ArgumentParser) -> dict:
    """A parser's subcommands by name (empty when it has none)."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


class DemoTourTest(unittest.TestCase):
    """docs/demo.md, the guided tour of the demo home."""

    COMMAND = re.compile(r"(?<![\w-])(?:rihmasto|rihma|kernel\.cli)[ \t]+([a-z][a-z-]*)(?:[ \t]+([a-z][a-z-]*))?")
    CODE = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)

    def test_FR_N4_AC_2_the_demo_tour_names_only_commands_the_parser_has(self):
        text = TOUR.read_text(encoding="utf-8")
        named = set()
        for block in self.CODE.findall(text):
            named.update(self.COMMAND.findall(block))
        self.assertGreaterEqual(len({cmd for cmd, _ in named}), 8, named)
        top, missing = _commands(build_parser()), []
        for cmd, sub in sorted(named):
            group = _commands(top[cmd]) if cmd in top else None
            if group is None or (group and sub not in group):           # a group's command must name one of its own
                missing.append(f"{cmd} {sub}".strip())
        self.assertEqual(missing, [], f"named in docs/demo.md but not in the parser: {missing}")

    def test_FR_N4_AC_2_the_demo_tour_covers_every_lens_and_names_no_machine(self):
        text = TOUR.read_text(encoding="utf-8")
        for lens in ("Business", "Concept", "Delivery", "Operations", "Compliance", "Insight"):
            self.assertRegex(text, rf"(?m)^#+ .*\b{lens}\b", lens)
        for piece in ("Example Scanner", "E-001", "R-2", "exports/", "Stock levels service", "autonomy"):
            self.assertIn(piece, text)
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]+Users[\\/]|/(?:home|Users)/[a-z]", text))
        self.assertIsNone(re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", text.replace("127.0.0.1", "")))

