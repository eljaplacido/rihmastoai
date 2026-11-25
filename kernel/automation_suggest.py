"""Automations a project would want, from a scan of its shape and state (FR-SET1).

The owner (2026-11-24): "for automations you should be able to scan a project for suggestions of them."

``scan`` reads what a project is and how it stands (``facts``): its profile (a game, an ML pipeline, a knowledge
base...), whether it is adopted or attached (a repository of its own), the test command it states or that was
found, its releases and whether one runs in production or reached a test road, the checks enabled on it,
whether it is confidential, whether agents work on it from an IDE, and whether it aligns with its repository's
own specs and tests. Each rule that applies offers one automation with a one-line reason:

    "Nightly gate on new commits; notify if it fails" - it is an attached repository: ...

A suggestion is a draft of kernel/automations.py, already checked against the allow-list. **Accept** sets it in
the person's name (one click, signed, ``automation_set``); **dismiss** is remembered per project
(``automation_suggestion_dismissed``), so it is not offered again. One already set up (an automation of the same
action and trigger reaches the project) shows as set up. Nothing here runs anything.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from kernel import automations as au
from kernel.alignment_suggest import plural
from kernel.store import Factory, Project, updating_json

FILE = "automation_suggestions.json"
Facts = dict[str, Any]
# The words a profile id is read by: a profile of this build, or one another stream adds (game, knowledge).
GAME, ML, KNOWLEDGE = ("game",), ("ml", "ml_pipeline", "machine_learning"), ("knowledge", "knowledge_base", "docs")


def _kinds(project: Project) -> set[str]:
    return {r["event"]["kind"] for r in project.ledger().records() if isinstance(r, dict) and "event" in r}


def _stated_tests(project: Project) -> str | None:
    from kernel.console import settings

    line = settings(project)["commands"].get("test")
    if line:
        return str(line)
    inv = project.read("inventory.json", {}) or {}
    tc = inv.get("test_command") if isinstance(inv, dict) else None
    if isinstance(tc, dict) and tc.get("detected"):
        return " ".join(str(x) for x in tc.get("command") or []) or "found by rule"
    return None


def _releases(project: Project) -> list[dict[str, Any]]:
    from kernel.deliver import releases

    try:
        return list(releases(project))
    except (OSError, ValueError, KeyError):
        return []


def facts(project: Project) -> Facts:
    """What the rules read, from the project's records only."""
    from kernel.alignment_records import applies
    from kernel.checks import store as cstore
    from kernel.confidential import confidential

    meta, kinds, rels = project.meta, _kinds(project), _releases(project)
    source = meta.get("source_kind")
    return {"pid": project.pid, "title": meta.get("title") or project.pid, "profile": str(meta.get("profile") or ""),
            "source": source, "attached": bool((meta.get("attached") or {}).get("repo")),
            "repository": source in ("attached", "adopted"), "tests": _stated_tests(project),
            "releases": len(rels), "checks": sorted(cstore.enabled(project)),
            "production": "promoted" in kinds or any(r.get("maturity") == "production" and r.get("state") == "done"
                                                     for r in rels),
            "test_road": "release_reached_test" in kinds, "confidential": confidential(project),
            "ide": bool(kinds & {"workspace_opened", "handoff_made", "channel_posted", "agent_progress",
                                 "ide_connected", "channel_message"}),
            "aligns": applies(project), "folder": _folder(project), "built": "first_build_passed" in kinds,
            "records": sum(1 for _ in project.ledger().records())}


def _folder(project: Project) -> str | None:
    """A folder on this machine the project was made from, for a re-scan."""
    from pathlib import Path

    for key in ("source_folder", "folder", "source_path"):
        value = project.meta.get(key)
        if isinstance(value, str) and value and Path(value).is_dir():
            return value
    return None


# -- the rules: each returns a suggestion or None ------------------------------------------------------------

def _s(sid: str, label: str, reason: str, draft: dict[str, Any], needs: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"id": sid, "label": label, "reason": reason, "draft": draft, "needs": list(needs)}


def _scope(f: Facts) -> dict[str, Any]:
    return {"kind": "project", "projects": [f["pid"]]}


def _told(draft: dict[str, Any], sub: str | None, when: str = "failed") -> dict[str, Any]:
    """The outcome notice, when a channel is set up for this project."""
    return dict(draft, notify={"subscription": sub, "when": when}) if sub else draft


def _tell(f: Facts, sub: str | None, text: str) -> dict[str, Any]:
    """Notify a channel when there is one; otherwise log a signal on the delivery square, which needs none."""
    if sub:
        return {"kind": "notify", "subscription": sub, "text": text}
    return {"kind": "signal", "text": text}


def _nightly_gate(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f["attached"]:
        return None
    draft = _told({"name": "Nightly gate on new commits", "trigger": {"kind": "schedule", "daily": "02:00"},
                   "action": {"kind": "gate"}, "scope": _scope(f)}, sub)
    told = "; notify if it fails" if sub else ""
    return _s("nightly_gate", f"Nightly gate on new commits{told}",
              "it is an attached repository: the gate judges what landed each night, before anyone builds on it", draft)


def _tests_on_commit(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not (f["repository"] and f["tests"]):
        return None
    draft = _told({"name": "Tests on every new commit", "trigger": {"kind": "repo"}, "action": {"kind": "command"},
                   "scope": _scope(f)}, sub)
    return _s("tests_on_commit", "Run its tests on every new commit",
              f"it states a test command ({str(f['tests'])[:60]}): run it in a sandbox when new commits land", draft)


def _weekly_summary(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if f["records"] < 5:
        return None
    draft = {"name": "Weekly activity summary", "trigger": {"kind": "schedule", "weekly": "mon 07:00"},
             "action": {"kind": "ask", "text": "Summarise last week's activity on {project} by area: what changed, "
                                               "what failed, and what waits on people."}, "scope": _scope(f)}
    where = "with a local model only, as it is confidential" if f["confidential"] else "as a comment"
    return _s("weekly_summary", "Weekly activity summary by area into Review",
              f"it has history to read: every Monday a summary by area lands in Review ({where})", draft)


def _probe_production(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f["production"]:
        return None
    draft = _told({"name": "Probe production", "trigger": {"kind": "schedule", "every": "5m"},
                   "action": {"kind": "probe", "environment": "production"}, "scope": _scope(f)}, sub)
    return _s("probe_production", "Probe production every 5 minutes",
              "a release of it runs in production: a failing probe opens the incident card at once", draft)


def _local_model_alert(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f["confidential"]:
        return None
    draft = {"name": "Alert if a role would leave the local model",
             "trigger": {"kind": "event", "types": ["confidential_fallback_skipped", "confidential_refused"]},
             "action": _tell(f, sub, "On {project} a role would have left the local model ({event})"),
             "scope": _scope(f)}
    return _s("local_model_alert", "Alert if a role would leave the local model",
              "it is confidential: be told the moment a role's model is hosted and the work was kept local", draft)


def _check_failed(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f["checks"]:
        return None
    draft = {"name": "A check failed", "trigger": {"kind": "event", "types": ["check_ran"]},
             "guard": {"kind": "field", "key": "verdict", "equals": "failed"},
             "action": _tell(f, sub, "A check failed on {project} ({verdict})"), "scope": _scope(f)}
    return _s("check_failed", "Tell me when a check fails",
              f"{len(f['checks'])} check(s) run on it ({', '.join(f['checks'][:3])}): a failure should reach a person",
              draft)


def _align_on_change(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not f["aligns"]:
        return None
    draft = {"name": "Alignment after a change", "trigger": {"kind": "repo"}, "action": {"kind": "align_scan"},
             "scope": _scope(f)}
    return _s("align_on_change", "Re-read its specs and tests when the repository changes",
              "its repository has specs and tests of its own: what drifts shows on Alignment to accept or reject",
              draft)


def _test_road(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not (f["test_road"] or f["releases"]):
        return None
    draft = _told({"name": "Check a release on test", "trigger": {"kind": "event", "types": ["release_reached_test"]},
                   "action": {"kind": "probe"}, "scope": _scope(f)}, sub, "always")
    return _s("test_road_checks", "When a release reaches test, probe it there",
              f"it has {plural(f['releases'], 'release')} on a paved road: each one that reaches test is checked "
              "there", draft)


def _gate_twice(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if not (f["ide"] or f["attached"]):
        return None
    draft = {"name": "Two failed gates", "trigger": {"kind": "event", "types": ["gate_failed"]},
             "guard": {"kind": "count", "event": "gate_failed", "at_least": 2, "within_hours": 24},
             "action": {"kind": "change", "text": "The gate failed twice within a day on {project}: look at why"},
             "scope": _scope(f)}
    who = "agents work on it from an IDE" if f["ide"] else "people push to it"
    return _s("gate_twice_change", "When the gate fails twice in a day, open a change proposal",
              f"{who}: two failures in a day are a pattern a person should look at", draft)


def _first_build(f: Facts, sub: str | None) -> dict[str, Any] | None:
    if f["repository"] or f["built"]:
        return None
    draft = {"name": "First build passed", "trigger": {"kind": "event", "types": ["first_build_passed"]},
             "action": _tell(f, sub, "{project}: the first build passed the gate"), "scope": _scope(f)}
    return _s("first_build", "Tell me when the first build passes the gate",
              "Rihmasto builds it: hear the moment there is something to try", draft)


def _profile(f: Facts, sub: str | None) -> dict[str, Any] | None:
    p = f["profile"].lower()
    if p in GAME and f["repository"]:
        draft = {"name": "Nightly build and tests", "trigger": {"kind": "schedule", "daily": "03:00"},
                 "action": {"kind": "command"}, "scope": _scope(f)}
        return _s("game_nightly", "Build and test it every night",
                  "it is a game: a build breaks quietly between play sessions", _told(draft, sub))
    if p in ML and f["repository"]:
        draft = {"name": "Weekly evaluation", "trigger": {"kind": "schedule", "weekly": "sun 03:00"},
                 "action": {"kind": "command"}, "scope": _scope(f)}
        return _s("ml_weekly_eval", "Run its evaluations every week",
                  "it is an ML pipeline: results drift with the data even when the code does not", _told(draft, sub))
    if p in KNOWLEDGE and f["folder"]:
        draft = {"name": "Weekly re-scan", "trigger": {"kind": "schedule", "weekly": "mon 06:00"},
                 "action": {"kind": "rescan", "folder": f["folder"]}, "scope": _scope(f)}
        return _s("knowledge_rescan", "Re-scan its folder every week",
                  "it is a knowledge base: new documents in its folder should join its material", draft)
    return None


RULES: tuple[Callable[[Facts, str | None], dict[str, Any] | None], ...] = (
    _nightly_gate, _tests_on_commit, _probe_production, _check_failed, _local_model_alert, _align_on_change,
    _test_road, _gate_twice, _profile, _weekly_summary, _first_build)


# -- the scan, and its state --------------------------------------------------------------------------------

def subscription_for(factory: Factory, pid: str) -> str | None:
    """The channel a suggestion notifies: the project's own receiver first, then one for every project."""
    from kernel import relay

    subs = relay.subscriptions(factory)
    own = [s for s in subs if pid in (s.get("projects") or [])]
    shared = [s for s in subs if not s.get("projects")]
    return str((own or shared)[0]["id"]) if own or shared else None


def _kept(project: Project) -> dict[str, Any]:
    return project.read(FILE, {}) or {}


def _set_up(factory: Factory, project: Project, draft: dict[str, Any]) -> str | None:
    """An automation reaching the project with this action and trigger already: its id."""
    for a in au.automations(factory):
        reaches = au.in_scope(project, a["scope"]) or a["action"].get("project") == project.pid
        if reaches and a["action"]["kind"] == draft["action"]["kind"] \
                and a["trigger"]["kind"] == draft["trigger"]["kind"]:
            return str(a["id"])
    return None


def scan(factory: Factory, pid: str) -> dict[str, Any]:
    """The suggestions for one project, each checked against the allow-list, with its state: offered,
    set_up (and by which automation) or dismissed. Records nothing."""
    project = factory.project(pid)
    f, sub = facts(project), subscription_for(factory, project.pid)
    kept = _kept(project)
    out = []
    for rule in RULES:
        s = rule(f, sub)
        if s is None:
            continue
        try:
            checked = au._checked(factory, s["draft"])
        except (ValueError, KeyError) as exc:          # never offer what would be refused
            s.update(state="unavailable", why=str(exc))
            out.append(s)
            continue
        from kernel import automations_text as words

        s["summary"] = words.describe(checked)
        done = (kept.get("accepted") or {}).get(s["id"], {}).get("automation") or _set_up(factory, project, s["draft"])
        dismissed = (kept.get("dismissed") or {}).get(s["id"])
        s.update(state="set_up" if done else "dismissed" if dismissed else "offered", automation=done,
                 dismissed=dismissed)
        out.append(s)
    return {"project": project.pid, "title": f["title"], "facts": f, "subscription": sub, "suggestions": out,
            "offered": sum(1 for s in out if s["state"] == "offered")}


def _one(factory: Factory, pid: str, sid: str) -> dict[str, Any]:
    found = next((s for s in scan(factory, pid)["suggestions"] if s["id"] == sid), None)
    if found is None:
        raise KeyError(f"no suggestion {sid!r} for {pid}")
    return found


def accept(factory: Factory, pid: str, sid: str, *, person: str, persona: str,
           changes: dict[str, Any] | None = None) -> dict[str, Any]:
    """Set the suggested automation in the person's name (signed, as any automation is), and remember it."""
    s = _one(factory, pid, sid)
    if s["state"] == "set_up":
        raise au.AutomationRefused(f"{sid} is set up already ({s['automation']})")
    if s["state"] == "unavailable":
        raise ValueError(f"{sid} cannot be set up here: {s.get('why')}")
    draft = copy.deepcopy(s["draft"])
    draft.update({k: v for k, v in (changes or {}).items() if k in ("name", "limits", "notify")})
    a = au.add(factory, draft, person=person, persona=persona)
    project = factory.project(pid)
    with updating_json(project.path(FILE), {}) as kept:
        kept.setdefault("accepted", {})[sid] = {"automation": a["id"], "by": person, "at": factory.clock.stamp()}
        (kept.get("dismissed") or {}).pop(sid, None)
    project.log("automation_suggestion_accepted", {"suggestion": sid, "automation": a["id"], "person": person,
                                                   "persona": persona})
    return {"suggestion": sid, "automation": a}


def dismiss(factory: Factory, pid: str, sid: str, *, person: str, persona: str) -> dict[str, Any]:
    """Do not offer this suggestion on this project again; remembered and recorded."""
    from kernel.access import require
    from kernel.people import PERSONAS, is_person

    if not is_person(person) or persona not in PERSONAS:
        raise au.AutomationRefused("a suggestion is dismissed by a named person with a persona")
    _one(factory, pid, sid)
    project = factory.project(pid)
    require(project, person, persona)
    with updating_json(project.path(FILE), {}) as kept:
        kept.setdefault("dismissed", {})[sid] = {"by": person, "persona": persona, "at": factory.clock.stamp()}
    project.log("automation_suggestion_dismissed", {"suggestion": sid, "person": person, "persona": persona})
    return {"suggestion": sid, "state": "dismissed"}


def offered_count(factory: Factory, pid: str) -> int:
    return int(scan(factory, pid)["offered"])
