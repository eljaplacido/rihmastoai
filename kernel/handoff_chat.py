"""Ask Rihma about handing work to a coding agent, by rule (FR-BRG1, UI and chat parity).

Two kinds of question, on a project's page:

- **a hand-off**: "hand off T-002 to Claude Code", "give C-0004 to Codex", "delegate this to Cursor": the answer
  opens the project's "Hand off to an agent" dialog with the task or change and the agent chosen (a plan step whose
  button opens it, and Take me there does the same). Nothing is handed off until the person copies, downloads or
  runs the brief there, signed;
- **where hand-offs are**: "where do I see hand-offs to agents?": the Agents view's channel (each hand-off and what
  the agent posted back) and the Trace; Take me there opens the Agents view.

Never about using Claude Code as Rihma's own model (that is Settings > Models). It writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

AGENT_NAMES = (("claude code", "claude-code"), ("claude-code", "claude-code"), ("claude", "claude-code"),
               ("codex", "codex"), ("opencode", "opencode"), ("open code", "opencode"), ("cursor", "cursor"),
               ("coding agent", "generic"), ("an agent", "generic"), ("agent", "generic"))
AGENT_WORDS = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "cursor": "Cursor",
               "generic": "any coding agent"}
HAND = re.compile(r"\b(hand(ed|ing)?[ -]?(it |this |that )?(off|over)|hand (?=[ct]-\d)|give (?=[ct]-\d)|delegate|"
                  r"pass (?=[ct]-\d)|send (?=[ct]-\d))")
WHERE = re.compile(r"^\W*(where|how) (do|can|will) (i|we) (see|find|look at|follow)\b.*\bhand[ -]?offs?\b"
                   r"|\bwhere (are|is) (the |my )?hand[ -]?offs?\b|\blist of hand[ -]?offs\b")
ITEM = re.compile(r"\b([ct]-\d{1,6})\b", re.I)


def _agent(low: str) -> str | None:
    tail = low.split(" to ", 1)[1] if " to " in low else low
    return next((key for word, key in AGENT_NAMES if re.search(r"\b" + re.escape(word) + r"\b", tail)), None)


def _out(text: str, nav: dict[str, Any] | None, match: str, **extra: Any) -> dict[str, Any]:
    return {"answer": text, "navigate": nav, "propose": [], "dropped": [], "sources": [], "by": "map",
            "matches": [match], **extra}


def _where(pid: str) -> dict[str, Any]:
    return _out("Hand-offs are listed in the project's Agents view: its channel shows each hand-off (who handed what "
                "to which agent, and how) and what the agent posted back; the Trace shows them in time with the "
                "builder cells and outside sessions. A hand-off still waiting for its change to be accepted is on "
                "the Board, in Planned. Take me there opens the Agents view.",
                {"route": f"#/p/{pid}/agents", "control": None}, "handoff_where")


def _handoff(project: Any, low: str) -> dict[str, Any] | None:
    item = ITEM.search(low)
    agent = _agent(low)
    if item is None and agent is None:
        return None
    what = item.group(1).upper() if item else None
    to = agent or "generic"
    pid = project.pid
    named = f"{what} to {AGENT_WORDS[to]}" if what else f"the project to {AGENT_WORDS[to]}"
    step = {"id": "S-1", "title": f"Hand {named}", "available": True,
            "detail": "Opens Hand off to an agent with these chosen: copy or download the brief for the agent, or "
                      "run it with the factory's builder cell after a person accepts it. The hand-off is recorded, "
                      "signed.",
            "action": {"kind": "handoff", "to": to, **({"change": what} if what else {})}}
    both = f"{what} and " if what else ""
    holds = "its criteria, " if what else "the goal, the criteria, "
    text = (f"Hand off to an agent opens with {both}{AGENT_WORDS[to]} chosen: the brief holds {holds}the open "
            "questions, the plan, the feedback still open, how to run the tests and how to report back. Copy it "
            "(or download it) and give it to the agent; what it does comes back in the Agents view's channel.")
    return _out(text, {"route": f"#/p/{pid}/board", "control": "handoff", "handoff": step["action"]}, "handoff",
                plan={"goal": f"hand off {named}", "steps": [step], "gaps": [], "dropped": []}, project=pid)


def answer(project: Any, question: str) -> dict[str, Any] | None:
    """The answer, or None when the question is not about hand-offs or no project is open."""
    if project is None or project.pid.startswith("_"):
        return None
    low = " ".join(question.lower().replace("’", "'").split())
    if WHERE.search(low):
        return _where(project.pid)
    hand = HAND.search(low)
    if hand is None or re.search(r"\b(model|models setup|as (the|my) model)\b", low):
        return None
    if hand.group(0) == "delegate" and not ITEM.search(low) and _agent(low) in (None, "generic"):
        return None          # "delegate operations to the ops agent" is a delegation to an agent (people), not this
    return _handoff(project, low)


__all__ = ["answer"]
