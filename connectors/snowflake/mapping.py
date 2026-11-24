"""The Snowflake connector's mapping: pure functions from what a read tool returned to proposals.

No I/O, no network and no model. A table or view becomes a note with its fully qualified name as the ref
(`snowflake:ANALYTICS.PUBLIC.SALES`); a row a SELECT returned becomes an observation
(`snowflake:result/1`). Every text is quoted as untrusted data (kernel.connectors.quote). A proposal
decides nothing.

The server's own result shape is UNVERIFIED offline; `rows` reads a list of objects, an object holding
one, or the JSON text of either.
"""

from __future__ import annotations

import json
import re
from typing import Any

from kernel.connectors import quote

NAMESPACE = "snowflake"
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]{0,254}\Z")


def rows(result: Any) -> list[dict[str, Any]]:
    """The rows a tool returned."""
    if isinstance(result, str):
        try:
            return rows(json.loads(result))
        except ValueError:
            return []
    if isinstance(result, dict):
        inner = next((result[k] for k in ("rows", "objects", "data", "result") if isinstance(result.get(k), list)),
                     None)
        return rows(inner) if inner is not None else [result]
    return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []


def to_proposal(item: dict[str, Any]) -> dict[str, Any]:
    """One warehouse object as a note. A name that is not a Snowflake identifier is refused."""
    parts = [str(item.get(k) or "") for k in ("database_name", "schema_name", "name")]
    if not all(_IDENT.match(p) for p in parts):
        raise ValueError("an object's database, schema and name are identifiers, such as ANALYTICS.PUBLIC.SALES")
    qualified = ".".join(parts)
    ref = f"{NAMESPACE}:{qualified}"
    text = f"{str(item.get('kind') or 'object').lower()} {qualified}"
    if item.get("comment"):
        text += f": {item['comment']}"
    if item.get("columns"):
        text += "; columns " + ", ".join(f"{c.get('name')} {c.get('type')}" for c in item["columns"]
                                         if isinstance(c, dict))
    return {"kind": "note", "ref": ref, "text": quote(text, ref=ref)}


def from_result(tool: str, result: Any) -> list[dict[str, Any]]:
    """The proposals one read tool's result makes."""
    if tool == "list_objects":
        return [to_proposal(r) for r in rows(result)]
    if tool == "describe_object":
        found = rows(result)
        return [to_proposal(found[0])] if found else []
    if tool == "run_snowflake_query":
        out = []
        for n, row in enumerate(rows(result), 1):
            ref = f"{NAMESPACE}:result/{n}"
            out.append({"kind": "observation", "ref": ref,
                        "text": quote(json.dumps(row, default=str, sort_keys=True), ref=ref)})
        return out
    raise ValueError(f"no mapping for the tool {tool}")
