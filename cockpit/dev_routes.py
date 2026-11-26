"""The cockpit's routes for a project's development board, trace and briefing (FR-DEV1).

Reads write nothing:

- ``GET /api/projects/<pid>/dev/board``: the lanes and cards (kernel/devboard.py);
- ``GET /api/projects/<pid>/dev/trace?window=&who=&harness=&task=``: the timeline (kernel/devtrace.py);
- ``GET /api/projects/<pid>/dev/briefing?person=``: the developer briefing (kernel/devbrief.py), for the signed-in
  person under enforced access;
- ``GET /api/projects/<pid>/dev/hooks?person=&persona=``: the session hooks for Claude Code and Cursor, to copy or
  download (kernel/devsessions.py), and the sessions recorded so far.

One write, signed by a person and persona as the other writes are: ``POST /api/projects/<pid>/dev/seen`` records
the person's look at the briefing (``dev_looked``), so the next briefing counts from there.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from kernel import devboard, devbrief, devsessions, devtrace
from kernel.learn import FACTORY_PID
from kernel.people import PERSONAS, is_person

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/dev/board", "get_dev_board"),
    ("GET", rf"/api/projects/{PID}/dev/trace", "get_dev_trace"),
    ("GET", rf"/api/projects/{PID}/dev/briefing", "get_dev_briefing"),
    ("GET", rf"/api/projects/{PID}/dev/hooks", "get_dev_hooks"),
    ("POST", rf"/api/projects/{PID}/dev/seen", "post_dev_seen"),
]
Reply = tuple[int, dict[str, Any]]
NOT_HERE = {"applies": False, "why": "development work is a product project's; open a project"}


def _q(query: dict[str, Any], key: str, limit: int = 64) -> str | None:
    value = query.get(key)
    return str(value)[:limit] if value else None


class DevRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``identity``, ``_project`` and ``_who``."""

    factory: Any
    identity: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _reader(self, query: dict[str, Any]) -> str | None:
        name = self.identity.name if self.identity is not None else (query.get("person") or "").strip()[:200]
        return name if name and is_person(name) else None

    def get_dev_board(self, pid: str, **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, **NOT_HERE}
        return 200, devboard.board(self._project(pid))

    def get_dev_trace(self, pid: str, query: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, **NOT_HERE}
        from cockpit.server import ApiError

        who = _q(query, "who")
        try:
            return 200, devtrace.trace(self._project(pid), window=_q(query, "window"),
                                       who=who if who in devtrace.WHO else None, harness=_q(query, "harness"),
                                       task=_q(query, "task", 16))
        except devtrace.WindowRefused as exc:    # never compared as text: says what to give instead (FR-DEV2)
            raise ApiError(400, str(exc)) from None

    def get_dev_briefing(self, pid: str, query: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, **NOT_HERE}
        return 200, devbrief.briefing(self._project(pid), person=self._reader(query))

    def get_dev_hooks(self, pid: str, query: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, **NOT_HERE}
        project = self._project(pid)
        persona = query.get("persona") if query.get("persona") in PERSONAS else "developer"
        out = devsessions.hooks(project, person=self._reader(query) or "<your name>", persona=persona,
                                python=sys.executable)
        out["recorded"] = devsessions.sessions(project)[-20:][::-1]
        out["harnesses"] = devsessions.HARNESSES
        return 200, out

    def post_dev_seen(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        from cockpit.server import ApiError, _require_person

        if pid == FACTORY_PID:
            raise ApiError(400, "development work is a product project's; open a project")
        project = self._project(pid)
        person, persona = self._who(body, pid)
        _require_person(person, persona)
        return 200, {"project": pid, "looked": devsessions.look(project, person=person, persona=persona)}
