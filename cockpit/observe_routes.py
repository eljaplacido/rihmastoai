"""The cockpit's routes for observer links (kernel/observe.py, FR-SHR1): share a read-only view of your work.

One read, the Share page's: the links made (never a hash or a session), who is watching each now, the guests'
comments, their suggestions waiting, the projects that may be shared (each marked confidential or not) and the
durations. Every write is signed by a person and persona, with access enforced granted where it acts: a project
link on that project, a link for every project on the factory's own grant. The sharer's current view (following)
is kept in memory only and records nothing. The link's address is given once, to the sharer, to pass on: nothing
is ever sent anywhere.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import observe, observe_guard
from kernel.confidential import confidential
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"   # as cockpit/server.py PID
ROUTES = [
    ("GET", r"/api/observe", "get_observe"),
    ("POST", r"/api/observe/links", "post_observe_link"),
    ("POST", r"/api/observe/revoke", "post_observe_revoke"),
    ("POST", r"/api/observe/presence", "post_observe_presence"),
    ("POST", rf"/api/projects/{PID}/observe/suggestions", "post_observe_suggestion"),
]
UNLOCKED = {"post_observe_presence"}      # where the sharer is: in memory, never on the write lock
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


def _str(body: dict[str, Any], key: str, limit: int = 200) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise _error(400, f"{key} is text of at most {limit} characters")
    return value.strip()


def _hours(body: dict[str, Any]) -> int:
    value = body.get("hours", 1)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or value not in observe.DURATIONS:
        raise _error(400, "hours is 1 (an hour), 24 (a day) or 168 (a week)")
    return int(value)


class ObserveRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``_who`` and ``request_origin``."""

    factory: Any
    server: Any
    request_origin: str

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _observe_base(self) -> str:
        """Where the guest's link points: this cockpit as the sharer reaches it (the tunnel's address, too)."""
        return (getattr(self, "request_origin", "") or self.server.origin).rstrip("/")

    def get_observe(self, **_: object) -> Reply:
        shown = observe.links(self.factory)[::-1]
        projects = [{"pid": p.pid, "title": p.meta.get("title") or p.pid, "confidential": confidential(p)}
                    for p in self.factory.projects() if p.pid != FACTORY_PID]
        out = {"links": [observe.public(self.factory, r) | {"scope_title": observe.scope_title(self.factory, r)}
                         for r in shown],
               "comments": observe.comments(self.factory)[::-1][:100],
               "suggestions": observe.suggestions(self.factory)[::-1][:100],
               "projects": projects,
               "durations": [{"hours": h, "words": w} for h, w in observe.DURATIONS.items()],
               "scopes": list(observe.SCOPES)}
        seen = {p.pid for p in self.factory.projects()}           # with access enforced, within grants (FR-SHR2)
        return 200, observe_guard.readable(getattr(self, "access", None), getattr(self, "identity", None), out, seen)

    def post_observe_link(self, body: dict[str, Any], **_: object) -> Reply:
        scope = _str(body, "scope", 20) or "project"
        pid = _str(body, "project", 90) or None
        person, persona = self._who(body, pid if scope == "project" and pid else FACTORY_PID)
        link = observe.create(self.factory, scope=scope, project=pid, hours=_hours(body),
                              guest=_str(body, "guest", 80), person=person, persona=persona,
                              confidential=body.get("confidential") is True, intake=body.get("intake") is True)
        url = observe.url(self._observe_base(), link.pop("token"))
        shown = observe.public(self.factory, link)
        lasts = observe.DURATIONS[link["hours"]]
        said = (f"{link['id']}: {observe.scope_title(self.factory, link)}, read only, for {lasts}. Pass it on "
                "yourself: Rihmasto sends nothing. It is shown once below to copy.")
        return 201, {"link": shown, "url": url, "shown_once": True, "said": said,
                     "once": [{"link": link["id"], "name": link["guest"] or "your guest", "url": url,
                               "said": said, "reusable": True}]}

    def post_observe_revoke(self, body: dict[str, Any], **_: object) -> Reply:
        lid = _str(body, "link", 20)
        try:
            found = observe.find(self.factory, lid)
        except KeyError as exc:
            raise _error(404, str(exc.args[0])) from None
        person, persona = self._who(body, found["project"] if found["scope"] == "project" and found["project"]
                                    else FACTORY_PID)
        return 200, {"link": observe.revoke(self.factory, lid, person=person, persona=persona)}

    def post_observe_presence(self, body: dict[str, Any], **_: object) -> Reply:
        pid = _str(body, "project", 90) or None
        person, persona = self._who(body, pid or FACTORY_PID)
        paused, hint = observe_guard.body_paused(body)       # a heartbeat never undoes a pause (FR-SHR2)
        where = observe.set_presence(self.factory, person=person, persona=persona, project=pid,
                                     view=_str(body, "view", 40) or None, paused=paused, hint=hint)
        active = observe.active_for(self.factory, person)
        return 200, {"presence": where, "sharing": len(active),
                     "watching": sorted({g for r in active for g in r["watching"]})}

    def post_observe_suggestion(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        try:
            project = self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None
        person, persona = self._who(body, pid)
        try:
            row = observe.decide_suggestion(project, _str(body, "suggestion", 20), verdict=_str(body, "verdict", 10),
                                            person=person, persona=persona)
        except KeyError as exc:
            raise _error(404, str(exc.args[0])) from None
        return 200, {"suggestion": row}
