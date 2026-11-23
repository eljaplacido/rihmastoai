"""A ledger kept in a JSONL file: one hash-chained record per line, appended only.

The chain rules (canonical JSON, the record hash, verify and the head) are `kernel.ledger`'s.
This module only stores records on disk and appends to them under a lock, so two writers in
the same factory cannot both take the same sequence number.
"""

from __future__ import annotations

import json
import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from kernel.filelock import locked
from kernel.ledger import VerifyResult, canonical_json, event_hash, verify


class ClockLike(Protocol):
    """What the store needs of a clock: the current time as an ISO stamp."""

    def stamp(self) -> str: ...


class LedgerStore:
    def __init__(self, path: str | Path, clock: ClockLike | None = None) -> None:
        self.path = Path(path)
        self.clock = clock

    def _locked(self) -> AbstractContextManager[None]:
        return locked(self.path.with_name(self.path.name + ".lock"))

    def records(self) -> list[Any]:
        """Every stored record, in order. A line that is not JSON is kept as a string so that
        verify reports it as broken instead of it vanishing."""
        if not self.path.exists():
            return []
        out: list[Any] = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append(line)
        return out

    def head(self) -> dict[str, Any]:
        """The head to keep outside the file; an empty ledger's head is seq -1 (FR-L1-AC-4)."""
        recs = self.records()
        if not recs:
            return {"seq": -1, "hash": None}
        last = recs[-1] if isinstance(recs[-1], dict) else {}
        return {"seq": last.get("seq", len(recs) - 1), "hash": last.get("hash")}

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        event: dict[str, Any] = {"kind": kind, "payload": payload}
        if self.clock is not None:
            event["at"] = self.clock.stamp()
        event = json.loads(canonical_json(event))  # store exactly what is hashed
        with self._locked():
            recs = self.records()
            seq = len(recs)
            prev = recs[-1].get("hash") if recs and isinstance(recs[-1], dict) else None
            record: dict[str, Any] = {"seq": seq, "event": event, "prev": prev,
                                      "hash": event_hash(seq, event, prev)}
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(canonical_json(record) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return record

    def verify(self, head: dict[str, Any] | None = None) -> VerifyResult:
        return verify(self.records(), head=head)

    def of_kind(self, *kinds: str) -> list[dict[str, Any]]:
        return [r for r in self.records()
                if isinstance(r, dict) and isinstance(r.get("event"), dict) and r["event"].get("kind") in kinds]
