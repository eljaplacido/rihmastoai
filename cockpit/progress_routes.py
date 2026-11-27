"""The cockpit's routes for live progress (kernel/progress.py, FR-PRG1).

An assessment runs in the background and reports its plan and each step: GET .../assessment/progress answers
with what changed since a cursor (``?since=<seq>``), so the Assessment view, its Overview card and Ask Rihma
read a few events a second, not the whole job. Cancel is a signed write: the assessment stops between two
steps and records nothing; who cancelled is noted in the project's ledger. An adoption's progress is mapped
from the step lines its job prints (kernel/progress_jobs.py), on the job's own view.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kernel import progress as kprogress
from kernel import progress_jobs
from kernel.assess_progress import KIND
from kernel.learn import FACTORY_PID
from kernel.walkthrough_flows import progress_in_log

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"   # as cockpit/server.py PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/assessment/progress", "get_assessment_progress"),
    ("POST", rf"/api/projects/{PID}/assessment/cancel", "post_assessment_cancel"),
]
# A cancel only asks the running assessment to stop: it never waits behind another write.
UNLOCKED = {"post_assessment_cancel"}
ASSESS_WAIT_S = 20      # an assessment by rule answers at once when it ends within this; else it goes on behind
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def history_path(home: Path, scope: str) -> Path:
    """Where a project's (or the factory's) earlier runs are timed: beside the cockpit's own files."""
    return Path(home) / "_cockpit" / "progress" / f"{scope}.json"


def adoption_progress(state: str, log: Path) -> dict[str, Any]:
    """An adoption job's progress, from the ``adopt:`` lines of its whole log (kernel/material_cli.py)."""
    return progress_jobs.adoption(progress_in_log(log), state)


def _cursor(query: dict[str, Any]) -> int:
    raw = str(query.get("since") or "0").strip()
    return int(raw) if raw.isdigit() and len(raw) < 10 else 0


class ProgressRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``_project``, ``_who`` and ``_audit``."""

    server: Any
    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _assess_reporter(self, project: Any) -> kprogress.Reporter:
        """A new assessment's progress, timed against the project's earlier assessments and registered where
        the routes and Ask Rihma find it."""
        rep = kprogress.Reporter(KIND, f"Assessing {project.meta.get('title') or project.pid}",
                                 history=kprogress.History(history_path(self.factory.home, project.pid)),
                                 stamp=self.factory.clock.stamp)
        return kprogress.register(kprogress.key_for(project, KIND), rep)

    @staticmethod
    def _assess_progress(project: Any, cursor: int = 0) -> dict[str, Any] | None:
        rep = kprogress.live(kprogress.key_for(project, KIND))
        return rep.since(cursor) if rep is not None else None

    def get_assessment_progress(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        """The assessment's progress since ``?since=``: its events after that cursor and its state now; the
        whole plan from cursor 0. None when no assessment ran since the cockpit started."""
        return 200, {"progress": self._assess_progress(self._project(pid), _cursor(query))}

    def post_assessment_cancel(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        """Stop the running assessment at its next step, signed; nothing it did so far is recorded."""
        srv = _server()
        project = self._project(pid)
        person, persona = self._who(body, pid)
        srv._require_person(person, persona)
        rep = kprogress.live(kprogress.key_for(project, KIND))
        if rep is None or not rep.cancel({"person": person, "persona": persona}):
            return 200, {"cancelled": False, "why": f"no assessment of {pid} is running",
                         "progress": rep.since(0) if rep is not None else None}
        srv.Api._audit(project, "assess_cancel", pid, person, persona)
        return 202, {"cancelled": True, "progress": rep.since(0)}


__all__ = ["ASSESS_WAIT_S", "ROUTES", "UNLOCKED", "ProgressRoutes", "adoption_progress", "history_path"]
