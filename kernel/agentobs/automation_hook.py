"""Agent observability in the automations (FR-OBS1 with FR-AUT1), plugged in with two calls:

    kernel/automations_text.py     register(au.ACTIONS, TEMPLATES)      the action and the templates
    kernel/automations_actions.py  register_handler(HANDLERS, MODULE)   how the action runs, and its module

- the action **agent_snapshot** records what the hub shows for the firing's project (kernel/agentobs/snapshot.py),
  signed by the automation's owner (a developer or IT); with the module off for that project it is refused;
- the template **notify on heavy rework** notifies a channel when a snapshot finds files newly at or above the
  hub's rework threshold (``agent_rework_heavy``); **unrecovered agent failures** does the same when a snapshot
  finds a session that left a failure unrecovered (``agent_failure_unrecovered``); **snapshot every morning**
  records a project's figures daily, so the two above have something to react to.

None decides anything: a snapshot records figures, and a notice tells people.
"""

from __future__ import annotations

from typing import Any

from kernel.agentobs import MAPPERS, MODULE

ACTION = "agent_snapshot"
TEMPLATES: list[dict[str, Any]] = [
    {"id": "agent_snapshot_daily", "label": "Record what the IDE agents did, every morning", "needs": ["project"],
     "about": "Every morning, record what the agent observability hub shows for a project: its sessions, unrecovered "
              "failures, rework and chain check (Agent observability on).",
     "draft": {"name": "IDE agents, every morning", "trigger": {"kind": "schedule", "daily": "07:00"},
               "action": {"kind": ACTION}, "scope": {"kind": "project", "projects": []}}},
    {"id": "agent_rework_notify", "label": "Notify on heavy rework by IDE agents", "needs": ["subscription"],
     "about": "When a snapshot finds files the IDE agents edited at or above the hub's rework threshold, notify a "
              "channel.",
     "draft": {"name": "Heavy rework by IDE agents", "trigger": {"kind": "event", "types": ["agent_rework_heavy"]},
               "action": {"kind": "notify", "subscription": "",
                          "text": "{project}: IDE agents keep reworking the same files ({event})"},
               "scope": {"kind": "factory"}}},
    {"id": "agent_failure_notify", "label": "Notify on unrecovered agent failures", "needs": ["subscription"],
     "about": "When a snapshot finds an IDE agent session that left a failure unrecovered, notify a channel.",
     "draft": {"name": "Unrecovered agent failures",
               "trigger": {"kind": "event", "types": ["agent_failure_unrecovered"]},
               "action": {"kind": "notify", "subscription": "",
                          "text": "{project}: an IDE agent session left a failure unrecovered ({event})"},
               "scope": {"kind": "factory"}}},
]


def register(actions: dict[str, dict[str, Any]], templates: list[dict[str, Any]]) -> None:
    """Add the action to the allow-list and the templates to the builder's starting points (idempotent)."""
    actions.setdefault(ACTION, {"label": "record what the agent observability hub shows", "personas": MAPPERS,
                                "per_project": True})
    known = {t["id"] for t in templates}
    templates.extend(t for t in TEMPLATES if t["id"] not in known)


def run(factory: Any, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    """The action: a snapshot of the firing's project, signed by the automation's owner."""
    from kernel.agentobs.snapshot import record

    if not f.get("project"):
        raise ValueError("agent_snapshot acts on a project, and the firing names none")
    owner = a["owner"]
    got = record(factory, factory.project(f["project"]), person=owner["person"], persona=owner["persona"],
                 via=f"automation {a['id']}")
    if not got["measured"]:
        return {"outcome": "nothing", "detail": f"not measured: {got.get('why')}"[:300]}
    new = ", ".join(got["new"]) or "nothing new"
    return {"outcome": "done", "detail": f"{got['sessions']} sessions, {len(got['unrecovered_sessions'])} with an "
                                         f"unrecovered failure, {len(got['rework_heavy'])} heavily reworked files; "
                                         f"{new}"[:300]}


def register_handler(handlers: dict[str, Any], module_of: dict[str, str]) -> None:
    """How the action runs, and the module that must be on where it acts."""
    handlers.setdefault(ACTION, run)
    module_of.setdefault(ACTION, MODULE)
