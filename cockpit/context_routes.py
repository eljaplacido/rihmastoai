"""The cockpit's routes for the data and context layer (FR-CTX1, docs/guides/context-and-data.md).

Reads write nothing:

- ``GET /api/projects/<pid>/context-map``: the context map and every pack in one row each;
- ``GET /api/projects/<pid>/context/pack?pack=&persona=&target=&question=``: one pack, part by part. Its content
  is shown only to a persona that may see it (with access enforced, one granted on the project), and anything of
  the holdout custody never;
- ``GET /api/projects/<pid>/context/audit``: the project's compression audit;
- ``GET /api/context/health``: the factory's Context health per role, the findings and what FR-CTX1 compressed;
- ``GET /api/data``: the factory home's stores, ledgers and their integrity, retention and what can be cleaned.

Writes are signed by a person and persona as the other write routes are, and recorded in Rihma's own ledger:
``POST /api/data/cleanup`` proposes a clean-up, ``POST /api/data/cleanup/<CU-id>/apply`` carries one out.
"""

from __future__ import annotations

from typing import Any

from kernel import context_audit, context_map, context_packs, context_parts, data_stores

PID = r"(?P<pid>_factory|[a-z0-9][a-z0-9-]{0,80})"   # as cockpit/server.py PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/context-map", "get_context_map"),
    ("GET", rf"/api/projects/{PID}/context/pack", "get_context_pack"),
    ("GET", rf"/api/projects/{PID}/context/audit", "get_context_audit"),
    ("GET", r"/api/context/health", "get_context_health"),
    ("GET", r"/api/data", "get_data"),
    ("POST", r"/api/data/cleanup", "post_data_cleanup"),
    ("POST", r"/api/data/cleanup/(?P<cid>CU-\d{1,6})/apply", "post_data_apply"),
]
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


class ContextRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``access``, ``identity``, ``_project`` and ``_who``."""

    factory: Any
    access: Any
    identity: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _viewer(self, query: dict[str, Any], pid: str) -> str | None:
        """The persona whose view a read shows: as asked, and with access enforced only one granted on ``pid``."""
        persona = query.get("persona") or None
        if persona is None or not getattr(self.access, "enforced", False):
            return persona
        from kernel import access as kaccess

        granted = kaccess.personas(self.access, self.identity, pid) if self.identity is not None else []
        return persona if persona in granted else None

    def get_context_map(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        persona = self._viewer(query, pid)
        rows = [p if "unavailable" in p else context_parts.summary(p)
                for p in context_packs.every(self.factory, project, persona=persona)]
        return 200, {"map": context_map.context_map(self.factory, project), "packs": rows, "persona": persona}

    def get_context_pack(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        from kernel.custody import held_strings

        project = self._project(pid)
        pack = str(query.get("pack") or "assistant")
        persona = self._viewer(query, pid)
        try:
            built = context_packs.build(self.factory, project, pack, target=query.get("target") or None,
                                        persona=persona, question=(query.get("question") or "")[:2000] or None)
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None
        except context_packs.Unavailable as exc:
            return 200, {"id": pack, "label": context_packs.LABELS.get(pack, pack), "unavailable": str(exc)}
        held = held_strings(self.factory.holdouts_dir, self.factory.projects_dir)
        out = context_parts.shown(built, persona, held)
        for o in out.get("outputs") or []:
            o["content"] = o["content"] if out["content_shown"] else None
        return 200, out

    def get_context_audit(self, pid: str, **_: object) -> Reply:
        self._project(pid)
        return 200, context_audit.audit(self.factory, pid, commands=False)

    def get_context_health(self, **_: object) -> Reply:
        doc = context_audit.audit(self.factory, commands=False)
        return 200, {k: doc[k] for k in ("health", "findings", "counts", "fixes", "tokens")} | {
            "projects": [{k: p[k] for k in ("project", "title")} for p in doc["projects"]]}

    def get_data(self, **_: object) -> Reply:
        return 200, data_stores.view(self.factory)

    def post_data_cleanup(self, body: dict[str, Any], **_: object) -> Reply:
        from kernel.learn import FACTORY_PID

        person, persona = self._who(body, FACTORY_PID)
        return 201, {"proposal": data_stores.propose_cleanup(self.factory, person=person, persona=persona)}

    def post_data_apply(self, cid: str, body: dict[str, Any], **_: object) -> Reply:
        from kernel.learn import FACTORY_PID

        person, persona = self._who(body, FACTORY_PID)
        try:
            return 200, {"proposal": data_stores.apply_cleanup(self.factory, cid, person=person, persona=persona)}
        except KeyError as exc:
            raise _error(404, str(exc.args[0] if exc.args else exc)) from None
