"""The cockpit's routes for FR-SET1: set up a project, the automations' suggestions and "Describe it", and archiving,
restoring and removing a project.

Every write is signed by a person and persona as the other write routes are (with access enforced, a persona
granted on the project; the factory's for a draft that reaches every project). "Describe it" records nothing: it
reads the words into a draft, with its summary and a dry run, and the person saves it through the automations'
own signed route. An archived project is read-only here: every other write on it is refused (``refuse_archived``)
until a person restores it.
"""

from __future__ import annotations

from typing import Any

from kernel import automation_compose as kcompose
from kernel import automation_suggest as ksuggest
from kernel import project_archive as karchive
from kernel import project_setup as ksetup
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + FACTORY_PID + r"|[a-z0-9][a-z0-9-]{0,80})"   # cockpit/server.py PID, the same pattern
ITEM = r"(?P<item>[a-z_]{2,40})"
SID = r"(?P<sid>[a-z_]{2,40})"
ROUTES = [
    ("GET", rf"/api/projects/{PID}/setup", "get_project_setup"),
    ("POST", rf"/api/projects/{PID}/setup/{ITEM}", "post_project_setup"),
    ("GET", rf"/api/projects/{PID}/automation-suggestions", "get_automation_suggestions"),
    ("POST", rf"/api/projects/{PID}/automation-suggestions/{SID}/accept", "post_suggestion_accept"),
    ("POST", rf"/api/projects/{PID}/automation-suggestions/{SID}/dismiss", "post_suggestion_dismiss"),
    ("POST", r"/api/automations/compose", "post_automation_compose"),
    ("GET", r"/api/archived-projects", "get_archived_projects"),
    ("POST", rf"/api/projects/{PID}/archive", "post_project_archive"),
    ("POST", rf"/api/projects/{PID}/restore", "post_project_restore"),
    ("POST", rf"/api/projects/{PID}/remove", "post_project_remove"),
]
# "Describe it" records nothing (a draft, its summary and its dry run); a model call never holds the write lock.
UNLOCKED = {"post_automation_compose"}
# The writes an archived project still takes: restoring it, and removing it.
ON_ARCHIVED = {"post_project_restore", "post_project_remove"}
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


def refuse_archived(factory: Any, route: str, pid: str | None) -> None:
    """Before a write on a project runs: an archived project takes none but its restoring and its removal."""
    if not pid or pid == FACTORY_PID or route in ON_ARCHIVED:
        return
    meta = factory.projects_dir / pid / "project.json"
    if meta.exists() and karchive.is_archived(factory.project(pid)):
        raise _error(403, f"{pid} is archived: it is read-only until a person restores it (Projects, Archived)")


class SetupRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``_who`` and ``_project``."""

    server: Any
    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _signed_on(self, body: dict[str, Any], pid: str) -> tuple[str, str]:
        self._project(pid)
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        return person, persona

    # set up this project

    def get_project_setup(self, pid: str, **_: object) -> Reply:
        self._project(pid)
        if pid == FACTORY_PID:     # Rihma's own proposals have no set-up of their own
            return 200, {"project": pid, "items": [], "counts": {s: 0 for s in ksetup.STATES}, "done": True,
                         "line": "Rihma's own proposals have no set-up of their own."}
        return 200, ksetup.checklist(self.factory, pid)

    def post_project_setup(self, pid: str, item: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._signed_on(body, pid)
        named = body.get("suggestion")       # the suggestion the button named: set up that one, or refused
        if named is not None and not isinstance(named, str):
            raise _error(400, "suggestion is a suggestion's id")
        try:
            return 200, ksetup.do(self.factory, pid, item, person=person, persona=persona, suggestion=named)
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None

    # the automations' suggestions

    def get_automation_suggestions(self, pid: str, **_: object) -> Reply:
        self._project(pid)
        if pid == FACTORY_PID:
            return 200, {"project": pid, "suggestions": [], "offered": 0}
        return 200, ksuggest.scan(self.factory, pid)

    def post_suggestion_accept(self, pid: str, sid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._signed_on(body, pid)
        changes = body.get("changes") if isinstance(body.get("changes"), dict) else None
        try:
            out = ksuggest.accept(self.factory, pid, sid, person=person, persona=persona, changes=changes)
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None
        return 201, out

    def post_suggestion_dismiss(self, pid: str, sid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._signed_on(body, pid)
        try:
            return 200, ksuggest.dismiss(self.factory, pid, sid, person=person, persona=persona)
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None

    def post_automation_compose(self, body: dict[str, Any], **_: object) -> Reply:
        """Describe it: a draft from the words, its summary and a dry run. Records nothing."""
        pid = _server()._text(body, "project", limit=100) or None
        project = self._project(pid) if pid and pid != FACTORY_PID else None
        person, persona = self._who(body, project.pid if project is not None else FACTORY_PID)
        _server()._require_person(person, persona)
        text = _server()._text(body, "text", required=True, limit=2000)
        model = self.server.assistant_model if body.get("with_model") is True else None
        return 200, kcompose.compose(self.factory, text, project=project, model=model)

    # archive, restore, remove

    def get_archived_projects(self, **_: object) -> Reply:
        return 200, {"archived": karchive.archived(self.factory), "duplicates": karchive.duplicates(self.factory),
                     "archivers": list(karchive.ARCHIVERS)}

    def post_project_archive(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._signed_on(body, pid)
        reason = _server()._text(body, "reason", limit=500)
        return 200, {"project": karchive.archive(self.factory, pid, person=person, persona=persona, reason=reason)}

    def post_project_restore(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._signed_on(body, pid)
        return 200, {"project": karchive.restore(self.factory, pid, person=person, persona=persona)}

    def post_project_remove(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._signed_on(body, pid)
        confirm = _server()._text(body, "confirm", limit=100)
        return 200, karchive.remove(self.factory, pid, person=person, persona=persona, confirm=confirm)
