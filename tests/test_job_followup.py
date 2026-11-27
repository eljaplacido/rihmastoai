"""A failed job always says why and what to do, and Ask Rihma answers from its log (FR-PRG1); a private
GitHub repository is read with the person's signed-in GitHub CLI, for github.com only (FR-RPJ1)."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel import adopt, job_words  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.store import Factory  # noqa: E402

FAILED = ("adopt: fetching the code\nTraceback (most recent call last):\n  File \"x\", line 1\n"
          "RuntimeError: git fetch failed: fatal: could not read Username for 'https://github.com': "
          "terminal prompts disabled\n")


class JobFollowUpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-job-"))
        self.factory = Factory(self.tmp / "home")
        (self.tmp / "home" / "jobs").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)       # the temp home and its jobs
        self.factory = None

    def test_FR_PRG1_AC_1_a_failed_job_says_why_and_what_to_do_and_ask_rihma_answers_from_its_log(self):
        log = self.tmp / "home" / "jobs" / "20261125T155711Z-adopt-_factory-7c25.log"
        log.write_text(FAILED, encoding="utf-8")
        why = job_words.reason(log)
        self.assertIn("could not read Username", why)
        self.assertIn("gh auth login", job_words.next_step(why))
        job = {"kind": "adopt", "project": "_factory",
               "args": ["-m", "kernel.cli", "adopt", "https://github.com/someone/orders-service"]}
        self.assertEqual(job_words.title(job), "Adopt orders-service")
        for q in ("why run failed", "what went wrong?", "why did the adoption fail"):
            self.assertTrue(job_words.asks_about_failure(q), q)
        self.assertFalse(job_words.asks_about_failure("how is the project going?"))
        out = ask(self.factory, "why run failed", persona="business_owner")
        self.assertEqual(out["by"], "rule")
        self.assertIn("could not read Username", out["answer"])
        self.assertEqual(out["navigate"]["route"], "#/jobs")

    def test_FR_RPJ1_AC_1_a_github_address_is_read_with_the_signed_in_cli_and_no_other_host_is(self):
        with mock.patch.object(adopt.shutil, "which", return_value="gh"):
            got = adopt._github_sign_in(self.tmp, ("ls-remote", "https://github.com/someone/private", "HEAD"))
            self.assertEqual(got, ["-c", "credential.https://github.com.helper=!gh auth git-credential"])
            self.assertEqual(adopt._github_sign_in(self.tmp, ("ls-remote", "https://example.com/x.git")), [])
        with mock.patch.object(adopt.shutil, "which", return_value=None):
            self.assertEqual(adopt._github_sign_in(self.tmp, ("ls-remote", "https://github.com/a/b")), [])
        self.assertIn("gh auth login", adopt._sign_in_hint("fatal: could not read Username for 'https://github.com'"))


if __name__ == "__main__":
    unittest.main()
