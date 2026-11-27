"""Observer links' guards (FR-SHR2): the rules that keep sharing private, quiet and within what the sharer holds.

The owner (2026-11-26) asked for observer links to be fixed after an independent check: "Fix every one". Each rule
here answers one finding (kernel/observe.py, kernel/observe_view.py and cockpit/observe_routes.py call them):

- **a pause stays paused**: whether a sharer shows guests the view they are on is kept on the server (in memory, as
  where they are). Only an explicit pause or resume changes it, from the Share page or from Ask Rihma; the page's
  heartbeat says only where the person is and never undoes a pause. After a restart, when the server remembers
  nothing, the page's own last word (``hint``) stands until the person changes it;
- **following says only what the link covers, in plain words**: a project-only link says "elsewhere" whenever the
  sharer is on something without that project (Settings, Share, a view across projects); a platform-wide link names
  a view across projects only when it is one a guest could understand, in words, never a route id;
- **a guest cannot flood**: at most ``PER_WINDOW`` comments and as many suggestions per link in ``WINDOW_MINUTES``;
- **team mode stays within grants**: with access enforced, a platform-wide link shows only the projects the sharer
  was granted when they made it (``within``); the Share page's read shows a person only the links, comments,
  suggestions and projects their grants cover (``readable``); a link is revoked by the person who made it, or by
  someone granted on every project (``may_revoke``). A single operator sees and does everything, as before.
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any

PER_WINDOW = 10            # comments (and, apart, suggestions) one link may send in a window
WINDOW_MINUTES = 10
TOO_FAST = (f"You have sent {PER_WINDOW} in {WINDOW_MINUTES} minutes: wait a few minutes, then send again. "
            "The person who shared reads every one.")

# a project's view, as a guest reads it
PROJECT_WORDS = {
    "overview": "the overview", "plan": "the plan", "inbox": "the decisions waiting", "questions": "the questions",
    "assumptions": "the assumptions", "spec": "the spec and contract", "tasks": "the tasks", "track": "the track",
    "ledger": "the activity", "evidence": "the evidence", "review": "the review", "agents": "the agent channel",
    "agent_sessions": "the agent sessions", "checks": "the health checks", "insights": "the insights",
    "releases": "the releases", "changes": "the changes", "outputs": "the outputs", "assessment": "the assessment",
    "graph": "the knowledge graph", "context": "the context", "incidents": "the incidents",
}
# a view across projects a guest on a platform-wide link may be told about; any other (Settings, Share, People,
# Models, Integrations, a project-less page) says only "elsewhere"
ACROSS_WORDS = {
    "home": "the home page", "projects": "the project list", "inbox_all": "the decisions waiting across projects",
    "review_all": "the review across projects", "agents_all": "the agent activity across projects",
    "insights_all": "the insights across projects", "health_all": "the health across projects",
    "decide": "deciding what matters",
}

_PAUSED: dict[tuple[str, str], bool] = {}       # (home, person) -> paused: in memory, recorded nowhere
_LOCK = threading.Lock()


class GuestTooFast(Exception):
    """A guest sent more than a link allows in the window: the page answers 429 with these words."""


# -- a pause stays paused ------------------------------------------------------------------------------------

def paused_now(home: str, person: str, paused: bool | None, hint: bool | None = None) -> bool:
    """Whether the person's view is hidden from guests now: ``paused`` True or False changes it; None (the
    heartbeat) keeps what the server holds, or, when it holds nothing (after a restart), takes the page's ``hint``."""
    key = (home, person)
    with _LOCK:
        if paused is not None:
            _PAUSED[key] = bool(paused)
        elif key not in _PAUSED:
            _PAUSED[key] = bool(hint)
        if len(_PAUSED) > 5000:
            _PAUSED.clear()
            _PAUSED[key] = bool(paused if paused is not None else hint)
        return _PAUSED[key]


def body_paused(body: dict[str, Any]) -> tuple[bool | None, bool | None]:
    """A presence request's explicit pause (True, False, or None for a heartbeat) and the page's hint."""
    paused = body.get("paused")
    hint = body.get("was_paused")
    return (paused if isinstance(paused, bool) else None), (hint if isinstance(hint, bool) else None)


# -- following within the link, in words ---------------------------------------------------------------------

def where_shown(link: dict[str, Any], where: dict[str, Any], ids: dict[str, str]) -> dict[str, Any] | None:
    """What a guest is told about the sharer's place: None for "elsewhere" (never says where); else the project
    (or None), the view's id (for the page to follow) and its words."""
    pid, view = where.get("project"), str(where.get("view") or "")
    if pid:
        if pid not in ids:
            return None
        return {"project": pid, "view": view, "view_words": PROJECT_WORDS.get(view, "a view of the project")}
    if link.get("scope") != "platform" or view not in ACROSS_WORDS:
        return None
    return {"project": None, "view": view, "view_words": ACROSS_WORDS[view]}


# -- a guest cannot flood ------------------------------------------------------------------------------------

def _at(stamp: Any) -> dt.datetime | None:
    try:
        found = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=dt.UTC)


def check_rate(rows: list[dict[str, Any]], link_id: str, now: dt.datetime) -> None:
    """Refuse (GuestTooFast) a guest's comment or suggestion when the link sent PER_WINDOW in the window."""
    since = now - dt.timedelta(minutes=WINDOW_MINUTES)
    recent = 0
    for r in rows:
        at = _at(r.get("at"))
        if r.get("link") == link_id and at is not None and at > since:
            recent += 1
    if recent >= PER_WINDOW:
        raise GuestTooFast(TOO_FAST)


# -- team mode stays within grants ---------------------------------------------------------------------------

def _enforced(access: Any, ident: Any) -> bool:
    return access is not None and bool(getattr(access, "enforced", False)) and ident is not None


def _covers(access: Any, ident: Any, pid: str | None) -> bool:
    from kernel import access as kaccess

    return bool(kaccess.personas(access, ident, pid))


def _everywhere(access: Any, ident: Any) -> bool:
    from kernel import access as kaccess
    from kernel.accessfile import ALL

    return any(ALL in b.scope for b in kaccess.grants(access, ident))


def within(access: Any, ident: Any, pids: list[str]) -> list[str] | None:
    """The projects a platform-wide link may show: None (every one) for a single operator or someone granted
    every project; else those of ``pids`` the sharer holds a persona on, kept with the link."""
    if not _enforced(access, ident) or _everywhere(access, ident):
        return None
    return sorted(p for p in pids if _covers(access, ident, p))


def may_revoke(access: Any, ident: Any, link: dict[str, Any], person: str) -> bool:
    """A single operator revokes any link; with access enforced, the person who made it, or someone granted on
    every project."""
    if not _enforced(access, ident):
        return True
    return link.get("created_by") == person or _everywhere(access, ident)


def readable(access: Any, ident: Any, out: dict[str, Any], seen: set[str]) -> dict[str, Any]:
    """The Share page's read as this reader may see it: with access enforced, their own links and the links,
    comments and suggestions on projects their grants cover (a platform-wide one only for someone granted every
    project), and only those projects. ``seen``: the project ids the reader's factory shows."""
    if not _enforced(access, ident):
        return out
    every = _everywhere(access, ident)
    mine = {p for p in seen if _covers(access, ident, p)}

    def link_ok(r: dict[str, Any]) -> bool:
        if r.get("created_by") == ident.name:
            return True
        return every if r.get("scope") == "platform" else r.get("project") in mine

    links = [r for r in out["links"] if link_ok(r)]
    return {**out, "links": links,
            "comments": [c for c in out["comments"] if c.get("project") in mine],
            "suggestions": [s for s in out["suggestions"] if s.get("project") in mine],
            "projects": [p for p in out["projects"] if p["pid"] in mine]}
