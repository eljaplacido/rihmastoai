"""Which files a static scan reads, and how: nothing outside the target, nothing skipped unsaid.

- **Inside the target only.** A symbolic link, a Windows junction, or any file whose real path is
  outside the folder scanned is not read, and is listed: content from outside the tree would
  otherwise be reported under an in-tree name.
- **Skipped folders are said.** Version-control and tool caches (`.git`, `__pycache__`, `.tox`,
  ...) and dependency folders (`node_modules`) are not read; a folder named like a virtual
  environment (`venv`, `.venv`) is skipped only when it is one (it holds `pyvenv.cfg`). Every
  skipped folder is listed with its file count, so a product package that happens to carry such a
  name cannot drop out of the scan unseen. Paths a person excludes (`--exclude`) are listed too.
- **Python is read as Python reads it.** A source-encoding declaration (`# coding: utf-7`) is
  honoured, as CPython honours it on import, so code hidden in a comment by the encoding is seen;
  lines are mapped back to the file's own lines for the report.
- **Long Windows paths** (over the 260-character limit) are read through the `\\\\?\\` prefix, so
  where a repository is checked out does not change what is scanned.
"""

from __future__ import annotations

import fnmatch
import io
import os
import tokenize
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

TOOL_DIRS = frozenset({".git", ".hg", ".svn", "__pycache__", ".tox", ".nox", ".mypy_cache", ".ruff_cache",
                       ".pytest_cache", ".eggs"})
DEPENDENCY_DIRS = frozenset({"node_modules"})
VENV_DIRS = frozenset({"venv", ".venv"})
MAX_BYTES = 1_000_000
LONG_PATH = 240


@dataclass
class SourceFile:
    rel: str
    text: str | None = None
    error: str | None = None
    where: str = ""                         # the real path, for layers that depend on folders (.github)
    lines: list[int] | None = None          # line of the decoded text -> line of the file, when they differ

    @property
    def binary(self) -> bool:
        return self.text is None and self.error is None

    def line(self, n: int) -> int:
        """The file's own line for line ``n`` of the text the rules read."""
        return self.lines[n - 1] if self.lines and 0 < n <= len(self.lines) else n


@dataclass
class Skipped:
    """What the walk left out, said in the report."""

    folders: list[tuple[str, int, str]] = field(default_factory=list)   # (folder, files, why)
    links: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)   # folders the walk could not list: a gap

    def notes(self) -> list[str]:
        out = []
        if self.unlisted:
            out.append(f"Could not be listed, so not read: {', '.join(self.unlisted[:10])}.")
        if self.folders:
            shown = "; ".join(f"{d} ({n} file{'s' if n != 1 else ''}, {why})" for d, n, why in self.folders[:10])
            more = f" and {len(self.folders) - 10} more" if len(self.folders) > 10 else ""
            out.append(f"Not read, by folder name: {shown}{more}.")
        if self.links:
            out.append(f"Not read, a link or junction, or outside the target: {', '.join(self.links[:10])}"
                       + (f" and {len(self.links) - 10} more" if len(self.links) > 10 else "") + ".")
        if self.excluded:
            out.append(f"Excluded by the person running the scan: {len(self.excluded)} file(s), "
                       f"e.g. {', '.join(self.excluded[:5])}.")
        return out


_PREFIX = "\\\\?\\"


def _long(path: Path | str) -> str:
    """The path to open: with the `\\\\?\\` prefix for a long Windows path."""
    text = str(Path(path).absolute())
    if os.name == "nt" and len(text) >= LONG_PATH and not text.startswith(_PREFIX):
        return _PREFIX + text
    return text


def _strip(text: str) -> str:
    return text[len(_PREFIX):] if text.startswith(_PREFIX) else text


def _walk_root(target: Path) -> str:
    """Where a walk starts: on Windows always through the `\\\\?\\` prefix, so folders deeper than the
    260-character limit are listed too."""
    text = os.path.abspath(target)
    if os.name == "nt" and not text.startswith("\\\\"):
        return _PREFIX + text
    return text


def python_text(raw: bytes) -> tuple[str, list[int] | None]:
    """A Python file's text as CPython decodes it, and the line map when its declared encoding moves
    lines (`+AAo-` is a new line in UTF-7). Raises SyntaxError, LookupError or UnicodeDecodeError for
    an encoding Python would refuse."""
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    if encoding in ("utf-8", "utf-8-sig"):
        return raw.decode("utf-8", errors="replace").lstrip("﻿"), None
    text = raw.decode(encoding)
    mapping: list[int] = []
    for n, part in enumerate(raw.split(b"\n"), 1):
        mapping += [n] * (part.decode(encoding, errors="replace").count("\n") + 1)
    return text, mapping if len(mapping) >= text.count("\n") + 1 else None


def python_like(rel: str, raw: bytes) -> bool:
    """A file Python runs: `*.py`, `*.pyw`, or an extensionless script whose first line names python."""
    p = PurePosixPath(rel)
    if p.suffix.lower() in (".py", ".pyw"):
        return True
    return not p.suffix and raw.startswith(b"#!") and b"python" in raw.split(b"\n", 1)[0]


def read_file(path: Path, rel: str) -> SourceFile:
    """A file as the scan sees it: its text, or binary (None), or the reason it was not read."""
    where = _real(path).as_posix()
    try:
        size = os.stat(_long(path)).st_size
        if size > MAX_BYTES:
            return SourceFile(rel, error=f"{rel} is {size // 1000} kB, over the {MAX_BYTES // 1_000_000} MB limit",
                              where=where)
        with open(_long(path), "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return SourceFile(rel, error=f"{rel} could not be read ({type(exc).__name__})", where=where)
    if b"\x00" in raw[:8192]:
        return SourceFile(rel, where=where)
    if python_like(rel, raw):
        try:
            text, lines = python_text(raw)
        except (SyntaxError, LookupError, UnicodeDecodeError):
            return SourceFile(rel, error=f"{rel} declares a source encoding Python cannot read", where=where)
        return SourceFile(rel, text, where=where, lines=lines)
    return SourceFile(rel, raw.decode("utf-8", errors="replace").lstrip("﻿"), where=where)


def _link(path: Path) -> bool:
    junction = getattr(os.path, "isjunction", None)
    long = _long(path)
    return os.path.islink(long) or bool(junction and junction(long))


def _count(folder: Path) -> int:
    n = 0
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not _link(Path(root) / d)]
        n += len(names)
    return n


def _real(path: Path) -> Path:
    try:
        return Path(_strip(str(Path(_long(path)).resolve())))
    except OSError:
        return Path(os.path.normpath(path.absolute()))


def _skip_reason(folder: Path) -> str | None:
    name = folder.name
    if name in TOOL_DIRS:
        return "a version-control or tool folder"
    if name in DEPENDENCY_DIRS:
        return "installed dependencies"
    if name in VENV_DIRS and (folder / "pyvenv.cfg").exists():
        return "a virtual environment"
    return None


def _inside(path: Path, top: Path) -> bool:
    real = _real(path)
    return real == top or top in real.parents


class Walk:
    """The files under the targets, with what was left out and why."""

    def __init__(self, base: Path, exclude: Sequence[str] = ()) -> None:
        self.base = base
        self.exclude = [e.strip("/") for e in exclude if e.strip("/")]
        self.skipped = Skipped()

    def rel(self, path: Path) -> str:
        try:
            return _real(path).relative_to(_real(self.base)).as_posix()
        except ValueError:
            return Path(os.path.relpath(path.absolute(), self.base.absolute())).as_posix()

    def _unlisted(self, error: OSError) -> None:
        self.skipped.unlisted.append(self.rel(Path(_strip(str(error.filename or "?")))))

    def excluded(self, rel: str) -> bool:
        parts = PurePosixPath(rel).parts
        prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
        return any(fnmatch.fnmatch(p, pattern) for pattern in self.exclude for p in prefixes)

    def _prune(self, folder: Path, dirs: list[str]) -> list[str]:
        kept = []
        for d in sorted(dirs):
            path = folder / d
            why = "a link or junction" if _link(path) else _skip_reason(path)
            if why is None:
                kept.append(d)
            elif why == "a link or junction":
                self.skipped.links.append(self.rel(path) + "/")
            else:
                self.skipped.folders.append((self.rel(path), _count(path), why))
        return kept

    def files(self, target: Path) -> Iterable[Path]:
        top = _real(target)
        if target.is_file():
            yield target
            return
        for dirpath, dirs, names in os.walk(_walk_root(target), onerror=self._unlisted):
            folder = Path(_strip(str(dirpath)))
            dirs[:] = self._prune(folder, dirs)
            for name in sorted(names):
                path = folder / name
                if _link(path) or not _inside(path, top):
                    self.skipped.links.append(self.rel(path))
                elif self.excluded(self.rel(path)):
                    self.skipped.excluded.append(self.rel(path))
                else:
                    yield path
