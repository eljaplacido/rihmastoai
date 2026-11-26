"""The cockpit's routes for the Knowledge graph (kernel/graph_view.py, FR-GRV1).

- ``GET /api/projects/<pid>/graph?kinds=&rels=&states=&window=&q=&focus=&hops=&issues=&limit=&audience=``: one
  project's graph, filtered. With access enforced, only for an identity that holds a persona on the project.
- ``GET /api/graph?projects=a,b&...``: every project's graph in one view (with access enforced, only the projects
  the identity holds a persona on).
- ``GET /api/graph/prefs?person=&scope=<pid or *>``: a person's saved graph views for a project (or for the page
  across projects) and the mode they open in; the defaults when nothing is saved.
- ``PUT /api/graph/prefs``: save them (``presets``: at most MAX_PRESETS named filter queries; ``mode``: graph,
  table or auto), or ``reset`` them to the defaults. Signed by a named person, kept in the cockpit's own folder
  (``_cockpit/graph_views/``) as a layout is, and never in any project's ledger: a view is a preference, not a record.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from kernel import graph_view as kview
from kernel.store import read_json, write_json

PID = r"(?P<pid>_factory|[a-z0-9][a-z0-9-]{0,80})"
ROUTES = [
    ("GET", r"/api/graph", "get_graph"),
    ("GET", r"/api/graph/prefs", "get_graph_prefs"),
    ("PUT", r"/api/graph/prefs", "put_graph_prefs"),
    ("GET", r"/api/projects/" + PID + r"/graph", "get_project_graph"),
]
# The Knowledge graph widget a person pins to Home (cockpit/server.py WIDGETS): a slice, read by itself.
WIDGET = ("Knowledge graph", "graph",
          "A slice of a project's knowledge graph: what traces to what, and what has no test?")
MODES = ("auto", "graph", "table")
MAX_PRESETS, MAX_NAME, MAX_QUERY = 20, 60, 600
ALL = "*"
DEFAULT = {"mode": "auto", "presets": [], "default_preset": None}
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


def _text(body: dict[str, Any], key: str, limit: int) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise _error(400, f"{key} is text of at most {limit} characters")
    return value.strip()


def check_presets(raw: Any) -> list[dict[str, str]]:
    """Saved views as sent: a list of {name, query}, each query a filter query the read model takes."""
    if not isinstance(raw, list) or len(raw) > MAX_PRESETS:
        raise _error(400, f"presets is a list of at most {MAX_PRESETS} saved views")
    out: list[dict[str, str]] = []
    for p in raw:
        if not isinstance(p, dict):
            raise _error(400, "each saved view is an object with a name and a query")
        name, query = _text(p, "name", MAX_NAME), _text(p, "query", MAX_QUERY).lstrip("?")
        if not name or name in {x["name"] for x in out}:
            raise _error(400, "each saved view has a name of its own")
        try:
            kview.parse_filters(dict(parse_qsl(query)))
        except ValueError as exc:
            raise _error(400, f"saved view {name!r}: {exc}") from None
        out.append({"name": name, "query": query})
    return out


class GraphRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``server``, ``access`` and ``identity``."""

    factory: Any
    server: Any
    access: Any
    identity: Any

    def _sign(self, person: str, persona: str, pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _stamp(self) -> str:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _graph_visible(self) -> Callable[[str], bool] | None:
        """With access enforced, the projects the verified identity holds a persona on; else every project."""
        if not self.access.enforced or self.identity is None:
            return None
        from kernel import access as kaccess

        return lambda pid: bool(kaccess.personas(self.access, self.identity, pid))

    def _graph_project(self, pid: str) -> Any:
        try:
            project = self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None
        visible = self._graph_visible()
        if visible is not None and not visible(pid):
            raise _error(403, f"refused: {self.identity.name} holds no persona on {pid}, so its graph is not shown")
        return project

    @staticmethod
    def graph_pins() -> dict[str, Any]:
        """The Knowledge graph widget's part of GET /api/dashboard: where a pinned slice reads itself, so the
        dashboard never builds a graph it may not show."""
        return {"project": "/api/projects/<pid>/graph", "factory": "/api/graph", "page": "#/graph"}

    def get_project_graph(self, pid: str, query: dict[str, Any], **_: Any) -> Reply:
        project = self._graph_project(pid)
        return 200, kview.project_view(project, kview.parse_filters(query))

    def get_graph(self, query: dict[str, Any], **_: Any) -> Reply:
        return 200, kview.factory_view(self.factory, kview.parse_filters(query), visible=self._graph_visible())

    # -- saved views: per person, in the cockpit's own folder ------------------------------------------------

    def _prefs_path(self, person: str) -> Path:
        key = hashlib.sha256(person.strip().encode("utf-8")).hexdigest()[:20]
        return Path(self.server.layouts_dir).parent / "graph_views" / f"{key}.json"

    def _scope(self, raw: Any) -> str:
        scope = str(raw or ALL)
        if scope != ALL and not re.fullmatch(PID[8:-1], scope):
            raise _error(400, "scope is a project id, or * for the page across projects")
        if scope != ALL:
            self._graph_project(scope)
        return scope

    def get_graph_prefs(self, query: dict[str, Any], **_: Any) -> Reply:
        scope = self._scope(query.get("scope"))
        verified = self.access.enforced and self.identity is not None
        person = self.identity.name if verified else str(query.get("person") or "")
        saved = read_json(self._prefs_path(person)) if person.strip() else None
        mine = ((saved or {}).get("scopes") or {}).get(scope) if isinstance(saved, dict) else None
        return 200, {"scope": scope, "prefs": mine if isinstance(mine, dict) else dict(DEFAULT),
                     "saved": isinstance(mine, dict), "default": dict(DEFAULT), "modes": list(MODES)}

    def put_graph_prefs(self, body: dict[str, Any], **_: Any) -> Reply:
        from cockpit.server import _require_person

        person, persona = self._sign(_text(body, "person", 200), _text(body, "persona", 64), None)
        _require_person(person, persona)
        scope = self._scope(body.get("scope"))
        path = self._prefs_path(person)
        saved = read_json(path)
        scopes = dict((saved or {}).get("scopes") or {}) if isinstance(saved, dict) else {}
        if body.get("reset") is True:
            scopes.pop(scope, None)
            mine: dict[str, Any] = dict(DEFAULT)
        else:
            mine = dict(scopes.get(scope) or DEFAULT)
            if "mode" in body:
                if body["mode"] not in MODES:
                    raise _error(400, f"mode is one of {', '.join(MODES)}")
                mine["mode"] = body["mode"]
            if "presets" in body:
                mine["presets"] = check_presets(body["presets"])
            if "default_preset" in body:
                name = body["default_preset"]
                if name is not None and name not in {p["name"] for p in mine.get("presets") or []}:
                    raise _error(400, "default_preset names one of the saved views, or null")
                mine["default_preset"] = name
            scopes[scope] = mine
        write_json(path, {"person": person, "saved": self._stamp(), "scopes": scopes})
        return 200, {"scope": scope, "prefs": mine, "saved": body.get("reset") is not True, "default": dict(DEFAULT),
                     "modes": list(MODES)}
