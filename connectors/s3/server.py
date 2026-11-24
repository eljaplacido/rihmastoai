"""A narrow, read-only MCP server for S3-compatible object storage, over stdio.

Standard library only. It speaks the MCP stdio transport (one JSON-RPC 2.0 message a line: `initialize`,
`ping`, `tools/list`, `tools/call`) and offers three read tools on one bucket:

- `list_objects`: the keys under a prefix (at most 1000), with size and modification time;
- `get_object_metadata`: one object's size, type and modification time (an HTTP HEAD);
- `get_object_text`: the first bytes of one text object (at most 64 KiB), as text.

It reaches only the endpoint and the bucket IT configures, from the environment Gnomon gives it:
`S3_ENDPOINT_URL` (https, or http on loopback only), `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID` and
`S3_SECRET_ACCESS_KEY`. Every request is signed with AWS Signature Version 4 and path-style addressing,
which AWS S3 and most S3-compatible stores (MinIO, Ceph, R2 and the like) accept. It sends GET and HEAD
only and has no tool that puts, copies or deletes, so a model in the lane cannot write through it. Use
credentials that can only read the one bucket all the same.

    python server.py               serve the pinned tools (fixtures/tools.json)
    python server.py --rug-pull    serve a changed tools/list (fixtures/rugpull-tools.json), for the suite
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL = "2025-06-18"
MAX_TEXT = 65536
MAX_KEYS = 1000
LOOPBACK = ("127.0.0.1", "localhost", "::1")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _fixture(name: str) -> Any:
    return json.loads((HERE / "fixtures" / name).read_text(encoding="utf-8"))


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()


def _q(text: str) -> str:
    return urllib.parse.quote(text, safe="-_.~")


def sign_v4(method: str, url: str, *, access_key: str, secret_key: str, region: str, now: dt.datetime,
            service: str = "s3") -> dict[str, str]:
    """The headers that sign a request with no body (AWS Signature Version 4)."""
    parts = urllib.parse.urlsplit(url)
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    query = "&".join(f"{_q(k)}={_q(v)}" for k, v in sorted(urllib.parse.parse_qsl(parts.query,
                                                                                    keep_blank_values=True)))
    headers = {"host": parts.netloc, "x-amz-content-sha256": EMPTY_SHA256, "x-amz-date": stamp}
    signed = ";".join(sorted(headers))
    canonical = "\n".join([method, parts.path or "/", query, "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)),
                           signed, EMPTY_SHA256])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode("utf-8"), day), region), service), "aws4_request")
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"x-amz-content-sha256": EMPTY_SHA256, "x-amz-date": stamp,
            "Authorization": f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, "
                             f"Signature={signature}"}


class Store:
    """The one bucket this server reads, as the environment names it."""

    def __init__(self, env: dict[str, str]) -> None:
        self.endpoint = env.get("S3_ENDPOINT_URL", "").rstrip("/")
        self.bucket = env.get("S3_BUCKET", "")
        self.region = env.get("S3_REGION", "us-east-1")
        self.access_key, self.secret_key = env.get("S3_ACCESS_KEY_ID", ""), env.get("S3_SECRET_ACCESS_KEY", "")

    def problem(self) -> str | None:
        url = urllib.parse.urlsplit(self.endpoint)
        if not (url.scheme == "https" or url.scheme == "http" and url.hostname in LOOPBACK):
            return "S3_ENDPOINT_URL must be an https URL (http only on loopback)"
        if not self.bucket or "/" in self.bucket or not self.access_key or not self.secret_key:
            return "S3_BUCKET, S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY must be set"
        return None

    def request(self, method: str, key: str = "", query: dict[str, str] | None = None) -> tuple[int, dict, bytes]:
        path = "/" + _q(self.bucket) + ("/" + "/".join(_q(p) for p in key.split("/")) if key else "")
        url = self.endpoint + path + ("?" + urllib.parse.urlencode(sorted((query or {}).items())) if query else "")
        headers = sign_v4(method, url, access_key=self.access_key, secret_key=self.secret_key, region=self.region,
                          now=dt.datetime.now(dt.UTC))
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with _NO_PROXY.open(req, timeout=30) as resp:
                return resp.status, dict(resp.headers), resp.read(MAX_TEXT + 1)
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read(4096)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def call(store: Store, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
    """(the tool's result, whether it is an error)."""
    if name not in ("list_objects", "get_object_metadata", "get_object_text"):
        return {"error": f"no tool {name}: this server only reads"}, True
    problem = store.problem()
    if problem:
        return {"error": problem}, True
    key = str(args.get("key", ""))
    if name != "list_objects" and (not key or key.startswith("/") or ".." in key.split("/")):
        return {"error": "a key such as reports/2026-11-22.csv"}, True
    if name == "list_objects":
        limit = max(1, min(int(args.get("max_keys") or MAX_KEYS), MAX_KEYS))
        status, _, body = store.request("GET", query={"list-type": "2", "prefix": str(args.get("prefix", "")),
                                                      "max-keys": str(limit)})
        if status != 200:
            return {"error": f"the store answered {status}"}, True
        root = ET.fromstring(body)
        objects = [{_local(c.tag).lower(): c.text for c in item} for item in root if _local(item.tag) == "Contents"]
        return {"bucket": store.bucket, "objects": [{"key": o.get("key"), "size": int(o.get("size") or 0),
                                                     "last_modified": o.get("lastmodified")} for o in objects]}, False
    status, headers, body = store.request("HEAD" if name == "get_object_metadata" else "GET", key)
    if status != 200:
        return {"error": f"the store answered {status} for {key}"}, True
    meta = {"bucket": store.bucket, "key": key, "size": int(headers.get("Content-Length") or len(body)),
            "content_type": headers.get("Content-Type"), "last_modified": headers.get("Last-Modified")}
    if name == "get_object_text":
        meta["text"] = body[:MAX_TEXT].decode("utf-8", errors="replace")
    return meta, False


def handle(msg: dict[str, Any], store: Store, rug_pull: bool) -> dict[str, Any] | None:
    """The answer to one message; None for a notification."""
    if "id" not in msg:
        return None
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        result: Any = {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "rihmasto-s3-read", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _fixture("rugpull-tools.json" if rug_pull else "tools.json")["tools"]}
    elif method == "tools/call":
        try:
            out, error = call(store, str(params.get("name")), params.get("arguments") or {})
        except (OSError, ValueError, ET.ParseError) as exc:
            out, error = {"error": f"{type(exc).__name__}: the store could not be read"}, True
        result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": msg["id"], "result": result}


def main(argv: list[str]) -> int:
    rug_pull, store = "--rug-pull" in argv, Store(dict(os.environ))
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            answer: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None,
                                             "error": {"code": -32700, "message": "parse error"}}
        else:
            answer = handle(msg, store, rug_pull) if isinstance(msg, dict) else None
        if answer is not None:
            sys.stdout.write(json.dumps(answer, ensure_ascii=True) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
