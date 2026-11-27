"""The cockpit's routes for the Alignment tab (FR-ALN1, kernel/alignment_records.py).

- GET .../repo-alignment reads what was proposed and decided, the suggested changes for the repository and the
  drift since the scan before. It records nothing and reads no repository.
- POST .../repo-alignment/scan reads the project's repository at its committed revision and proposes again.
- POST .../repo-alignment/decide accepts (with edits) or rejects items.

Both writes are signed by a person and persona as the other write routes are (with access enforced, a persona
granted on the project), recorded in the project's ledger by the kernel, and never write to the repository.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import alignment_records as kalign
from kernel import structure_cards as kcards
from kernel import structure_policy as kpolicy
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/repo-alignment", "get_repo_alignment"),
    ("POST", rf"/api/projects/{PID}/repo-alignment/scan", "post_repo_alignment_scan"),
    ("POST", rf"/api/projects/{PID}/repo-alignment/decide", "post_repo_alignment_decide"),
]
MAX_ITEMS = 500


def _server() -> Any:
    from cockpit import server

    return server


class AlignRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``_who`` and ``_project``."""

    factory: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _align_signer(self, body: dict[str, Any], pid: str) -> tuple[str, str]:
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        return person, persona

    def get_repo_alignment(self, pid: str, **_: Any) -> tuple[int, dict[str, Any]]:
        if pid == FACTORY_PID:
            return 200, {"applies": False, "why": "Rihmasto's own records have no repository to align with"}
        project = self._project(pid)
        return 200, kpolicy.follow_alignment(self.factory, project, kalign.view(project))   # FR-STR1

    def post_repo_alignment_scan(self, pid: str, body: dict[str, Any], **_: Any) -> tuple[int, dict[str, Any]]:
        project = self._project(pid)
        person, persona = self._align_signer(body, pid)
        out = kalign.scan(project, person=person, persona=persona)
        kcards.sync(self.factory, project)        # an enforced convention's card follows what is open (FR-STR1)
        return 201, kpolicy.follow_alignment(self.factory, project, out)

    def post_repo_alignment_decide(self, pid: str, body: dict[str, Any], **_: Any) -> tuple[int, dict[str, Any]]:
        project = self._project(pid)
        person, persona = self._align_signer(body, pid)
        ids, verdict, edits = body.get("items"), body.get("verdict"), body.get("edits") or {}
        api_error = _server().ApiError
        if not isinstance(ids, list) or not ids or len(ids) > MAX_ITEMS or not all(isinstance(i, str) for i in ids):
            raise api_error(400, "items is a list of alignment item ids, such as req-1a2b3c4d5e")
        if verdict not in kalign.VERDICTS:
            raise api_error(400, "verdict is accept or reject")
        if not isinstance(edits, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in edits.items()):
            raise api_error(400, "edits maps an item id to the fields it changes, such as {\"then\": \"...\"}")
        reason = str(body.get("reason") or "")[:2000]
        out = kalign.decide(project, ids, verdict, person=person, persona=persona, edits=edits, reason=reason)
        kcards.sync(self.factory, project)
        return 200, out | {"alignment": kpolicy.follow_alignment(self.factory, project, kalign.view(project))}
