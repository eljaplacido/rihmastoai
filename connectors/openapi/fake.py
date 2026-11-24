"""A business API faked on 127.0.0.1, for the connector contract suite.

`backend()` starts it in this process, on a free loopback port, serving the records of
fixtures/records.json under /api as openapi.json describes them, and yields the environment the narrow
server (server.py) needs to reach it. It answers only a request with the test bearer token, and refuses
every write with 403, recording it, so the suite can show that the server never writes. Standard library
only; nothing leaves loopback.
"""

from __future__ import annotations

import contextlib
import json
import threading
import urllib.parse
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BEARER = "test-only-bearer-not-a-real-one"


class _Api(BaseHTTPRequestHandler):
    server: _FakeApi

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, status: int, doc: Any) -> None:
        body = json.dumps(doc).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.server.requests.append(f"GET {self.path}")
        if self.headers.get("Authorization") != f"Bearer {BEARER}":
            self._send(401, {"error": "unauthorized"})
            return
        parts = urllib.parse.urlsplit(self.path)
        records, segs = self.server.records, parts.path.strip("/").split("/")
        query = dict(urllib.parse.parse_qsl(parts.query))
        if segs[:2] == ["api", "orders"] and len(segs) == 2:
            self._send(200, [o for o in records["orders"] if query.get("status") in (None, o["status"])])
        elif segs[:2] == ["api", "orders"] and len(segs) == 3:
            found = next((o for o in records["orders"] if o["id"] == urllib.parse.unquote(segs[2])), None)
            self._send(200 if found else 404, found or {"error": "no such order"})
        elif segs == ["api", "customers"]:
            self._send(200, records["customers"])
        else:
            self._send(404, {"error": "no such path"})

    def _write(self) -> None:
        self.server.requests.append(f"{self.command} {self.path}")
        self.server.writes.append(f"{self.command} {self.path}")
        self._send(403, {"error": "this fake takes no writes"})

    do_POST = do_PUT = do_PATCH = do_DELETE = _write


class _FakeApi(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Api)
        self.records: dict[str, Any] = json.loads((HERE / "fixtures" / "records.json").read_text(encoding="utf-8"))
        self.requests: list[str] = []
        self.writes: list[str] = []


@contextlib.contextmanager
def backend() -> Iterator[dict[str, Any]]:
    """The fake API, running; yields the server's environment and the API itself (``store``)."""
    api = _FakeApi()
    threading.Thread(target=api.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    try:
        yield {"env": {"OPENAPI_BASE_URL": f"http://127.0.0.1:{api.server_address[1]}/api", "OPENAPI_TOKEN": BEARER},
               "store": api}
    finally:
        api.shutdown()
        api.server_close()
