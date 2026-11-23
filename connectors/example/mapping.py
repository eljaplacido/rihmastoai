"""The example connector's mapping: pure functions from what a read tool returned to proposals.

No I/O, no network and no model. A proposal is a signal with the item's ref in this connector's
namespace; its text is the item's title quoted as untrusted data (kernel.connectors.quote): no HTML,
no hidden characters, its URLs never fetched. A proposal decides nothing: a person triages the
signal, and a person decides whatever card it becomes.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.connectors import quote

NAMESPACE = "example"
_KEY = re.compile(r"[A-Z][A-Z0-9]{0,9}-[0-9]{1,7}\Z")


def to_proposal(item: dict[str, Any]) -> dict[str, Any]:
    """One item as one signal proposal. An item whose key is not a tracker key is refused."""
    key = str(item.get("key", ""))
    if not _KEY.match(key):
        raise ValueError("an item's key looks like EX-12")
    ref = f"{NAMESPACE}:{key}"
    return {"kind": "signal", "channel": "feed", "ref": ref, "text": quote(item.get("title", ""), ref=ref)}


def from_result(tool: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """The proposals one read tool's result makes: one per listed item, or the one item fetched."""
    if tool == "list_items":
        return [to_proposal(item) for item in result.get("items", [])]
    if tool == "get_item":
        return [to_proposal(result)]
    raise ValueError(f"no mapping for the tool {tool}")
