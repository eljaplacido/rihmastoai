"""A precise assessment of an adopted project (FR-ASP1): what is worth acting on, and what is probably noise.

The fixture is an invented repository shaped like the ones people adopt: two Python packages, each with its own test
root (running pytest from the repository's root cannot import them), a stated test command of the project's own that
the kernel does not run, a plan document last changed weeks before the code, test fixtures holding fake identifiers
that look like credentials, an attachment URL whose path looks like a token, and one value that looks real. Every
credential-shaped value is made at run time, so no tracked file holds one.
"""

from __future__ import annotations

import os
import random
import string
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_assess import ID, git, no_scanner, run_cli, write  # noqa: E402
from test_cockpit import CockpitTestCase, FakeRunner  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import alignment, assess, assess_cards, assess_measure, assess_precise, assistant_ops  # noqa: E402
from kernel.adopt import adopt, detect_tests  # noqa: E402
from kernel.assistant import ask  # noqa: E402

OLD, NEW = "2026-09-01T10:00:00+00:00", "2026-11-20T10:00:00+00:00"
PORT = 9330          # this build's own cockpit port


def token(n: int = 24) -> str:
    rnd = random.Random(7)
    return "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(n))


def uuid_like() -> str:
    rnd = random.Random(11)
    hexd = lambda k: "".join(rnd.choice("0123456789abcdef") for _ in range(k))   # noqa: E731
    return f"{hexd(8)}-{hexd(4)}-4{hexd(3)}-9{hexd(3)}-{hexd(12)}"


def jwt_path() -> str:
    """A token-shaped path segment of an attachment URL (three base64url parts), made at run time."""
    import base64

    parts = [b'{"alg":"HS256","typ":"x"}', b'{"sub":"attachment-0042"}', b"signaturepart1"]
    return ".".join(base64.urlsafe_b64encode(p).decode().replace("=", "") for p in parts)


def harbour(dest: Path) -> Path:
    """The invented repository, committed twice: the plan and the first code in September, the code again in November."""
    write(dest, {
        "README.md": "# Harbour\n\nA small simulation with two packages.\n",
        "CLAUDE.md": "# Working here\n\nRun the gates with `py -3 tools/gates.py test` before a push.\n",
        "docs/plan.md": "# Plan\n\n## REQ-1 Boats dock\n\nThe harbour shall dock boats in order.\n",
        "packages/engine/pyproject.toml": "[project]\nname = \"engine\"\nversion = \"0.1.0\"\n",
        "packages/engine/engine_core.py": "def dock(n):\n    return list(range(n))\n",
        "packages/engine/tests/test_engine.py": "import pytest\nfrom engine_core import dock\n\n\ndef test_dock():\n"
                                                "    assert dock(2) == [0, 1]\n",
        "packages/tools/setup.cfg": "[metadata]\nname = tools\n",
        "packages/tools/tools_lib.py": "def tide():\n    return 3\n",
        "packages/tools/tests/test_tools.py": "from tools_lib import tide\n\n\ndef test_tide():\n    assert tide() == 3\n",
    })
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    env = dict(os.environ, GIT_AUTHOR_DATE=OLD, GIT_COMMITTER_DATE=OLD)
    git(dest, *ID, "commit", "-q", "-m", "plan and first code", env=env)
    write(dest, {
        "packages/engine/engine_core.py": "def dock(n):\n    return list(range(n))\n\n\ndef undock(n):\n    return n\n",
        "packages/engine/tests/fixtures/accounts.py":
            f'api_token = "{uuid_like()}"\nsession_token = "testTOKEN{token(14)}"\n',
        "packages/engine/attach.py": f'ATTACHMENT = "https://files.cdn.invalid/att/{jwt_path()}/image.png"\n',
        "packages/engine/settings.py": f'api_token = "{token()}"\n',
    })
    git(dest, "add", "-A")
    env = dict(os.environ, GIT_AUTHOR_DATE=NEW, GIT_COMMITTER_DATE=NEW)
    git(dest, *ID, "commit", "-q", "-m", "undock, fixtures, attachments", env=env)
    return dest


def adopted(factory, tmp: Path):
    project = adopt(factory, "Harbour", source=str(harbour(tmp / "harbour")), intent="monitor", person="Ida Example",
                    persona="developer", suite_timeout=120)
    contract = project.read("contract.json") or {"requirements": []}
    contract["requirements"].append({"id": "REQ-1", "statement": "The harbour shall dock boats in order.",
                                     "imported": {"path": "docs/plan.md", "ref": "REQ-1", "item": "req-x"}})
    project.write("contract.json", contract)
    return project


def secrets(record: dict) -> dict:
    return {c["evidence"][0]["file"]: c for c in record["checks"] if assess_precise.secret_rule(c)
            and c["verdict"] == "failed"}


class PreciseTest(FactoryTestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util

        if importlib.util.find_spec("pytest") is None:
            raise unittest.SkipTest("pytest runs the fixture's own suites")

    def setUp(self):
        super().setUp()
        self.project = adopted(self.factory, self.tmp)
        self.record = assess.assess(self.project, person="Ida Example", persona="developer", which=no_scanner)

    def test_FR_ASP1_AC_1_a_fixture_or_a_url_path_is_likely_not_a_secret_and_a_mark_is_remembered_per_file(self):
        found = secrets(self.record)
        fixture = found["packages/engine/tests/fixtures/accounts.py"]
        url, real = found["packages/engine/attach.py"], found["packages/engine/settings.py"]
        self.assertEqual((fixture["likely"]["verdict"], fixture["severity"]), ("likely not a secret", "info"))
        self.assertIn("test fixture", fixture["likely"]["reason"])
        self.assertTrue(fixture["severity_was"])
        self.assertIn("URL path", url["likely"]["reason"])
        self.assertEqual(real["likely"]["verdict"], "possibly real")
        self.assertNotEqual(real["severity"], "info")
        self.assertNotIn(token(), str(self.record), "evidence stays masked")
        self.assertEqual(assess_precise.judge_line("src/a.py", 'k = "https://h.invalid/x?token=' + token() + '"')[0],
                         "possibly real", "a URL carrying a credential-shaped query is not a path")
        self.assertIsNone(assess_precise.fake_value("sk_test_" + token(), in_tests=False))

        out = assess_precise.give(self.project, real["id"], "fixture", person="Ida Example", persona="developer",
                                  reason="a local stand-in")
        self.assertEqual((out["file"], out["verdict"]), ("packages/engine/settings.py", "fixture"))
        shown = secrets(assess_cards.view(self.project)["latest"])["packages/engine/settings.py"]
        self.assertEqual((shown["likely"]["verdict"], shown["likely"]["by"]), ("likely not a secret", "person"))
        again = secrets(assess.assess(self.project, person="Ida Example", persona="developer", which=no_scanner))
        self.assertIn("marked as a fixture by Ida Example", again["packages/engine/settings.py"]["likely"]["reason"])
        assess_precise.give(self.project, again["packages/engine/settings.py"]["id"], "real", person="Ida Example",
                            persona="developer")
        latest = secrets(assess_cards.view(self.project)["latest"])["packages/engine/settings.py"]
        self.assertEqual(latest["likely"]["verdict"], "confirmed real")
        self.assertNotEqual(latest["severity"], "info")
        kinds = [r["event"]["payload"]["mark"] for r in self.project.ledger().of_kind("assessment_secret_marked")]
        self.assertEqual(kinds, ["fixture", "real"])
        with self.assertRaises(assess_precise.VerdictRefused):           # a secret is judged by those who may
            assess_precise.give(self.project, again["packages/engine/settings.py"]["id"], "real", person="Bea Example",
                                persona="end_user")
        other = next(c for c in self.record["checks"] if c.get("id") and not assess_precise.secret_rule(c))
        with self.assertRaises(assess_precise.VerdictRefused):
            assess_precise.give(self.project, other["id"], "fixture", person="Ida Example", persona="developer")

    def test_FR_ASP1_AC_2_each_package_runs_in_its_own_test_root_and_the_project_s_own_runner_is_mapped(self):
        roots = assess_measure.python_roots(["packages/engine/pyproject.toml", "packages/engine/tests/test_a.py",
                                             "packages/tools/setup.cfg", "packages/tools/tests/test_b.py"], lambda r: "")
        self.assertEqual(roots, ["packages/engine", "packages/tools"])
        self.assertEqual(assess_measure.python_roots(["pytest.ini", "a/setup.cfg", "a/tests/test_x.py"], lambda r: ""),
                         [""], "a root that sets pytest up runs once, as before")
        base = self.project.read("baseline.json")
        runs = [(r.get("cwd"), r["verdict"]) for r in base["runs"] if r["runner"] == "pytest"]
        self.assertEqual(runs, [("packages/engine", "passed"), ("packages/tools", "passed")])
        tests = [t for t in detect_tests(self.tmp / "harbour", ["packages/engine/pyproject.toml",
                                                                "packages/engine/tests/test_engine.py"]) if t.get("cwd")]
        self.assertEqual([t["cwd"] for t in tests], ["packages/engine"])

        checks = {c["key"]: c for c in self.record["checks"]}
        measured = checks["maintenance.tests_measured"]
        self.assertEqual(measured["verdict"], "not measured")
        self.assertIn("not measured by Rihmasto yet: map its runner", measured["reason"])
        self.assertIn("CLAUDE.md", str(measured["evidence"]))
        self.assertIn("not mapped", self.record["precise"]["measured_against"])
        self.assertNotIn("0 %", str(self.record))
        broken = {"key": "maintenance.baseline", "verdict": "failed", "severity": "high", "suggestion": "x",
                  "summary": "the suite could not run (3 errors: errors while collecting the tests, so no test ran)"}
        assess_precise.never_ran([broken])
        self.assertEqual((broken["verdict"], broken["severity"]), ("not measured", None))
        self.assertIn("map its runner", broken["reason"])

        assess_measure.map_runner(self.project, command="py -3 tools/gates.py test", results="build/gates.xml",
                                  note="on the build machine", person="Ida Example", persona="developer")
        for bad in ("make x && rm -rf /", "x | y"):
            with self.assertRaises(assess_measure.RunnerRefused):
                assess_measure.map_runner(self.project, command=bad, results=None, note=None, person="Ida Example",
                                          persona="developer")
        with self.assertRaises(assess_measure.RunnerRefused):
            assess_measure.map_runner(self.project, command="ok", results="../out.xml", note=None, person="Ida Example",
                                      persona="developer")
        write(self.tmp / "harbour", {"build/gates.xml": '<testsuites tests="660" failures="0" errors="0">'
                                                        '<testsuite tests="660"/></testsuites>\n'})
        git(self.tmp / "harbour", "add", "-A")
        git(self.tmp / "harbour", *ID, "commit", "-q", "-m", "gate results")
        from kernel.adopt import sync

        head = sync(self.project)["upstream"]              # main is not moved: the upstream's head is assessed
        again = {c["key"]: c for c in assess.assess(self.project, person="Ida Example", persona="developer",
                                                    which=no_scanner, ref=head)["checks"]}
        self.assertEqual((again["maintenance.tests_measured"]["verdict"], again["maintenance.tests_measured"]["summary"]),
                         ("passed", "660 passed, read from build/gates.xml"))
        self.assertEqual(assess_measure.read_results('{"tests": [{"status": "passed"}, {"outcome": "failed"}]}'),
                         {"passed": 1, "failed": 1, "errors": 0, "skipped": 0})
        self.assertTrue(self.project.ledger().of_kind("assessment_runner_mapped"))

    def test_FR_ASP1_AC_3_a_finding_not_relevant_leaves_the_priorities_and_findings_like_it_are_proposed(self):
        url = secrets(self.record)["packages/engine/attach.py"]
        fixture = secrets(self.record)["packages/engine/tests/fixtures/accounts.py"]
        with self.assertRaises(assess_precise.VerdictRefused):
            assess_precise.give(self.project, url["id"], "not_relevant", person="Ida Example", persona="developer")
        out = assess_precise.give(self.project, url["id"], "not_relevant", person="Ida Example", persona="developer",
                                  reason="attachment paths are public by design")
        self.assertEqual(out["findings"], [url["id"]])
        same_rule = [c["id"] for c in self.record["checks"] if c.get("id") and c["id"] != url["id"]
                     and assess_precise.family(c) == assess_precise.family(url)]
        self.assertEqual(out["similar"], same_rule)
        view = assess_cards.view(self.project)
        self.assertNotIn(url["id"], [r["id"] for r in view["priority"]])
        byid = {c.get("id"): c for c in view["latest"]["checks"]}
        self.assertEqual(byid[url["id"]]["dismissed"]["reason"], "attachment paths are public by design")
        for fid in same_rule:
            self.assertEqual(byid[fid]["propose_dismiss"]["like"], url["id"])
        payload = self.project.ledger().of_kind("assessment_finding_dismissed")[-1]["event"]["payload"]
        self.assertEqual((payload["person"], payload["findings"]), ("Ida Example", [url["id"]]))
        assess.assess(self.project, person="Ida Example", persona="developer", which=no_scanner)
        later = assess_cards.view(self.project)
        self.assertTrue(any(c.get("dismissed") for c in later["latest"]["checks"]), "kept by key in the next version")
        assess_precise.give(self.project, url["id"], "relevant", person="Ida Example", persona="developer")
        self.assertFalse(any(c.get("dismissed") for c in assess_cards.view(self.project)["latest"]["checks"]))
        self.assertTrue(fixture["id"])

    def test_FR_ASP1_AC_4_imported_plans_carry_their_document_and_date_and_an_old_one_is_flagged(self):
        plans = self.record["precise"]["plans"]
        row = next(r for r in plans["items"] if r["id"] == "REQ-1")
        self.assertEqual((row["path"], row["committed"][:10], row["stale"]), ("docs/plan.md", "2026-09-01", True))
        self.assertIn("this plan is from 2026-09-01; the code moved on since", row["said"])
        self.assertIn("2026-11-20", row["said"])
        self.assertEqual(plans["stale"], 1)
        summed = alignment.summary([], {"tests": {"count": 2, "frameworks": ["pytest"]},
                                        "specs": [{"path": "docs/plan.md"}]})
        self.assertIn("measured against the 0 requirements read from docs/plan.md", summed["against"])
        self.assertIn("a runner of the project's own is not counted here", summed["against"])

    def test_FR_ASP1_AC_5_the_view_opens_on_two_lines_and_ask_rihma_answers_and_proposes_the_same(self):
        head = assess_cards.view(self.project)["headline"]
        self.assertTrue(head["act"].startswith("Worth acting on now:") or head["act"].startswith("Nothing needs"))
        self.assertTrue(head["noise"].startswith("Probably noise:"))
        self.assertIn("likely not a secret", head["noise"])
        self.assertIn("not measured by Rihmasto yet", head["gaps"])      # a gap to close, not noise (FR-ASP2)
        self.assertIn("imported plan", head["gaps"])
        self.assertEqual({s["do"] for s in head["next"]} >= {"map_runner", "review_secrets"}, True)
        pid = self.project.pid
        out = ask(self.factory, "What in the assessment is worth acting on, and what is noise?", persona="developer",
                  project_id=pid)
        self.assertEqual((out["by"], out["navigate"]["route"]), ("rule", f"#/p/{pid}/assessment"))
        self.assertIn("Probably noise", out["answer"])
        url = secrets(self.record)["packages/engine/attach.py"]["id"]
        out = ask(self.factory, f"{url} is not relevant because attachment paths are public", persona="developer",
                  project_id=pid, view="assessment")
        call = out["propose"][0]["args"]["call"]
        self.assertEqual((call["path"], call["body"]["finding"], call["body"]["verdict"]),
                         (f"/api/projects/{pid}/assessment/verdict", url, "not_relevant"))
        out = ask(self.factory, f"{url} is a fixture", persona="developer", project_id=pid)
        self.assertEqual(out["propose"][0]["args"]["op"], "mark_secret")
        out = ask(self.factory, "map the runner `py -3 tools/gates.py test` results in build/gates.xml",
                  persona="developer", project_id=pid)
        self.assertEqual(out["propose"][0]["args"]["call"]["body"],
                         {"command": "py -3 tools/gates.py test", "results": "build/gates.xml"})
        self.assertIn("mark_secret", assistant_ops.OPS)


class PortCockpit(CockpitTestCase):
    """The cockpit on this build's own port."""

    def setUp(self):
        FactoryTestCase.setUp(self)
        self.runner = FakeRunner()
        self.server, self.bootstrap = make_server(self.factory, PORT, runner=self.runner)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.origin = self.server.origin
        status, body, _ = self.call("POST", "/auth", {"bootstrap": self.bootstrap}, token=None)
        self.assertEqual(status, 200, body)
        self.token = body["token"]


class SurfacesTest(PortCockpit):
    def test_FR_ASP1_AC_6_the_cockpit_and_the_command_line_take_each_verdict_and_the_runner_signed(self):
        project = adopted(self.factory, self.tmp)
        pid = project.pid
        signer = {"person": "Ida Example", "persona": "developer"}
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/assessment", signer)[0], 201)
        status, view, _ = self.call("GET", f"/api/projects/{pid}/assessment")
        self.assertTrue(view["headline"]["noise"])
        url = secrets(view["latest"])["packages/engine/attach.py"]["id"]
        path = f"/api/projects/{pid}/assessment/verdict"
        self.assertEqual(self.call("POST", path, {"finding": url, "verdict": "not_relevant", "reason": "public",
                                                  "person": "model", "persona": "developer"})[0], 403)
        self.assertEqual(self.call("POST", path, {"finding": url, "verdict": "fixture", "person": "Bea",
                                                  "persona": "end_user"})[0], 403)
        self.assertEqual(self.call("POST", path, {"finding": url, "verdict": "not_relevant", **signer})[0], 400)
        self.assertEqual(self.call("POST", path, {"finding": "F-999", "verdict": "relevant", **signer})[0], 400)
        status, out, _ = self.call("POST", path, {"finding": url, "verdict": "not_relevant", "reason": "public", **signer})
        self.assertEqual((status, out["findings"]), (200, [url]))
        status, out, _ = self.call("POST", f"/api/projects/{pid}/assessment/runner",
                                   {"command": "py -3 tools/gates.py test", "results": "build/gates.xml", **signer})
        self.assertEqual((status, out["runner"]["person"]), (200, "Ida Example"))
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/assessment/runner",
                                   {"command": "a; b", **signer})[0], 400)
        home = str(self.factory.home)
        code, got, _ = run_cli("--home", home, "assessment", "verdict", pid, url, "--verdict", "relevant",
                               "--person", "Ida Example", "--persona", "developer")
        self.assertEqual((code, got["verdict"]), (0, "relevant"))
        code, got, _ = run_cli("--home", home, "assessment", "runner", pid, "--command", "make gates", "--person",
                               "Ida Example", "--persona", "developer")
        self.assertEqual((code, got["runner"]["command"]), (0, "make gates"))
        code, got, err = run_cli("--home", home, "assessment", "verdict", pid, url, "--verdict", "not_relevant",
                                 "--person", "Ida Example", "--persona", "developer")
        self.assertEqual((code, got), (2, None), err)


if __name__ == "__main__":
    unittest.main()
