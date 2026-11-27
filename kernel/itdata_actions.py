"""What IT does on a connection (FR-ITD1): check it now, turn it off, and a reminder to rotate a credential.

Each is signed by a named person with a persona that may do it, and recorded in the ledger (the project's, or Rihma's
own for the platform's connections):

- **check now** (``check``; it, operations or developer): for each connection, what stands between it and working
  (a variable not set, an approval not given, a connector not enabled) and, where it has an address, whether
  something answers on its port and how fast. Only a TCP connection is opened: no data, no credential, no
  request is sent. Each result is kept in ``<home>/itdata/health.json`` with the failures in a row, and the round
  is recorded as ``itdata_checked``;
- **turn off** (``disable``; IT): a relay subscription ends, a webhook source stops, a connector is disabled, each
  through its own kernel rule (kernel/relay.py, kernel/hooks.py, kernel/connectors.py), recorded as
  ``itdata_disabled`` with the reason. Anything else says where it is changed instead (``NotHere``);
- **rotation reminder** (``remind_rotation``; IT or operations): the date by which a credential named here is to be
  rotated, kept in ``<home>/itdata/rotation.json`` and recorded as ``credential_rotation_reminder``. The value is
  never read: the reminder is about the name.
"""

from __future__ import annotations

import datetime as dt
import socket
import time
from typing import Any

from kernel import itdata as it
from kernel import itdata_project as ip
from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import updating_json

CHECKERS = ("it", "operations", "developer")
DISABLERS = ("it",)
REMINDERS = ("it", "operations")
REACH_TIMEOUT = 2.0
MAX_DAYS = 730
connect = socket.create_connection           # the one way out: a TCP connection to an address (tests replace it)


class NotHere(ValueError):
    """The connection is not turned off here: the message says where it is changed."""


def _signed(person: str, persona: str, allowed: tuple[str, ...], what: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"refused: {person!r} is not a person; {what} is signed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"refused: persona must be one of {', '.join(PERSONAS)}")
    if persona not in allowed:
        raise DecisionRefused(f"refused: {what} is for the {' or '.join(allowed)} persona, not {persona}; "
                              "switch persona in the person chip")


def _record(factory: Any, project: Any, kind: str, payload: dict[str, Any]) -> None:
    from kernel.learn import factory_project

    (project if project is not None else factory_project(factory)).log(kind, payload)


def _view(factory: Any, project: Any) -> dict[str, Any]:
    return ip.project_view(project) if project is not None else ip.platform_view(factory, stores=False)


def reach(host: str, port: int, timeout: float = REACH_TIMEOUT) -> dict[str, Any]:
    """Whether something answers on ``host:port``, and how long the connection took. Nothing is sent."""
    start = time.monotonic()
    try:
        with connect((host, int(port)), timeout=timeout):
            pass
    except OSError as exc:
        return {"ok": False, "latency_ms": None,
                "why": f"nothing answers at {host}:{port} ({type(exc).__name__}): check the address and the network, "
                       "then check again"}
    return {"ok": True, "latency_ms": round((time.monotonic() - start) * 1000), "why": f"{host}:{port} answers"}


def check_one(x: dict[str, Any]) -> dict[str, Any]:
    """One connection's check: what is missing first; then, where it has an address, whether it answers."""
    if x.get("connector_state") == "off":
        return {"ok": None, "latency_ms": None, "why": "it is off: nothing to check"}
    if x["missing"]:
        return {"ok": False, "latency_ms": None, "why": x["missing"][0]}
    if x.get("probe"):
        return reach(x["probe"]["host"], x["probe"]["port"])
    if x["kind"] == "road":
        return {"ok": None, "latency_ms": None, "why": "where it runs is probed from Destinations: Check now there"}
    return {"ok": True, "latency_ms": None, "why": "its settings are in place"}


def _keep(kept: dict[str, Any], x: dict[str, Any], r: dict[str, Any], at: str, person: str) -> dict[str, Any]:
    """One result, kept under the item's own key (a project's road:demo by project, kernel/itdata.health_key). A road
    whose check measured nothing is not kept: what Destinations' probe said stays its health."""
    key = it.health_key(x)
    before = (kept.get(key) or {}).get("failures") or 0
    row = {**r, "at": at, "by": "check", "person": person, "failures": before + 1 if r["ok"] is False else 0}
    if r["ok"] is None and x["kind"] == "road":
        return row
    kept[key] = row
    return row


def check(factory: Any, *, person: str, persona: str, project: Any = None, item: str | None = None) -> dict[str, Any]:
    """Check every connection here (or the one named), keep each result, and record the round."""
    _signed(person, persona, CHECKERS, "a check")
    items = _view(factory, project)["items"]
    if item:
        items = [x for x in items if x["id"] == item]
        if not items:
            raise KeyError(f"no connection {item!r} here: the view lists each one's id")
    at, results = factory.clock.stamp(), []
    demo = it.demo_home(factory)
    with updating_json(it.state_path(factory, "health.json"), {}) as kept:
        for x in items:
            r = ({"ok": None, "latency_ms": None, "why": "a demo home contacts no outside host: not checked"}
                 if demo and x.get("probe") and x.get("locality") in it.LEAVES else check_one(x))
            results.append({"id": x["id"], "label": x["label"], **_keep(kept, x, r, at, person)})
    failing = [r["label"] for r in results if r["ok"] is False]
    _record(factory, project, "itdata_checked", {"items": [r["id"] for r in results], "failing": failing,
                                                 "person": person, "persona": persona,
                                                 "project": project.pid if project is not None else None})
    line = f"Checked {len(results)}: " + (f"{len(failing)} failing ({', '.join(failing[:3])})." if failing else
                                          "nothing is failing.")
    return {"at": at, "results": results, "failing": failing, "summary": line}


def _turn_off(factory: Any, how: str, key: str, person: str, persona: str) -> None:
    from kernel import connectors, hooks, relay

    if how == "relay":
        relay.unsubscribe(factory, key, person=person, persona=persona)
    elif how == "hook":
        hooks.remove_source(factory, key, person=person, persona=persona)
    elif how == "connector":
        connectors.disable(factory, key, person=person, persona=persona)
    else:
        raise NotHere(f"{how} is not turned off here")


def disable(factory: Any, item_id: str, *, person: str, persona: str, reason: str = "",
            project: Any = None) -> dict[str, Any]:
    """IT turns a connection off through its own kernel rule, signed and recorded with the reason."""
    _signed(person, persona, DISABLERS, "turning a connection off")
    x = ip.find(factory, item_id, project)
    rule = x.get("disable") or {}
    if not rule.get("how"):
        raise NotHere(f"{x['label']} is not turned off here: {rule.get('why_not') or 'it has no switch of its own'}")
    _turn_off(factory, rule["how"], item_id.split(":", 1)[1], person, persona)
    wide = rule.get("wide")
    _record(factory, project, "itdata_disabled", {"id": item_id, "label": x["label"], "reason": reason,
                                                  "person": person, "persona": persona, "wide": bool(wide),
                                                  "project": project.pid if project is not None else None})
    every = not x["projects"]
    return {"disabled": item_id, "label": x["label"], "reason": reason, "wide": wide,
            "note": "it carried every project's events" if every and x["kind"] == "relay" else None}


def signs_on(factory: Any, item_id: str, project: Any) -> str | None:
    """The project a Turn off is signed on: this project for one of its own; the platform (None) for a connection
    that serves other projects too, so a person granted IT on one project cannot stop every project's channel."""
    if project is None:
        return None
    try:
        x = ip.find(factory, item_id, project)
    except KeyError:
        return project.pid
    return project.pid if x["scope"] == "project" else None


def remind_rotation(factory: Any, name: str, *, person: str, persona: str, days: int = 90,
                    project: Any = None) -> dict[str, Any]:
    """The date by which a credential named here is to be rotated, signed and recorded; never its value."""
    _signed(person, persona, REMINDERS, "a rotation reminder")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days is a whole number from 1 to {MAX_DAYS}")
    names = [c["name"] for c in _view(factory, project)["credentials"]]
    if name not in names:
        raise KeyError(f"no credential named {name!r} here; the names are: {', '.join(names) or 'none'}")
    due = (factory.clock.now().date() + dt.timedelta(days=days)).isoformat()
    entry = {"due": due, "days": days, "by": person, "persona": persona, "at": factory.clock.stamp()}
    with updating_json(it.state_path(factory, "rotation.json"), {}) as kept:
        kept[name] = entry
    _record(factory, project, "credential_rotation_reminder", {"name": name, "due": due, "person": person,
                                                               "persona": persona,
                                                               "project": project.pid if project is not None else None})
    return {"credential": name, **entry}
