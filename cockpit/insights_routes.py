"""The cockpit's routes for Insights (kernel/insights, FR-INS1). Reads only: nothing here writes a record.

- ``GET /api/insights?dimension=&window=&project=``: one dimension's read model, for the factory or a project;
- ``GET /api/insights/tile?dimension=&key=&window=&project=``: one tile, for a widget pinned on Home (with no
  key, the tiles of the dimension that can be pinned);
- ``GET /api/insights/export?format=json|csv|otlp-json&dimension=&window=&project=``: the export as text, which
  the page saves as a file. Nothing is sent anywhere (D-0017).
"""

from __future__ import annotations

import re
from typing import Any

from kernel import insights as kinsights
from kernel.insights.export import FORMATS, export

ROUTES = [
    ("GET", r"/api/insights", "get_insights"),
    ("GET", r"/api/insights/tile", "get_insights_tile"),
    ("GET", r"/api/insights/export", "get_insights_export"),
]
PID = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")
EXTENSION = {"json": "json", "csv": "csv", "otlp-json": "otlp.json"}
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


def _args(query: dict[str, Any]) -> tuple[str | None, str | None, str]:
    dimension = query.get("dimension") or None
    if dimension is not None and dimension not in kinsights.DIMENSIONS:
        raise _error(400, f"dimension is one of {', '.join(kinsights.DIMENSIONS)}")
    window = query.get("window") or "7d"
    if window not in kinsights.WINDOWS:
        raise _error(400, f"window is one of {', '.join(kinsights.WINDOWS)}")
    return dimension, query.get("project") or None, window


class InsightsRoutes:
    """Mixed into the cockpit's Api: it has ``factory``."""

    factory: Any

    def _insights_pid(self, pid: str | None) -> str | None:
        """A product's id as the routes name one; Rihma's own canon and anything else is not a project here."""
        if pid is None:
            return None
        if not PID.fullmatch(pid) or not (self.factory.projects_dir / pid / "project.json").exists():
            raise _error(404, f"no project {pid[:80]}")
        return pid

    @staticmethod
    def insights_pins() -> dict[str, Any]:
        """The Insight widget's part of GET /api/dashboard: where a pinned tile reads its figure. A pinned tile is
        read by itself (GET /api/insights/tile), so the dashboard never reads seven dimensions it may not show."""
        return {"tile": "/api/insights/tile", "page": "#/insights", "dimensions": list(kinsights.DIMENSIONS),
                "windows": list(kinsights.WINDOWS)}

    def get_insights(self, query: dict[str, Any], **_: Any) -> Reply:
        dimension, pid, window = _args(query)
        model = kinsights.read(self.factory, dimension or "health", pid=self._insights_pid(pid), window=window)
        return 200, model | {"dimensions": [{"id": d, "label": kinsights.LABELS[d]} for d in kinsights.DIMENSIONS],
                             "windows": list(kinsights.WINDOWS)}

    def get_insights_tile(self, query: dict[str, Any], **_: Any) -> Reply:
        dimension, pid, window = _args(query)
        key = str(query.get("key") or "")
        if not key:     # no tile named: the tiles of the dimension that can be pinned
            model = kinsights.read(self.factory, dimension or "health", pid=self._insights_pid(pid), window=window)
            return 200, {"dimension": model["dimension"], "pinnable": [{"key": t["key"], "label": t["label"]}
                                                                        for t in model["tiles"]]}
        if dimension is None:
            raise _error(400, "a tile is named by its dimension and key")
        try:
            return 200, kinsights.tile_of(self.factory, dimension, key, pid=self._insights_pid(pid), window=window)
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None

    def get_insights_export(self, query: dict[str, Any], **_: Any) -> Reply:
        dimension, pid, window = _args(query)
        fmt = query.get("format") or "json"
        if fmt not in FORMATS:
            raise _error(400, f"format is one of {', '.join(FORMATS)}")
        text = export(self.factory, fmt, dimension=dimension, pid=self._insights_pid(pid), window=window)
        name = f"rihmasto-insights-{pid or 'factory'}-{dimension or 'all'}-{window}.{EXTENSION[fmt]}"
        return 200, {"format": fmt, "filename": name, "text": text,
                     "media_type": "text/csv" if fmt == "csv" else "application/json"}
