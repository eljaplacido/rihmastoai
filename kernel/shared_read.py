"""One read shared by the requests that ask for it at once (FR-NVL3).

The owner's acceptance run opened Home in ten tabs at once over 30 projects: each dashboard took 0.6 s alone, and
ten at once took 7.5 s each, because each request built the same read model again while the others did (Python
runs one of them at a time). A read asked for while the same read is being built, over the same records, now
waits for that one and takes its answer: ten tabs cost one build.

The records are the same when their stamp is (``stamp``: the size and time of the folders and files a write
changes); a request whose stamp differs builds its own, so a write is never hidden. Nothing is kept after the
build ends. Standard library only.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable, Iterable
from pathlib import Path
from typing import Any, TypeVar, cast

T = TypeVar("T")
WAIT_SECONDS = 120.0


def stamp(paths: Iterable[Path]) -> tuple[Any, ...]:
    """The size and modification time of each path (None for one that is not there)."""
    out: list[Any] = []
    for path in paths:
        try:
            st = path.stat()
            out.append((st.st_size, st.st_mtime_ns))
        except OSError:
            out.append(None)
    return tuple(out)


def factory_stamp(factory: Any) -> tuple[Any, ...]:
    """What a write anywhere in the factory home changes: its folders (an atomic write renames into them) and every
    project's folder, canon, Inbox and ledger."""
    home = Path(factory.home)
    paths = [home, home / "projects", home / "jobs"]
    projects = home / "projects"
    if projects.is_dir():
        for folder in sorted(projects.iterdir()):
            paths += [folder, folder / "canon", folder / "canon" / "inbox", folder / "ledger.jsonl"]
    return stamp(paths)


class Shared:
    """Builds that requests asking at once share."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[Hashable, tuple[tuple[Any, ...], threading.Event, list[Any]]] = {}

    def read(self, key: Hashable, at: tuple[Any, ...], build: Callable[[], T]) -> T:
        """``build()``'s answer, or the answer of the same build already running over the same records."""
        with self._lock:
            running = self._running.get(key)
            if running is None or running[0] != at:
                done, box = threading.Event(), cast(list[Any], [])
                self._running[key] = (at, done, box)
                running = None
        if running is not None:
            running[1].wait(WAIT_SECONDS)
            if running[2]:
                kept: T = running[2][0]
                return kept
            return build()
        try:
            out = build()
            box.append(out)
            return out
        finally:
            with self._lock:
                if self._running.get(key, (None, None))[1] is done:
                    del self._running[key]
            done.set()
