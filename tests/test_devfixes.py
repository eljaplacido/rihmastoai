"""What an independent check of the development board found, fixed (FR-DEV2), on the neutral fixture of
tests/test_devboard.py: Ask Rihma's development rules give way to the others outside a project and for broad
questions; Cursor's per-turn hooks keep one start and one end per session with whole-session counts; Got it is
called Got it; a window the trace does not take is refused saying what to give; a card-less decision names what it
answered. Skipped without git.
"""

import json
import shutil
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_devboard import DEV, commit, git, world  # noqa: E402

from kernel import assistant, devask, devboard, devsessions, devtrace  # noqa: E402
from kernel.cli import main  # noqa: E402

GIT = shutil.which("git")
BROAD = ["brief me", "what happened since yesterday?", "what did the agents do?", "who worked on this?",
         "who approved this release? who worked on the security review", "What did the agents do since yesterday?",
         "what's next in development?"]
IN_PROJECT = ["brief me", "what happened since yesterday?", "who worked on this?",
              "who approved this release? who worked on the security review"]


def gist(out: dict) -> tuple:
    return out.get("matches"), (out.get("navigate") or {}).get("route"), out["answer"]


@unittest.skipUnless(GIT, "git is needed for the repository")
class AskGivesWayTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = world(self)

    def both(self, question: str, persona: str, pid: str | None) -> tuple[tuple, tuple]:
        ask = lambda: gist(assistant.ask(self.factory, question, persona=persona, project_id=pid,  # noqa: E731
                                         person=DEV))
        now = ask()
        with mock.patch.object(assistant.dev_q, "answer", return_value=None):
            return now, ask()

    def test_FR_DEV2_AC_1_broad_questions_get_the_answers_they_had(self):
        for persona in ("business_owner", "compliance", "developer"):
            for question in BROAD:
                now, without = self.both(question, persona, None)
                self.assertEqual(now, without, (persona, question))
                self.assertNotIn("open a project, then ask again", now[2])
                if question != "what's next in development?":
                    self.assertFalse(str((now[0] or [""])[0]).startswith("dev_"), (persona, question, now))
        for persona in ("developer", "compliance"):
            for question in IN_PROJECT:
                now, without = self.both(question, persona, self.p.pid)
                self.assertEqual(now, without, (persona, question))
                self.assertFalse(str((now[0] or [""])[0]).startswith("dev_"), (persona, question, now))

    def test_FR_DEV2_AC_1_development_questions_in_a_project_still_answer_by_rule(self):
        for question, match, view in (("What's next in development?", "dev_next", "board"),
                                      ("what should I build next?", "dev_next", "board"),
                                      ("What did the agents do since yesterday?", "dev_agents", "trace")):
            matches, route, _ = gist(assistant.ask(self.factory, question, persona="developer",
                                                   project_id=self.p.pid, person=DEV))
            self.assertEqual((matches, route), ([match], f"#/p/{self.p.pid}/{view}"), question)
        self.assertIsNone(devask.answer(self.factory, None, "what did the agents do since yesterday?"))

    def test_FR_DEV2_AC_3_got_it_is_called_got_it_in_the_trace(self):
        devsessions.look(self.p, person=DEV, persona="developer")
        lines = [i["what"] for i in devtrace.trace(self.p)["items"] if i["kind"] == devsessions.LOOKED]
        self.assertEqual(lines, ["Read the development briefing (Got it)"])

    def test_FR_DEV2_AC_5_a_card_less_decision_names_what_it_answered(self):
        self.p.log("decision", {"id": "D-0007", "card": None, "kind": "question", "verdict": "answer",
                                "refs": {"question": "Q-002"}, "person": DEV, "persona": "developer"})
        self.p.log("decision", {"id": "D-0008", "card": None, "kind": "question", "verdict": "answer",
                                "person": DEV, "persona": "developer"})
        lines = [i["what"] for i in devtrace.trace(self.p, window="all")["items"] if i["kind"] == "decision"]
        self.assertIn("Decided Q-002 (question): answer", lines)
        self.assertIn("Decided D-0008 (question): answer", lines)
        self.assertFalse(any("None" in line for line in lines), lines)


@unittest.skipUnless(GIT, "git is needed for the session hooks")
class CursorTurnsTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.factory.new_project("Turns project")
        self.work = self.tmp / "repo"
        self.work.mkdir()
        git(self.work, "init", "-q", "-b", "work/t-005")
        commit(self.work, "a.txt", "start")

    def turn(self, event: str) -> dict:
        stdin = StringIO(json.dumps({"conversation_id": "conv-1", "workspace_roots": [str(self.work)]}))
        return devsessions.hook_main(["--harness", "cursor", "--event", event], stdin, home=str(self.factory.home),
                                     pid=self.p.pid, person=DEV, persona="developer")

    def test_FR_DEV2_AC_2_three_turns_are_one_session_with_whole_session_counts(self):
        first = self.turn("start")
        self.assertTrue(first["recorded"])
        for n in (1, 2, 3):
            if n > 1:
                again = self.turn("start")
                self.assertFalse(again["recorded"])
                self.assertEqual(again["session"]["id"], first["session"]["id"])     # the one start
                self.assertEqual([c["kind"] for c in devboard.board(self.p)["cards"]], ["session"])  # open again
            self.clock.advance(minutes=10)
            commit(self.work, f"t{n}.txt", f"T-005 turn {n}")
            end = self.turn("end")
            self.assertEqual(end["recorded"], n == 1, n)
            self.assertEqual((end["session"]["commits"], end["session"]["files_changed"]), (n, n), n)
            self.assertNotIn("resumed", end["session"])
            self.assertEqual([c["kind"] for c in devboard.board(self.p)["cards"]], [])  # ended: nothing open
        rows = devsessions.sessions(self.p)
        self.assertEqual([(s["id"], s["event"]) for s in rows], [("S-0001", "start"), ("S-0002", "end")])
        self.assertEqual(rows[1]["tasks"], ["T-005"])
        self.assertGreaterEqual(rows[1]["seconds"], 0)
        recs = [r["event"]["payload"]["event"] for r in self.p.ledger().of_kind(devsessions.KIND)]
        self.assertEqual(recs, ["start", "end"])
        lines = [i["what"] for i in devtrace.trace(self.p, window="all")["items"]
                 if i["kind"] == devsessions.KIND]
        self.assertIn("cursor session ended: 3 commits, 3 files changed on work/t-005", lines)

    def test_FR_DEV2_AC_2_a_claude_code_resume_continues_the_session(self):
        rec = dict(harness="claude-code", session="cc-1", person=DEV, persona="developer")
        devsessions.record(self.p, event="start", **rec)
        devsessions.record(self.p, event="end", commits=1, **rec)
        self.assertFalse(devsessions.record(self.p, event="start", **rec)["recorded"])
        self.assertEqual(len(devsessions.open_sessions(self.p)), 1)
        devsessions.record(self.p, event="end", commits=4, **rec)
        self.assertEqual([s.get("commits") for s in devsessions.sessions(self.p)], [None, 4])
        self.assertEqual(devsessions.open_sessions(self.p), [])


class WindowTest(FactoryTestCase):
    def test_FR_DEV2_AC_4_a_window_it_does_not_take_is_refused_saying_what_to_give(self):
        p = self.factory.new_project("Window project")
        p.log("merged", {"task": "T-001"})
        now = self.clock.now()
        for bad in ("bogus", "'<script>", "yesterday", "2026-13-40", "7 days"):
            with self.assertRaises(devtrace.WindowRefused, msg=bad) as caught:
                devtrace.trace(p, window=bad)
            self.assertIn("24h, 7d, 30d, all", str(caught.exception))
        self.assertEqual(devtrace.since_of("2026-11-25T09:00:00", now), "2026-11-25T09:00:00Z")
        self.assertEqual(devtrace.since_of("2026-11-25T11:00:00+02:00", now), "2026-11-25T09:00:00Z")
        self.assertEqual(devtrace.trace(p, window="2000-01-01")["total"], devtrace.trace(p)["total"])
        self.assertEqual(main(["--home", str(self.factory.home), "dev", "trace", p.pid, "--window", "bogus"]), 2)


class WindowRouteTest(CockpitTestCase):
    def test_FR_DEV2_AC_4_the_route_refuses_a_bad_window_with_400(self):
        p = self.factory.new_project("Window route")
        base = f"/api/projects/{p.pid}/dev/trace"
        for bad in ("bogus", "%27%3Cscript"):
            status, out, _ = self.call("GET", f"{base}?window={bad}")
            self.assertEqual(status, 400, out)
            self.assertIn("2026-11-25T09:00:00Z", json.dumps(out))
        status, out, _ = self.call("GET", f"{base}?window=24h")
        self.assertEqual((status, out["window"]), (200, "24h"))


if __name__ == "__main__":
    unittest.main()
