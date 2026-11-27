"""The cockpit's routes for agent observability (kernel/agentobs, FR-OBS1).

- ``GET /api/agent-observability``: the hub's settings, whether the module is on anywhere, and who sets them;
  ``?check=1`` also asks the hub whether it answers (a read; nothing is kept);
- ``PUT /api/agent-observability``: IT sets the hub's address (core: IT configures it before anyone turns the
  module on), recorded in the factory's ledger;
- ``GET /api/projects/<pid>/agent-sessions?persona=``: the project's Agent sessions view, read from the hub when
  asked (only for developers and IT; any other persona is told who it is for and nothing is read). With
  ``&as_needed=1`` (the page viewing "everything", solo or team mode) it is read as developer or IT when the
  person holds one of them, as a write asking for the persona it needs is signed (cockpit/solo_routes.py);
- ``POST /api/projects/<pid>/agent-sessions/map`` and ``/snapshot``: a developer or IT maps the project to the
  hub's project, or records what the hub shows. Both belong to the module: refused while it is off there.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import agentobs as kobs
from kernel import solo as ksolo
from kernel.agentobs import client as kobs_client
from kernel.agentobs import mapping as kobs_map
from kernel.agentobs import snapshot as kobs_snap
from kernel.agentobs import view as kobs_view
from kernel.learn import FACTORY_PID
from kernel.people import PERSONAS

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", r"/api/agent-observability", "get_agent_observability"),
    ("PUT", r"/api/agent-observability", "put_agent_observability"),
    ("GET", rf"/api/projects/{PID}/agent-sessions", "get_agent_sessions"),
    ("POST", rf"/api/projects/{PID}/agent-sessions/map", "post_agent_sessions_map"),
    ("POST", rf"/api/projects/{PID}/agent-sessions/snapshot", "post_agent_sessions_snapshot"),
]
Reply = tuple[int, dict[str, Any]]


def _text(body: dict[str, Any], key: str, limit: int) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} is text of at most {limit} characters")
    return value.strip()


class AgentObsRoutes:
    """Mixed into the cockpit's Api: it has ``factory`` and ``_project`` and ``_who``."""

    factory: Any
    access: Any
    identity: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _agentobs_state(self) -> dict[str, Any]:
        return {"settings": kobs.settings(self.factory), "on_anywhere": kobs.on_anywhere(self.factory),
                "module": kobs.MODULE, "setters": list(kobs.SETTERS), "for_personas": list(kobs.SEES),
                "default_url": kobs.DEFAULT_URL}

    def get_agent_observability(self, query: dict[str, Any], **_: Any) -> Reply:
        out = self._agentobs_state()
        hub = kobs_client.from_settings(self.factory, timeout=3.0) if query.get("check") == "1" else None
        if hub is not None:
            try:
                out["hub"] = {"reachable": True, **hub.health()}
            except (kobs_client.HubUnreachable, kobs_client.HubError) as exc:
                out["hub"] = {"reachable": False, "error": str(exc)}
        return 200, out

    def put_agent_observability(self, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        kobs.set_settings(self.factory, url=_text(body, "url", 500), token_env=_text(body, "token_env", 64),
                          private=body.get("private") is True, hosted=body.get("hosted") is True, person=person,
                          persona=persona, reason=_text(body, "reason", 300))
        return 200, self._agentobs_state()

    def get_agent_sessions(self, pid: str, query: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"project": pid, "applies": False, "why": "the Agent sessions view is a product project's"}
        project = self._project(pid)
        persona = query.get("persona") if query.get("persona") in PERSONAS else "developer"
        if query.get("as_needed") == "1" and ksolo.chooses(self.access):    # "Viewing as: everything" (FR-PPL1)
            persona = ksolo.decide_as(kobs.SEES, ksolo.held(self.access, self.identity, pid), persona) or persona
        return 200, kobs_view.build(self.factory, project, persona=persona)

    def post_agent_sessions_map(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        how = "suggested" if body.get("how") == "suggested" else "chosen"
        doc = kobs_map.map_project(project, _text(body, "hub_project", 201), person=person, persona=persona,
                                   how=how, reason=_text(body, "reason", 300))
        return 200, {"project": pid, "mapping": doc}

    def post_agent_sessions_snapshot(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, {"project": pid, "snapshot": kobs_snap.record(self.factory, project, person=person,
                                                                  persona=persona)}
