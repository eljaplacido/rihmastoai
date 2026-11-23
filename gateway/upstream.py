"""One call to an OpenAI-compatible upstream, with the key read from the environment at call time.

The key is read from the environment variable the upstream names, sent as a bearer token, and kept
nowhere else: not in the config, the audit, an error message or a log line. Redirects are not
followed, so a key is never carried to a host the config does not name. An upstream answer counts
only when it is a 2xx JSON object with at least one choice; anything else is a failed rung, and the
ladder moves on. An error says what failed (`http 503`, `timed out`), never the upstream's body.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from gateway.config import Upstream

MAX_ANSWER = 16 * 1024 * 1024
# Request fields that are the gateway's own and never go upstream.
GATEWAY_FIELDS = frozenset({"data_class"})


@dataclass(frozen=True)
class UpstreamResult:
    ok: bool
    status: int | None
    data: dict | None
    error: str
    ms: float


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: a redirect would carry the Authorization header to another host."""

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        return None


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
_PROXIED = urllib.request.build_opener(_NoRedirect())


def loopback_host(host: str) -> bool:
    """Whether a host name or address is this machine's loopback."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_loopback(url: str) -> bool:
    return loopback_host(urlsplit(url).hostname or "")


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def _reason(exc: BaseException) -> str:
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in str(exc):
        return "timed out"
    reason = getattr(exc, "reason", None)
    return f"unreachable ({type(reason or exc).__name__})"


def _judge(status: int, raw: bytes, ms: float) -> UpstreamResult:
    if not 200 <= status < 300:
        return UpstreamResult(False, status, None, f"http {status}", ms)
    if len(raw) > MAX_ANSWER:
        return UpstreamResult(False, status, None, "answer too large", ms)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return UpstreamResult(False, status, None, "answer is not JSON", ms)
    if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or not data["choices"]:
        return UpstreamResult(False, status, None, "answer has no choices", ms)
    return UpstreamResult(True, status, data, "", ms)


def call_upstream(upstream: Upstream, model: str, body: dict, env: Mapping[str, str]) -> UpstreamResult:
    """Send one chat completion to ``upstream`` for ``model``. Never raises on what the upstream does."""
    payload = {k: v for k, v in body.items() if k not in GATEWAY_FIELDS} | {"model": model, "stream": False}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if upstream.api_key_env:
        key = env.get(upstream.api_key_env) or ""
        if not key:
            return UpstreamResult(False, None, None, f"no key: {upstream.api_key_env} is not set", 0.0)
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(upstream.url, data=json.dumps(payload).encode("utf-8"), headers=headers,
                                 method="POST")
    opener = _DIRECT if is_loopback(upstream.url) else _PROXIED
    t0 = time.perf_counter()
    try:
        with opener.open(req, timeout=upstream.timeout_s) as resp:
            status, raw = resp.status, resp.read(MAX_ANSWER + 1)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, b""
        exc.close()
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        return UpstreamResult(False, None, None, _reason(exc), _ms(t0))
    return _judge(status, raw, _ms(t0))
