"""What an assessment reads (kernel/assess.py): one revision of the factory's mirror, from git's objects.

- **Never checked out.** The files of the revision are read with `git ls-tree` and `git cat-file
  --batch` from the project's own `repo.git`, and written as plain files into a temporary folder for the
  rules and the red team's static layer. No filter, hook or LFS helper runs, nothing reaches the
  upstream, and nothing of the repository is executed.
- **Only what can be read safely.** A link is not followed and a submodule is not fetched; a name a
  file system here cannot hold (`..`, a reserved device name, a character Windows refuses) and a file
  over `MAX_FILE` are not written. Each is counted in the notes, so what was not read is said.
- **The system's own files.** What the kernel holds on main (its `.gnomon/` surface and the names in
  `kernel.adopt.KERNEL_HELD`) is the factory's, not the system's: it is left out of the assessment.
- **Evidence.** A finding names a file and a line (the line masked by the red team's masking, so a
  credential never reaches a record) or a measured fact. Dates are commit dates of the mirror, never
  this machine's clock, so the same revision always reads the same.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from kernel.adopt import KERNEL_HELD, _git_read, _opens, _read
from kernel.redteam.masking import evidence as masked
from kernel.redteam.secretscan import test_path

# What an assessment speaks in: the perspectives, in the order a person reads them, and the severities.
PERSPECTIVES = {"cicd": "CI/CD governance", "maintenance": "Maintenance", "security": "Security",
                "compliance": "Compliance", "architecture": "Architecture and operations"}
SEVERITIES = ("critical", "high", "medium", "low", "info")
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_EVIDENCE = 8
CODE = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".java", ".kt", ".cs", ".rb", ".php", ".rs",
        ".scala", ".ex", ".exs", ".swift")
_WINDOWS_BAD = re.compile(r'[<>:"|?*\\\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


def _holdable(rel: str) -> bool:
    """A path every file system the factory runs on can hold as written: no empty, `.` or `..` part, no
    character Windows refuses, no trailing dot or space, no reserved device name."""
    parts = rel.split("/")
    return all(p not in ("", ".", "..") and not _WINDOWS_BAD.search(p) and not p.endswith((" ", "."))
               and p.split(".")[0].lower() not in _RESERVED for p in parts)


def _kernel_held(rel: str) -> bool:
    first = rel.split("/", 1)[0]
    return any(_opens(first, name) for name in KERNEL_HELD)


@dataclass
class _Entry:
    mode: str
    kind: str
    sha: str
    size: int
    path: str


def _tree(bare: Path, revision: str) -> list[_Entry]:
    out = subprocess.run(["git", "ls-tree", "-r", "-z", "-l", "--full-tree", revision], cwd=bare,
                         capture_output=True, stdin=subprocess.DEVNULL, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"git ls-tree failed: {out.stderr.decode('utf-8', errors='replace').strip()[-300:]}")
    entries = []
    for raw in filter(None, out.stdout.split(b"\0")):
        head, _, path = raw.partition(b"\t")
        mode, kind, sha, size = head.decode("ascii", errors="replace").split()
        entries.append(_Entry(mode, kind, sha, int(size) if size.isdigit() else 0,
                              path.decode("utf-8", errors="replace")))
    return entries


def _write(dest: Path, rel: str, data: bytes) -> bool:
    """Write one file under ``dest``, never outside it and never over another (two names one file
    system takes for the same file: the second is not written)."""
    path = dest.joinpath(*rel.split("/"))
    if not path.resolve().is_relative_to(dest.resolve()):
        return False
    try:   # a folder whose name a file already took (two spellings of one name here) is not written either
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except OSError:
        return False
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return True


class _Blobs:
    """`git cat-file --batch` in the mirror: one object at a time, its raw bytes (no filter runs)."""

    def __init__(self, bare: Path) -> None:
        self.proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=bare, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, sha: str) -> bytes | None:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(sha.encode("ascii") + b"\n")
        self.proc.stdin.flush()
        head = self.proc.stdout.readline().split()
        if len(head) != 3:
            return None
        data = self.proc.stdout.read(int(head[2]))
        self.proc.stdout.read(1)
        return data

    def close(self) -> None:
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        if self.proc.stdout is not None:
            self.proc.stdout.close()


@dataclass
class Snapshot:
    files: list[str]
    notes: list[str]


def _skip_reason(e: _Entry, total: int) -> str | None:
    if e.mode == "120000":
        return "a link, not followed"
    if e.kind == "commit":
        return "a submodule, not fetched"
    if not _holdable(e.path):
        return "a name this machine cannot hold"
    if e.size > MAX_FILE:
        return f"over {MAX_FILE // (1024 * 1024)} MB"
    if total + e.size > MAX_TOTAL:
        return "past the assessment's size limit"
    return None


def snapshot(bare: Path, revision: str, dest: Path) -> Snapshot:
    """The revision's files written under ``dest``, read from git's objects; what was not, in notes."""
    dest.mkdir(parents=True, exist_ok=True)
    skipped: dict[str, list[str]] = {}
    files: list[str] = []
    total = 0
    blobs = _Blobs(bare)
    try:
        for e in _tree(bare, revision):
            if _kernel_held(e.path):
                continue
            why = _skip_reason(e, total)
            data = None if why else blobs.read(e.sha)
            if why is None and (data is None or not _write(dest, e.path, data)):
                why = "could not be written here (another file of the same name on this file system)"
            if why:
                skipped.setdefault(why, []).append(e.path)
                continue
            total += e.size
            files.append(e.path)
    finally:
        blobs.close()
    notes = [f"Not read, {why}: {len(paths)} ({', '.join(paths[:5])}{' ...' if len(paths) > 5 else ''})."
             for why, paths in sorted(skipped.items())]
    return Snapshot(sorted(files), notes)


@dataclass
class Repo:
    """The revision being assessed: its files on disk, its mirror, and the project's records."""

    root: Path
    files: list[str]
    bare: Path
    revision: str
    committed: str
    records: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def text(self, rel: str) -> str:
        return _read(self.root, rel)

    def named(self, test: Callable[[str], bool]) -> list[str]:
        return [f for f in self.files if test(f)]

    def first(self, *names: str) -> str | None:
        """The first of ``names`` the repository holds (exact paths, compared without case)."""
        lower = {f.lower(): f for f in self.files}
        return next((lower[n.lower()] for n in names if n.lower() in lower), None)

    def code(self, *, tests: bool = False) -> list[str]:
        return [f for f in self.files if f.lower().endswith(CODE) and (tests or not test_path(f))
                and not f.startswith(("vendor/", "node_modules/", "third_party/"))]

    def find(self, pattern: re.Pattern[str], files: Iterable[str], limit: int = MAX_EVIDENCE, *,
             code_only: bool = False) -> list[dict[str, Any]]:
        """Where ``pattern`` matches, as evidence: file, line and the masked line, at most ``limit``.
        With ``code_only``, a match inside a comment does not count: a comment names, it does not do."""
        out: list[dict[str, Any]] = []
        for rel in files:
            for n, line in enumerate(self.text(rel).splitlines(), 1):
                if any(not (code_only and commented(line, m.start())) for m in pattern.finditer(line)):
                    out.append(at(rel, n, line))
                    if len(out) >= limit:
                        return out
        return out

    def last_change(self, rel: str) -> str | None:
        """The commit date of the last commit up to the revision that changed ``rel``."""
        return _git_read(self.bare, "log", "-1", "--format=%cI", self.revision, "--", rel) or None


_COMMENT_START = re.compile(r"(?:^|\s)(?:#|//|/\*|<!--)|^\s*\*")


def commented(line: str, pos: int) -> bool:
    """Whether ``pos`` of ``line`` sits in a comment: after a `#`, `//`, `/*` or `<!--` that starts the
    line or follows a space, or on a block comment's `*` line. A marker inside a string can mislead it
    toward "commented", which costs a pass, never a false one."""
    return bool(_COMMENT_START.search(line[:pos]))


def at(rel: str, line: int, text: str) -> dict[str, Any]:
    """Evidence at a file and line: the line masked and trimmed."""
    return {"file": rel, "line": line, "text": masked(text)}


def fact(text: str) -> dict[str, Any]:
    """Evidence that is a measured fact rather than a line."""
    return {"fact": text}


def listed(paths: list[str], limit: int = 5) -> str:
    return ", ".join(paths[:limit]) + (f" and {len(paths) - limit} more" if len(paths) > limit else "")


def result(key: str, perspective: str, title: str, verdict: str, *, severity: str | None = None,
           summary: str = "", evidence: Iterable[dict[str, Any]] = (), suggestion: str = "",
           reason: str = "") -> dict[str, Any]:
    """One check's result. A failed check is a finding and carries a severity and a suggested change;
    a check that cannot know says "not measured" and why."""
    if perspective not in PERSPECTIVES:
        raise ValueError(f"unknown perspective {perspective!r}")
    out: dict[str, Any] = {"key": key, "perspective": perspective, "title": title, "verdict": verdict,
                           "severity": severity if verdict == "failed" else None, "summary": summary,
                           "evidence": list(evidence)[:MAX_EVIDENCE], "by": "rule"}
    if verdict == "failed":
        if severity not in SEVERITIES:
            raise ValueError(f"a finding needs a severity, one of {SEVERITIES}")
        out["suggestion"] = suggestion
    if reason:
        out["reason"] = reason
    return out


def suffix(rel: str) -> str:
    return PurePosixPath(rel).suffix.lower()


def base(rel: str) -> str:
    return PurePosixPath(rel).name.lower()


__all__ = ["PERSPECTIVES", "SEVERITIES", "Repo", "Snapshot", "at", "base", "fact", "listed", "result", "snapshot",
           "suffix"]
