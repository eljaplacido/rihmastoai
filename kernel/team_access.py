"""Team mode as access rules (D-0024 item 4, FR-PPL1): what the team file grants, its identity provider, and
what each person sees.

``access_of`` turns the team file (kernel/team.py) into the same access rules IT's access file gives
(``kernel.accessfile.Access``, with ``source="team"``), so every surface checks a team member exactly as it
checks an identity IT's file grants (``kernel.access.sign`` and ``require``):

- each active user's identities (``rihmasto:U-001``, and ``local:<os user>`` or ``<issuer>#<subject>`` where
  named) are bound to the user's personas on the user's scope; a deactivated user holds nothing;
- each mapped group is bound to its persona on its scope;
- a project role replaces, on that one project, what the user or the group holds elsewhere.

The identity provider (Entra ID, AWS ALB, Google IAP or any OIDC proxy: ``set_idp``) is checked as IT's
``proxy`` is (``kernel.accessfile.proxy_of``). Its public keys are kept beside the team file (``jwks.json``):
pasted by a person, or fetched once from the provider's JWKS address on a person's word (``fetch_keys``), never
in the background. ``test_token`` shows what a token from the provider would sign in as, and writes nothing.

``seen`` gives the cockpit a factory that shows a team member only the projects their personas cover.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from kernel import team
from kernel.accessfile import ALL, ENFORCED, SINGLE, Access, AccessFileError, Binding, proxy_of
from kernel.canon import Canon, deciders_of
from kernel.jwt_verify import KeyFileError, parse_jwks
from kernel.people import Identity
from kernel.store import Factory, Project, updating_json, write_text

IDP_KEYS = ("preset", "issuer", "origin", "audience", "token_header", "algorithm", "subject_claim", "name_claim",
            "groups_claim", "signer", "clock_skew")
_JWKS_URL = re.compile(r"(?:https://[^\s#]{1,400}|http://(?:127\.0\.0\.1|localhost):\d{1,5}/[^\s#]{0,400})\Z")
MAX_KEYS_BYTES = 256 * 1024
FETCH_TIMEOUT = 10
_BUILT: dict[tuple[str, str, tuple[str, ...]], Access] = {}


# -- the team file as access rules ---------------------------------------------------------------------------

def _minus(scope: Any, overridden: set[str], pids: list[str]) -> tuple[str, ...]:
    if scope == ALL:
        return (ALL,) if not overridden else tuple(p for p in pids if p not in overridden)
    return tuple(p for p in scope if p not in overridden)


def _user_bindings(user: dict, roles: list[dict], pids: list[str]) -> list[Binding]:
    mine = {r["project"]: r["personas"] for r in roles if r.get("user") == user["id"]}
    out = []
    for ident in user.get("identities", []):
        scope = _minus(user.get("scope", ALL), set(mine), pids)
        out += [Binding(p, scope, subject=ident) for p in user.get("personas", []) if scope]
        out += [Binding(p, (pid,), subject=ident) for pid, ps in mine.items() for p in ps]
    return out


def _group_bindings(groups: list[dict], roles: list[dict], pids: list[str]) -> list[Binding]:
    out = []
    for g in groups:
        theirs = {r["project"] for r in roles if r.get("group") == g["group"]}
        scope = _minus(g.get("scope", ALL), theirs, pids)
        if scope:
            out.append(Binding(g["persona"], scope, group=g["group"]))
    for r in roles:
        if r.get("group"):
            out += [Binding(p, (r["project"],), group=r["group"]) for p in r["personas"]]
    return out


def _proxy(doc: dict) -> Any:
    idp = doc.get("idp")
    return proxy_of({k: idp[k] for k in IDP_KEYS if k in idp}) if idp else None


def build(factory: Factory, doc: dict) -> Access:
    """The team file's grants as access rules, whatever its mode (ValueError, AccessFileError: why not)."""
    pids = [p.pid for p in factory.projects()]
    pids += [] if "_factory" in pids else ["_factory"]
    active = [u for u in doc["users"] if u.get("active")]
    people = {i: u["name"] for u in active for i in u.get("identities", [])}
    bindings = [b for u in active for b in _user_bindings(u, doc["roles"], pids)]
    bindings += _group_bindings(doc["groups"], doc["roles"], pids)
    access = Access(ENFORCED, changed_by=team.owner_identity(doc), proxy=_proxy(doc), people=people,
                    bindings=tuple(bindings), source="team")
    from kernel.access_tokens import with_keys

    return with_keys(team.folder(factory), access)


def access_of(factory: Factory) -> Access | None:
    """The access rules the team file gives: None without a team file; single-operator rules in solo mode;
    in team mode the team's grants, or rules that refuse every decision when the file cannot be read."""
    if not team.exists(factory):
        return None
    try:
        raw = team.path(factory).read_bytes()
        doc = team.read(factory)
    except (OSError, team.TeamFileError) as exc:
        return Access(ENFORCED, error=f"team mode is on, but {exc}", source="team")
    sha = hashlib.sha256(raw).hexdigest()
    if doc["mode"] != team.TEAM:
        return Access(SINGLE, sha256=sha, source="team")
    keys_sha = ""
    if keys_path(factory).is_file():
        with contextlib.suppress(OSError):
            keys_sha = hashlib.sha256(keys_path(factory).read_bytes()).hexdigest()
    key = (sha, keys_sha,
           tuple(sorted(p.name for p in factory.projects_dir.iterdir())) if factory.projects_dir.exists() else ())
    if key not in _BUILT:
        try:
            built = build(factory, doc)
        except (ValueError, AccessFileError, KeyError, TypeError) as exc:
            built = Access(ENFORCED, error=f"the team file is not valid: {exc}", source="team")
        if len(_BUILT) > 32:
            _BUILT.clear()
        _BUILT[key] = replace(built, sha256=sha)
    return _BUILT[key]


def keys_path(factory: Factory) -> Path:
    return team.folder(factory) / "jwks.json"


# -- the identity provider -----------------------------------------------------------------------------------

def set_idp(factory: Factory, settings: dict, *, jwks_url: str | None = None, person: str,
            persona: str) -> dict:
    """The identity provider team mode signs people in with, checked as IT's proxy settings are."""
    team._admin(factory, person, persona)
    cfg = {k: settings[k] for k in IDP_KEYS if settings.get(k) not in (None, "")}
    if "issuer" in cfg and isinstance(cfg["issuer"], str):
        cfg["issuer"] = cfg["issuer"].rstrip("/") if cfg["issuer"].count("/") > 2 else cfg["issuer"]
    proxy = proxy_of(cfg)
    url = str(jwks_url or "").strip() or None
    if url is not None and not _JWKS_URL.match(url):
        raise ValueError("the JWKS address is https:// (or http:// on 127.0.0.1 or localhost)")
    with updating_json(team.path(factory), team.blank()) as doc:
        doc["idp"] = cfg | ({"jwks_url": url} if url else {})
    team._record(factory, "idp_set", person, persona, preset=proxy.preset, issuer=proxy.issuer,
                 audience=proxy.audience, groups_claim=proxy.groups_claim, jwks_url=url)
    return {"idp": cfg, "jwks_url": url}


def put_keys(factory: Factory, raw: bytes, *, person: str, persona: str, source: str = "pasted") -> dict:
    """The provider's public keys (a JWKS: public keys only, as IT's key file), kept beside the team file."""
    team._admin(factory, person, persona)
    try:
        keys = parse_jwks(raw)
    except KeyFileError as exc:
        raise ValueError(f"the keys are not usable: {exc}") from None
    write_text(keys_path(factory), raw.decode("utf-8"))
    sha = hashlib.sha256(raw).hexdigest()
    team._record(factory, "keys_set", person, persona, sha256=sha, keys=sorted(keys), source=source)
    return {"keys": sorted(keys), "sha256": sha, "source": source}


Opener = Callable[..., Any]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> Any:
        return None  # JWKS fetch never follows redirects to another host or scheme


def fetch_keys(factory: Factory, *, person: str, persona: str, opener: Opener | None = None) -> dict:
    """Fetch the provider's JWKS once, from the address the provider settings name, on a person's word."""
    team._admin(factory, person, persona)
    idp = team.read(factory).get("idp") or {}
    url = idp.get("jwks_url")
    if not url:
        raise ValueError("the provider settings name no JWKS address: name it, or paste the keys")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "rihmasto"})
    open_fn = opener or urllib.request.build_opener(_NoRedirect()).open
    try:
        with open_fn(req, timeout=FETCH_TIMEOUT) as res:
            raw = res.read(MAX_KEYS_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"the JWKS address did not answer ({type(exc).__name__})") from None
    if len(raw) > MAX_KEYS_BYTES:
        raise ValueError("the JWKS is larger than 256 KiB")
    return put_keys(factory, raw, person=person, persona=persona, source=url)


def test_token(factory: Factory, token: str) -> dict:
    """What a token from the provider would sign in as: identity, name, groups and personas, or why it is
    refused. It writes nothing, and the token is never kept."""
    from kernel import access as kaccess
    from kernel.access_cli import _Forwarded

    doc = team.read(factory)
    access = build(factory, doc)
    proxy = access.proxy
    if proxy is None:
        return {"ok": False, "refused": "no identity provider is set for team mode"}
    raw = str(token or "").strip()
    given = f"Bearer {raw}" if proxy.token_header.lower() == "authorization" and " " not in raw else raw
    try:
        ident = kaccess.from_proxy(access, _Forwarded(proxy.token_header, given))
    except kaccess.AccessRefused as exc:
        return {"ok": False, "refused": str(exc)}
    return {"ok": True, "identity": ident.id, "name": ident.name, "groups": list(ident.groups),
            "grants": kaccess.view(access, ident)["grants"]}


# -- what a team member sees ---------------------------------------------------------------------------------

class Seen(Factory):
    """The factory as one team member sees it: only the projects their personas cover."""

    def __init__(self, base: Factory, visible: frozenset[str]) -> None:
        super().__init__(base.home, base.clock)
        self.visible = visible

    def project(self, pid: str) -> Project:
        if pid not in self.visible:
            raise KeyError(f"no project {pid!r} you may see")
        return super().project(pid)

    def projects(self) -> list[Project]:
        return [p for p in super().projects() if p.pid in self.visible]


def seen(factory: Factory, access: Access | None, ident: Identity | None) -> Factory:
    """``factory`` itself, unless team mode keeps this member to some projects."""
    if access is None or access.source != "team" or not access.enforced or ident is None:
        return factory
    held = [b for b in access.bindings if b.holds(ident)]
    if any(ALL in b.scope for b in held):
        return factory
    return Seen(factory, frozenset(pid for b in held for pid in b.scope))


def who_decides(factory: Factory, pid: str, card_id: str) -> dict:
    """Who may decide a card, in words: its kind's personas, the people and groups who hold them here (in
    solo mode, the one person), and the delegations to agents that cover it."""
    from kernel import access as kaccess
    from kernel.agent_personas import describe, for_kind

    project = factory.project(pid)
    card = Canon(project).get_card(card_id)
    deciders = list(deciders_of(card))
    access = kaccess.load(factory)
    holders = _holders(access, deciders, pid) if access.enforced and access.error is None else []
    agents = [describe(d) for d in for_kind(project, card["kind"])]
    solo = team.solo_name(factory) if not access.enforced else None
    kind = card["kind"].replace("_", " ")
    words = f"{card_id}, {'an' if kind[0] in 'aeiou' else 'a'} {kind} card, is decided as {' or '.join(deciders)}."
    if solo:
        words += f" In solo mode that is you, {solo}: the decision is signed as {deciders[0]} unless you choose."
    elif holders:
        words += " Here: " + "; ".join(f"{h.get('name') or 'group ' + h['group']} as {', '.join(h['personas'])}"
                                        for h in holders) + "."
    if agents:
        words += " By delegation: " + "; ".join(agents) + "."
    return {"card": card_id, "kind": card["kind"], "state": card["state"], "deciders": deciders, "holders": holders,
            "agents": agents, "solo": solo, "text": words}


def _holders(access: Access, deciders: list[str], pid: str) -> list[dict]:
    """The people (once each, by name) and the groups who hold one of ``deciders`` on ``pid``."""
    from kernel import access as kaccess

    holders: list[dict] = []
    for ident_id, name in access.people.items():
        mine = kaccess.personas(access, Identity(ident_id, name), pid)
        held = [p for p in deciders if p in mine]
        if held and not any(h["name"] == name for h in holders):
            holders.append({"name": name, "personas": held})
    return holders + [{"group": b.group, "personas": [b.persona]} for b in access.bindings
                      if b.group and b.persona in deciders and b.covers(pid)]


def public(factory: Factory) -> dict:
    """Team mode as Settings shows it: the mode in plain words, the users (never a link's hash), groups,
    roles, views and the provider."""
    from kernel import access as kaccess

    m = team.mode(factory)
    try:
        doc = team.read(factory)
    except team.TeamFileError as exc:
        return {"mode": m, "error": str(exc), "words": f"Team mode, but {exc}: every decision is refused."}
    keys = keys_path(factory)
    words = {team.SOLO: "Just you: you act in every persona, and each decision names the persona it used.",
             team.TEAM: f"A team: {sum(1 for u in doc['users'] if u.get('active'))} active people and "
                        f"{len(doc['groups'])} mapped groups decide as the personas they hold.",
             team.IT_FILE: "IT's access file governs who decides here (" + kaccess.describe(kaccess.load(factory))
             + ")."}[m]
    return {"mode": m, "words": words, "solo": doc.get("solo"), "users": [team.public_user(u) for u in doc["users"]],
            "groups": doc["groups"], "roles": doc["roles"], "views": doc.get("views") or {},
            "idp": doc.get("idp"), "keys": _kids(keys), "pages": list(team.PAGES)}


def _kids(keys: Path) -> list[str]:
    try:
        return sorted(str(k.get("kid")) for k in json.loads(keys.read_text(encoding="utf-8")).get("keys") or [])
    except (OSError, ValueError, AttributeError):
        return []
