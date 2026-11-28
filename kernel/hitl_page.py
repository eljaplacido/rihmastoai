"""The reviewer's page (FR-HITL1): what a person outside the system opens from their one-use link.

Served at ``/r/`` by the embed server (``python -m embed.server``, the public face IT puts behind TLS) and by the
cockpit (for a solo owner reaching it over a tunnel, and for testing). It is one static page, one script and one
style sheet from ``embed/static``, and three JSON calls:

- ``POST /r/api/open`` ``{link}``: the link's token (read from after ``#``) is exchanged, once, for a session;
- ``POST /r/api/items`` ``{session}``: the asks on that link, in their own words, and nothing else;
- ``POST /r/api/answer`` ``{session, ask, answer, comment}``: one answer, signed as the link's person.

The page is strict: a Content-Security-Policy with no inline script or style, nothing from elsewhere, no frame,
no form posting anywhere, no referrer, no cache; a POST must come from the page's own origin with JSON. A refusal
says what to do (ask for a new link). An internal error's words stay in the server's log.
"""

from __future__ import annotations

import ipaddress
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kernel import hitl_links
from kernel.canon import DecisionRefused
from kernel.store import Factory

STATIC = Path(__file__).resolve().parent.parent / "embed" / "static"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
           "Referrer-Policy": "no-referrer", "Cross-Origin-Opener-Policy": "same-origin",
           "Cross-Origin-Resource-Policy": "same-origin", "Cache-Control": "no-store",
           "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()"}
FILES = {"/r/": ("reviewer.html", "text/html; charset=utf-8"), "/r": ("reviewer.html", "text/html; charset=utf-8"),
         "/r/reviewer.js": ("reviewer.js", "text/javascript; charset=utf-8"),
         "/r/reviewer.css": ("reviewer.css", "text/css; charset=utf-8")}
MAX_BODY = 16 * 1024
OPENS_PER_MINUTE = 20          # failed opens from one address before it waits a minute
_FAILS: dict[str, list[float]] = {}
_FAILS_LOCK = threading.Lock()


def ours(path: str) -> bool:
    """Whether a request's path is the reviewer page's."""
    p = urlsplit(path).path
    return p == "/r" or p.startswith("/r/")


def _send(handler: Any, status: int, body: bytes, ctype: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    for name, value in HEADERS.items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)


def _json(handler: Any, status: int, obj: dict[str, Any]) -> None:
    _send(handler, status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")


def _allowed_origins(handler: Any) -> list[str]:
    """The configured origins this server answers (cockpit's own, public front, proxy); empty on embed.server."""
    server = getattr(handler, "server", None)
    origin = getattr(server, "origin", None)
    if not origin:
        return []
    out = [origin]
    public = getattr(server, "public_origin", None)
    if public:
        out.append(public)
    factory = getattr(server, "factory", None)
    if factory is not None:
        from kernel import access as kaccess

        acc = kaccess.load(factory)
        if acc.enforced and acc.proxy is not None:
            out.append(acc.proxy.origin)
    return out


def _same_origin(handler: Any) -> bool:
    import hmac

    origin = str(handler.headers.get("Origin") or "")
    if not origin:
        return False
    allowed = _allowed_origins(handler)
    if allowed:
        return any(hmac.compare_digest(origin, a) for a in allowed)
    host = str(handler.headers.get("Host") or "")
    return bool(host) and urlsplit(origin).netloc == host


def _body(handler: Any, raw: bytes | None) -> dict[str, Any] | None:
    if raw is None:
        try:
            length = int(handler.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            return None
        raw = handler.rfile.read(length) if length else b""
    if len(raw) > MAX_BODY or (handler.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _too_many(addr: str) -> bool:
    now = time.monotonic()
    with _FAILS_LOCK:
        seen = [t for t in _FAILS.get(addr, []) if now - t < 60]
        _FAILS[addr] = seen
        return len(seen) >= OPENS_PER_MINUTE


def _failed(addr: str) -> None:
    now = time.monotonic()
    with _FAILS_LOCK:
        _FAILS.setdefault(addr, []).append(now)
        if len(_FAILS) > 10000:
            # Prune expired windows first so spoofed X-Forwarded-For floods cannot wipe active throttles.
            stale = [k for k, times in _FAILS.items() if not any(now - t < 60 for t in times)]
            for k in stale:
                _FAILS.pop(k, None)
            if len(_FAILS) > 10000:
                oldest = sorted(_FAILS, key=lambda k: max(_FAILS[k]) if _FAILS[k] else 0.0)[:len(_FAILS) - 5000]
                for k in oldest:
                    _FAILS.pop(k, None)


def _open(factory: Factory, body: dict[str, Any], addr: str) -> tuple[int, dict[str, Any]]:
    """A real link always opens: only refused tries wait, so nobody's guessing (behind one proxy address, too)
    locks a reviewer out of their own link (FR-HITL2). A link's token is 256 random bits: waiting slows noise."""
    try:
        return 200, hitl_links.redeem(factory, str(body.get("link") or ""))
    except hitl_links.LinkRefused as exc:
        if _too_many(addr):
            return 429, {"error": "Too many tries. Wait a minute, then open your link again."}
        _failed(addr)
        return 403, {"error": str(exc)}


def _proxy(peer: str) -> bool:
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def client_of(handler: Any) -> str:
    """Who is trying: the peer, or behind IT's proxy on this machine or the private network, the address the
    proxy says it forwards (the last one it added)."""
    peer = str((handler.client_address or ("", 0))[0])
    forwarded = str(handler.headers.get("X-Forwarded-For") or "").split(",")[-1].strip()[:64]
    return f"{peer}>{forwarded}" if forwarded and _proxy(peer) else peer


def _with_session(factory: Factory, body: dict[str, Any]) -> dict[str, Any]:
    return hitl_links.session(factory, str(body.get("session") or ""))


def _items(factory: Factory, body: dict[str, Any], addr: str) -> tuple[int, dict[str, Any]]:
    return 200, hitl_links.items(factory, _with_session(factory, body))


def _answer(factory: Factory, body: dict[str, Any], addr: str) -> tuple[int, dict[str, Any]]:
    link = _with_session(factory, body)
    try:
        return 200, hitl_links.answer(factory, link, str(body.get("ask") or ""), str(body.get("answer") or ""),
                                      str(body.get("comment") or ""))
    except DecisionRefused as exc:
        return 409, {"error": f"{exc}. Refresh to see where it stands."}
    except ValueError as exc:
        return 400, {"error": str(exc)}


CALLS = {"/r/api/open": _open, "/r/api/items": _items, "/r/api/answer": _answer}


def _post(handler: Any, factory: Factory, path: str, raw: bytes | None) -> tuple[int, dict[str, Any]]:
    call = CALLS.get(path)
    if call is None:
        return 404, {"error": "not found"}
    if not _same_origin(handler):
        return 403, {"error": "This page answers its own page only."}
    body = _body(handler, raw)
    if body is None:
        return 400, {"error": "send a small JSON object"}
    addr = client_of(handler)
    try:
        return call(factory, body, addr)
    except hitl_links.LinkRefused as exc:
        return 403, {"error": str(exc)}
    except KeyError:
        return 404, {"error": "That question is no longer there. Ask the person who sent the link."}
    except Exception as exc:  # never shown: the page gets a plain line, the log the reason
        sys.stderr.write(f"reviewer page: {type(exc).__name__}: {exc}\n")
        return 500, {"error": "Something went wrong on our side. Try again in a moment."}


def serve(handler: Any, factory: Factory, raw: bytes | None = None) -> None:
    """Answer one request for the reviewer page (GET the page and its two files, POST its three calls)."""
    path = urlsplit(handler.path).path
    if handler.command == "GET" and path in FILES:
        name, ctype = FILES[path]
        return _send(handler, 200, (STATIC / name).read_bytes(), ctype)
    if handler.command == "POST":
        status, out = _post(handler, factory, path, raw)
        return _json(handler, status, out)
    return _json(handler, 404 if handler.command == "GET" else 405, {"error": "not found"})
