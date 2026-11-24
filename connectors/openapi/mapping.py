"""The OpenAPI business-API connector's mapping: pure functions from what a read tool returned to proposals.

No I/O, no network and no model. A record an operation returned (an order, a customer, a cost centre)
becomes an observation whose ref names the operation and the record's id (`api:listOrders/1001`); an
operation of the document becomes a note (`api:operation/listOrders`). Every text is quoted as untrusted
data (kernel.connectors.quote): a record's fields are text anyone with access to the system wrote. A
proposal decides nothing: a write to an ERP is a decided write, planned (docs/integrations.md).
"""

from __future__ import annotations

import json
import re
from typing import Any

from kernel.connectors import quote

NAMESPACE = "api"
_ID = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")
_OP = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z")
MAX_QUOTED = 600


def to_proposal(record: dict[str, Any], operation: str = "record") -> dict[str, Any]:
    """One record as an observation. A record with no usable id, or an unusable operation name, is refused."""
    rid = str(record.get("id", ""))
    if not _ID.match(rid) or not _OP.match(operation):
        raise ValueError("a record carries an id such as 1001, from an operation such as listOrders")
    ref = f"{NAMESPACE}:{operation}/{rid}"
    text = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)[:MAX_QUOTED]
    return {"kind": "observation", "ref": ref, "text": quote(text, ref=ref)}


def from_result(tool: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """The proposals one read tool's result makes."""
    if tool == "list_operations":
        out = []
        for op in result.get("operations", []):
            if not _OP.match(str(op.get("operation_id", ""))):
                continue
            ref = f"{NAMESPACE}:operation/{op['operation_id']}"
            out.append({"kind": "note", "ref": ref,
                        "text": quote(f"GET {op.get('path')}: {op.get('summary', '')}", ref=ref)})
        return out
    if tool == "call_operation":
        data = result.get("data")
        records = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        return [to_proposal(r, str(result.get("operation_id", "record"))) for r in records if isinstance(r, dict)]
    raise ValueError(f"no mapping for the tool {tool}")
