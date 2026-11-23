"""The ontology of Rihmasto's own records (docs/knowledge-graph.md, section 2; FR-KG1-AC-3).

`kernel/ontology.json` declares which kinds of record exist, which links between them are allowed,
how each link is known (its origin), who may see each kind, which `refs` keys and ledger fields carry
links, and which read model uses each kind and relation. This module reads it with the standard
library and checks it:

- every kind and relation has a stable id (its key, kept apart from its label), a label, a
  description, aliases and at least one consumer; a consumer names a function or method of
  `kernel/graph.py` or `kernel/graph_ask.py`, and it must resolve;
- every enum reference ("canon.CARD_VERDICTS") resolves to a constant in the kernel, so each list
  has one source and is never copied;
- every relation joins declared kinds, allows only declared origins and says which end is upstream;
- every `refs` key maps to a declared relation, or is declared an attribute (a value, not a link);
- every ledger field the graph reads names a declared kind, or null for a plain value.

The file's semver version and its sha256 are stamped on every graph built from it.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ONTOLOGY_FILE = Path(__file__).with_name("ontology.json")
SCHEMA = "rihmasto.ontology/1"
ORIGINS = ("kernel", "convention", "model_proposed", "person_confirmed")
OUTCOMES = ("answered", "ambiguous", "not_found", "not_measured")
CONSUMER_MODULES = ("graph", "graph_ask")
_SEMVER = re.compile(r"\d+\.\d+\.\d+\Z")
_DOTTED = re.compile(r"[a-z_]+(\.[A-Za-z_][A-Za-z0-9_]*)+\Z")


class OntologyError(ValueError):
    """The ontology file cannot be read as an ontology at all."""


@dataclass(frozen=True)
class Ontology:
    """The ontology as read: its data and the sha256 of the file's bytes."""

    data: dict[str, Any]
    sha256: str

    @property
    def version(self) -> str:
        return str(self.data.get("version", ""))

    @property
    def kinds(self) -> dict[str, dict[str, Any]]:
        kinds: dict[str, dict[str, Any]] = self.data.get("kinds") or {}
        return kinds

    @property
    def relations(self) -> dict[str, dict[str, Any]]:
        relations: dict[str, dict[str, Any]] = self.data.get("relations") or {}
        return relations

    @property
    def refs(self) -> dict[str, dict[str, Any]]:
        refs: dict[str, dict[str, Any]] = self.data.get("refs") or {}
        return refs

    @property
    def ledger(self) -> dict[str, dict[str, Any]]:
        ledger: dict[str, dict[str, Any]] = self.data.get("ledger") or {}
        return ledger

    def upstream_is_to(self, relation: str) -> bool:
        """Whether the relation's `to` end is its upstream end (the provenance side)."""
        return self.relations[relation].get("upstream") == "to"

    def visible_to(self, kind: str, audience: str) -> bool:
        return audience in (self.kinds.get(kind) or {}).get("audiences", [])

    def stamp(self) -> dict[str, str]:
        return {"version": self.version, "sha256": self.sha256}


def load(path: Path = ONTOLOGY_FILE) -> Ontology:
    """The ontology file, read. A file that is not a JSON object is an OntologyError."""
    raw = Path(path).read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise OntologyError(f"{Path(path).name} is not JSON: {exc}") from None
    if not isinstance(data, dict):
        raise OntologyError(f"{Path(path).name} is not a JSON object")
    return Ontology(data, hashlib.sha256(raw).hexdigest())


def resolve(ref: str) -> Any:
    """A dotted name in the kernel ("canon.CARD_VERDICTS", "graph.Graph.trace"): the module
    kernel.<first part>, then each attribute after it. A name that does not resolve is a LookupError."""
    if not isinstance(ref, str) or not _DOTTED.match(ref):
        raise LookupError(f"{ref!r} is not a dotted kernel name")
    module, *attrs = ref.split(".")
    try:
        value: Any = importlib.import_module(f"kernel.{module}")
    except ImportError:
        raise LookupError(f"no kernel module {module!r}") from None
    for attr in attrs:
        if not hasattr(value, attr):
            raise LookupError(f"{ref} does not resolve: no {attr!r}")
        value = getattr(value, attr)
    return value


def _enum_problems(where: str, enums: Any) -> list[str]:
    if not isinstance(enums, dict):
        return [f"{where}: enums must be an object"]
    problems: list[str] = []
    for key, ref in enums.items():
        try:
            value = resolve(ref)
        except LookupError as exc:
            problems.append(f"{where}.{key}: the enum reference {ref!r} does not resolve ({exc})")
            continue
        if not isinstance(value, (tuple, list, dict, set, frozenset)) or not value:
            problems.append(f"{where}.{key}: {ref} is not a list of values")
    return problems


def _consumer_problems(where: str, consumers: Any) -> list[str]:
    if not isinstance(consumers, list) or not consumers:
        return [f"{where}: no consumer names the read model that uses it"]
    problems: list[str] = []
    for name in consumers:
        if not isinstance(name, str) or name.split(".")[0] not in CONSUMER_MODULES:
            problems.append(f"{where}: consumer {name!r} is not a read model of {', '.join(CONSUMER_MODULES)}")
            continue
        try:
            if not callable(resolve(name)):
                problems.append(f"{where}: consumer {name} is not a function")
        except LookupError as exc:
            problems.append(f"{where}: consumer {name} does not resolve ({exc})")
    return problems


def _named(where: str, key: str, entry: Any) -> list[str]:
    """The fields every kind and relation carries: its id (equal to its key), label, description,
    aliases and consumers."""
    if not isinstance(entry, dict):
        return [f"{where}: not an object"]
    problems = [] if entry.get("id") == key else [f"{where}: its id must be {key!r}, got {entry.get('id')!r}"]
    for field in ("label", "description"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            problems.append(f"{where}: no {field}")
    if not isinstance(entry.get("aliases"), list):
        problems.append(f"{where}: aliases must be a list")
    return problems + _consumer_problems(where, entry.get("consumers"))


def _kind_problems(onto: Ontology) -> list[str]:
    audiences = set((onto.data.get("audiences") or {}).keys())
    problems: list[str] = []
    for key, kind in onto.kinds.items():
        where = f"kinds.{key}"
        problems += _named(where, key, kind)
        if not isinstance(kind, dict):
            continue
        seen = kind.get("audiences")
        if not isinstance(seen, list) or not seen or not set(seen) <= audiences:
            problems.append(f"{where}: audiences must be a non-empty list of {sorted(audiences)}")
        problems += _enum_problems(where, kind.get("enums", {}))
    return problems


def _relation_problems(onto: Ontology) -> list[str]:
    problems: list[str] = []
    for key, rel in onto.relations.items():
        where = f"relations.{key}"
        problems += _named(where, key, rel)
        if not isinstance(rel, dict):
            continue
        for end in ("from", "to"):
            kinds = rel.get(end)
            if not isinstance(kinds, list) or not kinds or not set(kinds) <= set(onto.kinds):
                problems.append(f"{where}.{end}: must list declared kinds, got {kinds!r}")
        if rel.get("upstream") not in ("to", "from"):
            problems.append(f"{where}.upstream: must be 'to' or 'from'")
        origins = rel.get("origins")
        if not isinstance(origins, list) or not origins or not set(origins) <= set(ORIGINS):
            problems.append(f"{where}.origins: must list origins of {ORIGINS}")
        if not isinstance(rel.get("carried_by"), str) or not rel["carried_by"].strip():
            problems.append(f"{where}: carried_by must say which records carry the link")
        problems += _enum_problems(where + ".qualifiers", rel.get("qualifiers", {}))
    return problems


def _refs_problems(onto: Ontology) -> list[str]:
    problems: list[str] = []
    for key, entry in onto.refs.items():
        if not isinstance(entry, dict) or not (("relation" in entry) ^ ("attribute" in entry)):
            problems.append(f"refs.{key}: must map to one relation or be declared one attribute")
        elif "relation" in entry and entry["relation"] not in onto.relations:
            problems.append(f"refs.{key}: {entry['relation']!r} is not a declared relation")
    return problems


def _ledger_problems(onto: Ontology) -> list[str]:
    problems: list[str] = []
    for event, fields in onto.ledger.items():
        if not isinstance(fields, dict):
            problems.append(f"ledger.{event}: must map fields to kinds")
            continue
        for field, kind in fields.items():
            if kind is not None and kind not in onto.kinds:
                problems.append(f"ledger.{event}.{field}: {kind!r} is not a declared kind")
    return problems


def validate(onto: Ontology) -> list[str]:
    """Every problem with the ontology, in plain words; empty when it holds."""
    problems = [] if onto.data.get("schema") == SCHEMA else [f"schema must be {SCHEMA}"]
    if not _SEMVER.match(onto.version):
        problems.append(f"version must be semver (1.2.3), got {onto.version!r}")
    if tuple(onto.data.get("outcomes") or ()) != OUTCOMES:
        problems.append(f"outcomes must be {list(OUTCOMES)}")
    if set(onto.data.get("origins") or {}) != set(ORIGINS):
        problems.append(f"origins must declare {list(ORIGINS)}")
    if not onto.kinds or not onto.relations:
        problems.append("the ontology declares no kinds or no relations")
    return (problems + _kind_problems(onto) + _relation_problems(onto) + _refs_problems(onto)
            + _ledger_problems(onto))
