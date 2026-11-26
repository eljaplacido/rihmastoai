"""Settings > People and access: solo or team, users, groups, roles, the identity provider, agents given a persona
(D-0024 item 4, FR-PPL1; kernel/team.py, kernel/team_access.py, kernel/agent_personas.py).

Reads record nothing: who works here and how (``GET /api/people``), who may decide a card
(``GET /api/people/who``), and every persona given to an agent (``GET /api/agent-personas``). Testing a token
from the identity provider records nothing either. Every other write is signed by a person and persona as
the other write routes are, and only IT changes who works here (in solo mode the one person is IT too).

In team mode a platform user signs in with a one-use link (``team_auth``): the session answers that user
only, and ends at their next request once they are deactivated (``team_identity``). Turning team mode on
from the cockpit hands the tab a session for the person's own user, so they stay signed in.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel import agent_personas as kagents
from kernel import team as kteam
from kernel import team_access as kteam_access
from kernel.access_tokens import once
from kernel.accessfile import Access
from kernel.learn import FACTORY_PID
from kernel.people import Identity

PID = r"(?P<pid>_factory|[a-z0-9][a-z0-9-]{0,80})"
UID = r"(?P<uid>U-\d{1,6})"
ROUTES = [
    ("GET", r"/api/people", "get_people"),
    ("GET", r"/api/people/who", "get_people_who"),
    ("GET", r"/api/agent-personas", "get_agent_personas"),
    ("POST", r"/api/people/solo", "post_people_solo"),
    ("POST", r"/api/people/mode", "post_people_mode"),
    ("POST", r"/api/people/users", "post_people_user"),
    ("PUT", rf"/api/people/users/{UID}", "put_people_user"),
    ("POST", rf"/api/people/users/{UID}/link", "post_people_link"),
    ("POST", r"/api/people/groups", "post_people_group"),
    ("POST", r"/api/people/roles", "post_people_role"),
    ("PUT", r"/api/people/views", "put_people_views"),
    ("PUT", r"/api/people/idp", "put_people_idp"),
    ("POST", r"/api/people/keys", "post_people_keys"),
    ("POST", r"/api/people/test-token", "post_people_test_token"),
    ("POST", rf"/api/projects/{PID}/agent-personas", "post_agent_persona"),
]
UNLOCKED = {"post_people_test_token"}       # it records nothing
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def _text(body: dict[str, Any], key: str, *, limit: int = 200, required: bool = False) -> str:
    return str(_server()._text(body, key, limit=limit, required=required))


def _list(body: dict[str, Any], key: str) -> list[str] | None:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if not isinstance(value, list) or len(value) > 200 or not all(isinstance(v, str) for v in value):
        raise _server().ApiError(400, f"{key} is a list of names")
    return value


def _found(fn: Callable[..., Reply]) -> Callable[..., Reply]:
    """A route that names a user or a project: one that does not exist is a 404, not a bug."""
    def wrapped(*args: Any, **kwargs: Any) -> Reply:
        try:
            return fn(*args, **kwargs)
        except KeyError as exc:
            raise _server().ApiError(404, str(exc.args[0] if exc.args else exc)) from None
    wrapped.__doc__ = fn.__doc__
    return wrapped


def _scope(body: dict[str, Any]) -> Any:
    value = body.get("scope", "*")
    return value if value == "*" or value is None else _list(body, "scope")


# -- sign-in in team mode ------------------------------------------------------------------------------------

def team_identity(handler: Any, access: Access, path: str) -> Identity | None:
    """A team member's identity: the provider's signed token when one is set and the request carries it,
    else the user a one-use link's session was opened for. None only for the sign-in itself."""
    from kernel import access as kaccess

    server = _server()
    if access.error is not None:
        raise server.ApiError(403, f"refused: access is enforced, but {access.error}")
    if access.proxy is not None and _carries(handler.headers, access.proxy.token_header):
        try:
            return kaccess.from_proxy(access, handler.headers)
        except kaccess.AccessRefused as exc:
            proxied = exc
    else:
        proxied = None
    token = handler.headers.get(kaccess.SESSION_HEADER, "").strip()
    ident_id = handler.server.session_identity(token) if token else None
    if ident_id is not None and ident_id in access.people:
        return kaccess.identity(access, ident_id)
    if path == "/auth":
        return None
    why = proxied or ("this person's user is deactivated" if ident_id else "sign in with your one-use link")
    raise server.ApiError(401, f"refused: team mode: {why}")


def _carries(headers: Any, name: str) -> bool:
    try:
        raw = once(headers, name)
    except ValueError:
        return True
    return bool(raw) and not (name.lower() == "authorization" and raw.count(".") != 2)


def team_auth(server: Any, access: Access, bootstrap: Any) -> str | None:
    """A session for the user a one-use team link names, or for the team's first IT user when the link is
    the cockpit's own (printed at start, or made in a signed-in tab for its own person)."""
    if not isinstance(bootstrap, str) or not bootstrap:
        return None
    user = kteam.redeem(server.factory, bootstrap)
    if user is not None:
        return str(server.open_session(kteam.PLATFORM + user["id"]))
    taken = server.take_link(bootstrap)
    if taken is False:
        return None
    ident_id = taken if isinstance(taken, str) else kteam.owner_identity(kteam.read(server.factory))
    if ident_id is None or ident_id not in access.people:
        return None
    return str(server.open_session(ident_id))


def meta(api: Any) -> dict[str, Any]:
    """The people part of the page's meta: the mode in plain words, the solo person's name, and the pages the
    signed-in person's personas do not see."""
    mode = kteam.mode(api.factory)
    out: dict[str, Any] = {"mode": mode, "solo_name": kteam.solo_name(api.factory), "hidden_pages": []}
    if mode == kteam.TEAM and api.identity is not None and api.access.source == "team":
        from kernel import access as kaccess

        try:
            views = kteam.read(api.factory).get("views") or {}
        except kteam.TeamFileError:
            views = {}
        mine = kaccess.personas(api.access, api.identity)
        hidden = [set(views.get(p) or []) for p in mine]
        out["hidden_pages"] = sorted(set.intersection(*hidden)) if hidden else []
        out["holds"] = mine
    return out


class PeopleRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``access``, ``identity`` and ``_who``."""

    server: Any
    factory: Any
    access: Any
    identity: Any
    request_origin: str
    _who: Callable[[dict[str, Any], str | None], tuple[str, str]]

    def get_people(self, **_: object) -> Reply:
        out = kteam_access.public(self.factory)
        out["agents"] = kagents.listed(self.factory)
        out["me"] = {"identity": self.identity.id if self.identity else None,
                     "name": self.identity.name if self.identity else kteam.solo_name(self.factory)}
        return 200, out

    def get_people_who(self, query: dict[str, str], **_: object) -> Reply:
        pid, card = query.get("project", ""), query.get("card", "")
        if not pid or not card:
            return 200, {"text": "Name a project and a card: ?project=<id>&card=C-1", "holders": [], "agents": []}
        try:
            return 200, kteam_access.who_decides(self.factory, pid, card.upper())
        except KeyError as exc:
            raise _server().ApiError(404, f"no such card or project: {exc}") from None

    def get_agent_personas(self, **_: object) -> Reply:
        return 200, {"agents": kagents.listed(self.factory)}

    def post_people_solo(self, body: dict[str, Any], **_: object) -> Reply:
        person, _persona = self._who(body, FACTORY_PID)
        return 200, kteam.name_solo(self.factory, person)

    def post_people_mode(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        out = kteam.set_mode(self.factory, _text(body, "mode", limit=16, required=True), person=person,
                             persona=persona, reason=_text(body, "reason", limit=500))
        if out["mode"] == kteam.TEAM:      # this tab stays signed in, as the person's own user
            user = out["user"] or {}
            out["session"] = self.server.open_session(kteam.PLATFORM + user["id"]) if user.get("id") else None
        else:
            out["session"] = self.server.open_session(None)
        return 200, out

    def post_people_user(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        user = kteam.add_user(self.factory, _text(body, "name", required=True), personas=_list(body, "personas") or [],
                              scope=_scope(body), email=_text(body, "email"),
                              identity=_text(body, "identity", limit=400) or None, person=person, persona=persona)
        return 201, {"user": user}

    @_found
    def put_people_user(self, uid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        if isinstance(body.get("active"), bool):
            return 200, {"user": kteam.set_active(self.factory, uid, body["active"], person=person, persona=persona)}
        name = _text(body, "name") or None
        user = kteam.update_user(self.factory, uid, name=name, personas=_list(body, "personas"),
                                 scope=_scope(body) if "scope" in body else None, person=person, persona=persona)
        return 200, {"user": user}

    @_found
    def post_people_link(self, uid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        made = kteam.link(self.factory, uid, kind=_text(body, "kind", limit=16) or "invite", person=person,
                          persona=persona)
        made["url"] = f"{self.request_origin}/#k={made.pop('token')}"     # shown once, never kept
        return 201, {"link": made}

    def post_people_group(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        out = kteam.map_group(self.factory, _text(body, "group", limit=256, required=True), _text(body, "to", limit=64),
                              scope=_scope(body), label=_text(body, "label"), remove=body.get("remove") is True,
                              person=person, persona=persona)
        return 200, {"group": out}

    @_found
    def post_people_role(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        out = kteam.set_role(self.factory, _text(body, "project", limit=100, required=True),
                             user=_text(body, "user", limit=16) or None, group=_text(body, "group", limit=256) or None,
                             personas=_list(body, "personas"), person=person, persona=persona)
        return 200, {"role": out}

    def put_people_views(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        out = kteam.set_views(self.factory, _text(body, "to", limit=64, required=True), _list(body, "hidden") or [],
                              person=person, persona=persona)
        return 200, {"views": out}

    def put_people_idp(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        settings = body.get("idp")
        if not isinstance(settings, dict):
            raise _server().ApiError(400, "idp is the provider's settings: preset, issuer, origin, audience, groups_claim")
        return 200, kteam_access.set_idp(self.factory, settings, jwks_url=_text(body, "jwks_url", limit=500) or None,
                                         person=person, persona=persona)

    def post_people_keys(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        if body.get("fetch") is True:
            return 200, kteam_access.fetch_keys(self.factory, person=person, persona=persona)
        jwks = _text(body, "jwks", limit=200_000, required=True)
        return 200, kteam_access.put_keys(self.factory, jwks.encode("utf-8"), person=person, persona=persona)

    def post_people_test_token(self, body: dict[str, Any], **_: object) -> Reply:
        return 200, kteam_access.test_token(self.factory, _text(body, "token", limit=20_000, required=True))

    @_found
    def post_agent_persona(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, pid)
        project = self.factory.project(pid)
        out = kagents.assign(project, _list(body, "kinds") or [], agent_kind=_text(body, "agent_kind", limit=16) or "bridge",
                             agent=_text(body, "agent", limit=64, required=True), until=_text(body, "until", limit=64) or "7d",
                             verdicts=_list(body, "verdicts"), max_decisions=body.get("max") or None, person=person,
                             persona=persona, reason=_text(body, "reason", limit=2000))
        return 201, {"delegation": out}
