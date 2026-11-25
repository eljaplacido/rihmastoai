"""An HTTP probe of a deployed URL (FR-CHK1): its status, how long it took, and when its TLS certificate
expires. The URL is ``url`` (http or https); the probe fails when the status is not ``expect_status`` (200),
when it takes longer than ``max_ms`` (2000), or when an https certificate expires within ``tls_days`` (14).
A URL that cannot be reached fails too: the service is down for whoever uses it. Proxies in the environment
are not used: the probe asks the address itself."""

from __future__ import annotations

import datetime as dt
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from kernel.checks import Check, Ctx, not_measured, result


def _number(ctx: Ctx, key: str, default: int) -> int:
    value = ctx.config.get(key, default)
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError(f"{key} is a whole number")
    return int(value)


def tls_days_left(host: str, port: int, timeout: float = 10) -> float:
    """Days until the certificate ``host:port`` presents expires (its chain verified as a browser would)."""
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock, \
            ctx.wrap_socket(sock, server_hostname=host) as tls:
        cert = tls.getpeercert() or {}
    not_after = str(cert.get("notAfter") or "")
    if not not_after:
        raise ssl.SSLError("the certificate has no expiry")
    ends = dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), dt.UTC)
    return (ends - dt.datetime.now(dt.UTC)).total_seconds() / 86400


def _fetch(url: str, timeout: float) -> tuple[int, float]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "rihmasto-probe"}, method="GET")
    try:
        with opener.open(req, timeout=timeout) as res:
            res.read(65536)
            status = res.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
    return status, (time.monotonic() - started) * 1000


def probe(ctx: Ctx) -> dict[str, Any]:
    url = str(ctx.config.get("url") or "").strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return not_measured("a probe needs a url (http:// or https://)")
    expect, max_ms, tls_days = _number(ctx, "expect_status", 200), _number(ctx, "max_ms", 2000), \
        _number(ctx, "tls_days", 14)
    try:
        status, ms = _fetch(url, timeout=max(1.0, min(60.0, max_ms / 1000 * 5)))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        why = getattr(exc, "reason", exc)
        return result("failed", f"{url} could not be reached ({why})", [f"GET {url}: {why}"], url=url)
    lines = [f"GET {url}: {status} in {ms:.0f} ms (expected {expect}, at most {max_ms} ms)"]
    problems = [f"status {status}, expected {expect}"] if status != expect else []
    problems += [f"{ms:.0f} ms, over {max_ms} ms"] if ms > max_ms else []
    days = None
    if parts.scheme == "https":
        try:
            days = tls_days_left(parts.hostname, parts.port or 443)
            lines.append(f"TLS certificate expires in {days:.1f} days (at least {tls_days} wanted)")
            problems += [f"the TLS certificate expires in {days:.1f} days"] if days < tls_days else []
        except (OSError, ssl.SSLError, ValueError) as exc:
            problems.append(f"the TLS certificate could not be read ({type(exc).__name__})")
    data = {"url": url, "status": status, "ms": round(ms), "tls_days": round(days, 1) if days is not None else None}
    if problems:
        return result("failed", f"{url}: " + "; ".join(problems), lines, **data)
    return result("passed", f"{url}: {status} in {ms:.0f} ms", lines, **data)


def executions(ctx: Ctx) -> dict[str, Any]:
    """A scheduled job's latest finished execution where it runs (the gcp-cloudrun road, kernel/roads_gcp_ops.py):
    passed or failed, with the last executions as evidence; not measured while none finished or no job runs."""
    from kernel import roads_gcp_ops
    from kernel.roads import slot_state

    env = str(ctx.config.get("environment") or "production")
    if env not in ("preview", "demo", "staging", "production"):
        raise ValueError("environment is preview, demo, staging or production")
    state = slot_state(ctx.project, env, "current")
    if not state or state.get("workload") != "job":
        return not_measured(f"no scheduled job runs in {env}")
    res = roads_gcp_ops.job_probe(ctx.project, env, state, record=False)
    why = res["health"].get("reason") or f"the latest execution of {state.get('job')} succeeded"
    lines = [f"{r.get('name')}: {r.get('state')}" + (f" ({r['reason']})" if r.get("reason") else "")
             for r in res.get("executions") or []]
    if res["verdict"] == "not measured":
        return not_measured(why, lines, job=state.get("job"))
    return result(res["verdict"], why, lines, job=state.get("job"), environment=env)


CHECKS = (Check("probe", "HTTP probe", "a deployed URL's status, latency and TLS expiry", probe,
                options=("url", "expect_status", "max_ms", "tls_days"), needs=("url",), every="15m"),
          Check("executions", "Scheduled job executions", "a Cloud Run job's latest execution where it runs, "
                "passed or failed (the gcp-cloudrun road)", executions, options=("environment",), every="1h"))
