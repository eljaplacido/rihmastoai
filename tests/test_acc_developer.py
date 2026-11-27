"""What the developer acceptance test (2026-11-26) found, each fixed and kept fixed, through the kernel and the API.

- a cockpit started with a relative ``--home`` (as the README shows) makes the home absolute, so the Console's
  working copy is cloned and its commands run; a copy that cannot be made is a 409 with one plain sentence;
- a demo home answers Ask Rihma from the map and keeps its own lanes unless asked otherwise;
- the developer briefing says who must decide when the next step waits on another persona's decision;
- a hand-off: Gnomon not installed is said before anything is filed; the board shows a hand-off as the agent's card
  (waiting for acceptance, or in progress), never a person as a harness, and the briefing agrees with the board
  and counts hand-offs as agent sessions; an unknown change is said in words; the brief hands on open feedback only;
- Ask Rihma: "hand off T-002 to Claude Code" opens the hand-off with both chosen; "generate an automation ..." carries
  the words into Describe it; "help" and "what should I do next?" give the persona's own next steps and who else
  must act; "where do I see hand-offs?" goes to the Agents view;
- a rejected or deferred defect takes its which-requirement question with it;
- the trace says a scripted stand-in is scripted, and how a builder round ended.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from acc_fakes import STOCK, WEBHOOK, copy_home, demo_home, pid_of  # noqa: E402
from console_fakes import PERSON, git_repo  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_dogfood_fix import specced  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import agent_bridge as bridge  # noqa: E402
from kernel import assistant, devbrief, devtrace, handoff_chat  # noqa: E402
from kernel import console as kconsole  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.change import submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.store import Factory  # noqa: E402

DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DEV = {"person": "Dev Tester", "persona": "developer"}


class Served:
    """A cockpit on ``factory`` for one test, signed in."""

    def __init__(self, case: unittest.TestCase, factory: Factory) -> None:
        self.server, boot = make_server(factory, 0)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        case.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.token = self.call("POST", "/auth", {"bootstrap": boot}, auth=False)[1]["token"]

    def call(self, method: str, path: str, body: dict | None = None, *, auth: bool = True) -> tuple[int, dict]:
        headers = {"Origin": self.server.origin, "Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.server.origin + path, data=json.dumps(body).encode() if body is not None
                                     else None, headers=headers, method=method)
        try:
            with DIRECT.open(req, timeout=60) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"null")


# -- the Console on a relative home (the blocker) ---------------------------------------------------------

class RelativeHomeTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_FR_CON1_AC_2_a_relative_home_is_made_absolute_and_the_console_runs_in_its_working_copy(self):
        run_in = self.tmp / "checkout"
        run_in.mkdir()
        here = os.getcwd()
        os.chdir(run_in)
        self.addCleanup(os.chdir, here)
        factory = Factory(os.path.join("..", "rel", "home"))            # `--home ../rel/home`, as typed
        self.assertTrue(factory.home.is_absolute(), factory.home)
        self.assertEqual(factory.home, (self.tmp / "rel" / "home").resolve())
        p = factory.new_project("Stock levels", maturity="demo", mode="mixed")
        source = git_repo(self.tmp / "stock-src", {"app.py": "print('stock')\n"})
        subprocess.run(["git", "clone", "-q", "--bare", str(source), str(p.path("repo.git"))], check=True,
                       capture_output=True)
        out = kconsole.run(p, {"line": f'"{sys.executable}" -c "print(open(\'app.py\').read())"'}, person=PERSON,
                           persona="developer")
        self.assertEqual(out["state"], "done", Path(out["log"]).read_text(encoding="utf-8"))
        self.assertIn("stock", Path(out["log"]).read_text(encoding="utf-8"))

    def test_FR_CON1_AC_8_a_working_copy_that_cannot_be_made_is_a_409_with_one_plain_sentence(self):
        p = self.factory.new_project("Broken", maturity="demo", mode="mixed")
        p.path("repo.git").mkdir()                                       # there, but not a repository
        served = Served(self, self.factory)
        status, out = served.call("POST", f"/api/projects/{p.pid}/console/run",
                                  {"line": "git status", "person": PERSON, "persona": "developer"})
        self.assertEqual(status, 409, out)
        said = out["error"]
        self.assertTrue(said.startswith(f"The console could not copy {p.pid}'s repository to run in: "), said)
        for raw in ("git clone", "smudge", "fatal:", " -c "):
            self.assertNotIn(raw, said)
        self.assertTrue(said.endswith("."), said)
        self.assertFalse((self.tmp / "lanes" / "workspaces" / p.pid / "console").exists())


class DemoDefaultsTest(unittest.TestCase):
    def test_FR_N4_AC_1_a_demo_home_answers_from_the_map_and_keeps_its_own_lanes(self):
        from cockpit.server import demo_defaults
        tmp = Path(tempfile.mkdtemp(prefix="rihma-demo-defaults-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        demo, other = Factory(tmp / "demo"), Factory(tmp / "other")
        demo.home.mkdir(parents=True)
        other.home.mkdir(parents=True)
        (demo.home / "demo.json").write_text("{}", encoding="utf-8")
        env: dict[str, str] = {}
        choice, said = demo_defaults(demo, None, env)
        self.assertEqual((choice, env["GF_LANES"]), ("map", str(demo.home / "lanes")))
        self.assertEqual(len(said), 2)
        env = {"GF_LANES": "/elsewhere"}
        self.assertEqual(demo_defaults(demo, "gnomon", env)[0], "gnomon")          # asked otherwise: kept
        self.assertEqual(env["GF_LANES"], "/elsewhere")
        env = {}
        self.assertEqual(demo_defaults(other, None, env), (None, []))
        self.assertEqual(env, {})


# -- the demo home: the briefing, hand-offs, the brief, Ask Rihma, the trace --------------------------------------

class DemoCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        cls.factory = Factory(demo_home())
        cls.webhook = cls.factory.project(pid_of(cls.factory, WEBHOOK))

    def copied(self) -> Factory:
        tmp = Path(tempfile.mkdtemp(prefix="rihma-acc-copy-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        return Factory(copy_home(tmp))

    def ask(self, question: str, pid: str | None = None, persona: str = "developer") -> dict:
        return assistant.ask(self.factory, question, persona=persona, project_id=pid or self.webhook.pid,
                             view="board", person="Dev Tester")


class BriefingTest(DemoCase):
    def test_FR_DEV1_AC_3_a_decision_another_persona_makes_says_who_and_offers_a_nudge(self):
        b = devbrief.briefing(self.webhook, person="Dev Tester", persona="developer")
        step = b["next"]
        self.assertEqual(step["title"], "C-0002 waits on the Business owner or Product owner")
        self.assertEqual(step["waits_for"]["who"], ["business_owner", "product_owner"])
        self.assertEqual(step["action"]["control"], "nudge")
        self.assertIn("C-0002 waits on your decision as Business owner or Product owner", step["waits_for"]["nudge"])
        self.assertEqual([x["card"] for x in b["blocking"]], ["C-0002"])       # never "nothing waits on a decision"
        own = devbrief.briefing(self.webhook, person="Dev Tester", persona="product_owner")["next"]
        self.assertEqual((own["title"], own["action"]["control"]), ("Decide the change C-0002, then build it",
                                                                     "decide"))
        self.assertNotIn("waits_for", devbrief.briefing(self.webhook, persona="*")["next"])   # everything: theirs
        served = Served(self, self.factory)
        status, out = served.call("GET", f"/api/projects/{self.webhook.pid}/dev/briefing?persona=developer")
        self.assertEqual((status, out["next"]["title"]), (200, step["title"]))

    def test_FR_DEV1_AC_2_a_scripted_stand_in_is_said_scripted_and_a_round_says_how_it_ended(self):
        items = devtrace.trace(self.webhook, window="all")["items"]
        cells = [i for i in items if i["kind"] == "cell_ran"]
        self.assertTrue(cells)
        for i in cells:
            self.assertTrue(i["what"].startswith("The scripted builder (demo-builder) worked on"), i["what"])
            self.assertFalse(i["what"].endswith("result"), i["what"])
            self.assertIn(": finished", i["what"])
            self.assertEqual(i["who"]["harness"], "scripted")
        runs = [i for i in items if i["kind"] == "model_run"]
        self.assertTrue(runs)
        self.assertTrue(all("answered from a script" in i["what"] and "glm" not in i["what"] for i in runs))
        self.assertEqual({i["who"]["model"] for i in runs}, {"scripted"})


class HandoffTest(DemoCase):
    def test_FR_BRG1_AC_3_gnomon_absent_is_said_before_filing_and_the_board_shows_the_agents_card(self):
        factory = self.copied()
        stock = pid_of(factory, STOCK)
        served = Served(self, factory)
        with mock.patch.dict(os.environ, {"GNOMON_CMD": str(factory.home / "no-such-gnomon")}):
            status, out = served.call("GET", f"/api/projects/{stock}/handoff?to=generic")
            self.assertEqual(status, 200, out)
            self.assertFalse(out["run"]["available"])
            self.assertIn("Gnomon is not installed on this machine", out["run"]["why_not"])
            cards = len(Canon(factory.project(stock)).cards())
            status, out = served.call("POST", f"/api/projects/{stock}/handoff", {"to": "generic", "via": "run", **DEV})
            self.assertEqual(status, 409, out)
            self.assertIn("Gnomon is not installed", out["error"])
            self.assertEqual(len(Canon(factory.project(stock)).cards()), cards)          # nothing filed
            self.assertEqual(factory.project(stock).ledger().of_kind("agent_handoff"), [])
        with mock.patch.dict(os.environ, {"GNOMON_CMD": Path(sys.executable).as_posix()}):   # a Gnomon that is there
            status, out = served.call("POST", f"/api/projects/{stock}/handoff", {"to": "generic", "via": "run", **DEV})
        self.assertEqual(status, 201, out)
        filed = out["card"]
        self.assertEqual(out["message"]["text"], f"Handed to Gnomon's builder cell through {filed}: it waits for "
                                                 f"{filed} to be accepted before the cell runs it.")
        status, out = served.call("POST", f"/api/projects/{stock}/handoff", {"to": "claude-code", "via": "copy", **DEV})
        self.assertEqual((status, out["message"]["text"]), (201, "Handed off to Claude Code (brief copied)."))
        board = served.call("GET", f"/api/projects/{stock}/dev/board")[1]
        handed = {c["title"]: c for c in board["cards"] if c["kind"] == "handoff"}
        run, copied = handed["Handed to Gnomon's builder cell"], handed["Handed to Claude Code"]
        self.assertEqual((run["lane"], run["waits_on"]["card"]), ("planned", filed))
        self.assertIn(f"waits for {filed} to be accepted", run["why"])
        self.assertEqual((copied["lane"], copied["agents"][0]["harness"]), ("in_progress", "claude-code"))
        self.assertEqual(board["filters"]["harnesses"], ["claude-code", "gnomon"])     # harnesses only, no person
        brief = served.call("GET", f"/api/projects/{stock}/dev/briefing?persona=developer&person=Dev%20Tester")[1]
        self.assertTrue(brief["next"]["title"].startswith("Follow M-"), brief["next"])    # the board's In progress
        self.assertNotIn("Every task is merged", brief["next"]["title"])
        self.assertEqual(brief["by_harness"].get("claude-code"), 1)
        self.assertEqual(brief["by_harness"].get("gnomon"), 1)
        # deferred: the run's hand-off ends, and its card leaves the board
        Canon(factory.project(stock)).decide(filed, "defer", person="Pia", persona="product_owner", reason="later")
        board = served.call("GET", f"/api/projects/{stock}/dev/board")[1]
        self.assertEqual([c["title"] for c in board["cards"] if c["kind"] == "handoff"], ["Handed to Claude Code"])

    def test_FR_BRG1_AC_2_an_unknown_change_is_said_in_words_and_a_task_can_be_handed_on_its_own(self):
        served = Served(self, self.factory)
        status, out = served.call("GET", f"/api/projects/{self.webhook.pid}/handoff?change=C-9999")
        self.assertEqual(status, 400, out)
        self.assertEqual(out["error"], "No change C-9999 in this project: give the id of one of its change cards, "
                                       "or leave Change empty")
        status, out = served.call("GET", f"/api/projects/{self.webhook.pid}/handoff?change=T-002&to=claude-code")
        self.assertEqual(status, 200, out)
        self.assertIn("## The task T-002", out["markdown"])
        self.assertIn("The scope is this task alone", out["markdown"])

    def test_FR_BRG1_AC_1_the_brief_hands_on_open_feedback_only(self):
        md = bridge.render(bridge.brief(self.webhook))
        said = md[md.index("## Feedback to address"):md.index("## Insights")]
        for resolved in ("T-002 round", "T-002 escalated", "security gate said not measured"):
            self.assertNotIn(resolved, said)
        self.assertEqual(bridge.failed_gates(self.webhook), [])


class AskRihmaTest(DemoCase):
    def test_FR_CPL1_AC_4_hand_off_t002_to_claude_code_opens_the_hand_off_with_both_chosen(self):
        out = self.ask("hand off T-002 to Claude Code")
        self.assertEqual(out["navigate"]["handoff"], {"kind": "handoff", "to": "claude-code", "change": "T-002"})
        self.assertEqual(out["navigate"]["control"], "handoff")
        self.assertEqual([s["action"]["kind"] for s in out["plan"]["steps"]], ["handoff"])
        self.assertNotIn("Models setup", out["answer"])
        self.assertTrue(out["answer"].startswith("Hand off to an agent opens with T-002 and Claude Code chosen"))
        where = self.ask("Where do I see hand-offs to agents?")
        self.assertEqual(where["navigate"]["route"], f"#/p/{self.webhook.pid}/agents")
        self.assertIn("channel", where["answer"])
        self.assertIn("Trace", where["answer"])
        # a delegation of a persona's cards to an agent (people in the loop) is not a hand-off to a coding agent
        self.assertIsNone(handoff_chat.answer(self.webhook, "Delegate operations to the ops agent"))
        self.assertEqual(handoff_chat.answer(self.webhook, "delegate T-002 to Codex")["navigate"]["handoff"]["to"],
                         "codex")

    def test_FR_CPL1_AC_5_generate_an_automation_carries_the_words_into_describe_it(self):
        said = "Generate an automation that runs the tests every night"
        out = self.ask(said)
        first = out["plan"]["steps"][0]["action"]
        self.assertEqual((first["kind"], first["describe"], first["template"]), ("automation", said, "nightly_regate"))
        self.assertNotIn("draft_change", [s["action"]["kind"] for s in out["plan"]["steps"]])
        self.assertEqual(out["navigate"]["describe"], said)
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.webhook.pid}/automations")

    def test_FR_JRN1_AC_2_help_and_what_next_give_the_personas_own_steps_and_who_else_must_act(self):
        for question in ("help", "What should I do next?"):
            out = self.ask(question)
            text = out["answer"]
            self.assertTrue(text.startswith("As Developer on Shipment webhook to the stock system: you can decide "
                                            "C-0004"), text)
            self.assertIn("Who else must act: C-0002 and C-0003 wait on the Business owner or Product owner.", text)
            for not_said in ("Assistant is in the bottom right", "Start from a new idea", "decision(s)",
                             "Decide C-0002"):
                self.assertNotIn(not_said, text)
            self.assertEqual(out["sources"], [])                     # no link labelled with the raw project id
            self.assertEqual(out["navigate"]["route"], f"#/p/{self.webhook.pid}/inbox/C-0004")
        owner = self.ask("What should I do next?", persona="product_owner")["answer"]
        self.assertIn("you can decide C-0002", owner)


class FollowUpTest(FactoryTestCase):
    def test_FR_DF3_AC_1_a_deferred_defect_takes_its_which_requirement_question_with_it(self):
        p = specced(self)
        compile_project(p)
        card = submit(p, persona="end_user", person="Eeva", text="Something is wrong: the lost items report is empty")
        tri = triage(p, card["id"], model=None)
        asked = tri["needs_requirement"]["card"]
        canon = Canon(p)
        self.assertEqual(canon.get_card(asked)["state"], "open")
        canon.decide(card["id"], "defer", person="Pia", persona="product_owner", reason="next quarter")
        closed = canon.get_card(asked)
        self.assertEqual(closed["state"], "withdrawn")
        self.assertIn(f"its change {card['id']} was deferred", closed["closed"]["why"])
        self.assertNotIn(asked, [c["id"] for c in canon.cards(state="open")])
        rec = p.ledger().of_kind("card_closed")[-1]["event"]["payload"]
        self.assertEqual((rec["id"], rec["state"]), (asked, "withdrawn"))


if __name__ == "__main__":
    unittest.main()
