"""The webhook server: where other systems ring the factory's doorbell (kernel/hooks.py, D-0015).

It answers two things only:

- `POST /hooks/<source>`: one delivery from a source IT configured (`rihmasto hooks add`). It is
  verified (a Standard Webhooks or GitHub signature, the timestamp, a delivery id never seen before)
  and becomes a signal or a change proposal carrying only external ids. 202 accepted, 200 already
  received (nothing stored), 401 a signature or timestamp that does not hold, 404 no such source,
  411 no length, 413 a body over the limit (refused before it is read), 400 or 422 a body that names
  no item, 503 a source whose secret this server's environment lacks.
- `GET /health`: 200, for IT's proxy.

It never serves the canon, the ledger, the cockpit or a project, and an answer never carries more
than accepted or a short refusal. It listens on 127.0.0.1; IT puts it behind their TLS reverse
proxy, and `--behind-proxy` allows another address for a proxy on another host. Secrets come from
this process's environment, under the names IT gave each source.

    python -m embed.webhooks --home <factory home> --port 8791
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

from kernel.filelock import LockHeld
from kernel.hooks import MAX_BODY, HookRefused, receive
from kernel.store import Factory, default_home

LOCAL_HOOKS_PORT = 8791
SOCKET_TIMEOUT = 15
_ROUTE = re.compile(r"^/hooks/([a-z0-9][a-z0-9-]{0,39})$")


class HooksHandler(BaseHTTPRequestHandler):
    """The two routes. make_handler sets ``factory`` for each server."""

    factory: Factory
    timeout: ClassVar[float | None] = SOCKET_TIMEOUT
    server_version = "rihmasto-hooks"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        """No access log: IT's proxy keeps one, and each accepted ring is in the factory's ledger."""

    def _json(self, status: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        for k, v in {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body)),
                     "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/health":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})

    def _body(self) -> bytes | None:
        """The request's body; None once a refusal is sent. Its length is checked before it is read."""
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isdigit():
            self._json(411, {"error": "a length is required"})
            return None
        if int(raw) > MAX_BODY:
            self.close_connection = True
            self._json(413, {"error": "the body is too large"})
            return None
        try:
            return self.rfile.read(int(raw))
        except OSError:                                  # it stopped sending: the socket timed out
            self.close_connection = True
            return None

    def do_POST(self) -> None:
        m = _ROUTE.match(self.path.split("?")[0])
        if not m:
            self._json(404, {"error": "not found"})
            return
        body = self._body()
        if body is None:
            return
        try:
            out = receive(self.factory, m.group(1), dict(self.headers.items()), body)
        except HookRefused as exc:
            self._json(exc.status, {"error": str(exc)})
            return
        except (LockHeld, OSError) as exc:  # busy or failing files: nothing was promised to the sender
            sys.stderr.write(f"hooks {m.group(1)}: {type(exc).__name__}: {exc}\n")
            self._json(503, {"error": "busy: try again"})
            return
        except Exception as exc:  # anything else is logged here and never shown to the sender
            sys.stderr.write(f"hooks {m.group(1)}: {type(exc).__name__}: {exc}\n")
            self._json(500, {"error": "not available just now"})
            return
        self._json(out["status"], {"accepted": out["accepted"]})


def make_server(factory: Factory, port: int = 0, *, host: str = "127.0.0.1",
                behind_proxy: bool = False) -> ThreadingHTTPServer:
    """The server on loopback, or on another address only when IT's TLS proxy fronts it."""
    if not behind_proxy and not ipaddress.ip_address(host).is_loopback:
        raise ValueError("the webhook server listens on loopback unless --behind-proxy says IT fronts it with TLS")

    class Handler(HooksHandler):
        pass

    Handler.factory = factory
    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m embed.webhooks", description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--home", help="the factory home (default: $RIHMASTO_HOME, else var/ in the checkout)")
    ap.add_argument("--port", type=int, default=LOCAL_HOOKS_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--behind-proxy", action="store_true", help="allow a non-loopback address behind IT's TLS proxy")
    args = ap.parse_args(argv)
    factory = Factory(args.home or default_home())
    srv = make_server(factory, args.port, host=args.host, behind_proxy=args.behind_proxy)
    sys.stdout.write(json.dumps({"listening": f"http://{args.host}:{srv.server_address[1]}/hooks/<source>",
                                 "home": str(Path(factory.home).resolve()), "pid": os.getpid()}) + "\n")
    sys.stdout.flush()
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
