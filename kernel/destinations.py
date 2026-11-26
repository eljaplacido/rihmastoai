"""Destinations (FR-DST1): every place a project's capability goes, read from what exists.

The owner (2026-11-24): "Rihmasto is the middle layer of development and all backend work and any external
platform / channel or similar where the solutions are pushed and published or taken to testing." (D-0023)

`view(project)` gathers them in four groups, each destination with its environment (test or production), its
state, its last delivery, its health and what a person can do there:

- **deployed**: each environment of the delivery plan on its paved road, what release runs there and its URL;
  read from `paved_roads.json`, `envs/<env>/current.json`, the releases, `ops/probes.jsonl`, the HTTP probe
  checks and `ops/incidents.json`;
- **data**: the data systems and integrations it reads or writes (databases, APIs, Google Drive) per
  environment, and the webhook sources bound to it; read from the spec's integrations and their bindings
  (kernel/integration_bind.py), Rihmasto's connectors and `hooks`;
- **channels**: where it is used (website chats, the relay's Teams, Slack, email and webhooks, its MCP, HTTP
  and OpenAI faces and who served them); kernel/destinations_more.py;
- **published**: the registries IT named and what was published there (kernel/publish.py), and the outputs
  built for its audiences; kernel/destinations_more.py.

**States**: `planned` (named, but not configured yet: what is missing is said), `configured` (ready, nothing
delivered there yet), `delivered` (something is there, its health not measured yet), `healthy` (the last
probe or check passed), `failing` (the last probe or check failed, a delivery there failed, or an incident is
open) and `not measured` (a probe ran and could not measure). Read only: nothing here writes a file.
The feedback round that probes them and records what changed is kernel/destinations_feedback.py.
"""

from __future__ import annotations

import json
from typing import Any

from kernel import destinations_more as more
from kernel.roads import ENVIRONMENTS, PavedRoads, RoadError, slot_state

STATES = ("planned", "configured", "delivered", "healthy", "failing", "not measured")
GROUPS = ("deployed", "data", "channels", "published")
GROUP_LABEL = {"deployed": "Deployed", "data": "Data and integrations", "channels": "Channels",
               "published": "Published"}
TIER = {"preview": "test", "demo": "test", "staging": "test", "production": "production"}
FEEDBACK = ("ops", "destinations.json")
PROBE_TAIL = 400


def tier(env: str | None) -> str | None:
    return TIER.get(str(env)) if env else None


def dest(did: str, group: str, kind: str, label: str, *, state: str, environment: str | None = None,
         last: dict | None = None, health: dict | None = None, url: str | None = None, details: dict | None = None,
         missing: list | None = None, actions: list | None = None, note: str | None = None) -> dict[str, Any]:
    """One destination, as every view and answer reads it."""
    assert state in STATES, state
    return {"id": did, "group": group, "kind": kind, "label": label, "environment": environment,
            "tier": tier(environment) or (environment if environment in ("test", "production") else None),
            "state": state, "last_delivery": last, "health": health, "url": url, "details": details or {},
            "missing": list(missing or []), "actions": list(actions or []), "note": note}


def action(aid: str, label: str, **more_keys: Any) -> dict[str, Any]:
    return {"id": aid, "label": label, **{k: v for k, v in more_keys.items() if v is not None}}


def feedback(project: Any) -> dict[str, Any]:
    """What the last feedback round found per destination (kernel/destinations_feedback.py)."""
    found = project.read("/".join(FEEDBACK), {})
    return found if isinstance(found, dict) else {}


def _last_probes(project: Any) -> dict[str, dict]:
    path = project.path("ops", "probes.jsonl")
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-PROBE_TAIL:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("slot", "current") == "current" and row.get("environment"):
            out[row["environment"]] = row
    return out


def _probe_health(row: dict | None) -> dict | None:
    if not row or row.get("verdict") == "not applicable":
        return None
    why = (row.get("health") or {}).get("reason") or row.get("reason")
    if row.get("verdict") == "failed" and not why:
        why = "; ".join(f"{s.get('criterion')}: {s.get('reason')}" for s in row.get("scenarios") or []
                        if s.get("verdict") != "passed") or "a probe check failed"
    return {"verdict": row.get("verdict"), "at": row.get("at"), "why": why, "by": "probe",
            "release": row.get("release")}


def _check_health(project: Any, base_url: str | None) -> dict | None:
    """The last result of an HTTP probe check (kernel/checks/probe.py) aimed at this URL, if one is enabled."""
    if not base_url:
        return None
    try:
        from kernel.checks import store as cstore

        found = None
        for key, entry in sorted(cstore.enabled(project).items()):
            url = str((entry.get("config") or {}).get("url") or "")
            if entry.get("kind") == "probe" and url.startswith(base_url):
                rows = cstore.results(project, key, 1)
                if rows and (found is None or str(rows[-1].get("at")) > str(found.get("at"))):
                    found = {"verdict": rows[-1].get("verdict"), "at": rows[-1].get("at"),
                             "why": rows[-1].get("summary"), "by": f"check {key}"}
        return found
    except (OSError, ValueError, KeyError):
        return None


def newest(*rows: dict | None) -> dict | None:
    found = [r for r in rows if r]
    return max(found, key=lambda r: str(r.get("at") or "")) if found else None


def state_of(health: dict | None, *, delivered: bool, failing: str | None = None) -> str:
    if failing:
        return "failing"
    if not delivered:
        return "configured"
    verdict = (health or {}).get("verdict")
    return {"passed": "healthy", "failed": "failing", "not measured": "not measured"}.get(str(verdict), "delivered")


def _incidents(project: Any) -> dict[str, dict]:
    from kernel.canon import Canon

    found = project.read("ops/incidents.json", {}) or {}
    canon, out = Canon(project), {}
    for entry in found.values() if isinstance(found, dict) else []:
        try:
            if canon.get_card(entry["card"])["state"] == "open":
                out[f"{entry['release']}:{entry['environment']}"] = entry
        except (KeyError, OSError, TypeError):
            continue
    return out


def _plan_envs(project: Any) -> list[str]:
    from kernel.deliver import delivery_plan, plan_environments

    try:
        return plan_environments(delivery_plan(project.meta.get("maturity") or "explore"))
    except ValueError:
        return []


def _road_missing(paved: PavedRoads, name: str | None, env: str) -> list[str]:
    try:
        return paved.missing(name, env)
    except (RoadError, OSError, ValueError) as exc:
        return [f"the road could not be checked: {exc}"]


def _deploy_actions(project: Any, env: str, planned: list[str], url: str | None, failing: str | None,
                    card: str | None) -> list:
    pid, out = project.pid, []
    if env in planned and tier(env) == "test":
        out.append(action("deliver", "Deliver to test", control="destinations_deliver", to="test"))
    if env == "production":
        why = None if "production" in planned else "the maturity is not production: raise it in the project's settings"
        out.append(action("promote", "Promote to production", control="destinations_promote", to="production",
                          disabled=why))
    if url and url.startswith(("http://", "https://")):
        out.append(action("open", "Open", href=url))
    if failing:
        out.append(action("investigate", "Investigate", control="destinations_investigate",
                          href=f"#/p/{pid}/inbox" + (f"/{card}" if card else "")))
    out.append(action("check", "Check now", control="destinations_check"))
    return out


class _Reads:
    """What every deployed destination is read against, read once per view."""

    def __init__(self, project: Any, paved: PavedRoads | None) -> None:
        from kernel.deliver import latest_release

        self.paved = paved or PavedRoads.load(project.factory)
        self.planned = _plan_envs(project)
        self.probes, self.incidents = _last_probes(project), _incidents(project)
        self.latest = latest_release(project) or {}
        self.mine = feedback(project).get("destinations") or {}


def _failure(r: _Reads, env: str, slot: dict, incident: dict | None) -> str | None:
    """Why ``env`` is failing: an open incident, or a newer release that failed there; None when neither."""
    if incident:
        return f"incident {incident['card']}: {incident['title']}"
    latest = r.latest
    newer = int(latest.get("release") or 0) > int(slot.get("release") or 0)
    if latest.get("state") == "failed" and str(latest.get("failed_step", "")).endswith(":" + env) and newer:
        return f"release {latest['release']} failed at {latest['failed_step']}: {latest.get('reason')}"
    return None


def _env_health(project: Any, r: _Reads, env: str, slot: dict) -> tuple[dict | None, dict | None, str | None]:
    """An environment's health (the newest of its probe, its HTTP probe check and the last round), its open
    incident, and why it is failing."""
    health = newest(_probe_health(r.probes.get(env)), _check_health(project, slot.get("base_url")),
                    (r.mine.get(f"deployed:{env}") or {}).get("health"))
    incident = r.incidents.get(f"{slot.get('release')}:{env}") if slot else None
    why = _failure(r, env, slot, incident)
    if why and health is None:
        health = {"verdict": "failed", "at": (incident or {}).get("last") or r.latest.get("updated"), "why": why}
    return health, incident, why


def _last_of(slot: dict) -> dict | None:
    if not slot:
        return None
    return {"release": slot["release"], "revision": slot.get("rev12"), "at": slot.get("started"),
            "what": f"release {slot['release']} ({slot.get('rev12')})"}


def _deployed_one(project: Any, r: _Reads, env: str) -> dict[str, Any]:
    name = r.paved.name_for(project, env)
    cfg = (r.paved.roads.get(name) or {}) if name else {}
    slot = slot_state(project, env, "current") or {}
    missing = [] if slot else _road_missing(r.paved, name, env)
    url = slot.get("base_url") or slot.get("console")
    health, incident, why = _env_health(project, r, env, slot)
    state = "planned" if missing else state_of(health, delivered=bool(slot), failing=why)
    label = f"{env.capitalize()} on {name}" if name else f"{env.capitalize()}: no paved road yet"
    card: str | None = (incident or {}).get("card")
    details = {"road": name, "road_kind": cfg.get("kind") or slot.get("kind"), "owner": cfg.get("owner"),
               "workload": slot.get("workload") or "service", "rules": cfg.get("rules") or {}, "incident": card}
    return dest(f"deployed:{env}", "deployed", "road", label, state=state, environment=env, last=_last_of(slot),
                health=health, url=url, details=details, missing=missing, note=why,
                actions=_deploy_actions(project, env, r.planned, url, why, card))


def deployed(project: Any, paved: PavedRoads | None = None) -> list[dict[str, Any]]:
    """Each environment the plan delivers to, and any other one where something runs."""
    r = _Reads(project, paved)
    envs = r.planned + [e for e in ENVIRONMENTS if e not in r.planned and slot_state(project, e, "current")]
    return [_deployed_one(project, r, env) for env in envs]


def _data_one(project: Any, row: dict, decl: dict) -> dict[str, Any]:
    from kernel.integration_decl import KINDS

    env = row["environment"]
    package = (slot_state(project, env, "current") or {}).get("package") or {}
    wired = [i.get("name") for i in package.get("integrations") or [] if isinstance(i, dict)]
    approved = row["state"] == "approved"
    state = "configured" if approved else "planned"
    if approved and row["integration"] in wired:
        state = "delivered"
    waiting = [] if approved else [f"IT approves the binding on {row['road']}: its road card is {row['state']}"]
    connector = (KINDS.get(str(decl.get("kind"))) or {}).get("connector")
    details = _decl_details(decl) | {"road": row["road"], "card": row["card"],
                                     "connector": more.connector_state(project.factory, connector)}
    kind = "Google Drive" if decl.get("kind") == "gdrive" else decl.get("kind")
    return dest(f"data:{row['integration']}:{env}", "data", "integration", f"{row['integration']} ({kind})",
                state=state, environment=env, details=details, missing=row["problems"] or waiting,
                note=f"{decl.get('access', 'read')} access" if decl else None)


def _decl_details(decl: dict) -> dict[str, Any]:
    return {k: decl[k] for k in ("kind", "via", "access", "data_classes", "credentials", "system")
            if decl.get(k) is not None}


def data(project: Any) -> list[dict[str, Any]]:
    """The data systems and integrations it reads or writes, per environment, and the sources bound to it."""
    from kernel import integration_bind

    try:
        status = integration_bind.status(project)
    except (OSError, ValueError, KeyError, RoadError) as exc:
        return [dest("data:unreadable", "data", "integration", "Integrations", state="planned",
                     missing=[f"the integrations could not be read: {exc}"])]
    decls = {d["name"]: d for d in status["integrations"]}
    rows = [_data_one(project, row, decls.get(row["integration"], {})) for row in status["bindings"]]
    return rows + more.hook_sources(project, dest)


def view(project: Any) -> dict[str, Any]:
    """Every destination of the project, grouped, with a summary."""
    found = deployed(project) + data(project) + more.channels(project, dest, action) + \
        more.published(project, dest, action)
    groups = {g: [d for d in found if d["group"] == g] for g in GROUPS}
    return {"project": project.pid, "title": project.meta.get("title"), "maturity": project.meta.get("maturity"),
            "groups": groups, "labels": GROUP_LABEL, "states": list(STATES), "summary": summarize(found),
            "checked": feedback(project).get("at")}


LIVE = ("delivered", "healthy", "failing", "not measured")


def _labels(found: list[dict[str, Any]], group: str, states: tuple[str, ...]) -> list[str]:
    return [d["label"] for d in found if d["group"] == group and d["state"] in states]


def _parts(found: list[dict[str, Any]]) -> list[str]:
    """The summary's clauses: where it runs, the data it reaches, what it is used through, where it is published."""
    running = [f"{d['environment']} ({d['state']})" for d in found if d["group"] == "deployed" and d["state"] in LIVE]
    parts = ["runs in " + ", ".join(running) if running else "runs nowhere yet"]
    n_data = len({d["label"] for d in found if d["group"] == "data"})
    if n_data:
        parts.append(f"reaches {n_data} data system" + ("s" if n_data != 1 else ""))
    used = _labels(found, "channels", ("configured", *LIVE))
    if used:
        parts.append("used through " + ", ".join(used[:4]) + (" and more" if len(used) > 4 else ""))
    pub = _labels(found, "published", ("delivered", "healthy"))
    if pub:
        parts.append("published to " + ", ".join(pub[:3]))
    return parts


def summarize(found: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {s: sum(1 for d in found if d["state"] == s) for s in STATES}
    failing = [d["label"] for d in found if d["state"] == "failing"]
    line = "It " + "; ".join(_parts(found)) + "."
    if failing:
        line += f" {len(failing)} failing: {', '.join(failing[:3])}."
    return {"counts": counts, "failing": failing, "line": line, "total": len(found)}


def where(project: Any) -> dict[str, Any]:
    """"Where this goes" on the project's overview: the summary and the deployed destinations only."""
    v = view(project)
    return {"project": project.pid, "summary": v["summary"],
            "deployed": [{k: d[k] for k in ("id", "label", "environment", "tier", "state", "url", "last_delivery")}
                         for d in v["groups"]["deployed"]]}
