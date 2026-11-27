"""A precise assessment, checked again (FR-ASP2): what an independent check of FR-ASP1 found, each fixed by rule.

Two invented repositories. Harbour (tests/test_assess_precise.py) has two pytest packages, a fixture of fake
identifiers, an attachment URL and one value that looks real. Lantern is a local desk-lamp simulation with no
route, container or deploy file: two unittest packages with their own roots, a gates command stated in CLAUDE.md,
requirements in a Markdown table and in a JSON rules file, rounds in a README table, and an issue log in JSON
lines. Every credential-shaped value is made at run time, so no tracked file holds one.
"""

from __future__ import annotations

import json
import random
import string
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_assess import ID, git, no_scanner, write  # noqa: E402
from test_assess_precise import adopted, jwt_path, secrets, token  # noqa: E402
from test_cockpit import CockpitTestCase, FakeRunner  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import agent_context_use, assess, assess_cards, assess_measure, assess_precise, devbrief  # noqa: E402
from kernel import alignment_records  # noqa: E402
from kernel.adopt import adopt, detect_tests, sync  # noqa: E402
from kernel.assess_repo import Repo  # noqa: E402
from kernel.assistant import ask  # noqa: E402

PORT = 9341          # this build's own cockpit port
WHO = {"person": "Ida Example", "persona": "developer"}


def tok(n: int, seed: int = 31) -> str:
    rnd = random.Random(seed)
    return "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(n))


def digits(n: int, seed: int = 5) -> str:
    rnd = random.Random(seed)
    return "".join(rnd.choice(string.digits) for _ in range(n))


def lantern(dest: Path) -> Path:
    """A local project: no route, container or deploy file; its own gates; plans in tables, JSON and JSON lines."""
    issues = [{"id": "ISS-1", "title": "The dimmer flickers at the lowest level", "severity": "high", "status": "open"},
              {"id": "ISS-2", "title": "The switch sticks", "severity": "medium", "status": "closed"},
              {"id": "ISS-3", "title": "Colour names are not sorted", "severity": "low", "status": "open"}]
    unit = ("import unittest\nfrom {m} import {f}\n\n\nclass {c}(unittest.TestCase):\n    def test_{f}(self):\n"
            "        self.assertEqual({f}(150), 100)\n")
    write(dest, {
        "README.md": "# Lantern\n\nA desk lamp simulation that runs on one computer.\n\n## Rounds\n\n"
                     "| Round | Goal | Status |\n|---|---|---|\n| 1 | First light | done |\n"
                     "| 2 | A dimmer | in progress |\n| 3 | Colour themes | planned |\n",
        "CLAUDE.md": "# Working here\n\nRun the gates with `py -3 tools/gates.py all` before a push "
                     "(about 40 headless gates).\n",
        "tools/gates.py": "print('gates')\n",
        "docs/planning/requirements.md": "# Requirements\n\n| ID | Requirement | Priority |\n|----|----|----|\n"
                                         "| R-01 | The lamp shall glow when it is switched on. | must |\n"
                                         "| R-02 | The dimmer shall keep the light between 5 and 100 percent. | should |\n",
        "laws/brightness.json": json.dumps({"laws": [
            {"id": "LAW-1", "rule": "Light never exceeds the brightness the person set."},
            {"id": "LAW-2", "text": "The lamp turns itself off after an hour without input."}]}, indent=1) + "\n",
        "docs/evidence/issues.jsonl": "".join(json.dumps(i) + "\n" for i in issues),
        "packages/core/setup.cfg": "[metadata]\nname = core\n",
        "packages/core/core_lib.py": "def glow(level):\n    return max(0, min(100, level))\n",
        "packages/core/tests/test_core.py": unit.format(m="core_lib", f="glow", c="GlowTest"),
        "packages/extras/setup.cfg": "[metadata]\nname = extras\n",
        "packages/extras/extras_lib.py": "def dim(level):\n    return max(5, min(100, level))\n",
        "packages/extras/tests/test_extras.py": unit.format(m="extras_lib", f="dim", c="DimTest"),
        "src/lamp.py": "LEVEL = 40\n\n\ndef level():\n    return LEVEL\n",
    })
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, *ID, "commit", "-q", "-m", "lantern")
    return dest


def by_key(record: dict) -> dict:
    return {c["key"]: c for c in record["checks"]}


class SecretContextTest(unittest.TestCase):
    def test_FR_ASP2_AC_1_a_url_that_is_a_credential_or_holds_one_and_a_value_beside_a_url_are_possibly_real(self):
        judge = assess_precise.judge_line
        lines = {
            "slack": f'HOOK = "https://hooks.slack.com/services/T{tok(9).upper()}/B{tok(9, 2).upper()}/{tok(24, 3)}"',
            "discord": f'HOOK = "https://discord.com/api/webhooks/{digits(18)}/{tok(60, 4)}"',
            "telegram": f'BOT = "https://api.telegram.org/bot{digits(9)}:{tok(35, 6)}/sendMessage"',
            "github": f'URL = "https://raw.host.invalid/{"ghp_" + tok(36, 8)}/file.txt"',
            "stripe": f'URL = "https://api.host.invalid/v1/{"sk_live_" + tok(24, 9)}/charges"',
            "beside": f'U = "https://files.cdn.invalid/a/{jwt_path()}/x.png"; key = "{tok(32, 10)}"',
        }
        for name, line in lines.items():
            verdict, reason = judge("src/notify.py", line)
            self.assertEqual(verdict, "possibly real", f"{name}: {reason}")
        self.assertIn("Slack webhook", judge("src/notify.py", lines["slack"])[1])
        self.assertIn("GitHub token", judge("src/notify.py", lines["github"])[1])
        self.assertEqual(judge("src/a.py", f'A = "https://files.cdn.invalid/att/{jwt_path()}/image.png"')[0],
                         "likely not a secret", "a long path alone is still a path")

    def test_FR_ASP2_AC_1_fake_words_count_only_in_test_files_and_only_as_words_of_their_own(self):
        fake = assess_precise.fake_value
        self.assertIsNone(fake("dummy" + tok(20), in_tests=False), "outside the tests a word says nothing")
        self.assertIsNone(fake("sample" + tok(20), in_tests=False))
        self.assertEqual(assess_precise.judge_line("src/settings.py", f'api_token = "mock{tok(20)}"')[0], "possibly real")
        self.assertIsNone(fake("latest" + tok(20, 12)), "latest is no test")
        self.assertIsNone(fake("sk_test_" + tok(24)), "a test-mode key is a secret")
        self.assertIsNone(fake("ghp_" + tok(36, 8) + "-test"), "a known format is never fake")
        self.assertTrue(fake("testTOKEN" + tok(14)))
        self.assertTrue(fake("fixture-" + tok(14)))
        self.assertEqual(assess_precise.judge_line("tests/fixtures/a.py", f'k = "latest{tok(20, 12)}"')[0],
                         "possibly real")

    def test_FR_ASP2_AC_1_a_signed_link_past_its_expiry_is_nothing_to_revoke_and_one_still_valid_is_real(self):
        base = "https://files.example.test/up/a.png?AWSAccessKeyId=AKIAEXAMPLEEXAMPLE0&Signature=abc123def456%2Fx&Expires="
        old = f"see ![img]({base}1000000000)"
        verdict, why = assess_precise.judge_line("docs/notes.md", old)
        self.assertEqual(verdict, "likely not a secret", why)
        self.assertIn("expired on 2001-09-09", why)
        self.assertNotIn("Signature", why)                                    # the date, never the link
        future = f"see ![img]({base}4102444800)"                              # 2100: still valid
        self.assertEqual(assess_precise.judge_line("docs/notes.md", future)[0], "possibly real")
        mixed = f"{old} and ({base}4102444800)"                               # one valid among them
        self.assertEqual(assess_precise.judge_line("docs/notes.md", mixed)[0], "possibly real")

    def test_FR_ASP2_AC_1_a_test_token_that_says_fixture_in_its_own_payload_is_not_a_secret(self):
        import base64

        def jwt(claims: dict) -> str:
            enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
            return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(claims)}.{tok(30, 12)}"

        made = jwt({"sub": "player_fixture", "tenant": "1d9c-fixture"})
        verdict, why = assess_precise.judge_line("apps/game/tests/network/fixtures/auth.json",
                                                 f'  "refresh_token": "{made}"')
        self.assertEqual(verdict, "likely not a secret", why)
        self.assertIn("fixture", why)
        self.assertNotIn(made, why)                                       # never the token itself
        real = jwt({"sub": "user-4711", "tenant": "acme"})
        self.assertEqual(assess_precise.judge_line("apps/game/tests/network/fixtures/auth.json",
                                                   f'  "refresh_token": "{real}"')[0], "possibly real")
        self.assertEqual(assess_precise.judge_line("src/auth.json", f'  "refresh_token": "{made}"')[0],
                         "possibly real", "outside the tests a payload's word says nothing")


class KindTest(unittest.TestCase):
    def test_FR_ASP2_AC_5_a_published_library_keeps_its_publish_findings_and_a_deployed_project_keeps_all(self):
        from kernel import assess_context

        def record(kind):
            return {"precise": {"kind": kind}, "checks": [
                {"key": k, "verdict": "failed", "id": f"F-{n}"} for n, k in
                enumerate(("security.policy", "cicd.pipeline", "architecture.config"), 1)]}

        lib = assess_context.put_off(None, record({"kind": "local", "published": True, "why": "no route"}))
        self.assertEqual([bool(c.get("later")) for c in lib["checks"]], [False, True, True])
        served = assess_context.put_off(None, record({"kind": "deployed", "why": "3 HTTP routes"}))
        self.assertFalse(any(c.get("later") for c in served["checks"]))
        self.assertEqual(assess_context.family_of("compliance.licence"), assess_context.family_of("security.policy"))
        self.assertEqual(assess_context.family_of("maintenance.issue_log:ISS-1"), "maintenance.issue_log")


class HarbourFixTest(FactoryTestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util

        if importlib.util.find_spec("pytest") is None:
            raise unittest.SkipTest("pytest runs the fixture's own suites")

    def setUp(self):
        super().setUp()
        self.project = adopted(self.factory, self.tmp)
        self.record = assess.assess(self.project, **WHO, which=no_scanner)
        self.src = self.tmp / "harbour"

    def commit_upstream(self, files: dict, message: str) -> str:
        write(self.src, files)
        git(self.src, "add", "-A")
        git(self.src, *ID, "commit", "-q", "-m", message)
        return sync(self.project)["upstream"]

    def test_FR_ASP2_AC_1_a_fixture_mark_covers_the_values_marked_not_one_added_later(self):
        real = secrets(self.record)["packages/engine/settings.py"]
        assess_precise.give(self.project, real["id"], "fixture", **WHO, reason="a local stand-in")
        head = self.commit_upstream({"packages/engine/settings.py":
                                     f'api_token = "{token()}"\nsession_secret = "{tok(28, 21)}"\n'}, "a new key")
        again = assess.assess(self.project, **WHO, which=no_scanner, ref=head)
        rows = sorted((c for c in again["checks"] if assess_precise.secret_rule(c) and c["verdict"] == "failed"
                       and c["evidence"][0]["file"] == "packages/engine/settings.py"),
                      key=lambda c: c["evidence"][0]["line"])
        self.assertEqual([c["likely"]["verdict"] for c in rows], ["likely not a secret", "possibly real"])
        self.assertIn("not this one", rows[1]["likely"]["reason"])
        self.assertNotEqual(rows[1]["severity"], "info")

    def test_FR_ASP2_AC_2_a_secret_is_marked_not_relevant_only_by_those_who_judge_secrets(self):
        real = secrets(self.record)["packages/engine/settings.py"]["id"]
        with self.assertRaises(PermissionError):
            assess_precise.give(self.project, real, "not_relevant", person="Eve Example", persona="end_user",
                                reason="looks fine to me")
        other = next(c["id"] for c in self.record["checks"] if c.get("id") and not assess_precise.secret_rule(c))
        with self.assertRaises(PermissionError):
            assess_precise.give(self.project, other, "not_relevant", person="Eve Example", persona="end_user",
                                reason="not for us", also=[real])
        out = assess_precise.give(self.project, other, "not_relevant", person="Eve Example", persona="end_user",
                                  reason="not for us")
        self.assertEqual(out["findings"], [other], "any finding that is no secret is anyone's to judge")
        view = assess_cards.view(self.project)
        self.assertIn(real, [r["id"] for r in view["priority"]])
        from cockpit import solo_routes

        out = ask(self.factory, f"{real} is not relevant because it looks fine to me", persona="end_user",
                  project_id=self.project.pid, view="assessment")
        self.assertEqual(out["propose"], [], "Ask Rihma offers no way around it either")
        self.assertIn("judges it", out["answer"])
        need = solo_routes.NEEDS["post_assessment_verdict"]
        self.assertEqual(need(self.factory, {"pid": self.project.pid}, {"verdict": "not_relevant", "finding": real}),
                         assess_precise.MARKERS)

    def test_FR_ASP2_AC_2_findings_of_the_same_kind_are_proposed_for_every_rule(self):
        failed = {c["key"]: c for c in self.record["checks"] if c["verdict"] == "failed" and c.get("id")}
        self.assertIn("security.policy", failed)
        self.assertIn("compliance.licence", failed)
        out = assess_precise.give(self.project, failed["security.policy"]["id"], "not_relevant", **WHO,
                                  reason="a private project")
        self.assertIn(failed["compliance.licence"]["id"], out["similar"])
        self.assertTrue(out["family"])
        shown = {c.get("id"): c for c in assess_cards.view(self.project)["latest"]["checks"]}
        self.assertEqual(shown[failed["compliance.licence"]["id"]]["propose_dismiss"]["like"],
                         failed["security.policy"]["id"])

    def test_FR_ASP2_AC_3_a_mapped_runner_s_results_are_read_from_the_synced_upstream_and_the_headline_follows(self):
        assess_measure.map_runner(self.project, command="py -3 tools/gates.py test", results="build/gates.xml",
                                  note="on the build machine", **WHO)
        head = assess_cards.view(self.project)["headline"]
        self.assertNotIn("not mapped", head["gaps"] or "")
        self.assertIn("assess again", head["gaps"])
        self.assertEqual([s["do"] for s in head["next"] if "runner" in s["do"] or "assess" in s["do"]], ["assess_again"])

        again = by_key(assess.assess(self.project, **WHO, which=no_scanner))["maintenance.tests_measured"]
        self.assertEqual(again["verdict"], "not measured")
        self.assertIn("Sync", again["reason"])
        head = assess_cards.view(self.project)["headline"]
        self.assertIn("results are not read yet", head["gaps"])
        self.assertNotIn("map_runner", [s["do"] for s in head["next"]])
        self.assertIn("runner_results", [s["do"] for s in head["next"]])

        self.commit_upstream({"build/gates.xml": '<testsuites tests="660" failures="0" errors="0">'
                                                 '<testsuite tests="660"/></testsuites>\n'}, "gate results")
        card = self.project.read("adopted.json")["last_sync"]["card"]
        measured = by_key(assess.assess(self.project, **WHO, which=no_scanner))["maintenance.tests_measured"]
        self.assertEqual((measured["verdict"], measured["summary"]), ("passed", "660 passed, read from build/gates.xml"))
        said = json.dumps(measured["evidence"])
        self.assertIn("upstream", said)
        self.assertIn(card, said)
        head = assess_cards.view(self.project)["headline"]
        self.assertNotIn("runner", " ".join(s["do"] for s in head["next"]))

    def test_FR_ASP2_AC_6_gaps_are_their_own_line_and_ask_rihma_gives_each_next_step_a_button(self):
        head = assess_cards.view(self.project)["headline"]
        self.assertIn("not mapped", head["gaps"])
        self.assertIn("imported plan", head["gaps"])
        self.assertNotIn("not measured", head["noise"])
        self.assertNotIn("imported plan", head["noise"])
        out = ask(self.factory, "What in the assessment is worth acting on, and what is noise?", persona="developer",
                  project_id=self.project.pid)
        self.assertIn("Gaps to close", out["answer"])
        steps = out["steps"]
        self.assertEqual([s["label"] for s in steps], [s["label"] for s in head["next"]])
        for s in steps:
            self.assertTrue(s["navigate"]["route"].startswith(f"#/p/{self.project.pid}/"), s)
            self.assertTrue(s["navigate"]["control"], s)


class LanternTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.project = adopt(self.factory, "Lantern", source=str(lantern(self.tmp / "lantern")), intent="monitor",
                             **WHO, suite_timeout=120)
        self.record = assess.assess(self.project, **WHO, which=no_scanner)

    def test_FR_ASP2_AC_3_a_gates_command_is_a_test_command_and_the_kernel_s_run_is_said_as_it_was(self):
        self.assertEqual(agent_context_use._kind("py -3 tools/gates.py all", "Run the gates with"), "test")
        measured = by_key(self.record)["maintenance.tests_measured"]
        self.assertEqual(measured["verdict"], "not measured")
        self.assertIn("py -3 tools/gates.py all", json.dumps(measured["evidence"]))
        self.assertIn("CLAUDE.md", json.dumps(measured["evidence"]))
        repo = Repo(root=self.tmp, files=[], bare=self.tmp, revision="b" * 40, committed="",
                    records={"inventory": {"tests": [{"runner": "unittest"}]},
                             "baseline": {"verdict": "not measured", "revision": "a" * 40,
                                          "reason": "not measured: no test ran"}})
        reason = assess_measure.tests_measured(repo)["reason"]
        self.assertNotIn("did not pass at this revision", reason)
        self.assertIn("at adoption", reason)
        self.assertIn("aaaaaaaaaaaa", reason)

    def test_FR_ASP2_AC_4_unittest_runs_in_each_package_s_own_root_and_every_line_says_what_ran(self):
        tests = detect_tests(self.tmp / "lantern", ["packages/core/setup.cfg", "packages/core/tests/test_core.py",
                                                    "packages/extras/setup.cfg", "packages/extras/tests/test_extras.py"])
        self.assertEqual([(t["runner"], t.get("cwd")) for t in tests],
                         [("unittest", "packages/core"), ("unittest", "packages/extras")])
        runs = [(r.get("cwd"), r["verdict"]) for r in self.project.read("baseline.json")["runs"]]
        self.assertIn(("packages/core", "passed"), runs)
        precise = self.record["precise"]
        self.assertEqual(precise["test_roots"], ["packages/core", "packages/extras"])
        self.assertIn("unittest", precise["measured_against"])
        alone = assess_measure.against_roots([{"runner": "unittest"}], ["packages/core", "packages/extras"])
        self.assertEqual(alone, [], "roots no run used are not said to be run")
        alignment_records.scan(self.project, **WHO)
        said = alignment_records.view(self.project)["summary"]["against"]
        self.assertIn("unittest", said)

    def test_FR_ASP2_AC_5_a_local_project_s_deploy_and_publish_findings_are_for_later_and_the_landing_leads_there(self):
        view = assess_cards.view(self.project)
        failed = {c["key"]: c for c in view["latest"]["checks"] if c["verdict"] == "failed"}
        for key in ("cicd.pipeline", "security.policy", "compliance.licence", "architecture.config"):
            self.assertIn(key, failed)
            self.assertIn("local project", failed[key]["later"]["reason"], key)
            self.assertNotIn(failed[key]["id"], view["headline"]["act_ids"], key)
        self.assertIn("for later", view["headline"]["noise"])
        order = [r["id"] for r in view["priority"]]
        self.assertLess(order.index(failed["maintenance.issue_log:ISS-1"]["id"]),
                        order.index(failed["cicd.pipeline"]["id"]),
                        "a finding for later goes after one to act on now in the suggested order")
        issue = failed["maintenance.issue_log:ISS-1"]
        self.assertIn(issue["id"], view["headline"]["act_ids"])
        assess_precise.give(self.project, failed["security.policy"]["id"], "relevant", **WHO)
        back = assess_cards.view(self.project)
        self.assertIn(failed["security.policy"]["id"], back["headline"]["act_ids"], "a person brings it back")
        out = ask(self.factory, f"{failed['compliance.licence']['id']} is relevant now", persona="developer",
                  project_id=self.project.pid, view="assessment")
        self.assertEqual((out["propose"][0]["args"]["op"], out["propose"][0]["args"]["call"]["body"]["verdict"]),
                         ("dismiss_finding", "relevant"))
        self.assertIn("put off for later", out["answer"])

        brief = devbrief.briefing(self.project, person="Ida Example")
        self.assertEqual(brief["assessment"]["route"], f"#/p/{self.project.pid}/assessment")
        self.assertTrue(brief["assessment"]["act"].startswith("Worth acting on now:"))
        from kernel import assess_context

        step = assess_context.landing_step(self.project, {"title": "Every task is merged: release it or take the "
                                                                   "next change", "task": None, "why": "x",
                                                          "action": {"route": "#/x", "label": "x", "control": None}})
        self.assertEqual(step["action"]["route"], f"#/p/{self.project.pid}/assessment")
        self.assertIn("assessment", step["title"].lower())

    def test_FR_ASP2_AC_7_requirements_in_tables_and_json_rounds_in_a_readme_and_an_issue_log_are_read(self):
        alignment_records.scan(self.project, **WHO)
        groups = {g["id"]: g["items"] for g in alignment_records.view(self.project)["groups"]}
        refs = {i["source"]["ref"] for i in groups["requirements"]}
        self.assertTrue({"R-01", "R-02", "LAW-1", "LAW-2"} <= refs, refs)
        statements = " ".join(i["proposal"]["statement"] for i in groups["requirements"])
        self.assertIn("never exceeds the brightness", statements)
        tasks = {i["proposal"]["title"]: i["proposal"]["done"] for i in groups["tasks"]}
        self.assertEqual((tasks.get("First light"), tasks.get("A dimmer")), (True, False), tasks)
        checks = by_key(self.record)
        self.assertEqual((checks["maintenance.issue_log:ISS-1"]["verdict"],
                          checks["maintenance.issue_log:ISS-1"]["severity"]), ("failed", "high"))
        self.assertEqual(checks["maintenance.issue_log:ISS-3"]["severity"], "low")
        self.assertNotIn("maintenance.issue_log:ISS-2", checks, "a closed issue is no finding")
        out = assess_precise.give(self.project, checks["maintenance.issue_log:ISS-1"]["id"], "not_relevant", **WHO,
                                  reason="handled in another tracker")
        self.assertEqual(out["similar"], [checks["maintenance.issue_log:ISS-3"]["id"]])


class PortCockpit(CockpitTestCase):
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


class RouteTest(PortCockpit):
    def test_FR_ASP2_AC_2_the_cockpit_refuses_a_secret_marked_not_relevant_by_an_end_user(self):
        import importlib.util

        if importlib.util.find_spec("pytest") is None:
            self.skipTest("pytest runs the fixture's own suites")
        project = adopted(self.factory, self.tmp)
        pid = project.pid
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/assessment", WHO)[0], 201)
        _, view, _ = self.call("GET", f"/api/projects/{pid}/assessment")
        real = secrets(view["latest"])["packages/engine/settings.py"]["id"]
        path = f"/api/projects/{pid}/assessment/verdict"
        status, body, _ = self.call("POST", path, {"finding": real, "verdict": "not_relevant",
                                                   "reason": "looks fine to me", "person": "Eve Example",
                                                   "persona": "end_user"})
        self.assertEqual(status, 403, body)
        status, body, _ = self.call("POST", path, {"finding": real, "verdict": "not_relevant", "reason": "a stand-in",
                                                   **WHO})
        self.assertEqual(status, 200, body)


if __name__ == "__main__":
    unittest.main()
