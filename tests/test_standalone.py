"""Each standalone preset end to end from the command line, with what exists today (FR-MOD3): spec only,
gate my code (an attached repository of your own, its holdouts and its contract), security only, evidence
only, and assess only. Every step is signed and recorded; the person's own repository is never written."""

import contextlib
import http.server
import io
import json
import shutil
import subprocess
import sys
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model, no_findings  # noqa: E402

from kernel import gate_external, modules  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.pipeline import advance  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
SMOKE = "import unittest\n\n\nclass Smoke(unittest.TestCase):\n    def test_imports(self):\n        import calc  # noqa: F401\n"
ADD_TEST = ("import unittest\n\nimport calc\n\n\nclass Add(unittest.TestCase):\n    def test_R_1_AC_1_add_adds(self):\n"
            "        self.assertEqual(calc.add(2, 3), 5)\n")
LAZY_TEST = "import unittest\n\n\nclass Add(unittest.TestCase):\n    def test_R_1_AC_1_always(self):\n        self.assertTrue(True)\n"
CONTRACT = {"schema": "gnomonfactory.contract/1", "contract": "calc",
            "requirements": [{"id": "R-1", "statement": "add adds two numbers", "provenance": "customer-endorsed",
                              "decided_by": "Aino", "acceptance": [
                                  {"id": "R-1-AC-1", "given": "-", "when": "add(2, 3)", "then": "5",
                                   "check": {"kind": "test"}},
                                  {"id": "R-1-AC-2", "given": "a running service", "when": "GET /health",
                                   "then": "200", "check": {"kind": "holdout", "ref": "H-R-1-AC-2"}}]}],
            "tasks": [{"id": "T-001", "title": "add", "criteria": ["R-1-AC-1", "R-1-AC-2"]}]}


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=Dev", "-c", "user.email=dev@example.org", *args], cwd=repo,
                          capture_output=True, text=True, check=True).stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class StandaloneTestCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        if shutil.which("git") is None:
            self.skipTest("git is needed")
        self.repo = self.tmp / "calc"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        write(self.repo / "calc.py", "def add(a, b):\n    return a - b\n")
        write(self.repo / "tests" / "test_smoke.py", SMOKE)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        git(self.repo, "tag", "v0.1")
        self.contract_file = self.tmp / "outside" / "contract.json"
        write(self.contract_file, json.dumps(CONTRACT))

    def change(self, branch: str, files: dict) -> str:
        git(self.repo, "checkout", "-q", "-b", branch, "main")
        for name, text in files.items():
            write(self.repo / name, text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", branch)
        git(self.repo, "checkout", "-q", "main")
        return git(self.repo, "rev-parse", branch)

    def cli(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("kernel.cli._model", model), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = main(["--home", str(self.factory.home), *argv])
        self.assertEqual(got, code, (argv, err.getvalue()))
        return json.loads(out.getvalue()) if out.getvalue().strip() else err.getvalue()

    def attached(self, *extra):
        out = self.cli("repo", "attach", "Calc", "--repo", str(self.repo), "--person", "Aino", "--persona", "developer",
                       *extra)
        return self.factory.project(out["project"])

    def untouched(self):
        """The person's own repository is as they left it: no file, branch or commit of Rihmasto's."""
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertNotIn("rihma", git(self.repo, "for-each-ref", "--format=%(refname)").lower())


class SpecOnlyTest(StandaloneTestCase):
    def test_FR_MOD3_AC_1_spec_only_ends_in_an_exported_spec_and_contract_and_nothing_is_built(self):
        self.cli("modules", "set", "--preset", "spec_only", "--person", "Aino", "--persona", "business_owner")
        pid = self.cli("new", "Equipment loans", "--source", IDEA, "--mode", "assume", "--maturity", "explore",
                       "--requested-by", "Aino")["project"]
        ran = self.cli("run", pid)
        self.assertEqual((ran["state"], ran["stopped_by_modules"]), ("done", "build"))
        self.cli("build", pid, code=2)                                           # nothing is built here
        out = self.cli("contract", "export", pid, "--out", str(self.tmp / "out"), "--person", "Aino",
                       "--persona", "product_owner")
        folder = Path(out["folder"])
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["MANIFEST.json", "REPORT.md", "brief.md", "checkplan.json", "contract.json", "spec.json",
                          "spec.md"])
        p = self.factory.project(pid)
        contract = json.loads((folder / "contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["revision"], p.meta["contract_revision"])
        manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["exported_by"], manifest["persona"]), ("Aino", "product_owner"))
        report = (folder / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn(contract["revision"], report)
        self.assertIn("Nothing was built from it here.", report)
        self.assertIn("Assumed (A-001)", report)                                 # what was assumed, by whom decided
        custody = sorted(p.holdouts_dir.glob("*.json"))
        self.assertTrue(custody)                                                 # the holdouts exist, in custody
        exported = "".join(f.read_text(encoding="utf-8") for f in folder.iterdir())
        self.assertNotIn("expect_status", exported)                             # and never leave it
        rec = p.ledger().of_kind("contract_exported")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"], rec["revision"]), ("Aino", "product_owner", contract["revision"]))
        again = self.cli("contract", "export", pid, "--out", str(self.tmp / "out"), "--person", "Aino",
                         "--persona", "product_owner")
        self.assertNotEqual(again["folder"], out["folder"])                     # an export never replaces another


class GateMyCodeTest(StandaloneTestCase):
    def test_FR_MOD3_AC_2_gate_my_code_judges_a_change_in_your_repository_with_the_gate_and_never_merges(self):
        self.cli("modules", "set", "--preset", "gate_my_code", "--person", "Aino", "--persona", "developer")
        p = self.attached("--contract", str(self.contract_file), "--branch", "main")
        good = self.change("fix", {"calc.py": "def add(a, b):\n    return a + b\n", "tests/test_add.py": ADD_TEST})
        out = gate_external.gate(p, person="Aino", persona="developer", head="fix", task="T-001",
                                 verifier_runner=no_findings)
        self.assertEqual((out["verdict"], out["head"]), ("passed", good))
        self.assertEqual({s["name"]: s["verdict"] for s in out["signals"]},
                         {"tests": "passed", "trace": "passed", "fail_first": "passed", "verifier": "passed"})
        self.assertIn("never merges", out["merge"])
        rec = p.ledger().of_kind("gate")[-1]["event"]["payload"]
        self.assertEqual((rec["task"], rec["verdict"], rec["person"], rec["persona"], rec["head"], rec["base"]),
                         ("T-001", "passed", "Aino", "developer", good, git(self.repo, "rev-parse", "main")))
        self.assertEqual(rec["repository"], str(self.repo.resolve()))
        self.change("lazy", {"tests/test_lazy.py": LAZY_TEST})                   # a test that cannot fail
        out = gate_external.gate(p, person="Aino", persona="developer", head="lazy", task="T-001",
                                 verifier_runner=no_findings)
        self.assertEqual({s["name"]: s["verdict"] for s in out["signals"]}["fail_first"], "failed")
        self.assertEqual(out["round"], 1)                                        # the task's second round
        self.change("rewrite", {"contract.json": "{}\n", "calc.py": "def add(a, b):\n    return a + b\n"})
        out = gate_external.gate(p, person="Aino", persona="developer", head="rewrite", verifier_runner=no_findings)
        self.assertEqual(out["verdict"], "violation")                            # the contract changes only by a person
        out = self.cli("repo", "gate", p.pid, "--head", "fix", "--task", "T-001", "--no-verifier", "--person", "Aino",
                       "--persona", "developer", code=4)
        self.assertEqual(out["verdict"], "not measured")                         # never passed without its verifier
        self.assertIn("never passed", {s["name"]: s["detail"] for s in out["signals"]}["verifier"])
        self.cli("repo", "gate", p.pid, "--person", "Aino", "--persona", "developer", code=2)  # HEAD is main itself
        self.assertEqual(advance(p, model=model())["state"], "waiting")           # no pipeline: a person asks
        self.untouched()

    def test_FR_MOD3_AC_3_holdouts_come_from_outside_the_repository_and_run_against_your_service(self):
        p = self.attached("--contract", str(self.contract_file))
        inside = self.repo / "scenarios"
        write(inside / "h.json", json.dumps({"criterion": "R-1-AC-2", "steps": [{"method": "GET", "path": "/health",
                                                                                 "expect_status": 200}]}))
        self.cli("repo", "holdouts", p.pid, "--import", str(inside), "--person", "Kaisa", "--persona", "it", code=2)
        shutil.rmtree(inside)
        outside = self.tmp / "qa"
        write(outside / "h.json", json.dumps({"criterion": "R-1-AC-2", "steps": [{"method": "GET", "path": "/health",
                                                                                  "expect_status": 200}]}))
        write(outside / "bad.json", json.dumps({"criterion": "R-1-AC-1", "steps": [{"method": "GET", "path": "/"}]}))
        self.cli("repo", "holdouts", p.pid, "--import", str(outside), "--person", "Kaisa", "--persona", "it", code=2)
        (outside / "bad.json").unlink()
        out = self.cli("repo", "holdouts", p.pid, "--import", str(outside), "--person", "Kaisa", "--persona", "it")
        self.assertEqual((out["imported"], out["in_custody"]), (["R-1-AC-2"], ["R-1-AC-2"]))
        self.assertTrue((p.holdouts_dir / "R-1-AC-2.json").exists())
        self.assertNotIn(str(self.repo.resolve()), str(p.holdouts_dir.resolve()))
        self.cli("repo", "holdouts", p.pid, "--import", str(outside), "--person", "Kaisa", "--persona", "it", code=2)

        class Health(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == "/health" else 404)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Health)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            out = self.cli("repo", "holdouts", p.pid, "--base-url", f"http://127.0.0.1:{server.server_port}",
                           "--person", "Kaisa", "--persona", "it")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual((out["run"]["verdict"], out["run"]["results"]), ("passed", [{"criterion": "R-1-AC-2",
                                                                                      "verdict": "passed"}]))
        rec = p.ledger().of_kind("holdouts_run")[-1]["event"]["payload"]
        self.assertEqual((rec["verdict"], rec["person"]), ("passed", "Kaisa"))
        self.assertNotIn("steps", json.dumps(rec))                               # verdicts only, never a scenario
        self.cli("repo", "holdouts", p.pid, "--base-url", "http://user:pw@127.0.0.1:1", "--person", "Kaisa",
                 "--persona", "it", code=2)
        self.untouched()


class AttachTest(StandaloneTestCase):
    def test_FR_MOD3_AC_4_a_repository_is_attached_with_a_checked_contract_a_compiled_spec_or_its_own(self):
        bad = dict(CONTRACT, revision="sha256:" + "0" * 64)
        write(self.tmp / "bad.json", json.dumps(bad))
        err = self.cli("repo", "attach", "Calc", "--repo", str(self.repo), "--contract", str(self.tmp / "bad.json"),
                       "--person", "Aino", "--persona", "developer", code=2)
        self.assertIn("changed after it was hashed", err)
        self.assertEqual(self.factory.projects(), [])                          # nothing is left half-attached
        self.cli("repo", "attach", "Calc", "--repo", "https://example.org/calc.git", "--person", "Aino",
                 "--persona", "developer", code=2)
        self.cli("repo", "attach", "Calc", "--repo", str(self.tmp / "outside"), "--person", "Aino",
                 "--persona", "developer", code=2)                              # not a git repository
        spec = {"title": "Calc", "requirements": [{"statement": "add adds", "acceptance": [
            {"given": "-", "when": "add(2, 3)", "then": "5", "kind": "test"}]}]}
        write(self.tmp / "spec.json", json.dumps(spec))
        p = self.attached("--spec", str(self.tmp / "spec.json"))
        req = p.read("contract.json")["requirements"][0]
        self.assertEqual((req["id"], req["provenance"], req["decided_by"]), ("R-1", "customer-endorsed", "Aino"))
        rec = p.ledger().of_kind("contract_imported")[-1]["event"]["payload"]
        self.assertEqual((rec["by"], rec["revision"]), ("Aino", p.meta["contract_revision"]))
        write(self.repo / "contract.json", json.dumps(CONTRACT))                 # the repository's own contract
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "contract")
        q = self.attached()
        self.assertEqual(q.read("contract.json")["requirements"][0]["statement"], "add adds two numbers")
        self.assertEqual(q.ledger().of_kind("contract_imported")[-1]["event"]["payload"]["from"],
                         {"repository": "main:contract.json"})
        listed = self.cli("repo", "list")["attached"]
        self.assertEqual({a["project"] for a in listed}, {p.pid, q.pid})
        state = advance(q, model=model())
        self.assertEqual((state["state"], state["attached"]), ("waiting", True))
        self.assertIn(f"rihmasto repo gate {q.pid}", state["why"])
        rec = q.ledger().of_kind("repo_attached")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"], rec["branch"]), ("Aino", "developer", "main"))


class SecurityAndEvidenceOnlyTest(StandaloneTestCase):
    def test_FR_MOD3_AC_5_security_only_scans_your_repository_into_the_security_gate(self):
        self.cli("modules", "set", "--preset", "security_only", "--person", "Ilkka", "--persona", "it")
        write(self.repo / "app" / "run.py", "def run(expr):\n    return eval(expr)\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "an eval")
        p = self.attached()
        self.assertIsNone(p.meta.get("contract_revision"))
        self.cli("repo", "gate", p.pid, "--person", "Ilkka", "--persona", "it", code=2)   # build is off
        out = self.cli("repo", "scan", p.pid, "--person", "Ilkka", "--persona", "it")
        self.assertEqual((out["verdict"], out["counts"]["error"]), ("failed", 1))
        self.assertEqual(out["gate"]["verdict"], "failed")
        status = self.cli("security", "status", p.pid)
        finding = status["findings"][0]
        self.assertEqual((finding["rule"], finding["location"]["uri"], finding["location"]["line"]),
                         ("RT-PY-EVAL", "app/run.py", 2))
        self.cli("security", "accept", p.pid, finding["id"], "--reason", "only ever called with literals",
                 "--expires", "2027-01-31", "--person", "Ilkka", "--persona", "it")
        self.assertEqual(self.cli("security", "status", p.pid)["verdict"], "passed")
        rec = p.ledger().of_kind("repo_scanned")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["verdict"], rec["revision"]),
                         ("Ilkka", "failed", git(self.repo, "rev-parse", "HEAD")))
        self.untouched()

    def test_FR_MOD3_AC_6_evidence_only_records_a_repositorys_releases_with_what_the_kernel_saw_there(self):
        self.cli("modules", "set", "--preset", "evidence_only", "--person", "Kaisa", "--persona", "compliance")
        p = self.attached("--contract", str(self.contract_file))
        git(self.repo, "checkout", "-q", "-b", "next")
        write(self.repo / "calc.py", "def add(a, b):\n    return a + b\n")
        write(self.repo / "tests" / "test_add.py", ADD_TEST)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "fix")
        git(self.repo, "tag", "-a", "v0.2", "-m", "release 0.2")
        git(self.repo, "checkout", "-q", "main")
        out = self.cli("repo", "releases", p.pid, "--check", "--person", "Kaisa", "--persona", "compliance")
        rows = {r["tag"]: r for r in out["recorded"]}
        self.assertEqual(set(rows), {"v0.1", "v0.2"})
        self.assertEqual(rows["v0.2"]["commit"], git(self.repo, "rev-parse", "next"))   # the commit, not the tag object
        self.assertEqual(rows["v0.2"]["checks"]["trace"]["verdict"], "passed")
        self.assertEqual(rows["v0.1"]["checks"]["trace"]["unnamed"], ["R-1-AC-1"])
        self.assertEqual(rows["v0.1"]["claimed_by_git"], ["commit", "date"])
        self.assertEqual(self.cli("repo", "releases", p.pid, "--person", "Kaisa", "--persona", "compliance")["unchanged"],
                         ["v0.1", "v0.2"])
        git(self.repo, "tag", "-f", "v0.1", "next")                               # a tag moved
        moved = self.cli("repo", "releases", p.pid, "--tag", "v0.1", "--person", "Kaisa", "--persona", "compliance")
        self.assertEqual(moved["recorded"][0]["moved_from"], rows["v0.1"]["commit"])
        zipped = self.cli("evidence", p.pid, "--out", str(self.tmp / "ev"), "--person", "Kaisa", "--persona", "compliance")
        with zipfile.ZipFile(zipped["file"]) as z:
            releases = json.loads(z.read("repository-releases.json"))
            readme = z.read("README.md").decode("utf-8")
        self.assertEqual({r["tag"] for r in releases}, {"v0.1", "v0.2"})
        self.assertIn("The repository's own releases: 2", readme)
        self.cli("repo", "scan", p.pid, "--person", "Kaisa", "--persona", "compliance", code=2)   # security is off
        self.untouched()


class AssessOnlyTest(StandaloneTestCase):
    def test_FR_MOD3_AC_7_assess_only_adopts_a_system_and_refuses_what_it_does_not_use(self):
        self.cli("modules", "set", "--preset", "assess_only", "--person", "Aino", "--persona", "it")
        self.cli("new", "Loans", "--source", IDEA, "--requested-by", "Aino", code=2)
        out = self.cli("adopt", "Calc", "--source", str(self.repo), "--intent", "maintain", "--person", "Aino",
                       "--persona", "developer")
        self.assertTrue(out["baseline"])
        self.assertTrue(self.cli("sync", out["project"])["upstream"])
        self.cli("deliver", out["project"], code=2)
        self.assertEqual(modules.enabled(self.factory.project(out["project"])), ["assessment"])
        self.cli("modules", "set", "--preset", "capability_only", "--person", "Aino", "--persona", "business_owner")
        pid = self.cli("new", "Loans", "--source", IDEA, "--mode", "assume", "--maturity", "explore",
                       "--requested-by", "Aino")["project"]                     # the chain to a capability is on
        for refused in (["operate", pid], ["change", pid, "it crashes", "--person", "Aino", "--persona", "end_user"],
                        ["signal", "list"], ["adopt", "Calc", "--source", str(self.repo), "--intent", "monitor",
                                             "--person", "Aino", "--persona", "developer"]):
            self.assertIn("which is not enabled for", self.cli(*refused, code=2), refused)


if __name__ == "__main__":
    unittest.main()
