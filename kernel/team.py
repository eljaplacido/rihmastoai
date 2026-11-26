"""Who works in this factory home: one person (solo) or a team (D-0024 item 4, FR-PPL1).

**Solo** is the default for a new home. One person, named once on the first visit, acts in every persona
they need: a decision is signed with the persona it needs, chosen for them (kernel/solo.py), and the record
says which ("decided by Aino as business owner"). Nothing is set up per persona.

**Team** is turned on in Settings > People and access, or with ``rihmasto access team``. Personas become
people and groups, kept by Rihmasto itself in ``projects/_factory/team/team.json`` (``rihmasto.team/1``):

- the platform's own **users**: a name, personas on every project or on named ones, an e-mail for the
  person's own reference, active or deactivated. A user signs in with a one-use link (an invite, or a
  sign-in link a later visit asks for): Rihmasto keeps only its sha256, and never a password;
- **groups** from an identity provider (Entra ID, AWS, Google or any OIDC provider, kernel/team_access.py),
  each mapped to a persona on a scope;
- **project roles**: on one project, a user or a group holds exactly the personas named there;
- **views per persona**: pages a persona does not see in the cockpit.

Moving from solo to team keeps every record: nothing is rewritten. The solo person becomes the first user,
with every persona on every project and this machine's account (``local:<os user>``) beside the platform
identity, so the command line and the MCP server sign as before. Each change is recorded in the factory's
ledger (``people_changed``) with who made it. Only IT changes who works here (in solo mode the one person is
IT too). An access file IT writes (kernel/access.py, D-0016) governs instead whenever it is there.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.learn import factory_project
from kernel.name_skeleton import skeleton
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, read_json, updating_json

SCHEMA = "rihmasto.team/1"
SOLO, TEAM, IT_FILE = "solo", "team", "it"
MODES = (SOLO, TEAM)
ADMINS = ("it",)                       # who changes who works here
PLATFORM = "rihmasto:"                 # a platform user's identity: rihmasto:U-001
RECORD = "people_changed"              # the factory ledger's record of every change here
LINK_HOURS = {"invite": 24 * 7, "sign_in": 24}
MAX_USERS = 500
# Pages a persona may be kept from (cockpit/static/app.js PAGE_ROUTE): Settings stays for everyone.
PAGES = ("review_all", "home", "square", "catalogue", "projects", "inbox_all", "insights_all", "floor", "jobs",
         "automations_all", "health_all", "agents_all")
Doc = dict[str, Any]


class TeamFileError(ValueError):
    """The team file cannot be read as a ``rihmasto.team/1`` document: every decision is refused."""


# -- reading ------------------------------------------------------------------------------------------------

def folder(factory: Factory) -> Path:
    return factory.projects_dir / "_factory" / "team"


def path(factory: Factory) -> Path:
    return folder(factory) / "team.json"


def blank() -> Doc:
    return {"schema": SCHEMA, "mode": SOLO, "solo": None, "users": [], "links": [], "groups": [], "roles": [],
            "views": {}, "idp": None}


def read(factory: Factory) -> Doc:
    """The team file, or a blank solo one while there is none. TeamFileError when it cannot be read."""
    try:
        doc = read_json(path(factory), None)
    except (OSError, ValueError) as exc:
        raise TeamFileError(f"the team file cannot be read ({type(exc).__name__})") from None
    if doc is None:
        return blank()
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or doc.get("mode") not in MODES:
        raise TeamFileError(f"the team file is not a {SCHEMA} document with a mode of {' or '.join(MODES)}")
    return blank() | doc


def exists(factory: Factory) -> bool:
    return path(factory).is_file()


def mode(factory: Factory) -> str:
    """``it`` while IT's access file is there (it governs), else ``solo`` or ``team``."""
    from kernel.access import access_path

    if access_path(factory).exists():
        return IT_FILE
    try:
        return str(read(factory)["mode"])
    except TeamFileError:
        return TEAM                    # an unreadable team file fails closed, as team mode


def solo_name(factory: Factory) -> str | None:
    try:
        solo = read(factory).get("solo") or {}
    except TeamFileError:
        return None
    return solo.get("name") if isinstance(solo, dict) else None


# -- the checks every change makes ---------------------------------------------------------------------------

def _now(factory: Factory) -> str:
    return factory.clock.stamp()


def _admin(factory: Factory, person: str, persona: str) -> None:
    """Only IT changes who works here; with access in force, the signing identity must hold it."""
    from kernel.access import require

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a change to who works here is signed by a person")
    if persona not in ADMINS:
        raise DecisionRefused(f"a {persona} may not change who works here: IT does (in solo mode you act as IT)")
    if mode(factory) == IT_FILE:
        raise DecisionRefused("IT's access file governs access here (projects/_factory/access/access.json): "
                              "people and groups are set there, not in team mode")
    require(factory_project(factory), person, persona)


def _record(factory: Factory, action: str, person: str, persona: str, **payload: Any) -> None:
    factory_project(factory).log(RECORD, {"action": action, "by": person, "persona": persona, **payload})


def _personas(value: Any) -> list[str]:
    items = [value] if isinstance(value, str) else list(value or [])
    bad = [p for p in items if p not in PERSONAS]
    if bad:
        raise ValueError(f"a persona is one of {', '.join(PERSONAS)}, not {bad[0]!r}")
    return [p for p in PERSONAS if p in items]


def scope_of(factory: Factory, value: Any) -> str | list[str]:
    """``"*"`` (every project) or a list of the factory's project ids."""
    if value in (None, "", "*"):
        return "*"
    items = [value] if isinstance(value, str) else list(value)
    known = {p.pid for p in factory.projects()} | {"_factory"}
    unknown = [p for p in items if p not in known]
    if unknown or not items:
        raise ValueError(f"a scope is \"*\" or a list of this factory's project ids; {unknown[:1] or 'none'} is not")
    return list(dict.fromkeys(items))


def _user(doc: Doc, uid: str) -> Doc:
    found = next((u for u in doc["users"] if u["id"] == uid), None)
    if found is None:
        raise KeyError(f"no user {uid}")
    return found


def is_admin(user: Doc) -> bool:
    return bool(user.get("active")) and "it" in user.get("personas", []) and user.get("scope") == "*"


def _check_name(doc: Doc, name: str, uid: str | None = None) -> str:
    name = str(name or "").strip()
    if not is_person(name) or len(name) > 200:
        raise ValueError("a user's name is a person's name, at most 200 characters")
    if any(skeleton(u["name"]) == skeleton(name) and u["id"] != uid for u in doc["users"]):
        raise ValueError(f"{name!r} is already a user's name (or looks like one): records carry the name")
    return name


# -- solo and team -------------------------------------------------------------------------------------------

def name_solo(factory: Factory, name: str) -> Doc:
    """The one person of a solo home, named once on the first visit (and changed the same way)."""
    name = str(name or "").strip()
    if not is_person(name) or len(name) > 200:
        raise DecisionRefused(f"{name!r} is not a person's name")
    if mode(factory) == IT_FILE:
        raise DecisionRefused("IT's access file governs access here: names come from it")
    with updating_json(path(factory), blank()) as doc:
        if doc.get("mode") == TEAM:
            raise DecisionRefused("this home is in team mode: each person's name is their user's")
        before = (doc.get("solo") or {}).get("name")
        doc["solo"] = {"name": name, "at": _now(factory)}
    if before != name:
        _record(factory, "solo_named", name, "", name=name, before=before)
    return {"mode": SOLO, "name": name}


def _new_user(factory: Factory, doc: Doc, name: str, personas: list[str], scope: str | list[str], *,
              by: str, email: str = "", identity: str | None = None) -> Doc:
    if len(doc["users"]) >= MAX_USERS:
        raise ValueError(f"a team holds at most {MAX_USERS} users")
    uid = f"U-{len(doc['users']) + 1:03d}"
    idents = [PLATFORM + uid] + ([identity] if identity else [])
    taken = {i for u in doc["users"] for i in u.get("identities", [])}
    if any(i in taken for i in idents):
        raise ValueError(f"{identity} is already another user's identity")
    user = {"id": uid, "name": name, "email": str(email or "").strip()[:200], "personas": personas, "scope": scope,
            "identities": idents, "active": True, "created": _now(factory), "by": by}
    doc["users"].append(user)
    return user


def _local_identity() -> str | None:
    from kernel.osuser import os_user

    try:
        return "local:" + os_user()
    except (OSError, KeyError):
        return None


def _owner(factory: Factory, doc: Doc, person: str) -> Doc:
    """The user who turns team mode on: the solo person's user (made now, with every persona everywhere and
    this machine's account), or the person's own when they are one already."""
    mine = next((u for u in doc["users"] if u["name"] == person and u.get("active")), None)
    if mine is not None:
        if not is_admin(mine):
            raise DecisionRefused(f"{person} is a user without IT on every project: an IT user turns team mode on")
        return mine
    local = _local_identity()
    taken = {i for u in doc["users"] for i in u.get("identities", [])}
    user = _new_user(factory, doc, _check_name(doc, person), list(PERSONAS), "*", by=person,
                     identity=local if local and local not in taken else None)
    user["owner"] = True
    return user


def set_mode(factory: Factory, to: str, *, person: str, persona: str, reason: str = "") -> Doc:
    """Solo or team. Every record stays as it is; the solo person becomes the team's first user."""
    if to not in MODES:
        raise ValueError(f"the mode is {' or '.join(MODES)}, not {to!r}")
    _admin(factory, person, persona)
    with updating_json(path(factory), blank()) as doc:
        before = doc.get("mode", SOLO)
        owner = _owner(factory, doc, person) if to == TEAM else None
        if to == SOLO and before == TEAM and not any(is_admin(u) and u["name"] == person for u in doc["users"]):
            raise DecisionRefused(f"{person} is not an IT user of this team: an IT user goes back to solo")
        if to == SOLO and not (doc.get("solo") or {}).get("name"):
            doc["solo"] = {"name": person, "at": _now(factory)}
        doc["mode"] = to
    _record(factory, "mode", person, persona, to=to, before=before, reason=str(reason or "")[:500],
            user=owner["id"] if owner else None, kept="every record")
    return {"mode": to, "before": before, "user": public_user(owner) if owner else None}


# -- users and their links -----------------------------------------------------------------------------------

def add_user(factory: Factory, name: str, *, personas: Any, scope: Any = "*", email: str = "",
             identity: str | None = None, person: str, persona: str) -> Doc:
    """A platform user: a name, personas on a scope, and optionally an identity from the provider."""
    _admin(factory, person, persona)
    chosen, where = _personas(personas), scope_of(factory, scope)
    if identity is not None and not _identity_ok(identity):
        raise ValueError("an identity is local:<os user> or <issuer>#<subject>")
    with updating_json(path(factory), blank()) as doc:
        user = _new_user(factory, doc, _check_name(doc, name), chosen, where, by=person, email=email,
                         identity=identity or None)
    _record(factory, "user_added", person, persona, user=user["id"], name=user["name"], personas=chosen,
            scope=where)
    return public_user(user)


def _identity_ok(identity: str) -> bool:
    from kernel.accessfile import _LOCAL, _is_oidc

    return bool(_LOCAL.match(identity)) or _is_oidc(identity)


def update_user(factory: Factory, uid: str, *, name: str | None = None, personas: Any = None, scope: Any = None,
                person: str, persona: str) -> Doc:
    """A user's profile name, personas or scope. The last IT user keeps IT on every project."""
    _admin(factory, person, persona)
    with updating_json(path(factory), blank()) as doc:
        user = _user(doc, uid)
        before = {k: user[k] for k in ("name", "personas", "scope")}
        if name is not None:
            user["name"] = _check_name(doc, name, uid)
        if personas is not None:
            user["personas"] = _personas(personas)
        if scope is not None:
            user["scope"] = scope_of(factory, scope)
        _keep_an_admin(doc)
    _record(factory, "user_changed", person, persona, user=uid, before=before,
            after={k: user[k] for k in ("name", "personas", "scope")})
    return public_user(user)


def _keep_an_admin(doc: Doc) -> None:
    if doc.get("mode") == TEAM and not any(is_admin(u) for u in doc["users"]):
        raise DecisionRefused("a team keeps at least one active user with IT on every project")


def set_active(factory: Factory, uid: str, active: bool, *, person: str, persona: str) -> Doc:
    """Deactivate a user (their sessions and links stop at their next request) or bring them back."""
    _admin(factory, person, persona)
    with updating_json(path(factory), blank()) as doc:
        user = _user(doc, uid)
        user["active"] = bool(active)
        _keep_an_admin(doc)
        if not active:
            for link in doc["links"]:
                if link["user"] == uid and not link.get("used"):
                    link["used"] = {"at": _now(factory), "by": "deactivated"}
    _record(factory, "user_activated" if active else "user_deactivated", person, persona, user=uid,
            name=user["name"])
    return public_user(user)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def link(factory: Factory, uid: str, *, kind: str = "invite", person: str, persona: str) -> Doc:
    """A one-use sign-in link for a user: an invite (a week) or a sign-in link (a day). The token is
    returned once and only its sha256 is kept."""
    if kind not in LINK_HOURS:
        raise ValueError(f"a link is {' or '.join(LINK_HOURS)}")
    _admin(factory, person, persona)
    token = secrets.token_urlsafe(32)
    expires = factory.clock.now() + timedelta(hours=LINK_HOURS[kind])
    with updating_json(path(factory), blank()) as doc:
        user = _user(doc, uid)
        if not user.get("active"):
            raise DecisionRefused(f"{uid} is deactivated: bring them back before sending a link")
        lid = f"L-{len(doc['links']) + 1:03d}"
        stamp = expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        doc["links"].append({"id": lid, "user": uid, "kind": kind, "sha256": _digest(token), "expires": stamp,
                             "used": None, "by": person})
    _record(factory, "link_made", person, persona, link=lid, user=uid, kind=kind, expires=stamp)
    return {"id": lid, "user": uid, "name": user["name"], "kind": kind, "token": token, "expires": stamp}


def redeem(factory: Factory, token: str) -> Doc | None:
    """The user a one-use link signs in, once (None: no such link, used, expired, or the user deactivated)."""
    if not isinstance(token, str) or not token or not exists(factory):
        return None
    digest, now = _digest(token), _now(factory)
    with updating_json(path(factory), blank()) as doc:
        found = next((x for x in doc["links"] if hmac.compare_digest(x["sha256"], digest)), None)
        if found is None or found.get("used") or found["expires"] <= now:
            return None
        user = _user(doc, found["user"])
        if not user.get("active") or doc.get("mode") != TEAM:
            return None
        found["used"] = {"at": now}
    _record(factory, "signed_in", user["name"], "", link=found["id"], user=user["id"], kind=found["kind"])
    return public_user(user)


def public_user(user: Doc) -> Doc:
    return {k: user.get(k) for k in ("id", "name", "email", "personas", "scope", "identities", "active", "owner",
                                     "created")}


def user_of(doc: Doc, ident_id: str) -> Doc | None:
    return next((u for u in doc["users"] if ident_id in u.get("identities", [])), None)


def owner_identity(doc: Doc) -> str | None:
    """The platform identity of the first active IT user: who the cockpit's own start link signs in."""
    first = next((u for u in doc["users"] if is_admin(u)), None)
    return PLATFORM + first["id"] if first else None


# -- groups, project roles and views -------------------------------------------------------------------------

def map_group(factory: Factory, group: str, to: str, *, scope: Any = "*", label: str = "", remove: bool = False,
              person: str, persona: str) -> Doc:
    """An identity provider's group (an id no user can choose: Entra ID's object id or an app role) mapped
    to a persona on a scope, or the mapping removed."""
    _admin(factory, person, persona)
    group = str(group or "").strip()
    if not group or len(group) > 256 or any(ord(c) < 32 for c in group):
        raise ValueError("a group is its id or name as the provider's token lists it")
    target = _personas([to])[0] if to else None
    if target is None:
        raise ValueError("name the persona the group maps to")
    where = scope_of(factory, scope)
    with updating_json(path(factory), blank()) as doc:
        doc["groups"] = [g for g in doc["groups"] if not (g["group"] == group and g["persona"] == target)]
        if not remove:
            doc["groups"].append({"group": group, "persona": target, "scope": where, "label": str(label)[:200]})
    _record(factory, "group_unmapped" if remove else "group_mapped", person, persona, group=group, to=target,
            scope=where)
    return {"group": group, "persona": target, "scope": where, "removed": remove}


def set_role(factory: Factory, pid: str, *, user: str | None = None, group: str | None = None, personas: Any = None,
             person: str, persona: str) -> Doc:
    """On one project, a user or a group holds exactly ``personas`` (None: the override is removed)."""
    _admin(factory, person, persona)
    factory.project(pid)
    if (user is None) == (group is None):
        raise ValueError("a project role names a user or a group")
    chosen = None if personas is None else _personas(personas)
    with updating_json(path(factory), blank()) as doc:
        if user is not None:
            _user(doc, user)
        doc["roles"] = [r for r in doc["roles"]
                        if not (r["project"] == pid and r.get("user") == user and r.get("group") == group)]
        if chosen is not None:
            doc["roles"].append({"project": pid, "user": user, "group": group, "personas": chosen})
    _record(factory, "role_set" if chosen is not None else "role_cleared", person, persona, project=pid, user=user,
            group=group, personas=chosen)
    return {"project": pid, "user": user, "group": group, "personas": chosen}


def set_views(factory: Factory, to: str, hidden: Any, *, person: str, persona: str) -> Doc:
    """The pages a persona does not see in the cockpit (a filter on what it shows; access stays per project)."""
    _admin(factory, person, persona)
    target = _personas([to])[0]
    pages = [p for p in PAGES if p in set(hidden or [])]
    if len(pages) != len(set(hidden or [])):
        raise ValueError(f"a page is one of {', '.join(PAGES)}")
    with updating_json(path(factory), blank()) as doc:
        doc["views"] = {**doc.get("views", {}), target: pages}
    _record(factory, "views_set", person, persona, to=target, hidden=pages)
    return {"persona": target, "hidden": pages}
