"""L4: requests no upstream could answer, queued with an honest "no answer yet".

A workload whose ladder ends in `"L4": "defer"` does not fail when L1 to L3 all fail or are not
allowed. Its request is queued and the client gets `202` with an id and `"answer": null`. The gateway
retries the queue every `defer.retry_s` seconds, up to `defer.max_attempts` times, and the client
asks `GET /v1/deferred/<id>` for the outcome.

The queue lives in memory only. It holds the request body so it can be retried, and writing it to
disk would store prompt content, which the gateway does not do unless content capture is on. So a
restart forgets queued requests; the audit still has a record of each one.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field

from gateway.config import DeferPolicy


@dataclass
class Deferred:
    id: str
    request_id: str
    workload: str
    data_class: str
    body: dict = field(repr=False)
    tries: int = 0
    status: str = "queued"  # queued, answered or failed
    answer: dict | None = field(default=None, repr=False)
    headers: dict[str, str] = field(default_factory=dict)


class DeferredQueue:
    """Deferred requests in memory, at most ``max_queue`` of them."""

    def __init__(self, policy: DeferPolicy) -> None:
        self.policy = policy
        self._items: dict[str, Deferred] = {}
        self._lock = threading.Lock()

    def put(self, request_id: str, workload: str, data_class: str, body: dict) -> Deferred | None:
        """Queue a request. None when the queue is full of requests still waiting."""
        with self._lock:
            if len(self._items) >= self.policy.max_queue:
                settled = [k for k, v in self._items.items() if v.status != "queued"]
                if not settled:
                    return None
                del self._items[settled[0]]  # the oldest outcome nobody fetched
            item = Deferred(id="dfr-" + secrets.token_urlsafe(12), request_id=request_id, workload=workload,
                            data_class=data_class, body=body)
            self._items[item.id] = item
            return item

    def pending(self) -> list[Deferred]:
        with self._lock:
            return [v for v in self._items.values() if v.status == "queued"]

    def settle(self, item: Deferred, answer: dict | None, headers: dict[str, str] | None = None) -> None:
        """Record a retry's outcome: an answer, or one more failed try (failed for good after the last)."""
        with self._lock:
            item.tries += 1
            if answer is not None:
                item.status, item.answer, item.headers = "answered", answer, dict(headers or {})
            elif item.tries >= self.policy.max_attempts:
                item.status = "failed"
            if item.status != "queued":
                item.body = {}  # the prompt is not kept once it cannot be needed again

    def fetch(self, deferred_id: str) -> Deferred | None:
        """The item; an answered or failed one is handed over once and then forgotten."""
        with self._lock:
            item = self._items.get(deferred_id)
            if item is not None and item.status != "queued":
                del self._items[deferred_id]
            return item

    def __len__(self) -> int:
        with self._lock:
            return sum(1 for v in self._items.values() if v.status == "queued")
