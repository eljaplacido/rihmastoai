"""The cockpit's routes for the review (FR-REV1): since you last looked, reviewed in place.

Reads record nothing: the review across a person's projects (``GET /api/review``) or one project's
(``GET /api/projects/<pid>/review``), one item's preview for the drawer (its diff, signals and facts), and
the person's morning digest with the receivers they may choose. The writes are signed by a person and persona
as every other write route is (with access enforced, the verified identity, granted the persona where the write
acts): ``review/mark`` records ``review_marked`` per item in the item's project, ``review/done`` records
``review_done`` and moves the person's marker, ``review/digest`` sets their digest. Deciding a card, settling an
assumption, revoking a delegation or reporting a change from the review goes through those routes' own paths.
"""

from __future__ import annotations

from typing import Any

from kernel import review as kreview
from kernel import review_digest as kdigest
from kernel import review_marks as kmarks
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>_factory|[a-z0-9][a-z0-9-]{0,80})"
ROUTES = [
    ("GET", r"/api/review", "get_review"),
    ("GET", rf"/api/projects/{PID}/review", "get_project_review"),
    ("GET", rf"/api/projects/{PID}/review/detail", "get_review_detail"),
    ("GET", r"/api/review/digest", "get_review_digest"),
    ("POST", r"/api/review/mark", "post_review_mark"),
    ("POST", r"/api/review/done", "post_review_done"),
    ("PUT", r"/api/review/digest", "put_review_digest"),
]
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


def _text(body: dict[str, Any], key: str, *, limit: int = 200) -> str:
    return str(_server()._text(body, key, limit=limit))


class ReviewRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``access``, ``identity`` and ``_sign``."""

    server: Any
    factory: Any
    access: Any
    identity: Any

    def _sign(self, person: str, persona: str, pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _audit(self, project: Any, action: str, target: str | None, person: str, persona: str,
               **extra: Any) -> None:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _review_jobs(self) -> list[dict[str, Any]]:
        """The cockpit's background jobs, as the Jobs page shows them, for the failed ones among them."""
        with self.server._jobs_lock:
            jobs = list(self.server.jobs)
        return [self.server.job_view(j) for j in jobs]

    def _review_visible(self) -> Any:
        """With access enforced, the projects the verified identity holds a persona on; else every project."""
        if not self.access.enforced or self.identity is None:
            return None
        from kernel import access as kaccess

        return lambda pid: bool(kaccess.personas(self.access, self.identity, pid))

    def _review(self, query: dict[str, Any], pid: str | None) -> Reply:
        if pid is not None:
            try:
                self.factory.project(pid)
            except KeyError:
                raise _error(404, f"no project {pid}") from None
        person = str(query.get("person") or "")[:200]
        if self.access.enforced and self.identity is not None:
            person = self.identity.name                 # with access enforced: the verified person's own review
        out = kreview.review(self.factory, person=person, persona=str(query.get("persona") or "")[:64], project=pid,
                             since=query.get("since") or None, jobs=self._review_jobs(), visible=self._review_visible())
        return 200, out

    # reads

    def get_review(self, query: dict[str, Any], **_: object) -> Reply:
        return self._review(query, query.get("project") or None)

    def get_project_review(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        return self._review(query, pid)

    def get_review_detail(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        """One item's preview: ``?item=task/T-001`` (or the whole id). Without one, it says what to name."""
        name = str(query.get("item") or "").strip()
        if not name:
            return 200, {"item": None, "why": "name an item: ?item=task/T-001"}
        item_id = name if name.startswith(pid + "/") else f"{pid}/{name}"
        try:
            return 200, kreview.detail(self.factory, item_id, person=str(query.get("person") or "")[:200],
                                       persona=str(query.get("persona") or "")[:64])
        except KeyError:
            raise _error(404, f"no review item {item_id}") from None

    def get_review_digest(self, query: dict[str, Any], **_: object) -> Reply:
        person, persona = str(query.get("person") or "").strip(), str(query.get("persona") or "")
        mine = kdigest.digests(self.factory, person) if person else []
        return 200, {"digest": mine[-1] if mine else None, "template": kdigest.TEMPLATE,
                     "receivers": kdigest.receivers(self.factory, persona or None)}

    # writes

    def post_review_mark(self, body: dict[str, Any], **_: object) -> Reply:
        items = body.get("items")
        if not isinstance(items, list) or not items or not all(isinstance(i, str) for i in items):
            raise _error(400, "items is a list of review items, such as [\"<project>/task/T-001\"]")
        person, persona = _text(body, "person"), _text(body, "persona", limit=64)
        signed = None
        for pid in dict.fromkeys(kmarks.parse_item(i)[0] for i in items):
            signed = self._sign(person, persona, pid)       # granted on every project it marks, or refused
        person, persona = signed or (person, persona)
        marked = kmarks.mark(self.factory, list(items), person=person, persona=persona,
                             note=_text(body, "note", limit=500))
        for m in marked:
            self._audit(self.factory.project(m["project"]), "review_mark", m["item"], person, persona)
        return 201, {"marked": marked}

    def post_review_done(self, body: dict[str, Any], **_: object) -> Reply:
        pid = _text(body, "project", limit=100) or None
        person, persona = self._sign(_text(body, "person"), _text(body, "persona", limit=64), pid or FACTORY_PID)
        if pid is not None:
            try:
                self.factory.project(pid)
            except KeyError:
                raise _error(404, f"no project {pid}") from None
        since = _text(body, "since", limit=64) or None
        done = kmarks.done(self.factory, person=person, persona=persona, project=pid, since=since,
                           jobs=self._review_jobs())
        self._audit(self.factory.project(done["ledger"]), "review_done", pid or "all", person, persona)
        return 201, {"done": done}

    def put_review_digest(self, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._sign(_text(body, "person"), _text(body, "persona", limit=64), FACTORY_PID)
        off = body.get("off") is True
        entry = kdigest.set_digest(self.factory, person=person, persona=persona,
                                   subscription=_text(body, "subscription", limit=32) or None,
                                   at=_text(body, "at", limit=8) or "07:30",
                                   days=_text(body, "days", limit=40) or "weekdays",
                                   tz=_text(body, "tz", limit=64) or "UTC", off=off)
        self._audit(self.factory.project(FACTORY_PID), "review_digest", entry.get("subscription"), person, persona)
        return 200, {"digest": entry}
