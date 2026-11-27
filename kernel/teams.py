"""Teams, each tied to projects (D-0027, FR-TM1): the one unit above a project.

The owner (2026-11-27), after a long discussion of the platform's own words and of scope: "Maybe at this point we
just talk about teams and them being tied to projects." So:

- a **team** has a name and members (people, as kernel/people.py names them); a project belongs to exactly one
  team, a team has many projects;
- a person working alone is a **team of one made automatically** (``team-solo``), named after the person; there is
  nothing for them to set up or see. When a second person is added (the solo to team switch, kernel/team.py) the same
  team simply has more members: no migration, nothing locked in;
- a project's team is ``team`` in its ``project.json``; a project with none (every project made before teams, and
  every new one) is in the automatic team, and nothing is rewritten for it;
- a team record may carry an empty ``unit`` field, so that business units added later migrate nothing; it is neither
  built nor shown. There is no enterprise or business-unit level here.

Teams are kept in the factory home, ``home/_teams/<id>.json`` (``rihmasto.team_unit/1``). Every change is signed by a
person, recorded in the factory's ledger with what it was before, and undone with ``undo``, which puts the earlier
record back exactly (the change that was undone stays in the ledger). Only IT defines teams; IT or a project's
owner moves a project (``MOVERS``); working alone the one person holds every role, so a change applies at once, with
a preview first and an undo after. The words a team or a project gives to Rihmasto's own terms are in kernel/vocab.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kernel import teams_guard as guard
from kernel.canon import DecisionRefused
from kernel.learn import FACTORY_PID, factory_project
from kernel.people import is_person
from kernel.store import Factory, Project, read_json, write_json

SCHEMA = "rihmasto.team_unit/1"
AUTO_ID = "team-solo"
ADMINS = ("it",)                                        # who defines a team and who is in it
MOVERS = ("it", "business_owner", "product_owner")      # who moves a project to another team
SET_KIND, MOVED_KIND, UNDONE_KIND = "team_set", "project_team_set", "team_undone"
MAX_MEMBERS, MAX_NAME, MAX_TEAMS = 200, 80, 100
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,60}")
Doc = dict[str, Any]


class NoSuchTeam(ValueError):
    """A team id nobody made."""


# -- reading -------------------------------------------------------------------------------------------------

def folder(factory: Factory) -> Path:
    return factory.home / "_teams"


def _file(factory: Factory, tid: str) -> Path:
    if not _ID.fullmatch(str(tid)):
        raise NoSuchTeam(f"no team {str(tid)[:60]!r}")
    return folder(factory) / f"{tid}.json"


def _people(factory: Factory) -> list[str]:
    """The people the home knows: the solo person, or the active users of team mode."""
    from kernel import team as kteam

    try:
        doc = kteam.read(factory)
    except kteam.TeamFileError:
        return []
    named = [(doc.get("solo") or {}).get("name")] if isinstance(doc.get("solo"), dict) else []
    named += [u.get("name") for u in doc.get("users") or [] if isinstance(u, dict) and u.get("active", True)]
    return [str(n) for n in named if is_person(n)]


def auto_name(factory: Factory) -> str:
    """The automatic team's name until a person renames it: working alone, the person's own; with a team, "Our team"
    (it is everyone, not the one who first used the home)."""
    from kernel import team as kteam

    return "Our team" if kteam.mode(factory) == kteam.TEAM else kteam.solo_name(factory) or "My team"


def _blank_auto(factory: Factory) -> Doc:
    return {"schema": SCHEMA, "id": AUTO_ID, "name": auto_name(factory), "members": [], "unit": "", "auto": True}


def read(factory: Factory, tid: str) -> Doc:
    """One team's record; the automatic team before anyone changed it is the one made from the person's name."""
    doc = read_json(_file(factory, tid), None)
    if isinstance(doc, dict) and doc.get("schema") == SCHEMA:
        return {**doc, "name": auto_name(factory)} if doc.get("auto") and not doc.get("renamed") else doc
    if tid == AUTO_ID:
        return _blank_auto(factory)
    raise NoSuchTeam(f"no team {tid!r}")


def members(factory: Factory, doc: Doc) -> list[str]:
    """The team's people. The automatic team is everyone the home knows, so a second person added to a solo home
    is simply a member of the same team."""
    named = [str(m) for m in doc.get("members") or []]
    if doc.get("auto"):
        named = _people(factory) + named
    return list(dict.fromkeys(named))


def all_teams(factory: Factory) -> list[Doc]:
    out = [read(factory, AUTO_ID)]
    if folder(factory).is_dir():
        for p in sorted(folder(factory).glob("*.json")):
            doc = read_json(p, None) if p.stem != AUTO_ID else None      # a vocabulary file has another schema
            if isinstance(doc, dict) and doc.get("schema") == SCHEMA:
                out.append(doc)
    return out


def exists(factory: Factory, tid: str) -> bool:
    try:
        read(factory, tid)
    except NoSuchTeam:
        return False
    return True


def team_of(factory: Factory, project: Project) -> str:
    """The id of the project's team: its own ``team``, or the automatic team when it has none (or an unknown one)."""
    try:
        tid = project.meta.get("team")
    except ValueError:
        return AUTO_ID
    return str(tid) if tid and exists(factory, str(tid)) else AUTO_ID


def projects_of(factory: Factory, tid: str) -> list[Project]:
    return [p for p in factory.projects() if p.pid != FACTORY_PID and team_of(factory, p) == tid]


def is_solo(factory: Factory) -> bool:
    """One team, with at most one person in it: nothing about teams is shown."""
    return len(all_teams(factory)) == 1 and len(members(factory, read(factory, AUTO_ID))) <= 1


def _row(factory: Factory, doc: Doc) -> Doc:
    mine = projects_of(factory, str(doc["id"]))
    return {"id": doc["id"], "name": doc["name"], "members": members(factory, doc), "auto": bool(doc.get("auto")),
            "projects": [{"id": p.pid, "title": p.meta.get("title") or p.pid} for p in mine],
            "updated": doc.get("updated")}      # the empty "unit" is never shown


def describe(factory: Factory) -> Doc:
    rows = [_row(factory, d) for d in all_teams(factory)]
    return {"teams": rows, "solo": is_solo(factory), "admins": list(ADMINS), "movers": list(MOVERS),
            "history": history(factory)}


def of_project(factory: Factory, project: Project) -> Doc:
    """The project's team, with the other teams it could move to."""
    tid = team_of(factory, project)
    teams = all_teams(factory)
    return {"project": project.pid, "team": _row(factory, read(factory, tid)), "solo": is_solo(factory),
            "choices": [{"id": d["id"], "name": d["name"]} for d in teams], "movers": list(MOVERS)}


def find(factory: Factory, words: str) -> Doc | None:
    """A team named in words (its id or name, whole, or the one that contains the words), else None."""
    low = " ".join(str(words).lower().split())
    teams = all_teams(factory)
    for d in teams:
        if low in (str(d["id"]).lower(), str(d["name"]).lower()):
            return d
    hits = [d for d in teams if low and (low in str(d["name"]).lower() or str(d["name"]).lower() in low)]
    return hits[0] if len(hits) == 1 else None


# -- the checks every change makes ---------------------------------------------------------------------------

def check_who(person: str, persona: str, allowed: tuple[str, ...], what: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: {what} is signed by a named person")
    guard.require_persona(persona, allowed, what)


def _name(factory: Factory, value: Any, own: str | None = None) -> str:
    return guard.clean_name(factory, value, own)


def _people_named(value: Any) -> list[str]:
    names = guard.names_of(value)
    for n in names:
        if not is_person(n) or len(n) > 200:
            raise ValueError(f"{n!r} is not a person's name")
    return list(dict.fromkeys(names))


def _free_id(factory: Factory, name: str) -> str:
    return guard.new_id(factory, name)


# -- the preview, and the changes ----------------------------------------------------------------------------

def _after(factory: Factory, before: Doc | None, *, tid: str, name: Any, add: Any, remove: Any) -> Doc:
    doc: Doc = dict(before) if before else {"schema": SCHEMA, "id": tid, "name": "", "members": [], "unit": "",
                                            "created": factory.clock.stamp()}
    doc["name"] = _name(factory, name, tid) if name is not None else doc["name"] or _name(factory, None, tid)
    if name is not None and doc.get("auto") and doc["name"] != (before or {}).get("name"):
        doc["renamed"] = True                     # a person's own name for the automatic team sticks
    held = [m for m in doc.get("members") or [] if m not in set(_people_named(remove))]
    doc["members"] = list(dict.fromkeys(held + _people_named(add)))[:MAX_MEMBERS]
    doc["updated"] = factory.clock.stamp()
    return doc


def _lines(factory: Factory, before: Doc | None, after: Doc) -> list[str]:
    old = members(factory, before) if before else []
    new = members(factory, after)
    out = [f"A team called {after['name']} is made." if before is None else
           (f"{before['name']} is called {after['name']}." if before["name"] != after["name"] else "")]
    out += [f"{m} joins {after['name']}." for m in new if m not in old]
    out += [f"{m} leaves {after['name']}." for m in old if m not in new]
    return [x for x in out if x] or ["Nothing changes."]


def preview(factory: Factory, *, team: str | None = None, name: Any = None, add: Any = None, remove: Any = None,
            project: str | None = None, to: str | None = None) -> Doc:
    """What a team change or a project's move would do. It records nothing."""
    if project is not None or to is not None:
        return _move_preview(factory, project, to)
    before = read(factory, team) if team else None
    after = _after(factory, before, tid=team or "new", name=name, add=add, remove=remove)
    return {"lines": _lines(factory, before, after), "changes": [{"team": team, "from": before, "to": after}],
            "projects": [p.pid for p in projects_of(factory, team)] if team else []}


def _move_preview(factory: Factory, pid: str | None, to: str | None) -> Doc:
    project = factory.project(str(pid))
    now, there = read(factory, team_of(factory, project)), read(factory, str(to))
    title = project.meta.get("title") or project.pid
    if now["id"] == there["id"]:
        return {"lines": [f"{title} is already in {now['name']}."], "changes": [], "projects": [project.pid]}
    from kernel import teams_move

    said, reach = teams_move.lines(factory, project, there["id"], there["name"])
    return {"lines": [f"{title} moves from {now['name']} to {there['name']}.",
                      "Its own words (its vocabulary override) stay with it; the team's words change.", *said],
            "changes": [{"project": project.pid, "from": now["id"], "to": there["id"]}], "projects": [project.pid],
            **reach}


def _journal(factory: Factory, kind: str, key: str, **payload: Any) -> None:
    factory_project(factory).log(kind, {"key": key, **payload})


def create(factory: Factory, name: Any, *, members_: Any = None, person: str, persona: str, reason: str = "") -> Doc:
    check_who(person, persona, ADMINS, "define a team")
    if len(all_teams(factory)) >= MAX_TEAMS:
        raise ValueError(f"a home holds at most {MAX_TEAMS} teams")
    tid = _free_id(factory, _name(factory, name))
    after = _after(factory, None, tid=tid, name=name, add=members_, remove=None)
    write_json(_file(factory, tid), after)
    _journal(factory, SET_KIND, f"team:{tid}", team=tid, before=None, after=after, by=person, persona=persona,
             reason=str(reason or "")[:300])
    return {"team": _row(factory, after), "lines": _lines(factory, None, after)}


def update(factory: Factory, tid: str, *, name: Any = None, add: Any = None, remove: Any = None, person: str,
           persona: str, reason: str = "") -> Doc:
    check_who(person, persona, ADMINS, "change a team")
    before = read(factory, tid)
    guard.check_remove(factory, bool(before.get("auto")), _people_named(remove))
    stored = read_json(_file(factory, tid), None)       # None for the automatic team before anyone changed it
    after = _after(factory, before, tid=tid, name=name, add=add, remove=remove)
    if after["name"] == before["name"] and after["members"] == (before.get("members") or []):
        return {"team": _row(factory, before), "lines": ["Nothing changes."]}
    write_json(_file(factory, tid), after)
    _journal(factory, SET_KIND, f"team:{tid}", team=tid, before=stored, after=after, by=person, persona=persona,
             reason=str(reason or "")[:300])
    return {"team": _row(factory, after), "lines": _lines(factory, before, after)}


def move_project(factory: Factory, project: Project, to: str, *, person: str, persona: str, reason: str = "") -> Doc:
    check_who(person, persona, MOVERS, "move a project to another team")
    there = read(factory, str(to))
    before = team_of(factory, project)
    if before == there["id"]:
        return {"project": project.pid, "team": _row(factory, there), "lines": ["It is already there."]}
    if there["id"] == AUTO_ID and not folder(factory).joinpath(f"{AUTO_ID}.json").exists():
        write_json(_file(factory, AUTO_ID), {**there, "created": factory.clock.stamp()})
    project.update_meta(team=there["id"])
    record = {"project": project.pid, "before": before, "after": there["id"], "by": person, "persona": persona,
              "reason": str(reason or "")[:300]}
    project.log(MOVED_KIND, record)
    _journal(factory, MOVED_KIND, f"project:{project.pid}", **record)
    return {"project": project.pid, "team": _row(factory, there),
            "lines": [f"{project.meta.get('title') or project.pid} is now in {there['name']}."]}


# -- undo and the record -------------------------------------------------------------------------------------

def _stack(factory: Factory, key: str) -> list[dict[str, Any]]:
    """The changes to ``key`` not yet undone, oldest first: an undo takes the newest off."""
    stack: list[dict[str, Any]] = []
    for r in factory_project(factory).ledger().of_kind(SET_KIND, MOVED_KIND, UNDONE_KIND):
        e = r["event"]
        p = e.get("payload") or {}
        if p.get("key") != key:
            continue
        if e["kind"] == UNDONE_KIND:
            if stack:
                stack.pop()
        else:
            stack.append({**p, "at": e.get("at")})
    return stack


def undo(factory: Factory, *, team: str | None = None, project: Project | None = None, person: str,
         persona: str) -> Doc:
    """Put back what the last change of the team (or of the project's team) replaced, exactly."""
    key = f"team:{team}" if team else f"project:{project.pid}" if project is not None else ""
    if not key:
        raise ValueError("say which to undo: a team or a project's team")
    check_who(person, persona, ADMINS if team else MOVERS, "undo a team change")
    stack = _stack(factory, key)
    if not stack:
        raise ValueError("there is nothing to undo here: no change was made, or all of them were undone")
    last = stack[-1]
    if team:
        guard.check_undo(factory, team, last)
        if last["before"] is None:
            _file(factory, team).unlink(missing_ok=True)
        else:
            write_json(_file(factory, team), last["before"])
    else:
        assert project is not None
        project.update_meta(team=last["before"])
        project.log(MOVED_KIND, {"project": project.pid, "before": last["after"], "after": last["before"],
                                 "by": person, "persona": persona, "reason": "undo"})
    _journal(factory, UNDONE_KIND, key, by=person, persona=persona, restored=last.get("before"))
    return {"undone": key, "restored": last.get("before"), "lines": ["The earlier reading is back; the change "
                                                                    "stays in the record."]}


def history(factory: Factory, limit: int = 20) -> list[dict[str, Any]]:
    rows = [{"at": r["event"].get("at"), "kind": r["event"]["kind"], **(r["event"].get("payload") or {})}
            for r in factory_project(factory).ledger().of_kind(SET_KIND, MOVED_KIND, UNDONE_KIND)]
    return rows[-limit:][::-1]
