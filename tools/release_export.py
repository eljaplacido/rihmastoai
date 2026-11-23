#!/usr/bin/env python3
"""release_export: a scrubbed snapshot of a git revision, for the public repository.

Standard library only, no model. It reads the tree of a revision (default HEAD), leaves out what
`release/exclude.txt` in that tree names, scans the rest and writes it into a target folder:

    python tools/release_export.py --target ../public-clone [--rev HEAD] [--denylist FILE]
    python tools/release_export.py --check [--rev HEAD] [--denylist FILE]

It refuses (exit 1, nothing written, every hit listed with its file and line) a snapshot holding:
- a denylisted word (one a line, `#` comments skipped, any case, where no letter or digit adjoins it),
  masked. The default list, `.release-denylist` at the repository root, is never exported;
- a secret-like string, masked: a private key block, an AWS access key id, a GitHub token, an `sk-` key
  (OpenAI, Anthropic, OpenRouter, opencode), a Slack token or webhook, or a random literal of 20 characters
  or more assigned to an api_key-like name. Placeholders are not secrets. A planted test value is allowed
  only in tests/fixtures/redteam/, on a line whose comment starts with `redteam: canary` or
  `seeded: RT-SECRET-...`, as those fixtures mark them;
- a relative Markdown link to an excluded or missing file;
- a file over 5 MB, an entry that is not a plain file, or a path that cannot be written safely.
A binary file's path is scanned for words and its bytes for words and secrets, read as Latin-1, UTF-8 and
UTF-16 text, where metadata such as a PNG's tEXt or EXIF is written; compressed bytes are not inflated.

Writing empties the target but its `.git` (never touched), so deletions carry over. The target must be
missing, empty, a work tree of another repository or an earlier export (it holds release/exclude.txt).
Exit codes: 0 clean (and written, unless --check); 1 refused; 2 the export cannot run (an unknown
revision, no exclude list or denylist, a target that may not be written).
"""

from __future__ import annotations

import argparse
import os
import posixpath
import re
import stat
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_FILE = "release/exclude.txt"
DENYLIST_NAME = ".release-denylist"
MAX_BYTES = 5 * 1024 * 1024
CANARY_DIR = "tests/fixtures/redteam/"
REGULAR_MODES = ("100644", "100755")
REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: a junction or a link, on Windows

# Each secret's pattern; group 1, when there is one, is the value that must look like a real secret.
SECRETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a private key block", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("an AWS access key id", re.compile(r"(?<![A-Z0-9])((?:AKIA|ASIA)[A-Z0-9]{16})(?![A-Z0-9])")),
    ("a GitHub token", re.compile(r"(?<![A-Za-z0-9_])(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("an sk- API key", re.compile(r"(?<![A-Za-z0-9_-])(sk-[A-Za-z0-9_-]{20,})")),
    ("a Slack token", re.compile(r"(?<![A-Za-z0-9])(xox[abposr]-[A-Za-z0-9-]{10,})")),
    ("a Slack webhook", re.compile(r"hooks\.slack\.com/services/(T[A-Za-z0-9_]+/B[A-Za-z0-9_]+/[A-Za-z0-9_]+)")),
    ("an api key literal", re.compile(
        r"(?i)(?<![a-z0-9])(?:api[_-]?(?:key|secret|token)|secret[_-]?key|access[_-]?token|auth[_-]?token"
        r"|client[_-]?secret)[\"']?\s*[:=]\s*[\"']([^\"'\s]{20,})[\"']")),
)
PLACEHOLDERS = ("xxxx", "example", "your", "placeholder", "changeme", "redacted", "dummy", "fake", "sample",
                "<", "${", "{{", "...")
ENV_NAME = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
# How tests/fixtures/redteam marks a planted secret: a comment holding the marker.
ALLOW_MARKER = re.compile(r"(?i)(?:#|//|/\*|<!--|--|;)\s*(?:redteam:\s*canary\b|seeded:\s*RT-SECRET-[A-Z]+)")

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(<[^>\n]*>|[^)\s]+)")
REFERENCE_LINK = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*(<[^>\n]*>|\S+)")
CODE_SPAN = re.compile(r"(`+).*?\1")
EXTERNAL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")


class ExportError(RuntimeError):
    """The export cannot run: an unknown revision, no exclude list or denylist, an unsafe target."""


@dataclass(frozen=True)
class Hit:
    """One reason the snapshot is refused. Line 0 is the file as a whole: its path, size or kind."""

    path: str
    line: int
    kind: str
    detail: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.kind}: {self.detail}"


@dataclass(frozen=True)
class Blob:
    path: str
    mode: str
    sha: str


@dataclass(frozen=True)
class Rule:
    regex: re.Pattern[str]
    negate: bool
    dir_only: bool


@dataclass
class Snapshot:
    commit: str
    tracked: int
    files: dict[str, tuple[bytes, str]] = field(default_factory=dict)  # path: (content, git mode)
    excluded: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    words: list[re.Pattern[str]] = field(default_factory=list)  # the denylist, to mask what is printed


# -- git ---------------------------------------------------------------------------------------

def git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        raise ExportError(f"git {args[0]}: {detail}")
    return proc.stdout


def tree(repo: Path, commit: str) -> tuple[list[Blob], list[Hit]]:
    """Every plain file of ``commit``, and a hit for each entry that is not one (a link, a submodule)."""
    blobs: list[Blob] = []
    odd: list[Hit] = []
    for record in git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        meta, _, raw = record.partition(b"\t")
        mode, kind, sha = meta.decode("ascii").split()
        path = raw.decode("utf-8", "surrogateescape")
        if kind == "blob" and mode in REGULAR_MODES:
            blobs.append(Blob(path, mode, sha))
        else:
            what = "a symbolic link" if mode == "120000" else f"a {kind} entry"
            odd.append(Hit(path, 0, "tree", f"{what} is not exported"))
    return blobs, odd


def read_blobs(repo: Path, shas: Iterable[str]) -> dict[str, bytes]:
    """The content of each blob, read in one `git cat-file --batch`."""
    wanted = sorted(set(shas))
    out = git(repo, "cat-file", "--batch", data="".join(f"{sha}\n" for sha in wanted).encode("ascii"))
    contents: dict[str, bytes] = {}
    pos = 0
    for sha in wanted:
        end = out.index(b"\n", pos)
        header = out[pos:end].split()
        if len(header) != 3:
            raise ExportError(f"git cat-file: no blob {sha}")
        size = int(header[2])
        contents[sha] = out[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
    return contents


def common_dir(path: Path) -> Path | None:
    """The git folder a work tree shares with its other work trees, or None when it is not one."""
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-common-dir"], capture_output=True,
                          text=True, check=False)
    return (path / proc.stdout.strip()).resolve() if proc.returncode == 0 else None


# -- the exclude list -------------------------------------------------------------------------

def _glob(pattern: str) -> str:
    """A gitignore glob as a regular expression: `*` and `?` stay within a folder, `**` crosses folders."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i) and (i == 0 or pattern[i - 1] == "/"):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c in "*?":
            out.append("[^/]*" if c == "*" else "[^/]")
            i += 1
        elif c == "[" and (close := pattern.find("]", i + 2)) != -1:
            body = pattern[i + 1:close]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body) + "]")
            i = close + 1
        else:
            escaped = c == "\\" and i + 1 < len(pattern)
            out.append(re.escape(pattern[i + 1] if escaped else c))
            i += 2 if escaped else 1
    return "".join(out)


def compile_rule(line: str) -> Rule | None:
    """One line of the exclude list as a rule, or None for a blank line or a comment."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    negate = text.startswith("!")
    text = text[1:] if negate else text
    dir_only = text.endswith("/")
    text = text.rstrip("/")
    anchored = "/" in text
    prefix = "" if anchored else "(?:.*/)?"
    return Rule(re.compile(prefix + _glob(text.lstrip("/")) + r"\Z"), negate, dir_only)


def compile_rules(text: str) -> list[Rule]:
    return [rule for rule in map(compile_rule, text.splitlines()) if rule is not None]


def excluded(path: str, rules: list[Rule]) -> bool:
    """Whether the rules leave ``path`` out: the last rule that matches it or one of its folders decides."""
    parts = path.split("/")
    folders = ["/".join(parts[:n]) for n in range(1, len(parts))]
    out = False
    for rule in rules:
        names = folders if rule.dir_only else [*folders, path]
        if any(rule.regex.match(name) for name in names):
            out = not rule.negate
    return out


# -- the scans --------------------------------------------------------------------------------

def load_denylist(path: Path) -> list[re.Pattern[str]]:
    """The denylist's words as patterns; the words themselves are never printed."""
    words = [w.strip() for w in path.read_text(encoding="utf-8-sig").splitlines()]
    return [re.compile(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])", re.IGNORECASE)
            for w in words if w and not w.startswith("#")]


def mask_word(word: str) -> str:
    return word[:1] + "*" * max(len(word) - 1, 3)


def mask_secret(value: str) -> str:
    return value[:min(4, len(value) // 6)] + "*" * 8


def mask_words(text: str, words: list[re.Pattern[str]]) -> str:
    """``text`` with every denylisted word masked: a hit's path or link target may hold one too."""
    for word in words:
        text = word.sub(lambda m: mask_word(m.group(0)), text)
    return text


def plausible(value: str) -> bool:
    """Whether a value looks like a real secret, not a placeholder, an environment variable's name or a slug."""
    low = value.lower()
    if any(p in low for p in PLACEHOLDERS) or ENV_NAME.fullmatch(value):
        return False
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value) and len(set(value)) >= 8


def denylist_hits(path: str, lines: list[str], words: list[re.Pattern[str]]) -> list[Hit]:
    """Each denylisted word in the file's path (line 0) and in its lines."""
    hits: list[Hit] = []
    for n, line in enumerate([path, *lines]):
        for word in words:
            where = "its path holds " if n == 0 else ""
            hits += [Hit(path, n, "denylist", f"{where}a denylisted word: {mask_word(m.group(0))}")
                     for m in word.finditer(line)]
    return hits


def secret_hits(path: str, lines: list[str]) -> list[Hit]:
    """Each secret-like string, but on a marked line of the red-team fixtures."""
    may_plant = path.startswith(CANARY_DIR)
    hits: list[Hit] = []
    for n, line in enumerate(lines, 1):
        if may_plant and ALLOW_MARKER.search(line):
            continue
        for kind, pattern in SECRETS:
            hits += [Hit(path, n, "secret", f"{kind}: {mask_secret(m.group(1))}" if pattern.groups else kind)
                     for m in pattern.finditer(line) if not pattern.groups or plausible(m.group(1))]
    return hits


def markdown_targets(lines: list[str]) -> Iterator[tuple[int, str]]:
    """(line, target) of each Markdown link outside fenced code and code spans."""
    fence: str | None = None
    for n, line in enumerate(lines, 1):
        m = FENCE.match(line)
        if m and (fence is None or (m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence))):
            fence = None if fence else m.group(1)
            continue
        if fence:
            continue
        text = CODE_SPAN.sub("", line)
        for target in (*INLINE_LINK.findall(text), *REFERENCE_LINK.findall(text)):
            yield n, target.strip("<>")


def resolve_link(source: str, target: str) -> str | None:
    """The repository path a relative link points at ("" is the root), or None when it names no file."""
    clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not clean:
        return None
    base = "" if clean.startswith("/") else posixpath.dirname(source)
    joined = posixpath.normpath(posixpath.join(base, clean.lstrip("/")))
    return "" if joined == "." else joined


def link_hits(path: str, lines: list[str], shipped: set[str], tracked: set[str]) -> list[Hit]:
    """Each relative link to a file or folder the snapshot does not hold."""
    hits: list[Hit] = []
    for n, target in markdown_targets(lines):
        if EXTERNAL.match(target) or target.startswith("#"):
            continue
        resolved = resolve_link(path, target)
        if resolved is None or resolved in shipped:
            continue
        state = ("an excluded file" if resolved in tracked else
                 "a file outside the repository" if resolved.startswith("..") else "a missing file")
        hits.append(Hit(path, n, "link", f"a relative link to {state}: {target}"))
    return hits


def unsafe_path(path: str) -> bool:
    """A path that could escape the target or cannot be written on every system."""
    parts = path.split("/")
    return (path.startswith("/") or parts[0] == ".git" or any(p in ("", ".", "..") for p in parts)
            or any(":" in p or "\\" in p for p in parts))


def binary_texts(data: bytes) -> tuple[str, ...]:
    """A binary file's bytes as Latin-1, UTF-8 and UTF-16 text; UTF-16 at both offsets reads either byte order."""
    return (data.decode("latin-1"), data.decode("utf-8", "replace"),
            *((data[start:] + b"\0").decode("utf-16-le", "replace") for start in (0, 1)))


def scan(path: str, data: bytes, words: list[re.Pattern[str]], shipped: set[str], tracked: set[str]) -> list[Hit]:
    """Every hit in one shipped file. A binary file's path and bytes are scanned; its hits are on line 0."""
    hits: list[Hit] = []
    if len(data) > MAX_BYTES:
        hits.append(Hit(path, 0, "size", f"{len(data)} bytes, over the {MAX_BYTES // 2**20} MB limit"))
    if unsafe_path(path):
        hits.append(Hit(path, 0, "path", "a path that cannot be written safely"))
    if b"\0" in data[:8192]:
        lines = [line for text in binary_texts(data) for line in text.splitlines()]
        inside = {Hit(path, 0, h.kind, f"its bytes hold {h.detail}")
                  for h in denylist_hits(path, lines, words) + secret_hits(path, lines) if h.line}
        return hits + denylist_hits(path, [], words) + sorted(inside, key=str)
    lines = data.decode("utf-8", "replace").splitlines()
    hits += denylist_hits(path, lines, words) + secret_hits(path, lines)
    if path.lower().endswith((".md", ".markdown")):
        hits += link_hits(path, lines, shipped, tracked)
    return hits


# -- the snapshot -----------------------------------------------------------------------------

def with_folders(paths: Iterable[str]) -> set[str]:
    """The paths, every folder that holds one, and the root ("")."""
    return {""} | {"/".join(parts[:n]) for parts in (p.split("/") for p in paths) for n in range(1, len(parts) + 1)}


def never_exported(repo: Path, denylist: Path | None) -> set[str]:
    """The denylist's own paths: the default name at the root, and the given file when it is in the repository."""
    out = {DENYLIST_NAME}
    if denylist is not None and repo.resolve() in denylist.resolve().parents:
        out.add(denylist.resolve().relative_to(repo.resolve()).as_posix())
    return out


def build(repo: Path, rev: str, denylist: Path | None) -> Snapshot:
    """Read ``rev``, leave out what its exclude list names, and scan the rest."""
    try:
        commit = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").decode("ascii").strip()
    except ExportError:
        raise ExportError(f"no commit {rev!r} in {repo}") from None
    blobs, odd = tree(repo, commit)
    by_path = {b.path: b for b in blobs}
    if EXCLUDE_FILE not in by_path:
        raise ExportError(f"{EXCLUDE_FILE} is not in {rev}: it names what the public repository leaves out")
    rules = compile_rules(read_blobs(repo, [by_path[EXCLUDE_FILE].sha])[by_path[EXCLUDE_FILE].sha].decode("utf-8"))
    never = never_exported(repo, denylist)
    snap = Snapshot(commit, len(blobs) + len(odd), hits=odd)
    shipped = [b for b in blobs if not (b.path in never or excluded(b.path, rules))]
    snap.excluded = sorted(set(by_path) - {b.path for b in shipped})
    contents = read_blobs(repo, [b.sha for b in shipped])
    snap.words = load_denylist(denylist) if denylist is not None else []
    shipped_paths, tracked_paths = with_folders(b.path for b in shipped), with_folders(by_path)
    for b in shipped:
        snap.files[b.path] = (contents[b.sha], b.mode)
        snap.hits += scan(b.path, contents[b.sha], snap.words, shipped_paths, tracked_paths)
    return snap


# -- the target -------------------------------------------------------------------------------

def check_target(target: Path, repo: Path) -> None:
    """Refuse a target the export may not empty: this repository, a folder around it, a stranger's folder."""
    t, r = target.resolve(), repo.resolve()
    if t == r or r in t.parents or t in r.parents:
        raise ExportError(f"the target {target} is this repository, inside it or around it")
    if t.exists() and not t.is_dir():
        raise ExportError(f"the target {target} is not a folder")
    names = {entry.name for entry in t.iterdir()} if t.is_dir() else set()
    if ".git" in names and common_dir(t) == common_dir(r):
        raise ExportError(f"the target {target} is a work tree of this repository")
    if names and ".git" not in names and not (t / EXCLUDE_FILE).is_file():
        raise ExportError(f"the target {target} is not empty, and is neither a git work tree nor an earlier "
                          "export: nothing is removed from it")


def remove(path: Path) -> None:
    """Remove a file or a folder and what it holds; a link or junction is removed, never followed."""
    st = path.lstat()
    if stat.S_ISDIR(st.st_mode):
        if not getattr(st, "st_file_attributes", 0) & REPARSE_POINT:
            for child in path.iterdir():
                remove(child)
        path.rmdir()
        return
    if not st.st_mode & stat.S_IWRITE:  # a read-only file, which Windows will not delete (a link never is)
        path.chmod(stat.S_IWRITE)
    path.unlink()


def write_snapshot(target: Path, files: dict[str, tuple[bytes, str]]) -> None:
    """Empty the target but its .git, then write every file of the snapshot."""
    target.mkdir(parents=True, exist_ok=True)
    for entry in target.iterdir():
        if entry.name != ".git":
            remove(entry)
    for rel, (data, mode) in sorted(files.items()):
        dest = target.joinpath(*rel.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        if mode == "100755" and os.name != "nt":
            dest.chmod(dest.stat().st_mode | 0o111)


# -- the command line -------------------------------------------------------------------------

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python tools/release_export.py",
                                 description="Export a scrubbed snapshot of a revision for the public repository.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--target", type=Path, help="the folder to write the snapshot into (its .git is kept)")
    mode.add_argument("--check", action="store_true", help="run the scans and write nothing")
    ap.add_argument("--rev", default="HEAD", help="the revision to export (default: HEAD)")
    ap.add_argument("--repo", type=Path, default=ROOT, help="the repository (default: this checkout)")
    deny = ap.add_mutually_exclusive_group()
    deny.add_argument("--denylist", type=Path, help=f"the denylist (default: {DENYLIST_NAME} at the repository root)")
    deny.add_argument("--no-denylist", action="store_true",
                      help="skip the denylist scan; the report says it was not measured")
    return ap.parse_args(argv)


def denylist_of(args: argparse.Namespace, repo: Path) -> Path | None:
    path: Path | None = None if args.no_denylist else args.denylist or repo / DENYLIST_NAME
    if path is not None and not path.is_file():
        raise ExportError(f"no denylist at {path}: pass --denylist FILE, or --no-denylist to skip that scan")
    return path


def report(snap: Snapshot, denylist: Path | None) -> None:
    for hit in sorted(snap.hits, key=lambda h: (h.path, h.line, h.kind, h.detail)):
        print(mask_words(str(hit), snap.words))
    size = sum(len(data) for data, _ in snap.files.values())
    print(f"{snap.commit[:12]}: {snap.tracked} entries, {len(snap.excluded)} excluded, "
          f"{len(snap.files)} files in the snapshot ({size} bytes)")
    if denylist is None:
        print("denylist: not measured (--no-denylist)")
    if snap.hits:
        print(f"refused: {len(snap.hits)} problem(s) above; nothing is written until they are fixed")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo = Path(git(args.repo, "rev-parse", "--show-toplevel").decode("utf-8").strip())
        denylist = denylist_of(args, repo)
        if args.target is not None:
            check_target(args.target, repo)
        snap = build(repo, args.rev, denylist)
    except ExportError as exc:
        print(f"release_export: {exc}", file=sys.stderr)
        return 2
    report(snap, denylist)
    if snap.hits:
        return 1
    if args.target is not None:
        write_snapshot(args.target, snap.files)
        print(f"written to {args.target}: the snapshot of {snap.commit[:12]} (its .git untouched)")
    else:
        print("clean: --check wrote nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
