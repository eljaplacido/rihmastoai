"""The S3 connector's mapping: pure functions from what a read tool returned to proposals.

No I/O, no network and no model. An object becomes a note whose ref is its bucket and key
(`s3:reports/daily/2026-11-22.csv`); what it says (its first bytes, from `get_object_text`) is quoted
as untrusted data (kernel.connectors.quote), for a file in a bucket is text anyone with write access
wrote. A proposal decides nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.connectors import quote

NAMESPACE = "s3"
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z")
_KEY = re.compile(r"[^\x00-\x1f\x7f]{1,1024}\Z")
MAX_QUOTED = 600


def to_proposal(item: dict[str, Any]) -> dict[str, Any]:
    """One object as a note. A bucket or key that is not one S3 accepts is refused."""
    bucket, key = str(item.get("bucket", "")), str(item.get("key", ""))
    if not _BUCKET.match(bucket) or not _KEY.match(key) or key.startswith("/"):
        raise ValueError("an object is named by its bucket and key, such as reports and daily/2026-11-22.csv")
    ref = f"{NAMESPACE}:{bucket}/{key}"
    text = f"object {key} ({item.get('size', '?')} bytes"
    text += f", modified {item['last_modified']})" if item.get("last_modified") else ")"
    if item.get("text"):
        text += ": " + str(item["text"])[:MAX_QUOTED]
    return {"kind": "note", "ref": ref, "text": quote(text, ref=ref)}


def from_result(tool: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """The proposals one read tool's result makes: one note per listed object, or the one object read."""
    if tool == "list_objects":
        return [to_proposal({**o, "bucket": result.get("bucket")}) for o in result.get("objects", [])]
    if tool in ("get_object_metadata", "get_object_text"):
        return [to_proposal(result)]
    raise ValueError(f"no mapping for the tool {tool}")
