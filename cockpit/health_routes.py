"""The cockpit's routes for checks and Health (kernel/checks/, FR-CHK1), and the ticker that runs checks on
their schedule while the cockpit runs.

Enabling, disabling and Run now are signed by a person and persona (with access enforced, granted on each
project they touch). Run now answers with the result once the check has run; it runs outside the write lock,
since a check keeps its records under their own file locks, and a test suite may take minutes. The ticker is
a thread started only by ``python -m cockpit.server``: once a minute it runs the checks that are due, each with
the rights of the person who enabled it (kernel/checks/store.py). ``rihmasto checks tick`` does the same from
cron or Windows Task Scheduler.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any
from urllib.parse import unquote

from cockpit.console_routes import PID
from cockpit.shape_routes import _error
from kernel import access_isolation as kisolation
from kernel.checks import health as chealth
from kernel.checks import store as cstore

KEY = r"(?P<key>[a-z_]{2,20}(?::|%3[Aa])?[a-z0-9-]{0,31})"
ROUTES = [
    ("GET", r"/api/checks", "get_checks_health"),
    ("GET", rf"/api/projects/{PID}/checks", "get_project_checks"),
    ("POST", rf"/api/projects/{PID}/checks/{KEY}/enable", "post_check_enable"),
    ("POST", rf"/api/projects/{PID}/checks/{KEY}/disable", "post_check_disable"),
    ("POST", rf"/api/projects/{PID}/checks/{KEY}/run", "post_check_run"),
    ("POST", r"/api/checks/enable", "post_checks_enable"),
]
UNLOCKED = {"post_check_run"}
TICK_EVERY = 60.0
Reply = tuple[int, dict[str, Any]]


class Ticker:
    """Runs the checks that are due, once a minute, in a background thread."""

    def __init__(self, factory: Any, *, every: float = TICK_EVERY) -> None:
        self.factory, self.every = factory, float(every)
        self.last: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="checks", daemon=True)

    def start(self) -> Ticker:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                with kisolation.serving(self.factory):
                    self.last = cstore.tick(self.factory)
            except Exception:  # one bad tick is printed, never the end of the ticker
                traceback.print_exc()
            self._stop.wait(self.every)


def serve_here(server: Any, factory: Any) -> None:
    """What only a cockpit started from the command line does (``python -m cockpit.server``): open a terminal
    on this machine (kernel/console_term.py), and run checks on their schedule."""
    from kernel import console_term

    server.terminal_launcher = console_term.launch
    server.checks_ticker = Ticker(factory).start()


class HealthRoutes:
    """Mixed into the cockpit's Api: it has ``factory`` and ``_who``."""

    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _health_project(self, pid: str) -> Any:
        try:
            return self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None

    def get_checks_health(self, **_: object) -> Reply:
        """Every project's enabled checks, their last results and trends, and the catalogue; reads only."""
        return 200, chealth.factory_health(self.factory)

    def get_project_checks(self, pid: str, **_: object) -> Reply:
        return 200, chealth.project_health(self._health_project(pid))

    @staticmethod
    def _enabling(body: dict[str, Any]) -> dict[str, Any]:
        on_fail = body.get("on_fail")
        every = body.get("every")
        if every is not None and not isinstance(every, str):
            raise _error(400, "every is 15m, 6h or 1d")
        return {"config": body.get("config"), "every": every or None,
                "on_fail": on_fail if isinstance(on_fail, list) or on_fail is None else [on_fail]}

    def post_check_enable(self, pid: str, key: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._health_project(pid)
        person, persona = self._who(body, pid)
        out = cstore.enable(project, unquote(key), person=person, persona=persona, **self._enabling(body))
        return 200, {"enabled": out, "health": chealth.project_health(project)}

    def post_check_disable(self, pid: str, key: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._health_project(pid)
        person, persona = self._who(body, pid)
        out = cstore.disable(project, unquote(key), person=person, persona=persona)
        return 200, {"disabled": out, "health": chealth.project_health(project)}

    def post_check_run(self, pid: str, key: str, body: dict[str, Any], **_: object) -> Reply:
        """Run now: the result, recorded, once the check has run."""
        project = self._health_project(pid)
        person, persona = self._who(body, pid)
        row = cstore.run(project, unquote(key), person=person, persona=persona, via="cockpit")
        return 200, {"result": row, "health": chealth.project_health(project)}

    def post_checks_enable(self, body: dict[str, Any], **_: object) -> Reply:
        """Enable one check on several projects at once, signed on each."""
        key = str(body.get("check") or "")
        pids = body.get("projects")
        if not isinstance(pids, list) or not pids or not all(isinstance(p, str) for p in pids):
            raise _error(400, "projects is a list of project ids")
        projects = [self._health_project(p) for p in pids]
        person, persona = self._who(body, projects[0].pid)
        for project in projects:                  # every one checked before any is written
            cstore.sign_on(project, person, persona)
            cstore.may(project, key, person, persona)
        how = self._enabling(body)
        out = [{"project": p.pid, **cstore.enable(p, key, person=person, persona=persona, **how)} for p in projects]
        return 200, {"enabled": out}
