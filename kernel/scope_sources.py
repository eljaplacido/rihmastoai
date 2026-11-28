"""Where a setting's value really comes from (D-0027, FR-TM4): one reader per surface of kernel/scope_table.py, each
looking at the store that surface is kept in, never at a fixed answer.

A reader takes the factory and a project (None: the home's own reading, with no project chosen) and answers the scope
the value in force comes from:

- ``project``: this project has its own;
- ``home``: one setting for the whole home, so for every team in it (a home with one team says "all projects");
- ``team``: the team's own (only words and membership are kept per team);
- ``default``: nothing was set, so what Rihmasto ships applies;
- ``none``: a thing that exists only where somebody made it (an embed, a link, an audit) and none was made here;
- ``per_project``: no project was chosen, and the setting is made on each project, not for a team.

The structure policy, the enforcement levels, the modules and the IT-check defaults are each one document per home,
with no team in it: they read ``home`` where they once read "the team", so a second team is never told that a setting is
its own when every team shares it. Nothing here writes: a read never creates a record.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Reader = Callable[[Any, Any], str]


def _widest(scopes: set[str]) -> str:
    return "project" if "project" in scopes else "home" if "platform" in scopes else "default"


def structure(factory: Any, project: Any) -> str:
    from kernel import structure_policy as sp

    kinds = [None] if project is not None else list(sp.DEFAULT)      # the home's reading: any kind's level
    return _widest({sp.row(factory, project, c, kind=k)["scope"] for c in sp.CONVENTIONS for k in kinds})


def enforcement(factory: Any, project: Any) -> str:
    from kernel import enforcement as ke

    cells = ke.grid(factory, project)
    return _widest({c["scope"] for c in cells} | {c["reviewer_scope"] for c in cells})


def modules(factory: Any, project: Any) -> str:
    from kernel import modules as km

    if project is not None and not km.project_set(project)["inherited"]:
        return "project"
    return "home" if km.factory_set(factory)["chosen"] else "default"


def itops(factory: Any, project: Any) -> str:
    from kernel import itops as it

    if project is not None and it.override(project):
        return "project"
    return "home" if it.defaults(factory) else "default"


def vocabulary(factory: Any, project: Any) -> str:
    from kernel import teams, vocab

    eff = vocab.effective(factory, project, None if project is not None else teams.AUTO_ID)
    scopes = {r["scope"] for r in vocab.differs(eff)}
    return "project" if "project" in scopes else "team" if "team" in scopes else "default"


def teams_row(factory: Any, project: Any) -> str:
    return "project" if project is not None and project.meta.get("team") else "default"


def runners(factory: Any, project: Any) -> str:
    from kernel.runners import ROLES, choice

    items = choice.choices(factory)
    pid = project.pid if project is not None else None
    came = {choice.effective(factory, pid, role, items=items)["from"] for role in ROLES}
    return "project" if "project" in came else "home" if "factory" in came else "default"


def roads(factory: Any, project: Any) -> str:
    from kernel.roads import BUILTIN_ROADS, PavedRoads

    if project is not None and project.meta.get("paved_road"):
        return "project"
    return "home" if set(PavedRoads.load(factory).roads) - set(BUILTIN_ROADS) else "default"


def harness(factory: Any, project: Any) -> str:
    from kernel import harness_enforcement as he

    came = he.state(factory, project)["from"]
    return "home" if came == "platform" else came


def models(factory: Any, project: Any) -> str:
    from kernel import lanes
    from kernel.store import read_json

    try:
        mine = read_json(lanes.ROUTING_LOCAL_FILE, None)
    except (OSError, ValueError):
        mine = None
    return "home" if isinstance(mine, dict) and mine else "default"


def people(factory: Any, project: Any) -> str:
    from kernel import team as kteam

    return "home" if kteam.mode(factory) == kteam.TEAM else "default"


def folders(factory: Any, project: Any) -> str:
    from kernel import source_guard

    return "home" if source_guard.allowed(factory.home) else "default"


def observability(factory: Any, project: Any) -> str:
    from kernel.agentobs.client import from_settings

    try:
        return "home" if from_settings(factory) is not None else "default"
    except (OSError, ValueError, KeyError):
        return "default"


def machines(factory: Any, project: Any) -> str:
    """The machines list is one for the whole platform (FR-XAG1): set in this home, or none yet."""
    from kernel import machines as kmachines

    try:
        return "home" if kmachines.listed(factory) else "default"
    except (OSError, ValueError):
        return "default"


def asks(factory: Any, project: Any) -> str:
    """Asks to other agents live in each project's channel (FR-XAG1): this project's, or one per project."""
    from kernel import asks as kasks

    if project is None:
        return "per_project"
    try:
        return "project" if kasks.listed(project) else "none"
    except (OSError, ValueError):
        return "none"


def _only_here(project: Any, found: bool, home: bool = False) -> str:
    """A thing made where it lives: this project's, or one that covers every project, or none made."""
    if project is None:
        return "home" if home else "per_project"
    return "project" if found else "home" if home else "none"


def embeds(factory: Any, project: Any) -> str:
    from kernel import embeds as ke

    live = [e for e in ke.embeds(factory) if e.get("state") == "active"]
    mine = project is not None and any(e.get("project") == project.pid for e in live)
    return _only_here(project, mine, home=any(e.get("kind") == "need" for e in live))


def observer(factory: Any, project: Any) -> str:
    from kernel import observe

    live = [x for x in observe.links(factory) if observe.state_of(factory, x) == "active"]
    mine = project is not None and any(x.get("scope") == "project" and x.get("project") == project.pid for x in live)
    return _only_here(project, mine, home=any(x.get("scope") == "platform" for x in live))


def automations(factory: Any, project: Any) -> str:
    from kernel import automations as ka

    live = ka.automations(factory)
    if project is None:
        return _only_here(None, False, home=any((a.get("scope") or {}).get("kind") == "factory" for a in live))
    scoped = [(a.get("scope") or {}) for a in live if ka.in_scope(project, a.get("scope") or {})]
    return _only_here(project, any(s.get("kind") in ("project", "projects") for s in scoped), home=bool(scoped))


def evals(factory: Any, project: Any) -> str:
    from kernel import gnomon_evals_run as run

    return _only_here(project, project is not None and bool(run.latest(project)))
