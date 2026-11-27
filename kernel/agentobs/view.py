"""The Agent sessions view of one project (FR-OBS1): read from the hub when it is asked for, never kept.

Six sections, each **measured** or **not measured** with why and how to get it measured (never a zero for what
was not seen): the sessions by harness over time, the rework hotspots, the failures and whether each was
recovered, governance coherence (sessions that read the contract before editing), the session trajectories, and
the hub's own hash-chain verification with what its verdict attests. Every section links into the hub's own page
for the detail. The view is for developers and IT (``SEES``); for any other persona it says so and reads nothing.
"""

from __future__ import annotations

from typing import Any

from kernel.agentobs import DEFAULT_URL, HUB, MAPPERS, SEES, VIEW, derive, module_on, settings
from kernel.agentobs.client import Hub, HubError, HubUnreachable, from_settings
from kernel.agentobs.mapping import candidates, current, instrumentation, suggest

SECTIONS = ("sessions", "rework", "failures", "governance", "trajectory", "chain")
MAX_ROWS = 50
HUB_START = ("in the hub's checkout: `npm install`, `npm run build`, then `npm run hub:dev` (it serves "
             + DEFAULT_URL + ")")


def nm(why: str, how: str) -> dict[str, Any]:
    """A section that is not measured, with why and how to get it measured."""
    return {"measured": False, "why": why, "how": how}


def _all_nm(why: str, how: str) -> dict[str, Any]:
    return {k: nm(why, how) for k in SECTIONS}


def _instrument_how(inst: dict[str, Any]) -> str:
    return ("instrument the repository with the hub's own command, in your shell: "
            + inst["commands"][1]["command"] + "; then work in it with Claude Code, Cursor or OpenCode")


def _base(project: Any, persona: str) -> dict[str, Any]:
    return {"project": project.pid, "title": project.meta.get("title"), "view": VIEW, "persona": persona,
            "for_personas": list(SEES), "mappers": list(MAPPERS), "applies": persona in SEES,
            "module_on": module_on(project), "by": "read from the hub when asked; nothing is kept"}


def build(factory: Any, project: Any, *, persona: str, hub: Hub | None = None) -> dict[str, Any]:
    """The view's whole read model for ``persona``."""
    out = _base(project, persona)
    if not out["applies"]:
        out["why"] = "the Agent sessions view is for developers and IT"
        return out
    out["instrumentation"] = inst = instrumentation(project)
    if not out["module_on"]:
        out["sections"] = _all_nm("Agent observability is not turned on for this project",
                                  "a developer or IT turns it on in Settings, Modules (it is off by default)")
        return out
    s = settings(factory)
    hub = hub or from_settings(factory)
    out["hub"] = {"configured": hub is not None, "url": s["url"], "where": s["where"], "token_env": s["token_env"],
                  "set_by": s["set_by"], "reachable": None, "chain_attests": None}
    out["mapping"] = {"current": current(project), "candidates": candidates(project), "suggested": None,
                      "hub_projects": []}
    if hub is None:
        out["sections"] = _all_nm(f"no address is set for {HUB}",
                                  "IT sets it in Settings, Agent observability; " + HUB_START)
        return out
    return _read(hub, out, inst)


def _read(hub: Hub, out: dict[str, Any], inst: dict[str, Any]) -> dict[str, Any]:
    try:
        out["hub"]["chain_attests"] = hub.health().get("chain_attests")
        out["hub"]["reachable"] = True
        listed = hub.projects()
    except (HubUnreachable, HubError) as exc:
        out["hub"].update(reachable=False, error=str(exc))
        out["sections"] = _all_nm(f"{HUB} did not answer: {exc}", "start it; " + HUB_START)
        return out
    mapping = out["mapping"]
    mapping["hub_projects"] = [{k: p.get(k) for k in ("project_id", "title", "last_event_at", "last_harness",
                                                      "event_count")} for p in listed[:MAX_ROWS]]
    mapping["suggested"] = suggest(mapping["candidates"], listed)
    pid = (mapping["current"] or {}).get("hub_project")
    out["hub"]["ui"] = hub.ui(pid)
    if not pid:
        out["sections"] = _all_nm("this project is not mapped to a project of the hub",
                                  "a developer or IT confirms the suggested hub project, or chooses one, below")
        return out
    return _sections(hub, pid, out, inst)


def _fetch(hub: Hub, pid: str) -> tuple[dict[str, Any], str | None]:
    got: dict[str, Any] = {}
    try:
        got["project"] = hub.project(pid)
        if got["project"] is None:
            return got, None
        got["sessions"] = hub.sessions(pid)
        for name in ("insight", "intelligence", "metrics"):
            got[name] = hub.section(pid, name)
        got["chain"] = hub.chain(pid)
    except (HubUnreachable, HubError) as exc:
        return got, str(exc)
    return got, None


def _sections(hub: Hub, pid: str, out: dict[str, Any], inst: dict[str, Any]) -> dict[str, Any]:
    got, error = _fetch(hub, pid)
    if error:
        out["sections"] = _all_nm(f"{HUB} stopped answering: {error}", "check that it still runs; " + HUB_START)
        return out
    if got.get("project") is None:
        out["sections"] = _all_nm(f"the hub has no project {pid}: no session from this repository reached it",
                                  _instrument_how(inst))
        return out
    out["hub_project"] = got["project"]
    intel = got["intelligence"]
    gov = intel.get("governance") if isinstance(intel.get("governance"), dict) else {}
    contract_files = {str(d.get("file")) for d in gov.get("docs") or [] if isinstance(d, dict)
                      and d.get("kind") == "contract"}
    rows = [derive.session_row(s, contract_files) for s in got["sessions"]]
    how = _instrument_how(inst)
    out["sections"] = {"sessions": _sessions(got["sessions"], rows, got["insight"], how),
                       "rework": _rework(got["insight"], how), "failures": _failures(intel, rows, how),
                       "governance": _governance(gov, rows, how), "trajectory": _trajectory(intel, rows, how),
                       "chain": _chain(got["chain"], out["hub"]["chain_attests"])}
    out["sessions"] = rows[:MAX_ROWS]
    out["metrics"] = got["metrics"]
    return out


def _sessions(sessions: list[dict[str, Any]], rows: list[dict[str, Any]], insight: dict[str, Any],
              how: str) -> dict[str, Any]:
    if not sessions:
        return nm("the hub holds no session for this project yet", how)
    return {"measured": True, "count": len(sessions), **derive.by_harness(sessions),
            "harness_activity": insight.get("harness_activity") or [],
            "with_failure": sum(1 for r in rows if r["had_failure"])}


def _part(doc: dict[str, Any], key: str) -> dict[str, Any]:
    """One section of the hub's answer, or {} when it is missing or not an object."""
    got = doc.get(key)
    return got if isinstance(got, dict) else {}


def _rework(insight: dict[str, Any], how: str) -> dict[str, Any]:
    rw = _part(insight, "rework")
    if not rw.get("total_edits"):
        return nm("no edit by an IDE agent is recorded (reads are not rework)", how)
    keys = ("threshold", "total_files_edited", "total_edits", "files_above_threshold", "top_share")
    return {"measured": True, **{k: rw.get(k) for k in keys},
            "files": [f for f in rw.get("files") or [] if isinstance(f, dict)],
            "basis": "Writes only (Edit, Write, MultiEdit, patch...), counted by the hub; the ten most edited files"}


def _failures(intel: dict[str, Any], rows: list[dict[str, Any]], how: str) -> dict[str, Any]:
    q = _part(intel, "quality")
    if not q.get("tool_events"):
        return nm("no tool call by an IDE agent is recorded", how)
    stuck = [r for r in rows if r["failures"]["unrecovered"]]
    keys = ("tool_events", "tool_failures", "tool_failure_rate", "recovered_failures", "blocked_failures",
            "undetermined_failures", "recovery_rate")
    return {"measured": True, **{k: q.get(k) for k in keys}, "unrecovered_sessions": stuck[:MAX_ROWS],
            "basis": "A failure is recovered when the same tool later succeeds on the same file in that session; "
                     "one with no file (a shell command) cannot be told and is left out of the recovery rate"}


def _governance(gov: dict[str, Any], rows: list[dict[str, Any]], how: str) -> dict[str, Any]:
    told = [r["contract_first"] for r in rows if r["contract_first"] is not None]
    per = {"read_first": told.count(True), "edited_without": told.count(False),
           "not_measured": sum(1 for r in rows if r["contract_first"] is None)}
    if gov.get("contract_engagement_rate") is None:
        status = gov.get("contract_status") or "unknown"
        why = ("no session edited code yet" if status == "present" else
               f"the hub does not know of a contract file in this repository (contract status: {status})")
        return nm(why, "keep the project's contract or AGENTS.md in the repository; " + how) | {"per_session": per}
    keys = ("contract_status", "sessions_total", "sessions_touching_code", "sessions_reading_contract",
            "sessions_contract_first", "contract_engagement_rate", "doc_reads", "source_edits")
    return {"measured": True, **{k: gov.get(k) for k in keys}, "per_session": per,
            "docs": [d for d in gov.get("docs") or [] if isinstance(d, dict) and d.get("kind") == "contract"],
            "basis": "A session that touched code and read the contract before its first edit, of those that "
                     "touched code (the hub's governance coherence)"}


def _trajectory(intel: dict[str, Any], rows: list[dict[str, Any]], how: str) -> dict[str, Any]:
    t = _part(intel, "trajectory")
    if not t.get("steps_total"):
        return nm("no step of an IDE agent is recorded", how)
    keys = ("steps_total", "productive", "exploratory", "execution", "corrective", "other", "exploration_ratio",
            "corrective_share", "median_steps_to_first_edit", "sessions_measured")
    return {"measured": True, **{k: t.get(k) for k in keys},
            "loops": [x for x in t.get("loops") or [] if isinstance(x, dict)],
            "strips": [{"session_id": r["session_id"], "harness": r["harness"], "strip": r["strip"],
                        "step_count": r["step_count"]} for r in rows[:12]]}


def _chain(chain: dict[str, Any], attests: Any) -> dict[str, Any]:
    status, ver = chain.get("status"), chain.get("verification") or {}
    if status == 503:
        return nm(f"the hub's history ({chain.get('event_count')} events) is longer than it verifies in one pass",
                  "IT raises the hub's aggregate ceiling, or reads its integrity route directly")
    if status not in (200, 409):
        return nm("the hub gave no verdict for this project", "check the project id the project is mapped to")
    return {"measured": True, "valid": bool(ver.get("valid")), "checked": ver.get("checked"),
            "reachable": ver.get("reachable"), "breaks": len(ver.get("breaks") or []), "attests": attests,
            "meaning": "A stored chain the hub cannot rewrite: tamper evidence" if attests == "persisted" else
                       "The hub rebuilds this chain when it starts, so an intact verdict says only that the chain it "
                       "derived is self-consistent"}
