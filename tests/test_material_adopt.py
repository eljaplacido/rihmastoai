"""FR-MAT1-AC-8: "An existing project" accepts any folder (kernel/material_adopt.py, kernel/adopt.py).

A git repository is adopted as before, and its documents are scanned as context. A folder that is not one is
snapshotted into a new repository under the factory home, with only the files that pass the scan's rules
(no secrets, nothing excluded), committed as the baseline, and adopted from there; the person's folder is never
changed. A folder with no code is refused, as material for a new project. The folders are built in the test.
"""

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import material_fixture as mf  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402

from kernel.adopt import AdoptionRefused, adopt  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.material_adopt import BASELINE  # noqa: E402

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def tree(root: Path) -> dict:
    """Every file under ``root`` with its sha256: what "never changed" is checked against."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def tracked(repo: str) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


class AnyFolderAdoptTest(FactoryTestCase):
    def test_FR_MAT1_AC_8_a_folder_that_is_not_a_repository_is_snapshotted_and_adopted_unchanged(self):
        folder = mf.build(self.tmp / "lobby")
        before = tree(folder)
        p = adopt(self.factory, "Visitor register", source=str(folder), intent="maintain", person="Aino",
                  persona="developer", which=lambda name: None, exclude=("data/*",), suite_timeout=120)
        self.assertEqual(tree(folder), before)                                  # the folder itself never changes
        self.assertFalse((folder / ".git").exists())
        adopted = p.read("adopted.json")
        snap = adopted["snapshot"]
        self.assertEqual(adopted["source"], folder.resolve().as_posix())
        self.assertEqual(adopted["source_kind"], "folder")
        self.assertTrue(Path(snap["repository"]).is_relative_to(self.factory.home.resolve() / "snapshots"))
        files = tracked(snap["repository"])
        for gone in (".env", "id_rsa", "config/credentials.yaml", "notes/handy.txt", "src/cloud.py",
                     "data/budget.xlsx", "data/visitors.csv"):
            self.assertNotIn(gone, files)                     # secret-looking and excluded files never copied
        for kept in ("README.md", "src/app.py", "tests/test_app.py", "brief.docx", "assets/logo.png", "Dockerfile"):
            self.assertIn(kept, files)
        self.assertEqual(snap["copied"], len(files))
        self.assertEqual((snap["secrets"], snap["excluded"]), (5, 3))
        log = subprocess.run(["git", "log", "--format=%s"], cwd=snap["repository"], capture_output=True, text=True,
                             check=True).stdout.strip()
        self.assertEqual(log, BASELINE.format(folder=folder.resolve().as_posix()))
        self.assertEqual(adopted["baseline"], snap["revision"])
        # its documents, scanned as context: kept in the project, counted in the ledger, nothing sent
        mp = p.read("material.json")
        self.assertIn("README.md", [o["path"] for o in mp["order"]])
        self.assertIn("nothing was sent to a model", mp["for"])
        self.assertTrue(p.path("material.md").read_text(encoding="utf-8").startswith("## README.md (brief or spec)"))
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        self.assertIn("snapshot_taken", kinds)
        scanned = p.ledger().of_kind("material_scanned")[-1]["event"]["payload"]
        self.assertEqual((scanned["person"], scanned["confirmed"]), ("Aino", "adopted: scanned, not sent"))
        ledger = p.path("ledger.jsonl").read_text(encoding="utf-8")
        for secret in (mf.TOKEN, mf.AWS_KEY):
            self.assertNotIn(secret, ledger + p.path("material.md").read_text(encoding="utf-8"))
        self.assertEqual(p.meta["stage"], 5)
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_MAT1_AC_8_a_folder_of_documents_only_is_refused_as_material_for_a_new_project(self):
        folder = self.tmp / "papers"
        folder.mkdir()
        (folder / "brief.md").write_text("# Brief\n\nA register of visitors.\n", encoding="utf-8")
        mf.docx(folder / "plan.docx", [("Heading1", "Plan")])
        with self.assertRaisesRegex(AdoptionRefused, "holds no code, only documents: there is nothing to adopt. "
                                                     "Start a new project from it instead"):
            adopt(self.factory, "Papers", source=str(folder), intent="improve", person="Aino", persona="developer")
        self.assertEqual(self.factory.projects(), [])
        self.assertEqual(list((self.factory.home / "snapshots").glob("*")) if (self.factory.home / "snapshots").exists()
                         else [], [])

    def test_FR_MAT1_AC_8_a_git_repository_is_adopted_as_before_with_its_documents_scanned(self):
        repo = self.tmp / "app"
        (repo / "docs").mkdir(parents=True)
        (repo / "README.md").write_text("# Orders\n\nA small order service.\n", encoding="utf-8")
        (repo / "docs" / "decisions.md").write_text("# Decisions\n\nDecision: one database.\n", encoding="utf-8")
        (repo / "app.py").write_text("print('orders')\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run([*GIT, "commit", "-q", "-m", "x"], cwd=repo, check=True)
        p = adopt(self.factory, "Orders", source=str(repo), intent="maintain", person="Aino", persona="developer",
                  which=lambda name: None, confidential=True)
        adopted = p.read("adopted.json")
        self.assertNotIn("snapshot", adopted)
        self.assertEqual(adopted["source_kind"], "path")
        order = [o["path"] for o in p.read("material.json")["order"]]
        self.assertEqual(order, ["README.md", "code inventory", "docs/decisions.md"])
        self.assertTrue(p.meta["confidential"])                          # recorded, and held to local models
        self.assertEqual(p.ledger().of_kind("confidential_set")[-1]["event"]["payload"]["person"], "Aino")
        # from the command line: the snapshot, the documents and the setting are said
        folder = mf.build(self.tmp / "lobby", secrets=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch("kernel.adopt.SUITE_TIMEOUT", 120):
            code = main(["--home", str(self.factory.home), "adopt", "Lobby", "--source", str(folder), "--intent",
                         "improve", "--person", "Aino", "--persona", "developer", "--exclude", "slides/*",
                         "--confidential"])
        self.assertEqual(code, 0)
        said = json.loads(out.getvalue())
        self.assertEqual(said["snapshot"]["excluded"], 2)
        self.assertGreater(said["documents"]["read"], 3)
        self.assertTrue(said["confidential"])


if __name__ == "__main__":
    unittest.main()
