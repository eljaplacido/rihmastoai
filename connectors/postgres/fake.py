"""An in-process fake of the pinned PostgreSQL MCP server, for the connector contract suite.

It answers MCP's JSON-RPC as the pinned server does in restricted mode: `initialize`, `tools/list` (the
pinned fixtures/tools.json, or a changed one with `rug_pull=True`) and `tools/call` for the read tools,
from fixtures/database.json. `execute_sql` runs on an in-memory SQLite database seeded from that file and,
as restricted mode does, refuses anything but one read statement. Standard library only; it opens no
socket and writes no file. It stands in for the server in tests: Gnomon runs the real one.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
READ = re.compile(r"(?is)\A\s*(?:select|with|explain|show|values)\b")
# A statement the live check and the suite send to prove that a write is refused.
WRITE_PROBE = {"name": "execute_sql", "arguments": {"sql": "CREATE TABLE rihma_write_probe (id integer)"}}


def _fixture(name: str) -> Any:
    return json.loads((HERE / "fixtures" / name).read_text(encoding="utf-8"))


class FakeServer:
    """The pinned server, faked: call ``handle`` with each JSON-RPC message."""

    def __init__(self, *, rug_pull: bool = False) -> None:
        self.rug_pull = rug_pull
        self.data = _fixture("database.json")
        self.db = sqlite3.connect(":memory:")
        for statement in self.data["seed"]:
            self.db.execute(statement)

    def _sql(self, sql: str) -> tuple[Any, bool]:
        if not READ.match(sql) or ";" in sql.strip().rstrip(";"):
            return {"error": "cannot run a statement that writes: the server runs in restricted mode"}, True
        try:
            cur = self.db.execute(sql)
        except sqlite3.Error as exc:
            return {"error": str(exc)}, True
        names = [d[0] for d in cur.description or []]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()], False

    def _call(self, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
        if name == "list_schemas":
            return self.data["schemas"], False
        if name == "list_objects":
            return [o for o in self.data["objects"] if o["schema"] == args.get("schema_name")], False
        if name == "get_object_details":
            found = next((o for o in self.data["objects"] if (o["schema"], o["name"]) ==
                          (args.get("schema_name"), args.get("object_name"))), None)
            if found is None:
                return {"error": "no such object"}, True
            cols = self.db.execute(f"PRAGMA table_info({found['name']})").fetchall() \
                if re.fullmatch(r"[a-z_]+", found["name"]) else []
            return {"basic": found, "columns": [{"column": c[1], "data_type": c[2]} for c in cols]}, False
        if name == "execute_sql":
            return self._sql(str(args.get("sql", "")))
        return {"error": f"{name} is not served by this fake"}, True

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        if "id" not in msg:
            return None
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            result: Any = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                           "capabilities": {"tools": {"listChanged": False}},
                           "serverInfo": {"name": "postgres-mcp (fake)", "version": "0"}}
        elif method == "tools/list":
            result = {"tools": _fixture("rugpull-tools.json" if self.rug_pull else "tools.json")["tools"]}
        elif method == "tools/call":
            out, error = self._call(str(params.get("name")), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(out, default=str)}], "isError": error}
        else:
            return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": msg["id"], "result": result}
