"""The gateway's audit: one hash-chained JSONL record per request, with no content in it.

Records have the kernel's ledger shape (`seq`, `event`, `prev`, `hash`) and the kernel's hashing
(`kernel.ledger.canonical_json` and `event_hash`), so `kernel.ledger.verify` checks the chain and
`kernel.ledgerstore.LedgerStore` reads it. Each event is `{"kind": "gateway_request", "at": ...,
"payload": ...}`. The payload says what happened: the workload, the level that answered, the
upstream and model, latency, token counts when the upstream returned them, and the status. It never
holds the prompt or the answer, unless the config sets `audit.content_capture` to true.

A gateway appends often, so unlike `LedgerStore.append` this one does not re-read the whole file on
every request: it keeps the head it wrote, and re-reads only when the file changed under it.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from kernel.ledger import canonical_json, event_hash
from kernel.ledgerstore import LedgerStore
from kernel.store import Clock

EVENT_KIND = "gateway_request"
# The fields a content-free record may carry; content is added only with content_capture.
FIELDS = ("request_id", "workload", "workload_class", "data_class", "status", "level", "degraded", "upstream",
          "model", "http_status", "latency_ms", "tokens", "attempts", "skipped", "reason", "deferred_id")


class AuditLog(LedgerStore):
    """An append-only, hash-chained JSONL audit of gateway requests."""

    def __init__(self, path: str | Path, clock: Clock | None = None, *, content_capture: bool = False) -> None:
        super().__init__(path, clock=clock or Clock())
        self.content_capture = content_capture
        self._mutex = threading.Lock()
        self._known: tuple[int, int, str | None] | None = None  # (file size, next seq, last hash)

    def _next(self) -> tuple[int, str | None]:
        size = self.path.stat().st_size if self.path.exists() else 0
        if self._known is not None and self._known[0] == size:
            return self._known[1], self._known[2]
        recs = self.records()
        last = recs[-1] if recs and isinstance(recs[-1], dict) else {}
        return len(recs), last.get("hash")

    def record(self, entry: dict, content: dict | None = None) -> dict:
        """Append one request's record. Only the known fields are kept; ``content`` (the messages
        and the answer) is kept only when content capture is on."""
        payload = {k: entry[k] for k in FIELDS if entry.get(k) is not None}
        if self.content_capture and content is not None:
            payload["content"] = content
        return self.append(EVENT_KIND, payload)

    def append(self, kind: str, payload: dict) -> dict:
        event = {"kind": kind, "payload": payload}
        if self.clock is not None:
            event["at"] = self.clock.stamp()
        event = json.loads(canonical_json(event))  # store exactly what is hashed
        with self._mutex, self._locked():
            seq, prev = self._next()
            record = {"seq": seq, "event": event, "prev": prev, "hash": event_hash(seq, event, prev)}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(canonical_json(record) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._known = (self.path.stat().st_size, seq + 1, record["hash"])
        return record
