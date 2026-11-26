"""The cockpit's route for "AI tools in this project" and "Work on it from your IDE" (FR-AGC1, kernel/ide.py).

A read: how the project's AI tools are set up, read from its committed revision (an adopted project's main,
an attached repository's branch) and never run; ready-to-paste MCP configuration pointing at Rihmasto's own
MCP server; how a developer's change comes back; and the section a person pastes into their own AGENTS.md or
CLAUDE.md. It records nothing and writes nothing, here or in the person's folder.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import ide as kide
from kernel.learn import FACTORY_PID
from kernel.people import PERSONAS, is_person

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [("GET", rf"/api/projects/{PID}/ai-tools", "get_ai_tools")]


class AgentContextRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``identity`` and ``_project``."""

    factory: Any
    identity: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def get_ai_tools(self, pid: str, query: dict, **_: Any) -> tuple[int, dict[str, Any]]:
        project = self._project(pid)
        persona = query.get("persona") if query.get("persona") in PERSONAS else "developer"
        name = self.identity.name if self.identity is not None else (query.get("person") or "").strip()[:200]
        out = kide.view(project, name=name if name and is_person(name) else None, persona=persona)
        if out.get("applies"):      # the agent observability hub's hooks, by file names (kernel/agentobs, FR-OBS1)
            from kernel.agentobs.feeds import catalogue_entry

            out["agent_observability"] = catalogue_entry(self.factory, project)
        return 200, out
