"""The cockpit's routes for People in the loop (kernel/hitl.py, hitl_links.py, hitl_send.py, hitl_nudge.py;
FR-HITL1).

One read, the project's view: its asks with who they wait on and for how long, the links given to people outside
(never a hash or a contact's address), each check family's level and where it is set, the nudges due, and the
channels a send can use. Every write is signed by a person and persona (with access enforced, granted on the
project) and recorded in the project's ledger; the platform-wide channels are IT's and the factory's ledger's.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import hitl, hitl_links, hitl_nudge, hitl_send
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"   # as cockpit/server.py PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/hitl", "get_hitl"),
    ("POST", rf"/api/projects/{PID}/hitl/asks", "post_hitl_ask"),
    ("POST", rf"/api/projects/{PID}/hitl/answer", "post_hitl_answer"),
    ("POST", rf"/api/projects/{PID}/hitl/send", "post_hitl_send"),
    ("POST", rf"/api/projects/{PID}/hitl/links", "post_hitl_link"),
    ("POST", rf"/api/projects/{PID}/hitl/revoke", "post_hitl_link_revoke"),
    ("POST", rf"/api/projects/{PID}/hitl/nudge", "post_hitl_nudge"),
    ("PUT", rf"/api/projects/{PID}/hitl/enforcement", "put_hitl_enforcement"),
    ("PUT", r"/api/hitl/channels", "put_hitl_channels"),
]
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


def _str(body: dict[str, Any], key: str, limit: int = 2000) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise _error(400, f"{key} is text of at most {limit} characters")
    return value.strip()


def _ids(body: dict[str, Any], key: str) -> list[str]:
    value = body.get(key)
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    if not isinstance(value, list) or len(value) > 50 or not all(isinstance(v, str) for v in value):
        raise _error(400, f"{key} is a list of ask ids (HQ-001)")
    return value


class HitlRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``_who`` and ``request_origin``."""

    factory: Any
    server: Any
    request_origin: str

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _loop_project(self, pid: str) -> Any:
        if pid == FACTORY_PID:
            raise _error(400, "the factory itself has no asks: open a project")
        try:
            return self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None

    def _link_base(self) -> str:
        """Where an outside reviewer's link points: IT's setting, else the embed server's public address, else
        this cockpit as the person reaches it."""
        return (hitl_send.channels(self.factory)["link_base"] or getattr(self.server, "embed_base", None)
                or getattr(self, "request_origin", "") or self.server.origin).rstrip("/")

    def _own_origin(self) -> str:
        """This cockpit as the person reached it: where a notice's link back points unless IT gave the relay one."""
        return (getattr(self, "request_origin", "") or self.server.origin).rstrip("/")

    def get_hitl(self, pid: str, **_: object) -> Reply:
        chans = hitl_send.channels(self.factory)
        if pid == FACTORY_PID:
            return 200, {"project": pid, "asks": [], "waiting": [], "links": [], "levels": [], "nudges": [],
                         "channels": chans, "families": list(hitl.FAMILIES), "kinds": list(hitl.KINDS)}
        project = self._loop_project(pid)
        base = self._link_base()
        return 200, {"project": pid, "link_base": base, "link_base_local": hitl_links.local_only(base),
                     "asks": hitl.asks(project)[::-1], "waiting": hitl.who_has_not_answered(project),
                     "links": [hitl_links.public(self.factory, r) for r in hitl_links.links(self.factory, pid)][::-1],
                     "levels": hitl.levels(project), "nudges": hitl_nudge.due(project),
                     "blocking": [a["id"] for a in hitl.blocking(project)], "channels": chans,
                     "families": list(hitl.FAMILIES), "kinds": list(hitl.KINDS),
                     "family_persona": hitl.FAMILY_PERSONA, "link_creators": list(hitl_links.CREATORS),
                     "setters": list(hitl.SETTERS)}

    def post_hitl_ask(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._loop_project(pid)
        person, persona = self._who(body, pid)
        options = body.get("options")
        if options is not None and (not isinstance(options, list) or len(options) > hitl.MAX_OPTIONS):
            raise _error(400, f"options is a list of at most {hitl.MAX_OPTIONS} choices")
        item = hitl.ask(project, text=_str(body, "text"), kind=_str(body, "kind", 20) or "question",
                        family=_str(body, "family", 20) or "general", to_persona=_str(body, "to_persona", 40) or None,
                        to_person=_str(body, "to_person", 120) or None, options=options, person=person, persona=persona)
        return 201, {"ask": item}

    def post_hitl_answer(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._loop_project(pid)
        person, persona = self._who(body, pid)
        try:
            item = hitl.answer(project, _str(body, "ask", 20), answer=_str(body, "answer"),
                               comment=_str(body, "comment"), person=person, persona=persona)
        except KeyError as exc:
            raise _error(404, str(exc.args[0])) from None
        return 200, {"ask": item}

    def post_hitl_send(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._loop_project(pid)
        person, persona = self._who(body, pid)
        try:
            return 200, hitl_send.send_ask(project, _str(body, "ask", 20), person=person, persona=persona,
                                           cockpit=self._own_origin())
        except KeyError as exc:
            raise _error(404, str(exc.args[0])) from None

    def post_hitl_link(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._loop_project(pid)
        person, persona = self._who(body, pid)
        asks = _ids(body, "asks")
        hours = body.get("hours", hitl_links.DEFAULT_HOURS)
        link = hitl_links.create(project, name=_str(body, "name", 120),
                                 persona=_str(body, "reviewer_persona", 40) or hitl_links.persona_for(project, asks)
                                 or "", asks=asks, person=person, creator_persona=persona,
                                 role=_str(body, "role", 120), hours=hours, channel=_str(body, "channel", 20) or "copy",
                                 address=_str(body, "address", 200) or None, context=_str(body, "context", 120))
        base = self._link_base()
        url = hitl_links.url(base, link.pop("token"))
        sent = hitl_send.send_link(project, link, url)
        warn = {"warning": hitl_links.LOCAL_WARNING} if hitl_links.local_only(base) else {}
        said = f"{link['id']} made for {link['name']}. {sent['said']} It is shown once below to copy."
        # the address, shown once wherever the request came from: the view's form or Ask Rihma's Confirm (FR-HITL2)
        return 201, {"link": hitl_links.public(self.factory, link), "url": url, "shown_once": True, "sent": sent,
                     "once": [{"link": link["id"], "name": link["name"], "url": url, "said": sent["said"]}],
                     "said": said, **warn}

    def post_hitl_link_revoke(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._loop_project(pid)
        person, persona = self._who(body, pid)
        try:
            return 200, {"link": hitl_links.revoke(project, _str(body, "link", 20), person=person, persona=persona)}
        except KeyError as exc:
            raise _error(404, str(exc.args[0])) from None

    def post_hitl_nudge(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._loop_project(pid)
        person, persona = self._who(body, pid)
        return 200, hitl_nudge.nudge(project, person=person, persona=persona, base=self._link_base(),
                                     cockpit=self._own_origin())

    def put_hitl_enforcement(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        """A project's level is signed on that project; every project's (scope platform) on the factory's own
        grant, as the channels are: a grant on one project never sets a rule for all of them (FR-HITL2)."""
        project = self._loop_project(pid)
        scope = _str(body, "scope", 20) or "project"
        person, persona = self._who(body, FACTORY_PID if scope == "platform" else pid)
        return 200, hitl.set_level(project, _str(body, "family", 20), _str(body, "level", 20), person=person,
                                   persona=persona, scope=scope)

    def put_hitl_channels(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        given = {k: _str(body, k, n) or None for k, n in (("provider", 20), ("url", 500), ("key_env", 80),
                                                         ("sender", 40), ("link_base", 300))}
        return 200, hitl_send.set_whatsapp(self.factory, person=person, persona=persona, **given)
