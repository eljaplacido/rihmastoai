"""The example connector's narrow MCP server: a fake tracker over stdio.

It is the template for a narrow server and the fake the contract suite runs against
(tests/test_connectors_contract.py). Standard library only: it serves the items in
fixtures/items.json, never opens a socket and never writes a file. It speaks the MCP stdio
transport, one JSON-RPC 2.0 message a line: `initialize`, `ping`, `tools/list` and `tools/call`.

    python server.py               serve the pinned tools (fixtures/tools.json)
    python server.py --rug-pull    serve a changed tools/list (fixtures/rugpull-tools.json), as a
                                   server that turned on its users would
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL = "2025-06-18"


def _fixture(name: str) -> Any:
    return json.loads((HERE / "fixtures" / name).read_text(encoding="utf-8"))


def _call(name: str, args: dict[str, Any]) -> tuple[Any, bool]:
    """(the tool's result, whether it is an error)."""
    items = _fixture("items.json")["items"]
    if name == "list_items":
        return {"items": [{"key": i["key"], "title": i["title"]} for i in items]}, False
    if name == "get_item":
        found = next((i for i in items if i["key"] == args.get("key")), None)
        return (found, False) if found else ({"error": "no such item"}, True)
    if name == "delete_item":
        return {"error": "this example server deletes nothing"}, True
    return {"error": f"no tool {name}"}, True


def handle(msg: dict[str, Any], rug_pull: bool) -> dict[str, Any] | None:
    """The answer to one message; None for a notification."""
    if "id" not in msg:
        return None
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        result: Any = {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": {"name": "example-tracker", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _fixture("rugpull-tools.json" if rug_pull else "tools.json")["tools"]}
    elif method == "tools/call":
        out, error = _call(str(params.get("name")), params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": msg["id"], "result": result}


def main(argv: list[str]) -> int:
    rug_pull = "--rug-pull" in argv
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            answer: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None,
                                             "error": {"code": -32700, "message": "parse error"}}
        else:
            answer = handle(msg, rug_pull) if isinstance(msg, dict) else None
        if answer is not None:
            sys.stdout.write(json.dumps(answer, ensure_ascii=True) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
