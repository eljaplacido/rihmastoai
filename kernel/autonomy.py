"""The autonomy ladder: one backend, four degrees of freedom, capped by the owner's policy.

1. **answer:** the factory answers questions and analyses; it changes nothing.
2. **suggest:** it notices things and proposes them; a person decides each one.
3. **prepare:** it builds and trials a candidate in a sandbox lane, judged by its evals; nothing
   reaches a running environment beyond a local preview or demo.
4. **deliver:** an approved candidate goes to staging and production and is monitored; a named
   person approves each release.

The owner's policy sets the cap for the whole factory (for example defence 3, industry 4,
development 4). A project may set a lower cap, never a higher one. The kernel enforces it: below
3 nothing is built, below 4 nothing lands on staging or production. Only a person with the right
persona changes a cap, and every change is in the ledger.

Every path that builds or delivers asks first, not only the pipeline: `cleared_to_build` before
the pipeline builds, before `rihma build`, and before a ruling or an applied change leads to a
rebuild; `cleared_to_deliver` (which also refuses a paused project) before the pipeline or
`rihma deliver` lands a release. Reading a cap never creates the factory's own canon (FR-S1-AC-3).
"""

from __future__ import annotations

from kernel.canon import DecisionRefused
from kernel.people import is_person
from kernel.store import Project

LEVELS = {1: "answer", 2: "suggest", 3: "prepare", 4: "deliver"}
MEANING = {
    1: "answers questions and analyses; changes nothing",
    2: "proposes; a person decides each proposal",
    3: "builds and trials candidates in a sandbox, judged by their evals",
    4: "delivers approved candidates to staging and production, with a named approver per release",
}
SETTERS = ("business_owner", "it", "compliance")
DEFAULT_CAP = 4
LANDING_LEVEL = {"preview": 3, "demo": 3, "staging": 4, "production": 4}
BUILD_LEVEL = 3


class AutonomyCapped(PermissionError):
    """An action needs a higher autonomy level than the policy allows."""

    def __init__(self, needed: int, cap: int, what: str):
        self.needed, self.cap = needed, cap
        super().__init__(f"{what} needs autonomy level {needed} ({LEVELS[needed]}); the cap is {cap} ({LEVELS[cap]})")


def _store(factory, *, create: bool = True):
    from kernel.learn import factory_project

    return factory_project(factory, create=create)


def factory_cap(factory) -> int:
    store = _store(factory, create=False)  # a reader: no canon yet means no policy yet, the default cap
    policy = (store.read("policy.json", {}) or {}) if store is not None else {}
    return int(policy.get("autonomy_cap", DEFAULT_CAP))


def cap_of(project) -> int:
    own = project.meta.get("autonomy_cap")
    cap = factory_cap(project.factory)
    return min(cap, int(own)) if own is not None else cap


def set_cap(target, level: int, *, person: str, persona: str, reason: str) -> dict:
    """Set the cap for the factory (``target`` is a Factory) or lower it for one project."""
    from kernel.store import Factory

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in SETTERS:
        raise DecisionRefused(f"a {persona} may not set the autonomy cap; {', '.join(SETTERS)} may")
    if level not in LEVELS:
        raise ValueError(f"the level is one of {sorted(LEVELS)}")
    if not str(reason).strip():
        raise ValueError("a cap change needs a reason")
    if isinstance(target, Factory):
        store = _store(target)
        policy = store.read("policy.json", {}) or {}
        before = policy.get("autonomy_cap", DEFAULT_CAP)
        policy["autonomy_cap"] = level
        store.write("policy.json", policy)
        store.log("autonomy_cap_set", {"scope": "factory", "from": before, "to": level, "by": person,
                                       "persona": persona, "reason": reason})
        return {"scope": "factory", "cap": level}
    if level > factory_cap(target.factory):
        raise DecisionRefused(f"a project may not exceed the factory's cap of {factory_cap(target.factory)}")
    before = target.meta.get("autonomy_cap")
    target.update_meta(autonomy_cap=level)
    target.log("autonomy_cap_set", {"scope": "project", "from": before, "to": level, "by": person,
                                    "persona": persona, "reason": reason})
    return {"scope": "project", "cap": cap_of(target)}


def require(project, needed: int, what: str) -> None:
    cap = cap_of(project)
    if needed > cap:
        raise AutonomyCapped(needed, cap, what)


def cleared_to_build(project: Project) -> Project:
    """``project`` itself when the cap lets the factory build it (level 3); AutonomyCapped otherwise.
    A project's posture may hold it further: a go-ahead card above the posture's autonomy, assumptions to
    confirm (kernel/posture_rules.py; nothing without a posture). A revision already built is not built
    again (the pipeline asks before a ruling that may rebuild): the posture holds the next build instead."""
    from kernel.posture_rules import clear

    require(project, BUILD_LEVEL, "building")
    if not project.meta.get("built"):
        clear(project, "build")
    return project


def cleared_to_deliver(project: Project) -> Project:
    """``project`` itself when it may be delivered now: it is not paused (a paused project runs
    nothing, FR-J3), and the cap lets it land where its maturity lands it (a preview or a demo at
    level 3, staging or production at 4). PermissionError otherwise, AutonomyCapped for the cap."""
    from kernel.deliver import LANDING
    from kernel.posture_rules import clear
    from kernel.safestop import paused

    if paused(project):
        raise PermissionError(f"{project.pid} is paused: a person resumes it before anything is delivered")
    landing = LANDING[project.meta["maturity"]]
    require(project, LANDING_LEVEL.get(landing, 4), f"delivering to {landing}")
    clear(project, "deliver", landing)    # a posture's go-ahead and landing gate (nothing without a posture)
    return project


def describe(project=None, factory=None) -> dict:
    cap = cap_of(project) if project is not None else factory_cap(factory)
    return {"cap": cap, "name": LEVELS[cap], "meaning": MEANING[cap],
            "levels": [{"level": n, "name": LEVELS[n], "meaning": MEANING[n], "allowed": n <= cap} for n in LEVELS]}
