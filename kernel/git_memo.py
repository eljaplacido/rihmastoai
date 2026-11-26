"""What a project's repository holds on main, read once per commit of main (FR-AOP2).

Reading what main holds (its tests, its learned notes) asks git once per file. The status, compliance and drift
read models, the context packs and Agent operations each read it again, so building one project's packs asked git
about 50 times and the platform's Agent operations view about 150. Main's commit is read from the repository's
ref files (no git process): while main points at the same commit, what was read from it is answered again from
memory. A repository whose main cannot be read from its files is asked every time, as before.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

MAX_KEPT = 512
T = TypeVar("T")
_kept: OrderedDict[tuple[str, str, str], Any] = OrderedDict()
_lock = threading.Lock()


def _git_dir(repo: Path) -> Path:
    dot = repo / ".git"
    return dot if dot.is_dir() else repo


def _packed(git: Path, ref: str) -> str | None:
    try:
        lines = (git / "packed-refs").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return next((line.split()[0] for line in lines if line.endswith(" " + ref)), None)


def main_commit(repo: Path, branch: str = "main") -> str | None:
    """main's commit id from the ref files, or None when it cannot be read from them."""
    git = _git_dir(Path(repo))
    ref = f"refs/heads/{branch}"
    try:
        sha = (git / ref).read_text(encoding="utf-8").strip()
    except OSError:
        sha = _packed(git, ref) or ""
    return sha if len(sha) >= 40 and all(c in "0123456789abcdef" for c in sha) else None


def on_main(repo: Path, what: str, read: Callable[[], T]) -> T:
    """``read()``'s answer for ``what`` on ``repo``'s main, kept while main is at the same commit."""
    sha = main_commit(repo)
    if sha is None:
        return read()
    key = (str(Path(repo).resolve()), what, sha)
    with _lock:
        if key in _kept:
            _kept.move_to_end(key)
            return _copy(_kept[key])
    got = read()
    with _lock:
        _kept[key] = _copy(got)
        while len(_kept) > MAX_KEPT:
            _kept.popitem(last=False)
    return got


def _copy(value: Any) -> Any:
    return list(value) if isinstance(value, list) else value


def forget() -> None:
    """Drop everything kept (tests)."""
    with _lock:
        _kept.clear()
