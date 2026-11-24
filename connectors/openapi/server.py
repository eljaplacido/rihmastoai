"""A narrow, read-only MCP server for an ERP or business API that an OpenAPI document describes, over stdio.

Standard library only. It reads an OpenAPI 3 document in this folder (`--document`, default openapi.json),
which the connector card pins with the rest of the folder, and offers two tools:

- `list_operations`: the document's GET operations: each one's operationId, path, summary and parameters;
- `call_operation`: one GET operation by its operationId, with the path and query parameters the document
  declares for it and no others. The JSON answer comes back (at most 256 KiB).

No other method is ever sent: an operation that posts, puts, patches or deletes is neither listed nor
callable, so a model in the lane cannot write through it. It reaches only `OPENAPI_BASE_URL` (https, or
http on loopback only), with `OPENAPI_TOKEN` as a bearer token when it is set. SAP (OData), Dynamics 365,
NetSuite (REST) and other business systems publish OpenAPI documents; how each signs in differs, and a
token command IT runs (`cmd:` in connector.json) can give the token.

    python server.py [--document openapi.json]   serve the pinned tools (fixtures/tools.json)
    python server.py --rug-pull                   serve a changed tools/list, for the contract suite
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL = "2025-06-18"
MAX_BODY = 256 * 1024
LOOPBACK = ("127.0.0.1", "localhost", "::1")
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _fixture(name: str) -> Any:
    return json.loads((HERE / "fixtures" / name).read_text(encoding="utf-8"))


def operations(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The document's GET operations by operationId: path, summary, and parameters by where they go."""
    out: dict[str, dict[str, Any]] = {}
    for path, item in (document.get("paths") or {}).items():
        op = (item or {}).get("get") if isinstance(item, dict) else None
        if not isinstance(op, dict) or not op.get("operationId"):
            continue
        params = [p for p in (item.get("parameters") or []) + (op.get("parameters") or []) if isinstance(p, dict)]
        out[str(op["operationId"])] = {"path": path, "summary": str(op.get("summary", "")),
                                       "path_params": [p["name"] for p in params if p.get("in") == "path"],
                                       "query_params": [p["name"] for p in params if p.get("in") == "query"]}
    return out


def _url(base: str, op: dict[str, Any], args: dict[str, Any]) -> tuple[str | None, str | None]:
    """The URL of one call, or why it may not be made."""
    unknown = sorted(set(args) - set(op["path_params"]) - set(op["query_params"]))
    if unknown:
        return None, "parameters the document does not declare: " + ", ".join(unknown)
    missing = [p for p in op["path_params"] if not str(args.get(p, "")).strip()]
    if missing:
        return None, "missing path parameters: " + ", ".join(missing)
    path = _PARAM.sub(lambda m: urllib.parse.quote(str(args[m.group(1)]), safe=""), op["path"])
    query = {k: str(v) for k, v in args.items() if k in op["query_params"]}
    return base.rstrip("/") + path + ("?" + urllib.parse.urlencode(sorted(query.items())) if query else ""), None


def call(env: dict[str, str], document: dict[str, Any], name: str, args: dict[str, Any]) -> tuple[Any, bool]:
    """(the tool's result, whether it is an error)."""
    ops = operations(document)
    if name == "list_operations":
        return {"operations": [{"operation_id": k, **v} for k, v in sorted(ops.items())]}, False
    if name != "call_operation":
        return {"error": f"no tool {name}: this server only reads"}, True
    base = env.get("OPENAPI_BASE_URL", "")
    parts = urllib.parse.urlsplit(base)
    if not (parts.scheme == "https" or parts.scheme == "http" and parts.hostname in LOOPBACK):
        return {"error": "OPENAPI_BASE_URL must be an https URL (http only on loopback)"}, True
    op_id = str(args.get("operation_id", ""))
    if op_id not in ops:
        return {"error": f"{op_id or 'that'} is not a GET operation of the document"}, True
    params = args.get("parameters") or {}
    url, why = _url(base, ops[op_id], params if isinstance(params, dict) else {})
    if url is None:
        return {"error": why}, True
    headers = {"Accept": "application/json"} | (
        {"Authorization": "Bearer " + env["OPENAPI_TOKEN"]} if env.get("OPENAPI_TOKEN") else {})
    try:
        with _NO_PROXY.open(urllib.request.Request(url, method="GET", headers=headers), timeout=30) as resp:
            body = resp.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        return {"error": f"the API answered {exc.code}", "operation_id": op_id}, True
    if len(body) > MAX_BODY:
        return {"error": "the answer is larger than 256 KiB: narrow the call"}, True
    return {"operation_id": op_id, "data": json.loads(body or b"null")}, False


def handle(msg: dict[str, Any], env: dict[str, str], document: dict[str, Any], rug_pull: bool) -> dict | None:
    """The answer to one message; None for a notification."""
    if "id" not in msg:
        return None
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        result: Any = {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "rihmasto-openapi-read", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _fixture("rugpull-tools.json" if rug_pull else "tools.json")["tools"]}
    elif method == "tools/call":
        try:
            out, error = call(env, document, str(params.get("name")), params.get("arguments") or {})
        except (OSError, ValueError) as exc:
            out, error = {"error": f"{type(exc).__name__}: the API could not be read"}, True
        result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": msg["id"], "result": result}


def main(argv: list[str]) -> int:
    name = argv[argv.index("--document") + 1] if "--document" in argv[:-1] else "openapi.json"
    document = json.loads((HERE / Path(name).name).read_text(encoding="utf-8"))  # a file of this folder only
    rug_pull, env = "--rug-pull" in argv, dict(os.environ)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            answer: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None,
                                             "error": {"code": -32700, "message": "parse error"}}
        else:
            answer = handle(msg, env, document, rug_pull) if isinstance(msg, dict) else None
        if answer is not None:
            sys.stdout.write(json.dumps(answer, ensure_ascii=True) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
