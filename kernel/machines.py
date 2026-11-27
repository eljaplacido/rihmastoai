"""The machines a person works across (FR-XAG1): where their agents and working copies are, and how each is reached.

The owner (2026-11-27), relaying setup steps, a public key and error output between agents on two computers by
copy-paste: "this back and forth that I'm now doing and copy pasting from a place to another will be helped by
Rihmasto". A machine is the other end of that back-and-forth. Each has:

- a ``name`` (``laptop``, ``build-server``): lower-case letters, digits, dots and hyphens;
- how it is ``reach``ed: ``ssh`` (an alias or ``user@host`` this machine's ssh knows, ``address``), ``https`` (an
  address in front of a cockpit or an agent, ``address``), or ``hand`` (nothing connects: asks go by copy and paste);
- its ``os`` (``windows``, ``linux``, ``macos`` or ``unknown``), so a fix is said for that system;
- the ``agents`` that run there (``claude-code``, ``codex``), which asks name.

The list is platform-wide (one per Rihmasto home), kept with Rihmasto's own records (``_factory/machines.json``)
and changed by a named person: the developer or IT (IT alone once a team shares the home). Each change is recorded
in Rihmasto's own ledger with the machine's name and what changed, never an address. Nothing here connects
anywhere: kernel/reach.py tests a machine when a person asks it to.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import teams
from kernel.canon import DecisionRefused
from kernel.learn import factory_project
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, read_json, updating_json

FILE = "machines.json"
REACH = ("ssh", "https", "hand")
SYSTEMS = ("windows", "linux", "macos", "unknown")
SOLO_EDITORS = ("developer", "it")          # alone, the developer may keep the list; in a team, IT keeps it
TEAM_EDITORS = ("it",)
MAX_MACHINES = 50
MAX_AGENTS = 12
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,40}\Z")
SSH_ADDRESS = re.compile(r"(?:[A-Za-z0-9._\\-]{1,64}@)?[A-Za-z0-9][A-Za-z0-9._-]{0,120}\Z")
HTTPS_ADDRESS = re.compile(r"https://[A-Za-z0-9.-]{1,190}(?::\d{1,5})?(?:/[A-Za-z0-9._~/-]{0,200})?\Z")
NOTE_LIMIT = 300
ADDED, CHANGED, REMOVED = "machine_added", "machine_changed", "machine_removed"


class MachineRefused(ValueError):
    """A machine the list does not take, with the reason."""


def _path(factory: Factory) -> Any:
    return factory_project(factory).path(FILE)


def listed(factory: Factory) -> list[dict[str, Any]]:
    """Every machine, by name."""
    return sorted(read_json(_path(factory), {"machines": []}).get("machines") or [], key=lambda m: m["name"])


def get(factory: Factory, name: str) -> dict[str, Any] | None:
    key = str(name or "").strip().lower()
    return next((m for m in listed(factory) if m["name"] == key), None)


def editors(factory: Factory) -> tuple[str, ...]:
    return SOLO_EDITORS if teams.is_solo(factory) else TEAM_EDITORS


def describe(factory: Factory) -> dict[str, Any]:
    """The list as the cockpit shows it, with its scope and who may change it."""
    rows = listed(factory)
    return {"machines": rows, "scope": "platform", "editors": list(editors(factory)), "reach": list(REACH),
            "systems": list(SYSTEMS),
            "said": (f"{len(rows)} machine(s): " + ", ".join(m["name"] for m in rows)) if rows else
            "No machines yet: add the computers where your agents and working copies are, so Rihmasto can test "
            "them and carry asks to their agents."}


def _check_who(factory: Factory, person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: the machine list is changed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"{persona!r} is not a persona")
    allowed = editors(factory)
    if persona not in allowed:
        raise DecisionRefused(f"the machine list is kept by {' or '.join(allowed)}; {persona} cannot change it")


def _agents(value: Any) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[,\s]+", str(value or ""))
    out = []
    for a in (str(x).strip().lower() for x in items):
        if not a:
            continue
        if not NAME.match(a):
            raise MachineRefused(f"{a!r} is not an agent's name (lower-case letters, digits, dots and hyphens)")
        if a not in out:
            out.append(a)
    if len(out) > MAX_AGENTS:
        raise MachineRefused(f"at most {MAX_AGENTS} agents on one machine")
    return out


def _address(reach: str, address: Any) -> str | None:
    text = str(address or "").strip()
    if reach == "hand":
        return None
    if reach == "ssh" and not SSH_ADDRESS.match(text):
        raise MachineRefused("an ssh machine is reached by an alias this computer's ssh knows, or user@host "
                             "(laptop, me@build-server)")
    if reach == "https" and not HTTPS_ADDRESS.match(text):
        raise MachineRefused("an https machine is reached at an https:// address with a host")
    return text


def checked(fields: dict[str, Any], before: dict[str, Any] | None = None) -> dict[str, Any]:
    """A machine's fields as kept, the ones not given taken from ``before``; or why not."""
    base = dict(before or {})
    name = str(fields.get("name", base.get("name")) or "").strip().lower()
    if not NAME.match(name):
        raise MachineRefused("a machine's name is lower-case letters, digits, dots and hyphens (laptop, build-server)")
    reach = str(fields.get("reach", base.get("reach")) or "hand").strip().lower()
    if reach not in REACH:
        raise MachineRefused(f"a machine is reached by one of {', '.join(REACH)}")
    system = str(fields.get("os", base.get("os")) or "unknown").strip().lower()
    if system not in SYSTEMS:
        raise MachineRefused(f"a machine's system is one of {', '.join(SYSTEMS)}")
    note = str(fields.get("note", base.get("note")) or "").strip()
    if len(note) > NOTE_LIMIT:
        raise MachineRefused(f"a note is at most {NOTE_LIMIT} characters")
    address = fields.get("address", base.get("address"))
    out = {"name": name, "reach": reach, "address": _address(reach, address), "os": system,
           "agents": _agents(fields.get("agents", base.get("agents") or [])), "note": note}
    return {k: v for k, v in out.items() if v not in (None, "")} | {"agents": out["agents"]}


def add(factory: Factory, fields: dict[str, Any], *, person: str, persona: str) -> dict[str, Any]:
    """Add a machine, or change the one of that name (only the fields given change)."""
    _check_who(factory, person, persona)
    name = str(fields.get("name") or "").strip().lower()
    with updating_json(_path(factory), {"machines": []}) as doc:
        rows = doc.setdefault("machines", [])
        before = next((m for m in rows if m["name"] == name), None)
        row = checked(fields, before)
        if before is None and len(rows) >= MAX_MACHINES:
            raise MachineRefused(f"at most {MAX_MACHINES} machines")
        row["updated"] = factory.clock.stamp()
        row["by"] = person
        if before is not None:
            rows[rows.index(before)] = row
        else:
            rows.append(row)
    changed = sorted(k for k in ("reach", "address", "os", "agents", "note") if (before or {}).get(k) != row.get(k))
    factory_project(factory).log(CHANGED if before else ADDED,
                                 {"machine": row["name"], "reach": row["reach"], "changed": changed,
                                  "person": person, "persona": persona})
    return {"machine": row, "added": before is None,
            "said": f"Machine {row['name']} {'changed' if before else 'added'} ({row['reach']})."}


def remove(factory: Factory, name: str, *, person: str, persona: str) -> dict[str, Any]:
    _check_who(factory, person, persona)
    key = str(name or "").strip().lower()
    with updating_json(_path(factory), {"machines": []}) as doc:
        rows = doc.setdefault("machines", [])
        row = next((m for m in rows if m["name"] == key), None)
        if row is None:
            raise MachineRefused(f"there is no machine {key!r}")
        rows.remove(row)
    factory_project(factory).log(REMOVED, {"machine": key, "person": person, "persona": persona})
    return {"removed": key, "said": f"Machine {key} removed; asks already sent to it keep their record."}


def agent_on(factory: Factory, agent: str) -> list[str]:
    """The machines an agent runs on, by name."""
    a = str(agent or "").strip().lower()
    return [m["name"] for m in listed(factory) if a in (m.get("agents") or [])]
