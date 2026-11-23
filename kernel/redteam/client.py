"""The red team's only way to send a request: through the scope, within a budget, on loopback.

Every request a dynamic probe sends goes through `Client`, in this order:

1. **the scope, for every request** (`scope.check`, not once per run): a target the factory did
   not deploy, off loopback, or outside an unexpired scope is refused before anything is sent, and
   so is the next request after a scope is revoked or expires mid-run. The client is built by
   checking the target itself, so a refused target never receives a single connection;
2. **the run's request budget**: the request after the last one the budget allows is not sent
   (`BudgetSpent`);
3. **one connection per request**, with a timeout on every socket, no proxy, no redirect followed,
   and at most `MAX_READ` bytes of an answer read.

TLS is verified with the default context. A loopback certificate the default context does not
trust is an answer the run could not get (a coverage gap), never a reason to turn checks off.
"""

from __future__ import annotations

import http.client
import re
import socket
import ssl
import time
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from kernel.redteam.scope import Permit, check
from kernel.redteam.started import Started

DEFAULT_BUDGET = 300
MAX_BUDGET = 1000
TIMEOUT = 5.0
MAX_READ = 256 * 1024
EARLY_WAIT = 0.3
CHUNK = 64 * 1024
_STATUS = re.compile(rb"^HTTP/\d(?:\.\d)? (\d{3})")
_TARGET = re.compile(r"/[\x21-\x7e]*")
# Errors that mean the server dropped the request it was handling, as opposed to never taking it.
DROPPED = ("RemoteDisconnected", "ConnectionResetError", "ConnectionAbortedError", "BrokenPipeError",
           "TimeoutError", "IncompleteRead", "BadStatusLine")


class BudgetSpent(RuntimeError):
    """The run's request budget is spent: this request was not sent."""


@dataclass
class Answer:
    """What came back for one request: a status, or why there was none."""

    method: str
    target: str
    route: str
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    error: str | None = None
    ms: float = 0.0

    @property
    def answered(self) -> bool:
        return self.status is not None

    @property
    def dropped(self) -> bool:
        """The server took the request and then closed the connection, or never answered it."""
        return self.status is None and (self.error or "").split(":")[0] in DROPPED

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    @property
    def content_type(self) -> str:
        return self.header("content-type").split(";")[0].strip().lower()

    @property
    def html(self) -> bool:
        """A page a browser renders as HTML: declared so, or declared nothing (a browser may sniff it)."""
        declared = self.content_type
        return declared in ("text/html", "application/xhtml+xml") or (not declared and bool(self.body))


def _headers(pairs: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in pairs:
        key = name.lower()
        out[key] = f"{out[key]}, {value}" if key in out else value
    return out


def _first_line(sock: socket.socket, wait: float) -> tuple[str, int | None]:
    """("answered", status), or ("timeout" | "closed" | "garbled", None), reading at most ``wait`` seconds."""
    data, deadline = b"", time.monotonic() + wait
    try:
        while b"\r\n" not in data and len(data) < 1024:
            sock.settimeout(max(deadline - time.monotonic(), 0.01))
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
    except TimeoutError:
        if not data:
            return "timeout", None
    except OSError:
        return "closed", None
    if not data:
        return "closed", None
    m = _STATUS.match(data)
    return ("answered", int(m.group(1))) if m else ("garbled", None)


def _send_some(sock: socket.socket, total: int, timeout: float) -> None:
    """Send up to ``total`` bytes of JSON whitespace; stop quietly when the server stops taking them."""
    sock.settimeout(timeout)
    chunk, sent = b" " * CHUNK, 0
    try:
        while sent < total:
            part = chunk[: total - sent]
            sock.sendall(part)
            sent += len(part)
    except OSError:
        return


class Client:
    """Requests to one deployment the scope allows, each checked against the scope first."""

    def __init__(self, project: Any, target: str, *, running: Mapping[str, Started] | None = None,
                 budget: int = DEFAULT_BUDGET, timeout: float = TIMEOUT) -> None:
        if not 1 <= int(budget) <= MAX_BUDGET:
            raise ValueError(f"a run's budget is 1 to {MAX_BUDGET} requests, not {budget}")
        self.project, self.running, self.budget, self.timeout = project, running, int(budget), float(timeout)
        self.permit: Permit = check(project, target, running=running)  # before anything is sent
        parts = urllib.parse.urlsplit(self.permit.base_url)
        self.scheme, self.host = parts.scheme, parts.hostname or ""
        self.port = parts.port or (443 if self.scheme == "https" else 80)
        self.hostport = f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"
        self.prefix = parts.path.rstrip("/")
        self.sent = 0
        self.answers: list[Answer] = []

    def url(self, target: str) -> str:
        return f"{self.scheme}://{self.hostport}{self.prefix}{target}"

    def _admit(self, target: str) -> None:
        """The budget, then the scope, for this one request. Raises before anything is sent."""
        if not _TARGET.fullmatch(target):
            raise ValueError(f"a probe target is a path of printable ASCII, not {target!r}")
        if self.sent >= self.budget:
            raise BudgetSpent(f"the run's budget of {self.budget} requests was spent")
        check(self.project, self.url(target), running=self.running)
        self.sent += 1

    def _connection(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout,
                                               context=ssl.create_default_context())
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)

    def _socket(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.scheme == "https":
            return ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
        return sock

    def request(self, method: str, target: str, *, route: str, body: bytes | None = None,
                headers: Mapping[str, str] | None = None) -> Answer:
        """One request; a 4xx or 5xx is an answer, and no answer is an Answer with its reason."""
        self._admit(target)
        conn, t0 = self._connection(), time.perf_counter()
        try:
            conn.request(method, self.prefix + target, body=body, headers=dict(headers or {}))
            resp = conn.getresponse()
            raw = resp.read(MAX_READ)
            answer = Answer(method, target, route, resp.status, _headers(resp.getheaders()),
                            raw.decode("utf-8", "replace"))
        except (OSError, http.client.HTTPException) as exc:
            answer = Answer(method, target, route, None, error=f"{type(exc).__name__}: {exc}"[:200])
        finally:
            conn.close()
        answer.ms = round((time.perf_counter() - t0) * 1000, 1)
        self.answers.append(answer)
        return answer

    def declared_body(self, method: str, target: str, *, route: str, declared: int, send: int,
                      wait: float) -> Answer:
        """A request that declares a body of ``declared`` bytes and sends at most ``send`` of them.

        Nothing is sent after the headers until the server has had `EARLY_WAIT` seconds to refuse on
        the declared length alone. The answer's error is "timeout" when the server was still waiting
        for the body ``wait`` seconds after the last byte, and "closed" when it cut the body off."""
        self._admit(target)
        head = (f"{method} {self.prefix + target} HTTP/1.1\r\nHost: {self.hostport}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {declared}\r\nConnection: close\r\n\r\n")
        t0 = time.perf_counter()
        try:
            with self._socket() as sock:
                sock.sendall(head.encode("ascii"))
                outcome, status = _first_line(sock, EARLY_WAIT)
                if outcome == "timeout":
                    _send_some(sock, send, self.timeout)
                    outcome, status = _first_line(sock, wait)
        except OSError as exc:
            outcome, status = f"{type(exc).__name__}: {exc}"[:200], None
        answer = Answer(method, target, route, status, error=None if status is not None else outcome,
                        ms=round((time.perf_counter() - t0) * 1000, 1))
        self.answers.append(answer)
        return answer
