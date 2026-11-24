"""The assessment says only what it measured (FR-BA1, kernel/assess.py).

A rule passes on what shows its claim, never on a word in passing or a comment; the record names the
model that answered each perspective of the panel; and the reader of the mirror's objects is closed
whether the read finishes or fails. Each test fails without the change it names.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import test_assess as base  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import assess, assess_repo  # noqa: E402
from kernel.canon import PERSPECTIVES as PANEL  # noqa: E402
from kernel.model import FakeModel  # noqa: E402

WORDS_ONLY = {
    "app.py": 'CONFIG = {"db": "postgres://db.internal/orders"}\n'
              'settings = {"audit": None}\n'
              "\n\n"
              "def db():\n"
              '    # one day: os.environ["DB"], and an audit_log of who asked\n'
              '    return CONFIG.get("db")\n'
              "\n\n"
              "config = CONFIG\n"
              'print(config.get("db"))\n',
    "users.sql": "create table users (email text);\n",
    "README.md": "# Orders\n\nThis app has no privacy story at all, and no data retention.\n"}
SHOWN = {
    "app.py": "import os\n"
              'DB = os.environ["DB"]  # from the environment\n'
              "audit_log = []\n",
    "users.sql": "create table users (email text);\n",
    "README.md": "# Orders\n\n## Personal data\n\nEmails are kept for 30 days and read by support only.\n"}


def plain_repo(dest: Path, files: dict) -> Path:
    base.write(dest, files)
    base.git(dest, "init", "-q", "-b", "main")
    base.git(dest, "add", "-A")
    base.git(dest, *base.ID, "commit", "-q", "-m", "initial")
    return dest


class WordsTest(FactoryTestCase):
    def assessed(self, name: str, files: dict) -> dict:
        project = base.mirrored(self.factory, name, plain_repo(self.tmp / name, files))
        return base.by_key(assess.assess(project, person="Aino", persona="developer", which=base.no_scanner))

    def test_FR_BA1_AC_15_a_rule_passes_only_on_what_shows_its_claim_never_on_a_word_in_passing_or_a_comment(self):
        words = self.assessed("words", WORDS_ONLY)
        config = words["architecture.config"]
        self.assertEqual(config["verdict"], "failed", config)            # config.get( and a comment read nothing
        self.assertEqual(config["severity"], "medium")
        audit = words["compliance.audit_trail"]
        self.assertEqual(audit["verdict"], "not measured", audit)        # "audit" as a word, and a comment
        self.assertEqual(audit["evidence"], [])
        personal = words["compliance.personal_data"]
        self.assertEqual(personal["verdict"], "failed", personal)        # a README that mentions privacy in passing
        self.assertEqual([(e["file"], e["line"]) for e in personal["evidence"]], [("users.sql", 1)])

        shown = self.assessed("shown", SHOWN)
        config = shown["architecture.config"]
        self.assertEqual((config["verdict"], [(e["file"], e["line"]) for e in config["evidence"]]),
                         ("passed", [("app.py", 2)]))                    # a comment after the read keeps it
        audit = shown["compliance.audit_trail"]
        self.assertEqual((audit["verdict"], [(e["file"], e["line"]) for e in audit["evidence"]]),
                         ("passed", [("app.py", 3)]))
        personal = shown["compliance.personal_data"]
        self.assertEqual(personal["verdict"], "passed", personal)
        self.assertIn({"file": "README.md", "line": 3, "text": "## Personal data"}, personal["evidence"])
        self.assertIn("not checked by rule", personal["summary"])


class RecordedModel(FakeModel):
    """A scripted model that, as a Gnomon run does, records which model answered, for one perspective."""

    def ask(self, prompt: str, *, role: str) -> str:
        self.last_record = {"final_model": "scripted-analyst-1"} if "You are the **business**" in prompt else None
        return super().ask(prompt, role=role)


class ModelNamedTest(FactoryTestCase):
    def test_FR_BA1_AC_16_the_record_names_the_model_that_answered_each_perspective_or_says_it_was_not_recorded(self):
        project = base.mirrored(self.factory, "Orders", base.fixture_repo("poor", self.tmp / "src"))
        model = RecordedModel(lambda prompt, role: '```json\n{"findings": []}\n```')
        record = assess.assess(project, person="Aino", persona="developer", model=model, which=base.no_scanner)
        want = {p: "scripted-analyst-1" if p == "business" else "not recorded" for p in PANEL}
        self.assertEqual(record["panel"]["models"], want)
        self.assertEqual(record["trace"]["delegated_to"]["models"], want)


class ReaderClosedTest(FactoryTestCase):
    def test_FR_BA1_AC_17_the_reader_of_the_mirror_s_objects_is_closed_after_a_read_and_after_a_failure(self):
        project = base.mirrored(self.factory, "Orders", base.fixture_repo("poor", self.tmp / "src"))
        bare = project.path("repo.git")
        opened: list = []

        class Counted(assess_repo._Blobs):
            def __init__(self, where: Path) -> None:
                super().__init__(where)
                opened.append(self)

        def reap() -> None:                     # without the fix, cat-file would wait on its input for ever
            for blobs in opened:
                if blobs.proc.poll() is None:
                    blobs.proc.kill()
                    blobs.proc.wait()
                for pipe in (blobs.proc.stdin, blobs.proc.stdout):
                    if pipe is not None and not pipe.closed:
                        pipe.close()
        self.addCleanup(reap)

        with mock.patch.object(assess_repo, "_Blobs", Counted):
            assess_repo.snapshot(bare, "main", self.tmp / "read")
            with mock.patch.object(assess_repo, "_tree", side_effect=RuntimeError("git ls-tree failed")), \
                    self.assertRaises(RuntimeError):
                assess_repo.snapshot(bare, "main", self.tmp / "failed")
        self.assertEqual(len(opened), 2)
        for blobs in opened:
            self.assertIsNotNone(blobs.proc.poll(), "cat-file is still running")
            self.assertTrue(blobs.proc.stdout.closed)


if __name__ == "__main__":
    unittest.main()
