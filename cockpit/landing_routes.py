"""The cockpit's routes for a clear landing and live tasks (FR-LND1).

Reads write nothing:

- ``GET /api/projects/<pid>/start-here``: what Rihmasto understood the project to be, the one to three steps to take
  now and what runs on its own meanwhile, for the person reading (whether they hid it) (kernel/start_here.py);
- ``GET /api/projects/<pid>/tasks``: every task with its status and source, and a signature that changes when one
  does, for the list's filters and its live updates (kernel/task_detail.py ``rows``);
- ``GET /api/projects/<pid>/task?id=T-001``: one task's panel: criteria, tests and their last results, commits,
  agent sessions, status history and actions (``detail``);
- ``GET /api/run-log?job=J-..&from=N`` the whole log of a background job from byte N, ``?project=<pid>&from=N`` the
  running cell's steps from step N, and with neither the runs to open a log of (Activity); a finished job says what
  it changed (kernel/run_log.py).
- ``GET /api/projects/<pid>/wip``: its work in progress, what its working copy holds uncommitted, by kind and area,
  or "not measured" with why (kernel/wip.py, FR-WIP1); nothing is written to the repository.

Writes are signed by a person and persona (with access enforced, one granted where it acts) and recorded:

- ``POST /api/projects/<pid>/start-here``: hide the panel for this person (``hide``: true) or show it again;
- ``POST /api/projects/<pid>/tasks/<tid>/start``, ``.../done`` (with ``evidence``) and ``.../handoff`` (``to``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel import run_log, start_here, task_detail, wip
from kernel.people import is_person

PID = r"(?P<pid>_factory|[a-z0-9][a-z0-9-]{0,80})"
TID = r"(?P<tid>[A-Za-z0-9][A-Za-z0-9_-]{0,39})"
ROUTES = [
    ("GET", rf"/api/projects/{PID}/start-here", "get_start_here"),
    ("POST", rf"/api/projects/{PID}/start-here", "post_start_here"),
    ("GET", rf"/api/projects/{PID}/tasks", "get_task_rows"),
    ("GET", rf"/api/projects/{PID}/task", "get_task_detail"),
    ("POST", rf"/api/projects/{PID}/tasks/{TID}/start", "post_task_start"),
    ("POST", rf"/api/projects/{PID}/tasks/{TID}/done", "post_task_done"),
    ("POST", rf"/api/projects/{PID}/tasks/{TID}/handoff", "post_task_handoff"),
    ("GET", r"/api/run-log", "get_run_log"),
    ("GET", rf"/api/projects/{PID}/wip", "get_wip"),   # work in progress (FR-WIP1)
]
Reply = tuple[int, dict[str, Any]]
RECENT = 20


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


def _offset(query: dict[str, Any], default: int) -> int:
    try:
        return int(str(query.get("from") or default))
    except ValueError:
        raise _error(400, "from is a whole number: the offset to read on from") from None


class LandingRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``identity``, ``_who`` and ``_project``."""

    server: Any
    factory: Any
    identity: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _signer(self, body: dict[str, Any], pid: str) -> tuple[str, str]:
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        return person, persona

    def _reader(self, query: dict[str, Any]) -> str | None:
        name = self.identity.name if self.identity is not None else str(query.get("person") or "").strip()[:200]
        return name if name and is_person(name) else None

    def _jobs(self, pid: str | None = None) -> list[dict[str, Any]]:
        with self.server._jobs_lock:
            jobs = list(self.server.jobs)
        return [self.server.job_view(j) | {"_raw": j} for j in jobs if pid is None or j["project"] == pid]

    # reads

    def get_start_here(self, pid: str, query: dict[str, Any] | None = None, **_: object) -> Reply:
        project = self._project(pid)
        jobs = [{k: v for k, v in j.items() if k != "_raw"} for j in self._jobs(pid)] if pid != "_factory" else []
        return 200, start_here.panel(project, person=self._reader(query or {}), jobs=jobs)

    def get_wip(self, pid: str, query: dict[str, Any] | None = None, **_: object) -> Reply:
        fresh = str((query or {}).get("fresh") or "") in ("1", "true")    # Refresh: read again, not the cached one
        return 200, wip.read(self._project(pid), fresh=fresh)

    def get_task_rows(self, pid: str, **_: object) -> Reply:
        return 200, task_detail.rows(self._project(pid))

    def get_task_detail(self, pid: str, query: dict[str, Any] | None = None, **_: object) -> Reply:
        project = self._project(pid)
        tid = str((query or {}).get("id") or "")[:40]
        if not tid:
            return 200, {"project": pid, "task": None, "why": "name a task: ?id=T-001; the list is at "
                                                             f"/api/projects/{pid}/tasks"}
        try:
            return 200, task_detail.detail(project, tid) | {"found": True}
        except task_detail.TaskRefused as exc:
            if exc.status != 404:
                raise _error(exc.status, str(exc)) from None
            return 200, {"project": pid, "id": tid, "found": False,
                         "why": f"{exc}: it was renamed or removed when the contract changed, or the link names "
                                "another project's task; Tasks lists this project's tasks"}

    def get_run_log(self, query: dict[str, Any] | None = None, **_: object) -> Reply:
        q = query or {}
        jid, pid = str(q.get("job") or "")[:40], str(q.get("project") or "")[:100]
        if jid:
            return 200, self._job_log(jid, _offset(q, -1))
        if pid:
            project = self._project(pid)
            return 200, {"project": pid, "kind": "cell", **run_log.cell_steps(project, max(0, _offset(q, 0)))}
        return 200, {"runs": self._runs()}

    def _job_log(self, jid: str, start: int) -> dict[str, Any]:
        job = next((j for j in self._jobs() if j["id"] == jid), None)
        if job is None:
            raise _error(404, f"no job {jid} in this session: jobs are kept while the cockpit runs; the Jobs page "
                              "lists them")
        raw = job.pop("_raw")
        out = {"job": {k: v for k, v in job.items() if k not in ("log_tail", "args")}, "kind": "job",
               **run_log.job_text(Path(raw["log"]), start)}
        # what it changed: from its start to its end, in the project it ran for or, for an adoption, made (FR-LND2)
        where = job.get("made") or job["project"]
        if job["state"] != "running" and where and not str(where).startswith("_"):
            try:
                out["changed"] = run_log.changed(self._project(where), job.get("started"), job.get("ended"))
                out["changed_in"] = where
            except Exception:  # noqa: BLE001 - a project gone since: the log still opens
                out["changed"] = []
        return out

    def _runs(self) -> list[dict[str, Any]]:
        """The runs to open a log of, newest first: the cockpit's jobs, then the cells building a task now."""
        out = [{"kind": "job", "id": j["id"], "title": j.get("title") or f"{j['kind']} {j['project']}",
                "project": j["project"], "state": j["state"], "started": j.get("started"),
                "open": f"#/jobs/{j['id']}"} for j in self._jobs()][::-1][:RECENT]
        from kernel import status as kstatus

        for p in self.factory.projects():
            try:
                lv = kstatus.live(p)
            except (OSError, ValueError):
                continue
            if lv.get("running") and not lv.get("ended"):
                out.insert(0, {"kind": "cell", "id": f"cell:{p.pid}", "title": f"Building {lv.get('task')}",
                               "project": p.pid, "state": "running", "started": None, "open": f"#/jobs/cell:{p.pid}"})
        return out

    # writes

    def post_start_here(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        if pid == "_factory":
            raise _error(400, "Start here is a project's: open a project")
        person, persona = self._signer(body, pid)
        hide = body.get("hide")
        if not isinstance(hide, bool):
            raise _error(400, "hide is true (hide it for you) or false (show it again)")
        try:
            return 200, start_here.choose(project, person=person, persona=persona, hide=hide)
        except start_here.StartHereRefused as exc:
            raise _error(403, str(exc)) from None

    def _task_write(self, pid: str, body: dict[str, Any], run: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._signer(body, pid)
        try:
            return 200, run(project, person, persona)
        except task_detail.TaskRefused as exc:
            raise _error(exc.status, str(exc)) from None

    def post_task_start(self, pid: str, tid: str, body: dict[str, Any], **_: object) -> Reply:
        note = _server()._text(body, "note", limit=500)
        return self._task_write(pid, body, lambda p, who, as_: task_detail.start(p, tid, person=who, persona=as_,
                                                                                    note=note))

    def post_task_done(self, pid: str, tid: str, body: dict[str, Any], **_: object) -> Reply:
        evidence = _server()._text(body, "evidence", limit=task_detail.MAX_EVIDENCE)
        return self._task_write(pid, body, lambda p, who, as_: task_detail.mark_done(p, tid, person=who, persona=as_,
                                                                                        evidence=evidence))

    def post_task_handoff(self, pid: str, tid: str, body: dict[str, Any], **_: object) -> Reply:
        to = _server()._text(body, "to", limit=16) or "generic"
        via = _server()._text(body, "via", limit=16) or "copy"
        return self._task_write(pid, body, lambda p, who, as_: task_detail.handoff(p, tid, to=to, via=via, person=who,
                                                                                      persona=as_))
