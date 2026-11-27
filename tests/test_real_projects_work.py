"""FR-RPJ1: working on an existing project once it is adopted (kernel/assistant_work.py, kernel/adopt_seen.py,
kernel/walkthrough_adopt.py, kernel/agent_bridge.py, kernel/copilot.py).

Ask Rihma's how-to with the project's real id and its baseline's test command, the status naming a failing
check, a goal to change the code planned as development (not a deployment), a workspace coming back to New
project and to the Plug in walkthrough with its adopted repositories said, and the hand-off brief's tests,
conventions and insights. Neutral fixtures only (tests/rpj_fixture.py and invented files here).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rpj_fixture as fx  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from walkthrough_fakes import allow_roots  # noqa: E402

from kernel import adopt, assistant, copilot, material_git  # noqa: E402
from kernel import agent_bridge as bridge  # noqa: E402
from kernel import walkthrough as wk  # noqa: E402
from kernel.adopt_seen import workspace_seen  # noqa: E402
from kernel.assistant_status import status_answer  # noqa: E402
from kernel.assistant_work import asks_work, work_answer  # noqa: E402

P, R = "Aino Tester", "developer"
APP = {"README.md": "# Berths\n\nBookings for the harbour's berths.\n",
       "berths.py": "def free(n):\n    return max(n, 0)\n",
       "CLAUDE.md": "# Berths\n\nRun the tests before every change.\n",
       "tests/test_berths.py": "import unittest\n\nfrom berths import free\n\n\nclass T(unittest.TestCase):\n"
                               "    def test_free(self):\n        self.assertEqual(free(-1), 0)\n"}


class Adopted(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = self.tmp.resolve()
        allow_roots(self, self.tmp)
        self.src = fx.repo(self.tmp / "berths", APP)
        self.p = adopt.adopt(self.factory, "Berths", source=str(self.src), intent="improve", person=P, persona=R,
                             suite_timeout=120)

    def test_FR_RPJ1_AC_17_how_to_work_on_it_gives_the_real_commands_its_baseline_and_the_console(self):
        q = "how do I work on this in my terminal?"
        self.assertTrue(asks_work(q))
        self.assertFalse(asks_work("what is the status of this project?"))
        with mock.patch("kernel.copilot.goal_answer", side_effect=AssertionError("no plan for a how-to")):
            got = assistant.ask(self.factory, q, persona=R, project_id=self.p.pid, person=P)
        text = got["answer"]
        for cmd in (f"rihmasto workspace open {self.p.pid} --person \"{P}\"", f"rihmasto workspace submit {self.p.pid}",
                    f"rihmasto shell {self.p.pid}", f"rihmasto ide {self.p.pid}"):
            self.assertIn(cmd, text)
        runs = (self.p.read("baseline.json") or {}).get("runs") or []
        self.assertTrue(runs, "the adoption ran its tests for a baseline")
        self.assertIn(" ".join(runs[0]["command"]), text)
        self.assertIn("Your own folder is never changed", text)
        self.assertEqual(got["navigate"], {"route": f"#/p/{self.p.pid}/console", "control": "console_terminal"})
        self.assertEqual(got["by"], "map")
        unnamed = work_answer(self.p)["answer"]
        self.assertIn('--person "<your name>"', unnamed)

    def test_FR_RPJ1_AC_17_a_project_with_no_code_yet_says_so(self):
        p = self.factory.new_project("Loans", mode="mixed", maturity="demo")
        got = work_answer(p, person=P)
        self.assertIn("has no code yet", got["answer"])
        self.assertEqual(got["navigate"]["route"], f"#/p/{p.pid}/overview")

    def test_FR_RPJ1_AC_17_the_status_names_a_failing_check(self):
        failing = {"failing": ["Secret scan"], "line": "1 check failing: Secret scan"}
        with mock.patch("kernel.checks.health.project_health", return_value=failing):
            said = status_answer(self.p)["answer"]
        self.assertIn("and 1 check failing: Secret scan (see Health).", said)
        self.assertNotIn("check failing", status_answer(self.p)["answer"])

    def test_FR_RPJ1_AC_17_a_goal_to_change_the_code_is_planned_as_development_not_a_deployment(self):
        goal = "I want to add a --dry-run option to the deploy command"
        self.assertEqual(copilot.intents(goal), ["develop"])
        self.assertIn("cloud", copilot.intents("deploy it to production in our cloud and add a health endpoint"))
        self.assertTrue(copilot.asks_goal(goal))
        plan = copilot.rule_plan(self.factory, self.p, goal)
        titles = [s["title"] for s in plan["steps"]]
        self.assertIn("See what its repository already says", titles)
        self.assertIn("Build it in a branch of your own", titles)
        self.assertIn("Run its tests in the Console", titles)
        self.assertFalse([t for t in titles if "production" in t.lower() or "deploy gate" in t.lower()], titles)
        branch = next(s for s in plan["steps"] if s["title"] == "Build it in a branch of your own")
        self.assertIn(f"rihmasto workspace open {self.p.pid}", branch["action"]["command"])

    def test_FR_RPJ1_AC_19_the_brief_gives_its_baseline_tests_its_conventions_and_insights_in_words(self):
        b = bridge.brief(self.p)
        self.assertNotIn("paved road's product suite", " ".join(b["tests"]))
        runs = (self.p.read("baseline.json") or {}).get("runs") or []
        self.assertIn(f"`{' '.join(runs[0]['command'])}`", b["tests"][0])
        self.assertIn("at the adoption's baseline", b["tests"][0])
        b["insights"] = {"health": {"at_risk": 0, "failures": 2}}
        text = bridge.render(b)
        self.assertIn("- health: at risk 0, failures 2", text)
        self.assertNotIn("{'at_risk'", text)
        conv = text.split("## The project's conventions", 1)[1].split("##", 1)[0]
        self.assertIn("CLAUDE.md", conv)
        self.assertIn("Read from", conv)


class Workspace(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = self.tmp.resolve()
        allow_roots(self, self.tmp)
        self.ws = fx.workspace(self.tmp / "harbour")
        self.app = adopt.adopt(self.factory, "Harbour · harbour-app", source=str(self.ws / "harbour-app"),
                               intent="improve", person=P, persona=R, suite_timeout=1)

    def walk(self, *replies) -> dict:
        w = wk.start(self.factory, "plug_in", person=P, persona=R)
        for r in replies:
            w = wk.reply(self.factory, w["id"], person=P, persona=R, **(r if isinstance(r, dict) else {"text": r}))
        return w

    @staticmethod
    def said(w: dict) -> str:
        return " ".join(m.get("text") or "" for m in w["messages"] if m["from"] == "rihma")

    def test_FR_RPJ1_AC_18_a_workspace_scanned_again_marks_the_repositories_adopted_already(self):
        ws = material_git.workspace(self.ws)
        got = workspace_seen(self.factory, ws)
        self.assertEqual([(g["path"], g["project"]) for g in got], [("harbour-app", self.app.pid)])
        by = {r["path"]: r["adopted_as"] for r in ws["repositories"]}
        self.assertEqual(by["harbour-tools"], [])
        self.assertEqual(by["harbour-app"][0]["title"], "Harbour · harbour-app")

    def test_FR_RPJ1_AC_18_the_walkthrough_says_which_repositories_are_adopted_and_offers_open(self):
        w = self.walk(str(self.ws))
        self.assertEqual(w["step"], "seen")
        self.assertIn(f"harbour-app as Harbour · harbour-app ({self.app.pid})", self.said(w))
        last = [m for m in w["messages"] if m["from"] == "rihma"][-1]
        self.assertEqual([o["id"] for o in last["options"]][:3], ["open", "again", "another"])
        self.assertEqual([x["label"] for x in last["links"]], ["Open Harbour · harbour-app"])
        done = wk.reply(self.factory, w["id"], person=P, persona=R, choice="open")
        self.assertEqual(done["state"], "done")
        self.assertIn("It is in the factory already", self.said(done))

    def test_FR_RPJ1_AC_18_the_same_repository_given_again_is_adopted_already(self):
        w = self.walk(str(self.ws / "harbour-app"))
        self.assertEqual(w["step"], "seen")
        self.assertIn(f"Already adopted as Harbour · harbour-app ({self.app.pid})", self.said(w))
        again = wk.reply(self.factory, w["id"], person=P, persona=R, choice="again")
        self.assertEqual(again["step"], "title")

    def test_FR_RPJ1_AC_18_a_workspace_none_of_whose_repositories_is_adopted_is_said_to_be_one_snapshot(self):
        other = fx.workspace(self.tmp / "quay")
        w = self.walk(str(other))
        self.assertEqual(w["step"], "title")
        self.assertIn("a workspace of 2 git repositories", self.said(w))
        self.assertIn("Adopt each as its own project", self.said(w))


if __name__ == "__main__":
    unittest.main()
