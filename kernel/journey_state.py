"""Where a person is on a journey (FR-JRN1): each step measured from the records, and the next best step.

Each step's ``check`` (kernel/journeys.py) names a rule here that reads the real records: the project's ledger
and files (adopted.json, baseline.json, the contract, the assessments' index), the factory's ledger, the
automations that reach the project, and the person's own walkthrough in Ask Rihma (the folder they gave and its
scan, before anything is adopted). A step a rule cannot see (that the IDE section is pasted) is done when the
person says so in the guided panel (``marks``, kernel/journey_guide.py), and the answer says it rests on their
word. Reading changes nothing.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from kernel import journeys as kj

Check = Callable[["Seen"], tuple[bool, str] | str | None]
UNDER_WAY = "under_way"


class Seen:
    """What the rules read for one project (or none): its ledger's kinds and records, read once."""

    def __init__(self, factory: Any, project: Any, *, walk: dict[str, Any] | None = None) -> None:
        self.factory, self.project, self.walk = factory, project, walk or {}
        self.records = _events(project) if project is not None else []
        self.kinds = {e.get("kind") for e in self.records}
        self._factory_kinds: set[Any] | None = None

    def first(self, *kinds: str) -> dict[str, Any] | None:
        return next((e for e in self.records if e.get("kind") in kinds), None)

    def last(self, *kinds: str) -> dict[str, Any] | None:
        return next((e for e in reversed(self.records) if e.get("kind") in kinds), None)

    def has(self, *kinds: str) -> bool:
        return bool(self.kinds & set(kinds))

    def factory_has(self, *kinds: str) -> bool:
        if self._factory_kinds is None:
            from kernel.learn import factory_project

            fp = factory_project(self.factory, False)
            self._factory_kinds = {e.get("kind") for e in _events(fp)} if fp is not None else set()
        return bool(self._factory_kinds & set(kinds))

    def ago(self, event: dict[str, Any] | None) -> str:
        return ago(str((event or {}).get("at") or ""), self.factory.clock.now())


def _events(project: Any) -> list[dict[str, Any]]:
    return [r["event"] for r in project.ledger().records() if isinstance(r, dict) and isinstance(r.get("event"), dict)]


def ago(stamp: str, now: dt.datetime) -> str:
    """"2 h ago", "5 min ago", "3 days ago" or "just now"; "" for no time."""
    try:
        then = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return ""
    s = max(0, int((now - then).total_seconds()))
    for size, unit in ((86_400, " day"), (3_600, " h"), (60, " min")):
        if s >= size:
            n = s // size
            return f"{n}{unit}{'s' if unit == ' day' and n > 1 else ''} ago"
    return "just now"


# -- the rules, one per check name ----------------------------------------------------------------------------

def _adopted(seen: Seen) -> tuple[bool, str] | None:
    e = seen.first("adopted")
    if e is None:
        return None
    who = (e.get("payload") or {}).get("person")
    return True, f"adopted {seen.ago(e)}" + (f" by {who}" if who else "")


def _folder(seen: Seen) -> tuple[bool, str] | None:
    if seen.project is not None and seen.has("adopted"):
        return True, "Adopted from " + str((seen.first("adopted") or {}).get("payload", {}).get("source"))
    src = seen.walk.get("source")
    return (True, f"You gave {src}") if src else None


def _scanned(seen: Seen) -> tuple[bool, str] | None:
    if seen.project is not None and seen.has("adopted", "material_scanned"):
        return True, "Scanned and taken at adoption"
    s = seen.walk.get("scan") or {}
    if not s:
        return None
    return True, f"Scanned: {s.get('read', 0)} read, {s.get('summarised', 0)} summarised, {s.get('skipped', 0)} skipped"


def _baseline(seen: Seen) -> tuple[bool, str] | str | None:
    base = seen.project.read("baseline.json") or {}
    if not base:
        return None
    verdict, reason = str(base.get("verdict") or "not measured"), str(base.get("reason") or "")
    if verdict in ("passed", "failed") or seen.has("baseline_stated_run"):
        return True, f"Baseline {verdict}" + (f": {reason}" if reason and verdict != "passed" else "")
    from kernel.adopt_stated import offers

    stated = offers(seen.project)
    if stated:
        return False, f"Not measured: your instructions state `{stated[0]['command']}`; run it as the baseline"
    return True, f"Not measured ({reason or 'no test command found'}): nothing to run unless you have a test command"


def _contract(seen: Seen) -> tuple[bool, str] | None:
    contract = seen.project.read("contract.json") or {}
    if not contract:
        return None
    n = len(contract.get("requirements") or [])
    return True, f"Compiled: {n} requirement{'s' if n != 1 else ''}, the as-is spec first"


def _assessed(seen: Seen) -> tuple[bool, str] | None:
    from kernel.assess import history

    versions = history(seen.project)
    if not versions:
        return None
    last = versions[-1]
    n = ((last.get("counts") or {}).get("findings")) or 0
    when = ago(str(last.get("at") or ""), seen.factory.clock.now())
    return True, f"{last.get('id')} recorded {when}: {n} finding{'s' if n != 1 else ''}"


def _reviewed(seen: Seen) -> tuple[bool, str] | None:
    parts = [what for kind, what in (("assessment_change_opened", "findings filed as changes"),
                                     ("alignment_scanned", "the repository read for alignment"),
                                     ("alignment_accepted", "alignment items decided")) if seen.has(kind)]
    return (True, "Done: " + ", ".join(parts)) if parts else None


def _tools(seen: Seen) -> tuple[bool, str] | None:
    e = seen.last("agent_handoff", "handoff_opened", "workspace_opened", "workspace_launched")
    return (True, f"A hand-off or workspace {seen.ago(e)}") if e else None


def _watched(seen: Seen) -> tuple[bool, str] | None:
    e = seen.last("watch_set", "check_enabled", "probe_check_enabled")
    if e is not None:
        return True, {"watch_set": "The watch is set", "check_enabled": "A check is enabled"}.get(
            str(e.get("kind")), "A probe check is enabled")
    n = len(_automations(seen))
    return (True, f"{n} automation{'s' if n != 1 else ''} reach it") if n else None


def _automations(seen: Seen) -> list[dict[str, Any]]:
    from kernel import automations as au

    try:
        every = au.automations(seen.factory)
    except (OSError, ValueError, KeyError):
        return []
    return [a for a in every if a.get("state") != "removed"
            and (seen.project is None or au.in_scope(seen.project, a.get("scope") or {}))]


def _changed(seen: Seen) -> tuple[bool, str] | str | None:
    e = seen.last("change_applied", "merged")
    if e is not None:
        return True, f"A change merged {seen.ago(e)}"
    e = seen.last("change_submitted", "change_triaged", "change_routed")
    return f"A change is under way ({seen.ago(e)}): decide it, then it is built and gated" if e else None


def _deployed(seen: Seen) -> tuple[bool, str] | None:
    e = seen.last("release_done", "road_chosen")
    return (True, "A release is done" if e and e.get("kind") == "release_done" else "A road is chosen") if e else None


def _made(seen: Seen) -> tuple[bool, str] | None:
    if seen.project is None:
        return None
    e = seen.first("project_created", "shaped_in_chat", "created_from_concept", "created_from_recipe")
    return True, "made" + (f" {seen.ago(e)}" if e else "")


def _answered(seen: Seen) -> tuple[bool, str] | str | None:
    from kernel.canon import Canon

    blocking = [q for q in Canon(seen.project).questions("open") if q.get("blocking")]
    if blocking:
        return f"{len(blocking)} blocking question{'s' if len(blocking) != 1 else ''} wait on a person"
    return (True, "The intake is done; no blocking question is open") if seen.has("intake_done", "reintake_done") \
        else None


def _planned(seen: Seen) -> tuple[bool, str] | None:
    if seen.has("plan_approved", "go_ahead_given", "posture_plan_approved") \
            or seen.project.path("contract.json").exists():
        return True, "The plan is approved"
    return None


def _kind_rule(*kinds: str, said: str) -> Check:
    def rule(seen: Seen) -> tuple[bool, str] | None:
        e = seen.last(*kinds)
        return (True, f"{said} {seen.ago(e)}".strip()) if e else None
    return rule


def _docs(seen: Seen) -> tuple[bool, str] | None:
    if seen.project is not None:
        return True, "The project has its material"
    src = seen.walk.get("source")
    return (True, f"You gave {src}") if src else None


def _models(seen: Seen) -> tuple[bool, str] | None:
    return (True, "A role is set in Models setup") if seen.factory_has("models_set", "models_use") else None


def _automated(seen: Seen) -> tuple[bool, str] | None:
    n = len(_automations(seen))
    return (True, f"{n} automation{'s' if n != 1 else ''} reach it") if n else None


def _ran(seen: Seen) -> tuple[bool, str] | None:
    from kernel.learn import factory_project

    pid = seen.project.pid if seen.project is not None else None
    fp = factory_project(seen.factory, False)
    records = seen.records + (_events(fp) if fp is not None else [])
    active = {str(a.get("id")) for a in _automations(seen)}
    for e in records:
        payload = e.get("payload") or {}
        if e.get("kind") != "automation_ran":
            continue
        if pid is None or payload.get("project") == pid:
            return True, "It ran"
        # A factory-wide run reaches every project in that automation's scope; another project's run does not.
        if not payload.get("project") and str(payload.get("id")) in active:
            return True, "It ran"
    return None


CHECKS: dict[str, Check] = {
    "folder_given": _folder, "scanned": _scanned, "adopted": _adopted, "baseline": _baseline,
    "contract": _contract, "assessed": _assessed, "reviewed": _reviewed, "tools": _tools, "watched": _watched,
    "changed": _changed, "deployed": _deployed, "made": _made, "answered": _answered,
    "planned": _planned, "built": _kind_rule("first_build_passed", "merged", said="Built and merged"),
    "delivered": _kind_rule("release_done", said="Released"), "docs_given": _docs, "models_seen": _models,
    "models_set": _models, "road_chosen": _kind_rule("road_chosen", said="A road was chosen"),
    "roads_seen": _kind_rule("road_chosen", said="A road was chosen"),
    "handed_off": _kind_rule("agent_handoff", "handoff_opened", said="Handed off"),
    "probed": _kind_rule("probed", "canary", said="Probed"), "automation_seen": _automated, "automated": _automated,
    "automation_ran": _ran, "mark": lambda seen: None,
}
# Checks that read a project's own files: without a project they cannot be done yet.
NEEDS_PROJECT = {"adopted", "baseline", "contract", "assessed", "reviewed", "tools", "watched", "changed", "deployed",
                 "answered", "planned", "built", "delivered", "road_chosen", "handed_off", "probed"}


def measure(step: kj.Step, seen: Seen) -> tuple[str, str]:
    """A step's state (done, under_way or todo) and what the records say about it."""
    if step.check in NEEDS_PROJECT and seen.project is None:
        return "todo", ""
    try:
        got = CHECKS[step.check](seen)
    except (OSError, ValueError, KeyError, LookupError) as exc:
        return "todo", f"Not measured: {exc}"
    if isinstance(got, str):
        return UNDER_WAY, got
    if got is None:
        return "todo", ""
    return ("done" if got[0] else "todo"), got[1]


# -- a journey's progress ---------------------------------------------------------------------------------------

def _route(step: kj.Step, pid: str | None) -> str | None:
    if step.view and pid:
        return f"#/p/{pid}/{step.view}"
    if step.page:
        return f"#/{step.page}"
    return "#/projects" if step.view else None


def step_view(step: kj.Step, state: str, said: str, *, pid: str | None, person: str | None,
              persona: str | None) -> dict[str, Any]:
    return {"id": step.id, "title": kj.title(step, persona), "why": step.why, "done_when": step.done_when,
            "not_yet": step.not_yet or f"{kj.title(step, persona)} is not done yet",
            "state": state, "said": said, "button": step.button, "optional": step.optional, "needs": list(step.needs),
            "action": {"control": kj.control(step), "route": _route(step, pid), "walkthrough": step.walkthrough,
                       "do": step.do if pid else None},
            "command": kj.command(step, pid=pid, person=person, persona=persona), "if_fails": step.if_fails}


def _with_mark(state: str, said: str, mark: dict[str, Any] | None, now: dt.datetime) -> tuple[str, str]:
    if state == "done" or not mark:
        return state, said
    when = ago(str(mark.get("at") or ""), now)
    if mark.get("how") == "did":
        return "done", f"You said you did it {when}".strip() + (f". {said}" if said else "")
    return ("skipped", f"Skipped {when}".strip()) if mark.get("how") == "skipped" else (state, said)


def _next(steps: list[dict[str, Any]]) -> str | None:
    settled = {s["id"] for s in steps if s["state"] in ("done", "skipped")}
    ready = [s for s in steps if s["id"] not in settled and set(s["needs"]) <= settled | {s["id"]}]
    first = next((s for s in ready if not s["optional"]), None) or next(iter(ready), None)
    if first is None:     # a step whose needs are not settled still comes next when it is the first left
        first = next((s for s in steps if s["id"] not in settled and not s["optional"]), None)
    return first["id"] if first else None


def progress(factory: Any, name: str, *, project: Any = None, person: str | None = None, persona: str | None = None,
             marks: dict[str, Any] | None = None, walk: dict[str, Any] | None = None) -> dict[str, Any]:
    """The journey's steps, each measured from the records (and the person's marks), and the next best one."""
    j = kj.journey(name)
    seen = Seen(factory, project, walk=walk)
    pid = project.pid if project is not None else None
    now = factory.clock.now()
    steps = []
    for step in j.steps:
        state, said = _with_mark(*measure(step, seen), (marks or {}).get(step.id), now)
        steps.append(step_view(step, state, said, pid=pid, person=person, persona=persona))
    nxt = _next(steps)
    done = sum(1 for s in steps if s["state"] == "done")
    anchor = next((s["said"] for s in steps if s["id"] == j.anchor and s["state"] == "done"), "")
    return {"journey": name, "label": kj.label(j, persona), "about": j.about, "scope": j.scope,
            "walkthrough": j.walkthrough, "project": pid,
            "title": project.meta.get("title") if project is not None else None, "steps": steps, "next": nxt,
            "done": done, "total": len(steps), "complete": nxt is None, "anchor": anchor,
            "last_done": next((s for s in reversed(steps) if s["state"] == "done"), None)}


def journey_for(project: Any) -> str:
    """The journey a project is on: an adopted one feeds in an existing project; one made from a folder of
    material started from documents; an attached repository connects an IDE; the rest started from an idea."""
    kind = project.meta.get("source_kind")
    if kind == "adopted":
        return "brownfield"
    if kind == "attached":
        return "ide"
    source = project.read("source.json") or {}
    return "documents" if isinstance(source, dict) and source.get("kind") in ("folder", "file") else "new_idea"


def factory_next(factory: Any, *, persona: str | None = None, person: str | None = None,
                 limit: int = 6) -> list[dict[str, Any]]:
    """Which project needs what: each project's journey and its next step, the unfinished ones first."""
    out = []
    for p in factory.projects():
        if p.pid.startswith("_"):
            continue
        prog = progress(factory, journey_for(p), project=p, person=person, persona=persona)
        step = next((s for s in prog["steps"] if s["id"] == prog["next"]), None)
        out.append({"project": p.pid, "title": p.meta.get("title"), "journey": prog["journey"],
                    "label": prog["label"], "done": prog["done"], "total": prog["total"], "next": step})
    out.sort(key=lambda r: r["next"] is None)
    return out[:limit]
