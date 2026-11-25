"""The paved roads as IT sees and sets them, and the road a project deploys on (FR-GCP1-AC-1, FR-GCP1-AC-6).

- `roads_view`: every road in `paved_roads.json` with the built-in preview, its kind, environments, rules and
  whether it is ready, or exactly what is missing; for a Google Cloud road its projects, region, repository,
  identities, workload and schedule. Read only: it writes nothing.
- `configure`: IT writes a `gcp-cloudrun` road into `paved_roads.json` (the cockpit's Settings, or
  `rihmasto road configure`), checked whole first (kernel/roads_gcp_config.py): a secret with a value, an
  unknown field or a missing identity is refused and nothing is written. The factory's ledger records
  `road_configured` with who, the road's name and the sha256 of its entry. Other kinds are still edited in
  the file by hand (docs/guides/deploying.md).
- `choose`: IT names the road a project deploys on (`paved_road` in project.json) and, on a Google Cloud
  road, the project's own workload, schedule and job settings (`cloudrun`). Recorded as `road_chosen`.
- `render`: the deploy package a project would get in an environment now, rendered and validated, with the
  exact YAML and gcloud commands, and nothing run (`rihmasto road render`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from kernel import roads_gcp_config as gc
from kernel.canon import DecisionRefused
from kernel.ledger import canonical_json
from kernel.people import PERSONAS, is_person
from kernel.roads import BUILTIN_ROADS, ENVIRONMENTS, SCHEMA, PavedRoads, RoadError, make_road, validate_package
from kernel.store import MATURITIES, Factory, Project, updating_json

DECIDERS = ("it",)
NAME_RULE = r"[a-z0-9][a-z0-9-]{1,40}"
KEYS = ("kind", "configured", "owner", "environments", "project_id", "projects", "region", "repository", "deployer",
        "runtime_service_account", "workload", "schedule", "job", "network", "resources", "env", "secrets", "rules",
        "data_bucket", "canary", "start_timeout", "note")
KIND_NOTES = {
    "local-process": "runs the product from a checkout on loopback; ready when configured",
    "docker": "an image per revision and a container per environment; ready when configured and docker is on PATH",
    "azure-containerapps": "renders Azure Container Apps YAML and an az plan; needs an identity and az on PATH",
    "gcp-cloudrun": "a Cloud Run service, or a Cloud Run job on a Cloud Scheduler schedule; needs projects, a region, "
                    "a repository, a deploying and a runtime identity, and gcloud signed in on PATH",
}
SAFE = ("project_id", "projects", "region", "repository", "deployer", "runtime_service_account", "workload",
        "schedule", "job", "network", "resources")


def _signed(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: configuring a road is signed by a named person")
    if persona not in DECIDERS:
        raise DecisionRefused(f"a {persona} may not set a paved road: IT sets them")


def _row(paved: PavedRoads, name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        missing = [] if cfg.get("configured") is True else [f"road {name!r} is not marked \"configured\": true by IT"]
        missing += make_road(name, cfg).missing()
    except RoadError as exc:
        missing = [str(exc)]
    row = {"name": name, "kind": cfg.get("kind"), "configured": cfg.get("configured") is True,
           "owner": cfg.get("owner"), "environments": cfg.get("environments") or list(ENVIRONMENTS),
           "rules": cfg.get("rules") or {},
           "builtin": name in BUILTIN_ROADS and paved.roads.get(name) == BUILTIN_ROADS[name],
           "ready": not missing, "missing": missing,
           "secrets": [s.get("name") for s in cfg.get("secrets") or [] if isinstance(s, dict)],
           "env": sorted((cfg.get("env") or {}) if isinstance(cfg.get("env"), dict) else [])}
    if cfg.get("kind") == gc.KIND:
        row["cloudrun"] = {k: cfg[k] for k in SAFE if k in cfg}
    return row


def roads_view(factory: Factory) -> dict[str, Any]:
    """Every paved road, ready or with what is missing, and what each kind does."""
    paved = PavedRoads.load(factory)
    return {"source": str(factory.paved_roads_path), "exists": factory.paved_roads_path.exists(),
            "problems": paved.problems, "roads": [_row(paved, n, c) for n, c in sorted(paved.roads.items())],
            "maturity": paved.maturity, "kinds": [{"kind": k, "what": v} for k, v in KIND_NOTES.items()],
            "deciders": list(DECIDERS), "environments": list(ENVIRONMENTS)}


def _entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise DecisionRefused("a road is a JSON object")
    unknown = sorted(set(entry) - set(KEYS))
    if unknown:
        raise DecisionRefused(f"a gcp-cloudrun road takes no {', '.join(unknown)}")
    if entry.get("kind") != gc.KIND:
        raise DecisionRefused("Settings configures a gcp-cloudrun road; other kinds are edited in paved_roads.json "
                              "(docs/guides/deploying.md)")
    out = {k: entry[k] for k in KEYS if k in entry}
    out["configured"] = entry.get("configured", True) is True
    envs = out.setdefault("environments", ["staging", "production"])
    if not isinstance(envs, list) or not envs or not set(envs) <= set(ENVIRONMENTS):
        raise DecisionRefused(f"environments must be some of {ENVIRONMENTS}")
    rules = out.setdefault("rules", {})
    if not isinstance(rules, dict):
        raise DecisionRefused("rules must be an object")
    rules.setdefault("region", out.get("region"))
    rules.setdefault("tls", "required: Cloud Run serves HTTPS")
    problems = gc.config_problems(out)
    if problems:
        raise DecisionRefused("the road is not complete: " + "; ".join(problems))
    return out


def configure(factory: Factory, name: str, entry: Any, *, person: str, persona: str,
              maturity: dict[str, str] | None = None) -> dict[str, Any]:
    """IT writes the gcp-cloudrun road ``name`` into paved_roads.json, whole or not at all, and the factory's
    ledger records it. ``maturity`` maps maturities (demo, pilot, production) to this road."""
    from kernel.learn import factory_project

    _signed(person, persona)
    if not re.fullmatch(NAME_RULE, str(name)) or name in BUILTIN_ROADS:
        raise DecisionRefused(f"a road's name is lower-case letters, digits and -, and not {', '.join(BUILTIN_ROADS)}")
    road = _entry(entry)
    maps = dict(maturity or {})
    if not set(maps) <= set(MATURITIES) - {"explore"} or any(v != name for v in maps.values()):
        raise DecisionRefused("maturity maps demo, pilot or production to this road")
    with updating_json(factory.paved_roads_path, {}) as doc:
        doc.setdefault("schema", SCHEMA)
        doc.setdefault("roads", {})[name] = road
        doc.setdefault("maturity", {}).update(maps)
    digest = hashlib.sha256(canonical_json(road).encode("utf-8")).hexdigest()
    factory_project(factory).log("road_configured", {
        "road": name, "kind": road["kind"], "configured": road["configured"], "environments": road["environments"],
        "workload": road.get("workload", "service"), "maturity": maps, "entry_sha256": digest, "person": person,
        "persona": persona})
    return _row(PavedRoads.load(factory), name, road)


def choose(project: Project, road: str, *, person: str, persona: str, workload: str | None = None,
           schedule: dict[str, Any] | None = None, job: dict[str, Any] | None = None) -> dict[str, Any]:
    """IT names the road ``project`` deploys on and, on a Google Cloud road, its workload and schedule."""
    _signed(person, persona)
    paved = PavedRoads.load(project.factory)
    cfg = paved.roads.get(road)
    if cfg is None:
        raise DecisionRefused(f"there is no road {road!r} in paved_roads.json")
    choice = {k: v for k, v in (("workload", workload), ("schedule", schedule), ("job", job)) if v is not None}
    if cfg.get("kind") != gc.KIND and choice:
        raise DecisionRefused("a workload and a schedule are chosen on a gcp-cloudrun road only")
    if choice:
        named: Any = cfg.get("environments") or ["staging", "production"]
        envs = [str(e) for e in named]
        problems = gc.choice_problems(gc.effective(cfg, {"cloudrun": choice}), envs)
        if problems:
            raise DecisionRefused("the choice is not complete: " + "; ".join(problems))
    before = {"paved_road": project.meta.get("paved_road"), "cloudrun": project.meta.get("cloudrun")}
    project.update_meta(paved_road=road, cloudrun=choice or None)
    project.log("road_chosen", {"road": road, "kind": cfg.get("kind"), "choice": choice, "before": before,
                                "person": person, "persona": persona})
    return project_view(project)


def _last_job_probe(project: Project) -> dict[str, Any] | None:
    path = project.path("ops", "probes.jsonl")
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("workload") == "job":
            return {k: rec.get(k) for k in ("at", "verdict", "job", "checks", "failed", "executions", "health")}
    return None


def project_view(project: Project) -> dict[str, Any]:
    """Where a project deploys: each environment of its plan and its road, ready or what is missing, the
    roads it may choose from, its own workload and schedule, and a job's last executions as last read."""
    from kernel.deliver import delivery_plan, plan_environments

    paved, meta = PavedRoads.load(project.factory), project.meta
    maturity = meta.get("maturity")
    envs = plan_environments(delivery_plan(maturity)) if maturity in MATURITIES else []
    rows = []
    for env in envs:
        name = paved.name_for(project, env)
        cfg = paved.roads.get(name) or {} if name else {}
        row = {"environment": env, "road": name, "kind": cfg.get("kind"), "missing": paved.missing(name, env)}
        if cfg.get("kind") == gc.KIND:
            row["cloudrun"] = {k: v for k, v in gc.effective(cfg, meta).items() if k in ("workload", "schedule")}
        rows.append(row | {"ready": not row["missing"]})
    return {"project": project.pid, "maturity": maturity, "chosen": meta.get("paved_road"),
            "cloudrun": meta.get("cloudrun"), "environments": rows,
            "roads": [{"name": n, "kind": c.get("kind"), "environments": c.get("environments") or list(ENVIRONMENTS)}
                      for n, c in sorted(paved.roads.items()) if n not in BUILTIN_ROADS],
            "job_status": _last_job_probe(project), "deciders": list(DECIDERS)}


def render(project: Project, env: str) -> dict[str, Any]:
    """The package ``project`` would deploy in ``env`` now: rendered, validated, and nothing run."""
    from kernel.lanes import _git

    paved = PavedRoads.load(project.factory)
    name = paved.name_for(project, env)
    if name is None or name not in paved.roads:
        raise DecisionRefused(f"no paved road is named for {env}")
    road = paved.road(name)
    bare = project.path("repo.git")
    revision = (_git(bare, "rev-parse", "main", check=False) if bare.exists() else "") or "0" * 40
    image = getattr(road, "image", lambda p, r: "<image>")(project, revision)
    pkg = road.package(project, env=env, slot="current", release=0, revision=revision,
                       artifact={"type": "image", "ref": image})
    rendered = pkg.get("rendered") or {}
    return {"road": name, "kind": road.kind, "environment": env, "revision": revision,
            "missing": paved.missing(name, env), "problems": validate_package(pkg), "yaml": rendered.get("yaml"),
            "scheduler": rendered.get("scheduler"), "commands": rendered.get("commands")}


# -- `rihmasto road ...` ---------------------------------------------------------------------------------

def _schedule(a: argparse.Namespace) -> dict[str, Any] | None:
    if not a.cron:
        return None
    out: dict[str, Any] = {"cron": a.cron, "time_zone": a.time_zone, "retries": a.retries,
                           "service_account": a.scheduler_account}
    return out | ({"environments": a.schedule_env} if a.schedule_env else {})


def add_parsers(sub: Any) -> None:
    """`rihmasto road <command>`, as the command line's parser adds it."""
    cmds = sub.add_parser("road", help="the paved roads, and the road a project deploys on (kernel/road_settings.py)"
                          ).add_subparsers(dest="sub", required=True)
    cmds.add_parser("list", help="every paved road: ready, or what is missing")
    c = cmds.add_parser("configure", help="IT writes a gcp-cloudrun road from a JSON file, checked whole first")
    c.add_argument("name")
    c.add_argument("--file", required=True, help="the road's entry as JSON (docs/guides/gcp.md)")
    c.add_argument("--maturity", action="append", default=[], metavar="MATURITY",
                   help="a maturity this road serves (demo, pilot or production); repeat it")
    r = cmds.add_parser("render", help="the package a project would deploy now: YAML and gcloud commands, nothing run")
    r.add_argument("pid")
    r.add_argument("--env", default="staging", choices=ENVIRONMENTS)
    ch = cmds.add_parser("choose", help="IT names a project's road, and on Google Cloud its workload and schedule")
    ch.add_argument("pid")
    ch.add_argument("road")
    ch.add_argument("--workload", choices=gc.WORKLOADS)
    ch.add_argument("--cron", help='five fields, such as "0 6 * * *"')
    ch.add_argument("--time-zone", dest="time_zone", default="UTC")
    ch.add_argument("--retries", type=int, default=1)
    ch.add_argument("--scheduler-account", dest="scheduler_account", default="")
    ch.add_argument("--schedule-env", dest="schedule_env", action="append", default=[], choices=ENVIRONMENTS)
    rb = cmds.add_parser("rollback", help="go back to the previous revision or image on a Google Cloud road")
    rb.add_argument("pid")
    rb.add_argument("--env", default="production", choices=ENVIRONMENTS)
    rb.add_argument("--reason", required=True)
    ex = cmds.add_parser("executions", help="a scheduled job's last executions, read with gcloud now")
    ex.add_argument("pid")
    ex.add_argument("--env", default="production", choices=ENVIRONMENTS)
    for p in (c, ch, rb):
        p.add_argument("--person", required=True)
        p.add_argument("--persona", required=True, choices=PERSONAS)


def _configure(f: Factory, a: argparse.Namespace) -> Any:
    with open(a.file, encoding="utf-8") as fh:
        entry = json.load(fh)
    return configure(f, a.name, entry, person=a.person, persona=a.persona, maturity={m: a.name for m in a.maturity})


def _executions(f: Factory, a: argparse.Namespace) -> Any:
    from kernel.roads import slot_state
    from kernel.roads_gcp_ops import job_probe

    project = f.project(a.pid)
    state = slot_state(project, a.env, "current")
    if not state or state.get("workload") != "job":
        raise DecisionRefused(f"no scheduled job runs in {a.env}")
    return job_probe(project, a.env, state, record=False)


def _rollback(f: Factory, a: argparse.Namespace) -> Any:
    from kernel.roads_gcp_ops import rollback

    try:
        return rollback(f.project(a.pid), a.env, person=a.person, persona=a.persona, reason=a.reason)
    except RoadError as exc:      # gcloud refused or is missing: said, never a traceback
        raise DecisionRefused(str(exc)) from None


def handlers(emit: Callable[[Any], None]) -> dict[str, Callable[[Factory, argparse.Namespace], None]]:
    """The `rihmasto road` handlers; ``emit`` prints what each returns."""
    return {
        "road list": lambda f, a: emit(roads_view(f)),
        "road configure": lambda f, a: emit(_configure(f, a)),
        "road render": lambda f, a: emit(render(f.project(a.pid), a.env)),
        "road choose": lambda f, a: emit(choose(f.project(a.pid), a.road, person=a.person, persona=a.persona,
                                                workload=a.workload, schedule=_schedule(a))),
        "road rollback": lambda f, a: emit(_rollback(f, a)),
        "road executions": lambda f, a: emit(_executions(f, a)),
    }
