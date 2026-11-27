"""A project's trace (FR-DEV1): every interaction of people and agents with its development, as one timeline.

The owner (2026-11-25): "how to figure out tracing". Read from two records, never kept:

- the **ledger**: people's decisions and answers, Rihma's roles asking a model (analyst, verifier, assistant), the
  builder cell's rounds (Gnomon or another runner, with its model), gate rounds and merges, workspaces, MCP writes
  from an agent in a terminal or an IDE, sessions in outside tools captured by hooks (kernel/devsessions.py), what
  the agent observability hub showed when recorded, automations;
- the **agent channel**: people, Rihma's agents and external agents (Claude Code, Codex, Cursor) talking, hand-offs,
  gate and check results posted there. Its ledger lines (``channel_posted``) are left out so a post shows once.

Each item says when, who (a person with their persona, Rihma in a role, an agent with its harness and operator, an
automation or the system), what in a short line, the task it belongs to, and its record (a ledger record as served
to people, without holdout details: kernel/custody.py), so the timeline can be expanded to the record.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from kernel import devhandoffs
from kernel.custody import ledger_record
from kernel.devboard import _d
from kernel.people import is_person

WHO = ("person", "rihma", "agent", "automation", "system")
SKIP = {"channel_posted"}
LIMIT = 300
WINDOWS = {"24h": 1, "7d": 7, "30d": 30}
SCRIPTED_MODELS = ("demo-builder",)     # kernel/demo.py BUILDER_NAME: a script stood in for the builder cell


def _person(pl: dict[str, Any]) -> str | None:
    for key in ("person", "by", "decided_by"):
        value = pl.get(key)
        if isinstance(value, str) and is_person(value):
            return value
    return None


def scripted_cell(pl: dict[str, Any]) -> bool:
    """A builder round a scripted stand-in made (kernel/demo.py's demo-builder), not a real runner."""
    return str(pl.get("final_model") or pl.get("model") or "") in SCRIPTED_MODELS


def _cell_actor(pl: dict[str, Any]) -> dict[str, Any]:
    runner = _d(pl.get("runner"))
    if scripted_cell(pl):                  # never "Gnomon" for what a script stood in for
        return {"kind": "agent", "name": "demo-builder (scripted)", "harness": "scripted", "role": "builder",
                "model": pl.get("final_model") or pl.get("model")}
    return {"kind": "agent", "name": runner.get("label") or "Builder cell", "harness": runner.get("name") or "gnomon",
            "role": "builder", "model": pl.get("final_model") or pl.get("model")}


def _outcome(pl: dict[str, Any]) -> str:
    """How a builder round ended, in words (never Gnomon's bare bucket name, "result")."""
    if pl.get("escalated"):
        return "escalated"
    if pl.get("bucket") == "apparatus_failure":
        return "the runner failed" + (f" ({str(pl.get('stop_reason'))[:80]})" if pl.get("stop_reason") else "")
    said = "finished" if pl.get("code") in (0, None) else f"ended with code {pl.get('code')}"
    return said + (f" after {pl['tool_steps']} tool steps" if pl.get("tool_steps") else "")


def _cell_line(pl: dict[str, Any]) -> str:
    who = "The scripted builder (demo-builder)" if scripted_cell(pl) else "Builder cell"
    return f"{who} worked on {pl.get('task')} (round {pl.get('round')}): {_outcome(pl)}"


def _model_line(pl: dict[str, Any]) -> str:
    asked = "answered from a script (demo)" if pl.get("runner") == "scripted" else f"asked {pl.get('model')}"
    return f"Rihma's {pl.get('role')} {asked}" + (f" on {pl['task']}" if pl.get("task") else "")


def actor(kind: str, pl: dict[str, Any]) -> dict[str, Any]:
    """Who acted in a ledger record: a person, Rihma in a role, an agent with its harness, an automation, the system."""
    if kind == "cell_ran":
        return _cell_actor(pl)
    if kind == "model_run":
        return {"kind": "rihma", "name": "Rihma", "role": pl.get("role"),
                "model": "scripted" if pl.get("runner") == "scripted" else pl.get("model")}
    person = _person(pl)
    if kind == "dev_session_recorded":
        return {"kind": "agent", "name": pl.get("harness"), "harness": pl.get("harness"), "operator": person}
    if kind == "mcp_write":
        return {"kind": "agent", "name": "an agent over MCP", "harness": "mcp", "operator": person}
    if pl.get("automation") and not person:
        return {"kind": "automation", "name": str(pl.get("automation"))}
    if person:
        return {"kind": "person", "name": person, "persona": pl.get("persona")}
    return {"kind": "system", "name": "Rihmasto"}


def _gate(pl: dict[str, Any]) -> str:
    return f"Gate round {pl.get('round')} on {pl.get('task')}: {pl.get('verdict')}"


def _session(pl: dict[str, Any]) -> str:
    said = f"{pl.get('harness')} session {'started' if pl.get('event') == 'start' else 'ended'}"
    if pl.get("event") == "end" and pl.get("commits") is not None:
        said += f": {pl.get('commits')} commits, {pl.get('files_changed', 0)} files changed"
    return said + (f" on {pl['branch']}" if pl.get("branch") else "")


def _decided(pl: dict[str, Any]) -> str:
    """A decision's line, naming its card, or what it answered (a question, a task) when it has no card (FR-DEV2)."""
    refs = _d(pl.get("refs"))
    named = pl.get("card") or next((str(v) for v in refs.values() if isinstance(v, (str, int)) and v != ""), None)
    return f"Decided {named or pl.get('id') or 'a decision'} ({pl.get('kind')}): {pl.get('verdict')}"


LINES = {
    "cell_ran": _cell_line,
    "gate": _gate,
    "merged": lambda pl: f"{pl.get('task')} merged into main",
    "escalated": lambda pl: f"{pl.get('task')} escalated to a person as {pl.get('card')}",
    "decision": _decided,
    "model_run": _model_line,
    "agent_handoff": lambda pl: "Handed off to " + (
        "Gnomon's builder cell through " + str(pl.get("filed")) if pl.get("via") == "run"
        else devhandoffs.AGENT_WORDS.get(str(pl.get("to")), str(pl.get("to")))) + (
        f" for {pl['change']}" if pl.get("change") else ""),
    "dev_session_recorded": _session,
    "dev_looked": lambda pl: "Read the development briefing (Got it)",
    "mcp_write": lambda pl: f"Proposed over MCP: {pl.get('action')}",
    "workspace_opened": lambda pl: f"Opened a workspace with {pl.get('agent')} on {pl.get('branch')}",
    "agent_sessions_observed": lambda pl: "Recorded what the agent observability hub shows",
    "card_opened": lambda pl: f"{pl.get('id')} opened for a person to decide ({str(pl.get('kind')).replace('_', ' ')})",
    "escalation_resolved":lambda pl: f"Escalation on {pl.get('task')} resolved: {pl.get('verdict')}",
    "build_round": lambda pl: "A build round ended: " + ", ".join(f"{k} {v}" for k, v in (pl.get("results") or {})
                                                                  .items()),
}


def _line(kind: str, pl: dict[str, Any]) -> str:
    fn = LINES.get(kind)
    try:
        return fn(pl) if fn else kind.replace("_", " ").capitalize()
    except (TypeError, ValueError, AttributeError):
        return kind.replace("_", " ").capitalize()


def _ends(project: Any) -> dict[str, dict[str, Any]]:
    """Each session's end as it stands now: a later end updates it with the whole session (FR-DEV2)."""
    from kernel.devsessions import sessions

    keep = ("commits", "files_changed", "branch")
    return {str(s["id"]): {k: s[k] for k in keep if k in s} for s in sessions(project)
            if s.get("event") == "end" and s.get("id")}


def _from_ledger(project: Any) -> list[dict[str, Any]]:
    out = []
    ends = _ends(project)
    for rec in project.ledger().records():
        event = _d(_d(rec).get("event"))
        kind = str(event.get("kind") or "")
        if not kind or kind in SKIP:
            continue
        pl = _d(event.get("payload"))
        said = {**pl, **ends.get(str(pl.get("id")), {})} if kind == "dev_session_recorded" else pl
        out.append({"id": f"L-{rec.get('seq')}", "source": "ledger", "at": event.get("at"), "kind": kind,
                    "who": actor(kind, pl), "what": _line(kind, said), "task": pl.get("task"),
                    "record": ledger_record(rec)})
    return out


def _channel_who(author: dict[str, Any]) -> dict[str, Any]:
    keep = ("kind", "name", "harness", "role", "persona", "operator")
    return {k: author.get(k) for k in keep if author.get(k)}


def _from_channel(project: Any) -> list[dict[str, Any]]:
    from kernel import agent_channel as ch

    out = []
    for m in ch.read(project)["messages"]:
        refs = _d(m.get("refs"))
        said = " ".join(str(m.get("text") or "").split())[:240]
        out.append({"id": m["id"], "source": "channel", "at": m.get("at"), "kind": m.get("kind"),
                    "who": _channel_who(_d(m.get("author"))), "what": said,
                    "task": (refs.get("tasks") or [None])[0], "record": {k: v for k, v in m.items() if k != "text"}})
    return out


class WindowRefused(ValueError):
    """A window the trace does not take, saying which it does."""


def since_of(window: str | None, now: dt.datetime) -> str | None:
    """The time a window ("24h", "7d", "30d", or an ISO time) starts at; None for all. Anything else is refused
    with what to give instead (FR-DEV2), never compared as text."""
    if not window or window == "all":
        return None
    if window in WINDOWS:
        return (now - dt.timedelta(days=WINDOWS[window])).isoformat().replace("+00:00", "Z")
    try:
        at = dt.datetime.fromisoformat(window.strip().replace("Z", "+00:00"))
    except ValueError:
        at = None
    if at is None or not window.strip()[:4].isdigit():
        raise WindowRefused(f"the window {window[:40]!r} is not one the trace takes: give 24h, 7d, 30d, all, or a "
                            "time such as 2026-11-25T09:00:00Z")
    at = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    return at.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _harness(item: dict[str, Any]) -> str | None:
    return item["who"].get("harness") or (item["who"].get("role") if item["who"].get("kind") == "rihma" else None)


def _keep(item: dict[str, Any], since: str | None, who: str | None, harness: str | None, task: str | None) -> bool:
    return ((not since or str(item.get("at") or "") > since) and (not who or item["who"].get("kind") == who)
            and (not harness or _harness(item) == harness) and (not task or item.get("task") == task))


def trace(project: Any, *, window: str | None = None, who: str | None = None, harness: str | None = None,
          task: str | None = None, limit: int = LIMIT) -> dict[str, Any]:
    """The project's timeline, newest first, with what it can be filtered by."""
    every = _from_ledger(project) + _from_channel(project)
    every.sort(key=lambda i: str(i.get("at") or ""), reverse=True)
    since = since_of(window, project.factory.clock.now())
    kept = [i for i in every if _keep(i, since, who, harness, task)]
    return {"project": project.pid, "since": since, "window": window or "all", "total": len(kept),
            "items": kept[:limit], "shown": min(limit, len(kept)),
            "counts": {k: sum(1 for i in kept if i["who"].get("kind") == k) for k in WHO},
            "filters": {"who": list(WHO), "harnesses": sorted({h for i in every if (h := _harness(i))}),
                        "tasks": sorted({str(i["task"]) for i in every if i.get("task")}),
                        "windows": ["24h", "7d", "30d", "all"]}}


__all__ = ["WHO", "WindowRefused", "actor", "since_of", "trace"]
