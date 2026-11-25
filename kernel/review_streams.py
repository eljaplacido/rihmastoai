"""What the other streams record, read for the Review (FR-REV1): the real record kinds, never a guess.

- **Went wrong**, in a project's ledger (read by kernel/review_ledger.py's pass through ``WRONG``): an automation run
  that failed or was refused (``automation_ran`` with that outcome), a check that failed (``check_ran`` with the
  verdict failed, kernel/checks), a console command that failed, ran out of time or did not start
  (``console_ran``, kernel/console.py), a task a cell runner would not run (``runner_refused``,
  kernel/runners/cell.py). A Cloud Run job's failed execution opens an incident (``probe_failed`` and
  ``incident_opened``, kernel/operate.py), which the pass already reads.
- **Went wrong**, in the factory's own ledger (``factory_wrong``): an automation paused, by a person or by its
  circuit breaker (``automation_paused``), and a factory-wide automation run that failed (one that names a
  project is read in that project's ledger, so it is never said twice).
- **From agents** (``from_agents``, the hook the agent channel fills, kernel/agent_channel.py): coding agents'
  progress posts, proposals that wait on a person, and the gate and check results agents asked for.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel.review_items import action, href, item

FAILED_OUTCOMES = ("failed", "refused")
CONSOLE_WRONG = ("failed", "timed_out", "not_started")
# kind -> (rank, title, when it is wrong): the same shape as kernel/review_ledger.py's WRONG, a predicate for "when".
WRONG_MORE: dict[str, tuple[int, str, Callable[[dict[str, Any]], bool] | bool]] = {
    "automation_ran": (1, "Automation {id} {outcome}: {detail}", lambda pl: pl.get("outcome") in FAILED_OUTCOMES),
    "check_ran": (2, "Check {check} failed: {summary}", lambda pl: pl.get("verdict") == "failed"),
    "console_ran": (3, "A console command {state}: {command}", lambda pl: pl.get("state") in CONSOLE_WRONG),
    "runner_refused": (2, "{task} did not run: {why}", False),
}
AGENT_KINDS = ("progress", "gate_result", "check_result")


def _in(at: str, start: str, end: str) -> bool:
    return start <= at <= end


def _factory_title(kind: str, pl: dict[str, Any]) -> str | None:
    """What one factory record says went wrong, or None when it is no such record."""
    if kind == "automation_paused":
        return f"Automation {pl.get('id')} was paused" + (" by its circuit breaker" if pl.get("by") else "") \
            + (f": {pl['why']}" if pl.get("why") else "")
    if kind == "automation_ran" and pl.get("outcome") in FAILED_OUTCOMES and not pl.get("project"):
        return f"Automation {pl.get('id')} {pl.get('outcome')}: {pl.get('detail') or ''}".rstrip(": ")
    return None


def factory_wrong(fp: Any, start: str, end: str, after: int = -1) -> list[dict[str, Any]]:
    """The factory's own records that went wrong in the period: automations paused, factory-wide runs failed."""
    out = []
    for rec in fp.ledger().records():
        ev = rec.get("event") if isinstance(rec, dict) else None
        if not isinstance(ev, dict) or not isinstance(ev.get("payload"), dict):
            continue
        kind, pl, at, seq = str(ev.get("kind") or ""), ev["payload"], str(ev.get("at") or ""), int(rec.get("seq", 0))
        title = _factory_title(kind, pl) if seq > after and _in(at, start, end) else None
        if title is None:
            continue
        iid = f"{fp.pid}/ledger/{seq}"
        by = {"type": "automation", "name": str(pl.get("id")), "persona": pl.get("persona")}
        out.append(item(iid, "wrong", kind, title[:300], None, at=at, by=by, rank=1 * 100_000 - seq,
                        record={"project": fp.pid, "seq": seq, "kind": kind},
                        links=[{"label": "Automations", "href": "#/automations"}],
                        detail=str(pl.get("why") or pl.get("detail") or ""),
                        actions=[action("reviewed", "Seen", key="r", path="/api/review/mark", body={"items": [iid]}),
                                 action("open", "Open Automations", key="o", link="#/automations")]))
    return out


def _agent_title(m: dict[str, Any], who: str) -> str:
    text = " ".join(str(m.get("text") or "").split())[:160]
    if m["kind"] == "proposal":
        return f"{who} proposes an answer, waiting on a person: {text}"
    if m["kind"] == "progress":
        return f"{who}: {text}"
    return f"{m['kind'].replace('_', ' ').capitalize()} for {who}: {text}"


def from_agents(project: Any, start: str, end: str) -> list[dict[str, Any]]:
    """The project's agent channel for the Review: agents' progress and the gate and check results they asked for
    in the period, and every proposal still waiting on a person (however old)."""
    try:
        from kernel import agent_channel as ch
    except ImportError:      # a build without the agent channel has nothing here
        return []
    out = []
    for m in ch.read(project)["messages"]:
        at, kind = str(m.get("at") or ""), m.get("kind")
        waiting = kind == "proposal" and m.get("state") == "open"
        by_agent = m["author"]["kind"] in ("agent", "rihma") or kind in ("gate_result", "check_result")
        if not (waiting or (kind in AGENT_KINDS and by_agent and _in(at, start, end))):
            continue
        who = ch.who(m)
        iid = f"{project.pid}/channel/{m['id']}"
        link = href(project.pid, "agents", m["id"])
        out.append(item(iid, "agents", f"channel_{kind}", _agent_title(m, who), project, at=at,
                        by={"type": "agent" if m["author"]["kind"] == "agent" else m["author"]["kind"], "name": who},
                        rank=(0 if waiting else 1) * 100_000 - int(str(m["id"])[2:] or 0),
                        record={"project": project.pid, "message": m["id"], "kind": kind},
                        links=[{"label": "Agent channel", "href": link}], new=_in(at, start, end),
                        actions=[action("open", "Open the channel", key="o", link=link)]))
    return out
