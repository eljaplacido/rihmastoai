"""The command line's chain after its refactor into small handlers selected by a table (FR-N2).

The chain's commands print what they printed before, through `main(argv)`, against a temporary factory
home and the scripted model. A refused chain command, a mistyped id or verdict included, is one line on stderr
and exit 2, as the capability layer's commands are (tests/test_cli_capability.py).
`doctor`, `demo`, `adopt` and `sync` have their own tests (test_doctor, test_demo, test_adopt)."""

import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel.cli import command_of, main  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class ChainCliTest(FactoryTestCase):
    def cli(self, *argv: str):
        out = io.StringIO()
        with mock.patch("kernel.cli._model", model), contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), *argv])
        self.assertEqual(code, 0, argv)
        return json.loads(out.getvalue())

    def test_new_answer_assume_status_spec_and_compile_through_the_table(self):
        out = self.cli("new", "Equipment loans", "--source", IDEA, "--mode", "socratic", "--requested-by", "Aino")
        pid = out["project"]
        self.assertEqual((out["questions"], len(out["asked"]), out["assumed"]), (7, 7, []))
        self.assertNotIn("readings", out)
        ran = self.cli("run", pid)                                               # stops where a person is needed
        self.assertEqual((ran["state"], ran["waiting_on"], ran["why"]),
                         ("waiting", ["C-0001"], "blocking questions are open"))
        row = self.cli("status", pid)["projects"][0]
        self.assertEqual((row["stage"], row["questions"]["open"], row["ledger_intact"]), ("2 concept", 7, True))
        answered = self.cli("answer", pid, "Q-001", "the team lead approves", "--person", "Aino",
                            "--persona", "business_owner")
        self.assertEqual((answered["id"], answered["status"]), ("Q-001", "answered"))
        brief = self.factory.project(pid).path("canon", "brief.md").read_text(encoding="utf-8")
        self.assertIn("**the team lead approves**", brief)                      # the brief is rendered again
        assumed = self.cli("assume", pid, "Q-002", "--person", "Aino", "--persona", "business_owner")
        self.assertEqual((assumed["question"], assumed["text"]), ("Q-002", "fewer lost items per month"))
        self.assertEqual(self.cli("spec", pid), {"requirements": 4})
        compiled = self.cli("compile", pid)
        self.assertEqual(compiled["counts"], {"requirements": 4, "criteria": 6, "tasks": 4})
        self.assertEqual(compiled["holdouts"], ["R-1-AC-2", "R-4-AC-2"])
        self.assertTrue(compiled["revision"].startswith("sha256:"))
        self.assertEqual(self.cli("status")["projects"][0]["stage"], "5 build and verify")

    def test_intake_change_decide_apply_and_the_operator_commands_through_the_table(self):
        pid = self.cli("new", "Equipment loans", "--source", IDEA, "--mode", "assume", "--maturity", "explore",
                       "--requested-by", "Aino")["project"]
        more = self.tmp / "more.md"
        more.write_text("Also track who returned an item late.\n", encoding="utf-8", newline="\n")
        again = self.cli("intake", pid, "--source-file", str(more), "--requested-by", "Aino")
        self.assertEqual((again["kind"], "readings" in again), ("idea", False))
        self.cli("spec", pid)
        self.cli("compile", pid)
        changed = self.cli("change", pid, "Adding an item with an empty name crashes", "--person", "Tester",
                           "--persona", "end_user")
        self.assertEqual(changed["triage"]["class"], "defect")
        decided = self.cli("decide", pid, changed["card"], "accept", "--person", "Aino", "--persona", "business_owner",
                           "--reason", "a crash")
        self.assertEqual((decided["verdict"], decided["person"], decided["reason"]), ("accept", "Aino", "a crash"))
        applied = self.cli("apply", pid, changed["card"])
        self.assertEqual((applied["class"], applied["changed"]), ("defect", ["R-1"]))
        self.assertIn("revision", self.cli("resurface", pid, "--reason", "a test"))
        self.assertEqual(self.cli("operate", pid)["probes"][0]["verdict"], "not applicable")
        self.assertEqual(self.cli("workspace", "list", pid), {"workspaces": []})
        self.assertEqual(set(self.cli("learn")),
                         {"added_default_checks", "proposals_opened", "immune_memory", "model_reliability"})

    def refused(self, *argv: str) -> str:
        """A chain command that is refused: exit 2 and one line on stderr, never a traceback."""
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        self.assertEqual(code, 2, argv)
        line = err.getvalue().strip().splitlines()[-1]
        self.assertNotIn("Traceback", err.getvalue())
        return line

    def test_a_mistyped_id_or_verdict_is_one_line_on_stderr_and_exit_2(self):
        p = self.new(mode="assume")
        sign = ("--person", "Aino", "--persona", "business_owner")
        line = self.refused("status", "nope")
        self.assertIn("no project 'nope'", line)
        self.assertIn(f"the projects are {p.pid}", line)                         # the ids there are
        self.assertIn("no project 'nope'", self.refused("answer", "nope", "Q-1", "x", *sign))
        self.assertTrue(self.refused("deliver", p.pid))                          # nothing compiled yet
        line = self.refused("decide", p.pid, "C-0099", "accept", *sign)
        self.assertIn("no card C-0099", line)
        self.cli("intake", p.pid, "--source", IDEA, "--requested-by", "Aino")
        self.assertIn("is assumed, not open", self.refused("assume", p.pid, "Q-001", *sign))
        qpid = self.cli("new", "Equipment loans", "--source", IDEA, "--mode", "socratic",
                        "--requested-by", "Aino")["project"]
        line = self.refused("answer", qpid, "Q-099", "x", *sign)
        self.assertIn("no question Q-099", line)
        self.assertIn("Q-001 (card C-0001)", line)                                # what to use instead
        line = self.refused("decide", qpid, "C-0001", "maybe", *sign)
        self.assertIn("not 'maybe'", line)
        self.assertIn("answer", line)                                             # the verdicts it takes

    def test_status_names_each_open_question_and_answer_takes_its_card_id(self):
        pid = self.cli("new", "Equipment loans", "--source", IDEA, "--mode", "socratic",
                       "--requested-by", "Aino")["project"]
        row = self.cli("status", pid)["projects"][0]
        card = next(c for c in row["open_cards"] if c["kind"] == "question")
        self.assertRegex(card["question"], r"^Q-\d+$")
        self.assertIn({"id": card["question"], "card": card["id"]},
                      [{k: q[k] for k in ("id", "card")} for q in row["open_questions"]])
        answered = self.cli("answer", pid, card["id"], "The team lead approves", "--person", "Tester",
                            "--persona", "business_owner")
        self.assertEqual((answered["id"], answered["status"]), (card["question"], "answered"))
        other = self.cli("status", pid)["projects"][0]["open_cards"]
        card = next(c for c in other if c["kind"] == "question")
        assumed = self.cli("assume", pid, card["id"], "--person", "Tester", "--persona", "business_owner")
        self.assertEqual(assumed["question"], card["question"])

    def test_a_command_line_names_its_table_key(self):
        import argparse

        self.assertEqual(command_of(argparse.Namespace(cmd="status", pid=None)), "status")
        self.assertEqual(command_of(argparse.Namespace(cmd="workspace", sub="list", pid="x")), "workspace list")


class ModuleEntryTest(unittest.TestCase):
    def test_python_m_kernel_cli_runs_the_same_main(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            run = subprocess.run([sys.executable, "-m", "kernel.cli", "--home", tmp, "status"], cwd=REPO,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual((run.returncode, json.loads(run.stdout)), (0, {"projects": []}), run.stderr)
            run = subprocess.run([sys.executable, "-m", "kernel.cli", "--help"], cwd=REPO, capture_output=True,
                                 text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        for name in ("security", "pack", "evidence", "embed", "autonomy", "signal", "concept", "observe", "updates",
                     "square", "catalogue", "workspace", "adopt", "doctor", "demo"):
            self.assertIn(name, run.stdout)


if __name__ == "__main__":
    unittest.main()
