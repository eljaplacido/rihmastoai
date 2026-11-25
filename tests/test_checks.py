"""FR-CHK1: pluggable checks for maintenance and administration, and Health.

Each check runs with its tool present (a stand-in on PATH written by the test) and absent (not measured,
never passed); CI status comes from a 127.0.0.1 stand-in for the GitHub API; the probe asks a 127.0.0.1
server. Every result is recorded (check_ran in the ledger, the evidence with the project), a schedule runs
what is due with the rights of the person who enabled it, and a failure logs a signal or opens a change
once per change of verdict. No network beyond 127.0.0.1.
"""

import contextlib
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from console_fakes import PERSON, Stub, attached, fake_tool, git_only, git_repo, printing  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import access as kaccess  # noqa: E402
from kernel import checks  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.checks import automation_hook  # noqa: E402
from kernel.checks import health as chealth  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.signals import signals  # noqa: E402
from kernel.store import write_json  # noqa: E402

TOKEN = "gho_" + "Z" * 36            # built at run time, so no token-shaped literal ships
PLANTED = "AKIA" + "QWERTYUIOPASDF12"   # an AWS-shaped key the secret scan must find in the workspace
LOCK = {"name": "shop", "lockfileVersion": 3, "packages": {
    "": {"name": "shop", "version": "1.0.0", "license": "MIT"},
    "node_modules/left-pad": {"version": "1.3.0", "license": "MIT"},
    "node_modules/copyleft-lib": {"version": "2.0.0", "license": "GPL-3.0-or-later"}}}


class ChecksCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.repo = git_repo(self.tmp / "shop", {
            "README.md": "# Shop\n", "requirements.txt": "requests==2.31.0\nflask==3.0.0\n",
            "tests/test_ok.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n"
                                "        self.assertTrue(True)\n"})
        self.p = attached(self.factory, self.repo, "Shop")

    def only_bin(self):
        """PATH holds only the tools the test wrote (git stays reachable for the workspace, and nothing beside it:
        a hosted Linux runner's /usr/bin also holds gh)."""
        git = git_only(self.tmp / "git-only")
        env = {"PATH": os.pathsep.join([str(self.bin), str(git)])}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            os.environ.pop(name, None)

    def enable_run(self, key, **config):
        cstore.enable(self.p, key, person=PERSON, persona="developer", config=config or None)
        return cstore.run(self.p, key, person=PERSON, persona="developer")


class CatalogueTest(ChecksCase):
    def test_FR_CHK1_AC_1_checks_are_enabled_and_disabled_signed_and_recorded_per_project_or_across(self):
        kinds = [c["kind"] for c in checks.public()]
        self.assertEqual(kinds, ["tests", "custom", "ci", "dependencies", "secrets", "repo_gate", "security_gate",
                                 "licences", "sbom", "probe", "executions",    # executions: a Cloud Run job's
                                 "destinations"])                              # every destination (FR-DST1)
        out = cstore.enable(self.p, "probe:prod", person=PERSON, persona="operations",
                            config={"url": "https://shop.example/health"}, every="15m", on_fail=["signal"])
        self.assertEqual((out["kind"], out["every"], out["by"]["person"]), ("probe", "15m", PERSON))
        rec = self.p.ledger().of_kind("check_enabled")[-1]["event"]["payload"]
        self.assertEqual((rec["check"], rec["person"], rec["persona"]), ("probe:prod", PERSON, "operations"))
        before = self.p.path("ledger.jsonl").read_text(encoding="utf-8")
        refusals = [("probe", {"url": "https://x.example"}, "end_user", "checks are set and run by"),
                    ("tests", None, "compliance", "the console on"),           # it runs code: a console persona
                    ("probe", {}, "developer", "needs url"), ("probe", {"colour": "red"}, "developer", "takes url"),
                    ("nonesuch", None, "developer", "a check is one of")]
        for key, config, persona, words in refusals:
            with self.assertRaises(ValueError) as caught:
                cstore.enable(self.p, key, person=PERSON, persona=persona, config=config)
            self.assertIn(words, str(caught.exception))
        with self.assertRaises(ValueError):
            cstore.enable(self.p, "secrets", person=PERSON, persona="developer", every="soon")
        self.assertEqual(self.p.path("ledger.jsonl").read_text(encoding="utf-8"), before)
        cstore.disable(self.p, "probe:prod", person=PERSON, persona="it")
        self.assertNotIn("probe:prod", cstore.enabled(self.p))
        self.assertEqual(self.p.ledger().of_kind("check_disabled")[-1]["event"]["payload"]["person"], PERSON)
        other = self.factory.new_project("Loans", maturity="demo", mode="mixed")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), "checks", "enable", self.p.pid, "sbom", "--every", "1d",
                         "--all-projects", "--person", PERSON, "--persona", "developer"])
        self.assertEqual(code, 0)
        self.assertEqual(sorted(r["project"] for r in json.loads(out.getvalue())), sorted([self.p.pid, other.pid]))
        self.assertIn("sbom", cstore.enabled(other))


class SuiteTest(ChecksCase):
    def test_FR_CHK1_AC_2_the_test_suite_and_a_custom_check_pass_fail_or_are_not_measured(self):
        row = self.enable_run("tests")
        self.assertEqual(row["verdict"], "passed", row)
        self.assertIn("unittest", row["summary"])
        (self.repo / "tests" / "test_ok.py").write_text("import unittest\n\nclass T(unittest.TestCase):\n"
                                                         "    def test_no(self):\n        self.fail('broken')\n",
                                                         encoding="utf-8")
        row = cstore.run(self.p, "tests", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "failed", row)
        self.only_bin()
        fake_tool(self.bin, "lint-ok", "import sys\nprint('clean')\nsys.exit(0)\n")
        fake_tool(self.bin, "lint-bad", "import sys\nprint('3 problems')\nsys.exit(1)\n")
        self.assertEqual(self.enable_run("custom:lint", command="lint-ok")["verdict"], "passed")
        row = self.enable_run("custom:style", command="lint-bad --strict")
        self.assertEqual((row["verdict"], row["exit"]), ("failed", 1))
        self.assertIn("3 problems", "\n".join(row["evidence"]))
        row = self.enable_run("custom:gone", command="no-such-tool-here --x")
        self.assertEqual(row["verdict"], "not measured", row)
        self.assertTrue(row["summary"].startswith("not measured: "), row)


class CiTest(ChecksCase):
    def runs(self, conclusion):
        return {"workflow_runs": [{"name": "CI", "status": "completed", "conclusion": conclusion,
                                   "head_sha": "a" * 40}, {"name": "CI", "status": "completed",
                                                           "conclusion": "success", "head_sha": "b" * 40}]}

    def test_FR_CHK1_AC_3_ci_status_from_the_github_api_with_a_token_else_gh_else_not_measured(self):
        self.only_bin()
        stub = Stub({"/repos/acme/shop": (200, {"default_branch": "trunk"}),
                     "/repos/acme/shop/actions/runs": (200, self.runs("success"))})
        self.addCleanup(stub.close)
        config = {"repo": "acme/shop", "api": stub.url, "token_env": "SHOP_CI_TOKEN"}
        with mock.patch.dict(os.environ, {"SHOP_CI_TOKEN": TOKEN}):
            row = self.enable_run("ci", **config)
        self.assertEqual((row["verdict"], row["source"]), ("passed", "GitHub API"), row)
        self.assertIn("on trunk", row["summary"])
        paths = [p for p, _ in stub.seen]
        self.assertIn("/repos/acme/shop/actions/runs?branch=trunk&per_page=10", paths)
        self.assertEqual(stub.seen[-1][1]["Authorization"], f"Bearer {TOKEN}")
        stub.routes["/repos/acme/shop/actions/runs"] = (200, self.runs("failure"))
        with mock.patch.dict(os.environ, {"SHOP_CI_TOKEN": TOKEN}):
            row = cstore.run(self.p, "ci", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "failed")
        stub.routes["/repos/acme/shop/actions/runs"] = (401, {"message": "Bad credentials"})
        with mock.patch.dict(os.environ, {"SHOP_CI_TOKEN": TOKEN}):
            row = cstore.run(self.p, "ci", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "not measured")
        for where in (self.p.path("ledger.jsonl"), self.p.path("checks", "results.json"), self.p.path("checks.json")):
            self.assertNotIn(TOKEN, where.read_text(encoding="utf-8"))
        # no token: the GitHub CLI, when installed
        row = cstore.run(self.p, "ci", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "not measured")
        self.assertIn("SHOP_CI_TOKEN is not set", row["summary"])
        self.assertIn("gh) is not installed", row["summary"])
        gh_runs = [{"name": "CI", "workflowName": "CI", "status": "completed", "conclusion": "success",
                    "headSha": "c" * 40}]
        fake_tool(self.bin, "gh", "import json, sys\n"
                                  "if sys.argv[1:3] == ['repo', 'view']:\n"
                                  "    print(json.dumps({'defaultBranchRef': {'name': 'main'}}))\n"
                                  f"else:\n    print({json.dumps(json.dumps(gh_runs))})\n")
        row = cstore.run(self.p, "ci", person=PERSON, persona="developer")
        self.assertEqual((row["verdict"], row["source"]), ("passed", "gh run list"), row)


class DependencyTest(ChecksCase):
    def test_FR_CHK1_AC_4_a_dependency_audit_by_the_tools_installed_and_not_measured_without_them(self):
        self.only_bin()
        row = self.enable_run("dependencies")
        self.assertEqual(row["verdict"], "not measured")
        self.assertIn("pip-audit (or osv-scanner) is not installed", row["summary"])
        fake_tool(self.bin, "pip-audit", printing({"dependencies": [
            {"name": "requests", "version": "2.31.0", "vulns": [{"id": "PYSEC-2024-1"}]},
            {"name": "flask", "version": "3.0.0", "vulns": []}]}, exit_code=1))
        row = cstore.run(self.p, "dependencies", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "failed", row)
        self.assertIn("pip-audit found 1 known vulnerability", row["summary"])
        fake_tool(self.bin, "pip-audit", printing({"dependencies": [{"name": "flask", "vulns": []}]}))
        self.assertEqual(cstore.run(self.p, "dependencies", person=PERSON, persona="developer")["verdict"], "passed")
        (self.repo / "package-lock.json").write_text(json.dumps(LOCK), encoding="utf-8")
        row = cstore.run(self.p, "dependencies", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "not measured")                 # node is not audited here: never passed
        self.assertIn("npm (or osv-scanner) is not installed", row["summary"])
        fake_tool(self.bin, "npm", printing({"metadata": {"vulnerabilities": {"low": 0, "high": 2, "total": 2}}}, 1))
        row = cstore.run(self.p, "dependencies", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "failed")
        self.assertIn("npm found 2 known vulnerabilities", row["summary"])


class FilesTest(ChecksCase):
    def test_FR_CHK1_AC_5_the_secret_scan_licences_and_an_sbom(self):
        row = self.enable_run("secrets")
        self.assertEqual(row["verdict"], "passed", row)
        (self.repo / "settings.py").write_text(f'AWS_KEY_ID = "{PLANTED}"\n', encoding="utf-8")
        row = cstore.run(self.p, "secrets", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "failed", row)
        self.assertIn("settings.py:1", "\n".join(row["evidence"]))
        self.assertNotIn(PLANTED, json.dumps(row))                       # evidence is masked
        row = self.enable_run("licences")
        self.assertEqual(row["verdict"], "not measured")                  # no lockfile records licences
        (self.repo / "package-lock.json").write_text(json.dumps(LOCK), encoding="utf-8")
        row = cstore.run(self.p, "licences", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "failed", row)
        self.assertIn("denied: copyleft-lib@2.0.0 GPL-3.0-or-later", row["evidence"])
        lock = json.loads(json.dumps(LOCK))
        lock["packages"]["node_modules/copyleft-lib"]["license"] = "Apache-2.0"
        lock["packages"]["node_modules/mystery"] = {"version": "0.1.0"}
        (self.repo / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        self.assertEqual(cstore.run(self.p, "licences", person=PERSON, persona="developer")["verdict"], "not measured")
        del lock["packages"]["node_modules/mystery"]
        (self.repo / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
        self.assertEqual(cstore.run(self.p, "licences", person=PERSON, persona="developer")["verdict"], "passed")
        row = self.enable_run("sbom")
        self.assertEqual(row["verdict"], "passed", row)
        doc = json.loads(self.p.path("checks", row["sbom"]).read_text(encoding="utf-8"))
        self.assertEqual((doc["bomFormat"], doc["specVersion"]), ("CycloneDX", "1.5"))
        purls = {c["purl"] for c in doc["components"]}
        self.assertIn("pkg:npm/left-pad@1.3.0", purls)
        self.assertIn("pkg:pypi/requests@2.31.0", purls)


class ProbeTest(ChecksCase):
    def test_FR_CHK1_AC_6_an_http_probe_of_a_deployed_url(self):
        stub = Stub({"/health": (200, {"ok": True}), "/down": (503, {"ok": False}), "/slow": (200, {}, 0.6)})
        self.addCleanup(stub.close)
        row = self.enable_run("probe:health", url=f"{stub.url}/health")
        self.assertEqual((row["verdict"], row["status"]), ("passed", 200), row)
        self.assertIsNone(row["tls_days"])                                # plain http: no certificate
        self.assertEqual(self.enable_run("probe:down", url=f"{stub.url}/down")["verdict"], "failed")
        row = self.enable_run("probe:slow", url=f"{stub.url}/slow", max_ms=200)
        self.assertEqual(row["verdict"], "failed")
        self.assertIn("over 200 ms", row["summary"])
        port = stub.server.server_address[1]
        stub.close()
        self.addCleanup(lambda: None)
        row = cstore.run(self.p, "probe:health", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "failed")
        self.assertIn(f"127.0.0.1:{port}/health could not be reached", row["summary"])


class GatesTest(ChecksCase):
    def test_FR_CHK1_AC_7_the_repo_gate_and_the_security_gate_as_checks(self):
        row = self.enable_run("security_gate")
        self.assertEqual(row["verdict"], "not measured")
        self.assertIn("no security scan", row["summary"])
        row = self.enable_run("repo_gate")
        self.assertEqual(row["verdict"], "not measured")                  # the repository has no contract yet
        self.assertIn("no contract", row["summary"])
        built = self.factory.new_project("Loans", maturity="demo", mode="mixed")
        cstore.enable(built, "repo_gate", person=PERSON, persona="developer")
        row = cstore.run(built, "repo_gate", person=PERSON, persona="developer")
        self.assertEqual(row["verdict"], "not measured")
        self.assertIn("judges an attached repository", row["summary"])


class RecordsTest(ChecksCase):
    def test_FR_CHK1_AC_8_results_are_recorded_and_a_failure_logs_a_signal_and_a_change_once(self):
        self.only_bin()
        tool = fake_tool(self.bin, "gate-me", "import sys\nsys.exit(int(open('verdict.txt').read()))\n")
        self.assertTrue(tool.exists())
        (self.repo / "verdict.txt").write_text("1", encoding="utf-8")
        cstore.enable(self.p, "custom:gate", person=PERSON, persona="developer", config={"command": "gate-me"},
                      on_fail=["signal", "change"])
        first = cstore.run(self.p, "custom:gate", person=PERSON, persona="developer")
        self.assertEqual((first["verdict"], first["on_fail"]), ("failed", ["signal", "change"]))
        again = cstore.run(self.p, "custom:gate", person=PERSON, persona="developer")
        self.assertEqual(again["on_fail"], [])                           # once per change of verdict
        self.assertEqual(len([s for s in signals(self.factory) if "custom:gate" in s["text"]]), 1)
        self.assertEqual(len(Canon(self.p).cards(kind="change")), 1)
        ran = [r["event"]["payload"] for r in self.p.ledger().of_kind("check_ran")]
        self.assertEqual([(r["check"], r["verdict"], r["person"]) for r in ran][-2:],
                         [("custom:gate", "failed", PERSON)] * 2)
        self.assertEqual([r["verdict"] for r in cstore.results(self.p, "custom:gate")], ["failed", "failed"])
        (self.repo / "verdict.txt").write_text("0", encoding="utf-8")
        self.assertEqual(cstore.run(self.p, "custom:gate", person=PERSON, persona="developer")["verdict"], "passed")

    def test_FR_CHK1_AC_8_a_schedule_runs_what_is_due_with_the_enablers_rights(self):
        cstore.enable(self.p, "secrets", person=PERSON, persona="developer", every="1h")
        cstore.enable(self.p, "sbom", person=PERSON, persona="developer")            # on demand only
        self.assertEqual([k for _, k in cstore.due(self.factory)], ["secrets"])
        self.assertEqual(cstore.tick(self.factory), [{"project": self.p.pid, "check": "secrets", "verdict": "passed"}])
        self.assertEqual(cstore.due(self.factory), [])
        self.clock.advance(minutes=61)
        self.assertEqual([k for _, k in cstore.due(self.factory)], ["secrets"])
        rec = self.p.ledger().of_kind("check_ran")[-1]["event"]["payload"]
        self.assertEqual((rec["via"], rec["person"]), ("schedule", PERSON))
        # access enforced: a check enabled without a verified identity does not run on its own
        path = kaccess.access_path(self.factory)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, {"schema": kaccess.SCHEMA, "mode": "enforced", "changed_by": "local:it-admin",
                          "proxy": {"preset": "oauth2-proxy", "issuer": "https://id.example",
                                    "origin": "https://r.example", "audience": "r", "groups_claim": "groups"},
                          "people": [{"identity": "local:it-admin", "name": "Ilkka IT"}],
                          "bindings": [{"subject": "local:it-admin", "persona": "it", "scope": "*"}]})
        [out] = cstore.tick(self.factory)
        self.assertEqual(out["verdict"], "not measured")
        self.assertIn("no verified identity enabled this check", cstore.results(self.p, "secrets")[-1]["summary"])

    def test_FR_CHK1_AC_8_run_check_plugs_into_the_automations_allow_list(self):
        autos = types.SimpleNamespace(ACTIONS={}, _ACTION_FIELDS={})
        acts = types.SimpleNamespace(HANDLERS={})
        automation_hook.register(autos, acts)
        self.assertEqual(autos.ACTIONS["run_check"]["personas"], checks.ENABLERS)
        self.assertEqual(autos._ACTION_FIELDS["run_check"](self.factory, {"check": "probe:prod"}), {"check": "probe:prod"})
        with self.assertRaises(ValueError):
            autos._ACTION_FIELDS["run_check"](self.factory, {"check": "rm -rf"})
        a = {"id": "AU-001", "action": {"kind": "run_check", "check": "secrets"},
             "owner": {"person": PERSON, "persona": "developer"}}
        handle = acts.HANDLERS["run_check"]
        self.assertEqual(handle(self.factory, a, {"project": self.p.pid}, None)["outcome"], "nothing")
        cstore.enable(self.p, "secrets", person=PERSON, persona="developer")
        out = handle(self.factory, a, {"project": self.p.pid}, None)
        self.assertEqual((out["outcome"], out["verdict"]), ("done", "passed"))
        self.assertEqual(self.p.ledger().of_kind("check_ran")[-1]["event"]["payload"]["via"], "automation AU-001")


class HealthTest(ChecksCase):
    def test_FR_CHK1_AC_9_health_per_project_and_across_the_factory_feeds_whats_next(self):
        self.only_bin()
        fake_tool(self.bin, "nope", "import sys\nsys.exit(2)\n")
        cstore.enable(self.p, "custom:smoke", person=PERSON, persona="developer", config={"command": "nope"})
        cstore.enable(self.p, "secrets", person=PERSON, persona="developer")
        cstore.enable(self.p, "dependencies", person=PERSON, persona="developer")
        h = chealth.project_health(self.p)
        self.assertEqual(h["counts"]["not run yet"], 3)
        self.assertEqual(h["line"], "no check has run yet")
        for key in ("custom:smoke", "secrets", "dependencies"):
            cstore.run(self.p, key, person=PERSON, persona="developer")
        h = chealth.project_health(self.p)
        self.assertEqual((h["counts"]["failed"], h["counts"]["passed"], h["counts"]["not measured"]), (1, 1, 1))
        self.assertEqual(h["line"], "1 check failing: Custom check (smoke)")
        row = next(r for r in h["checks"] if r["check"] == "dependencies")
        self.assertEqual(row["state"], "not measured")                     # never shown as passed
        self.assertEqual([t["verdict"] for t in row["trend"]], ["not measured"])
        nxt = chealth.with_failing(self.p, {"state": "ready", "actions": []})
        self.assertEqual(nxt["actions"][-1]["id"], "checks_failing")
        self.assertEqual(nxt["actions"][-1]["view"], "checks")
        f = chealth.factory_health(self.factory)
        self.assertEqual(f["failing"], [f"{self.p.pid}: Custom check (smoke)"])
        self.assertEqual(f["line"], "1 check failing across the factory")


if __name__ == "__main__":
    unittest.main()
