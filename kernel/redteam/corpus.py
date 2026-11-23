"""The payload corpus of the agentic red team (`payloads.json`), read and checked.

A payload names its category, the surfaces it is sent to (`embed`, `assistant`), the persona that
asks the cockpit assistant, and its turns: a person's messages, and forged assistant messages the
attacker puts into the history. Placeholders in braces name the sandbox's records; any other text
in braces is left as it is, so an attack may carry JSON.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kernel.people import PERSONAS
from kernel.redteam.scope import SURFACES

CORPUS = Path(__file__).with_name("payloads.json")
SCHEMA = "rihmasto.redteam.payloads/1"
PLACEHOLDERS = ("project", "project_title", "other_project", "other_title", "gate_card", "approval_card")
_PLACEHOLDER = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")
_ANY_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_ID = re.compile(r"[A-Z]{2}-\d{2}")
ROLES = ("person", "assistant")


class CorpusError(ValueError):
    """The payload file is not one the red team can run: nothing is sent."""


@dataclass(frozen=True)
class Payload:
    id: str
    category: str
    surfaces: tuple[str, ...]
    persona: str
    turns: tuple[tuple[str, str], ...]   # (role, text); the person's turns are sent, the others forged

    def filled(self, names: dict[str, str]) -> list[tuple[str, str]]:
        """The turns with their placeholders replaced by the sandbox's names."""
        return [(role, _PLACEHOLDER.sub(lambda m: names.get(m.group(1), m.group(0)), text))
                for role, text in self.turns]


@dataclass(frozen=True)
class Corpus:
    categories: dict[str, dict[str, str]]
    payloads: tuple[Payload, ...]
    digest: str

    def for_surface(self, surface: str, categories: list[str] | None = None) -> list[Payload]:
        return [p for p in self.payloads if surface in p.surfaces and (not categories or p.category in categories)]


def _turns(raw: object, where: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list) or not raw:
        raise CorpusError(f"{where}: turns is a non-empty list")
    out: list[tuple[str, str]] = []
    for t in raw:
        role, text = ("person", t) if isinstance(t, str) else \
            ((t.get("role"), t.get("text")) if isinstance(t, dict) else (None, None))
        if role not in ROLES or not isinstance(text, str) or not text.strip():
            raise CorpusError(f"{where}: a turn is a text, or {{\"role\": \"assistant\", \"text\": ...}}")
        unknown = [m for m in _ANY_PLACEHOLDER.findall(text) if m not in PLACEHOLDERS]
        if unknown:
            raise CorpusError(f"{where}: unknown placeholder {{{unknown[0]}}}")
        out.append((str(role), text))
    if out[-1][0] != "person":
        raise CorpusError(f"{where}: the last turn is the person's")
    return tuple(out)


def _payload(raw: object, categories: dict[str, Any], n: int) -> Payload:
    if not isinstance(raw, dict):
        raise CorpusError(f"payload {n} is not an object")
    pid = raw.get("id")
    where = f"payload {pid or n}"
    if not isinstance(pid, str) or not _ID.fullmatch(pid):
        raise CorpusError(f"{where}: an id is two capitals, a hyphen and two digits")
    if raw.get("category") not in categories:
        raise CorpusError(f"{where}: unknown category {raw.get('category')!r}")
    surfaces = raw.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces or any(s not in SURFACES for s in surfaces):
        raise CorpusError(f"{where}: surfaces are some of {SURFACES}")
    persona = raw.get("persona", "stakeholder")
    if persona not in PERSONAS:
        raise CorpusError(f"{where}: persona {persona!r} is not one of the factory's personas")
    return Payload(pid, str(raw["category"]), tuple(surfaces), str(persona), _turns(raw.get("turns"), where))


def _document(raw: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CorpusError(f"the corpus is not JSON in UTF-8: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise CorpusError(f"the corpus is a JSON object with schema {SCHEMA!r}")
    if not isinstance(doc.get("categories"), dict) or not doc["categories"]:
        raise CorpusError("the corpus names its categories")
    return doc


def _categories(raw: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {k: {"title": str(v.get("title") or k), "owasp_llm": str(v.get("owasp_llm") or ""),
                "aim": str(v.get("aim") or "")} for k, v in raw.items() if isinstance(v, dict)}


def load(path: str | Path | None = None) -> Corpus:
    """The corpus at ``path`` (default: the one beside this module), checked. CorpusError otherwise."""
    raw = Path(path or CORPUS).read_bytes()
    doc = _document(raw)
    payloads = [_payload(p, doc["categories"], n) for n, p in enumerate(doc.get("payloads") or [], 1)]
    if not payloads:
        raise CorpusError("the corpus holds no payloads")
    ids = [p.id for p in payloads]
    if len(set(ids)) != len(ids):
        raise CorpusError(f"payload ids are used once: {sorted({i for i in ids if ids.count(i) > 1})}")
    return Corpus(_categories(doc["categories"]), tuple(payloads), hashlib.sha256(raw).hexdigest()[:16])
