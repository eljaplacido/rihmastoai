"""Probes that judge how a server handles the protocol: methods its interface does not declare,
malformed and oversized bodies, cross-origin reads, and rate limits on write routes.

Each takes the run and its layer's tally, sends its requests through the run's scoped client, and
returns what it measured in a sentence. Requests that could change data are kept harmless:

- an undeclared write method goes only to a path with a parameter, set to `PROBE_VALUE`, which
  names no real record; a path without one (`DELETE /items`) would act on the whole collection, so
  it is never sent there, and the reason says how many paths that left out;
- a body is malformed (truncated JSON, invalid UTF-8, a declared size never sent), or, for the rate
  limit, JSON cut short, so no server can create a record from it;
- on `production` the probes that write (methods other than TRACE, bodies, rate limiting) are not
  sent at all: those layers are not measured, and say so. Probe staging or a twin for them.

The rate limit probe is bounded: at most `RATE_BURST` requests, and it stops at the first refusal.
"""

from __future__ import annotations

import time
from collections import Counter

from kernel.redteam.probing import JSON, NO_INTERFACE, PAGE_VALUE, PROBE_VALUE, Route, Run, Tally

MAX_METHOD_PATHS = 12
MAX_BODY_ROUTES = 3
MAX_OVERSIZE_ROUTES = 2
MAX_CORS_ROUTES = 2
TAMPERED = ("POST", "PUT", "PATCH", "DELETE")
DECLARED = 1024 * 1024 * 1024   # more than any form or upload route needs: a cap below it refuses at once
SENT = 1024 * 1024
OVERSIZE_WAIT = 2.0
RATE_BURST = 12
RATE_BODY = b'{"rihmasto-probe": '   # JSON cut short: a server that takes it cannot create a record from it
PROBE_ORIGIN = "http://rihmasto-probe.invalid"
MALFORMED = (("truncated JSON", b'{"rihmasto": '), ("invalid UTF-8", b'{"name": "\xff\xfe"}'))
NO_WRITES = "the interface declares no write route (POST, PUT or PATCH)"
READ_ONLY = "production"
READ_ONLY_REASON = ("not sent: production is probed read-only, since a probe that writes could change real data; "
                    "probe staging or a twin for this layer")


def read_only(run: Run) -> bool:
    """Whether the run probes production, where nothing that could write is sent."""
    return run.client.permit.environment == READ_ONLY


def _success(status: int | None) -> bool:
    return status is not None and 200 <= status < 300


def _no_writes(run: Run, tally: Tally) -> str:
    """Why a write probe has nothing to send: not applicable when the interface has no write route,
    not measured when there is no interface to tell."""
    if run.routes:
        tally.applicable = False
        return NO_WRITES
    tally.gap(f"{NO_INTERFACE}, so no write route is known")
    return ""


# -- method tampering ------------------------------------------------------------------------------

def _tamper(run: Run, tally: Tally, path: str, declared: set[str]) -> None:
    accepted = []
    for method in (m for m in TAMPERED if m not in declared):
        body = None if method == "DELETE" else b"{}"
        a = tally.count(run.client.request(method, Route(method, path).fill(PROBE_VALUE), route=path, body=body,
                                           headers=JSON if body else None))
        if _success(a.status):
            accepted.append(f"{method} answered {a.status}")
    if accepted:
        run.found("RT-DYN-METHOD", path,
                  f"{path}: {', '.join(accepted)}; the interface declares {', '.join(sorted(declared))} only")


def methods(run: Run, tally: Tally) -> str:
    """Send each write method a path's interface does not declare (paths with a parameter only, and
    none on production), and TRACE to the root."""
    declared: dict[str, set[str]] = {}
    for r in run.routes:
        declared.setdefault(r.path, set()).add(r.method)
    named = [p for p in declared if Route("GET", p).params]
    paths = [] if read_only(run) else named[:MAX_METHOD_PATHS]
    for path in paths:
        _tamper(run, tally, path, declared[path])
    a = tally.count(run.client.request("TRACE", "/", route="/"))
    if _success(a.status):
        run.found("RT-DYN-METHOD", "/", f"TRACE / answered {a.status}: the server echoes requests back")
    if not run.routes:
        tally.gap(f"{NO_INTERFACE}: only TRACE was tried")
    left = len(declared) - len(named)
    said = f"undeclared write methods sent to {len(paths)} path(s) with a parameter, and TRACE to the root"
    if read_only(run):
        said = "TRACE to the root only: production is probed read-only, so no write method was sent"
    elif left:
        said += (f"; {left} path(s) without a parameter were sent none, since a write there would act on the "
                 "whole collection")
    return said


# -- malformed and oversized bodies ----------------------------------------------------------------

def _malformed(run: Run, tally: Tally, route: Route) -> None:
    for label, body in MALFORMED:
        a = run.client.request(route.method, route.fill(PROBE_VALUE), route=route.path, body=body, headers=JSON)
        tally.count(a, judged=True if a.dropped else None)
        if a.dropped or (a.status or 0) >= 500:
            said = f"answered {a.status}" if a.answered else f"gave no answer ({a.error})"
            run.found("RT-DYN-MALFORMED", route.path, f"{route.method} {route.path} with {label} {said}")


def _oversize(run: Run, tally: Tally, route: Route) -> None:
    a = run.client.declared_body(route.method, route.fill(PROBE_VALUE), route=route.path, declared=DECLARED,
                                 send=SENT, wait=OVERSIZE_WAIT)
    waited = a.error == "timeout"
    tally.count(a, judged=True if waited or a.error == "closed" else None)
    if waited:
        run.found("RT-DYN-OVERSIZE", route.path,
                  f"{route.method} {route.path} declaring {DECLARED // 2**20} MB: still waiting {OVERSIZE_WAIT:g} s "
                  f"after {SENT // 2**20} MB had arrived, so it reads whatever length a client declares")
    elif (a.status or 0) >= 500:
        run.found("RT-DYN-OVERSIZE", route.path,
                  f"{route.method} {route.path} declaring {DECLARED // 2**20} MB answered {a.status}")


def bodies(run: Run, tally: Tally) -> str:
    """Send each write route malformed JSON and invalid UTF-8, and declare a body far too large."""
    writes = run.writes[:MAX_BODY_ROUTES]
    if writes and read_only(run):
        tally.gap(READ_ONLY_REASON)
        return ""
    if not writes:
        return _no_writes(run, tally)
    for route in writes:
        _malformed(run, tally, route)
    for route in writes[:MAX_OVERSIZE_ROUTES]:
        _oversize(run, tally, route)
    return (f"{len(writes)} write route(s) sent {len(MALFORMED)} malformed bodies each; "
            f"{min(len(writes), MAX_OVERSIZE_ROUTES)} declared a {DECLARED // 2**20} MB body")


# -- cross-origin reads ----------------------------------------------------------------------------

def _cors_problem(allow: str, credentials: str, origin: str) -> str:
    """What a CORS answer lets another site read. Echoing any origin, or `null`, without credentials
    exposes no more than `*`, which a public API may send; with credentials it hands any site the
    visitor's session."""
    creds = credentials.strip().lower() == "true"
    if not creds:
        return ""
    if allow.strip() == origin:
        return "Access-Control-Allow-Origin echoes it, with credentials"
    if allow.strip() == "*":
        return "Access-Control-Allow-Origin * with credentials"
    return ""


def cors(run: Run, tally: Tally) -> str:
    """Ask from a foreign origin and from `null`, and preflight a write; judge what is allowed."""
    plans: list[tuple[str, str, str, str, dict[str, str]]] = [("GET", "/", "/", PROBE_ORIGIN, {}),
                                                              ("GET", "/", "/", "null", {})]
    reads = [r for r in run.reads if r.path != "/"][:MAX_CORS_ROUTES]
    plans += [("GET", r.fill(PAGE_VALUE), r.path, PROBE_ORIGIN, {}) for r in reads]
    if run.writes:
        w = run.writes[0]
        preflight = {"Access-Control-Request-Method": w.method}
        plans.append(("OPTIONS", w.fill(PROBE_VALUE), w.path, PROBE_ORIGIN, preflight))
    for method, target, route, origin, extra in plans:
        a = tally.count(run.client.request(method, target, route=route, headers={"Origin": origin, **extra}))
        problem = _cors_problem(a.header("access-control-allow-origin"), a.header("access-control-allow-credentials"),
                                origin)
        if problem:
            run.found("RT-DYN-CORS", route, f"{method} {route} with Origin {origin}: {problem}", once=True)
    if not run.routes:
        tally.gap(f"{NO_INTERFACE}: only the root was asked")
    return f"{len(plans)} request(s) from a foreign origin"


# -- rate limiting ---------------------------------------------------------------------------------

def ratelimit(run: Run, tally: Tally) -> str:
    """Send one write route up to `RATE_BURST` empty writes in a row; a 429 (or 503 with Retry-After) stops it."""
    if run.writes and read_only(run):
        tally.gap(READ_ONLY_REASON)
        return ""
    if not run.writes:
        return _no_writes(run, tally)
    route = next((r for r in run.writes if r.method == "POST"), run.writes[0])
    started, statuses = time.monotonic(), Counter[int]()
    for n in range(1, RATE_BURST + 1):
        a = run.client.request(route.method, route.fill(PROBE_VALUE), route=route.path, body=RATE_BODY,
                               headers=JSON)
        tally.count(a, judged=a.answered)
        if a.status == 429 or (a.status == 503 and a.header("retry-after")):
            return f"{route.method} {route.path} was refused with {a.status} at request {n} of at most {RATE_BURST}"
        statuses[a.status or 0] += 1
    if tally.answered == RATE_BURST:
        seen = ", ".join(f"{status} x{count}" for status, count in sorted(statuses.items()))
        run.found("RT-DYN-RATELIMIT", route.path, f"{RATE_BURST} {route.method} requests in a row to {route.path} "
                                                  f"from one client, none refused with 429 (answers: {seen})")
    return (f"{RATE_BURST} {route.method} requests to {route.path} in {time.monotonic() - started:.1f} s, "
            "the most this probe ever sends")
