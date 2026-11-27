"""The observer's page (FR-SHR1): what a guest opens from an observer link, served by the cockpit at ``/o/``.

A guest reaches it on the same machine, or through an ssh tunnel (``ssh -L <port>:127.0.0.1:<port> <host>``): a
tunnel is an ssh login on the sharer's host, so only from a restricted account that may forward that one port
(docs/guides/observer-links.md). It is one static page (cockpit/static/observer.html) with its script
and style sheet from the cockpit's own static files, and four JSON calls, each from the page's own origin:

- ``POST /o/api/open`` ``{link}``: the link's token (read from after ``#``) is exchanged for this tab's session;
- ``POST /o/api/view`` ``{session, project}``: what the guest sees (kernel/observe_view.py), read only;
- ``POST /o/api/comment`` ``{session, project, text, about}``: a comment signed as the guest, marked as a guest's;
- ``POST /o/api/suggest`` ``{session, question, text}``: a suggested answer to an intake question, which waits for
  a person to confirm it (only on a project link the sharer opened for defining the project together).

The page is strict as the outside reviewer's page is (kernel/hitl_page.py, whose helpers it uses): no inline script
or style, nothing from elsewhere, no frame, no referrer, no cache. A guest's session never opens the cockpit's API:
a request carrying one is refused (``guest_request``) with 403 on every route.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kernel import hitl_page, observe, observe_guard, observe_view
from kernel.canon import DecisionRefused
from kernel.store import Factory

STATIC = Path(__file__).resolve().parent.parent / "cockpit" / "static"
PAGE = "observer.html"
GUEST_HEADER = "X-Rihmasto-Observer"
REFUSED = "An observer only watches: a guest's link never decides, runs or changes anything."


def ours(path: str) -> bool:
    p = urlsplit(path).path
    return p == "/o" or p.startswith("/o/")


def guest_request(handler: Any) -> bool:
    """Whether a cockpit request carries a guest's session (or says it is a guest's): refused, whatever it asks."""
    auth = str(handler.headers.get("Authorization") or "")
    token = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""
    # a cockpit session is 43 characters of token_urlsafe(32); a guest's is "os_" or "ob_" and those 43
    return bool(handler.headers.get(GUEST_HEADER)) or (len(token) > 43 and token.startswith(("os_", "ob_")))


def _open(factory: Factory, body: dict[str, Any], addr: str) -> tuple[int, dict[str, Any]]:
    try:
        return 200, observe.open_link(factory, str(body.get("link") or ""))
    except observe.ObserveRefused as exc:
        if hitl_page._too_many(addr):
            return 429, {"error": "Too many tries. Wait a minute, then open your link again."}
        hitl_page._failed(addr)
        return 403, {"error": str(exc)}


def _session(factory: Factory, body: dict[str, Any]) -> dict[str, Any]:
    return observe.session(factory, str(body.get("session") or ""))


def _view(factory: Factory, body: dict[str, Any], addr: str) -> tuple[int, dict[str, Any]]:
    link = _session(factory, body)
    return 200, observe_view.view(factory, link, str(body.get("project") or "") or None)


def _comment(factory: Factory, body: dict[str, Any], addr: str) -> tuple[int, dict[str, Any]]:
    link = _session(factory, body)
    try:
        row = observe.comment(factory, link, str(body.get("project") or ""), str(body.get("text") or ""),
                              str(body.get("about") or ""))
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 201, {"comment": {k: row[k] for k in ("id", "project", "about", "text", "at", "guest")}}


def _suggest(factory: Factory, body: dict[str, Any], addr: str) -> tuple[int, dict[str, Any]]:
    link = _session(factory, body)
    try:
        row = observe.suggest(factory, link, str(body.get("question") or ""), str(body.get("text") or ""))
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 201, {"suggestion": {k: row[k] for k in ("id", "question", "text", "state", "at")}}


CALLS = {"/o/api/open": _open, "/o/api/view": _view, "/o/api/comment": _comment, "/o/api/suggest": _suggest}


def _post(handler: Any, factory: Factory, path: str, raw: bytes | None) -> tuple[int, dict[str, Any]]:
    call = CALLS.get(path)
    if call is None:
        return 404, {"error": "not found"}
    if not hitl_page._same_origin(handler):
        return 403, {"error": "This page answers its own page only."}
    body = hitl_page._body(handler, raw)
    if body is None:
        return 400, {"error": "send a small JSON object"}
    try:
        return call(factory, body, hitl_page.client_of(handler))
    except observe.ObserveRefused as exc:
        return 403, {"error": str(exc)}
    except observe_guard.GuestTooFast as exc:      # a guest cannot flood the sharer (FR-SHR2)
        return 429, {"error": str(exc)}
    except DecisionRefused as exc:
        return 403, {"error": str(exc)}
    except Exception as exc:  # never shown: the page gets a plain line, the log the reason
        sys.stderr.write(f"observer page: {type(exc).__name__}: {exc}\n")
        return 500, {"error": "Something went wrong on our side. Try again in a moment."}


def serve(handler: Any, factory: Factory, raw: bytes | None = None) -> None:
    """Answer one request for the observer page: GET the page, POST its four calls."""
    path = urlsplit(handler.path).path
    if handler.command == "GET" and path in ("/o", "/o/"):
        return hitl_page._send(handler, 200, (STATIC / PAGE).read_bytes(), "text/html; charset=utf-8")
    if handler.command == "POST":
        status, out = _post(handler, factory, path, raw)
        return hitl_page._json(handler, status, out)
    return hitl_page._json(handler, 404 if handler.command == "GET" else 405, {"error": "not found"})
