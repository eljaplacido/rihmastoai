"""The cockpit's routes for an adopted project's own page (FR-RPJ1; docs/brownfield.md).

- ``GET /api/projects/<pid>/areas``: its inventory and activity by area (kernel/areas.py), with a summary;
  ``POST`` takes them again, signed.
- ``POST /api/projects/<pid>/watch``: set up the watch (kernel/adopt_watch.py), signed.
- ``POST /api/projects/<pid>/baseline/stated``: run a test command the project's instructions state as its
  baseline (kernel/adopt_stated.py), after the person said yes: it runs the project's own code, so it runs as a
  job, through IT's isolation runner when access is enforced.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import adopt_stated, adopt_watch, areas
from kernel.adopt import is_adopted
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/areas", "get_areas"),
    ("POST", rf"/api/projects/{PID}/areas", "post_areas"),
    ("POST", rf"/api/projects/{PID}/watch", "post_watch"),
    ("POST", rf"/api/projects/{PID}/baseline/stated", "post_baseline_stated"),
]
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


class AdoptedRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``server``, ``_project`` and ``_who``."""

    factory: Any
    server: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _adopted(self, pid: str) -> Any:
        project = self._project(pid)
        if not is_adopted(project):
            raise _server().ApiError(409, f"{pid} was not adopted: it has no repository of its own to read")
        return project

    def get_areas(self, pid: str, **_: object) -> Reply:
        project = self._project(pid)               # a project not adopted has none: said, not an error
        got = project.read("areas.json", None) or {"measured": False, "basis": "not taken" if is_adopted(project)
                                                   else "it was not adopted: it has no repository of its own to read"}
        return 200, {"areas": got, "summary": areas.summary(got)}

    def post_areas(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._adopted(pid)
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        got = areas.record(project, person, persona)
        return 200, {"areas": got, "summary": areas.summary(got)}

    def post_watch(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._adopted(pid)
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        parts = body.get("parts") if isinstance(body.get("parts"), list) else ["commits", "weekly", "failures"]
        view = adopt_watch.setup(project, person=person, persona=persona, commits="commits" in parts,
                                 weekly="weekly" in parts, failures="failures" in parts,
                                 subscription=_server()._text(body, "subscription", limit=100) or None)
        return 200, {"watch": view}

    def post_baseline_stated(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        from kernel import access_isolation as kisolation

        srv = _server()
        project = self._adopted(pid)
        person, persona = self._who(body, pid)
        srv._require_person(person, persona)
        command = srv._text(body, "command", required=True, limit=300)
        if command not in [o["command"] for o in adopt_stated.offers(project)]:
            raise srv.ApiError(400, "only a test command the project's instructions state is run, as stated")
        if persona not in adopt_stated.RUNNERS:
            raise srv.ApiError(403, f"refused: a stated command is run by a {', '.join(adopt_stated.RUNNERS)}")
        if body.get("confirm") is not True:
            raise srv.ApiError(400, "say yes first: " + adopt_stated.RUNS_CODE)
        kisolation.require(self.factory, kisolation.SUITE)     # it runs the project's own code
        running = self.server.running_job(pid)
        if running is not None:
            raise srv.ApiError(409, f"job {running['id']} is still running for {pid}")
        project.log("cockpit_write", {"action": "baseline_stated_requested", "target": command, "person": person,
                                      "persona": persona, "confirmed": adopt_stated.RUNS_CODE})   # signed, first
        job = self.server.start_job("baseline", project.pid,
                                    ["-m", "kernel.cli", "baseline", project.pid, "--command", command, "--person",
                                     person, "--persona", persona, "--yes"], {"person": person, "persona": persona})
        return 201, {"job": self.server.job_view(job)}
