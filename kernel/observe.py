"""Observer links (FR-SHR1): a time-limited, read-only view of your work for a colleague.

The owner (2026-11-26): "it would be really useful to share temporary access to view users current doings in
rihmasto as observer, let say you want to invite colleague to check work or defining a project together".

A person (the sharer) makes an **observer link** for one project or for every project (the platform scope), for
an hour, a day or a week, optionally naming the guest. The link:

- is shown once: only its sha256 is kept, with its expiry, as the one-use links for people outside are
  (kernel/hitl_links.py). Its token travels after ``#``, so no server, log or preview receives it;
- opens a read-only page (``/o/``, kernel/observe_page.py) as many times as needed until it expires or is revoked;
  each opening is a visit, recorded in the ledger, and gives that browser tab its own session;
- is revoked at once: a revoke ends every session it opened, and the link is refused from then on;
- never shows a confidential project unless the sharer ticked it explicitly; a project link for a confidential
  project cannot be made without that tick.

The guest watches: the views in scope, the agent channel, and (following) the view the sharer is on and the
sharer's latest actions. A guest may comment (signed with their name, marked as a guest) and, when the sharer
allowed it on a project link, suggest answers to the project's open intake questions, which wait for a person to
confirm or decline (``decide_suggestion``). A guest never decides, runs, changes a setting or sees a secret.
Nothing is ever sent anywhere: the link is given to the sharer to pass on.

Links, comments and suggestions are kept factory-wide (``_factory/observe_links.json``) so the page finds a link by
its hash alone. Who is watching now and the sharer's current view are kept in memory only: they record nothing.
"""

from __future__ import annotations

import datetime as dt
import hmac
import re
import secrets
import threading
import time
from typing import Any

from kernel import hitl_links, observe_guard
from kernel.canon import Canon, DecisionRefused
from kernel.confidential import confidential as is_confidential
from kernel.learn import FACTORY_PID, factory_project
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, Project, read_json, updating_json

FILE = "observe_links.json"
DURATIONS = {1: "an hour", 24: "a day", 168: "a week"}     # hours -> words
SCOPES = ("project", "platform")
PAGE_PATH = "/o/"
WATCHING_SECONDS = 45          # a guest whose page asked within this is watching now
PRESENCE_SECONDS = 120         # a sharer's view older than this is not followed
MAX_SESSIONS = 20
MAX_COMMENT = 2000
_TOKEN = re.compile(r"o[bs]_[A-Za-z0-9_-]{20,80}\Z")
_SEEN: dict[tuple[str, str, str], tuple[float, str]] = {}     # (home, link, session hash) -> (when, guest)
_PRESENCE: dict[tuple[str, str], dict[str, Any]] = {}          # (home, person) -> where the sharer is
_LOCK = threading.Lock()


class ObserveRefused(PermissionError):
    """A link or a session the observer page does not take: the words say what to do instead."""


def _path(factory: Factory) -> Any:
    return factory.projects_dir.joinpath(FACTORY_PID, FILE)       # kept beside the outside reviewers' links


def _blank() -> dict[str, Any]:
    return {"links": [], "comments": [], "suggestions": []}


def _load(factory: Factory) -> dict[str, Any]:
    found = read_json(_path(factory), None)
    return {**_blank(), **found} if isinstance(found, dict) else _blank()


def links(factory: Factory) -> list[dict[str, Any]]:
    return list(_load(factory)["links"])


_sha = hitl_links._sha       # a link's or a session's hash: the only form either is kept in, as for reviewers' links


def _stamp(at: dt.datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _next(rows: list[dict[str, Any]], prefix: str) -> str:
    n = max([int(str(r["id"]).split("-")[1]) for r in rows], default=0) + 1
    return f"{prefix}-{n:03d}"


def state_of(factory: Factory, link: dict[str, Any]) -> str:
    """active, revoked or expired."""
    if link.get("state") == "revoked":
        return "revoked"
    try:
        ends = dt.datetime.fromisoformat(str(link["expires"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return "expired"
    return "expired" if factory.clock.now() >= ends else "active"


def watching(factory: Factory, link: dict[str, Any]) -> list[str]:
    """The guests whose page asked in the last WATCHING_SECONDS, while the link is active."""
    if state_of(factory, link) != "active":
        return []
    now, home = time.monotonic(), str(factory.home)
    live = {s for s in link.get("sessions") or []}
    with _LOCK:
        return sorted({guest for (h, lid, s), (at, guest) in _SEEN.items()
                       if h == home and lid == link["id"] and s in live and now - at < WATCHING_SECONDS})


def public(factory: Factory, link: dict[str, Any]) -> dict[str, Any]:
    """A link as the cockpit shows it: never its hash or its sessions."""
    keep = ("id", "scope", "project", "guest", "confidential", "intake", "expires", "created_by", "created_persona",
            "at", "last_opened", "opens", "revoked_by", "revoked_at")
    return {k: link.get(k) for k in keep} | {"state": state_of(factory, link), "watching": watching(factory, link),
                                              "hours": link.get("hours")}


def scope_title(factory: Factory, link: dict[str, Any]) -> str:
    if link["scope"] == "platform":
        every = "every project" if link.get("within") is None else "every project its sharer holds"
        return every + (" (confidential ones too)" if link.get("confidential") else "")
    try:
        return str(factory.project(link["project"]).meta.get("title") or link["project"])
    except KeyError:
        return str(link["project"])


def in_scope(factory: Factory, link: dict[str, Any]) -> list[Project]:
    """The projects a link shows: its one project, or every project; a confidential one only when ticked."""
    if link["scope"] == "project":
        try:
            found = [factory.project(link["project"])]
        except KeyError:
            return []
    else:
        found = [p for p in factory.projects() if p.pid != FACTORY_PID]
        if link.get("within") is not None:       # a sharer kept to some projects shares only those (FR-SHR2)
            found = [p for p in found if p.pid in link["within"]]
    return [p for p in found if link.get("confidential") or not is_confidential(p)]


def _ledger(factory: Factory, link: dict[str, Any]) -> Project:
    """Where a link's records go: its project's ledger, or the factory's for every project."""
    if link["scope"] == "project":
        try:
            return factory.project(link["project"])
        except KeyError:
            pass
    return factory_project(factory)


def _checked(person: str, persona: str, scope: str, hours: int) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: an observer link is given by a named person")
    if persona not in PERSONAS:
        raise ValueError(f"persona is one of {', '.join(PERSONAS)}")
    if scope not in SCOPES:
        raise ValueError("scope is project (one project) or platform (every project)")
    if isinstance(hours, bool) or hours not in DURATIONS:
        raise ValueError("a link lasts an hour (1), a day (24) or a week (168)")


def _shared_project(factory: Factory, scope: str, project: str | None, confidential: bool, intake: bool) -> str | None:
    """The project a link shares (None: every project), refused when it may not be shared so."""
    if scope == "platform":
        if intake:
            raise ValueError("a guest suggests intake answers on one project's link, not on every project's")
        return None
    try:
        p = factory.project(str(project or ""))
    except KeyError:
        raise ValueError(f"no project {project!r}: name the project to share") from None
    if p.pid == FACTORY_PID:
        raise ValueError("share a project, or every project (scope platform)")
    if is_confidential(p) and not confidential:
        raise ValueError(f"{p.meta.get('title') or p.pid} is confidential: tick \"Include confidential "
                         "projects\" to share it, or share another project")
    return p.pid


def create(factory: Factory, *, scope: str, project: str | None, hours: int, guest: str = "", person: str,
           persona: str, confidential: bool = False, intake: bool = False) -> dict[str, Any]:
    """An observer link. Returns the record with ``token``: never kept, never shown again."""
    _checked(person, persona, scope, hours)
    guest = re.sub(r"\s+", " ", str(guest or "")).strip()[:80]
    project = _shared_project(factory, scope, project, confidential, intake)
    token = "ob_" + secrets.token_urlsafe(32)
    within = _within(factory) if scope == "platform" else None
    with updating_json(_path(factory), _blank()) as kept:
        rows = kept.setdefault("links", [])
        link: dict[str, Any] = {
            "id": _next(rows, "OL"), "scope": scope, "project": project, "guest": guest,
            "confidential": bool(confidential), "intake": bool(intake), "hours": hours,
            "link_sha256": _sha(token), "sessions": [], "state": "active",
            "expires": _stamp(factory.clock.now() + dt.timedelta(hours=hours)), "created_by": person,
            "created_persona": persona, "at": factory.clock.stamp(), "last_opened": None, "opens": 0}
        if within is not None:
            link["within"] = within
        rows.append(link)
    _ledger(factory, link).log("observe_link_given", {
        "link": link["id"], "scope": scope, "project": project, "guest": guest or None, "expires": link["expires"],
        "confidential": link["confidential"], "intake": link["intake"], "person": person, "persona": persona})
    return {**link, "token": token}


def _within(factory: Factory) -> list[str] | None:
    """The projects a platform-wide link may show: every one, unless access is enforced and the signer holds
    only some (FR-SHR2)."""
    from kernel import access as kaccess
    from kernel.people import SIGNER

    pids = [p.pid for p in factory.projects() if p.pid != FACTORY_PID]
    return observe_guard.within(kaccess.load(factory), SIGNER.get(), pids)


def revoke(factory: Factory, link_id: str, *, person: str, persona: str) -> dict[str, Any]:
    """End a link and every session it opened, at once. With access enforced, by the person who made it or by
    someone granted on every project (FR-SHR2)."""
    from kernel import access as kaccess
    from kernel.people import SIGNER

    if not is_person(person) or persona not in PERSONAS:
        raise DecisionRefused("an observer link is revoked by a named person")
    with updating_json(_path(factory), _blank()) as kept:
        link = next((r for r in kept.setdefault("links", []) if r["id"] == link_id), None)
        if link is None:
            raise KeyError(f"no observer link {link_id}")
        if not observe_guard.may_revoke(kaccess.load(factory), SIGNER.get(), link, person):
            raise DecisionRefused(f"{link_id} was made by {link['created_by']}: they revoke it, or someone granted "
                                  "on every project")
        link.update(state="revoked", revoked_by=person, revoked_at=factory.clock.stamp())   # its sessions end with it
    _ledger(factory, link).log("observe_link_revoked", {"link": link_id, "person": person, "persona": persona})
    return public(factory, link)


def find(factory: Factory, link_id: str) -> dict[str, Any]:
    found = next((r for r in links(factory) if r["id"] == link_id), None)
    if found is None:
        raise KeyError(f"no observer link {link_id}")
    return found


def url(base: str, token: str) -> str:
    """The address the guest opens: the token after #, never sent to a server."""
    return f"{base.rstrip('/')}{PAGE_PATH}#{token}"


# -- the page's side -------------------------------------------------------------------------------------

def _match(rows: list[dict[str, Any]], token: str, sessions: bool) -> dict[str, Any] | None:
    if not _TOKEN.match(str(token or "")):
        return None
    digest = _sha(token)
    for r in rows:
        kept = (r.get("sessions") or []) if sessions else [r.get("link_sha256") or ""]
        if any(hmac.compare_digest(str(k), digest) for k in kept):
            return r
    return None


def _closed(factory: Factory, link: dict[str, Any]) -> str | None:
    state = state_of(factory, link)
    if state == "revoked":
        return f"{link.get('revoked_by') or link['created_by']} stopped sharing. Ask them for a new link if you " \
               "still need to watch."
    if state == "expired":
        return f"This link has expired. Ask {link['created_by']} for a new one."
    return None


def open_link(factory: Factory, token: str) -> dict[str, Any]:
    """Open a link: a new session for this tab, and a visit in the ledger. ObserveRefused says why not."""
    session = "os_" + secrets.token_urlsafe(32)
    with updating_json(_path(factory), _blank()) as kept:
        link = _match(kept.setdefault("links", []), token, sessions=False)
        if link is None:
            raise ObserveRefused("This link is not valid. Ask the person who shared it for a new one.")
        why = _closed(factory, link)
        if why:
            raise ObserveRefused(why)
        link["sessions"] = [*(link.get("sessions") or []), _sha(session)][-MAX_SESSIONS:]
        link.update(last_opened=factory.clock.stamp(), opens=int(link.get("opens") or 0) + 1)
    _ledger(factory, link).log("observe_visit", {"link": link["id"], "guest": link.get("guest") or "a guest",
                                                 "by_guest": True, "visit": link["opens"]})
    return {"session": session, "expires": link["expires"], "link": link["id"]}


def session(factory: Factory, token: str) -> dict[str, Any]:
    """The link a page session belongs to, while it is open (and the guest counts as watching); else refused."""
    link = _match(links(factory), token, sessions=True)
    if link is None:
        raise ObserveRefused("Your session has ended. Open the link you were given again, or ask for a new one.")
    why = _closed(factory, link)
    if why:
        raise ObserveRefused(why)
    with _LOCK:
        if len(_SEEN) > 5000:
            _SEEN.clear()
        _SEEN[(str(factory.home), link["id"], _sha(token))] = (time.monotonic(), link.get("guest") or "a guest")
    return link


def guest_of(link: dict[str, Any]) -> str:
    return link.get("guest") or "A guest"


def _scoped(factory: Factory, link: dict[str, Any], pid: str) -> Project:
    found = next((p for p in in_scope(factory, link) if p.pid == pid), None)
    if found is None:
        raise ObserveRefused("That project is not shared with you.")
    return found


def comment(factory: Factory, link: dict[str, Any], pid: str, text: str, about: str = "") -> dict[str, Any]:
    """A guest's comment on a project in scope: signed with the guest's name, marked as a guest's."""
    project = _scoped(factory, link, pid)
    text = str(text or "").strip()
    if not text or len(text) > MAX_COMMENT:
        raise ValueError(f"a comment is 1 to {MAX_COMMENT} characters")
    with updating_json(_path(factory), _blank()) as kept:
        rows = kept.setdefault("comments", [])
        observe_guard.check_rate(rows, link["id"], factory.clock.now())     # a guest cannot flood (FR-SHR2)
        row = {"id": _next(rows, "GC"), "link": link["id"], "project": project.pid, "guest": guest_of(link),
               "by_guest": True, "about": str(about or "")[:60], "text": text, "at": factory.clock.stamp(),
               "for": link["created_by"]}
        rows.append(row)
    project.log("observe_comment", {"comment": row["id"], "link": link["id"], "guest": row["guest"],
                                    "by_guest": True, "about": row["about"], "chars": len(text)})
    return row


def comments(factory: Factory, *, link: dict[str, Any] | None = None, project: str | None = None) -> list[dict]:
    rows = _load(factory)["comments"]
    return [r for r in rows
            if (link is None or r["link"] == link["id"]) and (project is None or r["project"] == project)]


def open_questions(project: Project) -> list[dict[str, Any]]:
    return [{"id": q["id"], "text": q.get("text", ""), "options": q.get("options") or []}
            for q in Canon(project).questions("open")]


def suggest(factory: Factory, link: dict[str, Any], qid: str, text: str) -> dict[str, Any]:
    """A guest's suggested answer to an open intake question: it waits for a person to confirm it."""
    if not link.get("intake") or link["scope"] != "project":
        raise ObserveRefused("This link is for watching. Comment instead, or ask to define the project together.")
    project = _scoped(factory, link, link["project"])
    if qid not in {q["id"] for q in open_questions(project)}:
        raise ValueError(f"{qid} is not an open question of this project")
    text = str(text or "").strip()
    if not text or len(text) > MAX_COMMENT:
        raise ValueError(f"a suggestion is 1 to {MAX_COMMENT} characters")
    with updating_json(_path(factory), _blank()) as kept:
        rows = kept.setdefault("suggestions", [])
        observe_guard.check_rate(rows, link["id"], factory.clock.now())
        row = {"id": _next(rows, "GS"), "link": link["id"], "project": project.pid, "question": qid, "text": text,
               "guest": guest_of(link), "by_guest": True, "state": "waiting", "at": factory.clock.stamp()}
        rows.append(row)
    project.log("observe_suggested", {"suggestion": row["id"], "question": qid, "link": link["id"],
                                      "guest": row["guest"], "by_guest": True})
    return row


def suggestions(factory: Factory, *, project: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
    return [r for r in _load(factory)["suggestions"]
            if (project is None or r["project"] == project) and (state is None or r["state"] == state)]


def suggestion(factory: Factory, sid: str) -> dict[str, Any]:
    found = next((r for r in suggestions(factory) if r["id"] == sid), None)
    if found is None:
        raise KeyError(f"no suggestion {sid}")
    return found


def decide_suggestion(project: Project, sid: str, *, verdict: str, person: str, persona: str) -> dict[str, Any]:
    """Confirm a guest's suggestion (the question is answered with its words, signed by the person who confirms)
    or decline it. A guest's words are never an answer by themselves."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a suggestion is confirmed by a named person")
    if verdict not in ("accept", "decline"):
        raise ValueError("verdict is accept or decline")
    factory = project.factory
    row = suggestion(factory, sid)
    if row["project"] != project.pid:
        raise KeyError(f"no suggestion {sid} in {project.pid}")
    if row["state"] != "waiting":
        raise DecisionRefused(f"{sid} is already {row['state']}")
    if verdict == "accept":
        Canon(project).answer(row["question"], row["text"], person=person, persona=persona)
    with updating_json(_path(factory), _blank()) as kept:
        for r in kept.setdefault("suggestions", []):
            if r["id"] == sid:
                r.update(state="accepted" if verdict == "accept" else "declined", by=person, persona=persona,
                         decided_at=factory.clock.stamp())
                row = dict(r)
    project.log("observe_suggestion_decided", {"suggestion": sid, "question": row["question"], "verdict": verdict,
                                               "guest": row["guest"], "person": person, "persona": persona})
    return row


# -- following: where the sharer is, in memory only ------------------------------------------------------

def set_presence(factory: Factory, *, person: str, persona: str, project: str | None, view: str | None,
                 paused: bool | None = None, hint: bool | None = None) -> dict[str, Any]:
    """Where the sharer is now (the page posts it while a link of theirs is active). Records nothing. Only an
    explicit ``paused`` changes a pause; a heartbeat (None) keeps it (kernel/observe_guard.py, FR-SHR2)."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    held = observe_guard.paused_now(str(factory.home), person, paused, hint)
    where = {"person": person, "persona": persona, "project": str(project or "")[:90] or None,
             "view": str(view or "")[:40] or None, "paused": held, "at": factory.clock.stamp()}
    with _LOCK:
        _PRESENCE[(str(factory.home), person)] = {**where, "_t": time.monotonic()}
    return where


def presence(factory: Factory, person: str) -> dict[str, Any] | None:
    with _LOCK:
        found = _PRESENCE.get((str(factory.home), person))
    if not found or time.monotonic() - found["_t"] > PRESENCE_SECONDS:
        return None
    return {k: v for k, v in found.items() if k != "_t"}


def active_for(factory: Factory, person: str) -> list[dict[str, Any]]:
    """The person's links that are active now (the page follows their view only while one is)."""
    return [public(factory, r) for r in links(factory)
            if r.get("created_by") == person and state_of(factory, r) == "active"]
