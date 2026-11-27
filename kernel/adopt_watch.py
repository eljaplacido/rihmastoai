"""Watching an adopted project (FR-RPJ1; docs/brownfield.md, Watching).

Adopting to monitor or maintain means watching: after the adoption the project offers a watch, and a person
sets it up, signed. Through the automations engine (kernel/automations.py), scoped to the project and in that
person's name:

- **new commits**: a repository trigger (new commits upstream, found by polling) fires the ``watch`` action,
  which syncs the upstream (kernel/adopt.py ``sync``: an "Upstream changed: review" card in Review when it
  moved, and the drift in the project's timeline) and refreshes its areas (kernel/areas.py);
- **activity by area, weekly**: a schedule (Mondays, 07:00 UTC) records a summary of what moved by area;
- **failed checks -> notify**: when the project records a failed check (its baseline, a gate, a watch),
  a notice goes to one of IT's relay subscriptions; with none, that part says so and waits for one.

When an automation cannot be set (its rights, a scope the engine refuses), the watch falls back to the
upstream polling ``rihmasto sync`` already does, and says so. ``view`` is the project's "Watching: ..." line.
"""

from __future__ import annotations

from typing import Any

FILE = "watch.json"
INTENTS = ("monitor", "maintain")
FAILED = ["characterised", "gate_failed", "watch_check_failed", "baseline_stated_run"]


def _automations(project: Any, ids: list[str]) -> list[dict[str, Any]]:
    from kernel import automations as au

    known = {a["id"]: a for a in au.automations(project.factory)}
    return [known[i] for i in ids if i in known]


def view(project: Any) -> dict[str, Any]:
    """Whether the project is watched and how, as one line; or the offer, for an adopted project to monitor or
    maintain that is not watched yet."""
    w = project.read(FILE, None) or {}
    intent = project.meta.get("intent")
    if not w.get("parts"):
        offered = intent in INTENTS
        return {"watching": False, "offered": offered,
                "line": "Not watched yet: set up a watch for new commits, weekly activity by area and failed checks"
                if offered else "Not watched"}
    live = {a["id"]: a for a in _automations(project, [p["automation"] for p in w["parts"] if p.get("automation")])}
    said = []
    for p in w["parts"]:
        a = live.get(p.get("automation") or "")
        state = "" if a is None or a.get("state") == "active" else f" ({a.get('state')})"
        said.append(p["label"] + (f" [{p['automation']}]" if p.get("automation") else "") + state)
    return {"watching": True, "via": w.get("via"), "parts": w["parts"], "by": w.get("by"),
            "line": "Watching: " + "; ".join(said)}


def _wanted(project: Any, sub: str | None, on: dict[str, bool]) -> list[tuple[str, dict[str, Any]]]:
    """The automations a watch is made of: (its line, its record), for the parts asked for."""
    title, scope = project.meta.get("title") or project.pid, {"kind": "project", "project": project.pid}
    parts = {
        "commits": ("new commits -> a summary in Review and the timeline",
                    {"name": f"Watch {title}: new commits", "trigger": {"kind": "repo"},
                     "action": {"kind": "watch", "what": "commits"}, "scope": scope}),
        "weekly": ("activity by area, weekly",
                   {"name": f"Watch {title}: activity by area", "trigger": {"kind": "schedule", "weekly": "mon 07:00"},
                    "action": {"kind": "watch", "what": "areas"}, "scope": scope}),
        "failures": (f"failed checks -> notify {sub}",
                     {"name": f"Watch {title}: failed checks", "trigger": {"kind": "event", "types": FAILED},
                      "guard": {"kind": "field", "key": "verdict", "equals": "failed"},
                      "action": {"kind": "notify", "subscription": sub, "text": "{project}: a check failed ({event})"},
                      "scope": scope})}
    return [parts[k] for k in ("commits", "weekly", "failures") if on[k]]


def setup(project: Any, *, person: str, persona: str, commits: bool = True, weekly: bool = True,
          failures: bool = True, subscription: str | None = None) -> dict[str, Any]:
    """Set up the watch, signed: automations when the engine takes them, else the upstream polling."""
    from kernel import automations as au
    from kernel import relay
    from kernel.people import is_person

    if not is_person(person):
        raise au.AutomationRefused(f"{person!r} is not a person: a watch is set by a named person")
    subs = [s["id"] for s in relay.subscriptions(project.factory)]
    sub = subscription if subscription in subs else (subs[0] if subs else None)
    wanted = _wanted(project, sub, {"commits": commits, "weekly": weekly, "failures": failures and bool(sub)})
    parts, via, why = [], "automations", None
    for label, raw in wanted:
        try:
            a = au.add(project.factory, raw, person=person, persona=persona)
            parts.append({"label": label, "automation": a["id"]})
        except (au.AutomationRefused, ValueError, LookupError, PermissionError) as exc:
            via, why = "polling", str(exc)[:200]
            parts.append({"label": label + " (by the upstream polling: rihmasto sync)", "automation": None})
    if failures and not sub:
        parts.append({"label": "failed checks -> notify: waits for a notification channel (IT adds one in "
                               "Settings > Integrations)", "automation": None})
    w = {"parts": parts, "via": via, "why": why, "by": {"person": person, "persona": persona},
         "at": project.factory.clock.stamp()}
    project.write(FILE, w)
    project.log("watch_set", {"parts": [p["label"] for p in parts], "via": via, "person": person, "persona": persona,
                              "automations": [p["automation"] for p in parts if p.get("automation")]})
    return view(project)


def fire(project: Any, what: str) -> dict[str, Any]:
    """One firing of a watch: sync and summarise new commits, or summarise the activity by area."""
    from kernel import adopt, areas
    from kernel import native_sources as ns

    if what == "sources":      # the project's own sources read again on their schedule (FR-SRC1)
        got = ns.read(project, person=None, persona=None, why="their schedule", fetch=True)   # latest first (FR-SRC2)
        said = ", ".join(f"{len(got[k])} {k}" for k in ("requirements", "tasks", "findings", "results"))
        return {"outcome": "done", "detail": f"the project's own sources read again: {said}"}
    if what == "areas":
        got = areas.record(project)
        text = areas.summary(got, 7)
        project.log("watch_areas_summary", {"summary": text[:2000]})
        return {"outcome": "done", "detail": text[:300]}
    drift = adopt.sync(project)
    if drift.get("verdict") != "passed":
        project.log("watch_check_failed", {"verdict": "failed", "why": str(drift.get("reason"))[:300]})
        return {"outcome": "failed", "verdict": "failed", "detail": str(drift.get("reason"))[:300]}
    got = areas.record(project)
    new = drift.get("new_commits") or 0
    if not drift.get("moved_since_last_sync"):
        return {"outcome": "nothing", "detail": "no new commits upstream"}
    text = f"{new} new commit(s) upstream; {drift.get('files_changed')} file(s) differ. " + areas.summary(got, 7)
    if ns.reread(project, "a new commit"):     # sources read on every new commit (FR-SRC1)
        text += " The project's own sources were read again."
    project.log("watch_commits", {"new_commits": new, "card": drift.get("card"), "summary": text[:2000]})
    return {"outcome": "done", "detail": text[:300], "ref": drift.get("card") or ""}
