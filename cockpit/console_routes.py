"""The cockpit's routes for the console and "Open a terminal here" (kernel/console.py, FR-CON1).

A run is signed by a person and a persona the project's console allows (with access enforced, granted on the
project too), starts as a job and answers at once (201); its output is read back line by line from the job's
log (``GET .../console/output?job=<job>&offset=N``) until it ends, and Stop ends it and every process it started.
The ledger has the cockpit's write at once and ``console_ran`` at the end, signed with the verified identity.

"Open a terminal here" opens the operating system's terminal on the machine the cockpit runs on, so it is
taken only from the cockpit's own loopback address: a request through a public origin (``--public-origin``,
IT's proxy) is refused with why. A server made in a test opens nothing unless the test gives it a launcher.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cockpit.shape_routes import _error, _server
from kernel import console as kconsole
from kernel import console_run as crun
from kernel import console_term
from kernel.learn import FACTORY_PID

JID = r"(?P<jid>C-\d{4,9}-[0-9a-f]{4})"
PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"   # cockpit/server.py PID, the same
_JOB = re.compile(r"C-\d{4,9}-[0-9a-f]{4}\Z")
ROUTES = [
    ("GET", rf"/api/projects/{PID}/console", "get_console"),
    ("GET", rf"/api/projects/{PID}/console/output", "get_console_output"),
    ("POST", rf"/api/projects/{PID}/console/run", "post_console_run"),
    ("POST", rf"/api/projects/{PID}/console/runs/{JID}/stop", "post_console_stop"),
    ("POST", rf"/api/projects/{PID}/console/terminal", "post_console_terminal"),
    ("PUT", rf"/api/projects/{PID}/console/settings", "put_console_settings"),
]
# A run clones the working copy at first and opens a terminal: outside the write lock (records are locked).
UNLOCKED = {"post_console_run", "post_console_terminal"}
RECENT = 15
NOT_HERE = ("Open a terminal here works on the machine the cockpit runs on, from its own address "
            "(http://127.0.0.1:<port>): this request came through {origin}. Open a terminal on that machine "
            "yourself, or run `rihmasto shell {pid}` there.")
Reply = tuple[int, dict[str, Any]]


class ConsoleRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``identity``, ``_who`` and ``_audit``."""

    server: Any
    factory: Any
    identity: Any
    request_origin: str = ""

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _console_project(self, pid: str) -> Any:
        try:
            return self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None

    def _console_jobs(self) -> Any:
        return getattr(self.server, "console_jobs", None) or crun.JOBS

    def _console_runs(self, pid: str) -> list[dict[str, Any]]:
        with self.server._jobs_lock:
            jobs = [j for j in self.server.jobs if j["project"] == pid and j["kind"] == "console"]
        return [self.server.job_view(j) | {"what": j.get("what")} for j in jobs[-RECENT:]][::-1]

    def _terminal(self) -> dict[str, Any]:
        if self.request_origin and self.request_origin != self.server.origin:
            return {"available": False, "why": "this page came through a public origin, not the cockpit's own "
                                               "loopback address"}
        launcher = getattr(self.server, "terminal_launcher", None)
        if launcher is None:
            return {"available": False, "why": "this cockpit was not started from the command line"}
        missing = console_term.missing_terminal(launcher)
        if missing:
            return {"available": False, "why": missing}
        return {"available": True, "why": None}

    def get_console(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        """The workspace, who may run, the offered commands and the recent runs; reads only."""
        project = self._console_project(pid)
        person = str(query.get("person") or "") or None
        from kernel.model import gnomon_cmd

        return 200, {"workspace": kconsole.workspace(project, person), "settings": kconsole.settings(project),
                     "offers": kconsole.offered(project, person), "runs": self._console_runs(pid),
                     "terminal": self._terminal(), "gnomon": " ".join(gnomon_cmd()[:1]),
                     "limits": {"timeout": kconsole.DEFAULT_TIMEOUT, "max": kconsole.MAX_TIMEOUT}}

    def _job(self, pid: str, jid: str) -> dict[str, Any]:
        with self.server._jobs_lock:
            job = next((j for j in self.server.jobs if j["id"] == jid and j["project"] == pid), None)
        if job is None:
            raise _error(404, f"no console run {jid} on {pid}")
        return job

    def get_console_output(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        """A run's output from ``offset`` (whole lines while it runs), and its state: the run ``job`` names,
        else the project's latest."""
        self._console_project(pid)
        jid = str(query.get("job") or "")
        if jid and not _JOB.match(jid):
            raise _error(400, "job is a console run's id (C-0001-abcd)")
        if not jid:
            with self.server._jobs_lock:
                latest = [j["id"] for j in self.server.jobs if j["project"] == pid and j["kind"] == "console"]
            if not latest:
                return 200, {"job": None, "text": "", "offset": 0, "ended": True}
            jid = latest[-1]
        job = self._job(pid, jid)
        view = self.server.job_view(job)
        ended = view["state"] in crun.ENDED
        offset = int(query["offset"]) if str(query.get("offset") or "").isdigit() else 0
        text, nxt = crun.read_log(Path(job["log"]), offset, ended=ended)
        return 200, {"job": view, "text": text, "offset": nxt, "ended": ended}

    def post_console_run(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        """Start a command line, or a Gnomon task, as a job in the project's workspace."""
        project = self._console_project(pid)
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        request = {"line": body.get("line"), "shell": body.get("shell") is True, "gnomon": body.get("gnomon"),
                   "role": body.get("role"), "yes": body.get("yes") is True}
        ident = self.identity

        def signed(write: Any) -> None:
            from kernel import access as kaccess

            with kaccess.signing(ident):
                write()

        started = kconsole.start(project, request, person=person, persona=persona, on_end=signed,
                                 timeout=body.get("timeout"), jobs=self._console_jobs())
        job = {"id": started["id"], "kind": "console", "project": pid, "args": [started["display"]],
               "log": str(started["log"]), "started": self.factory.clock.stamp(),
               "by": {"person": person, "persona": persona}, "runner": self._console_jobs(), "what": started["kind"]}
        with self.server._jobs_lock:
            self.server.jobs.append(job)
        project.log("cockpit_write", {"action": "console_run", "target": started["display"], "person": person,
                                      "persona": persona, "job": started["id"], "workspace": started["workspace"]})
        return 201, {"job": self.server.job_view(job) | {"what": started["kind"]}, "timeout": started["timeout"],
                     "isolated": started["isolated"]}

    def post_console_stop(self, pid: str, jid: str, body: dict[str, Any], **_: object) -> Reply:
        """Stop a run and every process it started; answers once it has ended (up to 10 s)."""
        project = self._console_project(pid)
        job = self._job(pid, jid)
        person, persona = self._who(body, pid)
        kconsole.check_persona(project, person, persona)
        jobs = job.get("runner") or self._console_jobs()
        stopped = jobs.stop(jid)
        if stopped:
            jobs.wait(jid, 10)
        project.log("cockpit_write", {"action": "console_stop", "target": jid, "person": person, "persona": persona,
                                      "stopped": stopped})
        return 200, {"stopped": stopped, "job": self.server.job_view(job)}

    def post_console_terminal(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        """Open the operating system's terminal in the workspace, from the cockpit's own loopback address only."""
        project = self._console_project(pid)
        person, persona = self._who(body, pid)
        if self.request_origin and self.request_origin != self.server.origin:
            raise _error(403, NOT_HERE.format(origin=re.sub(r"[^\w:/.\-]", "", self.request_origin)[:100], pid=pid))
        launcher = getattr(self.server, "terminal_launcher", None)
        if launcher is None:
            raise _error(409, f"this cockpit was not started from the command line, so it opens no terminal: run "
                              f"`rihmasto shell {pid}` on its machine")
        out = console_term.open_terminal(project, person=person, persona=persona, launcher=launcher)
        return 200, out

    def put_console_settings(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        """IT sets who may use the console; developers, IT and product owners state the project's commands."""
        project = self._console_project(pid)
        person, persona = self._who(body, pid)
        personas = body.get("personas")
        if personas is not None and (not isinstance(personas, list) or not all(isinstance(p, str) for p in personas)):
            raise _error(400, "personas is a list of personas")
        out = kconsole.set_settings(project, person=person, persona=persona, personas=personas,
                                    commands=body.get("commands"))
        return 200, {"settings": out}
