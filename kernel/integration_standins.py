"""Stand-ins for a product's declared integrations, and the gate's `integrations` signal (FR-DS3).

The gate runs a product's tests with each integration its contract declares (the INT- requirements,
kernel/integration_decl.py) pointed at a stand-in on this machine, through the settings the product reads:

- via sql: a SQLite file in a folder of its own, seeded from `tests/standins/<name>.sql` when the product
  has that file. `<NAME>_URL` is `sqlite:///` and the file's absolute path (`sqlite:////tmp/x.sqlite3`).
- via http: a server on 127.0.0.1. For cloud storage it is an object store in S3's path style (`PUT`,
  `GET`, `HEAD` and `DELETE` on `/<bucket>/<key>`, and `GET /<bucket>` lists the keys as S3's XML);
  anything else answers from `tests/standins/<name>.json` (`{"responses": [{"method": "GET", "path":
  "/orders", "status": 200, "json": [...]}]}`), and 404 for what it does not know.
- via mcp: the same server speaking MCP's JSON-RPC over HTTP POST (`initialize`, `tools/list`, and
  `tools/call` answered from that file's `tools` and `results`).

Each credential the declaration names gets a placeholder that is no secret, `<NAME>_ACCESS` and
`<NAME>_KIND` are set as a road sets them, and every stand-in records what reached it. After the run the
`integrations` signal says, for each integration:

- **failed**: an integration declared read was written (its SQLite file changed; a PUT, PATCH or DELETE;
  a POST that is not a read query; an MCP tool whose name writes), or its seed did not load;
- **not measured**: the task tests its INT- criterion but no request reached its HTTP stand-in (a test that
  stubs the network proves nothing about the data access), or the criterion no longer names its
  integration as the kernel wrote it;
- **passed** otherwise. A SQLite file cannot show a read: there, the criterion's test that ran with the
  stand-in in place is the proof, and the trace signal holds the task to it.

A contract with no INT- requirement runs with no stand-in and gets no signal, so a product without
integrations meets the gate as before. Nothing reaches a network: the stand-ins listen on loopback only
and stop when the run ends.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import threading
import urllib.parse
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from kernel.connectors import _words  # a tool name's words: `insertOrder` and `insert_order` hold `insert`
from kernel.integration_decl import KINDS, from_contract, settings
from kernel.verdicts import combine_verdicts

PLACEHOLDER = "standin-placeholder-not-a-secret"
MAX_BODY = 1 << 20
WRITE_METHODS = ("PUT", "PATCH", "DELETE")
WRITE_WORDS = {"approve", "decide", "delete", "deploy", "merge", "push", "create", "insert", "update", "upsert",
               "write", "put", "set", "upload", "drop", "alter", "truncate", "remove", "execute", "post", "modify"}
READ_SQL = re.compile(r"(?is)\A\s*(?:select|with|show|describe|desc|explain|values)\b")


def _post_reads(body: bytes) -> bool:
    """A POST that only asks: its JSON names a SQL statement or query that reads (Snowflake's and Databricks'
    `statement`, BigQuery's `query`, NetSuite SuiteQL's `q`)."""
    try:
        doc = json.loads(body or b"{}")
    except ValueError:
        return False
    sql = next((doc.get(k) for k in ("statement", "query", "q") if isinstance(doc, dict) and doc.get(k)), None)
    return isinstance(sql, str) and bool(READ_SQL.match(sql)) and ";" not in sql.strip().rstrip(";")


class HttpStandin:
    """One integration's HTTP or MCP stand-in: what it answers, and what reached it."""

    def __init__(self, decl: dict[str, Any], fixture: dict[str, Any]) -> None:
        self.decl, self.fixture = decl, fixture
        self.storage = KINDS[decl["kind"]]["family"] == "storage"
        self.objects: dict[str, bytes] = {k: str(v).encode("utf-8") for k, v in (fixture.get("objects") or {}).items()}
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def answer(self, method: str, target: str, body: bytes) -> tuple[int, bytes, str]:
        path = urllib.parse.urlsplit(target).path
        if self.decl["via"] == "mcp":
            status, out, write = self._mcp(body)
        elif self.storage:
            status, out, write = self._object(method, target, body)
        else:
            status, out = self._fixture(method, path)
            write = method in WRITE_METHODS or (method == "POST" and not _post_reads(body))
        with self.lock:
            self.requests.append({"method": method, "path": path[:200], "write": write})
        ctype = "application/xml" if out.startswith(b"<?xml") else "application/json"
        return status, out, ctype

    def _fixture(self, method: str, path: str) -> tuple[int, bytes]:
        for r in self.fixture.get("responses") or []:
            if isinstance(r, dict) and r.get("method", "GET").upper() == method and r.get("path") == path:
                return int(r.get("status", 200)), json.dumps(r.get("json", {})).encode("utf-8")
        return 404, json.dumps({"error": f"the stand-in has no answer for {method} {path}"}).encode("utf-8")

    def _object(self, method: str, target: str, body: bytes) -> tuple[int, bytes, bool]:
        parts = urllib.parse.urlsplit(target)
        key = urllib.parse.unquote(parts.path.lstrip("/"))
        if method in ("GET", "HEAD") and "/" not in key.rstrip("/"):
            prefix = dict(urllib.parse.parse_qsl(parts.query)).get("prefix", "")
            bucket = key.rstrip("/")
            names = sorted(k.split("/", 1)[1] for k in self.objects if k.startswith(bucket + "/" + prefix))
            listing = "".join(f"<Contents><Key>{escape(n)}</Key><Size>{len(self.objects[bucket + '/' + n])}</Size>"
                              "</Contents>" for n in names)
            return 200, (f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult><Name>{escape(bucket)}</Name>'
                         f"<KeyCount>{len(names)}</KeyCount>{listing}</ListBucketResult>").encode(), False
        if method in ("GET", "HEAD"):
            found = self.objects.get(key)
            return (200, found, False) if found is not None else (404, b'{"error": "no such key"}', False)
        if method in ("PUT", "POST"):
            self.objects[key] = body
            return 200, b"{}", True
        if method == "DELETE":
            self.objects.pop(key, None)
            return 204, b"", True
        return 405, b'{"error": "not an object store method"}', True

    def _mcp(self, body: bytes) -> tuple[int, bytes, bool]:
        try:
            msg = json.loads(body or b"{}")
        except ValueError:
            return 400, b'{"jsonrpc": "2.0", "id": null, "error": {"code": -32700, "message": "parse error"}}', False
        method, params = msg.get("method"), msg.get("params") or {}
        write = False
        if method == "initialize":
            result: Any = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                           "capabilities": {"tools": {"listChanged": False}},
                           "serverInfo": {"name": f"standin-{self.decl['name']}", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": self.fixture.get("tools") or []}
        elif method == "tools/call":
            name = str(params.get("name", ""))
            write = bool(_words(name) & WRITE_WORDS)
            out = (self.fixture.get("results") or {}).get(name, {"error": f"the stand-in has no result for {name}"})
            result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": name not in (
                self.fixture.get("results") or {})}
        elif "id" not in msg:
            return 202, b"", False
        else:
            result = {}
        return 200, json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "result": result}).encode("utf-8"), write

    def report(self) -> dict[str, Any]:
        with self.lock:
            writes = [f"{r['method']} {r['path']}" for r in self.requests if r["write"]]
            return {"standin": "http", "requests": len(self.requests), "writes": writes[:20]}


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _serve(self) -> None:
        length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
        status, out, ctype = self.server.standin.answer(self.command, self.path, self.rfile.read(length))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(out)

    do_GET = do_PUT = do_POST = do_DELETE = do_PATCH = do_HEAD = _serve


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, standin: HttpStandin) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.standin = standin


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


class SqliteStandin:
    """One integration's SQLite stand-in: a file, seeded from the product's own seed, watched for writes."""

    def __init__(self, decl: dict[str, Any], repo_dir: Path, folder: Path) -> None:
        self.path, self.error = folder / f"{decl['name']}.sqlite3", None
        seed = Path(repo_dir) / "tests" / "standins" / f"{decl['name']}.sql"
        try:
            with contextlib.closing(sqlite3.connect(self.path)) as db:
                if seed.is_file():
                    db.executescript(seed.read_text(encoding="utf-8"))
                db.commit()
        except (sqlite3.Error, OSError, UnicodeDecodeError) as exc:
            self.error = f"its seed tests/standins/{decl['name']}.sql did not load: {type(exc).__name__}: {exc}"
        self.before = _sha(self.path)

    def url(self) -> str:
        """`sqlite:///` and the file's absolute path (`sqlite:////tmp/x.sqlite3`, `sqlite:///C:/x.sqlite3`)."""
        return "sqlite:///" + self.path.resolve().as_posix()

    def report(self) -> dict[str, Any]:
        journal = [p.name for p in (self.path.with_name(self.path.name + s) for s in ("-wal", "-journal"))
                   if p.exists() and p.stat().st_size]
        written = _sha(self.path) != self.before or bool(journal)
        return {"standin": "sqlite", "written": written, "writes": ["the SQLite file changed"] if written else [],
                "error": self.error}


class Standins:
    """The stand-ins of one run: the environment they give the suite, and what each saw."""

    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.items: dict[str, Any] = {}
        self.servers: list[_Server] = []

    def add(self, decl: dict[str, Any], repo_dir: Path, folder: Path) -> None:
        s = settings(decl)
        if decl["via"] == "sql":
            item: Any = SqliteStandin(decl, repo_dir, folder)
            url = item.url()
        else:
            item = HttpStandin(decl, _fixture(repo_dir, decl["name"]))
            server = _Server(item)
            threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
            self.servers.append(server)
            url = f"http://127.0.0.1:{server.server_address[1]}" + ("/mcp" if decl["via"] == "mcp" else "")
        self.items[decl["name"]] = item
        self.env |= {s["url"]: url, s["access"]: decl["access"], s["kind"]: decl["kind"]}
        self.env |= {c: PLACEHOLDER for c in decl.get("credentials") or []}

    def report(self) -> dict[str, Any]:
        """What each stand-in saw, as the run keeps it; nothing when there was none."""
        return {"standins": {name: item.report() for name, item in self.items.items()}} if self.items else {}

    def stop(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()


def _fixture(repo_dir: Path, name: str) -> dict[str, Any]:
    path = Path(repo_dir) / "tests" / "standins" / f"{name}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        doc = {}
    return doc if isinstance(doc, dict) else {}


def _contract(repo_dir: Path) -> dict[str, Any]:
    try:
        doc = json.loads((Path(repo_dir) / "contract.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


@contextlib.contextmanager
def running(repo_dir: Path) -> Iterator[Standins]:
    """The stand-ins for every integration the contract in ``repo_dir`` declares, for one run of its suite."""
    decls, _ = from_contract(_contract(repo_dir))
    stand = Standins()
    if not decls:
        yield stand
        return
    folder = Path(tempfile.mkdtemp(prefix="gate-standins-"))
    try:
        for decl in decls:
            stand.add(decl, Path(repo_dir), folder)
        yield stand
    finally:
        stand.stop()
        shutil.rmtree(folder, ignore_errors=True)


def _verdict(decl: dict[str, Any], seen: dict[str, Any] | None, owned: bool) -> tuple[str, str]:
    name = decl["name"]
    if seen is None:
        return "not measured", f"{name}: no stand-in ran for it"
    if seen.get("error"):
        return "failed", f"{name}: {seen['error']}"
    if decl["access"] == "read" and seen["writes"]:
        return "failed", f"{name} is declared read and was written: {', '.join(seen['writes'][:3])}"
    if owned and seen["standin"] == "http" and not seen["requests"]:
        return "not measured", f"{name}: no request reached its stand-in, so no test showed the data access"
    return "passed", f"{name}: " + (f"{seen['requests']} request(s) reached its stand-in" if seen["standin"] == "http"
                                    else "its SQLite stand-in was in place and not written")


def signal(contract: dict[str, Any], run: dict[str, Any], task_id: str | None = None) -> list[Any]:
    """The `integrations` signal for a run, as a list of one, or none when the contract declares none."""
    from kernel.gate import Signal

    decls, problems = from_contract(contract)
    if not decls and not problems:
        return []
    task: dict[str, Any] = next((t for t in contract.get("tasks") or [] if t.get("id") == task_id), {})
    seen = (run.get("standins") or {})
    rows = {d["name"]: _verdict(d, seen.get(d["name"]), d["criterion"] in (task.get("criteria") or []))
            for d in decls}
    verdicts = [v for v, _ in rows.values()] + ["not measured" for _ in problems]
    native = {"integrations": {n: {"verdict": v, "why": w} for n, (v, w) in rows.items()}, "problems": problems,
              "standins": seen}
    worst = [w for v, w in rows.values() if v != "passed"] + problems
    return [Signal("integrations", combine_verdicts(verdicts), native,
                   "; ".join(worst[:4]) if worst else f"{len(rows)} integration(s) met on their stand-ins")]
