"""The cockpit's routes for Rihmasto's structure and where the work went (kernel/structure_policy.py,
kernel/work_balance.py, FR-STR1).

- ``GET /api/structure``: the platform's level of each convention for each kind of project (its own structure, or
  built by Rihmasto), each saying whether it is the platform's or Rihmasto's default, and the changes made;
- ``PUT /api/structure``: a person sets the platform's levels for a kind of project, signed with their reason and
  recorded in the factory's ledger;
- ``POST /api/structure/preview``: what a change would do before it is made (``project`` for a project's own); it
  records nothing;
- ``GET /api/projects/<pid>/structure``: the project's level of each convention, with the platform's beside it,
  where each comes from, the reason recorded and what it finds open now;
- ``PUT /api/projects/<pid>/structure``: a person sets the project's own levels (``inherit`` gives a convention back
  to the platform), signed with their reason; the project's Inbox cards follow;
- ``GET /api/work-balance?project=&window=``: of the decisions and changes in a window, what moved development and
  what conformed to Rihmasto's structure, with the items behind each bar. It records nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import structure_policy as sp
from kernel import work_balance as wb
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", r"/api/structure", "get_structure"),
    ("PUT", r"/api/structure", "put_structure"),
    ("POST", r"/api/structure/preview", "post_structure_preview"),
    ("GET", rf"/api/projects/{PID}/structure", "get_project_structure"),
    ("PUT", rf"/api/projects/{PID}/structure", "put_project_structure"),
    ("GET", r"/api/work-balance", "get_work_balance"),
]
Reply = tuple[int, dict[str, Any]]
_PID = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")


def _text(body: dict[str, Any], key: str, limit: int) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} is text of at most {limit} characters")
    return value.strip()


class StructureRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``_project`` and ``_who``."""

    factory: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def get_structure(self, **_: Any) -> Reply:
        return 200, sp.describe(self.factory)

    def put_structure(self, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        return 200, sp.set_levels(self.factory, None, body.get("levels"), person=person, persona=persona,
                                  reason=_text(body, "reason", 300) or "", kind=_text(body, "kind", 16) or "own")

    def post_structure_preview(self, body: dict[str, Any], **_: Any) -> Reply:
        pid = _text(body, "project", 90) or None
        project = self._project(pid) if pid and pid != FACTORY_PID else None
        self._who(body, pid or FACTORY_PID)      # under enforced access only a granted persona sees the preview
        return 200, sp.preview(self.factory, project, body.get("levels"), kind=_text(body, "kind", 16) or "own")

    def get_project_structure(self, pid: str, **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, "applies": False, "why": "Rihmasto's own records follow its own structure"}
        return 200, {"applies": True, **sp.describe(self.factory, self._project(pid))}

    def put_project_structure(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            raise ValueError("the platform's levels are set at /api/structure")
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, sp.set_levels(self.factory, project, body.get("levels"), person=person, persona=persona,
                                  reason=_text(body, "reason", 300) or "")

    def get_work_balance(self, query: dict[str, Any], **_: Any) -> Reply:
        pid = query.get("project") or None
        if pid is not None and (not _PID.fullmatch(pid) or not (self.factory.projects_dir / pid / "project.json")
                                .exists()):
            from cockpit import server

            raise server.ApiError(404, f"no project {str(pid)[:80]}")
        window = query.get("window") or "30d"
        return 200, wb.read(self.factory, pid=pid, window=window)
