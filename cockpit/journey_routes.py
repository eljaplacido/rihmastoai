"""The cockpit's routes for guided journeys (kernel/journeys.py, FR-JRN1, docs/guides/guided-journeys.md).

Reads: the journeys on offer, the next best step (an open project's through its journey, or which project needs
what), and the asking person's guide with its journey measured from the records now. They write nothing.

The one write, POST /api/journeys/guide, starts, marks (I did it, Skip), attaches a project to, or stops the
person's guide. It is signed by a named person and a persona granted on the factory (as a walkthrough is), and it
writes only the guide's own file and its record in the factory's ledger, under their own locks, so it runs outside
the write lock. What a step does (Adopt, Run the assessment, Read the repository, Set up the watch) the guided
panel asks of that step's own route, signed, as its button in the cockpit would.
"""

from __future__ import annotations

from typing import Any

from kernel import journey_chat as kjchat
from kernel import journey_guide as kguide
from kernel import journeys as kj
from kernel.learn import FACTORY_PID

ROUTES = [
    ("GET", r"/api/journeys", "get_journeys"),
    ("GET", r"/api/journeys/next", "get_journey_next"),
    ("GET", r"/api/journeys/guide", "get_journey_guide"),
    ("POST", r"/api/journeys/guide", "post_journey_guide"),
]
UNLOCKED = {"post_journey_guide"}
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


class JourneyRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``access`` and ``_who``."""

    factory: Any
    access: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _journey_persona(self, query: dict[str, Any]) -> str | None:
        persona = str(query.get("persona") or "").strip()
        return persona or None

    def get_journeys(self, query: dict[str, Any], **_: object) -> Reply:
        """The journeys, their steps' titles in the persona's words, and the three a new person is offered."""
        return 200, {"journeys": kj.catalogue(self._journey_persona(query)), "starters": list(kj.STARTERS)}

    def get_journey_next(self, query: dict[str, Any], **_: object) -> Reply:
        """The next best step: ``project`` names one (its Overview's card), else which project needs what."""
        pid = str(query.get("project") or "").strip() or None
        project = None
        if pid and pid != FACTORY_PID:
            try:
                project = self.factory.project(pid)
            except KeyError:
                raise _server().ApiError(404, f"no project {pid}") from None
        return 200, kjchat.next_answer(self.factory, project, persona=self._journey_persona(query))

    def get_journey_guide(self, query: dict[str, Any], **_: object) -> Reply:
        """The asking person's guide, its journey measured now; ``guide`` is null when they have none."""
        person = str(query.get("person") or "").strip()
        got = kguide.view(self.factory, person, self._journey_persona(query)) if person else None
        return 200, {"guide": got}

    def post_journey_guide(self, body: dict[str, Any], **_: object) -> Reply:
        """Start, mark (did, skip), attach a project to, or stop the person's guide; signed, in the factory's ledger."""
        srv = _server()
        person, persona = self._who(body, FACTORY_PID)
        srv._require_person(person, persona)
        action = srv._text(body, "action", limit=16)
        try:
            kguide.act(self.factory, action, person=person, persona=persona,
                       journey=srv._text(body, "journey", limit=32) or None,
                       project=srv._text(body, "project", limit=100) or None,
                       step=srv._text(body, "step", limit=32) or None)
        except kguide.GuideRefused as exc:
            raise srv.ApiError(409 if "no guide is going" in str(exc) else 400, str(exc)) from None
        return (201 if action == "start" else 200), {"guide": kguide.view(self.factory, person, persona)}
