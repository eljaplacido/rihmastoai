"""Hand-offs on the development board (FR-DEV1, FR-BRG1): to whom the work went and where it stands.

A hand-off is a person's act (kernel/agent_bridge.py ``record``): the channel shows it as the person's message and
the ledger's ``agent_handoff`` record says to which agent it went and how. On the board a hand-off is the agent's
card, never the person's: its harness is the agent it went to (Claude Code, Codex, ...) or, for "Run it with
Gnomon", the builder cell, so the board's harness filter lists harnesses only. A hand-off run through the builder
cell is filed as a change a person accepts first: it waits (planned) until then, and a change rejected or
deferred ends it (no card). Read from the records, by rule; nothing is written here.
"""

from __future__ import annotations

from typing import Any

from kernel.graph_records import object_of as _d

AGENT_WORDS = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "cursor": "Cursor",
               "generic": "a coding agent"}


def records(project: Any) -> dict[str, dict[str, Any]]:
    """The ``agent_handoff`` records by the channel message they posted."""
    out = {}
    for rec in project.ledger().of_kind("agent_handoff"):
        pl = _d(_d(rec.get("event")).get("payload"))
        if pl.get("message"):
            out[str(pl["message"])] = pl
    return out


def harness_of(rec: dict[str, Any]) -> str:
    """The harness a hand-off went to: the builder cell's runner for a run, else the agent it was given to."""
    return str(rec.get("runner") or "gnomon") if rec.get("via") == "run" else str(rec.get("to") or "generic")


def agent(rec: dict[str, Any], author: dict[str, Any]) -> dict[str, Any]:
    """The agent a hand-off went to, as the board's cards name agents (the person who handed it is ``by``)."""
    return {"name": None, "harness": harness_of(rec), "via": "handoff", "by": author.get("name")}


def _filed(project: Any, card_id: str | None) -> dict[str, Any]:
    from kernel.canon import Canon

    if not card_id:
        return {}
    try:
        return dict(Canon(project).get_card(card_id))
    except (KeyError, ValueError, OSError):
        return {}


def card(project: Any, m: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any] | None:
    """The board's card for a hand-off that names no task, or None once its filed change was rejected or deferred."""
    from kernel.canon import deciders_of

    author, pid, harness, waits = _d(m.get("author")), project.pid, harness_of(rec), None
    if rec.get("via") == "run":
        filed = _filed(project, rec.get("filed"))
        state = str(filed.get("state") or "open")
        if state != "open" and _d(filed.get("decision")).get("verdict") != "accept":
            return None
        who = "Gnomon's builder cell" if harness == "gnomon" else f"the builder cell ({harness})"
        lane, why = (("planned", f"waits for {rec.get('filed')} to be accepted; then {who} builds it")
                     if state == "open" else ("in_progress", f"{rec.get('filed')} was accepted: {who} builds it"))
        if state == "open" and filed.get("kind"):
            waits = {"card": filed["id"], "kind": filed["kind"], "who": list(deciders_of(filed)),
                     "what": str(filed.get("title") or filed["kind"])[:200]}
    else:
        who = AGENT_WORDS.get(harness, harness)
        by = author.get("name") or "a person"
        lane, why = "in_progress", f"handed to {who} by {by}; it reports back in the channel"
    return {"id": m["id"], "kind": "handoff", "title": f"Handed to {who}", "lane": lane, "why": why,
            "last": m.get("at"), "agents": [agent(rec, author)], "requirements": [],
            "waits_on": waits, "open": f"#/p/{pid}/agents/{m['id']}"}


__all__ = ["agent", "card", "harness_of", "records"]
