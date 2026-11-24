"""An in-process fake of the pinned Snowflake MCP server, for the connector contract suite.

It answers MCP's JSON-RPC as the pinned server does with tools_config.yaml: `initialize`, `tools/list`
(fixtures/tools.json, or a changed one with `rug_pull=True`) and `tools/call` for the read tools, from
fixtures/warehouse.json. `run_snowflake_query` runs on an in-memory SQLite database seeded from that file
and refuses every statement but SELECT, SHOW and DESCRIBE, as the configuration's permissions do. The
object tools that create, drop or alter refuse too. Standard library only; no socket, no file written.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
READ = re.compile(r"(?is)\A\s*(?:select|with|show|describe|desc)\b")
WRITE_PROBE = {"name": "run_snowflake_query", "arguments": {"statement": "DROP TABLE SALES"}}


def _fixture(name: str) -> Any:
    return json.loads((HERE / "fixtures" / name).read_text(encoding="utf-8"))


class FakeServer:
    """The pinned server, faked: call ``handle`` with each JSON-RPC message."""

    def __init__(self, *, rug_pull: bool = False) -> None:
        self.rug_pull = rug_pull
        self.data = _fixture("warehouse.json")
        self.db = sqlite3.connect(":memory:")
        for statement in self.data["seed"]:
            self.db.execute(statement)

    def _query(self, statement: str) -> tuple[Any, bool]:
        if not READ.match(statement) or ";" in statement.strip().rstrip(";"):
            return {"error": "the statement type is not permitted by the service configuration"}, True
        try:
            cur = self.db.execute(statement)
        except sqlite3.Error as exc:
            return {"error": str(exc)}, True
        names = [d[0] for d in cur.description or []]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()], False

    def _call(self, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
        objects = self.data["objects"]
        if name == "list_objects":
            return [o for o in objects if args.get("database_name") in (None, o["database_name"])
                    and args.get("schema_name") in (None, o["schema_name"])], False
        if name == "describe_object":
            found = next((o for o in objects if ".".join((o["database_name"], o["schema_name"], o["name"]))
                          == args.get("object_name")), None)
            if found is None:
                return {"error": "no such object"}, True
            cols = self.db.execute(f"PRAGMA table_info({found['name']})").fetchall() \
                if re.fullmatch(r"[A-Z_]+", found["name"]) else []
            return {**found, "columns": [{"name": c[1], "type": c[2]} for c in cols]}, False
        if name == "run_snowflake_query":
            return self._query(str(args.get("statement", "")))
        return {"error": f"{name} is not permitted by the service configuration"}, True

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        if "id" not in msg:
            return None
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            result: Any = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                           "capabilities": {"tools": {"listChanged": False}},
                           "serverInfo": {"name": "snowflake-labs-mcp (fake)", "version": "0"}}
        elif method == "tools/list":
            result = {"tools": _fixture("rugpull-tools.json" if self.rug_pull else "tools.json")["tools"]}
        elif method == "tools/call":
            out, error = self._call(str(params.get("name")), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(out, default=str)}], "isError": error}
        else:
            return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": msg["id"], "result": result}
