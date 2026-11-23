"""tools/release_import.py: the import command of tools/release_sync.py, which brings the contributions
merged on the public main into the development repository: what it keeps (the author, the merged message,
the sign-off), what it refuses before it changes anything, and that it never applies a change twice.
tests/sync_fakes.py builds the repositories.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).parent))

import release_import  # noqa: E402
from sync_fakes import (  # noqa: E402
    BASE,
    CONTRIBUTOR,
    GITHUB_TOKEN,
    MAINTAINER,
    OLD_TOOL,
    PNG,
    SIGNED,
    WORD,
    SyncCase,
    blocks,
    git,
    plumb,
)

GUIDE = "# Guide\n\nline one\nline two, from a contributor\nline three\n"
SETTINGS = "settings.toml"


class ImportTest(SyncCase):
    def test_export_refuses_until_the_merged_contribution_is_imported_with_its_author_and_sign_off(self):
        self.export_and_merge()
        sha = self.contribute({"docs/guide.md": GUIDE}, "Clarify the guide")
        self.change(self.private, {"kernel/app.py": "def answer():\n    return 42\n"}, "Private work goes on")
        code, out, _ = self.sync("status")
        self.assertIn(f"waiting for import, oldest first (1):\n  {sha[:12]} Clarify the guide "
                      f"({CONTRIBUTOR[0]} <{CONTRIBUTOR[1]}>)", out)
        code, out, _ = self.sync("export")
        self.assertEqual(code, 1, out)
        self.assertIn("An export must never revert a contribution", out)
        self.assertNotIn(f"sync/{self.head()[:12]}", git(self.public, "branch", "--list"))
        code, out, err = self.sync("import")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"  {sha[:12]} Clarify the guide ({CONTRIBUTOR[0]} <{CONTRIBUTOR[1]}>): signed off by its author",
                      out)
        author = git(self.private, "log", "-1", "--format=%an|%ae|%ad|%cn", "--date=raw")
        self.assertEqual(author, "|".join([*CONTRIBUTOR, git(self.origin, "log", "-1", "--format=%ad", "--date=raw",
                                                             sha), MAINTAINER[0]]))
        self.assertEqual(git(self.private, "log", "-1", "--format=%B"),
                         f"Clarify the guide\n\n{SIGNED}\nRihmasto-Import: {sha}")
        self.assertIn("line two, from a contributor", self.read("docs/guide.md"))
        self.assertIn("nothing waits for import", self.sync("status")[1])
        self.assertIn("nothing waits for import", self.sync("import")[1])
        self.export_and_merge()                                                      # both changes go out
        public = (git(self.public, "show", "origin/main:docs/guide.md")
                  + git(self.public, "show", "origin/main:kernel/app.py"))
        self.assertIn("from a contributor", public)
        self.assertIn("return 42", public)

    def test_a_renamed_a_deleted_and_a_binary_file_come_in_and_the_next_export_has_nothing_to_add(self):
        self.export_and_merge()
        renamed = OLD_TOOL.replace("step 3", "step three")
        self.contribute({"tools/old.py": None, "tools/renamed.py": renamed, "docs/notes.md": None,
                         "img/logo.png": PNG + b"\0more", "img/new.png": PNG[::-1]},
                        "Rename the tool, drop the notes, new images")
        code, out, err = self.sync("import")
        self.assertEqual((code, err), (0, ""), out)
        self.assertFalse((self.private / "tools/old.py").exists())
        self.assertFalse((self.private / "docs/notes.md").exists())
        self.assertEqual(self.read("tools/renamed.py"), renamed)
        self.assertEqual((self.private / "img/logo.png").read_bytes(), PNG + b"\0more")
        self.assertEqual((self.private / "img/new.png").read_bytes(), PNG[::-1])
        self.assertEqual(git(self.private, "status", "--porcelain"), "")
        code, out, _ = self.sync("export")
        self.assertEqual(code, 0, out)
        self.assertIn("nothing to export: the public main already holds the snapshot", out)

    def test_a_contribution_touching_a_left_out_path_is_refused_before_anything_changes(self):
        self.export_and_merge()
        good = self.contribute({"README.md": "# Demo\n\nRead the [guide](docs/guide.md) first.\n"}, "A better readme")
        self.contribute({"intake/notes.md": "an outside note\n"}, "Add notes to the brief")
        self.contribute({"blueprint/extra.log": "a run\n", ".release-denylist": "nothing\n"}, "Add a run log")
        before = self.head()
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn("refused: nothing was imported.", out)
        for path in ("intake/notes.md", "blueprint/extra.log", ".release-denylist"):
            self.assertIn(f"touches {path}, which release/exclude.txt keeps out of the public repository", out)
        self.assertEqual(self.head(), before)
        self.assertNotIn("first", self.read("README.md"))
        code, out, _ = self.sync("import", "--through", good[:12])                    # the good one alone
        self.assertEqual(code, 0, out)
        self.assertIn("first", self.read("README.md"))

    def test_a_contribution_the_export_scans_would_refuse_is_refused_masked(self):
        self.export_and_merge()
        self.contribute({"docs/word.md": f"A pilot with {WORD}.\n", "kernel/keys.py": f'TOKEN = "{GITHUB_TOKEN}"\n',
                         "data/big.bin": b"\0" * (5 * 2**20 + 1),
                         "docs/link.md": "See the [brief](../intake/brief.md).\n"}, "Several problems")
        before = self.head()
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn("docs/word.md:1: denylist: a denylisted word: Z*******", out)
        self.assertIn("kernel/keys.py:1: secret: a GitHub token", out)
        self.assertIn("data/big.bin: size:", out)
        self.assertIn("docs/link.md:1: link: a relative link to an excluded file", out)
        self.assertNotIn(WORD.lower(), out.lower())
        self.assertNotIn(GITHUB_TOKEN, out)
        self.assertEqual(self.head(), before)

    def test_a_spoofed_export_trailer_is_a_contribution_and_a_planted_import_trailer_is_refused(self):
        exported = self.export_and_merge()
        spoof = self.contribute({"docs/guide.md": "# Guide\n\nline one\nline two\nline three\nline four\n"},
                                "Looks like an export", trailers=f"{SIGNED}\nRihmasto-Export: {exported}")
        unknown = self.contribute({"kernel/app.py": "def answer():\n    return 43\n"}, "Names no real revision",
                                  trailers=f"{SIGNED}\nRihmasto-Export: {'f' * 40}")
        code, out, _ = self.sync("status")
        self.assertIn(f"snapshot of {exported[:12]}", out)                           # still the real export
        self.assertIn(f"waiting for import, oldest first (2):\n  {spoof[:12]}", out)
        self.assertIn(f"  {unknown[:12]}", out)
        code, out, _ = self.sync("import")
        self.assertEqual(code, 0, out)
        self.assertIn(f"Rihmasto-Import: {spoof}", git(self.private, "log", "-1", "--format=%B", "HEAD~1"))
        planted = self.contribute({"README.md": "# Demo\n\nThe [guide](docs/guide.md).\n"}, "Marks another as imported",
                                  trailers=f"{SIGNED}\nRihmasto-Import: {'e' * 40}")
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn(f"{planted[:12]} Marks another as imported: its message carries a Rihmasto-Import trailer", out)

    def test_a_contribution_that_does_not_apply_cleanly_is_refused_and_nothing_changes(self):
        self.export_and_merge()
        self.change(self.private, {"docs/guide.md": "# Guide\n\nline one\nline two, private\nline three\n"},
                    "Private work on the guide")
        good = self.contribute({"README.md": "# Demo\n\nRead the [guide](docs/guide.md) first.\n"}, "A better readme")
        clash = self.contribute({"docs/guide.md": "# Guide\n\nline one\nline two, public\nline three\n"}, "Clash")
        before = self.head()
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn(f"{clash[:12]} Clash ({CONTRIBUTOR[0]} <{CONTRIBUTOR[1]}>): does not apply cleanly here: it "
                      "meets a different change made here, in docs/guide.md", out)
        self.assertIn("git apply --3way contribution.patch", out)
        self.assertIn(f'git commit --allow-empty -m "Record {clash[:12]}, here already" --trailer '
                      f'"Rihmasto-Import: {clash}"', out)
        self.assertIn(f"import them first with --through {good}", out)
        self.assertEqual(self.head(), before)
        self.assertEqual(git(self.private, "status", "--porcelain"), "")

    def test_a_merged_message_without_the_authors_sign_off_is_imported_and_said_so(self):
        self.export_and_merge()
        signed = self.contribute({"README.md": "# Demo\n\nRead the [guide](docs/guide.md) first.\n"}, "A better readme")
        bare = self.contribute({"docs/guide.md": GUIDE}, "", message="Clarify the guide (#9)\n\nThe second line was "
                               "unclear.")                                   # "Pull request title and description"
        code, out, _ = self.sync("import")
        self.assertEqual(code, 0, out)
        self.assertNotIn("each with its author and sign-off", out)
        self.assertIn(f"  {signed[:12]} A better readme ({CONTRIBUTOR[0]} <{CONTRIBUTOR[1]}>): signed off by its "
                      "author", out)
        self.assertIn(f"  {bare[:12]} Clarify the guide (#9) ({CONTRIBUTOR[0]} <{CONTRIBUTOR[1]}>): no "
                      "Signed-off-by of its author in the merged message", out)

    def test_a_contribution_merged_with_a_merge_commit_is_refused_with_what_to_do(self):
        self.export_and_merge()
        main = git(self.origin, "rev-parse", "main")
        topic = plumb(self.origin, [main], {"docs/guide.md": GUIDE}, f"Clarify the guide\n\n{SIGNED}", CONTRIBUTOR)
        message = "Merge pull request #8 from a-contributor/topic\n\nClarify the guide"
        merge = self.push_main(plumb(self.origin, [main, topic], {}, message, MAINTAINER, base=topic))
        before = self.head()
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn(f"{merge[:12]} Merge pull request #8 from a-contributor/topic: a merge commit: its author is "
                      "whoever merged it", out)
        self.assertIn("in a commit with the contributor as its author and their sign-off", " ".join(out.split()))
        self.assertEqual(self.head(), before)


class GuardTest(SyncCase):
    def test_a_contribution_loosening_the_exclude_list_is_refused_even_when_reviewed(self):
        self.export_and_merge()
        looser = "/intake/\n/blueprint/\n!/blueprint/run.log\n.release-denylist\n"
        sha = self.contribute({"release/exclude.txt": looser}, "Ship the run log")
        before = self.head()
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn(f"changes release/exclude.txt, which decide(s) what is tracked here and what ships: read the "
                      f"change, then import with --reviewed {sha[:12]}", out)
        self.assertIn("its release/exclude.txt would ship 1 file(s) this repository leaves out: blueprint/run.log", out)
        code, out, _ = self.sync("import", "--reviewed", sha[:12])
        self.assertEqual(code, 1, out)
        self.assertIn("would ship 1 file(s) this repository leaves out: blueprint/run.log", out)
        self.assertNotIn("--reviewed", out)
        self.assertEqual(self.head(), before)
        self.assertEqual(self.sync("export")[0], 1)                                   # nothing ships meanwhile

    def test_a_contribution_tightening_the_exclude_list_or_changing_a_release_tool_comes_in_only_when_reviewed(self):
        self.export_and_merge()
        tighter = self.contribute({"release/exclude.txt": BASE["release/exclude.txt"] + "/docs/notes.md\n"},
                                  "Leave the notes out")
        tool = self.contribute({"tools/release_export.py": "print('a faster export')\n"}, "A faster export")
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn(f"read the change, then import with --reviewed {tighter[:12]}", out)
        self.assertIn("changes tools/release_export.py, which decide(s) what is tracked here and what ships", out)
        self.assertEqual(self.sync("import", "--reviewed", tighter[:12])[0], 1)      # the tool is not reviewed yet
        code, out, _ = self.sync("import", "--reviewed", tighter[:12], "--reviewed", tool[:12])
        self.assertEqual(code, 0, out)
        rev = self.change(self.private, {"VERSION": "2\n"}, "Version 2")
        self.assertEqual(self.sync("export")[0], 0)
        self.assertNotIn("docs/notes.md", self.files_at(self.public, f"sync/{rev[:12]}"))

    def test_a_path_left_out_in_another_case_differing_only_in_case_or_landing_on_a_local_file_is_refused(self):
        self.export_and_merge()
        (self.private / ".env").write_text("PASSWORD=a-local-one\n", encoding="utf-8")
        self.contribute({"Intake/notes.md": "an outside note\n"}, "Notes, in another case")
        self.contribute({"Docs/extra.md": "More docs.\n"}, "Docs, in another case")
        self.contribute({".Release-Denylist": "nothing\n"}, "The denylist, in another case")
        self.contribute({".env": "PASSWORD=theirs\n"}, "An environment file")
        before = self.head()
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn("touches Intake/notes.md, which release/exclude.txt keeps out of the public repository", out)
        self.assertIn("adds Docs/extra.md, whose Docs differs only in case from docs here", out)
        self.assertIn("touches .Release-Denylist, which release/exclude.txt keeps out of the public repository", out)
        self.assertIn("adds .env, which is a local file here that git does not track: it would be overwritten", out)
        self.assertEqual(self.head(), before)
        self.assertEqual(self.read(".env"), "PASSWORD=a-local-one\n")

    def test_a_gitignore_change_that_would_expose_local_files_is_refused_even_when_reviewed(self):
        self.export_and_merge({".gitignore": ".env\n.audit/\n"})
        (self.private / ".env").write_text("DB_PASSWORD=hunter2hunter2\n", encoding="utf-8")
        (self.private / ".audit").mkdir()
        (self.private / ".audit" / "chain.jsonl").write_text("{}\n", encoding="utf-8")
        sha = self.contribute({".gitignore": "# nothing to ignore\n"}, "Tidy the ignore list")
        code, out, _ = self.sync("import")
        self.assertEqual(code, 1, out)
        self.assertIn(f"changes .gitignore, which decide(s) what is tracked here and what ships: read the change, then "
                      f"import with --reviewed {sha[:12]}", out)
        self.assertIn("its .gitignore would stop ignoring 2 local file(s), which the next commit could track and the "
                      "next export ship: .audit/chain.jsonl, .env", out)
        code, out, _ = self.sync("import", "--reviewed", sha[:12])
        self.assertEqual(code, 1, out)
        self.assertIn("would stop ignoring 2 local file(s)", out)
        self.assertEqual(self.read(".gitignore"), ".env\n.audit/\n")

    def test_a_gitignore_change_that_exposes_nothing_comes_in_when_reviewed(self):
        self.export_and_merge({".gitignore": ".env\n"})
        (self.private / ".env").write_text("DB_PASSWORD=hunter2hunter2\n", encoding="utf-8")
        sha = self.contribute({".gitignore": ".env\n*.tmp\n"}, "Ignore temporary files")
        self.assertEqual(self.sync("import")[0], 1)
        code, out, _ = self.sync("import", "--reviewed", sha[:12])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.read(".gitignore"), ".env\n*.tmp\n")


class AppliedOnceTest(SyncCase):
    """A change that is here already is recorded as imported, never applied a second time: in a file of
    identical blocks, a patch applied at an offset would change the wrong block."""

    def test_a_sync_pull_request_squashed_after_main_moved_is_not_applied_twice(self):
        self.export_and_merge({SETTINGS: blocks(1, 1, 1, 1, 1, 1)})
        rev = self.change(self.private, {SETTINGS: blocks(1, 2, 1, 1, 1, 1)}, "Raise block two")
        self.assertEqual(self.sync("export")[0], 0)                                   # its pull request waits...
        self.contribute({"docs/guide.md": GUIDE}, "Clarify the guide")               # ...a contribution merges...
        stale = self.merge_stale(f"sync/{rev[:12]}")                                  # ...then it merges anyway
        code, out, _ = self.sync("status")
        self.assertIn(f"  {stale[:12]} Sync from the development repository at {rev[:12]}", out)
        self.assertIn(f"it names {rev[:12]} as exported, but its tree is not that snapshot: a sync pull request "
                      "merged after main moved", out)
        code, out, err = self.sync("import")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn(f"  {stale[:12]} Sync from the development repository at {rev[:12]}", out)
        self.assertIn("here already, recorded with no change", out)
        self.assertEqual(self.read(SETTINGS), blocks(1, 2, 1, 1, 1, 1))
        self.assertIn("from a contributor", self.read("docs/guide.md"))
        self.assertEqual(self.sync("export")[0], 0)
        self.assertEqual(git(self.public, "show", f"origin/main:{SETTINGS}"), blocks(1, 2, 1, 1, 1, 1).strip())

    def test_an_export_of_a_branch_squashed_here_since_is_not_applied_twice(self):
        self.export_and_merge({SETTINGS: blocks(1, 1, 1, 1, 1, 1)})
        git(self.private, "checkout", "-q", "-b", "feature")
        rev = self.change(self.private, {SETTINGS: blocks(1, 2, 1, 1, 1, 1)}, "Raise block two")
        self.assertEqual(self.sync("export")[0], 0)
        squash = self.merge_pr(f"sync/{rev[:12]}")
        git(self.private, "checkout", "-q", "main")
        git(self.private, "merge", "-q", "--squash", "feature")
        git(self.private, "commit", "-q", "-m", "Raise block two, squashed")
        git(self.private, "branch", "-q", "-D", "feature")
        code, out, _ = self.sync("status")
        self.assertIn(f"  {squash[:12]} Sync from the development repository at {rev[:12]}", out)
        self.assertIn("which this repository's history does not hold", out)
        code, out, _ = self.sync("import")
        self.assertEqual(code, 0, out)
        self.assertIn("here already, recorded with no change", out)
        self.assertEqual(self.read(SETTINGS), blocks(1, 2, 1, 1, 1, 1))

    def test_a_contribution_rewritten_by_a_force_push_is_not_applied_twice(self):
        self.export_and_merge({SETTINGS: blocks(1, 1, 1, 1, 1, 1)})
        main = git(self.origin, "rev-parse", "main")
        self.contribute({SETTINGS: blocks(1, 2, 1, 1, 1, 1)}, "Raise block two")
        self.assertEqual(self.sync("import")[0], 0)
        self.push_main(plumb(self.origin, [main], {SETTINGS: blocks(1, 2, 1, 1, 1, 1)},
                             f"Raise block two, reworded\n\n{SIGNED}", CONTRIBUTOR))
        code, out, _ = self.sync("import")
        self.assertEqual(code, 0, out)
        self.assertIn("Raise block two, reworded", out)
        self.assertIn("here already, recorded with no change", out)
        self.assertEqual(self.read(SETTINGS), blocks(1, 2, 1, 1, 1, 1))


class TrailerTest(unittest.TestCase):
    def test_the_import_trailer_joins_a_trailer_block_or_starts_one(self):
        add = release_import.with_trailer
        self.assertEqual(add("Subject\n", "Rihmasto-Import: x"), "Subject\n\nRihmasto-Import: x\n")
        self.assertEqual(add("Fix: a crash\n", "K: v"), "Fix: a crash\n\nK: v\n")      # a subject is no trailer
        self.assertEqual(add("S\n\nBody text.\n\nSigned-off-by: A <a@example.invalid>\n\n", "K: v"),
                         "S\n\nBody text.\n\nSigned-off-by: A <a@example.invalid>\nK: v\n")
        self.assertEqual(add("S\n\nA closing paragraph: not trailers\nat all\n", "K: v"),
                         "S\n\nA closing paragraph: not trailers\nat all\n\nK: v\n")


if __name__ == "__main__":
    unittest.main()
