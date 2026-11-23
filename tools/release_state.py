#!/usr/bin/env python3
"""release_state: where this repository and the public one stand, as tools/release_sync.py reads it.

Standard library only, no model. It reads the public clone's origin/<branch>, first parents only, and
this repository's history:
- **An export** of a revision R names R, in a trailer `Rihmasto-Export: <full sha>` or in the sync pull
  request's title ("Sync from the development repository at <short sha>"); this repository's history
  holds R; its tree is R's snapshot; and R comes after the revision of the export before it, so each
  revision is exported once and an export never goes back. A merge commit whose second parent is such
  an export, with the same tree, counts as that export.
- **A contribution** is every other public commit, whatever it names. It is imported when a commit of
  this repository's history carries the trailer `Rihmasto-Import: <public sha>`.
Each git log is read with separators that carry a random token, so no commit's text can forge one, and
a record count that differs from git rev-list's stops the sync instead of dropping a commit.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_export as rx  # noqa: E402

EXPORT_KEY = "Rihmasto-Export"
IMPORT_KEY = "Rihmasto-Import"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's empty tree: what a root commit changes from
FULL_SHA = re.compile(r"[0-9a-f]{40}")
SYNC_TITLE = re.compile(r"Sync from the development repository at ([0-9a-f]{12})\b")
PUBLIC_FIELDS = ("%H", "%T", "%P", "%s", "%an <%ae>", f"%(trailers:key={EXPORT_KEY},valueonly)",
                 f"%(trailers:key={IMPORT_KEY},valueonly)")


class Refused(Exception):
    """The sync refuses and has changed nothing: each line says why, or what to do."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__("\n".join(lines))
        self.lines = lines


@dataclass(frozen=True)
class PublicCommit:
    sha: str
    tree: str
    parents: tuple[str, ...]
    subject: str
    author: str
    exports: tuple[str, ...]    # the revisions its Rihmasto-Export trailers name
    imports: tuple[str, ...]    # its Rihmasto-Import trailers, which only this tool writes, and only here

    @property
    def parent(self) -> str:
        """Its first parent, or the empty tree for a root commit."""
        return self.parents[0] if self.parents else EMPTY_TREE

    def __str__(self) -> str:
        return f"{self.sha[:12]} {self.subject} ({self.author})"


@dataclass
class Sync:
    private: Path
    clone: Path
    branch: str
    denylist: Path | None
    trees: dict[str, str] = field(default_factory=dict)  # a private revision: its snapshot's tree

    @property
    def ref(self) -> str:
        return f"refs/remotes/origin/{self.branch}"


@dataclass(frozen=True)
class State:
    head: str                           # the public branch's head
    last_export: PublicCommit | None
    exported: str | None                # the private revision the last export is the snapshot of
    after: list[PublicCommit]           # every public commit after the last export, oldest first
    waiting: list[PublicCommit]         # those this repository has not imported yet


# -- git ---------------------------------------------------------------------------------------

def run(repo: Path, *args: str, data: bytes | None = None,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=False,
                          env=None if env is None else {**os.environ, **env})


def git(repo: Path, *args: str, data: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
    proc = run(repo, *args, data=data, env=env)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        raise rx.ExportError(f"git {args[0]} in {repo}: {detail}")
    return proc.stdout


def text(repo: Path, *args: str, data: bytes | None = None, env: dict[str, str] | None = None) -> str:
    return git(repo, *args, data=data, env=env).decode("utf-8", "replace").strip()


def log_records(repo: Path, fields: tuple[str, ...], *revs: str) -> list[list[str]]:
    """git log's records over ``revs``, each a list of ``fields``. The separators carry a random token, so
    no commit's text can forge one; a count that differs from git rev-list's stops the sync."""
    token = secrets.token_hex(16)
    record, sep = f"\x1e{token}\x1e", f"\x1f{token}\x1f"
    raw = git(repo, "log", f"--format=%x1e{token}%x1e" + f"%x1f{token}%x1f".join(fields), *revs, "--")
    rows = [chunk.rstrip("\n").split(sep) for chunk in raw.decode("utf-8", "replace").split(record)[1:]]
    count = int(text(repo, "rev-list", "--count", *revs, "--"))
    if len(rows) != count or any(len(row) != len(fields) for row in rows):
        raise rx.ExportError(f"git log in {repo} gave {len(rows)} records for {count} commits: the history cannot "
                             "be read safely")
    return rows


def shas(values: str) -> tuple[str, ...]:
    return tuple(v for v in values.lower().split() if FULL_SHA.fullmatch(v))


def holds(sync: Sync, rev: str, ancestor: str) -> bool:
    """Whether ``rev`` of this repository holds ``ancestor``; False for a revision it does not have."""
    return run(sync.private, "merge-base", "--is-ancestor", ancestor, rev).returncode == 0


def listing(paths: Iterable[str], most: int = 5) -> str:
    """The first paths, and how many more."""
    items = list(paths)
    shown = ", ".join(items[:most])
    return f"{shown} and {len(items) - most} more" if len(items) > most else shown


# -- snapshots ---------------------------------------------------------------------------------

def rules_at(repo: Path, rev: str, path: str = rx.EXCLUDE_FILE) -> list[rx.Rule] | None:
    """The gitignore-style rules of the file ``path`` at ``rev``, or None when ``rev`` has no such file."""
    proc = run(repo, "cat-file", "blob", f"{rev}:{path}")
    return rx.compile_rules(proc.stdout.decode("utf-8", "replace")) if proc.returncode == 0 else None


def snapshot_tree(sync: Sync, rev: str) -> str | None:
    """The tree of ``rev``'s public snapshot, written into this repository's objects (no file is read or
    written); None when ``rev`` has no exclude list, so it has no snapshot."""
    if rev not in sync.trees:
        rules = rules_at(sync.private, rev)
        if rules is None:
            return None
        never = rx.never_exported(sync.private, sync.denylist)
        blobs, _ = rx.tree(sync.private, rev)
        entries = "".join(f"{b.mode} {b.sha}\t{b.path}\0" for b in blobs
                          if b.path not in never and not rx.excluded(b.path, rules))
        with tempfile.TemporaryDirectory(prefix="release-sync-") as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            git(sync.private, "update-index", "-z", "--index-info",
                data=entries.encode("utf-8", "surrogateescape"), env=env)
            sync.trees[rev] = text(sync.private, "write-tree", env=env)
    return sync.trees[rev]


def public_only(sync: Sync, tree: str) -> list[str]:
    """The files of the public branch that the snapshot ``tree`` does not hold: what exporting it deletes."""
    public = {b.path for b in rx.tree(sync.clone, sync.ref)[0]}
    return sorted(public - {b.path for b in rx.tree(sync.private, tree)[0]})


# -- what the two histories say ------------------------------------------------------------------

def public_history(sync: Sync) -> list[PublicCommit]:
    """The public branch's first-parent history, newest first."""
    if run(sync.clone, "rev-parse", "--verify", "--quiet", sync.ref).returncode != 0:
        raise rx.ExportError(f"the public clone's origin has no branch {sync.branch!r}")
    return [PublicCommit(sha, tree, tuple(parents.split()), subject, author, shas(exp), shas(imp))
            for sha, tree, parents, subject, author, exp, imp
            in log_records(sync.clone, PUBLIC_FIELDS, "--first-parent", sync.ref)]


def imported(sync: Sync, rev: str = "HEAD") -> set[str]:
    """The public commits that ``rev`` of this repository records as imported."""
    return set(shas(text(sync.private, "log", f"--format=%(trailers:key={IMPORT_KEY},valueonly)", rev, "--")))


def named(sync: Sync, commit: PublicCommit) -> list[str]:
    """The revisions of this repository ``commit`` names as exported: its trailers', then its title's."""
    names = list(commit.exports)
    title = SYNC_TITLE.match(commit.subject)
    if title:
        proc = run(sync.private, "rev-parse", "--verify", "--quiet", f"{title[1]}^{{commit}}")
        if proc.returncode == 0:
            names.append(proc.stdout.decode("ascii").strip())
    return list(dict.fromkeys(names))


def snapshot_of(sync: Sync, commit: PublicCommit, at: str) -> str | None:
    """The revision ``commit`` is the snapshot of, when it names one that ``at`` holds; None otherwise."""
    for rev in named(sync, commit):
        if holds(sync, at, rev) and snapshot_tree(sync, rev) == commit.tree:
            return rev
    return None


def merged_export(sync: Sync, commit: PublicCommit) -> PublicCommit | None:
    """A merge commit's second parent when the merge has its tree: a pull request merged as it was."""
    if len(commit.parents) < 2:
        return None
    raw = text(sync.clone, "log", "-1", f"--format=%T%x00%s%x00%(trailers:key={EXPORT_KEY},valueonly)",
               commit.parents[1])
    tree, subject, names = (raw.split("\0", 2) + ["", ""])[:3]
    if tree != commit.tree:
        return None
    return PublicCommit(commit.parents[1], tree, (), subject, commit.author, shas(names), ())


def candidates(sync: Sync, history: list[PublicCommit], at: str) -> Iterator[tuple[int, str]]:
    """(index, revision) of each public commit, newest first, that is the snapshot of a revision it names."""
    for n, commit in enumerate(history):
        rev = snapshot_of(sync, commit, at)
        second = None if rev else merged_export(sync, commit)
        rev = rev or (snapshot_of(sync, second, at) if second else None)
        if rev:
            yield n, rev


def last_export(sync: Sync, history: list[PublicCommit], at: str) -> tuple[int, str] | None:
    """The newest export: the newest candidate whose revision comes after the next older candidate's. One
    that does not, such as a commit restoring an older snapshot with its trailer copied, is a contribution."""
    found = candidates(sync, history, at)
    current = next(found, None)
    while current is not None:
        older = next(found, None)
        if older is None or (older[1] != current[1] and holds(sync, current[1], older[1])):
            return current
        current = older
    return None


def state(sync: Sync, at: str = "HEAD") -> State:
    """Fetch the clone's origin and read where the two repositories stand."""
    git(sync.clone, "fetch", "--quiet", "origin")
    history = public_history(sync)
    found = last_export(sync, history, at)
    end = found[0] if found else len(history)
    after = list(reversed(history[:end]))
    done = imported(sync, at)
    return State(history[0].sha, history[end] if found else None, found[1] if found else None, after,
                 [c for c in after if c.sha not in done])


def export_note(sync: Sync, commit: PublicCommit, at: str = "HEAD") -> str | None:
    """Why a contribution that names a revision as exported is no export of it; None when it names none."""
    if len(commit.parents) > 1:
        return "a merge commit: main takes squash merges, so this repository reads it as a contribution"
    names = named(sync, commit)
    if not names:
        return None
    rev = names[0]
    if not holds(sync, at, rev):
        return (f"it names {rev[:12]} as exported, which this repository's history does not hold (a branch "
                "rebased or squashed since, or a name copied)")
    if snapshot_tree(sync, rev) != commit.tree:
        return (f"it names {rev[:12]} as exported, but its tree is not that snapshot: a sync pull request merged "
                f"after {sync.branch} moved, or changed before the merge")
    return f"it names {rev[:12]} as exported, which the exports before it have passed: a name copied"
