"""The cockpit's routes for teams, the words they and their projects give Rihmasto's own terms, and what applies
where (kernel/teams.py, kernel/vocab.py, kernel/vocab_edit.py, kernel/scope_table.py; FR-TM1, FR-TM2, FR-TM3).

- ``GET /api/teams``: every team with its members and projects, whether the home is one person's, and the changes;
- ``POST /api/teams``: IT makes a team (``name``, ``members``); ``PUT /api/teams/<team>``: renames it or adds and
  removes members (``name``, ``add``, ``remove``); both signed and in the factory's ledger;
- ``POST /api/teams/preview``: what a change would do (a team's, or ``project`` and ``to`` for a move); it records nothing;
- ``POST /api/teams/undo``: puts back what the last change of a ``team`` (or of a ``project``'s team) replaced;
- ``GET`` / ``POST /api/projects/<pid>/team``: the project's team and the others it could move to; moving it (``team``),
  by IT or the project's owner, with a ``reason``;
- ``GET /api/vocabulary?team=&project=&term=``: every term as it reads here, with the shipped meaning, the team's, the
  project's and which is in force; ``term`` adds its definitions over time;
- ``POST /api/vocabulary/preview``: how a change would read and how many records, nodes and views read differently;
- ``PUT /api/teams/<team>/vocabulary`` (IT) and ``PUT /api/projects/<pid>/vocabulary`` (IT or the project's owner):
  rename, describe, add synonyms, hide a term, or add a custom term that means a kind of record; signed, with a reason;
  ``POST /api/vocabulary/undo`` gives the earlier reading back exactly;
- ``GET /api/scope?project=``: every setting surface with the scopes it may be set at and, for the project, where its
  value comes from now.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import scope_table, teams, vocab, vocab_edit
from kernel import teams_guard as guard
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
TID = r"(?P<tid>[a-z0-9][a-z0-9-]{0,60})"
ROUTES = [
    ("GET", r"/api/teams", "get_teams"),
    ("POST", r"/api/teams", "post_team"),
    ("POST", r"/api/teams/preview", "post_teams_preview"),
    ("POST", r"/api/teams/undo", "post_team_undo"),
    ("PUT", rf"/api/teams/{TID}", "put_team"),
    ("GET", rf"/api/projects/{PID}/team", "get_project_team"),
    ("POST", rf"/api/projects/{PID}/team", "post_project_team"),
    ("GET", r"/api/vocabulary", "get_vocabulary"),
    ("POST", r"/api/vocabulary/preview", "post_vocabulary_preview"),
    ("POST", r"/api/vocabulary/undo", "post_vocabulary_undo"),
    ("PUT", rf"/api/teams/{TID}/vocabulary", "put_team_vocabulary"),
    ("PUT", rf"/api/projects/{PID}/vocabulary", "put_project_vocabulary"),
    ("GET", r"/api/scope", "get_scope"),
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


def _fields(body: dict[str, Any]) -> dict[str, Any]:
    """The term's fields the body names: a field sent as null gives that one back to the layer below."""
    return {k: body[k] for k in vocab.FIELDS if k in body}


class TeamRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``_project``, ``_who`` and ``access``."""

    factory: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    # -- teams -----------------------------------------------------------------------------------------------

    def get_teams(self, **_: Any) -> Reply:
        return 200, teams.describe(self.factory)

    def post_team(self, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        return 200, teams.create(self.factory, body.get("name"), members_=body.get("members"), person=person,
                                 persona=persona, reason=_text(body, "reason", 300) or "")

    def put_team(self, tid: str, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        return 200, teams.update(self.factory, tid, name=body.get("name"), add=body.get("add"),
                                 remove=body.get("remove"), person=person, persona=persona,
                                 reason=_text(body, "reason", 300) or "")

    def post_teams_preview(self, body: dict[str, Any], **_: Any) -> Reply:
        pid = _text(body, "project", 90)
        _, persona = self._who(body, pid or FACTORY_PID)
        guard.require_persona(persona, teams.MOVERS if pid else teams.ADMINS,
                              "move a project to another team" if pid else "define a team")
        if pid:
            self._project(pid)
        return 200, teams.preview(self.factory, team=_text(body, "team", 60), name=body.get("name"),
                                  add=body.get("add"), remove=body.get("remove"), project=pid,
                                  to=_text(body, "to", 60))

    def post_team_undo(self, body: dict[str, Any], **_: Any) -> Reply:
        pid = _text(body, "project", 90)
        person, persona = self._who(body, pid or FACTORY_PID)
        return 200, teams.undo(self.factory, team=_text(body, "team", 60) or None,
                               project=self._project(pid) if pid else None, person=person, persona=persona)

    def get_project_team(self, pid: str, **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, "applies": False, "why": "Rihmasto's own records belong to no team"}
        return 200, {"applies": True, **teams.of_project(self.factory, self._project(pid))}

    def post_project_team(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            raise ValueError("Rihmasto's own records belong to no team: a project is moved, not Rihmasto itself")
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, teams.move_project(self.factory, project, str(body.get("team") or ""), person=person,
                                       persona=persona, reason=_text(body, "reason", 300) or "")

    # -- vocabulary ------------------------------------------------------------------------------------------

    def get_vocabulary(self, query: dict[str, Any], **_: Any) -> Reply:
        pid, tid = query.get("project") or None, query.get("team") or None
        if tid is not None and not teams._ID.fullmatch(tid):
            raise ValueError(f"no team {str(tid)[:60]!r}")
        project = self._project(pid) if pid and _PID.fullmatch(pid) else None
        if project is None and tid is None:
            eff = vocab.context(self.factory, None, self.factory.projects())
        else:
            eff = vocab.effective(self.factory, project, tid)
        if query.get("compact") == "1":          # what every page needs to say a term in the word in force
            return 200, {**vocab.compact(eff), "solo": teams.is_solo(self.factory)}
        out: dict[str, Any] = {"team": eff["team"], "project": eff["project"], "order": eff["order"],
                               "terms": eff["terms"], "scope_words": vocab.SCOPE_WORD,
                               "setters": {k: list(v) for k, v in vocab_edit.SETTERS.items()}}
        if query.get("term"):
            out["definitions"] = vocab_edit.definitions(self.factory, project, str(query["term"]), tid)
        scope, owner = ("project", project.pid) if project is not None else ("team", eff["team"])
        out["history"] = vocab_edit.history(self.factory, scope, owner) if owner else []
        return 200, out

    def _vocab_scope(self, body: dict[str, Any]) -> tuple[str, str, str, str]:
        """(scope, owner, person, persona) of a vocabulary write: a project's own, or a team's."""
        pid = _text(body, "project", 90)
        scope, owner = ("project", pid) if pid else ("team", _text(body, "team", 60) or "")
        if pid:
            self._project(pid)
        person, persona = self._who(body, pid or FACTORY_PID)
        return scope, owner, person, persona

    def post_vocabulary_preview(self, body: dict[str, Any], **_: Any) -> Reply:
        pid = _text(body, "project", 90)
        _, persona = self._who(body, pid or FACTORY_PID)
        scope, owner = ("project", pid) if pid else ("team", _text(body, "team", 60) or "")
        guard.require_persona(persona, vocab_edit.SETTERS[scope], f"change a {scope}'s words")
        if pid:
            self._project(pid)
        return 200, vocab_edit.preview(self.factory, scope, owner, term=body.get("term"), fields=_fields(body),
                                       reset=body.get("reset") is True)

    def post_vocabulary_undo(self, body: dict[str, Any], **_: Any) -> Reply:
        scope, owner, person, persona = self._vocab_scope(body)
        return 200, vocab_edit.undo(self.factory, scope, owner, person=person, persona=persona)

    def put_team_vocabulary(self, tid: str, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        return 200, vocab_edit.set_term(self.factory, "team", tid, term=body.get("term"), fields=_fields(body),
                                        reset=body.get("reset") is True, person=person, persona=persona,
                                        reason=_text(body, "reason", 300) or "")

    def put_project_vocabulary(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        self._project(pid)
        person, persona = self._who(body, pid)
        return 200, vocab_edit.set_term(self.factory, "project", pid, term=body.get("term"), fields=_fields(body),
                                        reset=body.get("reset") is True, person=person, persona=persona,
                                        reason=_text(body, "reason", 300) or "")

    # -- what applies where ----------------------------------------------------------------------------------

    def get_scope(self, query: dict[str, Any], **_: Any) -> Reply:
        pid = query.get("project") or None
        project = self._project(pid) if pid and _PID.fullmatch(pid) else None
        return 200, scope_table.describe(self.factory, project)
