"""The cockpit's routes for Agent operations (kernel/agentops*.py, FR-AOP1).

- ``GET /api/agent-ops?window=24h|7d|30d|all``: every project the person sees, with Rihmasto's own canon: the runs
  per role, harness and model, tokens, cost, latency, tools, the harness's overhead, the context packs, context
  drift, the hub's recorded figures and the Optimise audit's proposals. ``&context=0`` leaves the context packs
  out (a quicker read);
- ``GET /api/projects/<pid>/agent-ops``: the same for one project;
- ``POST /api/agent-ops/audit``: the Optimise audit recorded in the ledger (``project`` in the body: that
  project's; none: Rihmasto's own), signed;
- ``POST /api/agent-ops/prices``: a model's price per million tokens (``model``, ``input``, ``output``,
  ``cached`` or ``local``), kept in the home and recorded in Rihmasto's own ledger, signed (FR-AOP2);
- ``POST /api/projects/<pid>/agent-ops/proposals/<id>/change``: one proposal filed as a change card, signed
  (``<pid>`` ``_factory``: a proposal of the platform-wide audit).

Reads write nothing; every figure that is not measured says why and how.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import agentops_actions as ops
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", r"/api/agent-ops", "get_agent_ops"),
    ("POST", r"/api/agent-ops/audit", "post_agent_ops_audit"),
    ("POST", r"/api/agent-ops/prices", "post_agent_ops_price"),
    ("GET", rf"/api/projects/{PID}/agent-ops", "get_project_agent_ops"),
    ("POST", rf"/api/projects/{PID}/agent-ops/proposals/(?P<oid>OPT-[0-9a-f]{{10}})/change", "post_agent_ops_change"),
]
Reply = tuple[int, dict[str, Any]]


class AgentOpsRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``_project`` and ``_who``."""

    factory: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def get_agent_ops(self, query: dict[str, Any], **_: Any) -> Reply:
        return 200, ops.read(self.factory, window=ops.window_of(query.get("window")),
                             context=query.get("context") != "0")

    def get_project_agent_ops(self, pid: str, query: dict[str, Any], **_: Any) -> Reply:
        if pid == FACTORY_PID:
            return self.get_agent_ops(query)
        self._project(pid)
        return 200, ops.read(self.factory, pid=pid, window=ops.window_of(query.get("window")),
                             context=query.get("context") != "0")

    def post_agent_ops_audit(self, body: dict[str, Any], **_: Any) -> Reply:
        pid = body.get("project") if isinstance(body.get("project"), str) and body.get("project") else None
        if pid == FACTORY_PID:
            pid = None
        if pid is not None:
            self._project(pid)
        person, persona = self._who(body, pid or FACTORY_PID)
        return 200, ops.record(self.factory, pid=pid, window=ops.window_of(body.get("window")), person=person,
                               persona=persona)

    def post_agent_ops_price(self, body: dict[str, Any], **_: Any) -> Reply:
        """A model's price per million tokens kept in the home, signed (FR-AOP2)."""
        from kernel import agentops_prices

        person, persona = self._who(body, FACTORY_PID)
        return 200, agentops_prices.set_price(self.factory, model=body.get("model"), input=body.get("input"),
                                              output=body.get("output"), cached=body.get("cached"),
                                              local=body.get("local"), person=person, persona=persona)

    def post_agent_ops_change(self, pid: str, oid: str, body: dict[str, Any], **_: Any) -> Reply:
        if pid != FACTORY_PID:
            self._project(pid)
        person, persona = self._who(body, pid)
        try:
            out = ops.file_change(self.factory, pid=pid, oid=oid, person=person, persona=persona,
                                  window=ops.window_of(body.get("window")))
        except KeyError as exc:
            from cockpit.server import ApiError

            raise ApiError(404, str(exc).strip("'\"")) from None
        return (200 if out["already"] else 201), out
