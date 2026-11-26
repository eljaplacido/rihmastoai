"""The cockpit's routes for what IT checks (kernel/itops*.py, FR-ITO1): check sets per project and solution type,
eval sets, and running any assessment.

Reads (they write nothing):

- ``GET /api/itops``: every solution type's default check set (Rihmasto's, IT's changes marked), each project's
  set in a line, the eval sets and the assessment targets;
- ``GET /api/projects/<pid>/itops``: the project's check set with why each check is there and its scope, its eval
  sets with their trends, the assessment targets and the automations IT's context suggests;
- ``GET /api/itops/evalsets`` and ``GET /api/projects/<pid>/itops/evalsets``: the enabled eval sets' trends, for
  Agent operations.

Writes, each signed by a person and persona and recorded:

- ``POST /api/projects/<pid>/itops/apply``: enable the set's checks not enabled yet (``only``: some of them);
- ``POST /api/projects/<pid>/itops/run``: run the set's infrastructure checks now (outside the write lock: each
  check keeps its records under its own lock, with short timeouts);
- ``POST /api/projects/<pid>/itops/override``: add (``why``), remove or reset one check for this project;
- ``POST /api/projects/<pid>/itops/types``: choose the project's solution types (an empty list: as detected);
- ``POST /api/itops/defaults``: IT changes a type's platform default (``type``, ``check``, ``action``);
- ``POST /api/projects/<pid>/itops/assess``: run any assessment (``target``) now (outside the write lock);
- ``POST /api/projects/<pid>/itops/evalsets``: enable (``on``) or disable an eval set (``set``) on the project.
"""

from __future__ import annotations

from typing import Any

from cockpit.console_routes import PID  # cockpit/server.py PID, the same
from kernel import itops, itops_assess, itops_evals
from kernel.learn import FACTORY_PID

ROUTES = [
    ("GET", r"/api/itops", "get_itops"),
    ("GET", r"/api/itops/evalsets", "get_itops_evalsets"),
    ("GET", rf"/api/projects/{PID}/itops", "get_project_itops"),
    ("GET", rf"/api/projects/{PID}/itops/evalsets", "get_project_itops_evalsets"),
    ("POST", rf"/api/projects/{PID}/itops/apply", "post_itops_apply"),
    ("POST", rf"/api/projects/{PID}/itops/run", "post_itops_run"),
    ("POST", rf"/api/projects/{PID}/itops/override", "post_itops_override"),
    ("POST", rf"/api/projects/{PID}/itops/types", "post_itops_types"),
    ("POST", r"/api/itops/defaults", "post_itops_defaults"),
    ("POST", rf"/api/projects/{PID}/itops/assess", "post_itops_assess"),
    ("POST", rf"/api/projects/{PID}/itops/evalsets", "post_itops_evalset"),
]
UNLOCKED = {"post_itops_run", "post_itops_assess"}
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


def _text(body: dict[str, Any], key: str, limit: int) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} is text of at most {limit} characters")
    return value.strip()


def _words(body: dict[str, Any], key: str) -> list[str] | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) and len(v) <= 40 for v in value):
        raise ValueError(f"{key} is a list of short words")
    return list(value)


def suggestions(factory: Any, pid: str) -> list[dict[str, Any]]:
    """The automations IT's context suggests for the project (their ids start it_), as kernel/automation_suggest.py
    offers them."""
    from kernel import automation_suggest

    return [s for s in automation_suggest.scan(factory, pid)["suggestions"] if str(s["id"]).startswith("it_")]


class ItOpsRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``_project`` and ``_who``."""

    factory: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def get_itops(self, **_: Any) -> Reply:
        return 200, {"defaults": itops.platform(self.factory), "evalsets": itops_evals.view(None),
                     "targets": itops_assess.public()}

    def get_itops_evalsets(self, **_: Any) -> Reply:
        return 200, {"trends": itops_evals.trends(self.factory)}

    def get_project_itops(self, pid: str, **_: Any) -> Reply:
        project = self._project(pid)
        return 200, {"set": itops.check_set(project), "evalsets": itops_evals.view(project),
                     "targets": itops_assess.public(), "suggestions": suggestions(self.factory, project.pid),
                     "types": [{"id": k, "label": v["label"]} for k, v in itops.TYPES.items()],
                     "setters": list(itops.SETTERS)}           # who turns the set on and runs it (FR-ITO2)

    def get_project_itops_evalsets(self, pid: str, **_: Any) -> Reply:
        project = self._project(pid)
        return 200, {"trends": itops_evals.trends(self.factory, project.pid)}

    def post_itops_apply(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, itops.apply(project, person=person, persona=persona, only=_words(body, "only"))

    def post_itops_run(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, itops.run(project, person=person, persona=persona, via="cockpit")

    def post_itops_override(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, {"set": itops.change(project, _text(body, "check", 60), _text(body, "action", 10), person=person,
                                         persona=persona, why=_text(body, "why", 300))}

    def post_itops_types(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, {"set": itops.set_types(project, _words(body, "types") or [], person=person, persona=persona)}

    def post_itops_defaults(self, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        return 200, {"defaults": itops.change_default(self.factory, _text(body, "type", 40), _text(body, "check", 60),
                                                      _text(body, "action", 10), person=person, persona=persona,
                                                      why=_text(body, "why", 300))}

    def post_itops_assess(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, itops_assess.run(project, _text(body, "target", 80), person=person, persona=persona,
                                     via="cockpit")

    def post_itops_evalset(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        on = body.get("on", True)
        if not isinstance(on, bool):
            raise _error(400, "on is true or false")
        every = _text(body, "every", 10) or None
        return 200, itops_evals.toggle(project, _text(body, "set", 60), on, person=person, persona=persona,
                                       every=every)
