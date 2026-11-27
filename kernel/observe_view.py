"""What a guest sees through an observer link (FR-SHR1): the views in scope, read only.

One read for the observer page (kernel/observe_page.py): the projects the link shows (a confidential one only
when the sharer ticked it), the chosen project's overview, plan, decisions waiting, activity and agent channel,
and following: the view the sharer is on (unless paused, or on something outside the link) and their latest
actions. It never carries a setting, a credential, a secret (every text is masked), a holdout, another project,
or a ledger record's payload beyond its kind, its time and who acted.
"""

from __future__ import annotations

from typing import Any

from kernel import agent_channel, observe, observe_guard
from kernel.canon import Canon
from kernel.incidents import mask_text
from kernel.store import STAGES, Factory, Project

VIEWS = ("overview", "plan", "decisions", "activity", "channel")
WHO_KEYS = ("person", "by", "requested_by", "guest")
TAIL = 200          # ledger records read per project for activity and the sharer's actions
SHOWN = 25


def _who(payload: dict[str, Any]) -> str:
    for key in WHO_KEYS:
        if isinstance(payload.get(key), str) and payload[key]:
            return payload[key][:80] + (" (guest)" if key == "guest" else "")
    return "Rihmasto"


def _events(project: Project) -> list[dict[str, Any]]:
    out = []
    for r in project.ledger().records()[-TAIL:]:
        ev = r.get("event") if isinstance(r, dict) else None
        if isinstance(ev, dict):
            found = ev.get("payload")
            pay: dict[str, Any] = found if isinstance(found, dict) else {}
            out.append({"at": ev.get("at"), "kind": str(ev.get("kind") or ""), "who": _who(pay),
                        "person": pay.get("person"), "project": project.pid})
    return out


def _title(project: Project) -> str:
    return str(project.meta.get("title") or project.pid)


def _plan(project: Project) -> dict[str, Any]:
    contract = project.read("contract.json", None)
    contract = contract if isinstance(contract, dict) else {}
    state = project.read("tasks.json", {}) or {}
    state = state if isinstance(state, dict) else {}
    reqs = [{"id": r.get("id"), "statement": mask_text(r.get("statement") or "", 400)}
            for r in contract.get("requirements") or [] if isinstance(r, dict)][:60]
    tasks = [{"id": t.get("id"), "title": mask_text(t.get("title") or "", 200),
              "status": (state.get(t.get("id")) or {}).get("status", "pending")}
             for t in contract.get("tasks") or [] if isinstance(t, dict)][:80]
    return {"requirements": reqs, "tasks": tasks}


def project_view(project: Project) -> dict[str, Any]:
    """One project as the guest sees it."""
    from kernel.status import now

    meta = project.meta
    stage = meta.get("stage")
    try:
        said = now(project)
    except (OSError, ValueError, KeyError):
        said = {"state": "working", "line": ""}
    canon = Canon(project)
    cards = [{"id": c["id"], "kind": c["kind"], "title": mask_text(c.get("title") or "", 200),
              "blocking": bool(c.get("blocking"))} for c in canon.cards(state="open")][:40]
    channel = [{"id": m["id"], "at": m.get("at"), "who": agent_channel.who(m), "kind": m.get("kind"),
                "text": mask_text(m.get("text") or "", 1200)}
               for m in agent_channel.messages(project, held=False, limit=30)]
    activity = [{k: e[k] for k in ("at", "kind", "who")} for e in _events(project)[-SHOWN:]][::-1]
    return {"pid": project.pid, "title": _title(project), "stage": stage,
            "stage_name": STAGES.get(stage, "") if isinstance(stage, int) else "", "now": {"state": said.get("state"),
                                                                     "line": mask_text(said.get("line") or "", 300)},
            "plan": _plan(project), "decisions": cards, "activity": activity, "channel": channel}


def following(factory: Factory, link: dict[str, Any], shown: list[Project]) -> dict[str, Any]:
    """Where the sharer is now and what they did last, within the link's scope only."""
    sharer = link["created_by"]
    ids = {p.pid: _title(p) for p in shown}
    actions = sorted((e for p in shown for e in _events(p) if e["person"] == sharer),
                     key=lambda e: str(e["at"] or ""))[-10:][::-1]
    done = [{"at": e["at"], "kind": e["kind"], "project": ids[e["project"]], "pid": e["project"]} for e in actions]
    where = observe.presence(factory, sharer)
    if where is None:
        return {"sharer": sharer, "state": "away", "actions": done}
    if where["paused"]:
        return {"sharer": sharer, "state": "paused", "actions": done}
    place = observe_guard.where_shown(link, where, ids)       # only what the link covers, in words (FR-SHR2)
    if place is None:
        return {"sharer": sharer, "state": "elsewhere", "actions": done}   # never says where
    pid = place["project"]
    return {"sharer": sharer, "state": "here", "project": pid, "project_title": ids.get(pid or "", ""),
            "view": place["view"], "view_words": place["view_words"], "at": where.get("at"), "actions": done}


def _chosen(shown: list[Project], pid: str | None, follow: dict[str, Any]) -> Project | None:
    """The project asked for, else the one the sharer is on, else the first in scope; never one outside it."""
    by_id = {p.pid: p for p in shown}
    for wanted in (pid, follow.get("project")):
        if wanted in by_id:
            return by_id[wanted]
    return shown[0] if shown else None


def _guest_part(factory: Factory, link: dict[str, Any], project: Project | None) -> dict[str, Any]:
    """The guest's own comments, and on a link for defining the project together the open questions and their
    suggestions."""
    mine = [{k: c[k] for k in ("id", "project", "about", "text", "at", "guest")}
            for c in observe.comments(factory, link=link)][-50:]
    if project is None or not link.get("intake"):
        return {"comments": mine, "questions": [], "suggestions": []}
    offered = [{k: s[k] for k in ("id", "question", "text", "state", "at")}
               for s in observe.suggestions(factory, project=project.pid) if s["link"] == link["id"]]
    return {"comments": mine, "questions": observe.open_questions(project), "suggestions": offered}


def view(factory: Factory, link: dict[str, Any], pid: str | None = None) -> dict[str, Any]:
    """The observer page's one read."""
    shown = observe.in_scope(factory, link)
    follow = following(factory, link, shown)
    project = _chosen(shown, pid, follow)
    return {"guest": observe.guest_of(link), "from": link["created_by"], "expires": link["expires"],
            "scope": link["scope"], "scope_title": observe.scope_title(factory, link),
            "intake": bool(link.get("intake")), "projects": [{"pid": p.pid, "title": _title(p)} for p in shown],
            "project": project_view(project) if project is not None else None, "following": follow,
            "views": list(VIEWS), **_guest_part(factory, link, project)}
