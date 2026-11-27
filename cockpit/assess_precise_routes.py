"""The cockpit's routes for a precise assessment (FR-ASP1; kernel/assess_precise.py, kernel/assess_measure.py).

- ``POST /api/projects/<pid>/assessment/verdict``: a person's verdict on a finding of the latest assessment,
  signed: ``not_relevant`` (with a reason, and ``also`` for the findings like it), ``relevant`` again, or, for a
  secret, ``fixture`` or ``real`` (remembered for its file). The answer names the findings like it, proposed for
  the same verdict.
- ``POST /api/projects/<pid>/assessment/runner``: the command the project runs its own tests with and the results
  file it writes, signed. Rihmasto never runs it; the next assessment reads the results file as the test runs.

``GET /api/projects/<pid>/assessment`` carries the rest: each finding as people judged it, the headline, the runner.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import assess_measure, assess_precise
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("POST", rf"/api/projects/{PID}/assessment/verdict", "post_assessment_verdict"),
    ("POST", rf"/api/projects/{PID}/assessment/runner", "post_assessment_runner"),
]
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


class AssessPreciseRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``server``, ``_project`` and ``_who``."""

    factory: Any
    server: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def post_assessment_verdict(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        srv = _server()
        project = self._project(pid)
        person, persona = self._who(body, pid)
        srv._require_person(person, persona)
        verdict = srv._text(body, "verdict", required=True, limit=32)
        if verdict in assess_precise.SECRET_MARKS and persona not in assess_precise.MARKERS:
            raise srv.ApiError(403, f"a secret is judged by a {', '.join(assess_precise.MARKERS)}, not {persona}")
        also = body.get("also") or []
        if not isinstance(also, list) or not all(isinstance(i, str) for i in also):
            raise srv.ApiError(400, "also is a list of finding ids, such as F-4")
        try:
            out = assess_precise.give(project, srv._text(body, "finding", required=True, limit=16), verdict,
                                      person=person, persona=persona, reason=srv._text(body, "reason", limit=400),
                                      also=also)
        except LookupError as exc:
            raise srv.ApiError(404, str(exc.args[0] if exc.args else exc)) from None
        return 200, out

    def post_assessment_runner(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        srv = _server()
        project = self._project(pid)
        person, persona = self._who(body, pid)
        srv._require_person(person, persona)
        setters = assess_measure.RUNNER_SETTERS
        if persona not in setters:
            raise srv.ApiError(403, f"a runner is mapped by a {', '.join(setters)}, not {persona}")
        kept = assess_measure.map_runner(project, command=srv._text(body, "command", required=True, limit=300),
                                         results=srv._text(body, "results", limit=300) or None,
                                         note=srv._text(body, "note", limit=300) or None, person=person,
                                         persona=persona)
        return 200, {"runner": kept, "next": "assess again: the next assessment reads its results file"}
