"""Quotas, so that batch work cannot starve interactive work.

Two simple mechanisms, both in memory:

- **A concurrency limit per workload class.** Each class (interactive, batch, specialist) has its own
  number of requests in flight. When batch is at its limit, a new batch request is refused (or waits
  up to `quotas.wait_s`), and interactive requests still have their own slots.
- **A token bucket per workload.** A workload with a `rate` takes one token per request; the bucket
  refills at `per_minute` and holds at most `burst`. An empty bucket says how long until a token is
  free, which becomes the `Retry-After` of the 429.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from gateway.config import GatewayConfig


class TokenBucket:
    """One workload's request rate."""

    def __init__(self, per_minute: float, burst: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._last = clock()
        self._lock = threading.Lock()

    def take(self) -> float:
        """Take one token. Returns 0.0 when one was taken, else the seconds until one is free."""
        with self._lock:
            now = self._clock()
            self._tokens = min(self._burst, self._tokens + max(0.0, now - self._last) * self._rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            return (1.0 - self._tokens) / self._rate


class ClassSlots:
    """The requests in flight per workload class, each class with its own limit."""

    def __init__(self, limits: dict[str, int]) -> None:
        self._limits = dict(limits)
        self._used = {k: 0 for k in limits}
        self._cond = threading.Condition()

    def acquire(self, klass: str, wait_s: float = 0.0) -> bool:
        """Take a slot for this class, waiting up to ``wait_s`` seconds. False when none came free."""
        with self._cond:
            free = self._cond.wait_for(lambda: self._used[klass] < self._limits[klass], timeout=wait_s)
            if free:
                self._used[klass] += 1
            return bool(free)

    def release(self, klass: str) -> None:
        with self._cond:
            self._used[klass] = max(0, self._used[klass] - 1)
            self._cond.notify_all()

    def in_use(self) -> dict[str, dict[str, int]]:
        with self._cond:
            return {k: {"in_flight": self._used[k], "limit": self._limits[k]} for k in self._limits}


class Quotas:
    """The gateway's quotas: one slot pool per class and one bucket per workload that declares a rate."""

    def __init__(self, config: GatewayConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self.slots = ClassSlots(config.concurrency)
        self.wait_s = config.wait_s
        self.buckets = {name: TokenBucket(w.rate.per_minute, w.rate.burst, clock)
                        for name, w in config.workloads.items() if w.rate is not None}

    def rate_wait(self, workload: str) -> float:
        """0.0 when the workload's bucket gave a token (or it has none), else seconds to wait."""
        bucket = self.buckets.get(workload)
        return bucket.take() if bucket is not None else 0.0
