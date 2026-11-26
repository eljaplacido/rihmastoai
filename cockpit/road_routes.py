"""The cockpit's routes for the paved roads and the integration kinds (kernel/road_settings.py, FR-GCP1, FR-GDR1).

Settings shows every road, ready or what is missing, and lets IT configure a Google Cloud road; a project's
Releases view shows where each environment of its plan deploys and lets IT choose the road, the workload and
the schedule; Settings' Integrations card shows the kinds of systems a capability can reach, the Google
Drive connector among them. Every write is signed by a person and persona as the other write routes are
(with access enforced, IT's persona granted on the factory or the project) and recorded by the kernel.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import road_settings
from kernel.learn import FACTORY_PID

ROAD = r"(?P<road>[a-z0-9][a-z0-9-]{1,40})"
PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"   # as cockpit/server.py PID
ROUTES = [
    ("GET", r"/api/roads", "get_roads"),
    ("PUT", rf"/api/roads/{ROAD}", "put_road"),
    ("GET", rf"/api/projects/{PID}/roads", "get_project_roads"),
    ("PUT", rf"/api/projects/{PID}/road", "put_project_road"),
    ("GET", r"/api/integration-kinds", "get_integration_kinds"),
]
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


def _object(body: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = body.get(key)
    if value is not None and not isinstance(value, dict):
        raise _error(400, f"{key} is an object")
    return value


class RoadRoutes:
    """Mixed into the cockpit's Api: it has ``factory`` and ``_who``."""

    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _road_project(self, pid: str) -> Any:
        try:
            return self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None

    def get_roads(self, **_: object) -> Reply:
        return 200, road_settings.roads_view(self.factory)

    def put_road(self, road: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        entry = _object(body, "road")
        if entry is None:
            raise _error(400, "road is the road's entry, an object")
        maturity = body.get("maturity") or []
        if not isinstance(maturity, list):
            raise _error(400, "maturity is a list of maturities this road serves")
        row = road_settings.configure(self.factory, road, entry, person=person, persona=persona,
                                      maturity={str(m): road for m in maturity})
        return 200, {"road": row}

    def get_project_roads(self, pid: str, **_: object) -> Reply:
        return 200, road_settings.project_view(self._road_project(pid))

    def put_project_road(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._road_project(pid)
        person, persona = self._who(body, pid)
        road = str(body.get("road") or "").strip()
        if not road:
            raise _error(400, "road names the paved road")
        workload = body.get("workload")
        if workload is not None and not isinstance(workload, str):
            raise _error(400, "workload is service or job")
        view = road_settings.choose(project, road, person=person, persona=persona, workload=workload,
                                    schedule=_object(body, "schedule"), job=_object(body, "job"))
        return 200, view

    def get_integration_kinds(self, **_: object) -> Reply:
        from kernel import connectors_gdrive
        from kernel.integration_decl import kinds

        return 200, {"kinds": kinds(), "gdrive": {
            "scopes": {k: list(v) for k, v in connectors_gdrive.SCOPES.items()},
            "credentials": ["<NAME>_TOKEN: an OAuth access token, for a local run",
                            "<NAME>_KEY_FILE: the path of a service account's JSON key",
                            "neither: the runtime service account through the metadata server (Cloud Run)"],
            "settings": ["<NAME>_URL (https://www.googleapis.com)", "<NAME>_ACCESS (read or read-write)"],
            "client": "app/gdrive.py", "guide": "docs/guides/gcp.md"}}
