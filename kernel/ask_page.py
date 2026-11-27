"""An agent elsewhere answers an ask through its reply link (FR-XAG1): two JSON calls at ``/x/``, no page.

Served by the cockpit beside the reviewer's ``/r/`` (kernel/hitl_page.py), and reached from another machine only
through the cockpit's one trusted https front (``--public-origin``): the Host check of the server holds as for any
other request. An agent (a terminal agent, a script) calls:

- ``POST /x/api/ask`` ``{"token": …}``: the ask's words, why, the answer expected and who asks; the ask counts as
  delivered;
- ``POST /x/api/answer`` ``{"token": …, "answer": …}``: one answer, filed in the project's agent channel as a reply to
  the ask, in the name of the agent asked, vouched for by the person who made the link. The link then closes.

A call is JSON (``Content-Type: application/json``, a small body); a browser on another site cannot send that
without a preflight this server never answers. A call that carries an ``Origin`` must come from this server's own
origin. A real link always answers; refused tries are counted per address with the reviewer links' (kernel/hitl_page.py)
and past their limit in a minute a refused try waits. The token is 256 random bits, kept only as its sha256
(kernel/asks.py). An internal error's words stay in the server's log.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.parse import urlsplit

from kernel import asks, hitl_page
from kernel.canon import DecisionRefused

MAX_BODY = 16_000
HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
           "Cross-Origin-Resource-Policy": "same-origin", "X-Frame-Options": "DENY",
           "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}


def ours(path: str) -> bool:
    p = urlsplit(path).path
    return p == "/x" or p.startswith(asks.LINK_PATH)


def _json(handler: Any, status: int, obj: dict[str, Any]) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    for name, value in HEADERS.items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)


def _origin_ok(handler: Any) -> bool:
    """No Origin (an agent's own client), or this server's own."""
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    hosts = {handler.headers.get("Host") or "", handler.headers.get("X-Forwarded-Host") or ""} - {""}
    return urlsplit(origin).netloc in hosts


def _body(handler: Any, raw: bytes | None) -> dict[str, Any] | None:
    if (handler.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
        return None
    if raw is None or len(raw) > MAX_BODY:
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _read(factory: Any, body: dict[str, Any]) -> dict[str, Any]:
    return asks.read_by_link(factory, str(body.get("token") or ""))


def _answer(factory: Any, body: dict[str, Any]) -> dict[str, Any]:
    return asks.answer_by_link(factory, str(body.get("token") or ""), str(body.get("answer") or ""))


CALLS = {"/x/api/ask": _read, "/x/api/answer": _answer}


def _post(handler: Any, factory: Any, raw: bytes | None) -> tuple[int, dict[str, Any]]:
    call = CALLS.get(urlsplit(handler.path).path)
    if call is None:
        return 404, {"error": "not found"}
    if not _origin_ok(handler):
        return 403, {"error": "a reply link is answered by an agent's own client, not from another site"}
    body = _body(handler, raw)
    if body is None:
        return 400, {"error": "send a small JSON object with Content-Type: application/json"}
    addr = hitl_page.client_of(handler)
    try:
        return 200, call(factory, body)
    except (asks.AskRefused, DecisionRefused) as exc:
        if hitl_page._too_many(addr):
            return 429, {"error": "Too many tries. Wait a minute."}
        hitl_page._failed(addr)
        return 403, {"error": str(exc)}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:  # never shown: the agent gets a plain line, the log the reason
        sys.stderr.write(f"reply link: {type(exc).__name__}: {exc}\n")
        return 500, {"error": "Something went wrong on the cockpit's side. Try again in a moment."}


def serve(handler: Any, factory: Any, raw: bytes | None = None) -> None:
    if handler.command != "POST":
        return _json(handler, 405, {"error": "POST a JSON object to /x/api/ask or /x/api/answer"})
    status, out = _post(handler, factory, raw)
    return _json(handler, status, out)
