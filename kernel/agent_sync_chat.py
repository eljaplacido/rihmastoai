"""Ask Rihma, by rule: how to keep a coding agent in sync with a project, and what to monitor (FR-LND2).

The owner asked to "consult Claude Code on how to sync with Rihmasto and what to monitor"; the question went to a
guided journey about the AI tools a repository uses. In a project, a question that names a coding agent (Claude Code,
Codex, Cursor, OpenCode, Copilot, "my coding agent") and asks to sync it, keep it in step or know what to monitor
gets a sync plan from the project's records, each step its own button:

1. give the agent the project's brief and Rihma's tools (Connect your coding agent): what it does comes back here;
2. hand it the first task that is open and waits for nothing (the task's own hand-off), when there is one;
3. what to monitor: what runs on its own for the project (kernel/start_here.py ``meanwhile``), the agent channel
   and the agent's sessions, and the latest assessment's findings; or, when nothing runs on its own, the watch or
   automation that would.

Nothing is written: each step opens its place; the hand-offs are the person's own press there.
"""

from __future__ import annotations

import re
from typing import Any

AGENT = (("claude-code", re.compile(r"\bclaude(?: code)?\b", re.I)), ("codex", re.compile(r"\bcodex\b", re.I)),
         ("cursor", re.compile(r"\bcursor\b", re.I)), ("opencode", re.compile(r"\bopen ?code\b", re.I)),
         ("copilot", re.compile(r"\bcopilot\b", re.I)),
         ("generic", re.compile(r"\b(?:coding|code|ide) agents?\b|\bmy agent\b|\bthe ide\b", re.I)))
SYNC = re.compile(r"\b(?:sync\w*|synchron\w*|in step|up to date|monitor\w*|keep track|report(?:s|ing)? back|"
                  r"what to watch|stay aligned|align(?:ed)? with)\b", re.I)
NAMES = {"claude-code": "Claude Code", "codex": "Codex", "cursor": "Cursor", "opencode": "OpenCode",
         "copilot": "Copilot", "generic": "your coding agent"}


def asks(question: str) -> str | None:
    """The agent a question about syncing names, or None when it is not one."""
    q = question or ""
    if not SYNC.search(q):
        return None
    return next((key for key, rx in AGENT if rx.search(q)), None)


def _open_task(project: Any) -> dict[str, Any] | None:
    """The first task neither merged nor done that waits for nothing."""
    from kernel import task_detail, task_rules

    for row in task_detail.rows(project)["tasks"]:
        if row["status"] in ("merged", "done", "building", "stopped"):
            continue
        if task_rules.waits(project, row["id"]) is None:
            return row
    return None


def _step(sid: str, label: str, why: str, route: str, control: str | None) -> dict[str, Any]:
    return {"id": sid, "label": label, "why": why, "route": route, "control": control}


def plan(project: Any, agent: str) -> list[dict[str, Any]]:
    """The sync plan's steps for ``agent`` on ``project``, by rule."""
    from kernel import start_here

    pid, name = project.pid, NAMES.get(agent, NAMES["generic"])
    steps = [_step("hand_brief", f"Give {name} the project's brief and Rihma's tools",
                   "what it does then comes back here: its sessions through the hooks, its posts in the agent channel "
                   "and the tasks it names, so the board and the trace see who works on what",
                   f"#/p/{pid}/overview", "handoff")]
    task = _open_task(project)
    if task is not None:
        steps.append(_step("hand_task", f"Hand {task['id']} to {name}",
                           f"{task['title']}: the first open task that waits for nothing; its brief names its "
                           "criteria and tests, and how to report back", task["open"], "task_handoff"))
    mw = start_here.meanwhile(project)
    watch = "; ".join(r["what"] for r in mw["rows"][:3]) if mw["rows"] else None
    top = start_here.top_findings(project, 1)
    seen = [f"what runs on its own ({watch})" if watch else None, "the agent channel and the agent's sessions",
            f"the latest assessment's findings (the most severe: {top[0]['title']})" if top else None]
    steps.append(_step("monitor", "Monitor what it does", "watch " + ", ".join(s for s in seen if s)
                       + "; a failed check or a gate round that fails comes to the Inbox",
                       f"#/p/{pid}/agents", None))
    if mw["none"] is not None:
        steps.append(_step(mw["none"]["id"], mw["none"]["label"], mw["none"]["why"], mw["none"]["route"],
                           mw["none"]["control"]))
    return steps


def answer(factory: Any, project: Any, question: str, person: str | None = None) -> dict[str, Any] | None:
    """The sync plan, or None when the question is not about syncing a coding agent with a project."""
    agent = asks(question)
    if agent is None or project is None or project.pid.startswith("_"):
        return None
    steps = plan(project, agent)
    title = project.meta.get("title") or project.pid
    said = (f"To keep {NAMES.get(agent, NAMES['generic'])} in sync with {title}: "
            + " ".join(f"{i}. {s['label']}: {s['why']}." for i, s in enumerate(steps, 1))
            + " Each step is a button below; nothing is handed off until you press it there.")
    first = steps[0]
    return {"answer": said, "navigate": {"route": first["route"], "control": first["control"]}, "by": "rule",
            "propose": [], "dropped": [], "sources": [], "matches": ["agent_sync"], "topic": "agent_sync",
            "sync_plan": steps, "project": project.pid}


__all__ = ["answer", "asks", "plan"]
