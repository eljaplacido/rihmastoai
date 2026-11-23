"""The clean twin of ../../vulnerable/app/server.py: the same product and interface, written safely.

Every probe of kernel/redteam/dynamic.py must stay quiet here (tests/test_redteam_dynamic.py), and
every layer must be measured. Beside each fix sits what a careless probe could mistake for a
defect: a JSON 404 that echoes the path it was asked for, a static route that serves its own
script, a search page that shows the query (escaped), CORS for one fixed origin, security headers
on JSON as well as on pages. Test data only, loopback only.
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

STATIC = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
MAX_BODY = 64 * 1024
LIMIT, WINDOW = 5, 10.0  # writes per client per window
ALLOWED_ORIGINS = ("http://127.0.0.1:8080",)
SECURITY_HEADERS = (("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"),
                    ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
                    ("Referrer-Policy", "no-referrer"))


class Server(ThreadingHTTPServer):
    """Counts every connection, and keeps each client's recent writes for the rate limit."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.connections = 0
        self.items = {1: "Projector"}
        self.writes: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def verify_request(self, request: object, client_address: object) -> bool:
        self.connections += 1
        return True

    def handle_error(self, request: object, client_address: object) -> None:
        return

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def allow_write(self, client: str) -> bool:
        now = time.monotonic()
        with self.lock:
            recent = [t for t in self.writes.get(client, []) if now - t < WINDOW]
            allowed = len(recent) < LIMIT
            self.writes[client] = recent + [now] if allowed else recent
        return allowed


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, format: str, *args: object) -> None:
        return

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        headers = getattr(self, "headers", None)
        origin = headers.get("Origin", "") if headers is not None else ""
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def _send(self, status: int, body: object, ctype: str = "application/json",
              extra: tuple[tuple[str, str], ...] = ()) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for name, value in extra:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _page(self, title: str, body: str) -> None:
        self._send(200, f"<!doctype html><title>{html.escape(title)}</title><h1>{html.escape(title)}</h1>{body}",
                   "text/html; charset=utf-8")

    def _dispatch(self) -> None:
        length = self.headers.get("Content-Length") or "0"
        if not length.isdigit() or int(length) > MAX_BODY:
            return self._send(413, {"error": f"a body is at most {MAX_BODY} bytes"})
        self.raw = self.rfile.read(int(length))  # always read, so the connection closes cleanly
        try:
            self._route()
        except OSError:
            return
        except Exception:  # noqa: BLE001 - the details stay in the server's log, never in the answer
            self._send(500, {"error": "internal error"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _dispatch

    def do_OPTIONS(self) -> None:
        self._send(204, "", extra=(("Allow", "GET, POST"),))

    def _route(self) -> None:
        parts = urlsplit(self.path)
        allowed = []
        for method, pattern, handler in ROUTES:
            m = pattern.fullmatch(parts.path)
            if not m:
                continue
            if method == self.command:
                return handler(self, m.groupdict(), parse_qs(parts.query))
            allowed.append(method)
        if allowed:
            return self._send(405, {"error": "method not allowed"}, extra=(("Allow", ", ".join(allowed)),))
        # A JSON 404 that names the path asked for, decoded: what a request sent is not a leak, and
        # a tag in JSON is not reflected into a page.
        return self._send(404, {"error": "not found", "path": unquote(parts.path)})

    def home(self, params: dict[str, str], query: dict[str, list[str]]) -> None:
        self._page("Equipment loans", '<p>Borrow what you need.</p><script src="/static/app.js"></script>')

    def health(self, params: dict[str, str], query: dict[str, list[str]]) -> None:
        self._send(200, {"status": "ok"})

    def search(self, params: dict[str, str], query: dict[str, list[str]]) -> None:
        q = query.get("q", [""])[0]
        self._page("Search", f"<p>Results for {html.escape(q)}</p>")

    def item(self, params: dict[str, str], query: dict[str, list[str]]) -> None:
        name = self.server.items.get(int(params["id"])) if params["id"].isdigit() else None
        if name is None:
            return self._send(404, {"error": "not found"})
        return self._page(name, f"<p>{html.escape(name)} is available.</p>")

    def static(self, params: dict[str, str], query: dict[str, list[str]]) -> None:
        name = os.path.basename(unquote(params["name"]))
        path = os.path.realpath(os.path.join(STATIC, name))
        if os.path.splitext(name)[1] not in TYPES or not path.startswith(STATIC + os.sep) or not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        with open(path, encoding="utf-8") as fh:
            return self._send(200, fh.read(), TYPES[os.path.splitext(name)[1]])

    def add(self, params: dict[str, str], query: dict[str, list[str]]) -> None:
        if not self.server.allow_write(self.client_address[0]):
            return self._send(429, {"error": "too many writes"}, extra=(("Retry-After", str(int(WINDOW))),))
        try:
            body = json.loads(self.raw.decode("utf-8"))
        except ValueError:  # malformed JSON and invalid UTF-8 alike
            return self._send(400, {"error": "the body is not JSON"})
        if not isinstance(body, dict) or not str(body.get("name", "")).strip():
            return self._send(400, {"error": "an item needs a name"})
        with self.server.lock:
            item = max(self.server.items) + 1
            self.server.items[item] = str(body["name"])[:200]
        return self._send(201, {"id": item})


Route = tuple[str, "re.Pattern[str]", Callable[..., None]]
ROUTES: list[Route] = [
    ("GET", re.compile(r"/"), Handler.home),
    ("GET", re.compile(r"/health"), Handler.health),
    ("GET", re.compile(r"/search"), Handler.search),
    ("GET", re.compile(r"/items/(?P<id>[^/]+)"), Handler.item),
    ("POST", re.compile(r"/items"), Handler.add),
    ("GET", re.compile(r"/static/(?P<name>[^/]+)"), Handler.static),
    ("GET", re.compile(r"/files/(?P<name>[^/]+)"), Handler.static),
]
