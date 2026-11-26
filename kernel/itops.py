"""What IT checks for a project: a check set proposed from its solution type and what was found (FR-ITO1).

The owner (2026-11-25): "IT maintenance view should include typical infrastructure checks done for apps,
databases, networks, integrations by agents ... think what they would be per project and solution type too".

A **solution type** says what a project runs, and so what IT typically checks on it (``TYPES``): a web service
(its health endpoint, certificates, names, destinations, dependencies), a scheduled job or pipeline, an
integration, a database-backed service, an ML pipeline, an agent or assistant, a game or content, a mobile app, a
library or command-line tool, and documents only, which runs nothing, so it has no infrastructure check, said so.

A project's types come from its work profile (kernel/profiles.py) **and** from what was found: an address where it
runs, a declared database or other integration, a scheduled automation or job, Gnomon eval results. Each check of
the set says why it is there ("it runs at https://...", "it declares orders_db (postgres)"), and where the rule
came from: the **platform default** for its type (Rihmasto's, or IT's change to it, for every project of the type)
or this **project's override** (a check added or taken away here). Each one shows whether it is enabled on Health
and its last result. ``apply`` enables what is not enabled yet with its suggested schedule, each signed as a
check is (kernel/checks/store.py); ``run`` runs the set's infrastructure checks now.

Platform defaults are kept in ``<home>/itops/defaults.json``, a project's override in its ``itops.json``; every
change is signed and recorded (``itops_default_changed`` in Rihmasto's own canon, ``itops_override_changed``,
``itops_applied``, ``itops_ran`` in the project's ledger).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import read_json, updating_json

SETTERS = ("it", "operations", "developer")        # a project's override, apply and run
DEFAULTERS = ("it",)                               # the platform's defaults, for every project of a type
INFRA = ("app", "tls", "dns", "database", "integration", "job", "ml", "agent")
FILE = "itops.json"


def _c(check: str, why: str) -> dict[str, str]:
    return {"check": check, "why": why}


TYPES: dict[str, dict[str, Any]] = {
    "web_service": {"label": "Web service", "checks": [
        _c("app", "a web service is first judged by its health endpoint: up, fast, and the version you expect"),
        _c("tls", "an expired certificate takes a web service down for every browser"),
        _c("dns", "its names must resolve and its port answer"),
        _c("destinations", "every environment where it runs, probed"),
        _c("dependencies", "a web service is exposed: known vulnerabilities in what it depends on matter")]},
    "job": {"label": "Scheduled job or pipeline", "checks": [
        _c("job", "a job fails quietly: its last run, failures in a row, duration and output freshness say so"),
        _c("executions", "where it runs on a paved road, its latest execution"),
        _c("dependencies", "what it depends on moves underneath it between runs")]},
    "integration": {"label": "Integration", "checks": [
        _c("integration", "each system it connects answers, its credentials are not about to expire, its quota "
                          "has headroom"),
        _c("dns", "the systems' names must resolve and their ports answer"),
        _c("tls", "an expired certificate on either side stops the messages")]},
    "database": {"label": "Database-backed", "checks": [
        _c("database", "its database answers within budget, its backup is recent and its storage growth is sane"),
        _c("dns", "the database host must resolve and answer")]},
    "ml": {"label": "ML pipeline", "checks": [
        _c("ml", "results drift with the data even when the code does not: the latest eval and its drift"),
        _c("job", "training and scoring run as scheduled jobs")]},
    "agent": {"label": "Agent or assistant", "checks": [
        _c("agent", "an agent's tool errors, cost per run and refusals show trouble before people do"),
        _c("ml", "its eval sets' latest results and drift"),
        _c("gnomon_security", "what its Gnomon surface grants and contains")]},
    "game": {"label": "Game or content", "checks": [
        _c("tests", "a build breaks quietly between play sessions: its own tests"),
        _c("dependencies", "engines and packages move underneath it")]},
    "mobile": {"label": "Mobile app", "checks": [
        _c("app", "the app is only as up as the API behind it"),
        _c("tls", "an app refuses an expired certificate"),
        _c("dependencies", "store reviews and users find vulnerable packages")]},
    "library": {"label": "Library or command-line tool", "checks": [
        _c("tests", "a library is judged by its tests"),
        _c("dependencies", "what it depends on reaches everyone who uses it"),
        _c("licences", "its users inherit its dependencies' licences")]},
    "documents": {"label": "Documents only", "checks": [],
                  "none": "it holds documents and runs nothing, so there is no infrastructure to check: no address, "
                          "no database, no job. Its material is read, not probed."},
}
PROFILE_TYPES = {"web_service": "web_service", "integration": "integration", "mobile_prototype": "mobile",
                 "ml_pipeline": "ml", "ml_experiment": "ml", "data_pipeline": "job", "automation": "job",
                 "agentic_workflow": "agent", "ops_agent": "agent", "harness_engineering": "agent", "game": "game",
                 "library_cli": "library", "knowledge_tooling": "documents"}


class ItOpsRefused(DecisionRefused):
    """A change to a check set the rules refuse (403, exit 2)."""


def signed(person: str, persona: str, allowed: tuple[str, ...], what: str) -> None:
    if not is_person(person):
        raise ItOpsRefused(f"refused: {person!r} is not a person; {what} is signed by a named person")
    if persona not in PERSONAS:
        raise ItOpsRefused(f"refused: persona must be one of {', '.join(PERSONAS)}")
    if persona not in allowed:
        raise ItOpsRefused(f"refused: {what} is for the {' or '.join(allowed)} persona, not {persona}; switch persona "
                           "in the person chip")


def _defaults_path(factory: Any) -> Path:
    return Path(factory.home) / "itops" / "defaults.json"


def defaults(factory: Any) -> dict[str, Any]:
    found = read_json(_defaults_path(factory), {})
    return found if isinstance(found, dict) else {}


def override(project: Any) -> dict[str, Any]:
    found = project.read(FILE, {}) or {}
    return found if isinstance(found, dict) else {}


# -- what the project is ------------------------------------------------------------------------------------------

def detected(project: Any) -> dict[str, list[str]]:
    """Each solution type the project is, with why: its profile, and what was found in its records."""
    from kernel.checks import infra_targets as tg

    out: dict[str, list[str]] = {}

    def add(t: str, why: str) -> None:
        out.setdefault(t, []).append(why)

    profile = str(project.meta.get("profile") or "")
    if profile in PROFILE_TYPES:
        add(PROFILE_TYPES[profile], f"its work profile is {profile.replace('_', ' ')}")
    for u in tg.urls(project):
        add("web_service", f"it runs at {u['url']} ({u['environment']})")
    for b in tg.bindings(project):
        add("database" if b["family"] == "database" else "integration", f"it declares {b['name']} ({b['kind']})")
    if _scheduled(project):
        add("job", "a scheduled automation runs on it")
    if _gnomon_ran(project):
        add("ml", "Gnomon eval sets have run on it")
    if "documents" in out and len(out) > 1:
        del out["documents"]                    # it runs something after all: not documents only
    if not out:
        add("documents" if project.meta.get("source_kind") in ("folder", "file") else "web_service",
            "nothing else was found: " + ("it was made from documents" if project.meta.get("source_kind") in
                                           ("folder", "file") else "a project builds a web service by default"))
    return out


def _scheduled(project: Any) -> bool:
    """An active scheduled automation does this project's own work (never a platform-wide one, never one that only
    runs its checks or evals: kernel/itops_jobs.py)."""
    from kernel import itops_jobs

    return bool(itops_jobs.own_jobs(project))


def _gnomon_ran(project: Any) -> bool:
    from kernel import gnomon_evals_run as gr

    try:
        return bool(gr.latest(project))
    except (OSError, ValueError):
        return False


def types_of(project: Any) -> dict[str, list[str]]:
    """The types the set is built from: the project's own choice when it made one, else what was detected."""
    chosen = override(project).get("types")
    if isinstance(chosen, list) and chosen:
        return {t: ["chosen for this project"] for t in chosen if t in TYPES}
    return detected(project)


# -- the set ----------------------------------------------------------------------------------------------------

def _type_checks(factory: Any, t: str) -> tuple[list[dict[str, str]], str]:
    """A type's checks after IT's platform change, and whether IT changed it."""
    base = [dict(c) for c in TYPES[t]["checks"]]
    mine = defaults(factory).get(t) or {}
    removed = set(mine.get("remove") or [])
    added = [_c(k, str((mine.get("why") or {}).get(k) or "IT added it for every project of this type"))
             for k in mine.get("add") or [] if k not in {c["check"] for c in base}]
    changed = bool(removed or added)
    return [c for c in base if c["check"] not in removed] + added, "platform default (changed by IT)" if changed \
        else "platform default"


def _row(project: Any, key: str, enabled: dict[str, Any]) -> dict[str, Any]:
    from kernel.checks import catalogue
    from kernel.checks import store as cstore

    check = catalogue().get(key.split(":")[0])
    rows = cstore.results(project, key, 1)
    last: dict[str, Any] = rows[-1] if rows else {}
    entry = enabled.get(key)
    return {"check": key, "label": check.label if check else key, "what": check.what if check else "",
            "every": (entry or {}).get("every") or (check.every if check else None), "enabled": entry is not None,
            "infra": key.split(":")[0] in INFRA, "runs_code": bool(check and check.runs_code),
            "state": last.get("verdict") or ("not run yet" if entry else "not enabled"),
            "summary": last.get("summary"), "at": last.get("at")}


def _reasons(project: Any, types: dict[str, list[str]], mine: dict[str, Any], known: set[str]) -> dict:
    """Each check of the set with why it is there, the types it is for and the scope of its rule."""
    rows: dict[str, dict[str, Any]] = {}
    for t, why_type in types.items():
        checks, scope = _type_checks(project.factory, t)
        for c in (c for c in checks if c["check"] in known):
            r = rows.setdefault(c["check"], {"why": [], "types": [], "scope": scope})
            r["why"].append(f"{TYPES[t]['label']}: {c['why']} ({'; '.join(why_type)})")
            r["types"].append(t)
    for key, why in (mine.get("add") or {}).items():
        if key.split(":")[0] in known:
            r = rows.setdefault(key, {"why": [], "types": [], "scope": "project override"})
            r["why"].append(f"added for this project: {why.get('why') if isinstance(why, dict) else why}")
            r["scope"] = "project override"
    return rows


def check_set(project: Any) -> dict[str, Any]:
    """The project's check set: each check with why it is there, its scope and its state on Health."""
    from kernel.checks import catalogue
    from kernel.checks import store as cstore

    types = types_of(project)
    mine = override(project)
    rows = _reasons(project, types, mine, set(catalogue()))
    removed = [k for k in mine.get("remove") or [] if k in rows]
    enabled = cstore.enabled(project)
    out = [{**_row(project, k, enabled), **v} for k, v in sorted(rows.items()) if k not in removed]
    none = [TYPES[t]["none"] for t in types if TYPES[t].get("none")]
    return {"project": project.pid, "title": project.meta.get("title"),
            "types": [{"id": t, "label": TYPES[t]["label"], "why": w} for t, w in types.items()],
            "chosen": bool(mine.get("types")), "checks": out,
            "removed": [{"check": k, "why": "taken away for this project", "scope": "project override"}
                        for k in removed],
            "none": none[0] if none and not out else None, "line": _line(out, none),
            "missing": [r["check"] for r in out if not r["enabled"]]}


def _line(rows: list[dict[str, Any]], none: list[str]) -> str:
    if not rows:
        return "No infrastructure check: " + (none[0] if none else "nothing of this project runs yet")
    on = sum(1 for r in rows if r["enabled"])
    failing = [r["label"] for r in rows if r["state"] == "failed"]
    head = f"{on} of {len(rows)} IT checks enabled"
    return head + (f"; failing: {', '.join(failing)}" if failing else "")


# -- changes --------------------------------------------------------------------------------------------------------

def _known(key: str) -> str:
    from kernel.checks import store as cstore

    return cstore.check_of(key)[1]


def set_types(project: Any, types: list[str], *, person: str, persona: str) -> dict[str, Any]:
    """Choose the project's solution types by hand (an empty list goes back to what was detected)."""
    from kernel.checks import store as cstore

    signed(person, persona, SETTERS, "a project's check set")
    cstore.sign_on(project, person, persona)
    bad = [t for t in types if t not in TYPES]
    if bad:
        raise ValueError(f"a solution type is one of {', '.join(TYPES)}, not {', '.join(bad)}")
    with updating_json(project.path(FILE), {}) as kept:
        kept["types"] = list(dict.fromkeys(types))
    project.log("itops_override_changed", {"types": list(types), "person": person, "persona": persona})
    return check_set(project)


def change(project: Any, key: str, action: str, *, person: str, persona: str, why: str = "") -> dict[str, Any]:
    """This project's override: ``add`` a check (with why), ``remove`` one from its set, or ``reset`` it."""
    from kernel.checks import store as cstore

    signed(person, persona, SETTERS, "a project's check set")
    cstore.sign_on(project, person, persona)
    if action not in ("add", "remove", "reset"):
        raise ValueError("action is add, remove or reset")
    key = _known(key)
    with updating_json(project.path(FILE), {}) as kept:
        adds, removes = dict(kept.get("add") or {}), [k for k in kept.get("remove") or [] if k != key]
        adds.pop(key, None)
        if action == "add":
            adds[key] = {"why": str(why or "IT added it for this project")[:300], "by": person}
        elif action == "remove":
            removes.append(key)
        kept["add"], kept["remove"] = adds, removes
    project.log("itops_override_changed", {"check": key, "action": action, "why": str(why)[:300], "person": person,
                                           "persona": persona})
    return check_set(project)


def _changed(mine: dict[str, Any], key: str, action: str, why: str) -> dict[str, Any]:
    """A type's platform change with ``key`` added, taken away or put back (all of it, with no key)."""
    if action == "reset" and not key:
        return {"add": [], "remove": [], "why": {}}
    adds = [k for k in mine.get("add") or [] if k != key]
    removes = [k for k in mine.get("remove") or [] if k != key]
    whys = {k: v for k, v in (mine.get("why") or {}).items() if k != key}
    if action == "add":
        adds.append(key)
        whys[key] = str(why or "IT added it for every project of this type")[:300]
    elif action == "remove":
        removes.append(key)
    return {"add": adds, "remove": removes, "why": whys}


def change_default(factory: Any, solution_type: str, key: str, action: str, *, person: str, persona: str,
                   why: str = "") -> dict[str, Any]:
    """IT's platform default for a type: ``add`` a check, ``remove`` one, or ``reset`` the type to Rihmasto's."""
    from kernel.learn import factory_project

    signed(person, persona, DEFAULTERS, "a platform default check set")
    if solution_type not in TYPES:
        raise ValueError(f"a solution type is one of {', '.join(TYPES)}")
    if action not in ("add", "remove", "reset"):
        raise ValueError("action is add, remove or reset")
    key = _known(key) if action != "reset" or key else ""
    with updating_json(_defaults_path(factory), {}) as kept:
        mine = _changed(kept.get(solution_type) or {}, key, action, why)
        mine["by"] = {"person": person, "persona": persona, "at": factory.clock.stamp()}
        kept[solution_type] = mine
    factory_project(factory).log("itops_default_changed", {"type": solution_type, "check": key or None,
                                                           "action": action, "person": person, "persona": persona})
    return platform(factory)


def apply(project: Any, *, person: str, persona: str, only: list[str] | None = None) -> dict[str, Any]:
    """Enable each check of the set not enabled yet, with its suggested schedule, signed; refused ones said."""
    from kernel.checks import store as cstore

    signed(person, persona, SETTERS, "enabling a check set")
    cstore.sign_on(project, person, persona)
    done, skipped = [], []
    for r in check_set(project)["checks"]:
        if r["enabled"] or (only and r["check"] not in only):
            continue
        try:
            cstore.enable(project, r["check"], person=person, persona=persona, every=r["every"])
            done.append(r["check"])
        except (DecisionRefused, ValueError) as exc:
            skipped.append({"check": r["check"], "why": str(exc)})
    project.log("itops_applied", {"enabled": done, "skipped": [s["check"] for s in skipped], "person": person,
                                  "persona": persona})
    return {"enabled": done, "skipped": skipped, "set": check_set(project)}


def run(project: Any, *, person: str, persona: str, via: str = "person") -> dict[str, Any]:
    """Run the set's enabled infrastructure checks now; each result is recorded as any check's is."""
    from kernel.checks import store as cstore

    signed(person, persona, SETTERS, "running the IT checks")
    cstore.sign_on(project, person, persona)
    ran = []
    for r in check_set(project)["checks"]:
        if not (r["enabled"] and r["infra"]):
            continue
        try:
            row = cstore.run(project, r["check"], person=person, persona=persona, via=via)
            ran.append({"check": r["check"], "verdict": row["verdict"], "summary": row["summary"]})
        except (DecisionRefused, ValueError) as exc:
            ran.append({"check": r["check"], "verdict": "not measured", "summary": f"not run: {exc}"})
    project.log("itops_ran", {"ran": [x["check"] for x in ran],
                              "failed": [x["check"] for x in ran if x["verdict"] == "failed"], "person": person,
                              "persona": persona, "via": via})
    return {"ran": ran, "set": check_set(project)}


# -- the platform ---------------------------------------------------------------------------------------------------

def platform(factory: Any) -> dict[str, Any]:
    """Every type's default set (Rihmasto's, with IT's changes marked), and each project's types and set line."""
    types = []
    for t, spec in TYPES.items():
        checks, scope = _type_checks(factory, t)
        mine = defaults(factory).get(t) or {}
        types.append({"id": t, "label": spec["label"], "scope": scope, "none": spec.get("none"),
                      "checks": [{**c, "added_by_it": c["check"] in (mine.get("add") or [])} for c in checks],
                      "removed": list(mine.get("remove") or []), "by": mine.get("by")})
    return {"types": types, "projects": [_project_line(p) for p in factory.projects() if not p.pid.startswith("_")]}


def _project_line(p: Any) -> dict[str, Any]:
    """One project's set in a line, for the platform's page."""
    try:
        s = check_set(p)
    except (OSError, ValueError, KeyError) as exc:
        return {"project": p.pid, "title": p.meta.get("title"), "line": f"not read: {exc}", "types": [], "checks": 0,
                "enabled": 0, "failing": [], "overridden": False}
    return {"project": p.pid, "title": s["title"], "line": s["line"], "types": [t["label"] for t in s["types"]],
            "checks": len(s["checks"]), "enabled": sum(1 for r in s["checks"] if r["enabled"]),
            "overridden": any(r["scope"] == "project override" for r in s["checks"]) or bool(s["removed"]),
            "failing": [r["label"] for r in s["checks"] if r["state"] == "failed"]}
