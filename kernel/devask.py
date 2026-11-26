"""Ask Rihma about development, by rule and without a model (FR-DEV1).

Two questions, asked on a project's page (or with its link pasted):

- "what's next in development?" ("what should I build next?", "seuraava kehitysaskel?"): the developer briefing
  (kernel/devbrief.py) in a few sentences: the next step and why, only the decisions that block it, and the latest
  sessions since the person's last look; Take me there opens the project's development board;
- "what did the agents do since yesterday?" ("mitä agentit tekivät eilen?"): the trace (kernel/devtrace.py) of the
  window it names (since yesterday or today: 24 hours; this week: 7 days; since my last look), counted by harness,
  with the newest few; Take me there opens the trace.

These rules run before Ask Rihma's others, so they answer only inside a project and only what names development or
agents outright (FR-DEV2): outside a project, and for broad questions such as "brief me", "what happened since
yesterday?" or "who worked on this?", the other rules answer as they did before (Review, Shape it, the Ledger).
It writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.devbrief import briefing
from kernel.devsessions import last_look
from kernel.devtrace import trace

NEXT = ("next in development", "next development step", "next step in development", "next dev step",
        "build next", "develop next", "code next", "developer briefing", "development briefing",
        "brief me on development", "seuraava kehitys", "kehityksen seuraava", "mitä kehitän seuraavaksi",
        "mitä rakennan seuraavaksi")
AGENTS = ("agents do", "agents did", "agents done", "agent did", "agents been doing", "agents worked",
          "agent activity since", "mitä agentit", "agenttien työ")
WINDOW_WORDS = (("since my last look", "look"), ("since i last looked", "look"), ("yesterday", "24h"),
                ("today", "24h"), ("eilen", "24h"), ("tänään", "24h"), ("this week", "7d"), ("last week", "7d"),
                ("tällä viikolla", "7d"), ("this month", "30d"))
SHOWN = 5


def asks(question: str) -> str | None:
    """``"next"``, ``"agents"`` or None."""
    low = re.sub(r"\s+", " ", question.lower().replace("’", "'"))
    if any(p in low for p in NEXT) or ("next" in low and re.search(r"\bdevelop|\bdev\b|\bcoding\b", low)):
        return "next"
    if any(re.search(re.escape(p) + r"\b", low) for p in AGENTS):     # "agents do", never "agents doing"
        return "agents"
    return None


def _out(text: str, route: str | None, control: str | None, match: str) -> dict[str, Any]:
    return {"answer": text, "navigate": {"route": route, "control": control} if route else None, "propose": [],
            "dropped": [], "sources": [], "by": "map", "matches": [match]}


def _next_text(b: dict[str, Any]) -> str:
    step = b["next"]
    text = f"Next in development: {step['title']}. Why: {step['why']}."
    if b["blocking"]:
        text += " It waits on " + "; ".join(f"{x['card']} ({x['what']})" for x in b["blocking"][:3]) + "."
    else:
        text += " Nothing waits on a decision for it."
    if b["sessions"]:
        latest = b["sessions"][0]
        text += (f" Since {b['since_basis']}: {len(b['sessions'])} agent sessions and runs, the newest "
                 f"{latest['what']}.")
    else:
        text += f" No agent session since {b['since_basis']}."
    return text


def _window(project: Any, question: str, person: str | None) -> tuple[str, str]:
    low = question.lower()
    for words, window in WINDOW_WORDS:
        if words in low:
            if window == "look":
                looked = last_look(project, person)
                return (looked, "your last look") if looked else ("7d", "the last 7 days")
            return window, {"24h": "the last 24 hours", "7d": "the last 7 days", "30d": "the last 30 days"}[window]
    looked = last_look(project, person)
    return (looked, "your last look") if looked else ("7d", "the last 7 days")


def _agents_text(t: dict[str, Any], said: str) -> str:
    rows = [i for i in t["items"] if i["who"].get("kind") in ("agent", "rihma")]
    if not rows:
        return (f"No agent worked on this project in {said}. Sessions in Claude Code or Cursor appear here once the "
                "project's session hooks are installed (the Trace view shows them to copy).")
    by: dict[str, int] = {}
    for i in rows:
        key = str(i["who"].get("harness") or ("Rihma's " + str(i["who"].get("role"))))
        by[key] = by.get(key, 0) + 1
    text = f"In {said}, agents did {len(rows)} things: " + ", ".join(f"{k} {n}" for k, n in by.items()) + ". Newest: "
    return text + "; ".join(f"{i['what']}" for i in rows[:SHOWN]) + "."


def answer(factory: Any, project: Any, question: str, *, person: str | None = None) -> dict[str, Any] | None:
    """The answer, or None when the question is neither or no project is open (the other rules answer then)."""
    if project is None or project.pid.startswith("_"):
        return None
    kind = asks(question)
    if kind is None:
        return None
    pid = project.pid
    if kind == "next":
        return _out(_next_text(briefing(project, person=person)), f"#/p/{pid}/board", "dev_briefing", "dev_next")
    window, said = _window(project, question, person)
    return _out(_agents_text(trace(project, window=window), said), f"#/p/{pid}/trace", "dev_filters",
                "dev_agents")


__all__ = ["answer", "asks"]
