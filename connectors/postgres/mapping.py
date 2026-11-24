"""The PostgreSQL connector's mapping: pure functions from what a read tool returned to proposals.

No I/O, no network and no model. A schema or an object becomes a note with its schema-qualified name as
the ref (`pg:public.orders`); a row a read-only query returned becomes an observation (`pg:result/1`).
Every text is quoted as untrusted data (kernel.connectors.quote): a comment in a database is text anyone
with write access to it wrote. A proposal decides nothing: a person reads the note or the observation.

The server's own result shape is UNVERIFIED offline: postgres-mcp may return JSON or the text form of a
list of rows. `rows` reads both, and the live check (tests/test_connectors_live.py) shows which it is.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from kernel.connectors import quote

NAMESPACE = "pg"
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]{0,62}\Z")


def rows(result: Any) -> list[dict[str, Any]]:
    """The rows a tool returned: a list of objects, an object holding one, or the text of either."""
    if isinstance(result, str):
        text = result.strip()
        try:
            return rows(json.loads(text))
        except ValueError:
            pass
        try:
            return rows(ast.literal_eval(text))  # a Python literal, never evaluated as code
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return []
    if isinstance(result, dict):
        inner = next((result[k] for k in ("rows", "objects", "schemas", "result") if isinstance(result.get(k), list)),
                     None)
        return rows(inner) if inner is not None else [result]
    return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []


def _name(item: dict[str, Any], *keys: str) -> str:
    return str(next((item[k] for k in keys if item.get(k)), ""))


def to_proposal(item: dict[str, Any]) -> dict[str, Any]:
    """One database object as a note. An object whose schema or name is not an SQL identifier is refused."""
    schema = _name(item, "schema", "schema_name", "table_schema") or "public"
    name = _name(item, "name", "object_name", "table_name")
    if not _IDENT.match(schema) or not _IDENT.match(name):
        raise ValueError("an object's schema and name are SQL identifiers, such as public.orders")
    ref = f"{NAMESPACE}:{schema}.{name}"
    text = f"{item.get('type') or item.get('object_type') or 'object'} {schema}.{name}"
    if item.get("comment"):
        text += f": {item['comment']}"
    if item.get("columns"):
        text += "; columns " + ", ".join(f"{c.get('column')} {c.get('data_type')}" for c in item["columns"]
                                         if isinstance(c, dict))
    return {"kind": "note", "ref": ref, "text": quote(text, ref=ref)}


def schema_proposal(item: dict[str, Any]) -> dict[str, Any]:
    name = _name(item, "schema_name", "name")
    if not _IDENT.match(name):
        raise ValueError("a schema's name is an SQL identifier")
    ref = f"{NAMESPACE}:{name}"
    return {"kind": "note", "ref": ref, "text": quote(f"schema {name} owned by {item.get('schema_owner', '?')}",
                                                      ref=ref)}


def row_proposal(row: dict[str, Any], n: int) -> dict[str, Any]:
    ref = f"{NAMESPACE}:result/{n}"
    return {"kind": "observation", "ref": ref, "text": quote(json.dumps(row, default=str, sort_keys=True), ref=ref)}


def from_result(tool: str, result: Any) -> list[dict[str, Any]]:
    """The proposals one read tool's result makes."""
    if tool == "list_schemas":
        return [schema_proposal(r) for r in rows(result)]
    if tool == "list_objects":
        return [to_proposal(r) for r in rows(result)]
    if tool == "get_object_details":
        found = rows(result)
        detail = found[0] if found else {}
        basic = detail.get("basic") if isinstance(detail.get("basic"), dict) else detail
        return [to_proposal({**basic, "columns": detail.get("columns") or []})]
    if tool == "execute_sql":
        return [row_proposal(r, n) for n, r in enumerate(rows(result), 1)]
    raise ValueError(f"no mapping for the tool {tool}")
