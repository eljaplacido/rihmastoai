"""The cockpit's routes for machines, asks between agents and machines, and the reachability doctor (FR-XAG1, FR-RCH1).

- ``GET /api/machines``: the machines with how each is reached, its system and agents, the scope (platform-wide) and
  who may change the list; ``POST /api/machines`` adds or changes one, ``POST /api/machines/remove`` removes one;
  both signed;
- ``POST /api/reach`` ``{target}``: tests a machine, a project's working copy, an https address or ``github``; the
  verdict, the fix and (when something is not reachable) a drafted ask. It runs one read-only test and records
  nothing;
- ``GET /api/asks``: what waits on other agents across projects; ``GET /api/projects/<pid>/asks`` a project's asks;
- ``POST /api/projects/<pid>/asks``: puts an ask (``to``, ``text``, ``why``, ``expects``, ``machine``, ``days``,
  ``source``), signed;
- ``POST /api/projects/<pid>/asks/<aid>/copy``: the self-contained message for the other agent (counts as delivered);
- ``POST /api/projects/<pid>/asks/<aid>/answer`` ``{text}``: the answer pasted back; ``…/withdraw``; ``…/link``
  ``{hours}``: a reply link, shown once.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import asks, hitl_links, machines, reach
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"     # as cockpit/server.py's PID
AID = r"(?P<aid>AK-\d{4,6})"
ROUTES = [
    ("GET", r"/api/machines", "get_machines"),
    ("POST", r"/api/machines", "post_machine"),
    ("POST", r"/api/machines/remove", "post_machine_remove"),
    ("POST", r"/api/reach", "post_reach"),
    ("GET", r"/api/asks", "get_asks"),
    ("GET", rf"/api/projects/{PID}/asks", "get_project_asks"),
    ("POST", rf"/api/projects/{PID}/asks", "post_ask"),
    ("POST", rf"/api/projects/{PID}/asks/{AID}/copy", "post_ask_copy"),
    ("POST", rf"/api/projects/{PID}/asks/{AID}/answer", "post_ask_answer"),
    ("POST", rf"/api/projects/{PID}/asks/{AID}/withdraw", "post_ask_withdraw"),
    ("POST", rf"/api/projects/{PID}/asks/{AID}/link", "post_ask_link"),
]
UNLOCKED = {"post_reach"}          # a test records nothing: it never waits for another write
Reply = tuple[int, dict[str, Any]]
_TARGET = re.compile(r"[A-Za-z0-9:/._@\\-]{1,300}\Z")


def _text(body: dict[str, Any], key: str, limit: int) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} is text of at most {limit} characters")
    return value


class AskRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``server``, ``_project`` and ``_who``."""

    factory: Any
    server: Any

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _ask_base(self) -> str:
        """Where a reply link points: the trusted https front when one is set, else this cockpit as reached."""
        return (getattr(self.server, "public_origin", None) or getattr(self, "request_origin", "")
                or self.server.origin).rstrip("/")

    # -- machines --------------------------------------------------------------------------------------------

    def get_machines(self, **_: Any) -> Reply:
        return 200, machines.describe(self.factory)

    def post_machine(self, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        fields = {k: body[k] for k in ("name", "reach", "address", "os", "agents", "note") if k in body}
        return 200, machines.add(self.factory, fields, person=person, persona=persona)

    def post_machine_remove(self, body: dict[str, Any], **_: Any) -> Reply:
        person, persona = self._who(body, FACTORY_PID)
        return 200, machines.remove(self.factory, _text(body, "name", 41), person=person, persona=persona)

    # -- the doctor ------------------------------------------------------------------------------------------

    def post_reach(self, body: dict[str, Any], **_: Any) -> Reply:
        target = _text(body, "target", 300).strip()
        if not _TARGET.match(target):
            raise ValueError("name what to test: a machine, a project, an https:// address or github")
        if target in {p.pid for p in self.factory.projects()}:
            self._project(target)              # a member tests only projects they see
        return 200, reach.doctor(self.factory, target)

    # -- asks ------------------------------------------------------------------------------------------------

    def get_asks(self, **_: Any) -> Reply:
        return 200, asks.summary(self.factory)

    def get_project_asks(self, pid: str, **_: Any) -> Reply:
        project = self._project(pid)
        return 200, {"project": pid, "asks": asks.listed(project),
                     "machines": [m["name"] for m in machines.listed(self.factory)]}

    def post_ask(self, pid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        days = body.get("days")
        return 200, asks.create(project, to=_text(body, "to", 41), text=_text(body, "text", asks.TEXT_LIMIT),
                                why=_text(body, "why", asks.WHY_LIMIT), expects=_text(body, "expects",
                                                                                      asks.EXPECTS_LIMIT),
                                machine=_text(body, "machine", 41) or None,
                                days=int(days) if isinstance(days, int) else None,
                                source=body.get("source") if isinstance(body.get("source"), dict) else None,
                                person=person, persona=persona)

    def post_ask_copy(self, pid: str, aid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, asks.copy_text(project, aid, person=person, persona=persona)

    def post_ask_answer(self, pid: str, aid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, asks.answer(project, aid, _text(body, "text", 8000), person=person, persona=persona)

    def post_ask_withdraw(self, pid: str, aid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        return 200, asks.withdraw(project, aid, person=person, persona=persona)

    def post_ask_link(self, pid: str, aid: str, body: dict[str, Any], **_: Any) -> Reply:
        project = self._project(pid)
        person, persona = self._who(body, pid)
        hours = body.get("hours")
        base = self._ask_base()
        return 200, asks.reply_link(project, aid, person=person, persona=persona, base=base,
                                    hours=int(hours) if isinstance(hours, int) else None,
                                    local=hitl_links.local_only(base))
