"""From capability packs to gateway workloads.

A capability pack pins what a release is. When it declares the workloads its product calls at run
time, under `runtime.workloads`, each becomes a gateway workload: its name, class and data class come
from the pack, and its L1 is the model the pack was accepted with. The site adds the upstream and the
rest of the ladder (L2 to L4), which are its own business.

    {"runtime": {"declared": true, "workloads": [
        {"name": "classify", "class": "batch", "data_class": "internal", "model": "qwen3-8b"}]}}

A pack that declares no runtime (`"declared": false`, what a web-service product's pack says) gives none.

A small capability whose runtime offers the openai face (kernel/runtime_decl.py) is itself a model: its
pack names it under `runtime.agent`, and `agent_workloads` makes the gateway workload of that name whose
L1 is the capability's own OpenAI-compatible endpoint (FR-SC3). A client of the gateway then names the
capability as its model; the capability's pack guard answers 503 until its pack checks out, and the
gateway then says that no upstream answered. The upstream names the faces' bearer token by its variable
(`api_key_env`), as for any upstream.

`check` says where a gateway config has drifted from a pack: a workload missing, of another class,
or whose L1 serves another model, which would be a behaviour change the pack did not accept; and an
agent the pack offers that the gateway does not route to the capability itself.

    python -m gateway.server --config gateway.json --check-pack capability-pack.json
"""

from __future__ import annotations

from typing import Any

from gateway.config import GatewayConfig


def declared_workloads(pack: Any) -> list[dict]:
    """The workloads a pack declares, each with a name and a model; [] when it declares no runtime."""
    runtime = pack.get("runtime") if isinstance(pack, dict) else None
    if not isinstance(runtime, dict) or runtime.get("declared") is not True:
        return []
    found = runtime.get("workloads")
    return [w for w in (found if isinstance(found, list) else [])
            if isinstance(w, dict) and isinstance(w.get("name"), str) and isinstance(w.get("model"), str)]


def workloads_from_pack(pack: dict, upstream: str) -> dict[str, dict]:
    """Gateway workload entries for a pack's declared workloads, with L1 on ``upstream``."""
    source = f"from capability pack {pack.get('pack', '?')} {pack.get('version', '')}".strip()
    return {w["name"]: {"class": w.get("class", "interactive"), "data_class": w.get("data_class", "internal"),
                        "description": w.get("description") or source,
                        "ladder": {"L1": [{"upstream": upstream, "model": w["model"]}]}}
            for w in declared_workloads(pack)}


def declared_agent(pack: Any) -> dict | None:
    """The agent a small capability's pack offers as a model (its name and data class); None when none."""
    runtime = pack.get("runtime") if isinstance(pack, dict) else None
    if not isinstance(runtime, dict) or runtime.get("declared") is not True:
        return None
    agent = runtime.get("agent")
    return agent if isinstance(agent, dict) and isinstance(agent.get("model"), str) else None


def agent_workloads(pack: dict, upstream: str) -> dict[str, dict]:
    """The gateway workload that routes to a capability as a model: named after it, its L1 the capability's
    own OpenAI-compatible face on ``upstream``. {} when the pack offers no agent."""
    agent = declared_agent(pack)
    if agent is None:
        return {}
    source = f"capability pack {pack.get('pack', '?')} {pack.get('version', '')}".strip()
    return {agent["model"]: {"class": "interactive", "data_class": agent.get("data_class", "internal"),
                             "description": f"the capability {agent['model']} as a model, from {source}",
                             "ladder": {"L1": [{"upstream": upstream, "model": agent["model"]}]}}}


def check(config: GatewayConfig, pack: dict) -> list[str]:
    """Where the gateway config does not serve a pack's declared workloads as the pack accepted them, or
    does not route the agent the pack offers to the capability itself."""
    problems = []
    agent = declared_agent(pack)
    if agent is not None:
        have = config.workloads.get(agent["model"])
        l1 = sorted({t.model for t in have.targets if t.level == "L1"}) if have else []
        if have is None:
            problems.append(f"{agent['model']}: the pack offers this capability as a model; the gateway has no "
                            "such workload")
        elif l1 != [agent["model"]]:
            problems.append(f"{agent['model']}: the gateway's L1 serves {', '.join(l1)}, not the capability itself")
    for w in declared_workloads(pack):
        have = config.workloads.get(w["name"])
        if have is None:
            problems.append(f"{w['name']}: the pack declares it; the gateway has no such workload")
            continue
        if w.get("class") and w["class"] != have.workload_class:
            problems.append(f"{w['name']}: the pack says {w['class']}, the gateway {have.workload_class}")
        l1 = sorted({t.model for t in have.targets if t.level == "L1"})
        if l1 != [w["model"]]:
            problems.append(f"{w['name']}: the pack was accepted with {w['model']}; the gateway's L1 serves "
                            f"{', '.join(l1)}")
    return problems

