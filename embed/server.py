"""The embed server: what a website talks to when it carries a Rihma chat.

It is deliberately separate from the cockpit. The cockpit stays on loopback with its one-use sign-in;
this server answers only two things:

- `GET /e/<id>/widget.js`: the chat widget (one static file, no external assets);
- `POST /e/<id>/messages`: one turn of the chat. It needs the embed's key and an `Origin` header the
  embed allows. CORS is answered for allowed origins only.

It never serves the canon, the ledger, the cockpit or another project. By default it listens on
127.0.0.1; IT puts it behind their TLS reverse proxy (`--behind-proxy` allows another address).

A website's snippet points here, never at the cockpit: the cockpit is told this server's public
address (`--embed-base https://...` or `RIHMA_EMBED_BASE`) and writes it into each snippet.

With `--model gnomon` the chat runs Gnomon's `assistant` role in a lane of its own
(`<lanes root>/embed/analyst`), never in the factory's analyst lane: a turn waits at most
LANE_WAIT seconds for that lane and gives the model at most `--model-timeout` seconds. On a busy
lane or any model failure the message is filed without a model reply.

    python -m embed.server --home <factory home> --port 8790 [--model gnomon]
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import re
import sys
import time
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, NamedTuple

from kernel.access_isolation import serve
from kernel.embeds import LOCAL_EMBED_PORT, BadTurn, EmbedRefused, RateLimit, converse, embeds
from kernel.filelock import LockHeld
from kernel.lanes import lane_lock
from kernel.model import Model, ModelError, run_gnomon_task
from kernel.store import Factory

STATIC = Path(__file__).parent / "static"
MAX_BODY = 32 * 1024
SOCKET_TIMEOUT = 15        # seconds a connection may stall while it sends its request
MODEL_TIMEOUT = 60         # seconds a chat turn gives the model, all told
DEADLINE_GRACE = 15        # of those, the last ones are for Gnomon to stop at its own deadline
LANE_WAIT = 10.0           # seconds a turn waits for the chat's lane before it files without a reply
LANE_POLL = 0.2
_ROUTE = re.compile(r"^/e/(E-\d{3,})/(widget\.js|messages)$")


class ChatModel(Model):
    """Gnomon's `assistant` role for public chat turns, in a lane of its own.

    A website's turn never waits on the factory's own model work, nor holds it up: the lane is
    the embed server's own, a turn waits at most ``lane_wait`` seconds for it (the server's other
    turns share it) and a Gnomon task gets at most ``timeout`` seconds. It keeps no task records,
    because the server runs for months. Every failure raises (LockHeld, ModelError), and the turn
    is filed without a model reply."""

    def __init__(self, lane_dir: str | Path, *, timeout: int = MODEL_TIMEOUT, lane_wait: float = LANE_WAIT) -> None:
        self.lane_dir, self.timeout, self.lane_wait = Path(lane_dir), timeout, lane_wait

    def ask(self, prompt: str, *, role: str) -> str:
        with ExitStack() as held:
            self._hold_lane(held)
            record = run_gnomon_task(self.lane_dir, prompt, role=role, timeout=self.timeout,
                                     deadline=max(1, self.timeout - DEADLINE_GRACE))
        output = record.get("output")
        if record.get("bucket") == "apparatus_failure" or not isinstance(output, str) or not output.strip():
            raise ModelError(f"gnomon task --role {role} gave no answer (stop: {record.get('stop_reason')})")
        return output

    def _hold_lane(self, held: ExitStack) -> None:
        """Take the lane's lock, waiting at most ``lane_wait`` seconds; LockHeld after that."""
        give_up = time.monotonic() + self.lane_wait
        while True:
            try:
                held.enter_context(lane_lock(self.lane_dir, blocking=False))
                return
            except LockHeld:
                if time.monotonic() >= give_up:
                    raise
                time.sleep(LANE_POLL)


def chat_model(routing: dict | None = None, *, root: Path | None = None, timeout: int = MODEL_TIMEOUT,
               lane_wait: float = LANE_WAIT) -> ChatModel:
    """The chat's model, in ``<lanes root>/embed/analyst``: a toolless analyst lane of its own, never
    the factory's analyst lane, whose lock intake, spec, holdout authoring and the cockpit's
    assistant share."""
    from kernel.lanes import ensure_analyst_lane, lanes_root, load_routing

    lane = ensure_analyst_lane(routing or load_routing(), root=Path(root or lanes_root()) / "embed")
    return ChatModel(lane, timeout=timeout, lane_wait=lane_wait)


def _allowed_origin(factory: Factory, embed_id: str, origin: str | None) -> str | None:
    e = next((x for x in embeds(factory) if x["id"] == embed_id and x["state"] == "active"), None)
    o = (origin or "").rstrip("/").lower()
    return origin if e and o in e["origins"] else None


def _log_error(embed_id: str, exc: BaseException) -> None:
    sys.stderr.write(f"embed {embed_id}: a turn failed: {type(exc).__name__}: {exc}\n")


def _turn(factory: Factory, embed_id: str, origin: str | None, body: dict, *, model: Model | None,
          rate: RateLimit) -> tuple[int, dict]:
    """One chat turn as (status, answer). Only words written for the website reach it: a refusal,
    a turn it cannot read, or a fixed line. An internal error's text (a path, a project id) stays
    in this server's log."""
    try:
        out = converse(factory, embed_id, str(body.get("key", "")), origin, body.get("history") or [],
                       model=model, rate=rate)
    except EmbedRefused as exc:
        return (429 if "too many" in str(exc) else 403), {"error": str(exc)}
    except BadTurn as exc:
        return 400, {"error": str(exc)[:200]}
    except (LockHeld, OSError) as exc:  # busy or failing files: nothing was promised to the website
        _log_error(embed_id, exc)
        return 503, {"error": "the chat is busy: please try again in a moment"}
    except Exception as exc:  # anything else is logged here and never shown to the website
        _log_error(embed_id, exc)
        return 500, {"error": "the chat is not available just now"}
    filed = {"kind": out["filed"]["kind"], "ref": out["filed"]["id"]} if out["filed"] else None
    return 200, {"reply": out["reply"], "filed": filed}


class _Chat(NamedTuple):
    """What a handler serves: the factory, the chat's model (or none) and the rate limit."""

    factory: Factory
    model: Model | None
    rate: RateLimit


class EmbedHandler(BaseHTTPRequestHandler):
    """The two routes. make_handler sets ``chat`` and ``timeout`` for each server."""

    chat: _Chat
    timeout: ClassVar[float | None] = SOCKET_TIMEOUT   # a stalled connection raises and closes, freeing its thread
    server_version = "rihma-embed"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "verbose", False):
            sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    def _send(self, status: int, body: bytes, ctype: str, origin: str | None = None,
              extra: dict | None = None) -> None:
        headers = {"Content-Type": ctype, "Content-Length": str(len(body)), "X-Content-Type-Options": "nosniff",
                   "Referrer-Policy": "no-referrer", "Cache-Control": "no-store", "Vary": "Origin"}
        if origin:
            headers["Access-Control-Allow-Origin"] = origin
        headers.update(extra or {})                      # an answer's own header replaces the default
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: dict, origin: str | None = None) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8", origin)

    def do_GET(self) -> None:
        m = _ROUTE.match(self.path.split("?")[0])
        if not m or m.group(2) != "widget.js":
            self._json(404, {"error": "not found"})
            return
        body = (STATIC / "widget.js").read_bytes()
        self._send(200, body, "text/javascript; charset=utf-8",
                   extra={"Cache-Control": "public, max-age=300", "Cross-Origin-Resource-Policy": "cross-origin"})

    def do_OPTIONS(self) -> None:
        m = _ROUTE.match(self.path.split("?")[0])
        origin = _allowed_origin(self.chat.factory, m.group(1), self.headers.get("Origin")) if m else None
        if not m or m.group(2) != "messages" or not origin:
            self._send(403, b"", "text/plain")
            return
        self._send(204, b"", "text/plain", origin, {"Access-Control-Allow-Methods": "POST",
                                                    "Access-Control-Allow-Headers": "Content-Type",
                                                    "Access-Control-Max-Age": "600"})

    def _body(self, origin: str) -> dict | None:
        """The request's JSON object; None once a 400 or 413 is sent, or the client stopped sending."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(413 if length > MAX_BODY else 400, {"error": "empty or too large"}, origin)
            return None
        try:
            raw = self.rfile.read(length)
        except OSError:                                  # it stopped sending: the socket timed out
            self.close_connection = True
            return None
        try:
            body = json.loads(raw)
        except ValueError:                               # not JSON, or not UTF-8
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": "the body is a JSON object with a key and a history"}, origin)
            return None
        return body

    def do_POST(self) -> None:
        m = _ROUTE.match(self.path.split("?")[0])
        origin = _allowed_origin(self.chat.factory, m.group(1), self.headers.get("Origin")) if m else None
        if not m or m.group(2) != "messages":
            self._json(404, {"error": "not found"})
        elif not origin:
            self._json(403, {"error": "this website is not allowed to use the embed"})
        elif (body := self._body(origin)) is not None:
            status, out = _turn(self.chat.factory, m.group(1), self.headers.get("Origin"), body,
                                model=self.chat.model, rate=self.chat.rate)
            self._json(status, out, origin)


def make_handler(factory: Factory, *, model: Model | None = None, rate: RateLimit | None = None,
                 timeout: float = SOCKET_TIMEOUT) -> type[EmbedHandler]:
    class Handler(EmbedHandler):
        pass

    Handler.chat = _Chat(factory, model, rate or RateLimit(factory.clock))
    Handler.timeout = timeout
    return Handler


def make_server(factory: Factory, port: int = 0, *, host: str = "127.0.0.1", model: Model | None = None,
                rate: RateLimit | None = None, behind_proxy: bool = False,
                timeout: float = SOCKET_TIMEOUT) -> ThreadingHTTPServer:
    if not behind_proxy and not ipaddress.ip_address(host).is_loopback:
        raise ValueError("the embed server listens on loopback unless --behind-proxy says IT fronts it with TLS")
    return ThreadingHTTPServer((host, port), make_handler(factory, model=model, rate=rate, timeout=timeout))


def main(argv: list[str] | None = None) -> int:
    import os

    from kernel.store import HOME_ENV, RIHMA_HOME_ENV

    ap = argparse.ArgumentParser(prog="python -m embed.server", description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--home", help=f"the factory home (default ${RIHMA_HOME_ENV} or ${HOME_ENV})")
    ap.add_argument("--port", type=int, default=LOCAL_EMBED_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--behind-proxy", action="store_true", help="allow a non-loopback address behind IT's TLS proxy")
    ap.add_argument("--model", choices=("none", "gnomon"), default="none",
                    help="gnomon: the chat asks one clarifying question when a message is vague (role 'assistant'), "
                         "in the embed's own lane")
    ap.add_argument("--model-timeout", type=int, default=MODEL_TIMEOUT,
                    help=f"seconds a turn gives the model before it files without a reply (default {MODEL_TIMEOUT})")
    args = ap.parse_args(argv)
    home = args.home or os.environ.get(RIHMA_HOME_ENV) or os.environ.get(HOME_ENV) or "var"
    factory = Factory(home)
    serve(factory)    # access enforced: the chat's Gnomon calls go through IT's isolation runner (D-0016)
    model = chat_model(timeout=args.model_timeout) if args.model == "gnomon" else None
    srv = make_server(factory, args.port, host=args.host, model=model, behind_proxy=args.behind_proxy)
    print(json.dumps({"listening": f"http://{args.host}:{srv.server_address[1]}", "home": str(Path(home).resolve()),
                      "model": f"gnomon in {model.lane_dir}" if model else "none",
                      "snippets": "give the cockpit this server's public https address: --embed-base or "
                                  "RIHMA_EMBED_BASE"}), flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
