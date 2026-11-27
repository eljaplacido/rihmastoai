"""A project's context audit for Agent operations, kept while nothing it is built from changed (FR-AOP2).

Building every context pack of a project takes a while (the packs read the project's records, its repository's main
and the home's settings). Agent operations reads them on every open, every period switch and Ask Rihma's "where can
I cut tokens?", though the period changes nothing a role is given. So a project's audit is kept in memory with a
fingerprint of what it was built from: the size and time of every file and folder at the top of the project's folder
and of the home (but its projects folder and lock files), and main's commit. A record written, a file added or main
moved changes the fingerprint and the next read builds the packs again; a kept audit is never older than
``MAX_AGE`` seconds either. Nothing is written.
"""

from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

MAX_AGE = 300.0
MAX_KEPT = 64
_kept: OrderedDict[tuple[str, str], tuple[tuple, float, dict[str, Any]]] = OrderedDict()
_lock = threading.Lock()


def _stats(folder: Path, skip: tuple[str, ...] = ()) -> tuple:
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return ()
    out = []
    for e in entries:
        if e.name in skip or e.name.endswith(".lock"):
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        out.append((e.name, st.st_mtime_ns, st.st_size))
    return tuple(out)


def fingerprint(factory: Any, project: Any) -> tuple:
    """What the project's packs are built from, as sizes, times and main's commit."""
    from kernel.git_memo import main_commit

    repo = project.path("repo.git")
    # the home's projects folder changes with every project added: each project has its own fingerprint
    return (_stats(project.dir), _stats(Path(factory.home), ("projects",)),
            main_commit(repo) if repo.exists() else None)


def project_audit(factory: Any, project: Any) -> dict[str, Any]:
    """kernel/context_audit.py's audit of the project (no commands run), from memory when nothing changed."""
    from kernel import context_audit as ca

    key = (str(Path(factory.home).resolve()), project.pid)
    mark, now = fingerprint(factory, project), time.monotonic()
    with _lock:
        hit = _kept.get(key)
        if hit is not None and hit[0] == mark and now - hit[1] < MAX_AGE:
            _kept.move_to_end(key)
            return copy.deepcopy(hit[2])
    got = ca.project_audit(factory, project, commands=False)
    mark = fingerprint(factory, project)       # after: building may keep its own caches beside the records
    with _lock:
        _kept[key] = (mark, now, copy.deepcopy(got))
        while len(_kept) > MAX_KEPT:
            _kept.popitem(last=False)
    return got


def forget() -> None:
    """Drop every kept audit and what was read from main (tests)."""
    from kernel import git_memo

    git_memo.forget()
    with _lock:
        _kept.clear()
