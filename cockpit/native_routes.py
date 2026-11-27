"""The cockpit's routes for a project's own sources (FR-SRC1, kernel/native_sources.py, kernel/native_apply.py).

- ``GET .../sources``: what is mapped and when it was last read, what is detected (each with Map), the planning
  documents that may be old plans (each with Use it anyway), the test roots, runs and imports, the trace, and the
  next steps. It reads the repository's committed revision and records nothing.

Writes, each signed by a person and persona (with access enforced, granted on the project) and in its ledger;
nothing is written to the repository:

- ``POST .../sources/map``: map a detected source (``key``) or one named (``spec``); with ``source``, change it;
- ``POST .../sources/<SRC-n>/stop``: stop reading it (kept, stopped);
- ``POST .../sources/read``: read every mapped source again;
- ``POST .../sources/use-anyway``: use a planning document (``path``) although it may be an old plan;
- ``POST .../sources/import-results``: a results file produced elsewhere (``text``), with ``produced_at`` and
  ``machine``;
- ``POST .../sources/run``: run a mapped test root's command, after ``confirm``: a job (live in Running now), since
  it runs the project's own code on this machine, through IT's isolation runner when access is enforced.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import adopt_stated, native_apply, native_sources, native_tests
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/sources", "get_native_sources"),
    ("POST", rf"/api/projects/{PID}/sources/map", "post_native_map"),
    ("POST", rf"/api/projects/{PID}/sources/(?P<sid>SRC-\d{{1,6}})/stop", "post_native_stop"),
    ("POST", rf"/api/projects/{PID}/sources/read", "post_native_read"),
    ("POST", rf"/api/projects/{PID}/sources/use-anyway", "post_native_use_anyway"),
    ("POST", rf"/api/projects/{PID}/sources/import-results", "post_native_import"),
    ("POST", rf"/api/projects/{PID}/sources/run", "post_native_run"),
]
MAX_RESULTS = 4 * 1024 * 1024
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


class NativeSourceRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``server``, ``_project`` and ``_who``."""

    factory: Any
    server: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _own_sources(self, pid: str, body: dict[str, Any] | None = None) -> tuple[Any, str, str]:
        if pid == FACTORY_PID:
            raise _server().ApiError(404, "Rihmasto's own records have no repository of their own to read")
        project = self._project(pid)
        if body is None:
            return project, "", ""
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        return project, person, persona

    def get_native_sources(self, pid: str, **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"applies": False, "scope": native_sources.SCOPE,
                         "why": "Rihmasto's own records have no repository of their own to read"}
        return 200, native_apply.view(self._project(pid))

    def post_native_map(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project, person, persona = self._own_sources(pid, body)
        srv = _server()
        key = srv._text(body, "key", limit=300) or None
        sid = srv._text(body, "source", limit=20) or None
        spec = body.get("spec")
        if spec is not None and not isinstance(spec, dict):
            raise srv.ApiError(400, "spec is the source's settings: kind, glob, mapping, roots, every")
        if not (key or spec or sid):
            raise srv.ApiError(400, "name a detected source (key) or the source's settings (spec)")
        every = srv._text(body, "every", limit=20) or None
        return 200, native_sources.map_source(project, person=person, persona=persona, key=key, spec=spec, sid=sid,
                                              every=every)

    def post_native_stop(self, pid: str, sid: str, body: dict[str, Any], **_: Any) -> Reply:
        project, person, persona = self._own_sources(pid, body)
        reason = _server()._text(body, "reason", limit=500)
        return 200, native_sources.stop(project, sid, person=person, persona=persona, reason=reason)

    def post_native_read(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        from kernel.access import require

        project, person, persona = self._own_sources(pid, body)
        require(project, person, persona)
        if not native_sources.active(project):
            raise _server().ApiError(400, "nothing is mapped yet: map a source first, then it is read")
        got = native_sources.read(project, person=person, persona=persona, why="asked in the cockpit", fetch=True)
        return 200, native_apply.view(project) | {"fetched": got.get("fetch")}   # the upstream fetched first (FR-SRC2)

    def post_native_use_anyway(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project, person, persona = self._own_sources(pid, body)
        path = _server()._text(body, "path", required=True, limit=300)
        return 200, native_sources.use_anyway(project, path, person=person, persona=persona)

    def post_native_import(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        from kernel.access import require

        srv = _server()
        project, person, persona = self._own_sources(pid, body)
        require(project, person, persona)
        text = body.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_RESULTS:
            raise srv.ApiError(400, "text is the results file's content (JUnit XML, TAP or JSON), up to 4 MB")
        fmt = srv._text(body, "format", limit=10) or None
        root = body.get("root")
        run = native_tests.import_results(project, text, person=person, persona=persona, fmt=fmt,
                                          produced_at=srv._text(body, "produced_at", limit=40) or None,
                                          machine=srv._text(body, "machine", limit=120) or None,
                                          name=srv._text(body, "name", limit=120) or None,
                                          root=root if isinstance(root, str) else None)
        return 201, {"run": run, **native_apply.view(project)}

    def post_native_run(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        from kernel import access_isolation as kisolation

        srv = _server()
        project, person, persona = self._own_sources(pid, body)
        root = srv._text(body, "root", limit=200).strip("/")
        if root not in [r["root"] for r in native_sources.mapped_roots(project)]:
            raise srv.ApiError(400, "only a test root mapped in the project's own sources is run: map its tests first")
        if persona not in adopt_stated.RUNNERS:
            raise srv.ApiError(403, f"refused: a project's tests are run by a {', '.join(adopt_stated.RUNNERS)}")
        if body.get("confirm") is not True:
            raise srv.ApiError(400, "say yes first: " + adopt_stated.RUNS_CODE)
        kisolation.require(self.factory, kisolation.SUITE)     # it runs the project's own code
        running = self.server.running_job(pid)
        if running is not None:
            raise srv.ApiError(409, f"job {running['id']} is still running for {pid}")
        project.log("cockpit_write", {"action": "native_tests_run_requested", "target": root or ".", "person": person,
                                      "persona": persona, "confirmed": adopt_stated.RUNS_CODE})   # signed, first
        job = self.server.start_job("tests", project.pid,
                                    ["-m", "kernel.cli", "sources", "run", project.pid, root or ".", "--yes",
                                     "--person", person, "--persona", persona], {"person": person, "persona": persona})
        return 201, {"job": self.server.job_view(job)}
