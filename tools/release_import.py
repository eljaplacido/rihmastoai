#!/usr/bin/env python3
"""release_import: brings the contributions merged on the public main into this repository, for the
import command of tools/release_sync.py.

Standard library only, no model. Each contribution waiting for import becomes a commit here, oldest
first: the three-way merge of its change (from its first parent to it) into this repository, with its
author and its merged message kept and the trailer `Rihmasto-Import: <public sha>` added. A change that
is here already merges to nothing and is recorded as imported, never applied twice; a change that meets
a different change here is a conflict, and nothing is imported. Before it changes anything, the import
refuses every waiting contribution that:
- touches a path release/exclude.txt leaves out (in any case), or the denylist's own file;
- adds a path that differs only in case from one here, or that is a local file git does not track;
- changes release/exclude.txt, a release tool (tools/release_*.py) or a .gitignore, unless the maintainer
  has read it and names it with --reviewed; even then, one whose exclude list would ship a file left out
  here, or whose .gitignore would stop ignoring a local file, is refused;
- adds a file the export's scans would refuse (a denylisted word, a secret, a file over 5 MB, a link to
  a left-out file);
- is a merge commit (main takes squash merges), or carries a Rihmasto-Import trailer.
The import needs git 2.40 or later (git merge-tree --merge-base).
"""

from __future__ import annotations

import os
import posixpath
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dco_check  # noqa: E402
import release_export as rx  # noqa: E402
from release_state import IMPORT_KEY, PublicCommit, Refused, Sync, export_note, git, listing, rules_at, run, state, text  # noqa: E402

TRAILER_LINE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*:\s")
# What decides which files are tracked here and which ship, and the code that ships them.
GUARDED = re.compile(r"release/exclude\.txt|tools/release_[^/]*\.py|(?:.*/)?\.gitignore", re.IGNORECASE)
DIFF = ("diff", "--binary", "--full-index", "-M", "--no-color", "--no-ext-diff", "--no-textconv",
        "--src-prefix=a/", "--dst-prefix=b/")


@dataclass(frozen=True)
class Change:
    status: str                 # A, M, D, T, or R and C with a score
    old: str
    new: str


class Here:
    """This repository at HEAD and in its work tree, as import checks each contribution against it."""

    def __init__(self, sync: Sync) -> None:
        self.rules = rules_at(sync.private, "HEAD") or []
        self.paths = {b.path for b in rx.tree(sync.private, "HEAD")[0]}            # the left-out ones included
        self.folded = {p.lower(): p for p in rx.with_folders(self.paths)}         # each path and folder
        self.never = {p.lower() for p in rx.never_exported(sync.private, sync.denylist)}
        self.untracked = set(ls_files(sync.private, "--exclude-standard"))
        self.ignored = set(ls_files(sync.private, "--ignored", "--exclude-standard"))
        self.local = {p.lower() for p in self.untracked | self.ignored}


def ls_files(repo: Path, *args: str) -> list[str]:
    """The work tree's files git does not track, as ``args`` select them."""
    return [p for p in git(repo, "ls-files", "-z", "--others", *args).decode("utf-8", "surrogateescape").split("\0")
            if p]


# -- the checks ---------------------------------------------------------------------------------

def changes(sync: Sync, commit: PublicCommit) -> list[Change]:
    """What ``commit`` changes against its first parent, renames detected."""
    raw = git(sync.clone, "diff-tree", "-r", "-z", "-M", "--no-commit-id", "--name-status", commit.parent, commit.sha)
    parts = raw.decode("utf-8", "surrogateescape").split("\0")
    out: list[Change] = []
    i = 0
    while i < len(parts) and parts[i]:
        two = parts[i][0] in "RC"
        out.append(Change(parts[i][0], parts[i + 1], parts[i + 2] if two else parts[i + 1]))
        i += 3 if two else 2
    return out


def scan_written(sync: Sync, commit: PublicCommit, written: list[str], words: list[re.Pattern[str]],
                 private_paths: set[str]) -> list[str]:
    """What the export's scans would refuse in the files ``commit`` adds or changes."""
    blobs, odd = rx.tree(sync.clone, commit.sha)
    by_path = {b.path: b for b in blobs}
    found = [str(hit) for hit in odd if hit.path in written]
    present = [p for p in written if p in by_path]
    contents = rx.read_blobs(sync.clone, [by_path[p].sha for p in present])
    shipped, tracked = rx.with_folders(by_path), rx.with_folders(set(by_path) | private_paths)
    for path in present:
        found += [str(hit) for hit in rx.scan(path, contents[by_path[path].sha], words, shipped, tracked)]
    return found


def left_out(sync: Sync, commit: PublicCommit, touched: set[str], here: Here) -> list[str]:
    """The touched paths the public repository must never hold, by this repository's exclude list or by the
    one the contribution brings; the exclude list matches in any case."""
    rules = [here.rules]
    if rx.EXCLUDE_FILE in touched:
        rules.append(rules_at(sync.clone, commit.sha) or [])
    return [f"touches {path}, which release/exclude.txt keeps out of the public repository"
            for path in sorted(touched) if path.lower() in here.never or any(rx.excluded(path, r) for r in rules)]


def clashes(written: list[str], here: Here) -> list[str]:
    """The written paths that would land on a local file, or differ only in case from a path here: on a disk
    that ignores case, git would file this repository's own files under the contribution's spelling."""
    found: list[str] = []
    for path in written:
        if path.lower() in here.local:
            found.append(f"adds {path}, which is a local file here that git does not track: it would be overwritten")
            continue
        parts = path.split("/")
        for name in ("/".join(parts[:n]) for n in range(1, len(parts) + 1)):
            mine = here.folded.get(name.lower())
            if mine is not None and mine != name:
                found.append(f"adds {path}, whose {name} differs only in case from {mine} here")
                break
    return found


def verdict(path: str, rules: list[rx.Rule]) -> bool | None:
    """What the last rule matching ``path`` or a folder of it says: True leaves it out, False takes it back,
    None when no rule matches."""
    for rule in reversed(rules):
        if rx.excluded(path, [rx.Rule(rule.regex, False, rule.dir_only)]):
            return not rule.negate
    return None


def freed(path: str, old: list[rx.Rule], new: list[rx.Rule]) -> bool:
    """Whether a .gitignore change stops ignoring ``path``: its new rules take it back, or the rule that
    ignored it is gone."""
    before, after = verdict(path, old), verdict(path, new)
    return (after is False and before is not False) or (before is True and after is None)


def shipped(sync: Sync, commit: PublicCommit, here: Here) -> list[str]:
    """The files here, tracked or not yet, that the contribution's exclude list would ship though this
    repository's leaves them out."""
    new = rules_at(sync.clone, commit.sha) or []
    ships = sorted(p for p in here.paths | here.untracked
                   if p.lower() not in here.never and rx.excluded(p, here.rules) and not rx.excluded(p, new))
    return [f"its release/exclude.txt would ship {len(ships)} file(s) this repository leaves out: "
            f"{listing(ships)}"] if ships else []


def unignored(sync: Sync, commit: PublicCommit, path: str, here: Here) -> list[str]:
    """The ignored local files the contribution's .gitignore at ``path`` would stop ignoring."""
    old, new = rules_at(sync.private, "HEAD", path) or [], rules_at(sync.clone, commit.sha, path) or []
    prefix = f"{posixpath.dirname(path)}/" if "/" in path else ""
    loose = sorted(f for f in here.ignored if f.startswith(prefix) and freed(f[len(prefix):], old, new))
    return [f"its {path} would stop ignoring {len(loose)} local file(s), which the next commit could track and "
            f"the next export ship: {listing(loose)}"] if loose else []


def exposed(sync: Sync, commit: PublicCommit, paths: list[str], here: Here) -> list[str]:
    """What a change to the exclude list or a .gitignore would let out: files left out here that the next
    export would ship, and ignored local files the next commit could track."""
    found = shipped(sync, commit, here) if rx.EXCLUDE_FILE in paths else []
    for path in (p for p in paths if posixpath.basename(p).lower() == ".gitignore"):
        found += unignored(sync, commit, path, here)
    return found


def guarded(sync: Sync, commit: PublicCommit, cs: list[Change], here: Here, reviewed: set[str]) -> list[str]:
    """A change to what decides which files are tracked and shipped, or to the code that ships them: never
    imported unread, and never when it would let out a file."""
    paths = sorted({p for c in cs for p in (c.old, c.new) if GUARDED.fullmatch(p)})
    if not paths:
        return []
    found = [] if commit.sha in reviewed else [
        f"changes {', '.join(paths)}, which decide(s) what is tracked here and what ships: read the change, "
        f"then import with --reviewed {commit.sha[:12]}"]
    return found + exposed(sync, commit, paths, here)


def problems(sync: Sync, commit: PublicCommit, words: list[re.Pattern[str]], here: Here,
             reviewed: set[str]) -> list[str]:
    """Why ``commit`` may not be imported: each problem on a line, words masked."""
    found = [f"its message carries a {IMPORT_KEY} trailer, which only this tool writes"] if commit.imports else []
    if len(commit.parents) > 1:
        found.append("a merge commit: its author is whoever merged it, and its message holds no contributor's "
                     "sign-off (main takes squash merges)")
    cs = changes(sync, commit)
    written = sorted({c.new for c in cs if c.status != "D"})
    found += left_out(sync, commit, {p for c in cs for p in (c.old, c.new)}, here)
    found += clashes(written, here) + guarded(sync, commit, cs, here, reviewed)
    if written:
        found += scan_written(sync, commit, written, words, here.paths)
    return [rx.mask_words(f"  {commit.sha[:12]} {commit.subject}: {p}", words) for p in found]


# -- the commits --------------------------------------------------------------------------------

def with_trailer(message: str, line: str) -> str:
    """``message`` with ``line`` added to its trailer block, or as a new last paragraph."""
    body = message.rstrip()
    _, sep, last = body.rpartition("\n\n")
    lines = last.splitlines()
    block = bool(sep and lines) and all(TRAILER_LINE.match(x) or (n and x[:1] in " \t") for n, x in enumerate(lines))
    return f"{body}\n{line}\n" if block else f"{body}\n\n{line}\n"


def authored(sync: Sync, commit: PublicCommit) -> tuple[dict[str, str], bytes, bool]:
    """(the environment that keeps ``commit``'s author and date, its message with the import trailer,
    whether that message carries its author's sign-off)."""
    raw = git(sync.clone, "log", "-1", "--date=raw",
              "--format=%an%x00%ae%x00%ad%x00%(trailers:key=Signed-off-by,valueonly,unfold)%x00%B", commit.sha)
    name, email, date, signoffs, message = raw.decode("utf-8", "replace").split("\0", 4)
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date}
    entry = dco_check.Commit(commit.sha, name, email, commit.subject,
                             tuple(s.strip() for s in signoffs.splitlines() if s.strip()))
    return env, with_trailer(message, f"{IMPORT_KEY}: {commit.sha}").encode("utf-8"), dco_check.problem(entry) is None


def fetch_public(sync: Sync) -> None:
    """Copy the public history's objects into this repository, so the merges can read them: no ref, no
    FETCH_HEAD and no file of the work tree changes."""
    git(sync.private, "-c", "gc.auto=0", "-c", "maintenance.auto=false", "fetch", "--quiet", "--no-tags",
        "--no-write-fetch-head", str(sync.clone), sync.ref)


def merged(sync: Sync, tip: str, commit: PublicCommit) -> tuple[str, list[str]]:
    """(``tip``'s tree with ``commit``'s change merged in three ways, the paths that conflict)."""
    base = commit.parents[0] if commit.parents else text(sync.private, "commit-tree", text(
        sync.private, "mktree", data=b""), "-m", "The empty tree, the base of a root commit")
    proc = run(sync.private, "merge-tree", "--write-tree", "-z", "--name-only", "--no-messages",
               f"--merge-base={base}", tip, commit.sha)
    if proc.returncode not in (0, 1):
        detail = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        raise rx.ExportError(f"git merge-tree in {sync.private} (it needs git 2.40 or later): {detail}")
    tree, *paths = proc.stdout.decode("utf-8", "surrogateescape").split("\0")
    return tree.strip(), list(dict.fromkeys(p for p in paths if p)) if proc.returncode else []


def conflict(sync: Sync, commit: PublicCommit, before: list[PublicCommit], paths: list[str]) -> Refused:
    lines = ["refused: nothing was imported.",
             f"  {commit}: does not apply cleanly here: it meets a different change made here, in {listing(paths)}"]
    note = export_note(sync, commit)
    lines += [f"  ({note})"] if note else []
    lines += ["What to do: merge its change by hand, resolve the conflict, and commit it with its author kept",
              f"(git commit --author) and a message that ends with the trailer {IMPORT_KEY}: {commit.sha}",
              f'  git -C "{sync.clone}" {" ".join(DIFF)} {commit.parent} {commit.sha} > contribution.patch',
              "  git apply --3way contribution.patch",
              "When nothing is left to commit, its change is here already: record it as imported with",
              f'  git commit --allow-empty -m "Record {commit.sha[:12]}, here already" --trailer "{IMPORT_KEY}: '
              f'{commit.sha}"',
              "then run import again for the contributions after it."]
    if before:
        lines.append(f"The {len(before)} before it apply cleanly: import them first with --through {before[-1].sha}.")
    return Refused(lines)


def build_imports(sync: Sync, waiting: list[PublicCommit]) -> tuple[str, list[str]]:
    """Write one commit per contribution on top of HEAD and return the last, with a line on each. Nothing a
    person sees changes: the commits are reachable from no branch yet."""
    fetch_public(sync)
    tip = text(sync.private, "rev-parse", "HEAD")
    report: list[str] = []
    for n, commit in enumerate(waiting):
        tree, conflicts = merged(sync, tip, commit)
        if conflicts:
            raise conflict(sync, commit, waiting[:n], conflicts)
        same = tree == text(sync.private, "rev-parse", f"{tip}^{{tree}}")
        author, message, signed = authored(sync, commit)
        tip = text(sync.private, "commit-tree", tree, "-p", tip, "-F", "-", data=message, env=author)
        how = "signed off by its author" if signed else (
            "no Signed-off-by of its author in the merged message (the DCO check ran on the pull request's commits)")
        report.append(f"  {commit}: " + ("here already, recorded with no change" if same else how))
    return tip, report


def chosen(waiting: list[PublicCommit], names: list[str], flag: str) -> list[PublicCommit]:
    """The waiting contributions ``names`` name, by a prefix of their sha; Refused for a name that is none."""
    out: list[PublicCommit] = []
    for name in names:
        hits = [c for c in waiting if len(name) >= 7 and c.sha.startswith(name.lower())]
        if len(hits) != 1:
            raise Refused([f"refused: {flag} {name} names none of the {len(waiting)} contribution(s) waiting for "
                           "import (a prefix of 7 characters or more)"])
        out += hits
    return out


def import_contributions(sync: Sync, through: str | None, reviewed: list[str]) -> int:
    waiting = state(sync).waiting
    accepted = {c.sha for c in chosen(waiting, reviewed, "--reviewed")}
    if through:
        waiting = waiting[:waiting.index(chosen(waiting, [through], "--through")[0]) + 1]
    if not waiting:
        print("nothing waits for import")
        return 0
    words = rx.load_denylist(sync.denylist) if sync.denylist else []
    here = Here(sync)
    found = [line for commit in waiting for line in problems(sync, commit, words, here, accepted)]
    if found:
        raise Refused(["refused: nothing was imported.", *found,
                       "What to do: bring in by hand what belongs here, in a commit with the contributor as its",
                       f"author and their sign-off, whose message ends with the trailer {IMPORT_KEY}: <public sha>.",
                       "The next export replaces the public tree with this repository's snapshot, so what was left",
                       "out leaves the public main too."])
    tip, report = build_imports(sync, waiting)
    ff = run(sync.private, "merge", "--ff-only", "--quiet", tip)
    if ff.returncode != 0:
        raise Refused(["refused: nothing was imported.", ff.stderr.decode("utf-8", "replace").strip(),
                       "What to do: commit or set aside your own uncommitted changes to the tracked files named above,",
                       "then run import again. Never move an untracked file aside for an import."])
    print(f"imported {len(waiting)} contribution(s), oldest first, each with its author and merged message:")
    print("\n".join(report))
    if sync.denylist is None:
        print("denylist: not measured (--no-denylist)")
    print("next: run the checks, then export")
    return 0
