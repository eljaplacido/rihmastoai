"""The repositories the release sync tests share (tests/test_release_sync.py, tests/test_release_import.py).

Every test builds, in a temporary folder, a private repository, a bare repository standing in for the
public one on GitHub and the maintainer's clone of it. A pull request merged on GitHub is played by a
commit written to the bare repository's main with git's plumbing, so a path keeps its case even on a disk
that ignores case: a squash merge writes a new commit with the branch's tree and the message GitHub
proposes. git is needed; the network and gh are not. The planted secret is put together at run time, and
the denylisted word is a made-up one.
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import release_export  # noqa: E402
import release_sync  # noqa: E402

MAINTAINER = ("A Maintainer", "maintainer@example.invalid")
CONTRIBUTOR = ("A Contributor", "contributor@example.invalid")
SIGNED = f"Signed-off-by: {CONTRIBUTOR[0]} <{CONTRIBUTOR[1]}>"
WORD = "Zorbalux"                                   # the made-up name on the test denylist
GITHUB_TOKEN = "ghp_" + "Rel3aseSyncTok3n" + "1234567890" * 2 + "abcd"
PNG = b"\x89PNG\r\n\x1a\n\0\0\0\x0dIHDR" + bytes(range(256))
OLD_TOOL = "".join(f"print('step {n}')\n" for n in range(12))
BASE = {
    "README.md": "# Demo\n\nRead the [guide](docs/guide.md).\n",
    "docs/guide.md": "# Guide\n\nline one\nline two\nline three\n",
    "docs/notes.md": "Notes to delete.\n",
    "kernel/app.py": "def answer():\n    return 41\n",
    "tools/old.py": OLD_TOOL,
    "img/logo.png": PNG,
    "intake/brief.md": "The private brief.\n",
    "blueprint/run.log": "a private run\n",
    "release/exclude.txt": "/intake/\n/blueprint/\n.release-denylist\n",
}
PUBLIC = set(BASE) - {"intake/brief.md", "blueprint/run.log"}
# Every git the tests and the tool start reads these settings, whatever the machine's own are.
GIT_CONFIG = {"user.name": MAINTAINER[0], "user.email": MAINTAINER[1], "core.autocrlf": "false",
              "commit.gpgsign": "false", "init.defaultBranch": "main"}


def git(repo: Path, *args: str, data: str | bytes | None = None, env: dict | None = None) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    proc = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, input=raw,
                          env=None if env is None else {**os.environ, **env})
    return proc.stdout.decode("utf-8", "replace").strip()


def as_author(person: tuple) -> dict:
    return {"GIT_AUTHOR_NAME": person[0], "GIT_AUTHOR_EMAIL": person[1]}


def change(repo: Path, files: dict, message: str, author: tuple | None = None) -> str:
    """Commit ``files`` (None deletes one) in the work tree of ``repo``, as ``author`` when given."""
    for rel, content in files.items():
        path = repo / rel
        if content is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-F", "-", data=message + "\n", env=as_author(author) if author else None)
    return git(repo, "rev-parse", "HEAD")


def plumb(repo: Path, parents: list, files: dict, message: str, author: tuple, base: str | None = None) -> str:
    """A commit of ``base``'s tree (the first parent's by default) with ``files`` written (None deletes one),
    made without a work tree, so every path keeps its case."""
    with tempfile.TemporaryDirectory(prefix="sync-index-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", base or parents[0], env=env)
        for rel, content in files.items():
            # an entry of mode 0 removes the path; --index-info needs no work tree, so a bare repository will do
            blob = "0" * 40 if content is None else git(repo, "hash-object", "-w", "--stdin", data=content)
            entry = f"0 {blob}" if content is None else f"100644 {blob}"
            git(repo, "update-index", "--index-info", data=f"{entry}\t{rel}\n", env=env)
        tree = git(repo, "write-tree", env=env)
    links = [arg for parent in parents for arg in ("-p", parent)]
    return git(repo, "commit-tree", tree, *links, "-F", "-", data=message + "\n", env=as_author(author))


def build_repositories(tmp: Path) -> str:
    """The private repository, the public one and the maintainer's clone, as release_sync first finds
    them; the sha of the one public commit."""
    (tmp / "denylist.txt").write_text(f"# names that never ship\n{WORD}\n", encoding="utf-8")
    private, origin, public = tmp / "private", tmp / "origin.git", tmp / "public"
    git(tmp, "init", "-q", str(private))
    change(private, BASE, "The first version")
    git(tmp, "init", "-q", "--bare", str(origin))
    git(tmp, "clone", "-q", str(origin), str(public))
    git(public, "symbolic-ref", "HEAD", "refs/heads/main")
    # the first public snapshot, made as the ones before release_sync were: an export, then a plain commit
    with contextlib.redirect_stdout(io.StringIO()):
        release_export.main(["--repo", str(private), "--target", str(public), "--denylist", str(tmp / "denylist.txt")])
    first = change(public, {}, "The first public snapshot")
    git(public, "push", "-q", "origin", "main")
    # recorded once as imported (docs/maintainers.md, "Once: record the earlier snapshots")
    git(private, "commit", "-q", "--allow-empty", "-m", "Record the public history", "-m", f"Rihmasto-Import: {first}")
    return first


def blocks(*levels: int) -> str:
    """A file of identical blocks but for their levels: a patch's context matches at every block."""
    return "".join(f"[block]\nlevel = {level}\n\n" for level in levels)


class SyncCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {"GIT_CONFIG_COUNT": str(len(GIT_CONFIG))}
        for n, (key, value) in enumerate(GIT_CONFIG.items()):
            env |= {f"GIT_CONFIG_KEY_{n}": key, f"GIT_CONFIG_VALUE_{n}": value}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.template = Path(tempfile.mkdtemp(prefix="release-sync-template-"))
        cls.addClassCleanup(release_export.remove, cls.template)  # git's objects are read-only on Windows
        cls.first = build_repositories(cls.template)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="release-sync-test-"))
        self.addCleanup(release_export.remove, self.tmp)
        for entry in self.template.iterdir():
            (shutil.copytree if entry.is_dir() else shutil.copy2)(entry, self.tmp / entry.name)
        self.private, self.origin, self.public = self.tmp / "private", self.tmp / "origin.git", self.tmp / "public"
        self.deny = self.tmp / "denylist.txt"
        git(self.public, "remote", "set-url", "origin", str(self.origin))
        self.pulls = 0

    # -- the public side ---------------------------------------------------------------------------

    def push_main(self, commit: str) -> str:
        """Make ``commit`` the public main, as a merge on GitHub (or a force-push) would."""
        git(self.origin, "update-ref", "refs/heads/main", commit)
        return commit

    def contribute(self, files: dict, subject: str, trailers: str = SIGNED, message: str | None = None) -> str:
        """A contributor's pull request of one commit, signed off and squash-merged into the public main
        with GitHub's default message: that commit's message."""
        main = git(self.origin, "rev-parse", "main")
        text = message or (f"{subject}\n\n{trailers}" if trailers else subject)
        return self.push_main(plumb(self.origin, [main], files, text, CONTRIBUTOR))

    def merge_pr(self, branch: str, title_only: bool = False) -> str:
        """Squash-merge a branch of the maintainer's clone into the public main: a new commit with the branch's
        tree and the message GitHub proposes, or with the pull request's title alone."""
        self.pulls += 1
        git(self.public, "fetch", "-q", "origin")
        message = git(self.public, "log", "-1", "--format=%B", branch)
        if title_only:
            message = f"{message.splitlines()[0]} (#{self.pulls})"
        tree = git(self.public, "rev-parse", f"{branch}^{{tree}}")
        squash = git(self.public, "commit-tree", tree, "-p", "origin/main", "-F", "-", data=message + "\n")
        git(self.public, "push", "-q", "origin", f"{squash}:refs/heads/main")
        return squash

    def merge_stale(self, branch: str) -> str:
        """Squash-merge a branch made before the public main moved: GitHub merges the two in three ways."""
        git(self.public, "fetch", "-q", "origin")
        tree = git(self.public, "merge-tree", "--write-tree", "origin/main", branch).splitlines()[0]
        message = git(self.public, "log", "-1", "--format=%B", branch)
        squash = git(self.public, "commit-tree", tree, "-p", "origin/main", "-F", "-", data=message + "\n")
        git(self.public, "push", "-q", "origin", f"{squash}:refs/heads/main")
        return squash

    # -- the private side --------------------------------------------------------------------------

    def change(self, repo: Path, files: dict, message: str, author: tuple | None = None) -> str:
        return change(repo, files, message, author)

    def sync(self, command: str, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = release_sync.main([command, "--public", str(self.public), "--repo", str(self.private),
                                      "--denylist", str(self.deny), *argv])
        return code, out.getvalue(), err.getvalue()

    def head(self) -> str:
        return git(self.private, "rev-parse", "HEAD")

    def export_and_merge(self, files: dict | None = None) -> str:
        """Commit a new version here (and ``files``), export it and squash-merge its pull request; the
        revision exported."""
        self.versions = getattr(self, "versions", 0) + 1
        rev = self.change(self.private, {"VERSION": f"{self.versions}\n", **(files or {})}, f"Version {self.versions}")
        code, out, err = self.sync("export")
        self.assertEqual((code, err), (0, ""), out)
        self.merge_pr(f"sync/{rev[:12]}")
        return rev

    def files_at(self, repo: Path, rev: str) -> set:
        return set(git(repo, "ls-tree", "-r", "--name-only", rev).splitlines())

    def read(self, rel: str) -> str:
        return (self.private / rel).read_text(encoding="utf-8")


def release_sync_main(*argv: str) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = release_sync.main(list(argv))
    return code, out.getvalue(), err.getvalue()
