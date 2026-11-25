"""What Rihmasto's other views read from agent observability, through hooks they call when they are in the build
(FR-OBS1). Each reads the hub when asked and keeps nothing; a project whose module is off, or that is not mapped,
gives nothing (or "not measured"), never a zero.

=====================  =====================================================================================
``insight_tiles``      Insights (kernel/insights): QA, the files the IDE agents reworked most and their
                       unrecovered failures; Governance, the share of sessions that read the contract before
                       editing; Usage, the sessions by harness. Tiles in the insights tile shape
``review_items``       Review (kernel/review.py): "From your IDE agents", the sessions that left a failure
                       unrecovered and the files at or above the rework threshold since the person last looked
``session_links``      the agent channel (kernel/agent_channel.py): an external agent's post whose trace names
                       a session id the hub observed, linked to that session
``catalogue_entry``    the copilot's catalogue (kernel/copilot_catalog.py): the view, and whether to suggest
                       turning the module on for a project worked on in IDEs
``check_result``       the checks (kernel/checks): "unrecovered agent failures", passed, failed or not measured;
                       ``check_spec`` makes it a ``kernel.checks.Check`` when that package is in the build
=====================  =====================================================================================

The automations' snapshot action and the "notify on heavy rework" template are in ``automation_hook``.
"""

from __future__ import annotations

import datetime as dt
import importlib
from collections.abc import Callable
from typing import Any

from kernel.agentobs import MODULE, SEES, VIEW, module_on
from kernel.agentobs.client import Hub
from kernel.agentobs.mapping import current, instrumentation
from kernel.agentobs.view import build

GROUP = "from_ide_agents"
WINDOWS = {"24h": dt.timedelta(hours=24), "7d": dt.timedelta(days=7), "30d": dt.timedelta(days=30), "all": None}
CHECK_KIND = "agent_failures"


def optional(name: str) -> Any:
    """A module of another stream when it is in this build, else None."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _when(stamp: Any) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def observed(factory: Any, project: Any, hub: Hub | None = None) -> dict[str, Any] | None:
    """The view of a project whose module is on and that is mapped, or None."""
    if project.pid.startswith("_") or not module_on(project) or current(project) is None:
        return None
    return build(factory, project, persona=SEES[0], hub=hub)


def _scope(factory: Any, pid: str | None) -> list[Any]:
    return [factory.project(pid)] if pid else [p for p in factory.projects() if not p.pid.startswith("_")]


def _tile(key: str, label: str, value: float | None, **kw: Any) -> dict[str, Any]:
    base = optional("kernel.insights.base")
    if base is not None:
        result: dict[str, Any] = base.tile(key, label, value, **kw)
        return result
    measured = value is not None
    return {"key": key, "label": label, "value": value, "measured": measured, "unit": kw.get("unit", ""),
            "display": kw.get("display") or (str(value) if measured else "not measured"), "basis": kw["basis"],
            "line": kw.get("line") if measured else f"Not measured: {kw.get('why')}.",
            "why": None if measured else kw.get("why"), "how": None if measured else kw.get("how"),
            "href": kw.get("href"), "status": kw.get("status") if measured else None, "delta": None,
            "sub": kw.get("sub")}


def _in_window(rows: list[dict[str, Any]], since: dt.datetime | None) -> list[dict[str, Any]]:
    return [r for r in rows if since is None or ((t := _when(r.get("started_at"))) is not None and t >= since)]


def insight_tiles(factory: Any, dimension: str, *, pid: str | None = None, window: str = "7d",
                  hub: Hub | None = None) -> list[dict[str, Any]]:
    """The tiles agent observability adds to an Insights dimension (qa, governance, usage); [] for the others,
    and [] where no project has the module on and a mapping."""
    if dimension not in ("qa", "governance", "usage"):
        return []
    views = [(p, v) for p in _scope(factory, pid) if (v := observed(factory, p, hub)) is not None]
    if not views:
        return []
    span = WINDOWS.get(window)
    since = factory.clock.now() - span if span else None
    measured = [v for _, v in views if (v["sections"].get("sessions") or {}).get("measured")]
    rows = [r for v in measured for r in _in_window(v.get("sessions") or [], since)]
    kw = {"href": f"#/p/{views[0][0].pid}/{VIEW}" if len(views) == 1 else None,
          "why": "the hub holds no session for the mapped projects",
          "how": "open Agent sessions on a project for what to do"}
    return _TILES[dimension](measured, rows, kw)


def _usage(measured: list[dict[str, Any]], rows: list[dict[str, Any]], kw: dict[str, Any]) -> list[dict[str, Any]]:
    per: dict[str, int] = {}
    for r in rows:
        per[str(r["harness"])] = per.get(str(r["harness"]), 0) + 1
    return [_tile("ide_sessions", "IDE agent sessions", len(rows) if measured else None, **kw,
                  basis="sessions the hub recorded that started in the window, by harness",
                  sub=" · ".join(f"{h} {n}" for h, n in sorted(per.items())) or None)]


def _governance(measured: list[dict[str, Any]], rows: list[dict[str, Any]],
                kw: dict[str, Any]) -> list[dict[str, Any]]:
    rates = [v["sections"]["governance"] for v in measured if v["sections"]["governance"].get("measured")]
    first = sum(g.get("sessions_contract_first") or 0 for g in rates)
    code = sum(g.get("sessions_touching_code") or 0 for g in rates)
    return [_tile("ide_contract_first", "Contract read before edit", round(first / code * 100, 1) if code else None,
                  unit="%", basis="IDE agent sessions that read the contract before their first edit, of those that "
                  "touched code (all of the hub's records)",
                  **(kw | {"why": "no session touched code with a known contract file"}))]


def _qa(measured: list[dict[str, Any]], rows: list[dict[str, Any]], kw: dict[str, Any]) -> list[dict[str, Any]]:
    heavy = sum(v["sections"]["rework"].get("files_above_threshold") or 0 for v in measured
                if v["sections"]["rework"].get("measured"))
    stuck = [r for r in rows if r["failures"]["unrecovered"]]
    return [_tile("ide_rework", "Files IDE agents reworked", heavy if measured else None, **kw,
                  basis="files at or above the hub's rework threshold (all of the hub's records)",
                  status="warning" if heavy else "good"),
            _tile("ide_unrecovered", "Unrecovered IDE agent failures", len(stuck) if measured else None, **kw,
                  basis="sessions in the window that left a failure unrecovered",
                  status="critical" if stuck else "good")]


_TILES: dict[str, Callable[[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]]] = {
    "usage": _usage, "governance": _governance, "qa": _qa}


def _item(project: Any, kind: str, ref: str, title: str, at: Any, by: dict[str, Any], rank: float,
          hub_ui: str | None, record: dict[str, Any]) -> dict[str, Any]:
    href = f"#/p/{project.pid}/{VIEW}"
    links = [{"label": "Agent sessions", "href": href}] + ([{"label": "Open in the hub", "href": hub_ui,
                                                             "external": True}] if hub_ui else [])
    return {"id": f"{project.pid}/{kind}/{ref}", "group": GROUP, "kind": kind, "title": title, "project": project.pid,
            "project_title": project.meta.get("title") or project.pid, "at": at, "by": by, "rank": rank,
            "links": links, "record": record, "actions": [{"do": "open", "label": "Open Agent sessions", "href": href}]}


def review_items(factory: Any, *, pid: str | None = None, since: str | None = None,
                 hub: Hub | None = None) -> list[dict[str, Any]]:
    """"From your IDE agents": unrecovered failures and heavy rework since ``since`` (all when None)."""
    after = _when(since) if since else None
    out: list[dict[str, Any]] = []
    for p in _scope(factory, pid):
        v = observed(factory, p, hub)
        if v is None or not (v["sections"].get("sessions") or {}).get("measured"):
            continue
        rows, ui = _in_window(v.get("sessions") or [], after), (v.get("hub") or {}).get("ui")
        out += _failure_items(p, rows, ui) + _rework_items(p, v["sections"]["rework"], rows, after is not None, ui)
    return out


def _failure_items(p: Any, rows: list[dict[str, Any]], ui: str | None) -> list[dict[str, Any]]:
    return [_item(p, "agent_failure", str(r["session_id"]), f"A {r['harness']} session left {s['tool']} on "
                  f"{s['file']} failing", r["started_at"], {"kind": "harness", "name": r["harness"]}, 0, ui,
                  {"session": r["session_id"]} | s) for r in rows for s in r["failures"]["stuck"][:3]]


def _rework_items(p: Any, rw: dict[str, Any], rows: list[dict[str, Any]], since: bool,
                  ui: str | None) -> list[dict[str, Any]]:
    """Files at or above the threshold; with a ``since``, only those a session since then touched."""
    if not rw.get("measured"):
        return []
    touched = {f for r in rows for f in (r.get("touched") or [])}
    heavy = [f for f in rw.get("files") or [] if (f.get("edits") or 0) >= (rw.get("threshold") or 3)]
    return [_item(p, "agent_rework", str(f.get("file")), f"{f.get('file')} was edited {f.get('edits')} times across "
                  f"{f.get('sessions')} sessions", None, {"kind": "harness", "name": "IDE agents"}, 1, ui, dict(f))
            for f in heavy if not since or f.get("file") in touched]


def session_links(factory: Any, project: Any, messages: list[dict[str, Any]],
                  hub: Hub | None = None) -> dict[str, dict[str, Any]]:
    """For each channel message by an external agent whose trace names a session the hub observed: that session
    (``{message id: {session_id, harness, started_at, href}}``)."""
    wanted = {str((m.get("trace") or {}).get("session_id") or (m.get("trace") or {}).get("session") or ""): m["id"]
              for m in messages if isinstance(m, dict) and (m.get("author") or {}).get("kind") == "agent"}
    wanted.pop("", None)
    v = observed(factory, project, hub) if wanted else None
    if v is None:
        return {}
    ui = (v.get("hub") or {}).get("ui")
    return {wanted[str(r["session_id"])]: {"session_id": r["session_id"], "harness": r["harness"],
                                           "started_at": r["started_at"], "href": ui}
            for r in v.get("sessions") or [] if str(r["session_id"]) in wanted}


def catalogue_entry(factory: Any, project: Any | None = None) -> dict[str, Any]:
    """The view for the copilot's catalogue, and whether to suggest turning it on for ``project`` (one adopted or
    attached, whose repository carries the hub's hooks or an AI tool's configuration)."""
    out = {"id": "agent_observability", "label": "Agent sessions (agent observability)", "available": True,
           "module": MODULE, "view": VIEW, "for_personas": list(SEES),
           "what": "what the IDE agents did in a project's repository: sessions by harness, rework, failures and "
                   "whether they were recovered, contract read before edit, the hub's chain check"}
    if project is None:
        return out | {"on": module_on(factory), "suggest": False}
    on = module_on(project)
    inst = instrumentation(project)
    tools = project.read("agent_context.json", None)
    worked_in_ide = inst["instrumented"] or (isinstance(tools, dict) and bool(tools.get("found")))
    suggest = inst["applies"] and worked_in_ide and not on
    why = ("its repository carries the hub's hooks" if inst["instrumented"] else
           "it is worked on with AI coding tools (their configuration is in the repository)")
    return out | {"on": on, "suggest": suggest, "why": why if suggest else None, "instrumentation": inst,
                  "how": "Settings, Modules: turn on Agent observability for this project" if suggest else None}


def check_result(factory: Any, project: Any, hub: Hub | None = None) -> dict[str, Any]:
    """"Unrecovered agent failures": failed when a session left one, passed when none did, else not measured."""
    v = observed(factory, project, hub)
    fl = ((v or {}).get("sections") or {}).get("failures") or {}
    if not fl.get("measured"):
        why = fl.get("why") or "Agent observability is off for this project, or it is not mapped to a hub project"
        return {"verdict": "not measured", "summary": f"not measured: {why}", "evidence": []}
    stuck = fl.get("unrecovered_sessions") or []
    lines = [f"{r['harness']} {r['session_id']}: " + ", ".join(f"{s['tool']} on {s['file']}"
                                                                for s in r["failures"]["stuck"][:3]) for r in stuck]
    if stuck:
        return {"verdict": "failed", "summary": f"{len(stuck)} IDE agent session(s) left a failure unrecovered",
                "evidence": lines[:20]}
    return {"verdict": "passed", "summary": f"no unrecovered failure in {fl.get('tool_failures') or 0} failure(s) "
            f"of {fl.get('tool_events')} tool calls", "evidence": []}


def check_spec() -> Any:
    """The check as a ``kernel.checks.Check`` when that package is in the build, else None."""
    checks = optional("kernel.checks")
    if checks is None or not hasattr(checks, "Check"):
        return None

    def run(ctx: Any) -> dict[str, Any]:
        got = check_result(ctx.project.factory, ctx.project)
        fn: Callable[..., dict[str, Any]] = checks.result
        return fn(got["verdict"], got["summary"], got["evidence"])

    return checks.Check(CHECK_KIND, "Unrecovered agent failures", "whether an IDE agent session left a failure "
                        "unrecovered, read from the agent observability hub", run)
