"""The gateway's HTTP server: one OpenAI-compatible endpoint, served by workload.

- `POST /v1/chat/completions`: `model` names a workload ("classify", "dev-assistant"), never a model.
- `GET /v1/models`: the workloads.
- `GET /v1/deferred/<id>`: the outcome of a request queued at L4.
- `GET /health`: the site mode, the slots in use per class and the queue length.

It listens on 127.0.0.1 by default and refuses another address unless `--behind-proxy` says a TLS
reverse proxy fronts it. It has no client authentication of its own: on loopback only local
processes reach it, and behind a proxy the proxy authenticates.

    python -m gateway.server --config gateway.json [--port 8792] [--host 127.0.0.1 [--behind-proxy]]
    python -m gateway.server --config gateway.json --verify-audit
    python -m gateway.server --config gateway.json --check-pack capability-pack.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from gateway.config import GatewayConfig, load_config
from gateway.packs import check as check_pack
from gateway.packs import declared_workloads
from gateway.router import Gateway, Reply
from gateway.upstream import loopback_host

MAX_BODY = 4 * 1024 * 1024
_DEFERRED = re.compile(r"^/v1/deferred/(dfr-[A-Za-z0-9_-]{8,64})$")


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], gateway: Gateway, *, verbose: bool = False) -> None:
        super().__init__(address, GatewayHandler)
        self.gateway = gateway
        self.verbose = verbose


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "rihma-gateway"
    sys_version = ""
    server: GatewayServer

    def log_message(self, format: str, *args: Any) -> None:
        # The request line and status only: never a header (a key) or a body (content).
        if self.server.verbose:
            sys.stderr.write(f"{self.address_string()} - {format % args}\n")

    def _send(self, reply: Reply) -> None:
        body = json.dumps(reply.body).encode("utf-8")
        self.send_response(reply.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in reply.headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status: int, message: str) -> None:
        self._send(Reply(status, {"error": {"message": message, "type": "invalid_request_error", "code": None}}))

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        gateway = self.server.gateway
        if path == "/v1/models":
            return self._send(Reply(200, gateway.models()))
        if path == "/health":
            return self._send(Reply(200, gateway.health()))
        m = _DEFERRED.match(path)
        if m:
            return self._send(gateway.deferred(m.group(1)))
        self._fail(404, "not found")

    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/v1/chat/completions":
            return self._fail(404, "not found")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY:
            too_large = length > MAX_BODY
            return self._send(self.server.gateway.refuse(413 if too_large else 400, "the body is empty or too large",
                                                         "body_too_large" if too_large else "empty_body"))
        try:
            body = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = None  # the gateway refuses it, and the refusal is audited
        self._send(self.server.gateway.complete(body, self.headers.get("X-Data-Class")))


def make_server(gateway: Gateway, port: int = 0, *, host: str = "127.0.0.1", behind_proxy: bool = False,
                verbose: bool = False) -> GatewayServer:
    """The server, bound but not serving. A non-loopback host needs ``behind_proxy``."""
    if not behind_proxy and not loopback_host(host):
        raise ValueError("the gateway listens on loopback unless --behind-proxy says a TLS proxy fronts it")
    return GatewayServer((host, port), gateway, verbose=verbose)


def start_drainer(gateway: Gateway) -> threading.Event:
    """Retry the L4 queue every `defer.retry_s` seconds in a daemon thread. Set the event to stop it."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(gateway.config.defer.retry_s):
            gateway.drain()

    threading.Thread(target=loop, name="gateway-drain", daemon=True).start()
    return stop


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m gateway.server", description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--config", required=True, help="the gateway config (JSON)")
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--behind-proxy", action="store_true", help="allow a non-loopback address behind a TLS proxy")
    ap.add_argument("--verbose", action="store_true", help="log request lines (never headers or bodies)")
    ap.add_argument("--verify-audit", action="store_true", help="check the audit's hash chain and exit")
    ap.add_argument("--check-pack", metavar="PACK", help="say where the config drifts from a capability pack, and exit")
    return ap


def _verify_audit(gateway: Gateway) -> int:
    result = gateway.audit.verify()
    print(json.dumps({"audit": str(gateway.audit.path), "intact": result.intact, "broken_seq": result.broken_seq,
                      "records": len(gateway.audit.records())}))
    return 0 if result.intact else 1


def _check_pack(config: GatewayConfig, pack_path: str) -> int:
    with open(pack_path, encoding="utf-8") as fh:
        pack = json.load(fh)
    drift = check_pack(config, pack)
    print(json.dumps({"declared": len(declared_workloads(pack)), "drift": drift}, indent=2))
    return 1 if drift else 0


def _serve(gateway: Gateway, args: argparse.Namespace) -> int:
    srv = make_server(gateway, args.port, host=args.host, behind_proxy=args.behind_proxy, verbose=args.verbose)
    stop = start_drainer(gateway)
    config = gateway.config
    print(json.dumps({"listening": f"http://{args.host}:{srv.server_address[1]}/v1", "site_mode": config.site_mode,
                      "workloads": sorted(config.workloads), "audit": str(config.audit_path)}), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.check_pack:
            return _check_pack(config, args.check_pack)
        gateway = Gateway(config)
        return _verify_audit(gateway) if args.verify_audit else _serve(gateway, args)
    except (OSError, ValueError) as exc:  # ConfigError and a refused address are ValueErrors
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
