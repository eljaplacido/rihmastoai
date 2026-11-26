"""Ask Rihma's ``act`` proposals (FR-SET1): one cockpit write a person confirms, named by its operation.

The owner (2026-11-24): "when you know how it happens I can also do it on a UIX level or by agent request on chat."
The assistant's first actions (decide, answer, pause...) each have their own shape (kernel/assistant_rules.py
``ACTIONS``). Every other write the cockpit makes by a click is offered here as an **operation**: its cockpit
route (method and path), the arguments it needs, what it sends, and the control of the map (cockpit/ui_map.json)
that does the same by hand. A proposal ``act(op, ...)`` is checked here (``check``): the operation exists, its
arguments are given and plain, and the project it acts on exists and is not archived (but for restoring and
removing). The check fills the proposal's ``call`` (method, path, body) from the table, never from the words of a
model, so the cockpit's Confirm sends exactly that request, signed by the person who confirms it.

Nothing here writes. The routes behind each operation check everything again, as for a click.
"""

from __future__ import annotations

import re
from typing import Any

# op -> (label, method, path template, the arguments it needs, the arguments it sends, the map's control)
OPS: dict[str, tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]] = {
    "archive_project": ("Archive the project", "POST", "/api/projects/{pid}/archive", (), ("reason",),
                        "archive_project"),
    "restore_project": ("Restore the project", "POST", "/api/projects/{pid}/restore", (), (), "restore_project"),
    "remove_project": ("Remove the project for good (its records are exported first)", "POST",
                       "/api/projects/{pid}/remove", ("confirm",), ("confirm",), "remove_project"),
    "setup_step": ("Set up", "POST", "/api/projects/{pid}/setup/{item}", ("item",), ("suggestion",), "setup_do"),
    "accept_suggestion": ("Set up a suggested automation", "POST",
                          "/api/projects/{pid}/automation-suggestions/{suggestion}/accept", ("suggestion",), (),
                          "automations_suggest_accept"),
    "dismiss_suggestion": ("Dismiss a suggested automation", "POST",
                           "/api/projects/{pid}/automation-suggestions/{suggestion}/dismiss", ("suggestion",), (),
                           "automations_suggest_dismiss"),
    "add_automation": ("Set up the automation", "POST", "/api/automations", ("automation",), ("automation",),
                       "automations_describe"),
    "pause_automation": ("Pause an automation", "POST", "/api/automations/{automation_id}/pause",
                         ("automation_id",), ("reason",), "automations_pause"),
    "resume_automation": ("Resume an automation", "POST", "/api/automations/{automation_id}/resume",
                          ("automation_id",), (), "automations_resume"),
    "remove_automation": ("Remove an automation", "POST", "/api/automations/{automation_id}/remove",
                          ("automation_id",), (), "automations_remove"),
    "run_automation": ("Run an automation now", "POST", "/api/automations/{automation_id}/run", ("automation_id",),
                       (), "automations_run"),
    "dry_run_automation": ("Dry-run an automation", "POST", "/api/automations/{automation_id}/dry-run",
                           ("automation_id",), (), "automations_dry_run"),
    "set_tags": ("Set the project's tags", "PUT", "/api/projects/{pid}/tags", ("tags",), ("tags",),
                 "automations_tags"),
    "enable_check": ("Enable a check", "POST", "/api/projects/{pid}/checks/{check}/enable", ("check",), ("every",),
                     "health_enable"),
    "disable_check": ("Disable a check", "POST", "/api/projects/{pid}/checks/{check}/disable", ("check",), (),
                      "health_disable"),
    "run_check": ("Run a check now", "POST", "/api/projects/{pid}/checks/{check}/run", ("check",), (), "health_run"),
    "align_scan": ("Read the repository for alignment", "POST", "/api/projects/{pid}/repo-alignment/scan", (), (),
                   "align_scan"),
    "review_done": ("Mark the review done", "POST", "/api/review/done", (), ("project",), "mark_all_reviewed"),
    "build_outputs": ("Build the chosen outputs", "POST", "/api/projects/{pid}/outputs/build", (), (),
                      "build_outputs"),
    "build_pack": ("Build the capability pack", "POST", "/api/projects/{pid}/pack/build", (), (), "build_pack"),
    "run_assessment": ("Assess the project now", "POST", "/api/projects/{pid}/assessment", (), (),
                       "run_assessment"),
    "stop_autopilot": ("Stop the autopilot", "POST", "/api/projects/{pid}/autopilot/stop", (), ("reason",),
                       "autopilot_stop"),
    "pause_channel": ("Pause the agent channel", "POST", "/api/projects/{pid}/channel/pause", (), ("reason",),
                      "channel_pause"),
    "log_signal": ("Log a signal on the delivery square", "POST", "/api/signals", ("text",), ("text", "channel"),
                   "log_signal"),
    "set_watch": ("Set up the watch of an adopted project", "POST", "/api/projects/{pid}/watch", (),
                  ("parts", "subscription"), "watch_setup"),
    "check_destinations": ("Check the destinations now", "POST", "/api/projects/{pid}/destinations/check", (), (),
                           "destinations_check"),
    # Agent operations (FR-AOP1): an optimisation filed as a change, the Optimise audit recorded
    "file_agent_optimisation": ("File an optimisation as a change", "POST",
                                "/api/projects/{pid}/agent-ops/proposals/{proposal}/change", ("proposal",), (),
                                "agent_ops_change"),
    "record_agent_ops_audit": ("Record the Optimise audit", "POST", "/api/agent-ops/audit", (), ("project",),
                               "agent_ops_audit"),
    "set_model_price": ("Set a model's price", "POST", "/api/agent-ops/prices", ("model",),       # FR-AOP2
                        ("model", "input", "output", "cached", "local"), "agent_ops_price"),
    # integrations and data (kernel/itdata_actions.py, FR-ITD1): the project the body names, else the platform's
    "check_integrations": ("Check the integrations now", "POST", "/api/it-data/check", (), ("project", "item"),
                           "itdata_check"),
    "disable_connection": ("Turn a connection off", "POST", "/api/it-data/disable", ("item",),
                           ("project", "item", "reason"), "itdata_disable"),
    "remind_rotation": ("Remind to rotate a credential", "POST", "/api/it-data/rotate-reminder", ("credential",),
                        ("project", "credential", "days"), "itdata_rotate"),
}
from kernel.hitl_chat import OPS as _HITL_OPS  # noqa: E402  (people in the loop, FR-HITL1)

OPS.update(_HITL_OPS)
# Operations that act on a project (their path names {pid}), and those an archived project still takes.
ON_ARCHIVED = ("restore_project", "remove_project")
_PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:.-]{0,80}\Z")


def label(op: str) -> str:
    return OPS[op][0]


def control(op: str) -> str:
    return OPS[op][5]


def needs_project(op: str) -> bool:
    return "{pid}" in OPS[op][2]


def call(op: str, args: dict[str, Any], pid: str | None) -> dict[str, Any]:
    """The request Confirm sends: the table's method and path, filled with plain ids only, and its body."""
    _, method, path, needed, sent, _ = OPS[op]
    values = {"pid": pid or "", **{k: args.get(k) for k in needed}}
    for key in re.findall(r"\{(\w+)\}", path):
        if not _PLAIN.match(str(values.get(key) or "")):
            raise ValueError(f"{key} is not a plain id")
    filled = path.format(**{k: str(v) for k, v in values.items() if isinstance(v, (str, int))})
    return {"method": method, "path": filled, "body": {k: args[k] for k in sent if k in args}}


def _project_problem(factory: Any, op: str, pid: str | None) -> str | None:
    if not needs_project(op):
        return None
    if not pid or pid.startswith("_"):
        return "no project is open: open the project first, or name it"
    path = factory.projects_dir / pid / "project.json"
    if not path.exists():
        return f"no project {pid}"
    from kernel.project_archive import is_archived

    archived = is_archived(factory.project(pid))
    if archived and op not in ON_ARCHIVED:
        return f"{pid} is archived: restore it first"
    if op in ON_ARCHIVED and not archived:
        return f"{pid} is not archived" + (": archive it first" if op == "remove_project" else "")
    return None


def _archive_problem(op: str, args: dict[str, Any], pid: str | None, persona: str) -> str | None:
    """Archiving, restoring and removing: who may, and a removal confirmed by the project's id."""
    if op not in ("archive_project", *ON_ARCHIVED):
        return None
    from kernel.project_archive import ARCHIVERS

    if persona not in ARCHIVERS:
        return f"as {persona} you may not archive, restore or remove a project (may: {', '.join(ARCHIVERS)})"
    if op == "remove_project" and str(args.get("confirm")) != pid:
        return "a removal is confirmed by naming the project's id"
    return None


def check(factory: Any, project: Any, persona: str, args: dict[str, Any]) -> str | None:
    """None when the ``act`` proposal may be offered; then ``args["call"]`` holds the request Confirm sends."""
    op = str(args.get("op") or "")
    if op not in OPS:
        return f"unknown operation {op!r}"
    pid = str(args.get("project") or (project.pid if project is not None else "")) or None
    missing = [k for k in OPS[op][3] if args.get(k) in (None, "", [])]
    if missing:
        return f"missing {', '.join(missing)}"
    why = _project_problem(factory, op, pid) or _archive_problem(op, args, pid, persona)
    if why:
        return why
    try:
        args["call"] = call(op, args, pid)
    except (ValueError, KeyError, IndexError) as exc:
        return str(exc)
    args.setdefault("summary", label(op) + (f" ({pid})" if pid and needs_project(op) else ""))
    args["control"] = control(op)
    return None


def proposal(factory: Any, op: str, args: dict[str, Any], *, persona: str, project: Any = None,
             summary: str | None = None) -> dict[str, Any] | None:
    """An ``act`` proposal, checked; None when it may not be offered."""
    full = {"op": op, **args, **({"summary": summary} if summary else {})}
    if check(factory, project, persona, full):
        return None
    pid = full.get("project") or (project.pid if project is not None else None)
    return {"action": "act", "args": full, "persona": persona, "project": pid}
