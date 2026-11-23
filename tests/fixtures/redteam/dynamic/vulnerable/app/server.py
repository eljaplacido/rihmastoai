"""A small product with one seeded defect per dynamic rule (kernel/redteam/rules.py, DYNAMIC_RULES).

Each defect sits on a line marked `seeded: <rule id>`. tests/test_redteam_dynamic.py starts it on
127.0.0.1 with port 0, records it as a slot the factory deployed, and proves that each probe of
kernel/redteam/dynamic.py catches its seed. ../../clean/app/server.py is the same product written
safely, where every probe must stay quiet. Test data only: it holds no secret, serves files from
its own folder, and binds loopback only. It is laid out like a product the factory builds:
app/server.py beside app/static/.
"""

from __future__ import annotations

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PATHS = ("/", "/search", "/items", "/health")


class Server(ThreadingHTTPServer):
    """Counts every connection, so a test can show that a refused run sent nothing."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.connections = 0
        self.items = {1: "Projector"}

    def verify_request(self, request: object, client_address: object) -> bool:
        self.connections += 1
        return True

    def handle_error(self, request: object, client_address: object) -> None:
        return

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, body: object, ctype: str = "application/json") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)  # seeded: RT-DYN-CSP RT-DYN-NOSNIFF RT-DYN-FRAME RT-DYN-REFERRER
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)  # seeded: RT-DYN-CORS
            self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _page(self, title: str, body: str) -> None:
        self._send(200, f"<!doctype html><title>{title}</title><h1>{title}</h1>{body}", "text/html; charset=utf-8")

    def _dispatch(self) -> None:
        try:
            self._route()
        except OSError:
            return  # the client went away
        except Exception:  # every other error is answered with its whole trace
            self._error()

    def _error(self) -> None:
        try:
            self._send(500, traceback.format_exc(), "text/plain; charset=utf-8")  # seeded: RT-DYN-LEAK
        except OSError:
            return

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _dispatch

    def do_TRACE(self) -> None:
        # TRACE echoes the request back (cross-site tracing): the other form of the method rule.
        self._send(200, f"{self.requestline}\r\n{self.headers}", "message/http")

    def _route(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))  # seeded: RT-DYN-OVERSIZE
        parts = urlsplit(self.path)
        path, method = parts.path, self.command
        if path.startswith("/items/"):
            return self._item(method, path[len("/items/"):])  # seeded: RT-DYN-METHOD
        if method == "GET":
            return self._get(path, parse_qs(parts.query))
        if method == "POST" and path == "/items":
            return self._add(raw)
        if method == "OPTIONS":
            return self._send(204, "")
        return self._send(405 if path in PATHS else 404, {"error": "no such route"})

    def _get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/":
            return self._page("Equipment loans", '<p>Borrow what you need.</p><script src="/static/app.js"></script>')
        if path == "/health":
            return self._send(200, {"status": "ok"})
        if path == "/search":
            q = query.get("q", [""])[0]
            return self._page("Search", f"<p>Results for {q}</p>")  # seeded: RT-DYN-REFLECT
        if path.startswith("/static/"):
            return self._file(os.path.join(STATIC, path[len("/static/"):]))  # seeded: RT-DYN-TRAVERSAL
        if path.startswith("/files/"):
            name = path[len("/files/"):]
            if ".." in name or "/" in name:
                return self._send(400, {"error": "bad name"})
            # The check runs before decoding, so an encoded ../ passes it: the encoded form of traversal.
            return self._file(os.path.join(STATIC, unquote(name)))
        return self._send(404, {"error": "not found"})

    def _item(self, method: str, raw: str) -> None:
        if method != "GET":
            return self._send(200, {"ok": True, "method": method})
        name = self.server.items[int(raw)]  # a name that is not a number raises, and the trace is sent
        return self._page(name, f"<p>{name} is available.</p>")

    def _file(self, path: str) -> None:
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        with open(path, encoding="utf-8") as fh:
            return self._send(200, fh.read(), "text/plain; charset=utf-8")

    def _add(self, raw: bytes) -> None:
        body = json.loads(raw.decode("utf-8"))  # seeded: RT-DYN-MALFORMED
        item = max(self.server.items) + 1  # every write is taken, however many: seeded: RT-DYN-RATELIMIT
        self.server.items[item] = str(body.get("name", ""))
        return self._send(201, {"id": item})
