"""All or nothing: a change that writes several record files is undone when one of its writes fails (FR-NVL3).

The owner's acceptance run made the ledger read-only (a full disk's stand-in) and answered a question: the
decision was written, the ledger refused its record, and the card vanished from every Inbox while the question
stayed open with no way to answer it. Inside ``all_or_nothing`` each record file keeps what it held before its
first write in this change (kernel/store.py ``write_text``) and each appended log keeps its length
(kernel/ledgerstore.py), so an OSError (a full disk, a read-only or locked file) puts every one back: nothing is
recorded, and trying again works. A refusal by the rules writes nothing before it is raised, so it needs no undo;
only an operating-system failure undoes.

Per thread, re-entrant: a change made inside another is undone with it. Standard library only.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Iterator
from pathlib import Path

_HERE = threading.local()


def _kept() -> dict[Path, bytes | int | None] | None:
    kept: dict[Path, bytes | int | None] | None = getattr(_HERE, "kept", None)
    return kept


def before_write(path: Path) -> None:
    """Called before a record file is replaced: keep what it held (None: it did not exist)."""
    kept = _kept()
    if kept is None or path in kept:
        return
    try:
        kept[path] = path.read_bytes()
    except FileNotFoundError:
        kept[path] = None


def before_append(path: Path) -> None:
    """Called before a line is appended to a log: keep its length, so a failed change cuts it back."""
    kept = _kept()
    if kept is None or path in kept:
        return
    try:
        kept[path] = path.stat().st_size
    except FileNotFoundError:
        kept[path] = None


def _undo(kept: dict[Path, bytes | int | None]) -> None:
    for path, was in kept.items():
        with contextlib.suppress(OSError):    # put back what can be; a file that still refuses stays as it was
            if was is None:
                path.unlink(missing_ok=True)
            elif isinstance(was, int):
                if path.stat().st_size > was:
                    with open(path, "r+b") as fh:
                        fh.truncate(was)
            else:
                tmp = path.with_name(f".undo-{os.getpid()}-{path.name}")
                tmp.write_bytes(was)
                os.replace(tmp, path)


@contextlib.contextmanager
def all_or_nothing() -> Iterator[None]:
    """Run a change whose writes are undone together when an operating-system failure stops it."""
    outer = _kept() is None
    if outer:
        _HERE.kept = {}
    try:
        yield
    except OSError as exc:
        if outer and exc.errno is not None:    # the system's failure; a rule's refusal carries no errno
            _undo(_HERE.kept)
        raise
    finally:
        if outer:
            _HERE.kept = None
