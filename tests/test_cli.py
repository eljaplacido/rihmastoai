"""The command line's chain after its refactor into small handlers selected by a table (FR-N2).

The chain's commands print what they printed before, through `main(argv)`, against a temporary factory
home and the scripted model. A refused or failing chain command still raises, as before: only the
capability layer's commands (tests/test_cli_capability.py) turn a refusal into a message and exit 2.
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

from kernel.canon import DecisionRefused  # noqa: E402
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

    def test_a_refused_or_failing_chain_command_raises_as_it_did_before_the_table(self):
        home = str(self.factory.home)
        p = self.new(mode="assume")
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyError):
                main(["--home", home, "status", "no-such-project"])
            with self.assertRaises(FileNotFoundError):
                main(["--home", home, "deliver", p.pid])                         # nothing compiled yet
            with self.assertRaises(KeyError):
                main(["--home", home, "decide", p.pid, "C-0099", "accept", "--person", "Aino",
                      "--persona", "business_owner"])
        self.cli("intake", p.pid, "--source", IDEA, "--requested-by", "Aino")
        with self.assertRaises(DecisionRefused), contextlib.redirect_stdout(io.StringIO()):
            main(["--home", home, "assume", p.pid, "Q-001", "--person", "Aino", "--persona", "business_owner"])

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
