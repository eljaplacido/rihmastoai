"""The gateway's core: a workload's request goes up its fallback ladder, within its quotas, into the audit.

For each `POST /v1/chat/completions` the request's `model` names a workload. The gateway:

1. checks the request and finds the workload (unknown: 404, like an unknown model);
2. settles the data class: the workload's own class is a floor, and a request may only raise it
   (`data_class` in the body or the `X-Data-Class` header);
3. takes a token from the workload's bucket and a slot of its class (none: 429 with Retry-After);
4. climbs the ladder: L1 targets, then L2 (degraded), then L3, leaving out every cloud upstream the
   site mode and data class do not allow; the first valid answer wins;
5. when nothing answered, queues the request (L4, `202`, "no answer yet") or says 503;
6. writes one audit record whatever happened.
"""

from __future__ import annotations

import math
import os
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from gateway.audit import AuditLog
from gateway.config import DATA_CLASSES, GatewayConfig, Target, Workload, cloud_allowed
from gateway.deferred import Deferred, DeferredQueue
from gateway.quotas import Quotas
from gateway.upstream import UpstreamResult, call_upstream

Caller = Callable[..., UpstreamResult]


@dataclass
class Reply:
    status: int
    body: dict
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _Ctx:
    """One request in flight: its id, its start and the audit entry being filled in."""

    rid: str = field(default_factory=lambda: "gw-" + secrets.token_hex(8))
    t0: float = field(default_factory=time.perf_counter)
    entry: dict = field(default_factory=dict)

    def done(self, **fields: Any) -> dict:
        self.entry.update(fields, request_id=self.rid, latency_ms=round((time.perf_counter() - self.t0) * 1000, 1))
        return self.entry


def _error(status: int, message: str, code: str, rid: str, retry_after: float | None = None,
           **extra: Any) -> Reply:
    headers = {"X-Gateway-Request-Id": rid}
    if retry_after is not None:
        headers["Retry-After"] = str(max(1, math.ceil(retry_after)))
    kind = "invalid_request_error" if status < 500 else "upstream_error"
    return Reply(status, {"error": {"message": message, "type": kind, "code": code, **extra}}, headers)


def check_request(body: Any) -> str | None:
    """What is wrong with a chat completion request, or None."""
    if not isinstance(body, dict):
        return "the body must be a JSON object"
    if not isinstance(body.get("model"), str) or not body["model"]:
        return "name a workload in 'model' (GET /v1/models lists them)"
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        return "'messages' must be a non-empty list"
    if body.get("stream"):
        return "the gateway does not stream yet; send \"stream\": false"
    return None


def plan(config: GatewayConfig, workload: Workload, data_class: str) -> tuple[list[Target], list[dict]]:
    """The ladder's targets this request may use, in order, and the ones left out with the reason."""
    allowed = cloud_allowed(config, data_class)
    keep: list[Target] = []
    skipped: list[dict] = []
    for t in workload.targets:
        if config.upstreams[t.upstream].cloud and not allowed:
            reason = ("the site is air-gapped" if config.site_mode == "air-gapped"
                      else f"{data_class} data may not leave the site")
            skipped.append({"level": t.level, "upstream": t.upstream, "model": t.model, "reason": reason})
        else:
            keep.append(t)
    return keep, skipped


NOT_MEASURED = "not measured"


def _tokens(usage: Any) -> dict | str:
    """The token counts an upstream returned; "not measured" when it counted none (usage absent or null, as a
    capability's openai face answers), so the audit never shows a count nobody made."""
    if not isinstance(usage, dict):
        return NOT_MEASURED
    out = {k.removesuffix("_tokens"): v for k, v in usage.items()
           if k in ("prompt_tokens", "completion_tokens", "total_tokens") and type(v) is int}
    return out or NOT_MEASURED


def _gateway_headers(rid: str, workload: str, target: Target) -> dict[str, str]:
    return {"X-Gateway-Request-Id": rid, "X-Gateway-Workload": workload, "X-Gateway-Level": target.level,
            "X-Gateway-Degraded": "true" if target.degraded else "false"}


def _answer(data: dict, rid: str, workload: str, target: Target) -> dict:
    info = {"request_id": rid, "workload": workload, "level": target.level, "degraded": target.degraded,
            "upstream": target.upstream, "model": target.model}
    if target.degraded:
        info["degraded_reason"] = f"answered at {target.level} by a fallback model, not the workload's own"
    return {**data, "model": data.get("model") or target.model, "gateway": info}


class Gateway:
    """Serves chat completions by workload. Thread-safe: the HTTP server calls it from many threads."""

    def __init__(self, config: GatewayConfig, *, audit: AuditLog | None = None,
                 env: Mapping[str, str] | None = None, clock: Callable[[], float] = time.monotonic,
                 call: Caller = call_upstream) -> None:
        self.config = config
        self.audit = audit or AuditLog(config.audit_path, content_capture=config.content_capture)
        self.env = os.environ if env is None else env
        self.quotas = Quotas(config, clock)
        self.queue = DeferredQueue(config.defer)
        self._call = call
        self._draining = threading.Lock()

    def models(self) -> dict:
        """The workloads, in the shape of OpenAI's model list. The models behind them are not listed."""
        data = [{"id": w.name, "object": "model", "owned_by": "rihma-gateway", "workload_class": w.workload_class,
                 "data_class": w.data_class, "description": w.description,
                 "levels": sorted({t.level for t in w.targets} | ({"L4"} if w.defer else set()))}
                for w in self.config.workloads.values()]
        return {"object": "list", "data": data}

    def health(self) -> dict:
        return {"ok": True, "site_mode": self.config.site_mode, "classes": self.quotas.slots.in_use(),
                "deferred": len(self.queue)}

    def _data_class(self, workload: Workload, *given: Any) -> str | None:
        asked = [g for g in given if g not in (None, "")]
        if any(g not in DATA_CLASSES for g in asked):
            return None
        return max([workload.data_class, *asked], key=DATA_CLASSES.index)

    def _refuse(self, ctx: _Ctx, status: int, message: str, code: str, retry_after: float | None = None) -> Reply:
        self.audit.record(ctx.done(status="refused", reason=code, http_status=status))
        return _error(status, message, code, ctx.rid, retry_after)

    def refuse(self, status: int, message: str, code: str) -> Reply:
        """Refuse, and audit, a request the server could not read at all (an empty or too large body)."""
        return self._refuse(_Ctx(), status, message, code)

    def complete(self, body: Any, data_class_header: str | None = None) -> Reply:
        """Answer one chat completion request whose `model` names a workload."""
        ctx = _Ctx()
        problem = check_request(body)
        if problem:
            return self._refuse(ctx, 400, problem, "invalid_request")
        workload = self.config.workloads.get(body["model"])
        if workload is None:
            ctx.entry["workload"] = body["model"][:64]
            return self._refuse(ctx, 404, f"no workload named {body['model'][:64]!r}; GET /v1/models lists them",
                                "model_not_found")
        ctx.entry.update(workload=workload.name, workload_class=workload.workload_class)
        data_class = self._data_class(workload, body.get("data_class"), data_class_header)
        if data_class is None:
            return self._refuse(ctx, 400, "data_class must be one of " + ", ".join(DATA_CLASSES), "invalid_data_class")
        ctx.entry["data_class"] = data_class
        wait = self.quotas.rate_wait(workload.name)
        if wait > 0:
            return self._refuse(ctx, 429, f"workload {workload.name!r} is over its rate", "rate_limited", wait)
        if not self.quotas.slots.acquire(workload.workload_class, self.quotas.wait_s):
            return self._refuse(ctx, 429, f"the {workload.workload_class} class is at its concurrency limit",
                                "concurrency_limited", 1.0)
        try:
            return self._serve(ctx, workload, body, data_class)
        finally:
            self.quotas.slots.release(workload.workload_class)

    def _climb(self, targets: list[Target], body: dict) -> tuple[UpstreamResult | None, Target | None, list[dict]]:
        attempts: list[dict] = []
        for t in targets:
            result = self._call(self.config.upstreams[t.upstream], t.model, body, self.env)
            attempts.append({"level": t.level, "upstream": t.upstream, "model": t.model,
                             "outcome": "answered" if result.ok else result.error, "ms": result.ms})
            if result.ok:
                return result, t, attempts
        return None, None, attempts

    def _serve(self, ctx: _Ctx, workload: Workload, body: dict, data_class: str) -> Reply:
        targets, skipped = plan(self.config, workload, data_class)
        result, target, attempts = self._climb(targets, body)
        ctx.entry.update(attempts=attempts, skipped=skipped or None)
        if result is not None and result.data is not None and target is not None:
            answer = _answer(result.data, ctx.rid, workload.name, target)
            self.audit.record(ctx.done(status="answered", level=target.level, degraded=target.degraded,
                                       upstream=target.upstream, model=target.model, http_status=200,
                                       tokens=_tokens(result.data.get("usage"))),
                              content={"messages": body["messages"], "choices": result.data["choices"]})
            return Reply(200, answer, _gateway_headers(ctx.rid, workload.name, target))
        if workload.defer:
            return self._defer(ctx, workload, body, data_class, attempts, skipped)
        self.audit.record(ctx.done(status="failed", reason="no_upstream", http_status=503))
        return _error(503, f"no upstream answered for workload {workload.name!r}", "no_upstream", ctx.rid,
                      attempts=attempts, skipped=skipped)

    def _defer(self, ctx: _Ctx, workload: Workload, body: dict, data_class: str, attempts: list[dict],
               skipped: list[dict]) -> Reply:
        item = self.queue.put(ctx.rid, workload.name, data_class, body)
        if item is None:
            self.audit.record(ctx.done(status="failed", reason="queue_full", http_status=503))
            return _error(503, "no upstream answered and the deferred queue is full", "queue_full", ctx.rid,
                          attempts=attempts, skipped=skipped)
        self.audit.record(ctx.done(status="deferred", level="L4", deferred_id=item.id, http_status=202),
                          content={"messages": body["messages"]})
        message = (f"no answer yet: no upstream for workload {workload.name!r} answered or was allowed; the request "
                   f"is queued and retried every {self.config.defer.retry_s:g} s")
        out = {"object": "gateway.deferred", "id": item.id, "status": "queued", "answer": None, "message": message,
               "gateway": {"request_id": ctx.rid, "workload": workload.name, "level": "L4", "attempts": attempts,
                           "skipped": skipped}}
        return Reply(202, out, {"X-Gateway-Request-Id": ctx.rid, "X-Gateway-Workload": workload.name,
                                "X-Gateway-Level": "L4", "Location": f"/v1/deferred/{item.id}"})

    def drain(self) -> int:
        """Retry every queued request once (L1 to L3), within its class's slots. Returns how many answered.
        One drain at a time: a second caller while one runs returns 0 at once."""
        if not self._draining.acquire(blocking=False):
            return 0
        try:
            return self._drain_once()
        finally:
            self._draining.release()

    def _drain_once(self) -> int:
        answered = 0
        for item in self.queue.pending():
            workload = self.config.workloads.get(item.workload)
            if workload is None or not self.quotas.slots.acquire(workload.workload_class, 0.0):
                continue
            try:
                answered += self._retry(workload, item)
            finally:
                self.quotas.slots.release(workload.workload_class)
        return answered

    def _retry(self, workload: Workload, item: Deferred) -> int:
        ctx = _Ctx(rid=item.request_id, entry={"workload": workload.name, "workload_class": workload.workload_class,
                                               "data_class": item.data_class, "deferred_id": item.id})
        targets, skipped = plan(self.config, workload, item.data_class)
        result, target, attempts = self._climb(targets, item.body)
        ctx.entry.update(attempts=attempts, skipped=skipped or None)
        if result is not None and result.data is not None and target is not None:
            self.audit.record(ctx.done(status="answered", level=target.level, degraded=target.degraded,
                                       upstream=target.upstream, model=target.model, http_status=200,
                                       tokens=_tokens(result.data.get("usage"))),
                              content={"choices": result.data["choices"]})
            self.queue.settle(item, _answer(result.data, ctx.rid, workload.name, target),
                              _gateway_headers(ctx.rid, workload.name, target))
            return 1
        self.queue.settle(item, None)
        if item.status == "failed":
            self.audit.record(ctx.done(status="failed", reason="deferred_gave_up", http_status=503))
        return 0

    def deferred(self, deferred_id: str) -> Reply:
        """The outcome of a deferred request: still queued (202), its answer (200) or given up (503)."""
        item = self.queue.fetch(deferred_id)
        if item is None:
            return _error(404, "no deferred request with that id; the queue is in memory, so a restart forgets it",
                          "not_found", "-")
        if item.status == "answered" and item.answer is not None:
            return Reply(200, item.answer, item.headers)
        if item.status == "failed":
            return _error(503, f"no upstream answered after {item.tries} tries; the request was given up",
                          "deferred_gave_up", item.request_id)
        return Reply(202, {"object": "gateway.deferred", "id": item.id, "status": "queued", "answer": None,
                           "message": "no answer yet", "tries": item.tries},
                     {"X-Gateway-Request-Id": item.request_id, "X-Gateway-Level": "L4"})
