"""Events: the factory's ledgers as `rihma.event/1`, in a CloudEvents 1.0 envelope (D-0015).

Every record of every ledger (each project's and the factory's own, `_factory`) maps to one event.
The kinds people act on have a type of their own in ``CATALOG`` (a card opened or decided, a release,
an incident, a signal); every other kind is `rihma.ledger.<kind>`, so no record is ever without a type.

Events are thin. One carries ids, its type, its place in the ledger and the hashes that chain it, the
id-like values of its payload, and, for a card, the card's kind, a cleaned and redacted title, the
personas it waits on and one deep link to it in the cockpit's Inbox. A card's body, a payload's free
text and anything in the holdout custody never leave: a title is redacted against every string of
every holdout scenario, as written and as cleaned, before it is cut to length, and a payload value is
kept only when it looks like an id.

``clean_text`` is the one rule for text that crosses the factory's edge, out or in: HTML tags and
entities, control and format characters (zero-width, bidirectional overrides, tag characters) are
removed and whitespace is collapsed. kernel/hooks.py and kernel/connectors.py use it for what arrives.
"""

from __future__ import annotations

import functools
import hashlib
import html
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

from kernel.canon import Canon
from kernel.ledger import verify
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, Project

EVENT_SCHEMA = "rihma.event/1"
SPECVERSION = "1.0"
TYPE_PREFIX = "rihma."
CONTENT_TYPE = "application/cloudevents+json; charset=utf-8"
DEFAULT_COCKPIT = "http://127.0.0.1:8787"   # the cockpit's own address (cockpit/server.py DEFAULT_PORT)
HELD = "[held out]"
MIN_HELD = 4             # shorter scenario strings ("GET", "id") are too common to redact
MAX_TITLE = 160
MAX_TEXT = 4000

# The ledger kinds people act on, by their event type (after `rihma.`). Any other kind is
# `rihma.ledger.<kind>`: the catalog names what matters, the rule keeps every kind typed.
CATALOG: dict[str, str] = {
    "card_opened": "card.opened", "decision": "card.decided", "card_closed": "card.closed",
    "approvals_stale": "card.stale",
    "project_created": "project.created", "stage_changed": "project.stage_changed",
    "created_from_concept": "project.created_from_concept", "adopted": "project.adopted",
    "signal_received": "signal.received", "signal_triaged": "signal.triaged", "concept_applied": "concept.applied",
    "change_submitted": "change.submitted", "change_triaged": "change.triaged", "change_applied": "change.applied",
    "contract_compiled": "contract.compiled", "gate": "task.gate", "merged": "task.merged",
    "escalated": "task.escalated",
    "release_started": "release.started", "release_done": "release.done", "release_failed": "release.failed",
    "promoted": "release.promoted", "rolled_back": "release.rolled_back",
    "incident_opened": "incident.opened", "probe_failed": "probe.failed",
    "security_gate": "security.gate", "risk_accepted": "security.risk_accepted",
    "risk_acceptance_expired": "security.risk_expired",
    "autonomy_cap_set": "autonomy.cap_set", "evidence_exported": "evidence.exported",
    "pack_versioned": "pack.versioned", "observation": "observation.recorded",
    "hook_received": "hook.received", "connector_enabled": "connector.enabled",
    "connector_stopped": "connector.stopped", "connector_disabled": "connector.disabled",
}
CARD_EVENTS = ("card.opened", "card.decided")
_CARD_ID_KEY = {"card_opened": "id", "card_closed": "id", "decision": "card"}
# Payload keys whose id-like values an event keeps (a person's name is never one of them).
ID_KEYS = ("id", "card", "kind", "verdict", "state", "release", "task", "signal", "concept", "environment",
           "stage", "finding", "embed", "trigger", "system", "source", "delegation")
# Holdout scenario fields that describe the scenario, not what it sends or expects.
_SCENARIO_META = ("criterion", "kind", "author_role")

_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/#@+-]{0,99}\Z")
_TAG = re.compile(r"<[^<>]{0,2000}>")


# -- text at the edge -----------------------------------------------------------------------------

def _visible(ch: str) -> bool:
    """A character that may cross the edge: not a control, format, private or unassigned one,
    except a newline or a tab."""
    return ch in "\n\t" or unicodedata.category(ch)[0] != "C"


def clean_text(text: object, limit: int = MAX_TEXT, *, one_line: bool = False) -> str:
    """Text with HTML tags and entities, hidden and control characters removed and whitespace
    collapsed, cut to ``limit`` characters. ``one_line`` folds it onto one line."""
    s = _TAG.sub(" ", html.unescape(str(text)))
    s = "".join(ch for ch in s if _visible(ch))
    if one_line:
        s = " ".join(s.split())
    else:
        lines = (" ".join(line.split()) for line in s.splitlines())
        s = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return s[:limit]


def _scenario_strings(value: Any) -> Iterator[str]:
    """The string values in a holdout scenario file, leaving out the fields that only name it."""
    if isinstance(value, str):
        yield value.strip()
    elif isinstance(value, list):
        for item in value:
            yield from _scenario_strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in _SCENARIO_META:
                yield from _scenario_strings(item)


def held_strings(factory: Factory) -> list[str]:
    """Every string of at least MIN_HELD characters in the holdout custody (retired scenarios too),
    longest first: what no event or notice may carry."""
    root = Path(factory.holdouts_dir)
    found: set[str] = set()
    for path in sorted(root.glob("*/*.json")) if root.is_dir() else []:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found.update(s for s in _scenario_strings(doc) if len(s) >= MIN_HELD)
    return sorted(found, key=lambda s: (-len(s), s))


@functools.lru_cache(maxsize=32)
def _forms(held: tuple[str, ...]) -> tuple[str, ...]:
    """Each held string as written and as ``clean_text`` leaves it on one line, longest first. A title
    is cleaned before it goes out, so a held string with HTML or runs of spaces in it is matched as
    cleaned too."""
    found = {s for s in held if s}
    for s in held:
        cleaned = clean_text(s, len(s) + 1, one_line=True)
        if len(cleaned) >= MIN_HELD:
            found.add(cleaned)
    return tuple(sorted(found, key=lambda s: (-len(s), s)))


def redact(text: str, held: Iterable[str]) -> str:
    """``text`` with every held string in it, as written or as cleaned, replaced by HELD."""
    for secret in _forms(tuple(held)):
        if secret in text:
            text = text.replace(secret, HELD)
    return text


# -- the catalog and one event ---------------------------------------------------------------------

def event_type(kind: str) -> str:
    """The CloudEvents type of a ledger kind: the catalog's, else `rihma.ledger.<kind>`."""
    if kind in CATALOG:
        return TYPE_PREFIX + CATALOG[kind]
    return f"{TYPE_PREFIX}ledger.{kind if _KIND.match(kind) else 'unknown'}"


def deep_link(base: str, pid: str, card: str) -> str:
    """The one link a notice carries: the card in its project's Inbox, in the cockpit at ``base``."""
    return f"{base.rstrip('/')}/#/p/{quote(pid, safe='')}/inbox/{quote(card, safe='')}"


def message_id(pid: str, record: dict[str, Any]) -> str:
    """The event's id, and its Standard Webhooks `webhook-id`: the same on every retry, unique per record."""
    digest = hashlib.sha256(f"{pid}\n{record.get('seq')}\n{record.get('hash')}".encode()).hexdigest()
    return f"msg_{digest[:32]}"


def _ids(payload: dict[str, Any], held: list[str]) -> dict[str, Any]:
    """The payload's id-like values under ID_KEYS: numbers, and short strings with no space in them."""
    out: dict[str, Any] = {}
    for key in ID_KEYS:
        value = payload.get(key)
        number = isinstance(value, int) and not isinstance(value, bool)
        if number or (isinstance(value, str) and _ID.match(value) and redact(value, held) == value):
            out[key] = value
    return out


def _actor(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Who the record names as acting: a person and their persona, or the kernel."""
    person = payload.get("person") if kind == "decision" else payload.get("person", payload.get("by"))
    persona = payload.get("persona")
    if isinstance(person, str) and is_person(person) and persona in PERSONAS:
        return {"kind": "person", "id": clean_text(person, 80, one_line=True), "persona": persona}
    return {"kind": "kernel"}


def _card(project: Project, card_id: str, cockpit: str, held: list[str]) -> dict[str, Any]:
    try:
        card = Canon(project).get_card(card_id)
    except (KeyError, OSError, ValueError):
        card = {}
    # Redacted as written, cleaned whole, redacted again as cleaned, and only then cut: a held string
    # that crosses the cut, or that cleaning changed, never goes out in part.
    title = redact(str(card.get("title", "")), held)
    title = redact(clean_text(title, len(title) + 1, one_line=True), held)[:MAX_TITLE]
    return {"id": card_id, "kind": card.get("kind"), "title": title, "state": card.get("state"),
            "waiting": [p for p in card.get("deciders") or [] if p in PERSONAS],
            "link": deep_link(cockpit, project.pid, card_id)}


def to_event(project: Project, record: dict[str, Any], *, cockpit: str = DEFAULT_COCKPIT,
             held: list[str] | None = None) -> dict[str, Any]:
    """One ledger record as a thin `rihma.event/1`."""
    raw = record.get("event")
    ev: dict[str, Any] = raw if isinstance(raw, dict) else {}
    kind = str(ev.get("kind", ""))
    payload: dict[str, Any] = ev["payload"] if isinstance(ev.get("payload"), dict) else {}
    held = held or []
    out: dict[str, Any] = {
        "spec_version": EVENT_SCHEMA, "event_id": message_id(project.pid, record),
        "event_type": event_type(kind)[len(TYPE_PREFIX):], "ledger_kind": kind if _KIND.match(kind) else "unknown",
        "occurred_at": ev.get("at"), "seq": record.get("seq"), "prev_hash": record.get("prev"),
        "record_hash": record.get("hash"), "stream": {"project_id": project.pid},
        "actor": _actor(kind, payload), "correlation": _ids(payload, held)}
    card_id = payload.get(_CARD_ID_KEY.get(kind, ""))
    if isinstance(card_id, str) and _ID.match(card_id):
        out["card"] = _card(project, card_id, cockpit, held)
    return out


def cloudevent(event: dict[str, Any]) -> dict[str, Any]:
    """The event in a CloudEvents 1.0 structured-mode envelope; the event itself is its data."""
    ce: dict[str, Any] = {"specversion": SPECVERSION, "id": event["event_id"],
                          "source": f"/rihmasto/projects/{event['stream']['project_id']}",
                          "type": TYPE_PREFIX + event["event_type"], "datacontenttype": "application/json",
                          "data": event}
    if event.get("occurred_at"):
        ce["time"] = event["occurred_at"]
    if event.get("card"):
        ce["subject"] = event["card"]["id"]
    return ce


def encode(obj: Any) -> bytes:
    """The bytes a body is sent and signed as: compact JSON in UTF-8."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


# -- reading the ledgers ---------------------------------------------------------------------------

def tail(project: Project) -> tuple[list[dict[str, Any]], int | None]:
    """A ledger's records up to its first broken one, and the seq of that break (None when intact).
    A break halts the stream there: nothing after it goes out until the chain is repaired."""
    records = project.ledger().records()
    result = verify(records)
    end = len(records) if result.intact or result.broken_seq is None else result.broken_seq
    return [r for r in records[:end] if isinstance(r, dict)], None if result.intact else result.broken_seq


def heads(factory: Factory) -> dict[str, int]:
    """Each ledger's last seq: where a new subscription starts, so it receives only what comes next."""
    return {p.pid: len(p.ledger().records()) - 1 for p in factory.projects()}
