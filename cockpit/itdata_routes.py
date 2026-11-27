"""The cockpit's routes for Integrations and data, IT's view of the connections (kernel/itdata*.py, FR-ITD1).

Reads (they write nothing):

- ``GET /api/it-data``: every connection of the platform, each project's integrations, every credential by name,
  what each agent may reach and the factory home's data stores with retention;
- ``GET /api/projects/<pid>/it-data``: what this project connects to, what each agent may reach and its data flow.

Writes, each signed by a person and persona (with access enforced, granted on the project the body names, else on
the factory) and recorded in the ledger. ``project`` in the body names the project; without it the platform's:

- ``POST /api/it-data/check``: check every connection (or ``item``) now. Outside the write lock: it opens TCP
  connections, each with a short timeout, and keeps its results under their own file lock;
- ``POST /api/it-data/disable``: IT turns ``item`` off through its own rule; 409 says where else it is changed.
  A connection that serves other projects too (a relay of every project's events, a webhook source bound to several)
  is signed on the platform even when a project is named, so IT granted on one project cannot stop it for all;
- ``POST /api/it-data/rotate-reminder``: a reminder to rotate ``credential`` in ``days`` (90 by default).
"""

from __future__ import annotations

import re
from typing import Any

from kernel import itdata_actions as actions
from kernel import itdata_project as views
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", r"/api/it-data", "get_itdata"),
    ("GET", rf"/api/projects/{PID}/it-data", "get_project_itdata"),
    ("POST", r"/api/it-data/check", "post_itdata_check"),
    ("POST", r"/api/it-data/disable", "post_itdata_disable"),
    ("POST", r"/api/it-data/rotate-reminder", "post_itdata_rotate"),
]
UNLOCKED = {"post_itdata_check"}
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


def _text(body: dict[str, Any], key: str, limit: int) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} is text of at most {limit} characters")
    return value.strip()


class ItDataRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``_project`` and ``_who``."""

    factory: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _itdata_target(self, body: dict[str, Any]) -> tuple[Any, str]:
        """The project the body names (or None: the platform), and the id access signs on."""
        pid = _text(body, "project", 100)
        if not pid or pid == FACTORY_PID:
            return None, FACTORY_PID
        return self._project(pid), pid

    def get_itdata(self, **_: Any) -> Reply:
        return 200, views.platform_view(self.factory)

    def get_project_itdata(self, pid: str, **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, views.platform_view(self.factory)
        return 200, views.project_view(self._project(pid))

    def post_itdata_check(self, body: dict[str, Any], **_: Any) -> Reply:
        project, pid = self._itdata_target(body)
        person, persona = self._who(body, pid)
        try:
            out = actions.check(self.factory, person=person, persona=persona, project=project,
                                item=_text(body, "item", 200) or None)
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None
        return 200, out

    def post_itdata_disable(self, body: dict[str, Any], **_: Any) -> Reply:
        project, _ = self._itdata_target(body)
        item = _text(body, "item", 200)
        if not item:
            raise _error(400, "item names the connection to turn off (its id, such as relay:SUB-001)")
        # one that serves other projects too is the platform's to turn off: signed on it, not on the project named
        person, persona = self._who(body, actions.signs_on(self.factory, item, project) or FACTORY_PID)
        try:
            out = actions.disable(self.factory, item, person=person, persona=persona,
                                  reason=_text(body, "reason", 300), project=project)
        except actions.NotHere as exc:
            raise _error(409, str(exc)) from None
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None
        return 200, out

    def post_itdata_rotate(self, body: dict[str, Any], **_: Any) -> Reply:
        project, pid = self._itdata_target(body)
        person, persona = self._who(body, pid)
        days = body.get("days", 90)
        try:
            out = actions.remind_rotation(self.factory, _text(body, "credential", 100), person=person,
                                          persona=persona, days=days, project=project)
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None
        return 200, out
