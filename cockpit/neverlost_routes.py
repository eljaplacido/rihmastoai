"""The cockpit's routes for never lost, who acted and decision triage (FR-NVL1).

Reads write nothing:

- ``GET /api/why``: why a view or one of its figures is empty, not measured or failing, and the step that fills it
  (kernel/neverlost.py, by rule), for ``?view=&field=&kind=&basis=&project=``;
- ``GET /api/projects/<pid>/triage``: the blocking few ranked with why, the proposal that assumes the rest, and the
  assumptions that grew in importance (kernel/triage.py, kernel/assumption_weight.py), for ``?persona=`` (the
  proposal holds only what that persona may decide);
- ``GET /api/triage``: the same across every project at once (kernel/triage_all.py, FR-NVL2);
- ``GET /api/projects/<pid>/who``: every run with who acted, and the project's harness and enforcement;
- ``GET /api/harness-enforcement``: the platform's harness and enforcement.

Writes are signed by a person and persona (with access enforced, one granted where it acts) and recorded:

- ``POST /api/projects/<pid>/triage/assume``: confirm the proposal, each card decided as the person's delegated
  choice through the canon's own rules;
- ``PUT /api/harness-enforcement`` and ``PUT /api/projects/<pid>/harness-enforcement``: Gnomon's enforcement on (the default) or an
  explicit opt-out with its reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel import harness_enforcement as kenf
from kernel import neverlost, triage, triage_all, who_acted
from kernel.people import PERSONAS

PID = r"(?P<pid>_factory|[a-z0-9][a-z0-9-]{0,80})"
ROUTES = [
    ("GET", r"/api/why", "get_why"),
    ("GET", r"/api/triage", "get_triage_all"),
    ("GET", rf"/api/projects/{PID}/triage", "get_triage"),
    ("POST", rf"/api/projects/{PID}/triage/assume", "post_triage_assume"),
    ("GET", rf"/api/projects/{PID}/who", "get_who"),
    ("GET", r"/api/harness-enforcement", "get_harness_enforcement"),
    ("PUT", r"/api/harness-enforcement", "put_harness_enforcement"),
    ("PUT", rf"/api/projects/{PID}/harness-enforcement", "put_project_harness_enforcement"),
]
Reply = tuple[int, dict[str, Any]]
ID_LIMIT = 500


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


def _text(body: dict[str, Any], key: str, *, limit: int = 2000) -> str:
    return str(_server()._text(body, key, limit=limit))


def _on(body: dict[str, Any]) -> bool:
    on = body.get("on")
    if not isinstance(on, bool):
        raise _error(400, "on must be true (Gnomon enforces) or false (an opt-out, with its reason)")
    return on


def _persona(query: dict[str, Any] | None) -> str | None:
    """The persona a triage is read for (its proposal holds only what that persona may decide), when it names one."""
    persona = str((query or {}).get("persona") or "")
    return persona if persona in PERSONAS else None


def why_from_body(factory: Any, pid: str | None, why: dict[str, Any]) -> dict[str, Any]:
    """Ask Rihma's answer to "Why? Ask Rihma" (the request's ``why``: view, field, kind, basis), by rule."""
    project = factory.project(pid) if pid and pid != "_factory" else None
    return neverlost.why(factory, project, view=str(why.get("view") or "")[:40],
                         field=str(why.get("field") or "")[:200], kind=str(why.get("kind") or "empty")[:20],
                         basis=str(why.get("basis") or "")[:400])


def _last_failure(body: dict[str, Any]) -> dict[str, Any] | None:
    """A typed "why did it fail?" carries the last failure the page showed (neverlost.js): its message and view."""
    from kernel.neverlost_ask import kind_of

    last = body.get("last_error")
    question = str(body.get("question") or "")
    if not isinstance(last, dict) or not str(last.get("message") or "").strip() or not neverlost.asked(question):
        return None
    if kind_of(question) != "error":
        return None
    return {"view": str(last.get("view") or ""), "field": "", "kind": "error", "basis": str(last["message"])}


def answer_with_who(factory: Any, pid: str | None, body: dict[str, Any], model: Any,
                    ask: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Ask Rihma's answer (``ask``), or the answer by rule to "Why? Ask Rihma" when the request carries its context
    (or a typed "why did it fail?" the last failure on the page), with who acted on it: which agent, harness and
    model answered."""
    project = factory.project(pid) if pid and pid != "_factory" else None
    why = body["why"] if isinstance(body.get("why"), dict) else _last_failure(body)
    out = why_from_body(factory, pid, why) if why is not None else ask()
    out["who"] = who_acted.for_answer(factory, project, out, model)
    return out


class NeverLostRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``_who`` and ``_project``."""

    server: Any
    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _signer(self, body: dict[str, Any], pid: str) -> tuple[str, str]:
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        return person, persona

    def _scoped(self, pid: str | None) -> Any:
        return self._project(pid) if pid and pid != "_factory" else None

    # reads

    def get_why(self, query: dict[str, Any], **_: object) -> Reply:
        pid = str(query.get("project") or "")[:100] or None
        project = self._scoped(pid)
        out = neverlost.why(self.factory, project, view=str(query.get("view") or "")[:40],
                            field=str(query.get("field") or "")[:200], kind=str(query.get("kind") or "empty")[:20],
                            basis=str(query.get("basis") or "")[:400])
        return 200, out | {"who": who_acted.for_answer(self.factory, project, out)}

    def get_triage(self, pid: str, query: dict[str, Any] | None = None, **_: object) -> Reply:
        return 200, triage.triage(self._project(pid), _persona(query))

    def get_triage_all(self, query: dict[str, Any] | None = None, **_: object) -> Reply:
        """Every project's open decisions at once, for the persona asking (FR-NVL2)."""
        return 200, triage_all.across(self.factory, _persona(query))

    def get_who(self, pid: str, **_: object) -> Reply:
        project = self._project(pid)
        scoped = project if pid != "_factory" else None
        return 200, {"project": pid, "runs": who_acted.runs(self.factory, project),
                     "harness": kenf.effects(self.factory, scoped) | {"project_setters": list(kenf.PROJECT_SETTERS)}}

    def get_harness_enforcement(self, **_: object) -> Reply:
        return 200, kenf.effects(self.factory, None) | {"setters": list(kenf.PLATFORM_SETTERS),
                                                        "project_setters": list(kenf.PROJECT_SETTERS)}

    # writes

    def post_triage_assume(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        person, persona = self._signer(body, pid)
        cards = body.get("cards")
        if cards is not None and (not isinstance(cards, list) or len(cards) > ID_LIMIT
                                  or not all(isinstance(c, str) and len(c) < 20 for c in cards)):
            raise _error(400, "cards is a list of card ids such as C-0001, or left out for the whole proposal")
        try:
            out = triage.confirm(project, person=person, persona=persona, cards=cards)
        except triage.TriageRefused as exc:
            raise _error(403, str(exc)) from None
        if out["assumed"]:
            from kernel.intake import render_brief

            render_brief(project)
        return 200, out

    def put_harness_enforcement(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._signer(body, "_factory")
        try:
            st = kenf.set_enforcement(self.factory, None, on=_on(body), reason=_text(body, "reason", limit=500),
                                      person=person, persona=persona)
        except kenf.EnforcementRefused as exc:
            raise _error(403 if "may not" in str(exc) else 400, str(exc)) from None
        return 200, kenf.effects(self.factory, None) | {"state": st}

    def put_project_harness_enforcement(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        person, persona = self._signer(body, pid)
        try:
            st = kenf.set_enforcement(self.factory, project, on=_on(body), reason=_text(body, "reason", limit=500),
                                      person=person, persona=persona)
        except kenf.EnforcementRefused as exc:
            raise _error(403 if "may not" in str(exc) else 400, str(exc)) from None
        return 200, kenf.effects(self.factory, project) | {"state": st}
