"""Enforcement levels per environment and check family: advise or enforce (D-0026, FR-ENF1, FR-ENF2).

The owner (2026-11-25): "in development we wouldn't want forced human check on everything; in testing and
production we wouldn't want any critical changes without human checks. So there should be different levels of
enforcement ... stay true to the middle layer vision while helping to enforce the structure."

A **level** says what Rihmasto does when something crosses into an environment and a check family has a say:

- ``off``: Rihmasto looks away (the project's own pipeline still does what it does);
- ``advise``: a note in the project's record, and a nudge in the view; the work goes on (the default);
- ``require_review``: a card for the named reviewer; the work goes on, the review is owed;
- ``enforce``: the work is refused until the named reviewer decides the card.

There is one level per **environment** (dev, test, prod; Rihmasto's own preview and demo count as dev, staging
as test, production as prod; a pipeline's name is placed by its whole words, and a name Rihmasto does not know
counts as production until a person places it, kernel/enforcement_places.py) and **check family** (quality,
security, legal, governance). The platform sets them for every project; a project may set its own for any cell,
and every cell says which scope it comes from. Nothing is enforced until a person turns it on. Every change is
signed and in a ledger: the platform's in the factory's own, a project's in its own. The runtime decision is
kernel/enforcement_guard.py; the project's own pipeline, read and never written, is kernel/enforcement_pipeline.py.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import enforcement_places as kplaces
from kernel.canon import DecisionRefused
from kernel.enforcement_places import ENV_OF, ENVIRONMENTS, env_of  # noqa: F401  (by whole words, FR-ENF2)
from kernel.people import is_person

LEVELS = ("off", "advise", "require_review", "enforce")
RANK = {lvl: n for n, lvl in enumerate(LEVELS)}
LEVEL_MEANING = {
    "off": "Rihmasto does not look; the project's own pipeline still does what it does",
    "advise": "a note in the record and a nudge; the work goes on",
    "require_review": "a card for the named reviewer; the work goes on and the review is owed",
    "enforce": "the work waits until the named reviewer decides",
}
ENV_MEANING = {"dev": "development: where people and agents change things freely",
               "test": "testing: where a release is tried before it is used",
               "prod": "production: what people use"}
FAMILIES = ("quality", "security", "legal", "governance")
FAMILY_MEANING = {
    "quality": "tests, the build pipeline's runs, health probes and the quality check of a change",
    "security": "open security findings, secrets and dependency audits",
    "legal": "licences of what the product uses, and its bill of materials",
    "governance": "a change itself entering the environment, approvals and the audits of how it was made",
}
# Who reviews each family unless a person names another (a card's deciders, kernel/canon.py "enforcement").
REVIEWERS = ("business_owner", "product_owner", "developer", "it", "operations", "compliance")
DEFAULT_REVIEWER = {"quality": "developer", "security": "it", "legal": "compliance", "governance": "business_owner"}
DEFAULT_LEVEL = "advise"
SETTERS = ("business_owner", "it", "compliance", "developer")     # who sets a level (the solo person holds all)
INHERIT = "inherit"                                              # a project cell back to the platform's
PRESETS: dict[str, dict[str, Any]] = {
    "advise": {"label": "Advise everywhere", "levels": {e: {f: "advise" for f in FAMILIES} for e in ENVIRONMENTS}},
    "split": {"label": "Free in development, reviewed in testing, enforced in production",
              "levels": {"dev": {f: "advise" for f in FAMILIES}, "test": {f: "require_review" for f in FAMILIES},
                         "prod": {f: "enforce" for f in FAMILIES}}},
    "strict": {"label": "Reviewed in development, enforced in testing and production",
               "levels": {"dev": {f: "require_review" for f in FAMILIES}, "test": {f: "enforce" for f in FAMILIES},
                          "prod": {f: "enforce" for f in FAMILIES}}},
}
FILE = "enforcement.json"


def count(n: int, word: str) -> str:
    """``n`` and ``word``, plural when ``n`` is not 1: "1 setting", "3 settings"."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _store(factory: Any, *, create: bool) -> Any:
    from kernel.learn import factory_project

    return factory_project(factory, create=create)


def platform_settings(factory: Any) -> dict[str, Any]:
    store = _store(factory, create=False)          # a reader never creates the factory's own records
    doc = store.read(FILE, {}) if store is not None else {}
    return doc if isinstance(doc, dict) else {}


def project_settings(project: Any) -> dict[str, Any]:
    doc = project.read(FILE, {})
    return doc if isinstance(doc, dict) else {}


def _cell(doc: dict[str, Any], env: str, family: str) -> str | None:
    value = ((doc.get("levels") or {}).get(env) or {}).get(family)
    return value if value in LEVELS else None


def _reviewer(doc: dict[str, Any], family: str) -> str | None:
    value = (doc.get("reviewers") or {}).get(family)
    return value if value in REVIEWERS else None


def cell(factory: Any, project: Any, env: str, family: str) -> dict[str, Any]:
    """The level and reviewer in force for one cell, and the scope each comes from."""
    plat, own = platform_settings(factory), project_settings(project) if project is not None else {}
    level, scope = _cell(own, env, family), "project"
    if level is None:
        level, scope = _cell(plat, env, family), "platform"
    if level is None:
        level, scope = DEFAULT_LEVEL, "default"
    reviewer, rscope = _reviewer(own, family), "project"
    if reviewer is None:
        reviewer, rscope = _reviewer(plat, family), "platform"
    if reviewer is None:
        reviewer, rscope = DEFAULT_REVIEWER[family], "default"
    return {"env": env, "family": family, "level": level, "scope": scope, "reviewer": reviewer,
            "reviewer_scope": rscope}


def grid(factory: Any, project: Any = None) -> list[dict[str, Any]]:
    return [cell(factory, project, e, f) for e in ENVIRONMENTS for f in FAMILIES]


def levels_of(cells: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {e: {} for e in ENVIRONMENTS}
    for c in cells:
        out[c["env"]][c["family"]] = c["level"]
    return out


def strictest(cells: list[dict[str, Any]], env: str) -> str:
    return max((c["level"] for c in cells if c["env"] == env), key=RANK.__getitem__, default=DEFAULT_LEVEL)


# -- changing them ------------------------------------------------------------------------------------------

def _checked_levels(levels: Any) -> dict[str, dict[str, str]]:
    if not isinstance(levels, dict):
        raise ValueError("levels is an object: {environment: {family: level}}")
    allowed = (*LEVELS, INHERIT)
    out: dict[str, dict[str, str]] = {}
    for env, row in levels.items():
        if env not in ENVIRONMENTS or not isinstance(row, dict):
            raise ValueError(f"an environment is one of {', '.join(ENVIRONMENTS)}, each with its families")
        for family, level in row.items():
            if family not in FAMILIES:
                raise ValueError(f"a check family is one of {', '.join(FAMILIES)}, got {family!r}")
            if level not in allowed:
                raise ValueError(f"a level is one of {', '.join(allowed)}, got {level!r}")
            out.setdefault(env, {})[family] = level
    return out


def _checked_reviewers(reviewers: Any) -> dict[str, str]:
    if reviewers is None:
        return {}
    if not isinstance(reviewers, dict):
        raise ValueError("reviewers is an object: {family: persona}")
    for family, who in reviewers.items():
        if family not in FAMILIES or who not in (*REVIEWERS, INHERIT):
            raise ValueError(f"a reviewer is one of {', '.join(REVIEWERS)} for a family of {', '.join(FAMILIES)}")
    return dict(reviewers)


def from_preset(name: str) -> dict[str, dict[str, str]]:
    if name not in PRESETS:
        raise ValueError(f"a preset is one of {', '.join(PRESETS)}")
    return {e: dict(row) for e, row in PRESETS[name]["levels"].items()}


def _apply(doc: dict[str, Any], levels: dict[str, dict[str, str]], reviewers: dict[str, str]) -> list[dict]:
    """Change ``doc`` in place; the cells that changed, from and to (None: not set in this scope)."""
    changes = []
    for env, row in levels.items():
        for family, level in row.items():
            have = doc.setdefault("levels", {}).setdefault(env, {})
            before = have.get(family)
            to = None if level == INHERIT else level
            if before != to:
                changes.append({"env": env, "family": family, "from": before, "to": to})
            if to is None:
                have.pop(family, None)
            else:
                have[family] = to
    for family, who in reviewers.items():
        have = doc.setdefault("reviewers", {})
        before, to = have.get(family), None if who == INHERIT else who
        if before != to:
            changes.append({"reviewer": family, "from": before, "to": to})
        if to is None:
            have.pop(family, None)
        else:
            have[family] = to
    return changes


def _loosens(changes: list[dict[str, Any]]) -> bool:
    return any(c.get("looser") for c in changes) or any(
        RANK.get(c["to"] or DEFAULT_LEVEL, 1) < RANK.get(c["from"] or DEFAULT_LEVEL, 1) for c in changes if "env" in c)


def _repo_change(doc: dict[str, Any], repo: str | None) -> list[dict[str, Any]]:
    """A project's GitHub repository named by a person (owner/name; empty removes it)."""
    if repo is None:
        return []
    repo = str(repo).strip()
    if repo and not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repo):
        raise ValueError("the repository is owner/name, as on GitHub")
    before = doc.get("repo") or None
    if (repo or None) == before:
        return []
    if repo:
        doc["repo"] = repo
    else:
        doc.pop("repo", None)
    return [{"repo": True, "from": before, "to": repo or None}]


def check_setter(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person; a level is set by a named person")
    if persona not in SETTERS:
        raise DecisionRefused(f"a {persona} may not set enforcement levels; {', '.join(SETTERS)} may")


def wanted_levels(levels: Any, preset: str | None) -> dict[str, dict[str, str]]:
    """A preset's cells, with the cells named in ``levels`` over them."""
    wanted = from_preset(preset) if preset else {}
    for env, row in _checked_levels(levels or {}).items():
        wanted.setdefault(env, {}).update(row)
    return wanted


def set_levels(factory: Any, project: Any, *, levels: Any = None, reviewers: Any = None, preset: str | None = None,
               person: str, persona: str, reason: str = "", repo: str | None = None, names: Any = None,
               gate_env: str | None = None) -> dict[str, Any]:
    """Set the platform's levels (``project`` None) or a project's own, signed; recorded in that scope's ledger.
    A level loosened (enforce to advise, say), a name placed in a less strict stage or the gate's changes sent to
    one needs a reason, as every override does (FR-ENF2)."""
    check_setter(person, persona)
    wanted, who = wanted_levels(levels, preset), _checked_reviewers(reviewers)
    if not any((wanted, who, *(x is not None for x in (repo, names, gate_env)))):
        raise ValueError("say what to change: levels, a preset, reviewers, names, the gate's stage or the repository")
    scope, target = _target(factory, project, repo)
    doc = target.read(FILE, {}) or {}
    changes = (_apply(doc, wanted, who) + _repo_change(doc, repo) + kplaces.names_change(doc, names)
               + kplaces.gate_change(doc, gate_env))
    said = str(reason or "").strip()
    if _loosens(changes) and not said:
        raise ValueError("loosening a level needs a reason: it is recorded with the change")
    _record(target, scope, doc, changes, {"preset": preset, "person": person, "persona": persona, "reason": said[:300]})
    return {"scope": scope, "changes": changes, **describe(factory, project)}


def _target(factory: Any, project: Any, repo: str | None) -> tuple[str, Any]:
    """The scope a change is made in, and the store that keeps it."""
    if project is not None:
        return "project", project
    if repo is not None:
        raise ValueError("a repository is a project's own: name it in the project's view")
    return "platform", _store(factory, create=True)


def place(factory: Any, project: Any, name: Any) -> dict[str, Any]:
    """Where an environment's name lands for ``project`` (kernel/enforcement_places.py): never quietly dev."""
    return kplaces.place(name, project_settings(project) if project is not None else {}, platform_settings(factory))


def gate_env(factory: Any, project: Any) -> dict[str, str]:
    return kplaces.gate_env(project_settings(project) if project is not None else {}, platform_settings(factory))


def _record(target: Any, scope: str, doc: dict[str, Any], changes: list[dict[str, Any]], who: dict[str, Any]) -> None:
    if changes:
        doc.update(set_by=who["person"], persona=who["persona"])
        target.write(FILE, doc)
        target.log("enforcement_set", {"scope": scope, "changes": changes, **who})


# -- reading them -------------------------------------------------------------------------------------------

def history(factory: Any, project: Any = None, limit: int = 20) -> list[dict[str, Any]]:
    store = project if project is not None else _store(factory, create=False)
    if store is None:
        return []
    rows = [{"at": r["event"].get("at"), **r["event"]["payload"]} for r in store.ledger().of_kind("enforcement_set")]
    return rows[-limit:][::-1]


def overriding_projects(factory: Any) -> list[dict[str, Any]]:
    """Every project that sets any cell or reviewer of its own: the platform's change does not reach those cells."""
    from kernel.learn import FACTORY_PID

    out = []
    for p in factory.projects():
        if p.pid == FACTORY_PID:
            continue
        own = project_settings(p)
        cells = [f"{e}/{f}" for e, row in (own.get("levels") or {}).items() for f in row]
        if cells or own.get("reviewers"):
            out.append({"project": p.pid, "title": p.meta.get("title") or p.pid, "cells": cells,
                        "reviewers": sorted(own.get("reviewers") or {})})
    return out


def _names(factory: Any, project: Any) -> list[dict[str, str]]:
    """The names a person placed, each with its stage and scope (the project's over all projects')."""
    own = project_settings(project).get("names") if project is not None else {}
    plat = platform_settings(factory).get("names") or {}
    rows = {k: {"name": k, "env": v, "scope": "platform"} for k, v in plat.items() if v in ENVIRONMENTS}
    rows |= {k: {"name": k, "env": v, "scope": "project"} for k, v in (own or {}).items() if v in ENVIRONMENTS}
    return sorted(rows.values(), key=lambda r: r["name"])


def describe(factory: Any, project: Any = None) -> dict[str, Any]:
    cells = grid(factory, project)
    return {"scope": "project" if project is not None else "platform",
            "project": project.pid if project is not None else None, "cells": cells, "levels": levels_of(cells),
            "strictest": {e: strictest(cells, e) for e in ENVIRONMENTS},
            "meta": {"levels": [{"id": lvl, "meaning": LEVEL_MEANING[lvl]} for lvl in LEVELS],
                     "environments": [{"id": e, "meaning": ENV_MEANING[e],
                                       "names": sorted(k for k, v in ENV_OF.items() if v == e)} for e in ENVIRONMENTS],
                     "families": [{"id": f, "meaning": FAMILY_MEANING[f]} for f in FAMILIES],
                     "reviewers": list(REVIEWERS), "default_level": DEFAULT_LEVEL,
                     "presets": [{"id": k, "label": v["label"]} for k, v in PRESETS.items()]},
            "setters": list(SETTERS), "history": history(factory, project),
            "names": _names(factory, project), "gate_env": gate_env(factory, project),
            "overriding": overriding_projects(factory) if project is None else []}
