"""Hash-chained, insert-only ledger.

The ledger is a list of events. ``append`` is the only mutation and ``read``
returns an independent copy, so callers cannot update or delete stored events.
Integrity is checked with :func:`verify`, which recomputes each event's
``sha256`` over canonical JSON and reports the first sequence number whose
stored hash does not match.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, TypedDict


class LedgerRecord(TypedDict):
    """One stored record: its place in the chain, the event, and the hashes that chain it."""

    seq: int
    event: Any  # any JSON value, stored as its canonical JSON round trip
    prev: str | None
    hash: str


class LedgerHead(TypedDict):
    """The head kept outside the ledger: the last sequence number and its hash."""

    seq: int
    hash: str | None


def canonical_json(value: object) -> str:
    """Canonical JSON: sorted keys, no insignificant whitespace.

    Raises ``ValueError`` if the value contains NaN or Infinity, and
    ``TypeError`` if it is not JSON-serializable.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def event_hash(seq: int, event: object, prev: str | None) -> str:
    """SHA-256 over the canonical JSON of one ledger event's chained fields."""
    return hashlib.sha256(
        canonical_json({"event": event, "prev": prev, "seq": seq}).encode("utf-8")
    ).hexdigest()


class Ledger:
    """An insert-only, hash-chained ledger."""

    ALLOWED_KEYS = frozenset({"seq", "event", "prev", "hash"})

    def __init__(self) -> None:
        self._events: list[LedgerRecord] = []

    def append(self, event: object) -> LedgerRecord:
        """Append one event and return a copy of the stored record.

        The payload is stored as its canonical JSON round trip, so only JSON
        values enter the ledger and the hash covers exactly the stored value.
        """
        stored_event = json.loads(canonical_json(event))
        seq = len(self._events)
        prev = self._events[-1]["hash"] if self._events else None
        record: LedgerRecord = {
            "seq": seq,
            "event": stored_event,
            "prev": prev,
            "hash": event_hash(seq, stored_event, prev),
        }
        self._events.append(record)
        return copy.deepcopy(record)

    def read(self) -> list[LedgerRecord]:
        """Return an independent copy of the stored events."""
        return copy.deepcopy(self._events)

    def head(self) -> LedgerHead:
        """Return the current head as ``{"seq": n, "hash": h}``. An empty ledger's head is
        ``{"seq": -1, "hash": None}``, so a head taken before the first append still checks the tail."""
        if not self._events:
            return {"seq": -1, "hash": None}
        return {"seq": self._events[-1]["seq"], "hash": self._events[-1]["hash"]}


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of a ledger integrity check."""

    intact: bool
    broken_seq: int | None = None
    tail_checked: bool = False


def _record_is_broken(events: Sequence[Any], i: int, event: object) -> bool:
    """Return True when the record at ``i`` fails any non-head integrity check.

    Every failure is returned rather than raised, including failures caused by
    malformed records whose payload cannot be canonicalised.
    """
    if not isinstance(event, dict):
        return True

    try:
        keys = set(event.keys())
        if keys != Ledger.ALLOWED_KEYS:
            return True

        seq = event.get("seq")
        if type(seq) is not int:
            return True
        if seq != i:
            return True

        stored_hash = event.get("hash")
        if not isinstance(stored_hash, str):
            return True

        prev = event.get("prev")
        if i == 0:
            if prev is not None:
                return True
        else:
            if not isinstance(prev, str):
                return True
            previous_hash = events[i - 1].get("hash")
            if prev != previous_hash:
                return True

        expected = event_hash(seq, event.get("event"), prev)
        if stored_hash != expected:
            return True
    except Exception:
        # verify never raises: malformed content, non-JSON payloads, mixed
        # key types and deeply nested payloads are all reported as broken.
        return True

    return False


def verify(events: Iterable[Any], head: object = None) -> VerifyResult:
    """Verify event hashes, chain integrity and, optionally, the expected head.

    Checks:
    - Each record has exactly the allowed keys {seq, event, prev, hash}.
    - ``seq`` is exactly an ``int`` (never a bool).
    - Sequence numbers run 0, 1, 2, ... without gaps.
    - The first record has prev=None.
    - Each record's prev matches the previous record's hash.
    - Each record's hash matches the recomputed hash.
    - When ``head`` is given, the tail is checked against it.

    Returns the first broken sequence number, or intact=True if all checks
    pass. ``tail_checked`` is True only when a head was supplied. Never raises
    on malformed records.
    """
    try:
        records = list(events)
    except Exception:  # events that cannot even be listed are a broken ledger, never an exception
        return VerifyResult(intact=False, broken_seq=0, tail_checked=head is not None)

    for i, event in enumerate(records):
        if _record_is_broken(records, i, event):
            return VerifyResult(
                intact=False, broken_seq=i, tail_checked=head is not None
            )

    if head is None:
        return VerifyResult(intact=True, broken_seq=None, tail_checked=False)

    # A malformed head is not a broken record: nothing was compared, so no record is blamed.
    not_compared = VerifyResult(intact=False, broken_seq=None, tail_checked=False)
    if not isinstance(head, dict):
        return not_compared
    head_seq, head_hash = head.get("seq"), head.get("hash")
    if type(head_seq) is not int or head_seq < -1:
        return not_compared
    if head_seq == -1:
        if head_hash is not None:
            return not_compared
        return VerifyResult(intact=True, broken_seq=None, tail_checked=True)
    if not isinstance(head_hash, str):
        return not_compared

    if len(records) < head_seq + 1:
        return VerifyResult(
            intact=False, broken_seq=len(records), tail_checked=True
        )
    if records[head_seq]["hash"] != head_hash:
        return VerifyResult(intact=False, broken_seq=head_seq, tail_checked=True)

    return VerifyResult(intact=True, broken_seq=None, tail_checked=True)
