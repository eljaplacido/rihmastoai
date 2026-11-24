"""The cockpit's routes for cell runners (kernel/runners, D-0019, FR-HRN1): Settings > Runners and Project settings.

Reading what runs each role writes nothing; ``?check=1`` also looks for each runner on this machine (its version)
and for Docker. Choosing a runner is signed by a person and persona granted on the factory, and recorded in the
factory's ledger: Gnomon applies at once, another runner opens a card that IT decides in the factory's Inbox (the
cards' own decide route), with the runner's version pinned.
"""

from __future__ import annotations

from typing import Any

from kernel.learn import FACTORY_PID
from kernel.runners import ROLES
from kernel.runners import choice as kchoice

ROLE = r"(?P<role>builder|verifier)"
ROUTES = [
    ("GET", r"/api/runners", "get_runners"),
    ("PUT", rf"/api/runners/{ROLE}", "put_runner"),
]
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def _text(body: dict[str, Any], key: str, limit: int = 500) -> str:
    return str(_server()._text(body, key, limit=limit))


class RunnerRoutes:
    """Mixed into the cockpit's Api: it has ``factory`` and ``_who``."""

    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def get_runners(self, query: dict[str, Any], **_: object) -> Reply:
        pid = (query.get("project") or "").strip() or None
        if pid is not None and pid not in {p.pid for p in self.factory.projects()}:
            raise _server().ApiError(404, f"no project {pid}")
        out = kchoice.view(self.factory, pid=pid, look=query.get("check") in ("1", "true"))
        return 200, out | {"cards_project": FACTORY_PID}      # where a runner card is decided

    def put_runner(self, role: str, body: dict[str, Any], **_: object) -> Reply:
        if role not in ROLES:
            raise _server().ApiError(404, f"no role {role}")
        person, persona = self._who(body, FACTORY_PID)
        _server()._require_person(person, persona)
        endpoints = body.get("endpoints") if isinstance(body.get("endpoints"), list) else []
        made = kchoice.propose(
            self.factory, role=role, runner=_text(body, "runner", 32), scope=_text(body, "project", 64) or None,
            person=person, persona=persona, reason=_text(body, "reason", 2000),
            version=_text(body, "version", 100) or None,
            model=_text(body, "model", 200) or None, family=_text(body, "family", 64) or None,
            command=_text(body, "command", 2000) or None, sandbox=_text(body, "sandbox", 16) or "off",
            image=_text(body, "image", 300) or None, endpoints=[str(e)[:200] for e in endpoints[:8]])
        return 200, {"choice": made}
