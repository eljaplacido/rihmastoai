"""FR-X1-AC-1 from the cockpit: New project can start from an existing project (a local git folder or a
git address); the cockpit checks the source at once and adopts it as a job, signed by the person."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cockpit import CockpitTestCase  # noqa: E402

from kernel.source_guard import ROOTS_ENV  # noqa: E402


class AdoptFromCockpitTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        # the cockpit reads local folders only under the home or a configured root (kernel/source_guard.py)
        patcher = mock.patch.dict(os.environ, {ROOTS_ENV: str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def repo(self) -> Path:
        path = self.tmp / "existing-app"
        (path / "app").mkdir(parents=True)
        (path / "README.md").write_text("# Order tracker\n\nA small web service.\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "add", "-A"], cwd=path, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x"],
                       cwd=path, check=True)
        return path

    def test_FR_X1_AC_1_new_project_adopts_an_existing_folder_as_a_signed_job(self):
        source = self.repo()
        status, body, _ = self.call("POST", "/api/adopt", {
            "title": "Order tracker", "source": str(source), "intent": "maintain", "maturity": "production",
            "base_url": "https://orders.example.com", "person": "Aino", "persona": "developer"})
        self.assertEqual(status, 201, body)
        job_id, args, _ = self.runner.started[-1]
        self.assertEqual(body["job"]["id"], job_id)
        self.assertEqual(args[:5], ["-m", "kernel.cli", "adopt", "Order tracker", "--source"])
        for flag, value in (("--intent", "maintain"), ("--person", "Aino"), ("--persona", "developer"),
                            ("--maturity", "production"), ("--base-url", "https://orders.example.com")):
            self.assertEqual(args[args.index(flag) + 1], value, flag)

    def test_FR_X1_AC_1_a_source_with_nothing_to_adopt_is_refused_at_once(self):
        folder = self.tmp / "not-a-repo"         # any folder is adopted now (FR-MAT1), but one with no code is not
        folder.mkdir()
        (folder / "notes.md").write_text("# Notes\n", encoding="utf-8")
        for source, why in ((str(folder), "holds no code"), (str(self.tmp / "missing"), "not a directory"),
                            ("https://user:secret@example.com/r.git", "credential")):
            with self.subTest(source=source):
                status, body, _ = self.call("POST", "/api/adopt", {"title": "X", "source": source, "intent": "improve",
                                                                   "person": "Aino", "persona": "developer"})
                self.assertEqual(status, 400, body)
                self.assertIn(why, body["error"])
        status, body, _ = self.call("POST", "/api/adopt", {"title": "X", "source": str(self.repo()), "intent": "rewrite",
                                                           "person": "Aino", "persona": "developer"})
        self.assertEqual(status, 400, body)
        self.assertEqual(self.runner.started, [])
