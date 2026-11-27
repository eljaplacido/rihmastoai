"""FR-RPJ1: what the verifiers of the r3b dogfood rounds found, held (kernel/assistant_work.py, kernel/copilot.py,
kernel/agent_bridge.py, kernel/console_offers.py, kernel/material_git.py, kernel/workspace.py, kernel/adopt.py,
kernel/repo_specs.py, kernel/automations_actions.py, kernel/confidential_local.py).

Ask Rihma answers how to work on the project, and only that: questions that merely name the command line stay
the map's. A goal to fix something is planned as development, built before it is delivered. Copied commands
say how they run on this machine. The hand-off brief of a confidential project says local models only, and a
brief for one change keeps to it. Neutral fixtures only (tests/rpj_fixture.py and invented files here).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rpj_fixture as fx  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from walkthrough_fakes import allow_roots  # noqa: E402

from kernel import adopt, assistant, copilot  # noqa: E402
from kernel.assistant_work import asks_work  # noqa: E402

P, R = "Aino Tester", "developer"
APP = {"README.md": "# Berths\n\nBookings for the harbour's berths.\n",
       "berths.py": "def free(n):\n    return max(n, 0)\n",
       "AGENTS.md": "# Berths\n\n## Tests\n\n```\npython -m unittest discover -s tests\n```\n",
       "tests/test_berths.py": "import unittest\n\nfrom berths import free\n\n\nclass T(unittest.TestCase):\n"
                               "    def test_free(self):\n        self.assertEqual(free(-1), 0)\n"}


class Asked(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = self.tmp.resolve()
        allow_roots(self, self.tmp)
        self.src = fx.repo(self.tmp / "berths", APP)
        self.p = adopt.adopt(self.factory, "Berths", source=str(self.src), intent="improve", person=P, persona=R,
                             suite_timeout=120)

    def ask(self, q, project=True):
        return assistant.ask(self.factory, q, persona=R, project_id=self.p.pid if project else None, person=P)

    def test_FR_RPJ1_AC_25_a_question_that_only_names_the_command_line_is_not_the_terminal_recipe(self):
        for q in ("how do I export the evidence pack from the command line?", "how do I approve the plan from the cli?",
                  "How do I enable a check from the command line?", "How does the shell option in the console work?",
                  "How do I add a CLI to my product?", "How can we develop monitoring for this?",
                  "how do I work on the alignment items?", "what are the agents working on in the console?"):
            self.assertFalse(asks_work(q), q)
            got = self.ask(q)
            self.assertNotIn("rihmasto workspace open", got["answer"], q)

    def test_FR_RPJ1_AC_25_working_on_the_project_itself_gets_its_commands(self):
        for q in ("how do I work on this in my terminal?", "how can I edit the code of Berths myself?",
                  "how can I edit the code myself?"):
            got = self.ask(q)
            self.assertIn(f"rihmasto workspace open {self.p.pid}", got["answer"], q)
        home = self.ask("how do I work on Berths in my terminal?", project=False)
        self.assertIn(f"rihmasto workspace open {self.p.pid}", home["answer"])

    def test_FR_RPJ1_AC_25_ide_tests_and_commands_questions_get_their_own_answer(self):
        ide = self.ask("Where do I set up my IDE?")
        self.assertEqual(ide["navigate"]["control"], "ide_setup")
        for q in ("what is the test command for this", "how do I run my evaluation", "how do I run its tests?"):
            got = self.ask(q)
            self.assertIn(got["navigate"]["control"], ("console_run", "health_enable"), q)
            self.assertNotIn("try", got["navigate"]["route"], q)
        state = self.ask("Where do I state the project's commands for the terminal?")
        self.assertEqual(state["navigate"]["control"], "console_settings")

    def test_FR_RPJ1_AC_25_no_test_command_found_says_where_to_name_one(self):
        self.p.write("baseline.json", {"verdict": "not measured", "reason": "no test runner was found"})
        self.p.write("agent_context.json", {"stated": []})
        got = self.ask("how do I run its tests?")
        self.assertIn("no test command was found by rule", got["answer"])
        self.assertEqual(got["navigate"]["control"], "health_enable")

    def test_FR_RPJ1_AC_28_a_suite_that_could_not_run_is_not_said_as_failing_tests(self):
        from kernel.status import failed_baseline

        self.p.write("baseline.json", {"verdict": "failed", "runs": [
            {"command": ["python", "-m", "pytest"], "counts": {"passed": 0, "failed": 0, "errors": 8}}]})
        said = failed_baseline(self.p)
        self.assertIn("could not run at the baseline", said)
        self.assertNotIn("tests fail", said)

    def test_FR_RPJ1_AC_25_the_copied_commands_say_how_they_run_here(self):
        with mock.patch("kernel.console_term.shutil.which", return_value=None):
            got = self.ask("how do I work on this in my terminal?")
        self.assertIn("-m kernel.cli --home", got["answer"])
        self.assertIn('--person "Aino Tester"', got["answer"])

    def test_FR_RPJ1_AC_26_a_fix_is_planned_as_development_built_before_it_is_delivered(self):
        for q in ("fix the crash in the deploy command", "fix the bug in the login page"):
            self.assertTrue(copilot.asks_goal(q), q)
            p = copilot.plan(self.factory, self.p, q)
            titles = [s["title"] for s in p["steps"]]
            self.assertTrue(any("branch of your own" in t or "Build it" in t for t in titles), (q, titles))
            self.assertFalse(any("web app with sign-in" in t for t in titles), (q, titles))
        p = copilot.plan(self.factory, self.p, "add a --dry-run option to the deploy command and deploy it to production")
        titles = [s["title"] for s in p["steps"]]
        build = next(i for i, t in enumerate(titles) if "branch of your own" in t or "Build it" in t)
        deliver = [i for i, t in enumerate(titles) if "deploy gate" in t]
        self.assertTrue(not deliver or build < deliver[0], titles)


class Brief(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = self.tmp.resolve()
        allow_roots(self, self.tmp)
        self.src = fx.repo(self.tmp / "berths", APP)
        self.p = adopt.adopt(self.factory, "Berths", source=str(self.src), intent="improve", person=P, persona=R,
                             suite_timeout=120)

    def test_FR_RPJ1_AC_27_a_confidential_project_s_brief_says_local_models_only(self):
        from kernel import agent_bridge as bridge
        from kernel.copilot_steps import handoff_step

        self.p.meta["confidential"] = True
        self.p.save_meta() if hasattr(self.p, "save_meta") else None
        data = bridge.brief(self.p)
        data["project"]["confidential"] = True
        self.assertIn("Confidential: local models only", bridge.render(data))
        self.assertNotIn("Confidential", bridge.render({**data, "project": {**data["project"], "confidential": False}}))
        self.assertIn("local model", handoff_step({"pid": self.p.pid, "confidential": True})["detail"])
        self.assertNotIn("local model", handoff_step({"pid": self.p.pid})["detail"])

    def test_FR_RPJ1_AC_27_a_brief_for_one_change_keeps_to_it_and_says_it_is_undecided(self):
        from kernel.agent_bridge import change_said

        lines = change_said({"id": "C-0001", "text": "Add --dry-run", "state": "open",
                             "deciders": ["business_owner", "product_owner"]})
        said = "\n".join(lines)
        self.assertIn("Not decided yet", said)
        self.assertIn("business owner or product owner", said)
        self.assertIn("The scope is this change alone", said)


class Pieces(unittest.TestCase):
    def test_FR_RPJ1_AC_28_a_template_command_fills_the_line_and_is_not_a_redirect(self):
        from kernel.console_offers import _offer, short_label

        o = _offer("x", "py -3 output/build_notes/2026_10/lane_gates.py --lane <lane> <gates>", "AGENTS.md")
        self.assertTrue(o["template"])
        self.assertFalse(o["shell"])
        self.assertEqual(short_label("py -3 output/build_notes/2026_10/lane_gates.py --lane <lane>", "test"),
                         "Test: lane_gates.py")
        self.assertFalse(_offer("x", "python -m pytest", "AGENTS.md")["template"])

    def test_FR_RPJ1_AC_28_a_path_is_not_masked_as_a_secret(self):
        from kernel.redteam.masking import _random_token

        self.assertFalse(_random_token("output/build_notes/2026_10/lane_gates"))
        self.assertTrue(_random_token("sk9Fq2LmZ7xR4tWv8Yb3Nc6Pd"))

    def test_FR_RPJ1_AC_28_two_clones_of_one_origin_are_one_repository_and_a_copy(self):
        from kernel.material_git import _same_origin

        repos = [{"path": "work/tool-cockpit", "origin": "https://example.invalid/a/tool.git", "copy": False,
                  "commits": 3},
                 {"path": "work/tool", "origin": "https://example.invalid/a/tool", "copy": False, "commits": 9}]
        _same_origin(repos)
        self.assertFalse(repos[1]["copy"])
        self.assertTrue(repos[0]["copy"] and repos[0]["same_origin"])
        self.assertEqual(repos[0]["copy_of"], "work/tool")

    def test_FR_RPJ1_AC_28_a_bullet_requirement_is_read_whole(self):
        from kernel.repo_specs import _first_line, criterion

        got = _first_line(["- Client wraps the REST API (HTTP) + WebSocket for", "  the lobby and matches.", ""], "x")
        self.assertEqual(got, "Client wraps the REST API (HTTP) + WebSocket for the lobby and matches.")
        self.assertNotIn("-", criterion("- ZONE_BOUNDS hold every spawn", 3)["then"][:2])

    def test_FR_RPJ1_AC_28_gdscript_is_a_language(self):
        from kernel.material_kinds import LANGUAGES

        self.assertEqual(LANGUAGES[".gd"], "GDScript")
        self.assertEqual(adopt.LANGUAGES[".gd"], "GDScript")

    def test_FR_RPJ1_AC_28_errors_while_collecting_are_not_failing_tests(self):
        from kernel.adopt import _baseline_verdict

        verdict, why = _baseline_verdict("pytest", 2, {"passed": 0, "failed": 0, "errors": 8},
                                         "Interrupted: 4 errors during collection", Path("."))
        self.assertEqual(verdict, "failed")          # the existing behaviour, recorded (FR-X1-AC-1)
        self.assertIn("could not run", why)
        self.assertIn("no test ran", why)

    def test_FR_RPJ1_AC_28_a_top_level_skill_is_an_ai_tool_file_and_unmeasured_insights_are_left_out(self):
        from kernel.agent_bridge import insight_lines
        from kernel.agent_context import sub_kind

        self.assertEqual(sub_kind("skills/factory-gate/SKILL.md"), "skill")
        self.assertEqual(sub_kind(".claude/skills/tidy/SKILL.md"), "skill")
        self.assertIsNone(sub_kind("docs/skills.md"))
        self.assertEqual(insight_lines({"security": {"open_findings": "not measured (no scan ran)",
                                                     "secret_hits": "not measured"},
                                        "health": {"at_risk": 1}}), ["- health: at risk 1"])

    def test_FR_RPJ1_AC_28_a_demos_specs_are_not_the_products_requirements(self):
        from kernel.repo_structure import roles

        self.assertNotIn("spec", roles("demo/run0/specs/requirements.md"))
        self.assertNotIn("spec", roles("examples/specs/prd.md"))
        self.assertIn("spec", roles("docs/specs/requirements.md"))

    def test_FR_RPJ1_AC_28_pytest_never_collects_generated_output_folders(self):
        from kernel.adopt import detect_tests

        files = ["conftest.py", "tests/test_a.py", "output/build_notes/x/test_scratch.py"]
        cmd = detect_tests(Path("."), files)[0]["command"]
        self.assertIn("--ignore=output", cmd)
        self.assertNotIn("--ignore=output", detect_tests(Path("."), files[:2])[0]["command"])

    def test_FR_RPJ1_AC_28_the_local_model_fix_says_it_is_machine_wide(self):
        from kernel import confidential_local as cl

        got = {"roles": ["builder"], "model": "m", "endpoint": "e", "host": "h", "left": {}}
        with mock.patch.object(cl, "offer", return_value=got),                 mock.patch.object(cl, "hosted", return_value=[{"role": "builder", "endpoint": "go", "url": "https://go.example.invalid/v1"}]):
            n = cl.notice({"roles": {}})
        self.assertIn("every project on this machine", n["fix"])


class PlugInAddress(FactoryTestCase):
    def test_FR_RPJ1_AC_29_plug_in_takes_a_git_address(self):
        from kernel import walkthrough as wk

        w = wk.start(self.factory, "plug_in", person=P, persona=R)
        w = wk.reply(self.factory, w["id"], person=P, persona=R, text="https://example.invalid/team/berths.git")
        said = [m for m in w["messages"] if m["from"] == "rihma"][-1]["text"]
        self.assertNotIn("I cannot adopt from that address", said)
        wk.cancel(self.factory, w["id"], person=P, persona=R)
        w = wk.reply(self.factory, wk.start(self.factory, "plug_in", person=P, persona=R)["id"],
                     person=P, persona=R, text="ftp://example.invalid/x.git")
        self.assertTrue(any("cannot adopt from that address" in m["text"] for m in w["messages"]),
                        [m["text"][:120] for m in w["messages"]])


class Workspace(FactoryTestCase):
    def test_FR_RPJ1_AC_29_open_merges_rihmas_mcp_server_into_the_projects_own(self):
        from kernel.workspace import _merge_mcp

        root = fx.repo(self.tmp / "game", {".mcp.json": json.dumps({"mcpServers": {"engine": {"command": "e"}}}),
                                           "README.md": "# g\n"})
        _merge_mcp(root, {"mcpServers": {"rihma": {"command": "r"}}})
        got = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(set(got["mcpServers"]), {"engine", "rihma"})
        self.assertEqual(fx.git(root, "status", "--porcelain"), "")   # never in the person's commits

    def test_FR_RPJ1_AC_29_the_gate_judges_an_adopted_project_by_its_own_suite(self):
        from kernel.gate_own import signal_own_suites

        ok = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(True)\n"
        bad = ok + "\n    def test_b(self):\n        self.assertEqual(1, 2)\n"
        root = fx.repo(self.tmp / "own", {"checks/test_a.py": ok, "README.md": "# o\n"})
        suite = {"ecosystem": "python", "runner": "unittest", "command": ["python", "-m", "unittest", "discover",
                                                                          "-s", "checks", "-v"], "verdict": "passed"}
        self.assertIsNone(signal_own_suites(root, []))
        self.assertEqual(signal_own_suites(root, [suite]).verdict, "passed")
        (root / "checks/test_a.py").write_text(bad, encoding="utf-8")
        self.assertEqual(signal_own_suites(root, [suite]).verdict, "failed")
        was = suite | {"verdict": "failed", "counts": {"passed": 1, "failed": 1}}
        self.assertEqual(signal_own_suites(root, [was]).verdict, "passed")    # no new failure

    def test_FR_RPJ1_AC_29_a_first_visit_to_the_console_offers_the_repositorys_commands(self):
        from kernel.console_offers import offers

        root = fx.repo(self.tmp / "tool", {"package.json": json.dumps({"scripts": {"lint": "eslint ."}}),
                                           "Makefile": "check:\n\tpython -m pytest\n", "README.md": "# t\n"})
        lines = [o["line"] for o in offers(None, {}, None, repo=root)]
        self.assertIn("npm run lint", lines)
        self.assertTrue(any("make check" in x for x in lines), lines)
        self.assertEqual(offers(None, {}, None), [])


if __name__ == "__main__":
    unittest.main()
