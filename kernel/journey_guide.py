"""The guided panel's record (FR-JRN1): who is being guided through which journey, about which project, and what
they said about the steps no record shows.

Kept per person under the factory home's ``_journeys/guides.json``: the journey, the project once there is one,
when it started, whether it is active, and the person's marks (I did it, Skip) by step. The factory's ledger
records journey_started, journey_step (a mark) and journey_ended with the journey, the step, the project and who,
never what was typed: what was done is in the records the steps are measured from.

Reading writes nothing. A guide started before there is a project (feeding one in) finds it again from the
person's own walkthrough that adopted it (kernel/walkthrough.py), and the folder and scan that walkthrough holds
measure the steps before the adoption.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kernel import journey_state as js
from kernel import journeys as kj
from kernel.store import Factory, read_json, updating_json

HOWS = {"did": "did", "skip": "skipped"}
ACTIONS = ("start", "did", "skip", "stop", "project")
PID = re.compile(r"[a-z0-9][a-z0-9-]{0,99}\Z")      # as the cockpit's routes name a project (cockpit/server.py PID)


class GuideRefused(ValueError):
    """A guide action that is not taken, with the reason."""


def _file(factory: Factory) -> Path:
    return factory.home / "_journeys" / "guides.json"


def guide_of(factory: Factory, person: str) -> dict[str, Any] | None:
    """The person's guide (active, done or stopped), or None."""
    kept = read_json(_file(factory), {}) or {}
    got = kept.get(person) if isinstance(kept, dict) else None
    return dict(got) if isinstance(got, dict) else None


def _signed(person: str, persona: str) -> None:
    from kernel.walkthrough import _signed as signed

    signed(person, persona)


def _log(factory: Factory, kind: str, payload: dict[str, Any]) -> None:
    from kernel.learn import factory_project

    project = factory_project(factory)
    project.log(kind, payload)


def _project_id(factory: Factory, pid: str | None) -> str | None:
    if not pid:
        return None
    if not PID.match(pid):
        raise GuideRefused(f"no project {pid!r}")
    try:
        factory.project(pid)
    except (KeyError, FileNotFoundError, ValueError):
        raise GuideRefused(f"no project {pid}") from None
    return pid


def start(factory: Factory, name: str, *, person: str, persona: str, project: str | None = None) -> dict[str, Any]:
    """Start guiding a person through a journey (one guide per person: a new one takes the old one's place)."""
    _signed(person, persona)
    if name not in kj.JOURNEYS:
        raise GuideRefused(f"no journey {name!r}: one of {', '.join(kj.JOURNEYS)}")
    pid = _project_id(factory, project)
    g = {"journey": name, "project": pid, "started": factory.clock.stamp(), "state": "active", "persona": persona,
         "marks": {}}
    with updating_json(_file(factory), {}) as kept:
        kept[person] = g
    _log(factory, "journey_started", {"journey": name, "person": person, "persona": persona,
                                      **({"project": pid} if pid else {})})
    return g


def _active(factory: Factory, person: str) -> dict[str, Any]:
    g = guide_of(factory, person)
    if g is None or g.get("state") != "active":
        raise GuideRefused("no guide is going: start one with Guide me step by step")
    return g


def mark(factory: Factory, *, person: str, persona: str, step: str, how: str) -> dict[str, Any]:
    """The person's word on a step: they did it (where no record can show it) or skip it."""
    _signed(person, persona)
    if how not in HOWS:
        raise GuideRefused("a step is marked did or skip")
    g = _active(factory, person)
    if step not in [s.id for s in kj.journey(g["journey"]).steps]:
        raise GuideRefused(f"{kj.journey(g['journey']).label} has no step {step!r}")
    pid = g.get("project") or (walk_for(factory, g, person) or {}).get("project")
    with updating_json(_file(factory), {}) as kept:
        kept[person].setdefault("marks", {})[step] = {"how": HOWS[how], "at": factory.clock.stamp()}
        kept[person]["project"] = pid
        g = dict(kept[person])
    _log(factory, "journey_step", {"journey": g["journey"], "step": step, "how": HOWS[how], "person": person,
                                   "persona": persona, **({"project": pid} if pid else {})})
    return g


def attach(factory: Factory, *, person: str, persona: str, project: str) -> dict[str, Any]:
    """Say which project the guide is about (one made or adopted outside the guide's walkthrough)."""
    _signed(person, persona)
    g = _active(factory, person)
    pid = _project_id(factory, project)
    with updating_json(_file(factory), {}) as kept:
        kept[person]["project"] = pid
        g = dict(kept[person])
    _log(factory, "journey_step", {"journey": g["journey"], "step": "project", "how": "attached", "project": pid,
                                   "person": person, "persona": persona})
    return g


def stop(factory: Factory, *, person: str, persona: str) -> dict[str, Any]:
    """End the guide: done when every step is settled, else stopped. Nothing else is undone or done."""
    _signed(person, persona)
    g = _active(factory, person)
    got = view(factory, person, persona)
    outcome = "done" if got and got["progress"]["complete"] else "stopped"
    with updating_json(_file(factory), {}) as kept:
        kept[person]["state"], kept[person]["ended"] = outcome, factory.clock.stamp()
        g = dict(kept[person])
    _log(factory, "journey_ended", {"journey": g["journey"], "outcome": outcome, "person": person, "persona": persona,
                                    **({"project": g["project"]} if g.get("project") else {})})
    return g


def act(factory: Factory, action: str, *, person: str, persona: str, journey: str | None = None,
        project: str | None = None, step: str | None = None) -> dict[str, Any]:
    """One of ACTIONS, as the cockpit's route and the command line ask for it."""
    if action == "start":
        return start(factory, str(journey or ""), person=person, persona=persona, project=project)
    if action in HOWS:
        return mark(factory, person=person, persona=persona, step=str(step or ""), how=action)
    if action == "project":
        return attach(factory, person=person, persona=persona, project=str(project or ""))
    if action == "stop":
        return stop(factory, person=person, persona=persona)
    raise GuideRefused(f"action is one of {', '.join(ACTIONS)}")


# -- reading -----------------------------------------------------------------------------------------------------

def walk_for(factory: Factory, g: dict[str, Any], person: str) -> dict[str, Any] | None:
    """The person's walkthrough for the guide's journey (Plug in for feeding in a project), started since the
    guide: the folder and scan it holds, and the project it made."""
    from kernel.walkthrough import walk_dir

    name = kj.journey(g["journey"]).walkthrough
    if not name:
        return None
    found = [w for w in (read_json(p, None) for p in sorted(walk_dir(factory).glob("WT-*.json")))
             if isinstance(w, dict) and w.get("person") == person and w.get("name") == name
             and str(w.get("started") or "") >= str(g.get("started") or "")]
    if not found:
        return None
    w = found[-1]
    data = w.get("data") or {}
    return {"id": w.get("id"), "state": w.get("state"), "step": w.get("step"), "source": data.get("source"),
            "scan": data.get("scan") or {}, "project": data.get("project")}


def view(factory: Factory, person: str, persona: str | None = None) -> dict[str, Any] | None:
    """The person's guide with its journey measured from the records now, or None when they have none."""
    g = guide_of(factory, person)
    if g is None:
        return None
    walk = walk_for(factory, g, person) if g.get("state") == "active" else None
    pid = g.get("project") or (walk or {}).get("project")
    project = None
    if pid:
        try:
            project = factory.project(pid)
        except (KeyError, FileNotFoundError, ValueError):
            project = None
    prog = js.progress(factory, g["journey"], project=project, person=person, persona=persona or g.get("persona"),
                       marks=g.get("marks") or {}, walk=walk)
    return {"guide": g | {"project": pid}, "walk": walk, "progress": prog}
