"""An S3-compatible store faked on 127.0.0.1, for the connector contract suite.

`backend()` starts it in this process, on a free loopback port, holding fixtures/objects.json in one
bucket, and yields the environment the narrow server (server.py) needs to reach it. It answers what the
server sends (ListObjectsV2 as S3's XML, GET and HEAD of an object) only when the request carries a valid
AWS Signature Version 4 for the test credentials, and refuses every write with 403, recording it, so the
suite can show that the server never writes. Standard library only; nothing leaves loopback.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import re
import threading
import urllib.parse
from collections.abc import Iterator
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
BUCKET, REGION, ACCESS_KEY = "reports", "eu-north-1", "test-reader"
SECRET_KEY = "test-only-not-a-real-secret"
_AUTH = re.compile(r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request, "
                   r"SignedHeaders=([a-z0-9;-]+), Signature=([0-9a-f]{64})")


def _server_module() -> Any:
    spec = importlib.util.spec_from_file_location("s3_connector_server", HERE / "server.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class _Store(BaseHTTPRequestHandler):
    server: _FakeS3

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _signed(self) -> bool:
        found = _AUTH.fullmatch(self.headers.get("Authorization", ""))
        stamp = self.headers.get("x-amz-date", "")
        if not found or found.group(1) != ACCESS_KEY or not stamp.startswith(found.group(2)):
            return False
        import datetime as dt

        when = dt.datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
        url = f"http://{self.headers.get('Host')}{self.path}"
        want = self.server.sign(self.command, url, access_key=ACCESS_KEY, secret_key=SECRET_KEY,
                                region=found.group(3), now=when)
        return want["Authorization"] == self.headers.get("Authorization")

    def _send(self, status: int, body: bytes, ctype: str = "application/xml") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Last-Modified", formatdate(1795000000, usegmt=True))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read(self) -> None:
        self.server.requests.append(f"{self.command} {self.path}")
        if not self._signed():
            self._send(403, b"<Error><Code>SignatureDoesNotMatch</Code></Error>")
            return
        parts = urllib.parse.urlsplit(self.path)
        bucket, _, key = urllib.parse.unquote(parts.path.lstrip("/")).partition("/")
        if bucket != BUCKET:
            self._send(404, b"<Error><Code>NoSuchBucket</Code></Error>")
        elif not key:
            prefix = dict(urllib.parse.parse_qsl(parts.query)).get("prefix", "")
            rows = "".join(f"<Contents><Key>{escape(k)}</Key><LastModified>2026-11-22T06:00:00.000Z</LastModified>"
                           f"<Size>{len(v.encode('utf-8'))}</Size></Contents>"
                           for k, v in sorted(self.server.objects.items()) if k.startswith(prefix))
            self._send(200, ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns='
                             f'"http://s3.amazonaws.com/doc/2006-03-01/"><Name>{BUCKET}</Name>{rows}'
                             "</ListBucketResult>").encode())
        elif key in self.server.objects:
            self._send(200, self.server.objects[key].encode("utf-8"), "text/csv")
        else:
            self._send(404, b"<Error><Code>NoSuchKey</Code></Error>")

    def _write(self) -> None:
        self.server.requests.append(f"{self.command} {self.path}")
        self.server.writes.append(f"{self.command} {self.path}")
        self._send(403, b"<Error><Code>AccessDenied</Code></Error>")

    do_GET = do_HEAD = _read
    do_PUT = do_POST = do_DELETE = do_PATCH = _write


class _FakeS3(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Store)
        self.objects: dict[str, str] = json.loads((HERE / "fixtures" / "objects.json").read_text(
            encoding="utf-8"))["objects"]
        self.requests: list[str] = []
        self.writes: list[str] = []
        self.sign = _server_module().sign_v4


@contextlib.contextmanager
def backend() -> Iterator[dict[str, Any]]:
    """The fake store, running; yields the server's environment and the store itself (``store``)."""
    store = _FakeS3()
    threading.Thread(target=store.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    try:
        yield {"env": {"S3_ENDPOINT_URL": f"http://127.0.0.1:{store.server_address[1]}", "S3_REGION": REGION,
                       "S3_BUCKET": BUCKET, "S3_ACCESS_KEY_ID": ACCESS_KEY, "S3_SECRET_ACCESS_KEY": SECRET_KEY},
               "store": store}
    finally:
        store.shutdown()
        store.server_close()
