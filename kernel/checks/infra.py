"""Infrastructure checks of a running service (FR-ITO1 with FR-CHK1): the app, its certificates, its names.

- **app**: the service's health endpoint answers: its status code, its latency against a budget (``max_ms``, 1000)
  and the version it reports (a JSON ``version`` field or an ``X-Version`` header). The address is ``url``, else
  each environment where the project runs, with ``path`` (``/health``) added;
- **tls**: for each https target (``targets``, else where it runs and every https endpoint a binding names), the
  days until its certificate expires: failed under ``fail_days`` (7), and said as a warning under ``warn_days`` (21);
- **dns**: each host (``hosts``, else every host where it runs or a binding names) resolves, and something answers
  on its port, both within a timeout. Nothing is sent but the connection itself.

Each says "not measured" with why when it has no target. Proxies in the environment are not used: a check asks the
address itself. The ways out (``fetch``, ``tls_days``, ``resolve``, ``connect``) are module names a test replaces.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from kernel.checks import Check, Ctx, not_measured, result
from kernel.checks import infra_settings as settings
from kernel.checks import infra_targets as tg
from kernel.checks.probe import _number, tls_days_left

tls_days = tls_days_left                          # replaced in tests: a stand-in certificate
connect = socket.create_connection
VERSION_HEADERS = ("X-Version", "X-App-Version", "X-Build")


number = _number                  # a setting that is a whole number, as the probe reads its own


class NotHttp(OSError):
    """Something answered, but not with HTTP (an SSH or database port, a closed stream): an OSError, so every caller
    that handles an unreachable address handles this too and records the check as failed, never crashes."""


def fetch(url: str, timeout: float) -> dict[str, Any]:
    """GET ``url`` without a proxy: status, milliseconds, a few headers and the start of the body."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": "rihmasto-check"}, method="GET")
    started = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as res:
            body, status, headers = res.read(65536), res.status, dict(res.headers.items())
    except urllib.error.HTTPError as exc:
        body, status, headers = b"", exc.code, dict(exc.headers.items()) if exc.headers else {}
        exc.close()
    except http.client.HTTPException as exc:          # BadStatusLine, RemoteDisconnected's kin, IncompleteRead
        raise NotHttp(f"it answered, but not with HTTP ({type(exc).__name__})") from exc
    return {"status": status, "ms": (time.monotonic() - started) * 1000, "headers": headers, "body": body}


def version_of(got: dict[str, Any]) -> str | None:
    for name in VERSION_HEADERS:
        found = next((v for k, v in got["headers"].items() if k.lower() == name.lower()), None)
        if found:
            return str(found)[:60]
    try:
        doc = json.loads(got["body"].decode("utf-8", "replace") or "null")
    except ValueError:
        return None
    if isinstance(doc, dict):
        for key in ("version", "app_version", "build"):
            if isinstance(doc.get(key), (str, int, float)) and not isinstance(doc.get(key), bool):
                return str(doc[key])[:60]
    return None


def _with_path(url: str, path: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.path not in ("", "/") or not path:
        return url
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/" + path.lstrip("/"), "", ""))


def app(ctx: Ctx) -> dict[str, Any]:
    if bad := settings.unusable("app", ctx.config):
        return not_measured(bad)
    given = tg.as_list(ctx.config.get("url"))
    path = str(ctx.config.get("path") if ctx.config.get("path") is not None else "/health")
    targets = given or [_with_path(u["url"], path) for u in tg.urls(ctx.project)]
    if not targets:
        return not_measured("no address to ask: the project runs nowhere yet and no url is given (give this check "
                            "a url, or deliver the project to an environment)")
    expect, budget = number(ctx, "expect_status", 200), number(ctx, "max_ms", 1000)
    lines, problems, measured = [], [], []
    for url in targets[:5]:
        try:
            got = fetch(url, timeout=max(1.0, min(30.0, budget / 1000 * 5)))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            why = getattr(exc, "reason", exc)
            problems.append(f"{url} could not be reached ({why})")
            lines.append(f"GET {url}: {why}")
            continue
        version = version_of(got)
        measured.append({"url": url, "status": got["status"], "ms": round(got["ms"]), "version": version})
        lines.append(f"GET {url}: {got['status']} in {got['ms']:.0f} ms (budget {budget} ms)"
                     + (f", version {version}" if version else ", no version reported"))
        if got["status"] != expect:
            problems.append(f"{url}: status {got['status']}, expected {expect}")
        if got["ms"] > budget:
            problems.append(f"{url}: {got['ms']:.0f} ms, over the {budget} ms budget")
    if problems:
        return result("failed", "; ".join(problems), lines, targets=measured)
    slowest = max(m["ms"] for m in measured)
    return result("passed", f"{len(measured)} health endpoint(s) answered {expect}, the slowest in {slowest} ms",
                  lines, targets=measured)


def _https_targets(ctx: Ctx) -> list[str]:
    given = tg.as_list(ctx.config.get("targets"))
    if given:
        return given
    found = [u["url"] for u in tg.urls(ctx.project)]
    for b in tg.bindings(ctx.project):
        found += [r["endpoint"] for r in b["environments"] if r["endpoint"]]
    out: list[str] = []
    for url in found:
        if urllib.parse.urlsplit(url).scheme == "https" and url not in out:
            out.append(url)
    return out


# OpenSSL's verify codes a person can act on: expired, not valid yet, not trusted, another name.
CERT_SAID = {10: "has expired", 9: "is not valid yet", 2: "is not trusted (its issuer is unknown here)",
             18: "is not trusted (self-signed)", 19: "is not trusted (a self-signed or private CA in its chain)",
             20: "is not trusted (issued by a CA unknown here, such as a private CA)",
             21: "is not trusted (its chain is incomplete)", 62: "does not match the name it is asked for"}


def unreadable(host: str, exc: BaseException) -> str:
    """Why a certificate could not be read, in words a person acts on: expired and untrusted said as such."""
    code = getattr(exc, "verify_code", None)
    if isinstance(exc, ssl.SSLCertVerificationError) and code in CERT_SAID:
        return f"{host}: the certificate {CERT_SAID[code]}"
    if isinstance(exc, ssl.SSLCertVerificationError):
        return f"{host}: the certificate failed verification ({getattr(exc, 'verify_message', '') or exc})"
    return f"{host}: the certificate could not be read ({type(exc).__name__})"


def tls(ctx: Ctx) -> dict[str, Any]:
    if bad := settings.unusable("tls", ctx.config):
        return not_measured(bad)
    targets = [u for u in _https_targets(ctx) if urllib.parse.urlsplit(u).scheme == "https"]
    if not targets:
        return not_measured("no https address to read a certificate from: where it runs and its bindings are not "
                            "https (give this check targets)")
    warn, fail = number(ctx, "warn_days", 21), number(ctx, "fail_days", 7)
    lines, failing, warning = [], [], []
    rows: list[dict[str, Any]] = []
    for url in targets[:10]:
        hp = tg.host_port(url)
        if hp is None:
            failing.append(f"{url}: not an address")
            continue
        try:
            days = float(tls_days(hp[0], hp[1], 10))
        except (OSError, ssl.SSLError, ValueError) as exc:
            failing.append(unreadable(hp[0], exc))
            lines.append(f"{hp[0]}:{hp[1]}: {type(exc).__name__}: {exc}")
            continue
        rows.append({"host": hp[0], "port": hp[1], "days": round(days, 1)})
        lines.append(f"{hp[0]}:{hp[1]}: the certificate expires in {days:.1f} days")
        if days < fail:
            failing.append(f"{hp[0]} expires in {days:.1f} days (under {fail})")
        elif days < warn:
            warning.append(f"{hp[0]} expires in {days:.1f} days (under {warn}: renew it soon)")
    if failing:
        renew = any("expire" in f for f in failing)          # expired or expiring: renew; else trust or name
        return result("failed", "; ".join(failing), lines, certificates=rows, remedy="renew" if renew else "tls")
    soonest = min((r["days"] for r in rows), default=None)
    summary = (f"{len(rows)} certificate(s), the soonest expiring in {soonest:.1f} days"
               + (f"; warning: {'; '.join(warning)}" if warning else ""))
    return result("passed", summary, lines, certificates=rows, warning=warning)


def resolve(host: str, timeout: float) -> list[str]:
    """The addresses ``host`` resolves to, within ``timeout`` seconds (the resolver has no timeout of its own)."""
    out: dict[str, Any] = {}

    def look() -> None:
        try:
            out["addrs"] = sorted({a[4][0] for a in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
        except OSError as exc:
            out["error"] = exc

    t = threading.Thread(target=look, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"{host} did not resolve within {timeout:g} s")
    if "error" in out:
        raise out["error"]
    return list(out["addrs"])


def _host_targets(ctx: Ctx) -> list[dict[str, Any]]:
    given = tg.as_list(ctx.config.get("hosts"))
    if not given:
        return tg.hosts(ctx.project)
    found = [settings.host_entry(h) for h in given]
    return [{"host": hp[0], "port": hp[1], "why": "given"} for hp in found if hp]


def dns(ctx: Ctx) -> dict[str, Any]:
    if bad := settings.unusable("dns", ctx.config):
        return not_measured(bad)
    targets = _host_targets(ctx)
    if not targets:
        return not_measured("no host to resolve: the project runs nowhere and no binding names an address (give "
                            "this check hosts, such as db.example.org:5432)")
    timeout = number(ctx, "timeout_ms", 3000) / 1000
    lines, problems, rows = [], [], []
    for t in targets[:10]:
        try:
            addrs = resolve(t["host"], timeout)
        except (OSError, TimeoutError) as exc:
            problems.append(f"{t['host']} does not resolve ({type(exc).__name__})")
            lines.append(f"{t['host']}: does not resolve: {exc}")
            continue
        started = time.monotonic()
        try:
            with connect((t["host"], t["port"]), timeout=timeout):
                pass
        except OSError as exc:
            problems.append(f"{t['host']}:{t['port']} resolves but nothing answers ({type(exc).__name__})")
            lines.append(f"{t['host']} -> {', '.join(addrs[:3])}; {t['port']}: {exc}")
            continue
        ms = round((time.monotonic() - started) * 1000)
        rows.append({"host": t["host"], "port": t["port"], "ms": ms})
        lines.append(f"{t['host']} -> {', '.join(addrs[:3])}; port {t['port']} answers in {ms} ms ({t['why']})")
    if problems:
        return result("failed", "; ".join(problems), lines, reached=rows, remedy="network")
    return result("passed", f"{len(rows)} host(s) resolve and answer", lines, reached=rows)


CHECKS = (
    Check("app", "App health endpoint", "the service's health endpoint: status code, latency against a budget and "
          "the version it reports", app, options=("url", "path", "expect_status", "max_ms"), every="15m"),
    Check("tls", "TLS certificates", "days until each https target's certificate expires, warned and failed "
          "before it does", tls, options=("targets", "warn_days", "fail_days"), every="1d"),
    Check("dns", "DNS and reachability", "each host resolves and answers on its port, within a timeout", dns,
          options=("hosts", "timeout_ms"), every="1h"),
)
