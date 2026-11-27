"""FR-WIP1: a project's work in progress, read from its own working copy, through the real cockpit server on a temp
factory (tests/test_cockpit.py CockpitTestCase), the command line and Ask Rihma. No model is asked.

The working copy is invented: a small rules service with a committed history, pushed to a remote of its own and one
commit ahead of it, then changed without committing: files modified, added (staged), deleted, renamed, untracked, and a
build folder full of untracked output. File times are set, never contents read.
"""

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from alignment_fixture import git, write  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import start_here, wip  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.cli import main  # noqa: E402

DAY = 86400


def digest(folder: Path) -> dict[str, str]:
    """Every file under a folder (its .git included) by its bytes: the reading must leave all of it as it was."""
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def working_copy(root: Path, *, pile: int = 60, old: bool = False) -> Path:
    """The working copy: committed, pushed, one commit ahead, then changed without committing."""
    remote = root / "remote.git"
    repo = root / "rules-service"
    repo.mkdir(parents=True)
    git(root, "init", "-q", "--bare", "-b", "main", str(remote))
    git(repo, "init", "-q", "-b", "main")
    write(repo, {"src/rules.py": "LIMIT = 30\n", "src/check.py": "def check(kg):\n    return kg <= 30\n",
                 "docs/guide.md": "# Guide\n", "docs/old.md": "# Old\n", "README.md": "Parcel rules.\n",
                 ".gitignore": "*.log\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "The rules", when="2026-11-20T10:00:00+00:00")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    write(repo, {"src/extra.py": "X = 1\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "An extra rule", when="2026-11-21T10:00:00+00:00")
    # the work in progress
    write(repo, {"src/rules.py": "LIMIT = 31\n", "src/new_rule.py": "Y = 2\n", "notes.txt": "todo\n",
                 "debug.log": "ignored by .gitignore\n"})
    git(repo, "add", "src/new_rule.py")                       # added (staged)
    (repo / "docs" / "old.md").unlink()                       # deleted
    git(repo, "mv", "docs/guide.md", "docs/handbook.md")      # renamed (staged)
    write(repo, {f"build/out_{i:03d}.bin": "x" for i in range(pile)})   # a pile of generated output
    if old:
        three_days = time.time() - 3 * DAY
        os.utime(repo / "src" / "rules.py", (three_days, three_days))
    return repo


def adopt(case, repo: Path, *, source_kind: str = "path", title: str = "Parcel rules"):
    p = case.factory.new_project(title)
    p.update_meta(source_kind="adopted", intent="maintain", upstream=str(repo))
    p.write("adopted.json", {"source": str(repo), "source_kind": source_kind, "intent": "maintain",
                             "default_branch": "main"})
    return p


class WipCase(CockpitTestCase):
    """Each test reads afresh: no reading cached by another test's working copy."""

    def setUp(self):
        super().setUp()
        wip._cache.clear()


class ReadingTest(WipCase):

    def test_FR_WIP1_AC_1_the_working_copy_is_read_as_metadata_and_nothing_is_written(self):
        repo = working_copy(self.tmp / "work")
        p = adopt(self, repo)
        before, ledger = digest(repo), p.path("ledger.jsonl").read_bytes()
        r = wip.read(p, fresh=True)
        self.assertTrue(r["measured"], r)
        self.assertEqual((r["branch"], r["tracking"], r["ahead"], r["behind"]), ("main", "origin/main", 1, 0))
        self.assertEqual(r["last_commit_at"], "2026-11-21T10:00:00Z")
        self.assertEqual({k: r["changed"][k] for k in wip.KINDS},
                         {"modified": 1, "added": 1, "deleted": 1, "renamed": 1, "conflicted": 0, "untracked": 61})
        self.assertNotIn("debug.log", json.dumps(r))                        # .gitignore hides it
        areas = {a["area"]: a for a in r["areas"]}
        self.assertEqual(areas["src"]["modified"] + areas["src"]["added"], 2)
        self.assertEqual((areas["docs"]["deleted"], areas["docs"]["renamed"]), (1, 1))
        self.assertEqual(areas[wip.TOP]["untracked"], 1)                    # notes.txt, in the root
        self.assertEqual(r["areas"][0]["area"], "build")                    # the most changed first
        self.assertIsNotNone(r["oldest_change_at"])
        self.assertEqual(digest(repo), before)                              # the repository, byte for byte
        self.assertEqual(p.path("ledger.jsonl").read_bytes(), ledger)       # and nothing recorded
        # git runs without optional locks, hooks or fsmonitor, within its limit
        with mock.patch("kernel.wip.subprocess.run", wraps=subprocess.run) as run:
            wip.read(p, fresh=True)
        for call in run.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[:2], ["git", "--no-optional-locks"])
            self.assertIn("core.fsmonitor=false", argv)
            self.assertTrue(any(a.startswith("core.hooksPath=") for a in argv))
            self.assertEqual(call.kwargs["timeout"], wip.TIMEOUT)

    def test_FR_WIP1_AC_2_no_working_copy_here_is_not_measured_with_why(self):
        made = self.factory.new_project("Made here")
        self.assertFalse(wip.read(made)["measured"])
        self.assertFalse(wip.read(made)["applies"])
        self.assertIn("no repository of its own", wip.read(made)["why"])
        remote = adopt(self, Path("https://example.org/rules.git"), source_kind="url", title="From a URL")
        self.assertIn("remote address", wip.read(remote)["why"])
        gone = adopt(self, self.tmp / "nowhere", title="Gone")
        self.assertIn("is not there on this machine", wip.read(gone)["why"])
        plain = self.tmp / "plain"
        plain.mkdir()
        not_git = adopt(self, plain, title="Not git")
        out = wip.read(not_git)
        self.assertEqual((out["measured"], out["applies"]), (False, True))
        self.assertIn("not a git working copy", out["why"])
        self.assertTrue(out["said"].startswith("Work in progress is not measured: "))
        self.assertNotIn("changed", out)                                    # never a zero
        repo = working_copy(self.tmp / "slow")
        slow = adopt(self, repo, title="Slow")
        with mock.patch("kernel.wip._git", side_effect=subprocess.TimeoutExpired(["git"], wip.TIMEOUT)):
            out = wip.read(slow, fresh=True)
        self.assertFalse(out["measured"])
        self.assertIn(f"longer than {wip.TIMEOUT} seconds", out["why"])

    def test_FR_WIP1_AC_3_a_pile_of_untracked_files_looks_generated_and_is_not_work(self):
        repo = working_copy(self.tmp / "work")
        r = wip.read(adopt(self, repo), fresh=True)
        self.assertEqual(r["piles"], [{"area": "build", "untracked": 60}])
        self.assertEqual(r["work"]["total"], 5)                             # the pile is left out of the work
        self.assertEqual(r["work"]["untracked"], 1)
        self.assertIn("60 untracked files in build/ look generated: add build/ to .gitignore", r["said"])
        self.assertIn("5 changed files not committed", r["said"])
        small = working_copy(self.tmp / "small", pile=3)
        self.assertEqual(wip.read(adopt(self, small, title="Small"), fresh=True)["piles"], [])   # a few files: work


class NudgeTest(WipCase):

    def test_FR_WIP1_AC_4_start_here_nudges_when_large_or_old_and_never_blocks(self):
        recent = adopt(self, working_copy(self.tmp / "recent"), title="Recent")
        self.assertFalse(wip.read(recent, fresh=True)["nudge"])             # 5 files, all from today
        self.assertNotIn("commit_work", [s["id"] for s in start_here.steps(recent)[0]])
        old = adopt(self, working_copy(self.tmp / "old", old=True), title="Old")
        r = wip.read(old, fresh=True)
        self.assertTrue(r["nudge"])
        steps = start_here.steps(old)[0]
        step = next(s for s in steps if s["id"] == "commit_work")
        self.assertEqual(step["label"], "Commit your work in progress (5 files)")
        self.assertIn("across docs, src, (top level)", step["why"])   # most changed first, then by name
        self.assertIn("from 3 days ago", step["why"])
        self.assertIn("Rihmasto reads committed work only", step["why"])
        self.assertEqual((step["route"], step["control"]), (f"#/p/{old.pid}/overview", "wip_card"))
        self.assertGreater(len(steps), 1)                                   # a nudge beside the others, not instead
        with mock.patch.object(wip, "LARGE", 5):                            # large, though recent
            wip._cache.clear()
            self.assertTrue(wip.read(recent, fresh=True)["nudge"])


class SameEverywhereTest(WipCase):
    def test_FR_WIP1_AC_5_the_card_the_command_line_and_ask_rihma_say_the_same(self):
        p = adopt(self, working_copy(self.tmp / "work", old=True))
        status, card, _ = self.call("GET", f"/api/projects/{p.pid}/wip")
        self.assertEqual(status, 200, card)
        self.assertTrue(card["measured"] and card["applies"] and card["nudge"])
        status, fresh, _ = self.call("GET", f"/api/projects/{p.pid}/wip?fresh=1")
        self.assertEqual((status, fresh["said"]), (200, card["said"]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), "wip", p.pid])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().splitlines()[0], card["said"])
        self.assertIn("  build: 60 untracked (looks generated)", out.getvalue())
        self.assertIn("Start here nudges to commit it.", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--home", str(self.factory.home), "wip", p.pid, "--json"])
        self.assertEqual(json.loads(out.getvalue())["said"], card["said"])
        for q in ("What am I in the middle of?", "what's uncommitted?", "what have I not committed yet?"):
            said = ask(self.factory, q, persona="developer", project_id=p.pid, model=None)
            self.assertEqual(said["by"], "rule", q)
            self.assertTrue(said["answer"].startswith(card["said"]), (q, said["answer"]))
            self.assertEqual(said["navigate"], {"route": f"#/p/{p.pid}/overview", "control": "wip_card"}, q)
        elsewhere = ask(self.factory, "what am I in the middle of?", persona="developer", model=None)
        self.assertIn("open an adopted or attached project", elsewhere["answer"])


if __name__ == "__main__":
    unittest.main()
