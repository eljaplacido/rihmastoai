"""Ask Rihma's how-to answers are practical, and an Inbox card says what it asks (FR-UXO1).

The owner (2026-11-25): how-to answers like "via `rihmasto ide <pid>`" or "the snapshot does not show ..." are of no
use. Each how-to question below, asked on a fixture project, must come back with numbered steps for that project:
the action that opens the place (Take me there), and commands with the project's id and the person's name filled
in. The test fails on any placeholder ("<pid>", "<your name>", any "<word>"), on "the snapshot does not show", and
on a how-to answer with no action to take.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_assistant import Seeded  # noqa: E402

from kernel.assistant import ask  # noqa: E402
from kernel.assistant_howto import ANY_PLACEHOLDER, named_project, practical  # noqa: E402
from kernel.card_words import plain  # noqa: E402

PERSON = "Aino Virtanen"
HOWTO = [
    "How do I work on this from my IDE?",
    "How do I decide a card?",
    "How do I export the evidence?",
    "How do I report a change?",
    "How do I answer a question?",
    "How do I run a command in the workspace?",
    "How do I build the capability pack?",
    "How do I start the autopilot?",
    "How do I pause this project?",
    "How do I see the health checks?",
]


def everything_said(out: dict) -> str:
    parts = [str(out.get("answer") or "")]
    for s in out.get("steps") or []:
        parts.append(str(s.get("text") or ""))
        parts += [str(c) for c in s.get("commands") or []]
    for s in (out.get("plan") or {}).get("steps") or []:   # a goal's plan: each step one click (kernel/copilot.py)
        parts += [str(s.get("title") or ""), str(s.get("detail") or ""), str((s.get("action") or {}).get("command") or "")]
    return "\n".join(parts)


class HowToTest(Seeded):
    def answer(self, q: str, persona: str = "developer", person: str = PERSON) -> dict:
        out = ask(self.factory, q, persona=persona, project_id=self.p.pid)
        return practical(out, q, project=self.p, person=person, persona=persona)

    def plan_actions(self, q: str, out: dict) -> bool:
        """A goal's plan (kernel/copilot.py): its steps are the actions; whether one has a filled-in command."""
        acts = [s for s in out["plan"]["steps"] if s.get("available") and s.get("action")]
        self.assertTrue(acts, f"no action in the plan for {q!r}")
        return any(self.p.pid in str(s["action"].get("command") or "") for s in acts)

    def steps_and_commands(self, q: str, out: dict) -> bool:
        """The numbered steps: the first opens the place in this project; every command is filled in."""
        nav = out.get("navigate") or {}
        self.assertTrue(nav.get("route") or nav.get("control"), f"no action for {q!r}")
        steps = out.get("steps") or []
        self.assertTrue(steps, f"no steps for {q!r}")
        self.assertEqual(steps[0].get("action"), "navigate")
        self.assertIn(self.p.meta["title"], steps[0]["text"])
        commands = [c for s in steps for c in s.get("commands") or []]
        for c in commands:
            self.assertIn(self.p.pid, c)
            if "--person" in c:
                self.assertIn(f'--person "{PERSON}" --persona developer', c)
        return bool(commands)

    def test_FR_UXO1_AC_5_every_how_to_answer_gives_steps_with_filled_commands_and_an_action(self):
        with_commands = 0
        for q in HOWTO:
            with self.subTest(question=q):
                out = self.answer(q)
                said = everything_said(out)
                self.assertIsNone(ANY_PLACEHOLDER.search(said), f"a placeholder in the answer to {q!r}: {said}")
                self.assertNotRegex(said.lower(), r"snapshot (does not|doesn't) show")
                with_commands += self.plan_actions(q, out) if out.get("plan") else self.steps_and_commands(q, out)
        self.assertGreaterEqual(with_commands, 7)        # most how-tos have a terminal way too, filled in

    def test_FR_UXO1_AC_5_without_a_name_no_signed_command_is_shown_with_a_placeholder(self):
        out = self.answer("How do I report a change?", person="")
        said = everything_said(out)
        self.assertIsNone(ANY_PLACEHOLDER.search(said))
        self.assertNotIn("--person", said)
        self.assertIn("person chip", said)

    def test_FR_UXO1_AC_5_a_snapshot_sentence_becomes_where_to_look(self):
        out = practical({"answer": "The snapshot does not show the releases. Ask again later.", "navigate": None,
                         "matches": ["releases"]}, "where are the releases", project=self.p, person=PERSON, persona="it")
        self.assertNotIn("snapshot", out["answer"].lower())
        self.assertIn("Look in", out["answer"])

    def test_FR_UXO1_AC_4_a_question_naming_another_project_switches_to_it(self):
        other = self.factory.new_project("Room bookings", mode="assume", maturity="demo")
        self.assertEqual(named_project(self.factory, "How is Room bookings doing?", self.p.pid).pid, other.pid)
        self.assertIsNone(named_project(self.factory, "How is this doing?", self.p.pid))
        self.assertIsNone(named_project(self.factory, "How is Room bookings doing?", other.pid))

    def test_FR_UXO1_AC_2_an_inbox_card_says_in_one_plain_line_what_it_asks_and_its_choices(self):
        line = plain(dict(self.escalation, verdicts=["retry", "accept_as_is", "stop"]), self.p)
        task = next(t for t in self.p.read("contract.json")["tasks"] if t["id"] == "T-002")
        self.assertRegex(line, "^" + re.escape(f"The task '{task['title']}' failed its checks ") + r"\d+ times?: ")
        self.assertTrue(line.endswith("retry it, accept it as it is or stop it"), line)
        self.assertNotRegex(line, re.escape("T-002 did not pass"))


if __name__ == "__main__":
    unittest.main()
