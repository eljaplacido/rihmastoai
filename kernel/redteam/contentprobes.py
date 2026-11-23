"""Probes that judge what an answer holds: security headers, error pages that leak, path traversal
and reflected injection. Each takes the run and its layer's tally, sends its requests through the
run's scoped client, and returns what it measured in a sentence.

Every probe here is a GET. Path parameters are filled from the project's fixed interface; the
deployment's root and a path no interface names are probed too, since a 404 page can leak or
reflect as well as a route.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse

from kernel.redteam.client import Answer
from kernel.redteam.probing import NO_INTERFACE, PAGE_VALUE, ROOT, Route, Run, Tally

MAX_HEADER_ROUTES = 8
MAX_ERROR_ROUTES = 3
MAX_TRAVERSAL_ROUTES = 4
MAX_INJECTION_ROUTES = 10
UNKNOWN = "/rihmasto-missing"
# What a browser asks for: a server that writes HTML (and its headers) only for browsers is judged as one.
BROWSER = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
# Query parameters the injection marker is sent in, all at once: a route reflects whichever it reads.
QUERY_NAMES = ("q", "search", "term", "query", "s", "name", "keyword", "filter")

# -- security headers ------------------------------------------------------------------------------

_UNSAFE_REFERRER = ("unsafe-url", "no-referrer-when-downgrade")


def header_gaps(a: Answer) -> list[tuple[str, str]]:
    """(rule, what is missing) for one answer: nosniff on any body, the page headers on HTML."""
    gaps = []
    if a.body and a.header("x-content-type-options").strip().lower() != "nosniff":
        gaps.append(("RT-DYN-NOSNIFF", "no X-Content-Type-Options: nosniff"))
    if not a.html:
        return gaps
    csp = a.header("content-security-policy")
    if not csp.strip():
        gaps.append(("RT-DYN-CSP", "no Content-Security-Policy"))
    if "frame-ancestors" not in csp.lower() and a.header("x-frame-options").strip().upper() not in ("DENY",
                                                                                                    "SAMEORIGIN"):
        gaps.append(("RT-DYN-FRAME", "no CSP frame-ancestors and no X-Frame-Options"))
    referrer = a.header("referrer-policy").strip().lower()
    if not referrer or referrer.split(",")[-1].strip() in _UNSAFE_REFERRER:
        gaps.append(("RT-DYN-REFERRER", f"Referrer-Policy {referrer or 'missing'}"))
    return gaps


def headers(run: Run, tally: Tally) -> str:
    """GET the root and the interface's read routes; judge each answer's security headers."""
    plans = [("/", "/")] + [(r.fill(PAGE_VALUE), r.path) for r in run.reads if r.path != "/"][:MAX_HEADER_ROUTES]
    pages = 0
    for target, route in plans:
        a = tally.count(run.client.request("GET", target, route=route, headers=BROWSER))
        if not a.answered:
            continue
        pages += a.html
        for rule_id, missing in header_gaps(a):
            run.found(rule_id, route, f"GET {route} ({a.content_type or 'no type'}): {missing}", once=True)
    if not run.routes:
        tally.gap(f"{NO_INTERFACE}: only the root was asked")
    note = "" if pages else "; no answer was HTML, so CSP, frame protection and referrer policy did not apply"
    return f"{tally.answered} answers checked, {pages} of them HTML pages{note}"


# -- error pages that leak -------------------------------------------------------------------------

_LEAKS = (
    ("a stack trace", re.compile(
        r"Traceback \(most recent call last\)|File \"[^\"\n]{1,200}\", line \d+|\bat [\w$.]+\([\w$]+\.java:\d+\)"
        r"|goroutine \d+ \[running\]|\bat [^\s()]{1,200} \((?:/|[A-Za-z]:\\)[^)\n]{1,200}:\d+:\d+\)"
        r"|\.rb:\d+:in `|Stack trace:\s*#0|\bat [\w.<>`]{1,200}\(.{0,200}\) in .{1,200}:line \d+")),
    ("a database error", re.compile(
        r"sqlite3\.\w*Error|\bOperationalError\b|error in your SQL syntax|\bpsycopg2?\.\w|\bORA-\d{5}\b"
        r"|SQLSTATE\[|unterminated quoted string|\bSQLITE_ERROR\b")),
    # A server's own file: under a system or home folder, of a language that runs on the server (a
    # page's script, /app/main.js, is a URL, not a leak), and not part of a URL (no host before it).
    ("a file path", re.compile(
        r"(?<![\w.:/-])/(?:home|usr|var|opt|srv|root|app|tmp|Users)/[\w.-]+(?:/[\w.-]+)*\.(?:py|pyc|rb|php|java|go|cs)\b"
        r"|\b[A-Za-z]:\\(?:[\w .-]+\\)+[\w .-]+\.(?:py|pyc|js|ts|rb|php|java|cs|dll)\b"
        r"|\bsite-packages[/\\]|\bnode_modules[/\\]")),
)


def _pathlike(segment: str) -> bool:
    decoded = urllib.parse.unquote(urllib.parse.unquote(segment))
    return any(c in decoded for c in "/\\:")


def _echoes(target: str) -> list[str]:
    """What the request itself put into the answer (the target, a path segment that decodes to a path,
    the query values), in the forms a server writes it back: raw, decoded once or twice, HTML-escaped
    and JSON-escaped. A plain word of the path is kept, so a leaked path that contains it is still seen."""
    path, _, query = target.partition("?")
    segments = [s for s in path.split("/") if _pathlike(s)]
    parts = [target, path, *segments, *(v for _, v in urllib.parse.parse_qsl(query, keep_blank_values=True))]
    forms: set[str] = set()
    for part in parts:
        once = urllib.parse.unquote(part)
        forms |= {part, once, urllib.parse.unquote(once), html.escape(once), json.dumps(once)[1:-1]}
    return sorted((f for f in forms if len(f) >= 4), key=len, reverse=True)


def leak(a: Answer) -> tuple[str, str] | None:
    """(what leaked, the matched text) for an error answer, ignoring what the request itself sent."""
    if not a.answered or (a.status or 0) < 400 or not a.body:
        return None
    text = a.body
    for echo in _echoes(a.target):
        text = text.replace(echo, " ")
    for kind, pattern in _LEAKS:
        m = pattern.search(text)
        if m:
            return kind, m.group(0)[:80]
    return None


def errors(run: Run, tally: Tally) -> str:
    """Ask for what fails: an unknown path, a parameter no route expects, a broken percent-escape."""
    plans = [(UNKNOWN, "/{unknown}"), ("/?rihmasto=%zz", "/")]
    plans += [(r.fill_last("rihmasto'\"probe"), r.path) for r in run.reads if r.params][:MAX_ERROR_ROUTES]
    for target, route in plans:
        tally.count(run.client.request("GET", target, route=route))
    if not run.routes:
        tally.gap(f"{NO_INTERFACE}: no route's parameters were tried")
    return f"{len(plans)} requests made to fail"


def inspect_errors(run: Run) -> int:
    """Look for leaks in every error answer of the run, whichever probe asked. Returns how many."""
    inspected = 0
    for a in run.client.answers:
        if a.answered and (a.status or 0) >= 400:
            inspected += 1
            hit = leak(a)
            if hit:
                run.found("RT-DYN-LEAK", a.route, f"{a.method} {a.route} answered {a.status} with {hit[0]}: {hit[1]}")
    return inspected


# -- path traversal --------------------------------------------------------------------------------

# (name, one step up, the separator inside the destination). `....//` is what a filter that strips
# `../` once leaves as `../`.
ESCAPES = (("plain", "../", "/"), ("encoded", "..%2f", "%2f"), ("dot-encoded", "%2e%2e%2f", "%2f"),
           ("backslash-encoded", "..%5c", "%5c"), ("double-encoded", "%252e%252e%252f", "%252f"),
           ("doubled", "....//", "/"))
# An absolute name a join takes as the whole path: (the name, encoded; the file it names).
ABSOLUTE = (("%2Fetc%2Fpasswd", "etc/passwd"), ("C%3A%5CWindows%5Cwin.ini", "windows/win.ini"))
_PY_IMPORT = re.compile(r"(?m)^(?:from [\w.]+ import \S|import [\w.]+)")
_PY_DEF = re.compile(r"(?m)^[ \t]*(?:async[ \t]+)?def \w+\(")
_PASSWD = re.compile(r"(?m)^root:[^:\n]*:0:0:")
_WIN_INI = re.compile(r"(?im)^\[(?:fonts|extensions|mci extensions)\]|for 16-bit app support")
# (steps up, file, what it is): the product's own source in the factory's layout (app/static beside
# app/server.py), and two files every Unix and Windows host has.
DESTINATIONS = ((1, "server.py", "the product's Python source"), (2, "app/server.py", "the product's Python source"),
                (8, "etc/passwd", "/etc/passwd"), (8, "windows/win.ini", "win.ini"))


def _shows(dest: str, body: str) -> bool:
    if dest.endswith(".py"):
        return bool(_PY_IMPORT.search(body) and _PY_DEF.search(body))
    return bool((_PASSWD if dest == "etc/passwd" else _WIN_INI).search(body))


def _disclosed(body: str) -> bool:
    return any(_shows(dest, body) for _, dest, _ in DESTINATIONS)


def _attempts_of() -> list[tuple[str, str, str, str]]:
    """(kind, payload, destination, what it is) in the order a traversal is tried."""
    out = [(kind, up * depth + dest.replace("/", sep), dest, what)
           for kind, up, sep in ESCAPES for depth, dest, what in DESTINATIONS]
    return out + [("absolute", name, dest, dest.rsplit("/", 1)[-1]) for name, dest in ABSOLUTE]


def _traverse(run: Run, tally: Tally, route: Route) -> None:
    for kind, payload, dest, what in _attempts_of():
        a = tally.count(run.client.request("GET", route.fill_last(payload, encoded=True), route=route.path))
        if a.answered and 200 <= (a.status or 0) < 300 and _shows(dest, a.body):
            run.found("RT-DYN-TRAVERSAL", route.path,
                      f"GET {route.path} with {kind} traversal ({payload}) answered {a.status} with {what}")
            return


def traversal(run: Run, tally: Tally) -> str:
    """Climb out of each route's folder, plain and encoded, toward files a traversal would reveal."""
    routes = [r for r in run.reads if r.params][:MAX_TRAVERSAL_ROUTES] + [ROOT]
    for route in routes:
        base = tally.count(run.client.request("GET", route.fill_last("rihmasto-missing.txt"), route=route.path))
        if base.answered and _disclosed(base.body):
            tally.gap(f"{route.path} answers such content for any name, so a traversal there cannot be told apart")
            continue
        _traverse(run, tally, route)
    if not run.routes:
        tally.gap(f"{NO_INTERFACE}: only the root was climbed")
    return (f"{len(routes)} route(s) climbed with {len(ESCAPES)} escapes toward {len(DESTINATIONS)} files, "
            "stopping at the first that answers")


# -- reflected injection ---------------------------------------------------------------------------

def injection(run: Run, tally: Tally) -> str:
    """Send a marker that would open an HTML tag; report it when it comes back unescaped in a page."""
    tag = f"rt{run.nonce}"
    payload = f"\"'><{tag}>"
    encoded = urllib.parse.quote(payload, safe="")
    plans = [(f"/rihmasto-{encoded}", "/{unknown}", "an unknown path")]
    query = "&".join(f"{name}={encoded}" for name in QUERY_NAMES)
    for r in run.reads[:MAX_INJECTION_ROUTES]:
        if r.params:
            plans.append((r.fill(payload), r.path, "the path parameter " + ", ".join(r.params)))
        plans.append((r.fill(PAGE_VALUE) + "?" + query, r.path, "a query parameter (" + ", ".join(QUERY_NAMES) + ")"))
    for target, route, where in plans:
        a = tally.count(run.client.request("GET", target, route=route, headers=BROWSER))
        if a.answered and a.html and f"<{tag}>" in a.body.lower():
            kind = a.content_type or "an untyped page"
            run.found("RT-DYN-REFLECT", route, f"GET {route}: a tag sent in {where} came back unescaped in {kind}")
    if not run.routes:
        tally.gap(f"{NO_INTERFACE}: only an unknown path was tried")
    return f"a tag marker sent in {len(plans)} place(s); only an HTML answer counts as reflected"
