"""What the infrastructure checks measure, found from the project's own records (FR-ITO1).

An infrastructure check (kernel/checks/infra.py, infra_data.py, infra_ai.py) takes its target from its settings when
a person gave one, and otherwise finds it here, so a check set enabled with no settings still measures what the
project has, and says plainly when it has nothing to measure:

- ``urls``: the addresses where the project runs (each environment's base URL, kernel/destinations.py);
- ``bindings``: each declared data integration (kernel/integration_decl.py) with, per environment its maturity
  delivers to, the endpoint IT bound on the paved road (kernel/integration_bind.py), its family (database,
  warehouse, storage, business_api, mcp, rest, drive) and the credentials it names. No value is ever read here;
- ``hosts``: every host and port the two above name, for the resolve-and-connect check.

Reading writes nothing; a record that cannot be read gives nothing, never a guess.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

PORTS = {"http": 80, "https": 443, "postgres": 5432, "postgresql": 5432, "mysql": 3306, "sqlserver": 1433,
         "mssql": 1433}


def as_list(value: Any) -> list[str]:
    """A setting given as one word, a comma-separated line or a list."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def urls(project: Any) -> list[dict[str, str]]:
    """Each environment's base URL where the project runs, http or https only."""
    from kernel import destinations

    try:
        rows = destinations.deployed(project)
    except (OSError, ValueError, KeyError, LookupError, RuntimeError):
        return []
    out = []
    for d in rows:
        url = str(d.get("url") or "")
        if urllib.parse.urlsplit(url).scheme in ("http", "https"):
            out.append({"url": url, "environment": str(d.get("environment") or "")})
    return out


def bindings(project: Any) -> list[dict[str, Any]]:
    """Each declared integration per environment, with the endpoint bound for it (or none yet)."""
    from kernel.deliver import delivery_plan, plan_environments
    from kernel.integration_bind import binding_of, declared
    from kernel.integration_decl import KINDS
    from kernel.roads import PavedRoads, RoadError

    try:
        paved = PavedRoads.load(project.factory)
        envs = plan_environments(delivery_plan(project.meta.get("maturity") or "explore"))
        decls = declared(project)
    except (OSError, ValueError, KeyError, RoadError):
        return []
    out = []
    for decl in decls:
        kind = str(decl.get("kind") or "")
        family = (KINDS.get(kind) or {}).get("family") or "rest"
        rows = []
        for env in envs or ["production"]:
            road = paved.name_for(project, env)
            bound = binding_of(paved.roads.get(road) or {}, decl.get("name", ""), env) if road else None
            rows.append({"environment": env, "road": road, "endpoint": str((bound or {}).get("endpoint") or "")})
        out.append({"name": decl.get("name"), "kind": kind, "family": family, "via": decl.get("via"),
                    "access": decl.get("access", "read"), "credentials": list(decl.get("credentials") or []),
                    "connector": (KINDS.get(kind) or {}).get("connector"), "environments": rows})
    return out


def endpoint_of(binding: dict[str, Any], environment: str | None = None) -> tuple[str, str]:
    """The endpoint bound for ``environment`` (else the first bound one) and its environment."""
    rows = binding.get("environments") or []
    if environment:
        rows = [r for r in rows if r["environment"] == environment]
    found = next((r for r in rows if r["endpoint"]), None)
    return (found["endpoint"], found["environment"]) if found else ("", environment or "")


def host_port(url: str) -> tuple[str, int] | None:
    """The host and port an address names, its scheme's port when it names none."""
    parts = urllib.parse.urlsplit(url)
    if not parts.hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    return parts.hostname, int(port or PORTS.get(parts.scheme.lower(), 443))


def hosts(project: Any) -> list[dict[str, Any]]:
    """Every host and port where the project runs or that a binding names, each once."""
    seen, out = set(), []
    places = [(u["url"], f"where it runs ({u['environment']})") for u in urls(project)]
    for b in bindings(project):
        places += [(r["endpoint"], f"{b['name']} ({r['environment']})") for r in b["environments"] if r["endpoint"]]
    for url, why in places:
        hp = host_port(url)
        if hp and hp not in seen:
            seen.add(hp)
            out.append({"host": hp[0], "port": hp[1], "why": why})
    return out
