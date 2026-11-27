"""Ask Rihma does what the agent channel does (FR-CHN2, UI and chat parity): put a question to a coding agent, and
say how to keep a project in step with Rihmasto and what to monitor, by rule.

- "ask Claude Code how we should sync" (or Cursor, Codex, the agent) in Ask Rihma: the answer says what will
  happen and offers the ``ask_agent`` operation (kernel/assistant_ops.py); Confirm posts the person's words in the
  project's agent channel, signed, where Rihma puts the question to that agent (kernel/channel_consult.py
  ``consult``), exactly as the channel's own "Ask a coding agent" does;
- "how do I keep this in sync with Rihmasto, what should I monitor": the same by-rule answer the channel gives
  (``sync_rule``), with Take me there on the first next step.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import channel_consult as cc

_ABOUT_RIHMASTO = re.compile(r"\b(?:rihmasto|rihma)\b", re.I)
_SYNC_CHAT = re.compile(r"\b(?:sync\w*|synchron\w*|in step|up to date|monitor\w*|synkr\w*|valvo\w*)\b", re.I)


def _out(answer: str, route: str, control: str | None, propose: list[Any], sources: list[str]) -> dict[str, Any]:
    return {"answer": answer, "navigate": {"route": route, "control": control}, "propose": propose, "dropped": [],
            "sources": sources, "by": "rule", "matches": ["agents"]}


def _consult(factory: Any, project: Any, question: str, persona: str, m: re.Match[str]) -> dict[str, Any]:
    from kernel import assistant_ops

    if project is None:
        return _out("Open the project first: a question for a coding agent goes into that project's agent channel, "
                    "where the agents working on it read it.", "#/projects", None, [], [])
    who = cc.target(project, m.group("agent"))
    if not cc.question_of(question, m):      # nothing to ask: ask the person what to ask, propose nothing (FR-CHN3)
        from kernel.channel_intent import what_to_ask

        return _out(what_to_ask(who["label"]), f"#/p/{project.pid}/agents", "channel_post", [], ["agent channel"])
    prop = assistant_ops.proposal(factory, "ask_agent", {"project": project.pid, "text": question.strip()},
                                  persona=persona, project=project,
                                  summary=f"Ask {who['label']} in the agent channel")
    how = (f"{who['label']} sees it over MCP in `rihma_channel_read` (asked_agents), and at its next session "
           f"start through the hook `rihmasto ide {project.pid} --section`; its answer comes back in the channel."
           if who["agent"] else
           "No coding agent is connected to this project yet, so it waits in the channel until one reads it. To "
           "connect one: " + " ".join(f"{i}. {s.format(pid=project.pid)}" for i, s in enumerate(cc.SETUP, 1)))
    now = cc.said_now(project, cc.question_of(question, m))
    said = (f"Confirm, and your question goes into this project's agent channel, signed by you, and Rihma puts it "
            f"to {who['label']} there. {how} Meanwhile, from the records: {now}")
    return _out(said, f"#/p/{project.pid}/agents", "channel_post", [prop] if prop else [],
                ["agent channel"])


def _sync(project: Any) -> dict[str, Any]:
    said, sources, _, acts = cc.sync_rule(project)
    first = acts[0] if acts else {"view": "agents", "control": None}
    route = f"#/p/{project.pid}/{first.get('view') or 'overview'}"
    steps = "; ".join(f"{a['label']}" + (f" (`{a['command']}`)" if a.get("command") else "") for a in acts)
    return _out(said + (f" Next steps: {steps}." if steps else ""), route, first.get("control"), [], sources)


def answer(factory: Any, project: Any, question: str, persona: str) -> dict[str, Any] | None:
    """Ask Rihma's answer by rule to a request to consult a coding agent, or to how to keep the project in step
    with Rihmasto and what to monitor; None for anything else."""
    m = cc.asks_an_agent(question)
    return _consult(factory, project, question, persona, m) if m else sync_answer(project, question)


def sync_answer(project: Any, question: str) -> dict[str, Any] | None:
    """Ask Rihma's answer by rule to how to keep a project in step with Rihmasto and what to monitor, or None."""
    if project is None or not _SYNC_CHAT.search(question) or not _ABOUT_RIHMASTO.search(question):
        return None
    return _sync(project)
