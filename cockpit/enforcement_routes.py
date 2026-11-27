"""The cockpit's routes for enforcement levels per environment (kernel/enforcement.py, D-0026, FR-ENF1, FR-ENF2).

- ``GET /api/enforcement``: the platform's levels for every environment and check family, each cell with its
  scope (platform or Rihmasto's default), the projects that set their own, and the changes made;
- ``PUT /api/enforcement``: a person sets the platform's levels (``levels``, a ``preset``, ``reviewers``), signed
  and recorded in the factory's ledger; loosening one needs a ``reason``;
- ``POST /api/enforcement/preview``: what a change would do, before it is made (``project`` for a project's own);
  it records nothing;
- ``GET /api/projects/<pid>/enforcement``: the project's levels, each cell saying whether it is the project's own,
  the platform's or the default; the guard's latest outcomes, its open review cards and its open findings; with
  ``?pipeline=1`` the project's GitHub environments and branch protection, read with ``gh`` and never written,
  and where Rihmasto and the pipeline agree or differ;
- ``PUT /api/projects/<pid>/enforcement``: a person sets the project's own levels (``inherit`` gives a cell back
  to the platform) or names its GitHub repository, signed and recorded in the project's ledger.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import enforcement as ke
from kernel import enforcement_pipeline as kpipe
from kernel.canon import Canon
from kernel.enforcement_guard import findings, recent
from kernel.enforcement_preview import preview
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", r"/api/enforcement", "get_enforcement"),
    ("PUT", r"/api/enforcement", "put_enforcement"),
    ("POST", r"/api/enforcement/preview", "post_enforcement_preview"),
    ("GET", rf"/api/projects/{PID}/enforcement", "get_project_enforcement"),
    ("PUT", rf"/api/projects/{PID}/enforcement", "put_project_enforcement"),
]
Reply = tuple[int, dict[str, Any]]


def _text(body: dict[str, Any], key: str, limit: int) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} is text of at most {limit} characters")
    return value.strip()


def _change(body: dict[str, Any]) -> dict[str, Any]:
    return {"levels": body.get("levels"), "preset": _text(body, "preset", 32) or None,
            "reviewers": body.get("reviewers"), "names": body.get("names"),
            "gate_env": _text(body, "gate_env", 16) or None}


def _cards(project: Any) -> list[dict[str, Any]]:
    return [{"id": c["id"], "title": c["title"], "deciders": c.get("deciders"), "blocking": c.get("blocking"),
             **{k: (c.get("payload") or {}).get(k) for k in ("env", "family", "level", "subject", "source")}}
            for c in Canon(project).cards(state="open", kind="enforcement")]


class EnforcementRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``_project`` and ``_who``."""

    factory: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def get_enforcement(self, **_: Any) -> Reply:
        return 200, ke.describe(self.factory)

    def put_enforcement(self, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        return 200, ke.set_levels(self.factory, None, **_change(body), person=person, persona=persona,
                                  reason=_text(body, "reason", 300) or "")

    def post_enforcement_preview(self, body: dict[str, Any], **_: Any) -> Reply:
        pid = _text(body, "project", 90) or None
        project = self._project(pid) if pid and pid != FACTORY_PID else None
        self._who(body, pid or FACTORY_PID)      # under enforced access only a granted persona sees the preview
        return 200, preview(self.factory, project, **_change(body))

    def get_project_enforcement(self, pid: str, query: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, "applies": False, "why": "levels are set for the platform and for projects"}
        project = self._project(pid)
        out = ke.describe(self.factory, project) | {
            "applies": True, "recent": recent(project), "open_cards": _cards(project), "findings": findings(project),
            "repo": ke.project_settings(project).get("repo"), "platform_levels": ke.levels_of(ke.grid(self.factory))}
        if query.get("pipeline") == "1":
            pipe = kpipe.read(project)
            out["pipeline"] = pipe
            out["compare"] = kpipe.compare(out, pipe)
        return 200, out

    def put_project_enforcement(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            raise ValueError("the platform's levels are set at /api/enforcement")
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, ke.set_levels(self.factory, project, **_change(body), person=person, persona=persona,
                                  reason=_text(body, "reason", 300) or "", repo=_text(body, "repo", 201))
