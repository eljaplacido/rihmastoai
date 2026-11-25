"""Automations (FR-AUT1): a trigger, an optional guard, an action, a scope and limits, owned by a person.

The owner (2026-11-24): "we should be able to set and run automations and hooks per project, even across
them." An automation is kept in the factory home (``<home>/automations/automations.json``) and changed only
through this module, signed and in the factory's ledger (``automation_set``, ``_paused``, ``_resumed``, ``_removed``):

- **trigger**: a schedule (``every`` 5m to 7d, ``daily`` at HH:MM, ``weekly`` on a day at HH:MM, in UTC), a
  ledger event in the scoped projects (any record kind, the life-cycle transitions of kernel/automations_events.py,
  ``card_waiting``), an inbound webhook, or new commits on an attached or adopted repository (by polling);
- **guard**, optional and cheap: a count of events within some hours, the branch, a field of the event, or
  the project's open cards. A guard that does not hold costs one read and records nothing;
- **action**, from an allow-list (``ACTIONS``), each carried out by the kernel's own path with the owner's
  rights and never beyond them (kernel/automations_actions.py). Nothing an automation does decides a card:
  deciding stays with people, or with a person's delegation as before (kernel/delegation.py);
- **scope**: one project, a list, every project with a tag, a profile or a source kind, or the factory;
- **limits**: runs per hour, a circuit breaker after failures in a row (it pauses the automation and says
  why on Home and in What's next), quiet hours, and a dry run that records what it would have done.

Running them is kernel/automations_run.py; the command line kernel/automations_cli.py; the cockpit
cockpit/automation_routes.py. docs/guides/automations.md has the templates and the scheduler lines.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from kernel.automations_events import probe_fields
from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, SIGNER, is_person
from kernel.store import Factory, Project, read_json, updating_json

FILE = "automations.json"
SCHEMA = "rihma.automations/1"
TRIGGERS = ("schedule", "event", "hook", "repo")
SCOPES = ("project", "projects", "tag", "profile", "source", "factory")
GUARDS = ("count", "branch", "field", "open_cards")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ALL = tuple(PERSONAS)
# The allow-list. Each action: what it does, the personas whose rights it may run with, and whether it acts on
# one project at a time (a factory-wide action runs once per firing).
ACTIONS: dict[str, dict[str, Any]] = {
    "advance": {"label": "advance the project", "personas": ("business_owner", "product_owner", "developer",
                                                              "operations", "it"), "per_project": True},
    "gate": {"label": "run the gate on the attached repository",
             "personas": ("developer", "it", "operations", "product_owner"), "per_project": True},
    "rescan": {"label": "re-scan a folder and add what is new as material",
               "personas": ("business_owner", "product_owner", "developer"), "per_project": True},
    "notify": {"label": "send a notification", "personas": ALL, "per_project": False},
    "change": {"label": "open a change proposal", "personas": ALL, "per_project": True},
    "signal": {"label": "log a signal in the delivery square", "personas": ALL, "per_project": False},
    "output": {"label": "rebuild the chosen outputs",
               "personas": ("business_owner", "product_owner", "developer", "it", "compliance"), "per_project": True},
    "command": {"label": "run the project's own tests in a sandbox", "personas": ("developer", "it", "operations"),
                "per_project": True},
    "ask": {"label": "ask a model and post the answer as a comment", "personas": ALL, "per_project": True},
    "probe": {"label": "run the probe check where the release runs", "per_project": True,
              "personas": ("business_owner", "product_owner", "developer", "it", "operations")},
    "watch": {"label": "watch an adopted project: new commits to Review, activity by area (kernel/adopt_watch.py)",
              "personas": ("business_owner", "product_owner", "developer", "it", "operations"), "per_project": True},
}
# What an automation never does, whatever it is called: a person's acts, the go-ahead on a spec and a runner too.
NEVER = ("decide", "approve", "answer", "assume", "accept", "reject", "deploy", "merge", "grant", "trust",
         "delegate", "settle", "go_ahead", "skip", "runner", "decline")
DEFAULT_LIMITS = {"max_per_hour": 12, "breaker": 3, "quiet": None, "dry_run": False}
_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_EVERY = re.compile(r"(\d{1,4})([mhd])\Z")
_HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)\Z")
_QUIET = re.compile(r"(([01]\d|2[0-3]):[0-5]\d)-(([01]\d|2[0-3]):[0-5]\d)\Z")
_TAG = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,99}\Z")
SOURCES = ("attached", "adopted", "idea", "folder", "file")
_ID = re.compile(r"AU-\d{3,6}\Z")
MAX_TEXT = 2000


class AutomationRefused(DecisionRefused):
    """A change to an automation, or a run, that the rules refuse: the reason says which."""


def _dir(factory: Factory) -> Path:
    return factory.home / "automations"


def _blank() -> dict[str, Any]:
    return {"schema": SCHEMA, "automations": []}


def automations(factory: Factory, *, removed: bool = False) -> list[dict[str, Any]]:
    """Every automation, newest last; removed ones only when asked."""
    items = list((read_json(_dir(factory) / FILE, None) or _blank()).get("automations", []))
    return [a for a in items if removed or a.get("state") != "removed"]


def get(factory: Factory, aid: str) -> dict[str, Any]:
    found = next((a for a in automations(factory, removed=True) if a["id"] == aid), None)
    if found is None:
        raise KeyError(f"no automation {aid!r}")
    return found


def _log(factory: Factory, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Record a change or a run of an automation in the factory's ledger."""
    from kernel.learn import factory_project

    return factory_project(factory).log(kind, payload)


# -- the parts, checked -------------------------------------------------------------------------------

def minutes_of(every: str) -> int:
    m = _EVERY.match(str(every))
    if not m:
        raise ValueError("every is a number and m, h or d: 15m, 2h, 1d")
    return int(m.group(1)) * {"m": 1, "h": 60, "d": 1440}[m.group(2)]


def _schedule(t: dict[str, Any]) -> dict[str, Any]:
    given = [k for k in ("every", "daily", "weekly") if t.get(k)]
    if len(given) != 1:
        raise ValueError("a schedule is one of every (15m, 2h, 1d), daily (HH:MM) or weekly (mon HH:MM)")
    key = given[0]
    value = str(t[key]).strip().lower()
    if key == "every" and not 5 <= minutes_of(value) <= 7 * 1440:
        raise ValueError("every is at least 5 minutes and at most 7 days")
    if key == "daily" and not _HHMM.match(value):
        raise ValueError("daily is a time, HH:MM in UTC")
    if key == "weekly" and not (value[:3] in DAYS and value[3:4] == " " and _HHMM.match(value[4:])):
        raise ValueError("weekly is a day and a time: mon 02:00 (UTC)")
    return {"kind": "schedule", key: value}


def _event(factory: Factory, t: dict[str, Any]) -> dict[str, Any]:
    types = t.get("types") or []
    if not isinstance(types, list) or not types or not all(isinstance(x, str) and _KIND.match(x) for x in types):
        raise ValueError("an event trigger names one or more record kinds, such as release_done or gate_failed")
    if any(x.startswith("automation_") for x in types):
        raise ValueError("an automation does not react to automations' own records")
    return {"kind": "event", "types": sorted(set(types))}


def _hook(factory: Factory, t: dict[str, Any]) -> dict[str, Any]:
    from kernel import hooks

    source = str(t.get("source") or "")
    if not any(s["id"] == source and s["state"] == "active" for s in hooks.sources(factory)):
        raise ValueError(f"no active inbound source {source!r}: IT adds one with `rihmasto hooks add`")
    return {"kind": "hook", "source": source}


def _repo(factory: Factory, t: dict[str, Any]) -> dict[str, Any]:
    branch = str(t.get("branch") or "").strip()
    if branch and (branch.startswith("-") or not _BRANCH.match(branch)):
        raise ValueError("a branch is a plain branch name, such as main")
    return {"kind": "repo", "branch": branch or None}


_TRIGGER_CHECKS = {"schedule": lambda factory, t: _schedule(t), "event": _event, "hook": _hook, "repo": _repo}


def _trigger(factory: Factory, t: Any) -> dict[str, Any]:
    if not isinstance(t, dict) or t.get("kind") not in TRIGGERS:
        raise ValueError(f"a trigger is one of {', '.join(TRIGGERS)}")
    return _TRIGGER_CHECKS[t["kind"]](factory, t)


def _number(g: dict[str, Any], key: str, low: int, high: int, default: int | None = None) -> int:
    value = g.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{key} is a whole number from {low} to {high}")
    return value


def _count_guard(g: dict[str, Any]) -> dict[str, Any]:
    event = str(g.get("event") or "")
    if not _KIND.match(event):
        raise ValueError("a count guard names the event it counts, such as gate_failed")
    return {"kind": "count", "event": event, "at_least": _number(g, "at_least", 1, 1000),
            "within_hours": _number(g, "within_hours", 1, 24 * 30, 24)}


def _branch_guard(g: dict[str, Any]) -> dict[str, Any]:
    branch = str(g.get("is") or "").strip()
    if not branch:
        raise ValueError("a branch guard names the branch: is main")
    return {"kind": "branch", "is": branch}


def _field_guard(g: dict[str, Any]) -> dict[str, Any]:
    key, equals = str(g.get("key") or ""), str(g.get("equals") or "")
    if not _KIND.match(key) or not equals:
        raise ValueError("a field guard names a field of the event and the value it equals")
    return {"kind": "field", "key": key, "equals": equals[:100]}


def _cards_guard(g: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "open_cards", "at_least": _number(g, "at_least", 1, 1000),
            "card_kind": str(g.get("card_kind") or "") or None}


_GUARD_CHECKS = {"count": _count_guard, "branch": _branch_guard, "field": _field_guard, "open_cards": _cards_guard}


def _guard(g: Any) -> dict[str, Any] | None:
    if g in (None, {}):
        return None
    if not isinstance(g, dict) or g.get("kind") not in GUARDS:
        raise ValueError(f"a guard is one of {', '.join(GUARDS)}")
    return _GUARD_CHECKS[g["kind"]](g)


def _text(value: Any, what: str, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"the {what} is empty")
    if len(text) > MAX_TEXT:
        raise ValueError(f"the {what} is longer than {MAX_TEXT} characters")
    return text


def _subscription(factory: Factory, sub_id: Any) -> str:
    from kernel import relay

    if not any(s["id"] == sub_id for s in relay.subscriptions(factory)):
        raise ValueError(f"no active relay subscription {sub_id!r}: IT adds one with `rihmasto relay subscribe`")
    return str(sub_id)


def _action(factory: Factory, a: Any) -> dict[str, Any]:
    if not isinstance(a, dict):
        raise ValueError(f"an action is one of {', '.join(ACTIONS)}")
    kind = str(a.get("kind") or "")
    if kind == "go" or any(word in kind for word in NEVER):
        raise AutomationRefused(f"an automation never may {kind}: deciding stays with people, or with a person's "
                                "delegation (kernel/delegation.py)")
    if kind not in ACTIONS:
        raise ValueError(f"an action is one of {', '.join(ACTIONS)}")
    fields = _ACTION_FIELDS.get(kind)
    return {"kind": kind, **(fields(factory, a) if fields else {})}


def _words(factory: Factory, a: dict[str, Any]) -> dict[str, Any]:
    return {"text": _text(a.get("text") or a.get("question"), "question" if a["kind"] == "ask" else "text")}


def _change_fields(factory: Factory, a: dict[str, Any]) -> dict[str, Any]:
    target = {"project": factory.project(str(a["project"])).pid} if a.get("project") else {}
    return {**_words(factory, a), **target}


def _targets(factory: Factory, a: dict[str, Any]) -> dict[str, Any]:
    targets = a.get("targets") or []
    if not isinstance(targets, list) or not all(isinstance(x, str) for x in targets):
        raise ValueError("targets is a list of output targets")
    return {"targets": list(targets)}


_ACTION_FIELDS: dict[str, Any] = {
    "gate": lambda factory, a: {"verifier": a.get("verifier") is not False},
    "rescan": lambda factory, a: {"folder": _text(a.get("folder"), "folder")},
    "notify": lambda factory, a: {"subscription": _subscription(factory, a.get("subscription")),
                                  "text": _text(a.get("text"), "text", required=False)},
    "change": _change_fields, "signal": _words, "ask": _words, "output": _targets, "probe": probe_fields,
    "watch": lambda factory, a: {"what": "areas" if a.get("what") == "areas" else "commits"}}


def _project_scope(factory: Factory, s: dict[str, Any]) -> dict[str, Any]:
    pids = s.get("projects") or ([s["project"]] if s.get("project") else [])
    if not isinstance(pids, list) or not pids or (s["kind"] == "project" and len(pids) != 1):
        raise ValueError("a project scope names one project; a projects scope names one or more")
    return {"kind": s["kind"], "projects": [factory.project(str(p)).pid for p in dict.fromkeys(pids)]}


def _one_of(key: str, allowed: Any, why: str) -> Any:
    def check(factory: Factory, s: dict[str, Any]) -> dict[str, Any]:
        value = s.get(key)
        if not (allowed(value) if callable(allowed) else value in allowed):
            raise ValueError(why)
        return {"kind": key, key: value}
    return check


def _scope(factory: Factory, s: Any) -> dict[str, Any]:
    from kernel.profiles import PROFILES

    if not isinstance(s, dict) or s.get("kind") not in SCOPES:
        raise ValueError(f"a scope is one of {', '.join(SCOPES)}")
    checks = {"project": _project_scope, "projects": _project_scope,
              "tag": _one_of("tag", lambda v: bool(_TAG.match(str(v or ""))),
                             "a tag is lower-case letters, digits, - and _, at most 32"),
              "profile": _one_of("profile", PROFILES, f"a profile is one of {', '.join(PROFILES)}"),
              "source": _one_of("source", SOURCES, f"a source scope is one of {', '.join(SOURCES)}"),
              "factory": lambda factory, s: {"kind": "factory"}}
    out: dict[str, Any] = checks[s["kind"]](factory, s)
    return out


def _limits(given: Any) -> dict[str, Any]:
    lim = dict(DEFAULT_LIMITS, **(given or {})) if isinstance(given, dict) or given is None else None
    if lim is None:
        raise ValueError("limits is an object: max_per_hour, breaker, quiet, dry_run")
    quiet = str(lim.get("quiet") or "").strip() or None
    if quiet and not _QUIET.match(quiet):
        raise ValueError("quiet hours are HH:MM-HH:MM in UTC, such as 22:00-06:00")
    return {"max_per_hour": _number(lim, "max_per_hour", 1, 120), "breaker": _number(lim, "breaker", 1, 20),
            "quiet": quiet, "dry_run": bool(lim.get("dry_run"))}


def _notify(factory: Factory, n: Any) -> dict[str, Any] | None:
    if not n:
        return None
    if not isinstance(n, dict) or n.get("when", "failed") not in ("failed", "always"):
        raise ValueError("notify is {subscription, when: failed or always}")
    return {"subscription": _subscription(factory, n.get("subscription")), "when": n.get("when", "failed")}


# -- the scope and the owner's rights -------------------------------------------------------------------

def in_scope(project: Project, scope: dict[str, Any]) -> bool:
    """Whether a project (never the factory's own canon) is in a scope."""
    meta, kind = project.meta, scope["kind"]
    if project.pid.startswith("_"):
        return False
    if kind in ("project", "projects"):
        return project.pid in scope["projects"]
    if kind == "tag":
        return scope["tag"] in (meta.get("tags") or [])
    if kind == "profile":
        return meta.get("profile") == scope["profile"]
    if kind == "source":
        return meta.get("source_kind") == scope["source"]
    return True


def projects_in(factory: Factory, scope: dict[str, Any]) -> list[Project]:
    return [p for p in factory.projects() if in_scope(p, scope)]


def check_persona(action: str, person: str, persona: str) -> None:
    if not is_person(person):
        raise AutomationRefused(f"{person!r} is not a person: an automation is owned and signed by a named person")
    if persona not in PERSONAS:
        raise AutomationRefused(f"persona must be one of {', '.join(PERSONAS)}")
    may = ACTIONS[action]["personas"]
    if persona not in may:
        raise AutomationRefused(f"a {persona} may not have an automation {ACTIONS[action]['label']} "
                                f"(may: {', '.join(may)})")


def _granted_everywhere(factory: Factory, a: dict[str, Any], person: str, persona: str) -> None:
    """With access enforced, the signer holds the persona on every project the automation acts on (on the
    factory for a factory-wide scope), checked as the identity signing now (kernel.access.require)."""
    from kernel.access import require
    from kernel.learn import factory_project

    targets = [factory.project(p) for p in a["scope"].get("projects", [])] or [factory_project(factory)]
    if a["action"].get("project"):
        targets.append(factory.project(a["action"]["project"]))
    for project in targets:
        require(project, person, persona)


def _owner(person: str, persona: str) -> dict[str, Any]:
    signer = SIGNER.get()
    held = signer is not None and signer.name == person
    return {"person": person, "persona": persona, "identity": signer.id if held and signer else None,
            "groups": list(signer.groups) if held and signer else []}


# -- changes, signed ----------------------------------------------------------------------------------

def _checked(factory: Factory, raw: dict[str, Any]) -> dict[str, Any]:
    name = _text(raw.get("name"), "name")[:120]
    return {"name": name, "trigger": _trigger(factory, raw.get("trigger")), "guard": _guard(raw.get("guard")),
            "action": _action(factory, raw.get("action")), "scope": _scope(factory, raw.get("scope")),
            "limits": _limits(raw.get("limits")), "notify": _notify(factory, raw.get("notify"))}


def _record(a: dict[str, Any]) -> dict[str, Any]:
    return {"id": a["id"], "name": a["name"], "trigger": a["trigger"]["kind"], "action": a["action"]["kind"],
            "scope": a["scope"]["kind"], "projects": a["scope"].get("projects"), "version": a["version"],
            "person": a["owner"]["person"], "persona": a["owner"]["persona"], "dry_run": a["limits"]["dry_run"]}


def add(factory: Factory, raw: dict[str, Any], *, person: str, persona: str) -> dict[str, Any]:
    """A person sets an automation, which runs with their rights from then on."""
    spec = _checked(factory, raw)
    check_persona(spec["action"]["kind"], person, persona)
    _granted_everywhere(factory, spec, person, persona)
    from kernel import automations_run

    with updating_json(_dir(factory) / FILE, _blank()) as data:
        numbers = [int(a["id"].split("-")[1]) for a in data["automations"]]
        a = {"id": f"AU-{max(numbers, default=0) + 1:03d}", **spec, "state": "active", "paused_why": None,
             "owner": _owner(person, persona), "version": 1, "at": factory.clock.stamp()}
        data["automations"].append(a)
    automations_run.armed(factory, a)
    _log(factory, "automation_set", _record(a))
    return a


def _may_change(a: dict[str, Any], person: str, persona: str, verb: str) -> None:
    if not is_person(person):
        raise AutomationRefused(f"{person!r} is not a person: a named person {verb}s an automation")
    if a["state"] == "removed":
        raise AutomationRefused(f"{a['id']} was removed")
    if verb != "pause" and person != a["owner"]["person"] and persona != "it":
        raise AutomationRefused(f"only its owner, {a['owner']['person']}, or IT {verb}s {a['id']}")


def _changing(factory: Factory, aid: str, person: str, persona: str, verb: str) -> Any:
    if not _ID.match(str(aid)):
        raise KeyError(f"no automation {aid!r}")
    _may_change(get(factory, aid), person, persona, verb)
    return updating_json(_dir(factory) / FILE, _blank())


def edit(factory: Factory, aid: str, changes: dict[str, Any], *, person: str, persona: str) -> dict[str, Any]:
    """Change an automation's parts. The person who changes it owns it from then on, so it runs with their
    rights: they sign it again, checked as when it was set."""
    with _changing(factory, aid, person, persona, "change") as data:
        a = next(x for x in data["automations"] if x["id"] == aid)
        merged = {k: copy.deepcopy(changes[k]) if k in changes else a[k]
                  for k in ("name", "trigger", "guard", "action", "scope", "limits", "notify")}
        spec = _checked(factory, merged)
        check_persona(spec["action"]["kind"], person, persona)
        _granted_everywhere(factory, spec, person, persona)
        rearm = spec["trigger"] != a["trigger"] or spec["scope"] != a["scope"]
        a.update(spec, owner=_owner(person, persona), version=int(a["version"]) + 1, at=factory.clock.stamp())
        out = dict(a)
    from kernel import automations_run

    automations_run.armed(factory, out, keep=not rearm)
    _log(factory, "automation_set", _record(out))
    return out


def pause(factory: Factory, aid: str, *, person: str, persona: str, reason: str = "") -> dict[str, Any]:
    """Any named person may pause an automation: stopping is always safe. It runs again when resumed."""
    with _changing(factory, aid, person, persona, "pause") as data:
        a = next(x for x in data["automations"] if x["id"] == aid)
        a.update(state="paused", paused_why=_text(reason, "reason", required=False) or f"paused by {person}",
                 paused_by=person)
        out = dict(a)
    _log(factory, "automation_paused", {"id": aid, "person": person, "persona": persona, "why": out["paused_why"]})
    return out


def breaker_pause(factory: Factory, aid: str, why: str) -> None:
    """The circuit breaker pauses an automation; the record says why, and Home and What's next show it."""
    with updating_json(_dir(factory) / FILE, _blank()) as data:
        a = next((x for x in data["automations"] if x["id"] == aid and x["state"] == "active"), None)
        if a is None:
            return
        a.update(state="paused", paused_why=why, paused_by="breaker")
    _log(factory, "automation_paused", {"id": aid, "by": "the circuit breaker", "why": why})


def resume(factory: Factory, aid: str, *, person: str, persona: str) -> dict[str, Any]:
    with _changing(factory, aid, person, persona, "resume") as data:
        a = next(x for x in data["automations"] if x["id"] == aid)
        a.update(state="active", paused_why=None, paused_by=None)
        out = dict(a)
    from kernel import automations_run

    automations_run.reset_failures(factory, aid)
    _log(factory, "automation_resumed", {"id": aid, "person": person, "persona": persona})
    return out


def remove(factory: Factory, aid: str, *, person: str, persona: str) -> dict[str, Any]:
    with _changing(factory, aid, person, persona, "remove") as data:
        a = next(x for x in data["automations"] if x["id"] == aid)
        a.update(state="removed", removed_by=person, removed_at=factory.clock.stamp())
        out = dict(a)
    _log(factory, "automation_removed", {"id": aid, "person": person, "persona": persona})
    return out


def set_tags(project: Project, tags: list[str], *, person: str, persona: str) -> list[str]:
    """Tag a project, so an automation scoped to a tag reaches it. Signed; recorded in the project's ledger."""
    from kernel.access import require

    if not is_person(person) or persona not in PERSONAS:
        raise AutomationRefused("tags are set by a named person with a persona")
    if project.pid.startswith("_"):
        raise ValueError("the factory's own canon has no tags")
    clean = sorted({str(t).strip().lower() for t in tags if str(t).strip()})
    if len(clean) > 10 or not all(_TAG.match(t) for t in clean):
        raise ValueError("at most 10 tags, each lower-case letters, digits, - and _, at most 32")
    require(project, person, persona)
    before = project.meta.get("tags") or []
    project.update_meta(tags=clean)
    project.log("project_tagged", {"tags": clean, "before": before, "person": person, "persona": persona})
    return clean


import kernel.automations_more  # noqa: E402,F401  (last: run_check and align_scan join the allow-list)
