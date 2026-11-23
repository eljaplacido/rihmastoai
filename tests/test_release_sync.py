"""tools/release_sync.py: the two-way sync between the development repository and the public one; here,
how the public history is read (tools/release_state.py) and the status and export commands. The import
command is tested in tests/test_release_import.py; tests/sync_fakes.py builds the repositories.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent))

import dco_check  # noqa: E402
import release_export  # noqa: E402
import release_state  # noqa: E402
import release_sync  # noqa: E402
from sync_fakes import CONTRIBUTOR, MAINTAINER, PUBLIC, ROOT, SIGNED, SyncCase, git, plumb, release_sync_main  # noqa: E402

GUIDE = "# Guide\n\nline one\nline two, from a contributor\nline three\n"


class ExportTest(SyncCase):
    def test_an_export_commits_the_snapshot_on_a_sync_branch_with_the_trailer_and_prints_the_next_steps(self):
        rev = self.change(self.private, {"kernel/app.py": "def answer():\n    return 42\n"}, "The right answer")
        code, out, err = self.sync("export")
        self.assertEqual((code, err), (0, ""), out)
        branch = f"sync/{rev[:12]}"
        self.assertEqual(self.files_at(self.public, branch), PUBLIC)                    # intake/, blueprint/ left out
        self.assertEqual(git(self.public, "show", f"{branch}:kernel/app.py"), "def answer():\n    return 42")
        self.assertEqual(git(self.public, "rev-parse", f"{branch}^"), self.first)       # made from the public main
        message = git(self.public, "log", "-1", "--format=%B", branch)
        self.assertTrue(message.startswith(f"Sync from the development repository at {rev[:12]}\n\n"), message)
        self.assertTrue(message.endswith(f"Signed-off-by: {MAINTAINER[0]} <{MAINTAINER[1]}>\nRihmasto-Export: {rev}"))
        self.assertIn(f"push origin {branch}", out)
        self.assertIn(f"gh pr create --base main --head {branch} --fill", out)
        self.assertEqual(git(self.origin, "rev-parse", "main"), self.first)             # nothing pushed without --pr
        # the sync pull request passes the DCO check: its commit is signed off by its author
        self.assertEqual(dco_check.check(self.public, self.first, branch)[0], 0)
        squash = self.merge_pr(branch)
        code, out, _ = self.sync("status")
        self.assertEqual(code, 0, out)
        self.assertIn(f"the last export: {squash[:12]}, the snapshot of {rev[:12]}", out)
        self.assertIn("nothing waits for import", out)
        self.assertIn("nothing to export", self.sync("export")[1])

    def test_with_pr_the_branch_is_pushed_and_a_pull_request_opened_whose_description_ends_with_the_trailer(self):
        rev = self.change(self.private, {"docs/guide.md": "# Guide\n\nline one, clearer\nline two\nline three\n"},
                          "A clearer guide")
        calls = []
        with mock.patch.object(release_sync, "run_gh", lambda cwd, args: calls.append((cwd, args)) or 0):
            code, out, err = self.sync("export", "--pr")
        self.assertEqual((code, err), (0, ""), out)
        branch = f"sync/{rev[:12]}"
        self.assertEqual(git(self.origin, "rev-parse", branch), git(self.public, "rev-parse", branch))
        [(cwd, args)] = calls
        self.assertEqual(Path(cwd), self.public)
        self.assertEqual(args[:6], ["pr", "create", "--base", "main", "--head", branch])
        body = args[args.index("--body") + 1]
        self.assertTrue(body.endswith(f"Rihmasto-Export: {rev}"), body)
        self.assertIn(f"{branch} exists already", self.sync("export")[1])            # an export is made once

    def test_an_export_that_would_go_back_before_the_last_one_is_refused(self):
        older = self.head()
        self.change(self.private, {"kernel/app.py": "def answer():\n    return 42\n"}, "The right answer")
        self.export_and_merge()
        code, out, _ = self.sync("export", "--rev", older)
        self.assertEqual(code, 1, out)
        self.assertIn("would undo work the public repository has", out)

    def test_an_older_revision_that_lacks_an_import_made_since_the_last_export_is_refused(self):
        self.export_and_merge()
        before = self.change(self.private, {"kernel/app.py": "def answer():\n    return 42\n"}, "Private work")
        sha = self.contribute({"docs/guide.md": GUIDE}, "Clarify the guide")
        self.assertEqual(self.sync("import")[0], 0)
        code, out, _ = self.sync("export", "--rev", before)
        self.assertEqual(code, 1, out)
        self.assertIn(f"refused: {before[:12]} does not hold the import of 1 contribution(s)", out)
        self.assertIn(f"  {sha[:12]} Clarify the guide", out)
        self.assertNotIn(f"sync/{before[:12]}", git(self.public, "branch", "--list"))
        self.assertEqual(self.sync("export")[0], 0)                                   # HEAD holds it

    def test_before_the_earlier_snapshots_are_recorded_status_shows_how_to_record_them(self):
        git(self.private, "reset", "-q", "--hard", "HEAD~1")                          # no record yet
        code, out, _ = self.sync("status")
        self.assertEqual(code, 0, out)
        self.assertIn("the last export: none found", out)
        self.assertIn(f"  {self.first[:12]} The first public snapshot ({MAINTAINER[0]} <{MAINTAINER[1]}>)", out)
        self.assertIn(f'--allow-empty -m "Record the public history made before release_sync" '
                      f'--trailer "Rihmasto-Import: {self.first}"', out)
        self.assertNotIn("Careful", out)                                              # HEAD holds the snapshot
        self.assertEqual(self.sync("export")[0], 1)

    def test_the_first_export_refuses_to_delete_public_files_head_lacks_unless_allowed(self):
        git(self.private, "reset", "-q", "--hard", "HEAD~1")
        # a later snapshot, made from a branch HEAD does not hold yet
        later = self.push_main(plumb(self.origin, [self.first], {"kernel/redteam.py": "RULES = []\n"},
                                     "The red team", MAINTAINER))
        code, out, _ = self.sync("status")
        self.assertIn("Careful: HEAD's snapshot lacks 1 file(s) the public main has: kernel/redteam.py.", out)
        git(self.private, "commit", "-q", "--allow-empty", "-m", "Record the public history",
            "-m", f"Rihmasto-Import: {self.first}\nRihmasto-Import: {later}")
        self.change(self.private, {"VERSION": "1\n"}, "Version 1")
        code, out, _ = self.sync("export")
        self.assertEqual(code, 1, out)
        self.assertIn("refused: this first export would delete 1 file(s) the public main has: kernel/redteam.py", out)
        self.assertEqual(git(self.public, "branch", "--list", "sync/*"), "")
        code, out, err = self.sync("export", "--allow-deletions")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("it deletes 1 file(s) from the public main: kernel/redteam.py", out)

    def test_the_public_clone_must_not_be_this_repository(self):
        code, out, err = release_sync_main("status", "--public", str(self.private), "--repo", str(self.private),
                                           "--denylist", str(self.deny))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("is this repository or a work tree of it", err)


class ReadingTheHistoryTest(SyncCase):
    def test_a_sync_pull_request_squashed_with_its_title_alone_is_still_the_export(self):
        rev = self.change(self.private, {"kernel/app.py": "def answer():\n    return 42\n"}, "The right answer")
        self.assertEqual(self.sync("export")[0], 0)
        squash = self.merge_pr(f"sync/{rev[:12]}", title_only=True)        # GitHub's "Pull request title" default
        self.assertNotIn("Rihmasto-Export", git(self.origin, "log", "-1", "--format=%B", squash))
        code, out, _ = self.sync("status")
        self.assertIn(f"the last export: {squash[:12]}, the snapshot of {rev[:12]}", out)
        self.assertIn("nothing waits for import", out)

    def test_a_sync_pull_request_merged_with_a_merge_commit_is_the_export(self):
        rev = self.change(self.private, {"kernel/app.py": "def answer():\n    return 42\n"}, "The right answer")
        self.assertEqual(self.sync("export")[0], 0)
        git(self.public, "push", "-q", "origin", f"sync/{rev[:12]}")
        branch = git(self.public, "rev-parse", f"sync/{rev[:12]}")
        merge = self.push_main(plumb(self.origin, [self.first, branch], {},
                                     f"Merge pull request #7 from a-maintainer/sync/{rev[:12]}", MAINTAINER,
                                     base=f"{branch}^{{tree}}"))
        code, out, _ = self.sync("status")
        self.assertIn(f"the last export: {merge[:12]}, the snapshot of {rev[:12]}", out)
        self.assertIn("nothing waits for import", out)
        self.export_and_merge()                                                        # the next export goes on

    def test_a_copied_trailer_restoring_an_earlier_snapshot_is_a_contribution_and_blocks_the_export(self):
        first = self.export_and_merge()
        first_tree = git(self.origin, "rev-parse", "main^{tree}")
        self.contribute({"docs/guide.md": GUIDE}, "Clarify the guide")
        self.assertEqual(self.sync("import")[0], 0)
        second = self.export_and_merge()
        main = git(self.origin, "rev-parse", "main")
        copied = self.push_main(plumb(self.origin, [main], {}, f"Back to the first release\n\n{SIGNED}\n"
                                      f"Rihmasto-Export: {first}", CONTRIBUTOR, base=first_tree))
        code, out, _ = self.sync("status")
        self.assertIn(f"the snapshot of {second[:12]}", out)                          # still the real export
        self.assertIn(f"waiting for import, oldest first (1):\n  {copied[:12]} Back to the first release", out)
        self.assertIn(f"it names {first[:12]} as exported, which the exports before it have passed", out)
        code, out, _ = self.sync("export")
        self.assertEqual(code, 1, out)
        self.assertIn("An export must never revert a contribution", out)

    def test_a_contribution_whose_subject_holds_a_control_character_is_read_and_waits(self):
        self.export_and_merge()
        sha = self.contribute({"GOVERNANCE.md": "A line from a contributor.\n"},
                              "C4 adds a line\x01 to governance (#15)")
        self.change(self.private, {"kernel/app.py": "def answer():\n    return 42\n"}, "Private work")
        code, out, _ = self.sync("status")
        self.assertIn(f"public main: {sha[:12]}", out)
        self.assertIn(f"waiting for import, oldest first (1):\n  {sha[:12]} C4 adds a line", out)
        code, out, _ = self.sync("export")
        self.assertEqual(code, 1, out)
        self.assertIn("An export must never revert a contribution", out)
        self.assertNotIn(f"sync/{self.head()[:12]}", git(self.public, "branch", "--list"))

    def test_a_record_that_forges_the_separators_stops_the_sync_instead_of_hiding_a_commit(self):
        self.export_and_merge()
        token = "0" * 32
        self.contribute({"docs/guide.md": GUIDE}, f"Looks harmless\x1f{token}\x1fforged")
        with mock.patch.object(release_state.secrets, "token_hex", return_value=token):
            code, out, err = self.sync("status")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("the history cannot be read safely", err)


class ExcludeListTest(unittest.TestCase):
    def test_the_exclude_list_keeps_everything_the_release_tools_need(self):
        rules = release_export.compile_rules((ROOT / "release" / "exclude.txt").read_text(encoding="utf-8"))
        for path in ("tools/release_export.py", "tools/release_sync.py", "tools/release_state.py",
                     "tools/release_import.py", "tools/dco_check.py", "release/exclude.txt",
                     "tests/test_release_export.py", "tests/test_release_sync.py", "tests/test_release_import.py",
                     "tests/sync_fakes.py", "tests/test_dco_check.py", ".github/workflows/ci.yml",
                     ".github/workflows/dco.yml", ".github/CODEOWNERS", ".github/dependabot.yml",
                     ".github/ISSUE_TEMPLATE/config.yml", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md",
                     "docs/maintainers.md"):
            self.assertFalse(release_export.excluded(path, rules), path)


if __name__ == "__main__":
    unittest.main()
