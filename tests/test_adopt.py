import contextlib
import importlib.util
import io
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel.adopt import NO_PUSH, AdoptionRefused, adopt, check_source, first_paragraph, probe, sync  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.compile import contract_check  # noqa: E402
from kernel.dispatch import ready_tasks  # noqa: E402
from kernel.lanes import GIT_ID, _git  # noqa: E402

README = """# Legacy loans

[![build](https://ci.example/badge.svg)](https://ci.example)

A small service that tracks which workshop equipment is lent to whom.
It has run on the team's server since 2019.

## Install

pip install -r requirements.txt
"""

LOANS = '''def add(items, name):
    name = str(name).strip()
    if not name:
        raise ValueError("name is required")
    items.append({"id": len(items) + 1, "name": name})
    return items[-1]
'''

APP = '''from flask import Flask

from loans import add

app = Flask(__name__)


@app.route("/items", methods=["GET", "POST"])
def items():
    return {}


@app.get("/health")
def health():
    return {"status": "ok"}
'''

SERVER_JS = """const express = require('express');
const app = express();
app.get('/api/loans', (req, res) => res.json([]));
app.delete("/api/loans/:id", (req, res) => res.sendStatus(204));
"""

TESTS = '''import unittest

from loans import add


class LoansTest(unittest.TestCase):
    def test_add_gives_an_id(self):
        self.assertEqual(add([], "drill")["id"], 1)

    def test_add_refuses_an_empty_name(self):
        with self.assertRaises(ValueError):
            add([], " ")
'''

FAILING_TEST = '''import unittest


class Broken(unittest.TestCase):
    def test_this_already_fails_upstream(self):
        self.assertEqual(1, 2)
'''


def make_repo(root: Path, files: dict) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    commit(root, files, "initial")
    return root


def commit(root: Path, files: dict, message: str) -> str:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    _git(root, "add", "-A")
    _git(root, *GIT_ID, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def python_repo(root: Path, **extra) -> Path:
    return make_repo(root, {"README.md": README, "loans.py": LOANS, "app.py": APP, "server.js": SERVER_JS,
                            "tests/__init__.py": "", "tests/test_loans.py": TESTS,
                            "Dockerfile": "FROM python:3.12-slim\nCOPY . /app\n", **extra})


def refs(repo: Path) -> str:
    return _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")


def kinds(project) -> list:
    return [r["event"]["kind"] for r in project.ledger().records()]


class _Answer(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"legacy loans"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class AdoptTest(FactoryTestCase):
    def test_FR_X1_AC_1_a_local_repository_is_adopted_with_inventory_baseline_as_is_spec_and_contract(self):
        src = python_repo(self.tmp / "src")
        before = refs(src)
        p = adopt(self.factory, "Legacy loans", source=str(src), intent="maintain", person="Aino",
                  persona="developer", which=lambda name: None)
        meta = p.meta
        self.assertEqual((meta["source_kind"], meta["intent"], meta["stage"]), ("adopted", "maintain", 5))
        self.assertTrue(meta.get("profile"))                                         # proposed by rule
        chosen = [r["event"]["payload"] for r in p.ledger().of_kind("profile_chosen")]
        self.assertEqual(chosen[-1]["basis"]["by"], "rule")
        # the mirror: main is the upstream's head at adoption, the baseline
        adopted = p.read("adopted.json")
        self.assertEqual(adopted["baseline"], _git(src, "rev-parse", "HEAD"))
        self.assertEqual(_git(p.path("repo.git"), "rev-parse", "main"), adopted["baseline"])
        self.assertEqual(adopted["source"], src.resolve().as_posix())
        # the inventory, by rule
        inv = p.read("inventory.json")
        self.assertEqual(inv["languages"][0]["language"], "Python")
        self.assertIn("JavaScript", [x["language"] for x in inv["languages"]])
        self.assertTrue(inv["test_command"]["detected"])
        self.assertEqual(inv["test_command"]["runner"], "unittest")
        self.assertIn("workshop equipment is lent", inv["readme"]["first_paragraph"])
        self.assertNotIn("Install", inv["readme"]["first_paragraph"])
        self.assertEqual(inv["dockerfile"], {"present": True, "files": ["Dockerfile"]})
        self.assertFalse(inv["endpoints"]["scanned"])                                # no base_url: not scanned
        # the characterisation baseline: existing behaviour, not a spec
        base = p.read("baseline.json")
        self.assertEqual(base["verdict"], "passed")
        self.assertEqual(base["meaning"], "existing behaviour, not a spec")
        self.assertEqual(base["runs"][0]["counts"]["passed"], 2)
        self.assertEqual(base["runs"][0]["counts"]["failed"], 0)
        # the as-is spec, observed, compiled into a contract and a check plan
        spec = p.read("spec.json")
        self.assertEqual({r["provenance"] for r in spec["requirements"]}, {"observed"})
        crit = spec["requirements"][0]["acceptance"][0]
        self.assertEqual((crit["kind"], crit["then"]), ("test", "the existing test suite keeps passing"))
        contract = p.read("contract.json")
        report, _ = contract_check().check(contract)
        self.assertEqual(report.violations, [])
        req = contract["requirements"][0]
        self.assertEqual(req["provenance"], "vendor-proposed")
        self.assertIn("observed", req["notes"])
        self.assertTrue(p.read("checkplan.json")["checks"])
        self.assertEqual(meta["contract_revision"], contract["revision"])
        self.assertEqual(ready_tasks(p), [])                                         # nothing to build yet
        for kind in ("adopted", "inventory_taken", "characterised", "as_is_spec_written", "contract_compiled",
                     "adoption_tasks"):
            self.assertIn(kind, kinds(p))
        self.assertIn("existing behaviour", Canon(p).brief)
        # the upstream is never pushed to
        self.assertEqual(refs(src), before)
        self.assertEqual(_git(p.path("repo.git"), "config", "remote.upstream.pushurl"), NO_PUSH)
        with self.assertRaises(RuntimeError):
            _git(p.path("repo.git"), "push", "-q", "upstream", "main:refs/heads/from-rihma")
        self.assertEqual(refs(src), before)
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_X1_AC_1_a_failing_suite_is_recorded_as_existing_behaviour_not_judged(self):
        src = python_repo(self.tmp / "src", **{"tests/test_broken.py": FAILING_TEST})
        p = adopt(self.factory, "Legacy loans", source=str(src), intent="improve", person="Aino",
                  persona="product_owner", profile="web_service", which=lambda name: None)
        base = p.read("baseline.json")
        self.assertEqual(base["verdict"], "failed")
        self.assertEqual((base["runs"][0]["counts"]["passed"], base["runs"][0]["counts"]["failed"]), (2, 1))
        self.assertIn("existing behaviour", base["reason"])
        self.assertEqual(p.meta["stage"], 5)
        self.assertEqual(p.meta["profile"], "web_service")                           # a person's choice stands

    def test_FR_X1_AC_1_other_toolchains_are_not_measured_unless_on_path_and_nothing_is_guessed(self):
        node = make_repo(self.tmp / "node", {
            "README.md": "Ticket sync between the help desk and the CRM.\n",
            "package.json": json.dumps({"name": "x", "scripts": {"test": "node test.js"}}),
            "index.js": "module.exports = 1;\n", "go.mod": "module example.com/x\n",
            "x_test.go": "package x\n"})
        p = adopt(self.factory, "Ticket sync", source=str(node), intent="maintain", person="Aino",
                  persona="developer", which=lambda name: None)
        inv = p.read("inventory.json")
        self.assertEqual([t["runner"] for t in inv["tests"]], ["npm", "go test"])
        base = p.read("baseline.json")
        self.assertEqual(base["verdict"], "not measured")
        self.assertTrue(all("toolchain not run by the kernel" in r["reason"] for r in base["runs"]))
        self.assertEqual(len(p.read("spec.json")["requirements"][0]["acceptance"]), 2)  # one per suite
        bare = make_repo(self.tmp / "bare", {"README.md": "Just a script.\n", "run.sh": "echo hi\n"})
        q = adopt(self.factory, "A script", source=str(bare), intent="maintain", person="Aino", persona="developer")
        self.assertFalse(q.read("inventory.json")["test_command"]["detected"])
        self.assertEqual(q.read("baseline.json")["reason"], "not measured: no test command was detected by rule")
        self.assertIn("no test command was detected", q.read("spec.json")["requirements"][0]["acceptance"][0]["when"])
        self.assertTrue(q.read("contract.json")["revision"])

    def test_FR_X1_AC_1_pytest_is_detected_by_rule_and_run_only_if_installed(self):
        src = make_repo(self.tmp / "src", {"README.md": "Pricing rules.\n", "pytest.ini": "[pytest]\n",
                                           "pricing.py": "def price(n):\n    return n * 2\n",
                                           "tests/test_pricing.py": "from pricing import price\n\n\n"
                                                                    "def test_price():\n    assert price(2) == 4\n"})
        p = adopt(self.factory, "Pricing", source=str(src), intent="maintain", person="Aino", persona="developer")
        tc = p.read("inventory.json")["test_command"]
        self.assertEqual((tc["runner"], tc["basis"]), ("pytest", "pytest.ini"))
        base = p.read("baseline.json")
        if importlib.util.find_spec("pytest") is None:
            self.assertEqual(base["verdict"], "not measured")
            self.assertIn("pytest is not installed", base["reason"])
        else:
            self.assertEqual(base["verdict"], "passed")
            self.assertEqual(base["runs"][0]["counts"]["passed"], 1)

    def test_FR_X1_AC_1_monitor_probes_the_running_service_and_finds_declared_routes(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            src = python_repo(self.tmp / "src")
            p = adopt(self.factory, "Legacy loans", source=str(src), intent="monitor", person="Ilkka",
                      persona="operations", base_url=url + "/", which=lambda name: None)
            self.assertEqual(p.meta["stage"], 7)
            found = {(e["method"], e["path"]) for e in p.read("inventory.json")["endpoints"]["found"]}
            self.assertLessEqual({("GET", "/items"), ("POST", "/items"), ("GET", "/health"), ("GET", "/api/loans"),
                                  ("DELETE", "/api/loans/:id")}, found)
            probe_req = p.read("spec.json")["requirements"][1]
            self.assertEqual(probe_req["acceptance"][0], {"id": "R-2-AC-1", "given": "the service as it runs today",
                                                          "when": f"GET {url}", "then": f"GET {url} answers",
                                                          "kind": "probe"})
            self.assertEqual(p.read("contract.json")["requirements"][1]["acceptance"][0]["check"]["kind"], "probe")
            self.assertTrue((p.holdouts_dir / "R-2-AC-1.json").exists())             # in the holdout custody
            self.assertEqual([r["event"]["payload"]["verdict"] for r in p.ledger().of_kind("probed")], ["passed"])
        finally:
            server.shutdown()
            server.server_close()
        out = probe(p)                                                               # the service went away
        self.assertEqual(out["verdict"], "failed")
        card = Canon(p).get_card(out["incident"])
        self.assertEqual(card["kind"], "incident")

    def test_FR_X1_AC_1_credentials_and_unknown_transports_are_refused_before_anything_is_fetched(self):
        for source in ("https://aino:s3cret@git.example/loans.git", "https://token@git.example/loans.git",
                       "https://git.example/loans.git?access_token=abc", "git@github.com:org/loans.git",
                       "ssh://git.example/loans.git", "ext::sh -c touch% /tmp/pwned", str(self.tmp / "missing")):
            with self.assertRaises(AdoptionRefused, msg=source):
                check_source(source)
        self.assertEqual(check_source("https://git.example/loans.git"), ("url", "https://git.example/loans.git"))
        src = python_repo(self.tmp / "src")
        with self.assertRaises(AdoptionRefused):
            adopt(self.factory, "x", source=str(src), intent="rewrite", person="Aino", persona="developer")
        with self.assertRaises(AdoptionRefused):
            adopt(self.factory, "x", source=str(src), intent="monitor", person="assistant", persona="developer")
        self.assertEqual(self.factory.projects(), [])                                # nothing half-adopted

    def test_FR_X1_AC_1_the_readme_paragraph_is_taken_by_rule(self):
        self.assertEqual(first_paragraph("Title\n=====\n\nThe first real paragraph\ncontinues.\n\nSecond."),
                         "The first real paragraph continues.")
        self.assertEqual(first_paragraph("# T\n\n```\ncode\n```\n\nText here.\n"), "Text here.")

    def test_FR_X1_AC_1_the_cli_adopts_and_syncs(self):
        from kernel.cli import main

        src = python_repo(self.tmp / "src")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["--home", str(self.tmp / "home"), "adopt", "Legacy loans", "--source", str(src),
                         "--intent", "maintain", "--person", "Aino", "--persona", "developer"])
        out = json.loads(buf.getvalue())
        self.assertEqual((code, out["stage"], out["characterisation"]["verdict"]), (0, 5, "passed"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["--home", str(self.tmp / "home"), "sync", out["project"]])
        self.assertEqual(json.loads(buf.getvalue())["upstream"]["new_commits"], 0)


class SyncTest(FactoryTestCase):
    def test_FR_X1_AC_2_sync_records_drift_and_opens_a_change_card_when_upstream_moved(self):
        src = python_repo(self.tmp / "src")
        p = adopt(self.factory, "Legacy loans", source=str(src), intent="maintain", person="Aino",
                  persona="developer", which=lambda name: None)
        baseline = p.read("adopted.json")["baseline"]
        quiet = sync(p)                                                              # nothing moved
        self.assertEqual((quiet["new_commits"], quiet["files_changed"], quiet["card"]), (0, 0, None))
        self.assertEqual(Canon(p).cards(kind="change"), [])
        head = commit(src, {"loans.py": LOANS + "\n\ndef count(items):\n    return len(items)\n",
                            "CHANGELOG.md": "- count\n"}, "Add count")
        before = refs(src)
        drift = sync(p)
        self.assertEqual((drift["baseline"], drift["upstream"]), (baseline, head))
        self.assertEqual((drift["new_commits"], drift["files_changed"]), (1, 2))
        self.assertEqual(sorted(drift["files"]), ["CHANGELOG.md", "loans.py"])
        card = Canon(p).get_card(drift["card"])
        self.assertEqual((card["kind"], card["title"]), ("change", "Upstream changed: review"))
        self.assertEqual((card["payload"]["person"], card["payload"]["source"]), ("upstream sync", "developer"))
        self.assertIn("Add count", card["payload"]["text"])
        synced = [r["event"]["payload"] for r in p.ledger().of_kind("upstream_synced")]
        self.assertEqual([s["new_commits"] for s in synced], [0, 1])
        self.assertEqual(_git(p.path("repo.git"), "rev-parse", "main"), baseline)    # main is not moved by a sync
        again = sync(p)                                                              # no new move: no new card
        self.assertEqual((again["new_commits"], again["card"]), (1, None))
        self.assertEqual(len(Canon(p).cards(kind="change")), 1)
        self.assertEqual(refs(src), before)                                          # never pushed to
        commit(src, {"README.md": README + "\nMore.\n"}, "Docs")
        before = refs(src)
        third = sync(p)
        self.assertEqual(third["new_commits"], 2)
        self.assertIsNotNone(third["card"])
        self.assertEqual(len(Canon(p).cards(kind="change")), 2)
        self.assertEqual(refs(src), before)

    def test_FR_X1_AC_2_sync_of_a_project_that_was_not_adopted_is_refused(self):
        p = self.new()
        with self.assertRaises(ValueError):
            sync(p)


if __name__ == "__main__":
    unittest.main()
