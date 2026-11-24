"""Ask Rihma on "how is this project doing", without a model: the project's own status, not the map.

Asked on a project's page, or with a project's cockpit link pasted in the question, a question about the
project's state ("what's the status of this project", "missä mennään", "what is it waiting for") is answered
from its records: the now line, its health, what it waits for and who can act (kernel/next_step.py), with
Take me there to the first action. The map still answers questions about where things are in the cockpit.
"""

from __future__ import annotations

import re
from typing import Any

# Words that ask about a project's state, in English and Finnish, matched as whole words.
STATUS_WORDS = {"status", "state", "progress", "doing", "going", "stuck", "waiting", "blocked", "next", "health",
                "tilanne", "tila", "missä", "mennään", "etenee", "odottaa", "seuraavaksi", "jumissa"}
STATUS_PHRASES = ("how is", "how's", "where are we", "what's happening", "what is happening", "what's next",
                  "what is next", "what does it wait", "what is it waiting", "about this project", "miten menee",
                  "mitä seuraavaksi", "tästä projektista")
# A project's cockpit link: http://127.0.0.1:8802/#/p/<pid>/...
LINK = re.compile(r"#/p/([a-z0-9][a-z0-9-]{0,99})")


def asks_status(question: str) -> bool:
    """Whether the question asks how a project is doing rather than where something is."""
    low = question.lower()
    return bool(set(re.findall(r"[a-zåäö]+", low)) & STATUS_WORDS) or any(p in low for p in STATUS_PHRASES)


def project_in(question: str, factory: Any) -> str | None:
    """A project named by a cockpit link pasted in the question, when that project exists."""
    for pid in LINK.findall(question):
        try:
            factory.project(pid)
        except (KeyError, FileNotFoundError, ValueError):
            continue
        return pid
    return None


def status_answer(project: Any) -> dict[str, Any]:
    """The project's state from its records, with Take me there to the first thing that moves it forward."""
    from kernel.next_step import next_step
    from kernel.status import health, now

    line = now(project)["line"]
    nxt = next_step(project)
    state = health(project)["status"].replace("_", " ")
    parts = [f"{project.meta.get('title')}: {line}{'' if line.endswith(('.', '!', '?')) else '.'}",
             f"Health: {state}."]
    if nxt.get("waits_for"):
        parts.append(f"It waits for {nxt['waits_for']}.")
    actions = [a for a in nxt.get("actions") or [] if a.get("label")]
    if actions:
        parts.append("Next: " + "; ".join(a["label"] for a in actions[:3]) + ".")
    first = actions[0] if actions else {}
    view = first.get("view") or "overview"
    nav = {"route": f"#/p/{project.pid}/{view}", "control": first.get("control")}
    return {"answer": " ".join(parts), "navigate": nav, "propose": [], "dropped": [], "sources": [], "by": "map",
            "matches": [a.get("id") for a in actions[:3]]}


def resolve(factory: Any, question: str, project_id: str | None) -> tuple[Any, dict[str, Any] | None]:
    """The project a question is about (the open one, else one whose cockpit link is pasted in it), and,
    when the link alone names it and the question asks to do nothing, the answer about that project."""
    from kernel.assistant_rules import asks_for_action

    linked = None if project_id else project_in(question, factory)
    pid = project_id or linked
    project = factory.project(pid) if pid else None
    return project, (status_answer(project) if linked and not asks_for_action(question) else None)
