"""tools/release_export.py: a scrubbed snapshot of a git revision, for the public repository.

Every test builds a small repository in a temporary folder (git is needed), exports a revision of it
and reads what the tool printed and wrote. The planted secrets are put together at run time, so
this file holds none itself, and the denylisted word is a made-up one.
"""

import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import release_export  # noqa: E402

GIT_ID = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
WORD = "Zorbalux"                                   # the made-up name on the test denylist
MASKED = "Z*******"
EXCLUDE = "# what the public repository leaves out\n\n/private/\n/docs/*.html\n.release-denylist\n"
BASE = {
    "README.md": "# Demo\n\nRead the [guide](docs/guide.md), the [site](https://example.com) or the [top](#demo).\n",
    "docs/guide.md": "Back to the [readme](../README.md) and the [docs](./).\n",
    "docs/page.html": "<p>an earlier design page</p>\n",
    "private/brief.md": "The private brief.\n",
    "tools/run.py": "print('hello')\n",
    "release/exclude.txt": EXCLUDE,
}
SHIPPED = {"README.md", "docs/guide.md", "tools/run.py", "release/exclude.txt"}
# Shaped like real credentials, and not real: put together here so no line of this file is one.
AWS_KEY = "AKIA" + "Q7RELEASETEST042"
GITHUB_TOKEN = "ghp_" + "Rel3aseTestTok3n" + "1234567890" * 2 + "abcd"
SK_KEY = "sk-" + "proj-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
SLACK_TOKEN = "xoxb-" + "1234567890-" + "aBcDeFgHiJ"
LITERAL = "Zq8Vz3LmW9pXr2Kd7NfYb4Hs"
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
KEY_MATERIAL = "MIIEpAIBAAKCAQEA" + "q7Lm2Xv9Rt4Wz8Np3Kd6Hs1Jf5Gb0Yc" * 2   # made up, shaped like a key body
HIT = re.compile(r"^(?P<path>\S+?)(?::(?P<line>\d+))?: (?P<kind>denylist|secret|link|size|path|tree): (?P<detail>.*)$")


def hits(out: str) -> list:
    """(path, line, kind) of each hit the tool printed; line 0 is the file as a whole."""
    return [(m["path"], int(m["line"] or 0), m["kind"]) for m in map(HIT.match, out.splitlines()) if m]


class ExportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="release-export-test-"))
        self.repo = self.tmp / "private-repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "core.autocrlf", "false")
        self.deny = self.tmp / "denylist.txt"
        self.deny.write_text(f"# names that never ship\n\n{WORD}\n", encoding="utf-8")
        self.target = self.tmp / "public"
        self.commit(BASE, "the first snapshot")

    def tearDown(self):
        release_export.remove(self.tmp)                  # git's objects are read-only on Windows

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *GIT_ID, *args], check=True, capture_output=True,
                              text=True).stdout

    def commit(self, files: dict, message: str = "a change") -> None:
        for rel, content in files.items():
            path = self.repo / rel
            if content is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def export(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_export.main(["--repo", str(self.repo), *argv])
        return code, out.getvalue(), err.getvalue()

    def to_target(self, *argv: str) -> tuple:
        return self.export("--target", str(self.target), "--denylist", str(self.deny), *argv)

    def check(self, *argv: str) -> tuple:
        return self.export("--check", "--denylist", str(self.deny), *argv)

    def written(self) -> set:
        return {p.relative_to(self.target).as_posix() for p in self.target.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(self.target).parts}


class ExportTest(ExportCase):
    def test_a_clean_revision_is_written_without_the_excluded_files_byte_for_byte(self):
        code, out, err = self.to_target()
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.written(), SHIPPED)
        for rel in SHIPPED:
            self.assertEqual((self.target / rel).read_bytes(), (self.repo / rel).read_bytes(), rel)
        self.assertNotIn(b"\r", (self.target / "README.md").read_bytes())      # LF, as the revision holds it
        self.assertIn("2 excluded, 4 files in the snapshot", out)

    def test_the_targets_git_is_kept_and_every_other_file_is_replaced_so_deletions_carry_over(self):
        (self.target / ".git").mkdir(parents=True)
        (self.target / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (self.target / "stale" / "deep").mkdir(parents=True)
        (self.target / "stale" / "deep" / "old.txt").write_text("from an earlier export\n", encoding="utf-8")
        readonly = self.target / "old-readonly.txt"
        readonly.write_text("read-only\n", encoding="utf-8")
        readonly.chmod(0o444)
        self.assertEqual(self.to_target()[0], 0)
        self.assertEqual(self.written(), SHIPPED)
        self.assertEqual((self.target / ".git" / "HEAD").read_text(encoding="utf-8"), "ref: refs/heads/main\n")
        # a file deleted in the private repository is deleted in the public one at the next export
        self.commit({"docs/guide.md": None, "README.md": "# Demo\n"}, "the guide goes")
        self.assertEqual(self.to_target()[0], 0)
        self.assertEqual(self.written(), SHIPPED - {"docs/guide.md"})

    def test_check_runs_the_scans_and_writes_nothing(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("clean: --check wrote nothing", out)
        self.assertFalse(self.target.exists())

    def test_an_earlier_revision_can_be_exported(self):
        first = self.git("rev-parse", "HEAD").strip()
        self.commit({"tools/new.py": "print('new')\n"})
        self.assertEqual(self.to_target("--rev", first)[0], 0)
        self.assertEqual(self.written(), SHIPPED)

    @unittest.skipIf(os.name == "nt", "the executable bit is a POSIX file mode")
    def test_an_executable_file_stays_executable(self):
        self.git("update-index", "--chmod=+x", "tools/run.py")
        self.git("commit", "-q", "-m", "executable")
        self.assertEqual(self.to_target()[0], 0)
        self.assertTrue(os.access(self.target / "tools" / "run.py", os.X_OK))


class RefusalTest(ExportCase):
    def assertRefused(self, out: str) -> None:
        self.assertIn("refused: ", out)
        self.assertFalse(self.target.exists(), "a refused export writes nothing")

    def test_a_denylisted_word_is_refused_with_its_file_and_line_and_masked(self):
        self.commit({"docs/word.md": f"# Notes\nA pilot with {WORD.upper()} starts.\n{WORD}ian is another word.\n",
                     f"notes/{WORD.lower()}-plan.txt": "a plan\n"})
        code, out, _ = self.to_target()
        self.assertEqual(code, 1, out)
        self.assertEqual(hits(out), [("docs/word.md", 2, "denylist"), (f"notes/{MASKED.lower()}-plan.txt", 0, "denylist")])
        self.assertNotIn(WORD.lower(), out.lower())                            # masked, in the path too
        self.assertIn(f"docs/word.md:2: denylist: a denylisted word: {MASKED}", out)
        self.assertRefused(out)

    def test_secret_like_strings_are_refused_masked_and_placeholders_are_not(self):
        lines = [f'KEY_ID = "{AWS_KEY}"', f"token: {GITHUB_TOKEN}", PRIVATE_KEY, KEY_MATERIAL,
                 f"OPENAI = '{SK_KEY}'", f"slack = {SLACK_TOKEN}", f'api_key = "{LITERAL}"',
                 # placeholders and names, not secrets
                 'api_key = "your-api-key-goes-here-1234"', 'KEY_ID = "AKIAIOSFODNN7EXAMPLE"',
                 'OPENAI_API_KEY = "OPENAI_API_KEY_FROM_THE_ENV"', "see the sk-learn-style-naming-of-things docs",
                 'token = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"']
        self.commit({"app/config.py": "\n".join(lines) + "\n"})
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertEqual(hits(out), [("app/config.py", n, "secret") for n in (1, 2, 3, 5, 6, 7)])
        for value in (AWS_KEY, GITHUB_TOKEN, SK_KEY, SLACK_TOKEN, LITERAL):
            self.assertNotIn(value, out)
        self.assertIn("app/config.py:1: secret: an AWS access key id: AKI********", out)
        self.assertIn("app/config.py:3: secret: a private key block", out)

    def test_a_private_key_header_without_key_material_is_not_a_secret(self):
        self.commit({"docs/deploy.md": f"The key file starts with `{PRIVATE_KEY}`; never commit it.\n",
                     "app/keydetect.py": f'HEADER = "{PRIVATE_KEY}"\nname = "cache"\n',
                     "app/real.pem": f"{PRIVATE_KEY}\n{KEY_MATERIAL}\n-----END RSA PRIVATE KEY-----\n"})
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertEqual(hits(out), [("app/real.pem", 1, "secret")])

    def test_a_seeded_secret_file_is_allowed_whole_only_in_the_redteam_fixtures(self):
        credentials = f"# seeded: RT-SECRET-FILE (made-up values)\n[default]\naws_access_key_id = {AWS_KEY}\n"
        pattern_only = f"# seeded: RT-SECRET-PATTERN\n[default]\naws_access_key_id = {AWS_KEY}\n"
        self.commit({"tests/fixtures/redteam/app/.aws/credentials": credentials,
                     "tests/fixtures/redteam/app/other.ini": pattern_only,
                     "app/.aws/credentials": credentials})
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        # the file marker covers only a fixture file marked as a seeded secret file, and only there
        self.assertEqual(hits(out), [("app/.aws/credentials", 3, "secret"),
                                     ("tests/fixtures/redteam/app/other.ini", 3, "secret")])

    def test_planted_canaries_are_allowed_only_on_a_marked_line_of_the_redteam_fixtures(self):
        fixture = "\n".join([f'exfil_token = "{GITHUB_TOKEN}"  # redteam: canary (planted for leak tests)',
                             f'STORAGE_KEY_ID = "{AWS_KEY}"  # seeded: RT-SECRET-PATTERN',
                             f'mail_api_token = "{LITERAL}"  # seeded: RT-SECRET-ENTROPY',
                             f'unmarked = "{GITHUB_TOKEN}"',
                             f'mentions = "{GITHUB_TOKEN}"  # this line talks about redteam: canary markers'])
        self.commit({"tests/fixtures/redteam/app/settings.py": fixture + "\n",
                     "tests/test_elsewhere.py": f'TOKEN = "{GITHUB_TOKEN}"  # redteam: canary\n'})
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        # line 5 only mentions the marker in prose: a marker is a comment that starts with it
        self.assertEqual(hits(out), [("tests/fixtures/redteam/app/settings.py", 4, "secret"),
                                     ("tests/fixtures/redteam/app/settings.py", 5, "secret"),
                                     ("tests/test_elsewhere.py", 1, "secret")])

    def test_a_relative_link_to_an_excluded_or_missing_file_is_refused_and_code_is_skipped(self):
        page = "\n".join(["# Links",                                                          # 1
                          "The [old page](docs/page.html) and the ![brief](private/brief.md).",  # 2
                          "A [gone page](docs/nowhere.md) and [outside](../outside.md).",       # 3
                          "[brief]: <private/brief.md>",                                        # 4
                          "```", "[in code](docs/nowhere.md)", "```",                            # 5-7
                          "A `[span](docs/nowhere.md)` and [docs](docs/) and [guide](docs/guide.md#top).",
                          "[web](https://example.com/x.md), [mail](mailto:a@example.invalid), [here](#links)."])
        self.commit({"links.md": page + "\n", "docs/back.md": "The [old page](page.html), the [guide](guide.md).\n"})
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertEqual(hits(out), [("docs/back.md", 1, "link")] + [("links.md", n, "link") for n in (2, 2, 3, 3, 4)])
        self.assertIn("links.md:3: link: a relative link to a missing file: docs/nowhere.md", out)
        self.assertIn("a relative link to a file outside the repository: ../outside.md", out)
        self.assertIn("links.md:2: link: a relative link to an excluded file: docs/page.html", out)
        self.assertIn("docs/back.md:1: link: a relative link to an excluded file: page.html", out)  # from its folder

    def test_a_binary_files_bytes_are_scanned_for_words_and_secrets_in_its_metadata(self):
        png = b"\x89PNG\r\n\x1a\n\0\0\0\x0dIHDR" + b"\0" * 13                     # 29 bytes: an odd offset follows
        self.commit({"img/text.png": png + b"tEXtAuthor\0" + WORD.encode("latin-1") + b"\0",      # Latin-1
                     "img/exif-even.png": png + b"\0" + f"XPAuthor {WORD}".encode("utf-16-le"),  # UTF-16, even
                     "img/exif-odd.png": png + f"XPAuthor {WORD}".encode("utf-16-le"),           # UTF-16, odd
                     "docs/scan.pdf": b"%PDF-1.7\n\0\xfe\xff" + f"Author {WORD}".encode("utf-16-be"),
                     "img/key.bin": png + f"token={GITHUB_TOKEN}\0".encode("ascii"),
                     "img/clean.png": png + b"tEXtSoftware\0an image editor\0" + bytes(range(256)) * 64})
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertEqual(hits(out), [("docs/scan.pdf", 0, "denylist"), ("img/exif-even.png", 0, "denylist"),
                                     ("img/exif-odd.png", 0, "denylist"), ("img/key.bin", 0, "secret"),
                                     ("img/text.png", 0, "denylist")])           # one hit a file, its views agreeing
        self.assertNotIn(WORD.lower(), out.lower())
        self.assertNotIn(GITHUB_TOKEN, out)
        self.assertIn(f"img/text.png: denylist: its bytes hold a denylisted word: {MASKED}", out)
        self.assertIn("img/key.bin: secret: its bytes hold a GitHub token: ghp_********", out)

    def test_a_file_over_5_mb_is_refused(self):
        self.commit({"data/big.bin": b"\0" * (5 * 2**20 + 1), "data/small.bin": b"\0" * 1024})
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertEqual(hits(out), [("data/big.bin", 0, "size")])

    def test_a_refused_export_leaves_the_target_as_it_was(self):
        (self.target / ".git").mkdir(parents=True)
        (self.target / "keep.txt").write_text("still here\n", encoding="utf-8")
        self.commit({"docs/word.md": f"{WORD}\n"})
        self.assertEqual(self.to_target()[0], 1)
        self.assertEqual((self.target / "keep.txt").read_text(encoding="utf-8"), "still here\n")


class DenylistTest(ExportCase):
    def test_the_denylist_is_never_exported_even_when_it_is_tracked(self):
        self.commit({".release-denylist": f"{WORD}\n", "docs/extra/.release-denylist": f"{WORD}\n"},
                    "tracked by mistake")
        code, out, _ = self.export("--target", str(self.target))                 # the default list, at the root
        self.assertEqual(code, 0, out)
        self.assertEqual(self.written(), SHIPPED)

    def test_without_a_denylist_the_export_stops_unless_told_to_skip_it(self):
        code, out, err = self.export("--check")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no denylist at", err)
        code, out, _ = self.export("--check", "--no-denylist")
        self.assertEqual(code, 0, out)
        self.assertIn("denylist: not measured", out)


class UnsafeTargetTest(ExportCase):
    def refused(self, target: Path) -> str:
        code, out, err = self.export("--target", str(target), "--denylist", str(self.deny))
        self.assertEqual((code, out), (2, ""), target)
        return err

    def test_this_repository_a_folder_in_it_or_around_it_is_refused(self):
        for target in (self.repo, self.repo / "docs", self.tmp):
            self.assertIn("is this repository, inside it or around it", self.refused(target))
        self.assertTrue((self.repo / "README.md").is_file())

    def test_another_work_tree_of_this_repository_is_refused(self):
        self.git("worktree", "add", "-q", str(self.tmp / "second"))
        self.assertIn("is a work tree of this repository", self.refused(self.tmp / "second"))
        self.assertTrue((self.tmp / "second" / "README.md").is_file())

    def test_a_folder_that_is_neither_empty_a_clone_nor_an_earlier_export_is_left_alone(self):
        stranger = self.tmp / "someone-elses"
        stranger.mkdir()
        (stranger / "notes.txt").write_text("mine\n", encoding="utf-8")
        self.assertIn("is not empty", self.refused(stranger))
        self.assertEqual((stranger / "notes.txt").read_text(encoding="utf-8"), "mine\n")
        # an earlier export (it holds release/exclude.txt) may be written again
        self.assertEqual(self.to_target()[0], 0)
        (self.target / "extra.txt").write_text("left over\n", encoding="utf-8")
        self.assertEqual(self.to_target()[0], 0)
        self.assertFalse((self.target / "extra.txt").exists())

    def test_an_unknown_revision_or_one_without_the_exclude_list_cannot_run(self):
        self.assertIn("no commit 'no-such-rev'", self.export("--check", "--no-denylist", "--rev", "no-such-rev")[2])
        self.commit({"release/exclude.txt": None})
        code, out, err = self.export("--check", "--no-denylist")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("release/exclude.txt is not in HEAD", err)


class ExcludeRulesTest(unittest.TestCase):
    def test_the_patterns_follow_gitignore(self):
        rules = release_export.compile_rules("# a comment\n\n/blueprint/\ndocs/*.html\n*.log\nbuild/\n!keep.log\n"
                                             "a/**/z.txt\n\\#hash\n")

        def out(path: str) -> bool:
            return release_export.excluded(path, rules)

        self.assertTrue(out("blueprint/run/x.md"))
        self.assertFalse(out("docs/blueprint/x.md"))                               # a leading slash anchors
        self.assertTrue(out("docs/a.html"))
        self.assertFalse(out("docs/sub/a.html") or out("x/docs/a.html"))         # a middle slash anchors too
        self.assertTrue(out("logs/run.log") and out("run.log"))
        self.assertFalse(out("keep.log"))                                          # `!` takes it back in
        self.assertTrue(out("src/build/out.o"))
        self.assertFalse(out("src/build"))                                         # build/ matches folders only
        self.assertTrue(out("a/z.txt") and out("a/b/c/z.txt"))
        self.assertTrue(out("#hash"))
        self.assertFalse(out("README.md"))

    def test_the_shipped_exclude_list_leaves_out_what_the_owner_named_and_ships_the_rest(self):
        rules = release_export.compile_rules((ROOT / "release" / "exclude.txt").read_text(encoding="utf-8"))
        for path in ("blueprint/run-a/AGENTS.md", "evidence/T-004.md", "intake/gnomon-factory-brief.md",
                     "envelopes/T-004/envelope.json", "docs/rihma-v1.html", "docs/m0-log.md",
                     "docs/release-checklist.md", ".release-denylist"):
            self.assertTrue(release_export.excluded(path, rules), path)
        for path in ("decisions/D-0013-name-rihmasto.md", "docs/how-it-works.md", "docs/guides/profiles.md",
                     "README.md", "release/exclude.txt", "tests/fixtures/redteam/clean_app/README.md",
                     "tools/release_export.py", "kernel/evidence_pack.py"):
            self.assertFalse(release_export.excluded(path, rules), path)


if __name__ == "__main__":
    unittest.main()
