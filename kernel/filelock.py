"""An exclusive lock on a file, for POSIX and Windows. Standard library only.

A blocking lock waits for its holder to let go, however long the holder keeps it, up to a bounded
time (``timeout``, WAIT_SECONDS by default). Then it raises LockHeld, naming the lock and how long
it waited. It polls the platform's non-blocking lock: msvcrt's own blocking mode gives up after
about ten seconds, which would fail a writer whose turn was simply slow to come.

A re-entrant lock (``reentrant=True``) may be taken again by the thread that holds it: the inner
hold does nothing, and the file is let go when the outer hold ends. The kernel's record files use
one (kernel/store.py), so one locked change may call another on the same files. A lane's lock is
not re-entrant: a second lease in the same thread must find the lane taken.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

# The longest a blocking lock waits for its holder by default: longer than anyone holds one for good
# reason (a delivery, a gnomon run in a lane), so only a holder that is stuck makes a writer fail.
WAIT_SECONDS = 3600.0
_FIRST_PAUSE, _LONGEST_PAUSE = 0.005, 0.1

if sys.platform == "win32":
    import msvcrt

    def _try(fh: BinaryIO) -> bool:
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _release(fh: BinaryIO) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:  # POSIX
    import fcntl

    def _try(fh: BinaryIO) -> bool:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def _release(fh: BinaryIO) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class LockHeld(RuntimeError):
    """The lock is held by someone else: the caller asked not to wait, or waited as long as it may."""


# The re-entrant locks this process holds: the lock file's key -> (the holding thread, its depth).
_HOLDS: dict[str, tuple[int, int]] = {}
_HOLDS_GUARD = threading.Lock()


def _acquire(fh: BinaryIO, path: Path, blocking: bool, timeout: float | None) -> None:
    """Take the lock, or raise LockHeld: at once when not blocking, else once ``timeout`` ran out."""
    limit = WAIT_SECONDS if timeout is None else max(0.0, timeout)
    deadline = time.monotonic() + limit
    pause = _FIRST_PAUSE
    while not _try(fh):
        if not blocking:
            raise LockHeld(str(path))
        left = deadline - time.monotonic()
        if left <= 0:
            raise LockHeld(f"{path} is still held by another writer after waiting {limit:g} s")
        time.sleep(min(pause, left))
        pause = min(pause * 2, _LONGEST_PAUSE)


def _key(path: Path) -> str:
    """One spelling per lock file, however its path was written (relative, another case, a link)."""
    return os.path.normcase(os.path.join(os.path.realpath(path.parent), path.name))


def _hold_again(key: str) -> bool:
    """Count one more hold when this thread already holds the lock; False when it does not."""
    me = threading.get_ident()
    with _HOLDS_GUARD:
        held = _HOLDS.get(key)
        if held is None or held[0] != me:
            return False
        _HOLDS[key] = (me, held[1] + 1)
        return True


def _let_go(key: str) -> None:
    with _HOLDS_GUARD:
        me, depth = _HOLDS[key]
        if depth > 1:
            _HOLDS[key] = (me, depth - 1)
        else:
            del _HOLDS[key]


@contextmanager
def locked(path: str | Path, *, blocking: bool = True, timeout: float | None = None,
           reentrant: bool = False) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` for the block. Without ``blocking`` a held lock raises
    LockHeld at once; with it, the lock is waited for up to ``timeout`` seconds (WAIT_SECONDS)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = _key(path) if reentrant else ""
    if reentrant and _hold_again(key):
        try:
            yield
        finally:
            _let_go(key)
        return
    with open(path, "a+b") as fh:
        _acquire(fh, path, blocking, timeout)
        if reentrant:
            with _HOLDS_GUARD:
                _HOLDS[key] = (threading.get_ident(), 1)
        try:
            yield
        finally:
            if reentrant:
                _let_go(key)
            _release(fh)
