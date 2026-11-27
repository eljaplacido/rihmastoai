"""Integrations and data (FR-ITD1): the platform's view and one project's, and what each agent may reach.

kernel/itdata.py reads each kind of connection. This module puts them together:

- ``project_view(project)``: what this project connects to: the data integrations its spec declares with their
  bindings per environment (endpoint host, access, data classes, credentials by name, IT's approval), where it
  runs, the relay channels that carry its events, the webhook sources and website chats that feed it, the
  connectors and registries it uses, and the model endpoints its roles send prompts to; what each agent may
  reach; and the data-flow diagram (kernel/itdata_flow.py). A confidential project's hosted endpoints are marked
  refused: they are never called for it (kernel/confidential.py).
- ``platform_view(factory)``: every connection of the platform, each project's integrations, every credential
  by name, and the factory home's data stores with their sizes, retention and ledger integrity
  (kernel/data_stores.py).

Reading writes nothing.
"""

from __future__ import annotations

from typing import Any

from kernel import itdata as it
from kernel import itdata_flow

ORDER = ("integration", "road", "relay", "hook", "chat", "connector", "registry", "model")
WORST = (it.OUTSIDE, it.UNKNOWN, it.NETWORK, it.LOCAL)
AGENTS = [
    {"id": "analyst", "label": "Analyst", "reaches": "the request, the answers, the material you added and the "
     "project's records", "never": "secret values, other projects, the hidden tests"},
    {"id": "holdout_author", "label": "Hidden-test author", "reaches": "the requirements; it writes the hidden tests "
     "into the holdout custody", "never": "the code, secret values"},
    {"id": "builder", "label": "Builder", "reaches": "a clean copy of the code in its own lane; each declared "
     "integration only through a stand-in on this machine", "never": "the real systems, secret values, the hidden "
     "tests"},
    {"id": "verifier", "label": "Reviewer", "reaches": "the change and its tests", "never": "the hidden tests, secret "
     "values"},
    {"id": "assistant", "label": "Ask Rihma", "reaches": "a snapshot of the records the person may see; it proposes "
     "and a person confirms", "never": "secret values; it never acts by itself"},
    {"id": "ide", "label": "Coding agents (MCP)", "reaches": "the project's records through the AI tool connection's "
     "read tools; proposals in the agent channel that a person confirms", "never": "secret values, decisions"},
]


def _worst(places: list[str]) -> str:
    return next((w for w in WORST if w in places), it.UNKNOWN)


def _where(endpoint: str) -> str:
    return it.LOCAL if endpoint.startswith("sqlite:") else it.locality(endpoint)


def _binding_rows(project: Any, decl: dict[str, Any], rows: list[dict[str, Any]], paved: Any) -> tuple:
    """Per environment: the road, its state, the endpoint's host; with the endpoints and credentials bound."""
    from kernel.integration_bind import binding_of

    envs, endpoints, creds = [], [], {}
    for r in rows:
        cfg = (paved.roads.get(r["road"]) or {}) if r["road"] else {}
        binding = binding_of(cfg, decl["name"], r["environment"]) or {}
        endpoint = str(binding.get("endpoint") or "")
        if endpoint:
            endpoints.append(endpoint)
        for s in binding.get("secrets") or []:
            if isinstance(s, dict) and s.get("name"):
                creds[s["name"]] = it.ref_credential(s["name"], str(s.get("ref") or ""))
        envs.append({"environment": r["environment"], "road": r["road"], "state": r["state"], "card": r["card"],
                     "host": it.host_of(endpoint), "problems": r["problems"]})
    for name in decl.get("credentials") or []:
        creds.setdefault(name, {"name": name, "where": "not bound to a place yet", "set": None})
    return envs, endpoints, list(creds.values())


def _approval(envs: list[dict[str, Any]]) -> list[str]:
    out = []
    for e in envs:
        out += [f"{e['environment']}: {p}" for p in e["problems"]]
        if not e["problems"] and e["state"] != "approved":
            out.append(f"{e['environment']}: IT approves the binding on {e['road']} (its road card is {e['state']}) "
                       "in the Inbox")
    return out


def _integration(project: Any, decl: dict[str, Any], rows: list[dict[str, Any]], paved: Any) -> dict[str, Any]:
    from kernel.integration_decl import KINDS

    envs, endpoints, creds = _binding_rows(project, decl, rows, paved)
    name, kind = decl["name"], decl.get("kind")
    first = next((e for e in endpoints if e.startswith(("http://", "https://"))), None)
    return it.item(f"integration:{name}", "integration", f"{name} ({'Google Drive' if kind == 'gdrive' else kind})",
                   direction="in" if decl.get("access", "read") == "read" else "both",
                   where=_worst([_where(e) for e in endpoints]) if endpoints else it.UNKNOWN,
                   host=it.host_of(first), data_classes=decl.get("data_classes") or [], credentials=creds,
                   missing=_approval(envs), projects=[project.pid], scope="project", access=decl.get("access", "read"),
                   via=decl.get("via"), environments=envs, probe=it.probe_of(first),
                   connector=(KINDS.get(str(kind)) or {}).get("connector"), open=f"#/p/{project.pid}/plan",
                   note=f"{decl.get('access', 'read')} access via {decl.get('via') or 'its default way'}",
                   disable={"why_not": "a declared integration is withdrawn as a change in the Plan's Data "
                                       "integrations (Change), or IT declines its road card in the Inbox"})


def integrations_of(project: Any) -> list[dict[str, Any]]:
    from kernel import integration_bind
    from kernel.roads import PavedRoads, RoadError

    try:
        status = integration_bind.status(project)
        paved = PavedRoads.load(project.factory)
    except (OSError, ValueError, KeyError, RoadError) as exc:
        return [it.item("integration:unreadable", "integration", "Integrations", direction="in", where=it.UNKNOWN,
                        missing=[f"the integrations could not be read ({exc}): open the Plan's Data integrations"],
                        scope="project", projects=[project.pid])]
    return [_integration(project, d, [r for r in status["bindings"] if r["integration"] == d["name"]], paved)
            for d in status["integrations"]]


def _road_health(d: dict[str, Any]) -> dict[str, Any] | None:
    h = d.get("health")
    if not h:
        return None
    return {"ok": {"passed": True, "failed": False}.get(str(h.get("verdict"))), "at": h.get("at"), "why": h.get("why"),
            "by": h.get("by") or "probe", "failures": 1 if h.get("verdict") == "failed" else 0, "latency_ms": None}


def roads_of(project: Any) -> list[dict[str, Any]]:
    from kernel import destinations

    out = []
    for d in destinations.deployed(project):
        kind = str((d.get("details") or {}).get("road_kind") or "")
        where = it.locality(d["url"]) if d.get("url") else (it.OUTSIDE if kind in it.ROAD_OUTSIDE else it.LOCAL)
        out.append(it.item(f"road:{d['environment']}", "road", d["label"], direction="out", where=where,
                           host=it.host_of(d.get("url")), missing=d.get("missing") or [], scope="project",
                           projects=[project.pid], data_classes=["the product and the data it keeps"],
                           environment=d["environment"], native=_road_health(d), open=f"#/p/{project.pid}/destinations",
                           note=f"{kind or 'no road yet'}; checked and delivered from Destinations",
                           disable={"why_not": "a running environment is stopped from Destinations or IT's road "
                                               "settings"}))
    return out


def _published(project: Any) -> set[str]:
    from kernel.publish import history

    return {str(h.get("registry")) for h in history(project) if h.get("registry")}


def _refuse_hosted(items: list[dict[str, Any]]) -> None:
    """A confidential project never calls a hosted model endpoint: it is marked refused, and sends nothing."""
    for x in items:
        if x["kind"] == "model" and x["locality"] in it.LEAVES:
            x["refused"] = True
            x["note"] = "this project is confidential: a hosted endpoint is never called for it"


BLOCKED = ("Blocked here: this project is confidential and this role's model is hosted, so its work is refused until "
           "a model on this machine or your network is set for it in Models setup.")


def _blocked(role: str, mine: list[dict[str, Any]]) -> str | None:
    """Why a role does no work in a confidential project: its own (primary) model is a refused hosted endpoint, and
    kernel/confidential.require_local refuses a hosted primary whatever its fallback. None when it may work."""
    primary = [x for x in mine if role in x.get("roles", [])]
    return BLOCKED if any(x.get("refused") for x in primary) else None


def agents(items: list[dict[str, Any]], project: Any = None) -> list[dict[str, Any]]:
    """What each agent may reach and never reaches, the model endpoints it sends its prompts to, and whether any
    of them is outside this machine and your network."""
    out = []
    for a in AGENTS:
        mine = [x for x in items if x["kind"] == "model" and a["id"] in {r.split(" ")[0] for r in x.get("roles", [])}]
        out.append({**a, "models": [x["id"] for x in mine], "model_labels": [x["label"] for x in mine],
                    "leaves": any(it.leaves(x) for x in mine), "blocked": _blocked(a["id"], mine)})
    if project is not None:
        reach = [f"{x['label']} ({x.get('access', 'read')})" for x in items if x["kind"] == "integration"]
        out.append({"id": "product", "label": "The delivered product", "models": [], "model_labels": [],
                    "blocked": None,
                    "reaches": ", ".join(reach) + ", each bound and approved by IT on its road" if reach else
                    "no declared data system", "never": "anything not declared in its spec and approved by IT",
                    "leaves": any(it.leaves(x) for x in items if x["kind"] in ("integration", "road"))})
    return out


def _sorted(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda x: (ORDER.index(x["kind"]) if x["kind"] in ORDER else 99, x["label"]))


def _checked(factory: Any, items: list[dict[str, Any]]) -> str | None:
    found = [str(x["health"]["at"]) for x in items if x["health"] and x["health"].get("by") == "check"]
    return max(found, default=None)


def _scoped(x: dict[str, Any], pid: str) -> None:
    """``project`` when it is this project's alone; ``shared`` when it serves other projects too; ``platform`` when
    it serves every project. Turning off one that is not this project's alone is signed on the platform and warned
    about first (``disable["wide"]``)."""
    if x["scope"] == "project" or x["projects"] == [pid]:
        x["scope"] = "project"
        return
    x["scope"] = "shared" if pid in x["projects"] else "platform"
    if (x.get("disable") or {}).get("how"):
        others = len(x["projects"]) - 1
        x["disable"]["wide"] = (f"it also serves {others} other project{'s' if others != 1 else ''}"
                                if x["scope"] == "shared" else "it serves every project, not only this one") + \
            ": turning it off stops it for all of them"


def project_view(project: Any) -> dict[str, Any]:
    """Everything this project connects to, what each agent may reach, and its data flow."""
    from kernel.confidential import confidential

    factory, pid = project.factory, project.pid
    ints = integrations_of(project)
    used = {x["connector"] for x in ints if x.get("connector")}
    items = ints + roads_of(project) + it.relays(factory, pid) + it.hooks_in(factory, pid) + \
        it.chats_in(factory, pid) + it.connectors_in(factory, used) + it.registries_in(factory, _published(project)) + \
        it.models(factory)
    for x in items:
        _scoped(x, pid)
    secret = confidential(project)
    if secret:
        _refuse_hosted(items)
    items = _sorted(it.with_health(factory, items))
    who = agents(items, project)
    return {"project": pid, "title": project.meta.get("title"), "confidential": secret, "items": items,
            "kinds": it.KIND_LABEL, "summary": it.summarize(items), "credentials": it.credentials(factory, items),
            "agents": who, "flow": itdata_flow.build(items, who, project.meta.get("title") or pid),
            "checked": _checked(factory, items)}


def _projects(factory: Any) -> list[dict[str, Any]]:
    from kernel.confidential import confidential
    from kernel.integration_bind import declared

    out = []
    for p in factory.projects():
        if p.pid.startswith("_"):
            continue
        decls = declared(p)
        out.append({"pid": p.pid, "title": p.meta.get("title"), "confidential": confidential(p),
                    "integrations": [{"name": d.get("name"), "kind": d.get("kind"), "access": d.get("access", "read"),
                                      "data_classes": d.get("data_classes") or []} for d in decls]})
    return out


def _stores(factory: Any) -> dict[str, Any]:
    from kernel import data_stores

    v = data_stores.view(factory)
    return {k: v[k] for k in ("stores", "bytes", "integrity", "retain_days", "never_cleaned", "cleanable")}


def platform_view(factory: Any, *, stores: bool = True) -> dict[str, Any]:
    """Every connection of the platform, each project's integrations, the credentials and the data stores (left
    out with ``stores=False``: a check or a reminder needs the connections only)."""
    items = it.models(factory) + it.relays(factory) + it.hooks_in(factory) + it.connectors_in(factory) + \
        it.registries_in(factory) + it.roads_in(factory) + it.chats_in(factory)
    items = _sorted(it.with_health(factory, items))
    projects = _projects(factory)
    return {"project": None, "items": items, "kinds": it.KIND_LABEL, "summary": it.summarize(items),
            "credentials": it.credentials(factory, items), "agents": agents(items), "projects": projects,
            "stores": _stores(factory) if stores else None, "checked": _checked(factory, items)}


def find(factory: Any, item_id: str, project: Any = None) -> dict[str, Any]:
    """One connection by its id, from the project's view or the platform's; KeyError when there is none."""
    view = project_view(project) if project is not None else platform_view(factory, stores=False)
    for x in view["items"]:
        if x["id"] == item_id:
            return x
    raise KeyError(f"no connection {item_id!r} here: the view lists each one's id")
