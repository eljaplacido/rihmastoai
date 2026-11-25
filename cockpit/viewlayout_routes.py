"""The cockpit's routes for a person's view layouts (FR-UXO1): Customize on every view other than Home.

Home keeps its widget layouts per person, persona and lens (``/api/layout``). Every other view keeps the
person's own arrangement of its sections (their order, which are hidden, compact or wide) and, in a project,
the capsule tabs they hide or pin. These are kept on the server, per person, in the factory home's
``_cockpit/view-layouts/`` (one file per person, named by a hash of the name), so they follow the person to
another computer and another browser. They are the cockpit's own files: never written into any project's
ledger, and a write records nothing anywhere else.

``GET /api/view-layouts?person=`` answers the person's views and tabs (empty for no one, with ``saved: false``
until their first save). ``PUT /api/view-layouts`` takes ``{person, persona, views?, tabs?, reset?}``: each view
in ``views`` replaces that view's layout (``null`` removes it), ``tabs`` replaces the tab choices, ``reset``
names views to remove (``"*"`` removes them all, with the tabs). The page's first load moves any layouts an
earlier version kept in that browser to the server in one save, then forgets the browser's copy.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from kernel.people import is_person
from kernel.store import read_json, write_json

ROUTES = [
    ("GET", r"/api/view-layouts", "get_view_layouts"),
    ("PUT", r"/api/view-layouts", "put_view_layouts"),
]
Reply = tuple[int, dict[str, Any]]

VIEW_KEY = re.compile(r"[pg]:[a-z][a-z0-9_]{0,40}")      # p:<project view> or g:<page>
TAB_ID = re.compile(r"[a-z][a-z0-9_]{0,40}")
SIZES = ("normal", "compact", "wide")
MAX_VIEWS = 120
MAX_SECTIONS = 80
MAX_TABS = 60


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


def _section(key: object) -> str:
    """A section key as the page made it (a slug, an id or a card's data-id): plain printable text, at most 80."""
    if not isinstance(key, str) or not key or len(key) > 80 or any(ord(c) < 32 for c in key):
        raise _error(400, "a section key is text of 1 to 80 printable characters")
    return key


def check_view(layout: object) -> dict[str, Any]:
    """One view's layout: {order: [key], hidden: [key], size: {key: normal|compact|wide}}, within fixed bounds."""
    if not isinstance(layout, dict):
        raise _error(400, "a view layout is an object with order, hidden and size")
    order, hidden, size = layout.get("order") or [], layout.get("hidden") or [], layout.get("size") or {}
    if not isinstance(order, list) or not isinstance(hidden, list) or not isinstance(size, dict):
        raise _error(400, "order and hidden are lists, size is an object")
    if len(order) > MAX_SECTIONS or len(hidden) > MAX_SECTIONS or len(size) > MAX_SECTIONS:
        raise _error(400, f"a view has at most {MAX_SECTIONS} sections")
    out_size = {}
    for k, v in size.items():
        if v not in SIZES:
            raise _error(400, f"a size is one of {', '.join(SIZES)}")
        if v != "normal":
            out_size[_section(k)] = v
    return {"order": [_section(k) for k in order], "hidden": list(dict.fromkeys(_section(k) for k in hidden)),
            "size": out_size}


def check_tabs(tabs: object) -> dict[str, list[str]]:
    """The capsule tabs a person hides or pins: {hidden: [view id], pinned: [view id]}."""
    if not isinstance(tabs, dict):
        raise _error(400, "tabs is an object with hidden and pinned")
    out = {}
    for kind in ("hidden", "pinned"):
        ids = tabs.get(kind) or []
        if not isinstance(ids, list) or len(ids) > MAX_TABS or not all(isinstance(i, str) and TAB_ID.fullmatch(i) for i in ids):
            raise _error(400, f"tabs.{kind} is a list of at most {MAX_TABS} view ids")
        out[kind] = list(dict.fromkeys(ids))
    return out


def empty() -> dict[str, Any]:
    return {"views": {}, "tabs": {"hidden": [], "pinned": []}}


class ViewLayoutRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``access`` and ``_sign``."""

    server: Any
    access: Any

    def _sign(self, person: str, persona: str, pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _stamp(self) -> str:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _view_layouts_path(self, person: str) -> Path:
        key = hashlib.sha256(person.strip().encode("utf-8")).hexdigest()[:20]
        return Path(self.server.cockpit_dir) / "view-layouts" / f"{key}.json"

    def _view_layouts(self, person: str) -> tuple[dict[str, Any], bool]:
        if not is_person(person):
            return empty(), False
        saved = read_json(self._view_layouts_path(person))
        if not isinstance(saved, dict):
            return empty(), False
        views = saved.get("views") if isinstance(saved.get("views"), dict) else {}
        tabs = saved.get("tabs") if isinstance(saved.get("tabs"), dict) else {}
        return {"views": views, "tabs": {"hidden": list(tabs.get("hidden") or []), "pinned": list(tabs.get("pinned") or [])}}, True

    def get_view_layouts(self, query: dict[str, Any], **_: object) -> Reply:
        person = str(query.get("person") or "").strip()[:200]
        if self.access.enforced and getattr(self, "identity", None) is not None:
            person = self.identity.name                  # with access enforced: the verified person's own layouts
        out, saved = self._view_layouts(person)
        return 200, dict(out, saved=saved, person=person if is_person(person) else "")

    def put_view_layouts(self, body: dict[str, Any], **_: object) -> Reply:
        """Save a person's view layouts: per view, the tabs, or a reset. Kept outside every ledger."""
        text = _server()._text
        person, persona = self._sign(text(body, "person", limit=200), text(body, "persona", limit=64), None)
        if not is_person(person):
            raise _error(403, f"refused: {person!r} is not a person; a view layout belongs to a named person")
        cur, _ = self._view_layouts(person)
        views = dict(cur["views"])
        reset = body.get("reset") or []
        if reset == "*" or reset == ["*"]:
            views, cur["tabs"] = {}, {"hidden": [], "pinned": []}
        elif isinstance(reset, list):
            for k in reset:
                views.pop(str(k), None)
        incoming = body.get("views") or {}
        if not isinstance(incoming, dict):
            raise _error(400, "views is an object of view key to layout")
        for k, lay in incoming.items():
            if not isinstance(k, str) or not VIEW_KEY.fullmatch(k):
                raise _error(400, "a view key is p:<view> or g:<page>")
            if lay is None:
                views.pop(k, None)
            else:
                views[k] = check_view(lay)
        if len(views) > MAX_VIEWS:
            raise _error(400, f"at most {MAX_VIEWS} views are kept per person")
        tabs = check_tabs(body["tabs"]) if body.get("tabs") is not None else cur["tabs"]
        doc = {"person": person, "persona": persona, "saved": self._stamp(), "views": views, "tabs": tabs}
        write_json(self._view_layouts_path(person), doc)
        return 200, {"views": views, "tabs": tabs, "saved": True, "person": person}
