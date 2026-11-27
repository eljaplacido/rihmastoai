"""The cockpit's routes for the Alignment view's origin, impact and triage (FR-ORG1, kernel/alignment_triage.py).

- GET .../repo-alignment/impact?items=a,b&verdict=accept|reject|defer says what deciding those items would do: what
  the project's records gain, what the gate then measures, that the repository is never written, how the measured
  state shifts and how it is undone. It records nothing.
- POST .../repo-alignment/triage does one triage action, signed by a person and persona: reject_stale,
  defer_convention, accept_current, restore (every deferred item, or those named), defer (the items named).

The write is signed as the other alignment writes are, recorded in the project's ledger by the kernel, and never
writes to the repository.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import alignment_impact as kimpact
from kernel import alignment_triage as ktriage
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/repo-alignment/impact", "get_repo_alignment_impact"),
    ("POST", rf"/api/projects/{PID}/repo-alignment/triage", "post_repo_alignment_triage"),
]
MAX_ITEMS = 500
_ID = re.compile(r"[a-z]+-[0-9a-f]{10}\Z")


def _server() -> Any:
    from cockpit import server

    return server


class AlignTriageRoutes:
    """Mixed into the cockpit's Api: it has ``_project`` and ``_align_signer`` (cockpit/align_routes.py)."""

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _align_signer(self, body: dict[str, Any], pid: str) -> tuple[str, str]:  # pragma: no cover - AlignRoutes'
        raise NotImplementedError

    def get_repo_alignment_impact(self, pid: str, query: dict[str, str], **_: Any) -> tuple[int, dict[str, Any]]:
        ids = [i.strip() for i in str(query.get("items") or "").split(",") if i.strip()]
        verdict = query.get("verdict") or "accept"
        if not ids:            # a read with nothing named answers how to ask, and reads nothing
            return 200, {"verdict": verdict, "items": [], "said": "Name the items to see what deciding them would do: "
                                                                  "?items=<id>,<id>&verdict=accept|reject|defer"}
        if len(ids) > MAX_ITEMS or not all(_ID.match(i) for i in ids):
            raise _server().ApiError(400, "items is a comma-separated list of alignment item ids, such as "
                                          "req-1a2b3c4d5e")
        return 200, kimpact.impact(self._project(pid), ids, verdict)

    def post_repo_alignment_triage(self, pid: str, body: dict[str, Any], **_: Any) -> tuple[int, dict[str, Any]]:
        project = self._project(pid)
        person, persona = self._align_signer(body, pid)
        do, items = body.get("do"), body.get("items")
        api_error = _server().ApiError
        if do not in ktriage.ACTIONS:
            raise api_error(400, f"do is one of {', '.join(ktriage.ACTIONS)}")
        if items is not None and (not isinstance(items, list) or len(items) > MAX_ITEMS
                                  or not all(isinstance(i, str) for i in items)):
            raise api_error(400, "items is a list of alignment item ids, such as gap-1a2b3c4d5e")
        return 200, ktriage.act(project, do, person=person, persona=persona, items=items or None)
