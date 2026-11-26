"""People in the loop's write routes for the completeness tables (tests/test_brief_ln.py, tests/test_access.py;
FR-HITL1): each signed, in an order where each one's target exists. An ask is put to a product owner, sent (no
channel is set up, so it says so), carried on a link for a person outside, the link withdrawn, a nudge asked,
then the ask answered; a family's level set and the channels saved."""

from __future__ import annotations

from typing import Any


def write_routes(case: Any, w: dict[str, Any]) -> list:
    b = w["built"].pid
    base = f"/api/projects/{b}/hitl"

    def qid(got: dict[str, Any]) -> str:
        return got["post_hitl_ask"]["ask"]["id"]

    def as_po(who: str, got: dict[str, Any]) -> dict[str, Any]:
        return {"person": who, "persona": "product_owner"}

    return [
        ("post_hitl_ask", "POST", f"{base}/asks",
         lambda who, got: {"text": "May we keep the loan history for two years?", "kind": "decision",
                           "family": "legal", "to_persona": "product_owner", "options": ["Yes", "No"],
                           **as_po(who, got)}),
        ("post_hitl_send", "POST", f"{base}/send", lambda who, got: {"ask": qid(got), **as_po(who, got)}),
        ("post_hitl_link", "POST", f"{base}/links",
         lambda who, got: {"name": "Maria Example", "role": "External legal counsel", "asks": [qid(got)],
                           "channel": "copy", **as_po(who, got)}),
        ("post_hitl_link_revoke", "POST", f"{base}/revoke",
         lambda who, got: {"link": got["post_hitl_link"]["link"]["id"], **as_po(who, got)}),
        ("post_hitl_nudge", "POST", f"{base}/nudge", as_po),
        ("post_hitl_answer", "POST", f"{base}/answer",
         lambda who, got: {"ask": qid(got), "answer": "Yes", "comment": "within the GDPR's limits", **as_po(who, got)}),
        ("put_hitl_enforcement", "PUT", f"{base}/enforcement",
         lambda who, got: {"family": "legal", "level": "require", **as_po(who, got)}),
        ("put_hitl_channels", "PUT", "/api/hitl/channels",
         lambda who, got: {"provider": "meta", "url": "http://127.0.0.1:9/v19.0/123/messages",
                           "key_env": "WHATSAPP_TEST_KEY", "person": who, "persona": "it"}),
    ]
