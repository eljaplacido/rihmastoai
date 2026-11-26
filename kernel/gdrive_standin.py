"""A stand-in for the Google Drive v3 API on 127.0.0.1 (FR-GDR1-AC-2): the gate's, and the tests'.

It answers what kernel/connectors_gdrive.py asks, as Drive does: `GET /drive/v3/files` with a query (`'<id>'
in parents`, `trashed = false`, `mimeType != '...'`, `modifiedTime >= '...'`, `name = '...'`), ordered by
modified time and cut into pages with a page token; `GET /drive/v3/files/<id>?alt=media`; a multipart upload
(`POST /upload/drive/v3/files?uploadType=multipart`); a media update (`PATCH /upload/drive/v3/files/<id>`);
the OAuth token endpoint (`POST /token`, the JWT bearer grant, its RS256 signature checked against the key it
was given); and the metadata server's token (`GET /computeMetadata/v1/.../token`, with `Metadata-Flavor`).

With `require_auth` (the tests) every Drive call needs a token it issued, and an upload needs a write scope.
The gate runs it without (kernel/integration_standins.py): the product's tests reach it through
`<NAME>_URL`, and `GCE_METADATA_HOST` points the metadata path at it. It records each request's method,
path and whether it wrote, never a token or a file's content, and listens on loopback only.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
import threading
import urllib.parse
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
WRITE_SCOPES = ("https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive")
CLAUSE = re.compile(r"'(?P<parent>[^']+)' in parents|trashed = (?P<trashed>true|false)|mimeType != '(?P<notmime>[^']+)'"
                    r"|modifiedTime >= '(?P<after>[^']+)'|name = '(?P<name>(?:[^'\\]|\\.)*)'")
MAX_BODY = 32 << 20


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_rs256(token: str, public: tuple[int, int]) -> dict[str, Any] | None:
    """The claims of a JWT whose RS256 signature verifies with (n, e), else None."""
    try:
        head, claims, sig = token.split(".")
        n, e = public
        size = (n.bit_length() + 7) // 8
        em = pow(int.from_bytes(_b64d(sig), "big"), e, n).to_bytes(size, "big")
        info = SHA256_INFO + hashlib.sha256(f"{head}.{claims}".encode("ascii")).digest()
        if em != b"\x00\x01" + b"\xff" * (size - 3 - len(info)) + b"\x00" + info:
            return None
        return json.loads(_b64d(claims))
    except (ValueError, OverflowError):
        return None


class DriveStandin:
    """Drive's files in memory, the tokens it issued, and what reached it."""

    def __init__(self, files: list[dict[str, Any]] | None = None, *, require_auth: bool = False,
                 public_key: tuple[int, int] | None = None, client_email: str | None = None) -> None:
        self.files: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, tuple[str, ...]] = {}
        self.requests: list[dict[str, Any]] = []
        self.fail_next: list[int] = []           # statuses to answer before the next real answer (retries)
        self.require_auth, self.public_key, self.client_email = require_auth, public_key, client_email
        self.lock, self.clock, self._n = threading.Lock(), 0, 0
        for f in files or []:
            self.add(f.get("name", "file"), f.get("content", ""), parents=f.get("parents") or ["root"],
                     mime=f.get("mimeType", "application/octet-stream"), modified=f.get("modifiedTime"))

    def stamp(self) -> str:
        self.clock += 1
        return f"2026-11-24T08:{self.clock // 60:02d}:{self.clock % 60:02d}.000Z"

    def add(self, name: str, content: bytes | str, *, parents: list[str], mime: str = "audio/mpeg",
            modified: str | None = None) -> dict[str, Any]:
        with self.lock:
            self._n += 1
            fid = f"f{self._n:04d}"
            data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
            self.files[fid] = {"id": fid, "name": name, "mimeType": mime, "parents": list(parents),
                               "modifiedTime": modified or self.stamp(), "trashed": False, "content": data}
            return self.files[fid]

    def issue(self, scopes: tuple[str, ...]) -> str:
        token = "ya29.standin-" + hashlib.sha256(f"{len(self.tokens)}{scopes}".encode()).hexdigest()[:24]
        self.tokens[token] = scopes
        return token

    # -- answering --------------------------------------------------------------------------------------

    def answer(self, method: str, target: str, body: bytes, headers: dict[str, str] | None = None
               ) -> tuple[int, bytes, str]:
        parts = urllib.parse.urlsplit(target)
        query = dict(urllib.parse.parse_qsl(parts.query))
        write = method in ("PATCH", "PUT", "DELETE") or (method == "POST" and parts.path.startswith("/upload/"))
        with self.lock:
            self.requests.append({"method": method, "path": parts.path[:200], "write": write})
            drive_call = parts.path.startswith(("/drive/", "/upload/"))
            failing = self.fail_next.pop(0) if self.fail_next and drive_call else None
        if failing:
            return _error(failing, "the stand-in was asked to fail once")
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        if parts.path == "/token" and method == "POST":
            return self._token(body)
        if parts.path.startswith("/computeMetadata/"):
            if hdrs.get("metadata-flavor") != "Google":
                return _error(403, "Missing Metadata-Flavor: Google header")
            return _json({"access_token": self.issue(tuple(query.get("scopes", "").split(","))), "expires_in": 3599,
                          "token_type": "Bearer"})
        denied = self._denied(hdrs, write)
        return denied if denied else self._drive(method, parts.path, query, body, hdrs)

    def _denied(self, hdrs: dict[str, str], write: bool) -> tuple[int, bytes, str] | None:
        if not self.require_auth:
            return None
        token = hdrs.get("authorization", "").removeprefix("Bearer ")
        if token not in self.tokens:
            return _error(401, "Request had invalid authentication credentials.")
        if write and not set(self.tokens[token]) & set(WRITE_SCOPES):
            return _error(403, "Request had insufficient authentication scopes.")
        return None

    def _token(self, body: bytes) -> tuple[int, bytes, str]:
        form = dict(urllib.parse.parse_qsl(body.decode("ascii", "replace")))
        if form.get("grant_type") != "urn:ietf:params:oauth:grant-type:jwt-bearer":
            return _json({"error": "unsupported_grant_type"}, 400)
        claims = verify_rs256(form.get("assertion", ""), self.public_key) if self.public_key else None
        if not claims or (self.client_email and claims.get("iss") != self.client_email):
            return _json({"error": "invalid_grant", "error_description": "Invalid JWT Signature."}, 400)
        return _json({"access_token": self.issue(tuple(str(claims.get("scope", "")).split())), "expires_in": 3599,
                      "token_type": "Bearer"})

    def _drive(self, method: str, path: str, query: dict[str, str], body: bytes,
               hdrs: dict[str, str]) -> tuple[int, bytes, str]:
        m = re.fullmatch(r"/(?P<up>upload/)?drive/v3/files(?:/(?P<id>[A-Za-z0-9_-]+))?", path)
        if m is None:
            return _error(404, f"the stand-in has no {path}")
        fid, upload = m.group("id"), bool(m.group("up"))
        if method == "GET" and not upload:
            return self._list(query) if fid is None else self._media(fid, query)
        if method == "POST" and upload and fid is None:
            return self._upload(body, hdrs.get("content-type", ""))
        if method == "PATCH" and upload and fid in self.files:
            with self.lock:
                self.files[fid].update(content=body, modifiedTime=self.stamp())
            return _json({"id": fid, "name": self.files[fid]["name"]})
        return _error(404, f"the stand-in does not take {method} {path}")

    def _media(self, fid: str, query: dict[str, str]) -> tuple[int, bytes, str]:
        found = self.files.get(fid)
        if found is None:
            return _error(404, f"File not found: {fid}.")
        if query.get("alt") != "media":
            return _json({k: v for k, v in found.items() if k in ("id", "name", "mimeType", "modifiedTime")})
        return 200, found["content"], found["mimeType"]

    def _list(self, query: dict[str, str]) -> tuple[int, bytes, str]:
        clauses = [c.strip() for c in query.get("q", "").split(" and ") if c.strip()]
        rows = [f for f in self.files.values() if all(_holds(c, f) for c in clauses)]
        if query.get("orderBy") == "modifiedTime":
            rows.sort(key=lambda f: (f["modifiedTime"], f["id"]))
        start, size = int(query.get("pageToken") or 0), max(1, min(int(query.get("pageSize") or 100), 1000))
        page = rows[start:start + size]
        out: dict[str, Any] = {"files": [{k: v for k, v in f.items() if k in ("id", "name", "mimeType", "modifiedTime")}
                                         | {"size": str(len(f["content"]))} for f in page]}
        if start + size < len(rows):
            out["nextPageToken"] = str(start + size)
        return _json(out)

    def _upload(self, body: bytes, ctype: str) -> tuple[int, bytes, str]:
        boundary = re.search(r"boundary=([^;]+)", ctype)
        if not boundary:
            return _error(400, "a multipart upload needs a boundary")
        parts = body.split(b"--" + boundary.group(1).strip().encode())
        chunks = [p.split(b"\r\n\r\n", 1) for p in parts if b"\r\n\r\n" in p]
        if len(chunks) < 2:
            return _error(400, "a multipart upload has metadata and media")
        meta = json.loads(chunks[0][1].strip() or b"{}")
        made = self.add(meta.get("name", "upload"), chunks[1][1].removesuffix(b"\r\n"),
                        parents=meta.get("parents") or ["root"], mime=meta.get("mimeType", "application/octet-stream"))
        return _json({"id": made["id"], "name": made["name"]})

    def report(self) -> dict[str, Any]:
        with self.lock:
            writes = [f"{r['method']} {r['path']}" for r in self.requests if r["write"]]
            drive = sum(1 for r in self.requests if r["path"].startswith(("/drive/", "/upload/")))   # not a token
            return {"standin": "http", "api": "gdrive", "requests": drive, "writes": writes[:20]}


def _holds(clause: str, f: dict[str, Any]) -> bool:
    m = CLAUSE.fullmatch(clause)
    if m is None:
        return False
    if m.group("parent"):
        return m.group("parent") in f["parents"]
    if m.group("trashed"):
        return f["trashed"] == (m.group("trashed") == "true")
    if m.group("notmime"):
        return f["mimeType"] != m.group("notmime")
    if m.group("after"):
        return f["modifiedTime"] >= m.group("after")
    return f["name"] == re.sub(r"\\(.)", r"\1", m.group("name"))


def _json(doc: Any, status: int = 200) -> tuple[int, bytes, str]:
    return status, json.dumps(doc).encode("utf-8"), "application/json"


def _error(status: int, message: str) -> tuple[int, bytes, str]:
    return _json({"error": {"code": status, "message": message}}, status)


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _serve(self) -> None:
        length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
        status, out, ctype = self.server.standin.answer(self.command, self.path, self.rfile.read(length),
                                                        dict(self.headers.items()))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _serve


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, standin: DriveStandin) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.standin = standin


@contextlib.contextmanager
def serving(standin: DriveStandin) -> Iterator[str]:
    """The stand-in on a free loopback port while the block runs; yields its base URL."""
    server = _Server(standin)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def start(standin: DriveStandin) -> tuple[ThreadingHTTPServer, str]:
    """The stand-in started for a caller that stops it itself (the gate's run): its server and base URL."""
    server = _Server(standin)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
