"""tools/dco_check.py: every commit of a pull request is signed off by its author, the check CI runs on
each pull request; and the repository's contribution files around it (the DCO workflow, CODEOWNERS,
the Dependabot settings, the maintainers' settings and the changelog).

Every check test builds a small repository in a temporary folder (git is needed). The people in it are
made up.
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
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dco_check  # noqa: E402
import release_export  # noqa: E402

CONTRIBUTOR = ("A Contributor", "contributor@example.invalid")
MAINTAINER = ("A Maintainer", "maintainer@example.invalid")


class DcoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dco-check-test-"))
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, capture_output=True)
        for key, value in (("user.name", MAINTAINER[0]), ("user.email", MAINTAINER[1]), ("core.autocrlf", "false"),
                           ("commit.gpgsign", "false")):
            self.git("config", key, value)
        self.base = self.commit("base.txt", "The base", author=MAINTAINER)

    def tearDown(self):
        release_export.remove(self.tmp)                  # git's objects are read-only on Windows

    def git(self, *args: str, env: dict | None = None, data: str | None = None) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True,
                              input=data, env=None if env is None else {**os.environ, **env}).stdout.strip()

    def commit(self, name: str, message: str, author: tuple = CONTRIBUTOR, signoff: str | None = None) -> str:
        """Commit a change to ``name`` as ``author``, with a Signed-off-by trailer when ``signoff`` is given."""
        path = self.repo / name
        path.write_text(path.read_text(encoding="utf-8") + "x\n" if path.exists() else "x\n", encoding="utf-8")
        self.git("add", name)
        text = message + (f"\n\nSigned-off-by: {signoff}" if signoff else "") + "\n"
        env = {"GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1]}
        self.git("commit", "-q", "-F", "-", data=text, env=env)
        return self.git("rev-parse", "HEAD")

    def check(self, base: str | None = None, head: str = "HEAD", opened_by: str | None = None) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        author = ["--pr-author", opened_by] if opened_by else []
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dco_check.main(["--repo", str(self.repo), "--base", base or self.base, "--head", head, *author])
        return code, out.getvalue(), err.getvalue()


class SignOffTest(DcoCase):
    def test_commits_signed_off_by_their_author_pass_with_the_email_in_any_case(self):
        self.commit("a.txt", "Add a", signoff="A Contributor <contributor@example.invalid>")
        self.commit("b.txt", "Add b", signoff="A Contributor <Contributor@Example.INVALID>")
        code, out, err = self.check()
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("DCO: 2 commit(s) checked, every one signed off by its author or exempt", out)

    def test_a_missing_or_mismatched_sign_off_fails_listing_each_commit_and_how_to_fix_it(self):
        good = self.commit("a.txt", "Signed properly", signoff="A Contributor <contributor@example.invalid>")
        missing = self.commit("b.txt", "Not signed")
        other = self.commit("c.txt", "Signed by someone else", signoff="Somebody Else <else@example.invalid>")
        renamed = self.commit("d.txt", "Signed with another name",
                              signoff="A. Contributor <contributor@example.invalid>")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("DCO: 3 of 4 commit(s) are not signed off by their author:", out)
        self.assertNotIn(good[:12], out)
        self.assertIn(f"{missing[:12]} Not signed (by A Contributor <contributor@example.invalid>): "
                      "no Signed-off-by trailer", out)
        self.assertIn(f"{other[:12]} Signed by someone else", out)
        self.assertIn("its Signed-off-by (Somebody Else <else@example.invalid>) is not its author", out)
        self.assertIn(renamed[:12], out)
        self.assertIn(f"git rebase --signoff {self.base[:12]}", out)
        self.assertIn("git push --force-with-lease origin HEAD", out)

    def test_the_fix_names_the_commit_the_branch_starts_from_and_a_push_that_needs_no_upstream(self):
        self.git("checkout", "-q", "-b", "topic")
        self.commit("a.txt", "Not signed")
        self.git("checkout", "-q", "main")
        moved = self.commit("b.txt", "Main moves on", author=MAINTAINER,
                            signoff="A Maintainer <maintainer@example.invalid>")
        code, out, _ = self.check(base=moved, head="topic")            # the pull request's base: main's tip
        self.assertEqual(code, 1, out)
        self.assertIn(f"git rebase --signoff {self.base[:12]}", out)   # where the branch starts: every clone has it
        self.assertNotIn(moved[:12], out)
        self.assertIn("  git push --force-with-lease origin HEAD\n", out)

    def test_a_control_character_in_a_subject_hides_no_commit(self):
        hidden = self.commit("a.txt", "innocent\x01subject")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn(f"{hidden[:12]} innocent\x01subject", out)
        self.assertIn("DCO: 1 of 1 commit(s) are not signed off", out)
        # a commit that forges the separators, were their token known, stops the check instead of hiding
        self.commit("b.txt", "forged\x1f" + "0" * 32 + "\x1fparts",
                    signoff="A Contributor <contributor@example.invalid>")
        with mock.patch.object(dco_check.secrets, "token_hex", return_value="0" * 32):
            code, out, err = self.check()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("the check cannot run safely", err)

    def test_a_sign_off_line_outside_the_trailer_block_does_not_count(self):
        self.commit("a.txt", "Signed in the middle\n\nSigned-off-by: A Contributor <contributor@example.invalid>\n\n"
                             "And then more prose, so the line above is no trailer.")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("no Signed-off-by trailer", out)

    def test_the_project_owner_and_dependabot_need_no_sign_off_in_their_own_pull_requests(self):
        self.commit("a.txt", "The owner's own work", author=("eljaplacido", dco_check.OWNER_EMAIL.upper()))
        code, out, _ = self.check(opened_by="eljaplacido")
        self.assertEqual(code, 0, out)
        self.assertIn("authored by the project owner, who holds the copyright, in a pull request eljaplacido opened",
                      out)
        bump = self.commit("b.txt", "Bump actions/checkout", author=("dependabot[bot]", dco_check.DEPENDABOT_EMAIL))
        code, out, _ = self.check(base=bump + "~1", opened_by="dependabot[bot]")
        self.assertEqual(code, 0, out)
        self.assertIn("authored by dependabot[bot], in a pull request dependabot[bot] opened", out)
        # the exemption is the author's address, not a name anyone can type
        self.commit("c.txt", "Pretends to be the bot", author=("dependabot[bot]", "someone@example.invalid"))
        self.assertEqual(self.check(base=bump, opened_by="dependabot[bot]")[0], 1)

    def test_the_owners_address_exempts_nobody_in_someone_elses_pull_request(self):
        # git lets anyone author a commit with any address: the pull request's author is GitHub's record
        spoof = self.commit("a.txt", "Looks like the owner's", author=("Anyone", dco_check.OWNER_EMAIL))
        for opened_by in ("someone-else", None):
            code, out, _ = self.check(opened_by=opened_by)
            self.assertEqual(code, 1, out)
            self.assertIn(f"{spoof[:12]} Looks like the owner's", out)
            self.assertIn("no Signed-off-by trailer (its author address is exempt only in a pull request eljaplacido "
                          "opened)", out)
            self.assertNotIn("exempt:", out)

    def test_merge_commits_are_not_checked(self):
        self.git("checkout", "-q", "-b", "topic")
        self.commit("a.txt", "On a branch", signoff="A Contributor <contributor@example.invalid>")
        self.git("checkout", "-q", "main")
        self.commit("b.txt", "On main", signoff="A Contributor <contributor@example.invalid>")
        self.git("merge", "-q", "--no-ff", "-m", "Merge the topic, unsigned", "topic")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("DCO: 2 commit(s) checked", out)

    def test_no_commits_pass_and_an_unknown_revision_cannot_run(self):
        self.assertEqual(self.check(head=self.base)[:2], (0, "DCO: no commits to check (merges are not checked)\n"))
        code, out, err = self.check(base="no-such-revision")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no commit 'no-such-revision'", err)


class ContributionFilesTest(unittest.TestCase):
    def test_the_dco_workflow_checks_every_pull_request_with_read_only_access(self):
        text = (ROOT / ".github" / "workflows" / "dco.yml").read_text(encoding="utf-8")
        for needle in ("pull_request:", "types: [opened, synchronize, reopened]", "permissions:\n  contents: read",
                       "  dco:\n    name: DCO sign-off\n    runs-on: ubuntu-latest", "uses: actions/checkout@v4",
                       "fetch-depth: 0", "github.event.pull_request.base.sha", "github.event.pull_request.head.sha",
                       "PR_AUTHOR: ${{ github.event.pull_request.user.login }}",
                       'python tools/dco_check.py --base "$BASE_SHA" --head "$HEAD_SHA" --pr-author "$PR_AUTHOR"'):
            self.assertIn(needle, text)
        self.assertNotIn("\r", text)

    def test_codeowners_names_the_lead_maintainer_and_dependabot_watches_the_actions_weekly(self):
        owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        self.assertIn("* @eljaplacido", [line.strip() for line in owners.splitlines()])
        bot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        for needle in ("version: 2", 'package-ecosystem: "github-actions"', 'directory: "/"', 'interval: "weekly"'):
            self.assertIn(needle, bot)
        self.assertEqual(bot.count("package-ecosystem"), 1)                # no package dependencies to watch

    def test_the_maintainers_page_names_every_required_check_and_the_settings_the_sync_relies_on(self):
        page = " ".join((ROOT / "docs" / "maintainers.md").read_text(encoding="utf-8").split())
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("name: ${{ matrix.os }}, Python ${{ matrix.python }}", ci)  # the names GitHub shows
        systems = re.search(r"os: \[([^\]]+)\]", ci)[1].split(", ")
        versions = re.findall(r'"([0-9.]+)"', re.search(r"python: \[([^\]]+)\]", ci)[1])
        checks = [f"{system}, Python {version}" for system in systems for version in versions] + ["DCO sign-off"]
        self.assertEqual(len(checks), 5)
        for name in checks:
            self.assertIn(f"`{name}`", page)
        for setting in ("squash as the only allowed merge method", "**Default message**", "branches up to date",
                        "the bypass list: the Repository admin role, for pull requests only",
                        "GitHub never lets the author of a pull request approve it",
                        "Automatically delete head branches",
                        "**Discussions** on", "**Private vulnerability reporting** on", "pull requests from forks",
                        "`good first issue`"):
            self.assertIn(setting, page)

    def test_contributing_says_how_a_sign_off_survives_the_squash_and_how_to_add_a_missing_one(self):
        text = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
        self.assertIn("A pull request of one commit merges with that commit's message, your `Signed-off-by` line "
                      "included", text)
        self.assertIn("the maintainer who merges keeps your `Signed-off-by` line at its end", text)
        self.assertNotIn("Its title and description become that commit's message", text)
        self.assertIn("`git rebase --signoff <start>`, where `<start>` is the last commit your branch shares with "
                      "`main`: the DCO check prints it", text)
        self.assertIn("`git push --force-with-lease origin HEAD`", text)
        self.assertIn("Two authors need no sign-off, each only in a pull request its own account opened", text)

    def test_the_changelogs_first_release_covers_the_red_team_published_the_same_day(self):
        log = " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split())
        first = log.split("## [1.0.0.dev0] - 2026-11-23", 1)[1]
        self.assertIn("**Rihmasto's own red team** (`python -m kernel.redteam`, [docs/guides/security.md]", first)
        self.assertIn("the release scan reads a private key as a header with key material", first)


if __name__ == "__main__":
    unittest.main()
