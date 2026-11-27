"""The cockpit's routes for a project's Gnomon posture (kernel/gnomon_posture, FR-GNP1).

- ``GET /api/projects/<pid>/gnomon-posture?persona=``: the posture, computed now from the project's own Gnomon files
  (reading writes nothing);
- ``POST /api/projects/<pid>/gnomon-posture/propose``: a developer or IT files one suggestion as a change card.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.gnomon_posture import view as gp_view
from kernel.learn import FACTORY_PID
from kernel.people import PERSONAS

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/gnomon-posture", "get_gnomon_posture"),
    ("POST", rf"/api/projects/{PID}/gnomon-posture/propose", "post_gnomon_posture_propose"),
]
Reply = tuple[int, dict[str, Any]]


class GnomonPostureRoutes:
    """Mixed into the cockpit's Api: it has ``factory`` and ``_project`` and ``_who``."""

    factory: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def get_gnomon_posture(self, pid: str, query: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, "measured": False, "why": "the Gnomon posture is a product project's"}
        persona = str(query["persona"]) if query.get("persona") in PERSONAS else "developer"
        return 200, gp_view.build(self.factory, self._project(pid), persona=persona)

    def post_gnomon_posture_propose(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        sid = body.get("suggestion")
        if not isinstance(sid, str) or not 0 < len(sid) <= 40:
            raise ValueError("suggestion is a suggestion's id, such as GP-sandbox-exec")
        out = gp_view.propose(self.factory, project, sid.strip(), person=person, persona=persona)
        return 200, {"project": pid, "suggestion": out["suggestion"], "card": {"id": out["card"]["id"]},
                     "already": out["already"]}
