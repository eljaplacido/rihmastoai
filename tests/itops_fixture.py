"""Neutral stand-ins for what IT checks (FR-ITO1): a service, a database, an API and a certificate, all on this machine.

`Standins()` starts, on loopback ports only:

- an HTTP service: ``/health`` answers 200 with ``{"version": "1.4.2"}``, ``/slow`` answers after ``slow`` seconds,
  ``/down`` answers 503, and ``/api`` answers 401 (it wants a credential, which is never sent) with
  ``X-RateLimit-Remaining`` of ``X-RateLimit-Limit`` set from ``quota`` (remaining, limit);
- a PostgreSQL stand-in that answers the SSL request with ``N``, as a server without TLS does;
- a MySQL stand-in that greets with protocol 10 and version ``8.0.36-standin``.

`populate(factory, s)` (clock fixed at 2026-11-25 by the caller) adds:

- "Order service", a web service at maturity pilot (it delivers to staging on the ``local`` road), whose spec declares
  ``orders_db`` (postgres) bound to the PostgreSQL stand-in, ``ledger_db`` (sqlite) bound to a SQLite file, and
  ``stock_api`` (rest, credential STOCK_API_TOKEN) bound to the service's ``/api``;
- "Team handbook", a knowledge project made from a folder of documents: documents only.

`guard(calls)` are the stand-ins for every way a check goes out (kernel/checks/infra.py ``fetch``, ``connect``,
``resolve`` and ``tls_days``): loopback is reached for real, every other address is refused and recorded, and a
certificate's days left are read from ``CERT_DAYS``. A test never touches the network.

`write_routes(case, w)` are the cockpit's IT checks writes for the completeness tables (tests/test_brief_ln.py,
tests/test_access.py); `cli_writes(pid)` the signed commands for tests/test_access.py.
"""

from __future__ import annotations

import json
import socket
import socketserver
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from kernel.store import Factory, write_json

PERSON = ("Ilkka Example", "it")
LOOPBACK = ("127.0.0.1", "localhost", "::1")
CERT_DAYS: dict[str, float] = {"shop.example.org": 90.0, "expiring.example.org": 3.0, "soon.example.org": 15.0}


class _Http(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (the standard library's name)
        owner = self.server.owner                                    # type: ignore[attr-defined]
        if self.path.startswith("/health"):
            self._send(200, json.dumps({"status": "ok", "version": "1.4.2"}).encode())
        elif self.path.startswith("/slow"):
            time.sleep(owner.slow)
            self._send(200, b"{}")
        elif self.path.startswith("/down"):
            self._send(503, b"down")
        elif self.path.startswith("/api"):
            left, limit = owner.quota
            self._send(401, b"{}", {"X-RateLimit-Remaining": str(left), "X-RateLimit-Limit": str(limit)})
        else:
            self._send(404, b"")


class _Postgres(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        if len(self.request.recv(8)) == 8:
            self.request.sendall(b"N")


class _MySql(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        payload = b"\x0a" + b"8.0.36-standin\x00" + b"\x01\x00\x00\x00" + b"abcdefgh\x00"
        self.request.sendall(len(payload).to_bytes(3, "little") + b"\x00" + payload)


class Standins:
    """The HTTP service, PostgreSQL and MySQL stand-ins, each on its own loopback port."""

    def __init__(self) -> None:
        self.slow, self.quota = 0.0, (80, 100)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), _Http)
        self.http.owner = self                                         # type: ignore[attr-defined]
        self.pg = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Postgres)
        self.my = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _MySql)
        self.threads = []
        for srv in (self.http, self.pg, self.my):
            srv.daemon_threads = True
            t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            t.start()
            self.threads.append(t)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.http.server_address[1]}"

    @property
    def pg_port(self) -> int:
        return int(self.pg.server_address[1])

    @property
    def my_port(self) -> int:
        return int(self.my.server_address[1])

    def stop(self) -> None:
        for srv in (self.http, self.pg, self.my):
            srv.shutdown()
            srv.server_close()
        for t in self.threads:
            t.join(5)


def sqlite_file(folder: Path) -> Path:
    path = folder / "ledger.sqlite3"
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, amount INTEGER)")
    con.commit()
    con.close()
    return path


def populate(factory: Factory, s: Standins, folder: Path) -> dict[str, Any]:
    db = sqlite_file(folder)
    project = factory.new_project("Order service", mode="assume", maturity="pilot", profile="web_service")
    spec = project.read("spec.json") or {}
    integrations = [
        {"name": "orders_db", "kind": "postgres", "via": "sql", "access": "read-write", "data_classes": ["internal"],
         "credentials": ["ORDERS_DB_PASSWORD"], "provenance": "customer-confirmed"},
        {"name": "ledger_db", "kind": "sqlite", "via": "sql", "access": "read", "data_classes": ["internal"],
         "credentials": [], "provenance": "customer-confirmed"},
        {"name": "stock_api", "kind": "rest", "via": "http", "access": "read", "data_classes": ["internal"],
         "credentials": ["STOCK_API_TOKEN"], "provenance": "customer-confirmed"}]
    project.write("spec.json", {"title": "Order service", "requirements": [], **spec, "integrations": integrations})
    write_json(factory.paved_roads_path, {
        "schema": "gnomonfactory.paved_roads/1",
        "roads": {"local": {"kind": "local-process", "configured": True, "environments": ["staging"], "integrations": {
            "orders_db": {"endpoint": f"postgresql://127.0.0.1:{s.pg_port}/orders"},
            "ledger_db": {"endpoint": "sqlite:///" + db.resolve().as_posix()},
            "stock_api": {"endpoint": f"{s.base}/api",
                          "secrets": [{"name": "STOCK_API_TOKEN", "ref": "env:STOCK_STAGING_TOKEN"}]}}}},
        "maturity": {"pilot": {"staging": "local"}}})
    docs = factory.new_project("Team handbook", mode="assume", source_kind="folder", profile="knowledge_tooling")
    return {"project": project, "docs": docs, "db": db}


def guard(calls: list) -> dict[str, Any]:
    """Stand-ins for every way out of the infrastructure checks: loopback only, the rest refused and recorded."""
    from kernel.checks import infra

    real_fetch = infra.fetch

    def host_of(url: str) -> str:
        from urllib.parse import urlsplit

        return urlsplit(url).hostname or ""

    def fetch(url: str, timeout: float) -> dict[str, Any]:
        calls.append(("fetch", url))
        if host_of(url) not in LOOPBACK:
            raise OSError("the test never leaves this machine")
        return real_fetch(url, timeout)

    def connect(address: tuple, timeout: float = 2.0) -> socket.socket:
        calls.append(("connect", address))
        if address[0] not in LOOPBACK:
            raise OSError("the test never leaves this machine")
        return socket.create_connection(address, timeout=timeout)

    def resolve(host: str, timeout: float) -> list[str]:
        calls.append(("resolve", host))
        if host in LOOPBACK:
            return ["127.0.0.1"]
        if host in CERT_DAYS:
            return ["192.0.2.10"]                 # a documentation address: resolved, never reached
        raise OSError(f"{host}: no such name (stand-in)")

    def tls_days(host: str, port: int, timeout: float = 10) -> float:
        calls.append(("tls", host))
        if host not in CERT_DAYS:
            raise OSError("no certificate stand-in for " + host)
        return CERT_DAYS[host]

    return {"fetch": fetch, "connect": connect, "resolve": resolve, "tls_days": tls_days}


def write_routes(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The IT checks' writes on the built project, by IT: types, a check added, the set turned on and run, a platform
    default, an assessment and an eval set."""
    b = w["built"].pid
    it = lambda extra: (lambda who, got: {**extra, "person": who, "persona": "it"})   # noqa: E731
    return [
        ("post_itops_types", "POST", f"/api/projects/{b}/itops/types", it({"types": ["web_service"]})),
        ("post_itops_override", "POST", f"/api/projects/{b}/itops/override",
         it({"check": "tls", "action": "add", "why": "the shop's certificate"})),
        ("post_itops_apply", "POST", f"/api/projects/{b}/itops/apply", it({"only": ["tls"]})),
        ("post_itops_run", "POST", f"/api/projects/{b}/itops/run", it({})),
        ("post_itops_defaults", "POST", "/api/itops/defaults",
         it({"type": "web_service", "check": "dns", "action": "remove", "why": "the CDN answers for it"})),
        ("post_itops_assess", "POST", f"/api/projects/{b}/itops/assess", it({"target": "check:tls"})),
        ("post_itops_evalset", "POST", f"/api/projects/{b}/itops/evalsets",
         it({"set": "role:ask_answers", "on": True})),
    ]


def cli_writes(pid: str) -> dict[str, list[str]]:
    who = ["--person", "Mallory Example", "--persona", "it"]
    return {"itops apply": ["itops", "apply", pid, *who],
            "itops assess": ["itops", "assess", pid, "--target", "infra", *who]}
