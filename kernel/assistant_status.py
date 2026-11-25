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
# Words that ask how a part of the work is coming along (an adopted project's areas, kernel/areas.py).
AREA_WORDS = {"assets", "asset", "levels", "level", "lore", "world", "textures", "models", "audio", "scenes",
              "areas", "area", "activity", "folders", "content", "maps", "characters", "datasets", "runs",
              "assetit", "tasot", "maailma", "alueet"}


def asks_areas(question: str) -> bool:
    """Whether the question asks how a part of the work (its assets, levels, lore, areas) is coming along."""
    return bool(set(re.findall(r"[a-zåäö]+", question.lower())) & AREA_WORDS)


def asks_status(question: str) -> bool:
    """Whether the question asks how a project is doing rather than where something is."""
    low = question.lower()
    return bool(set(re.findall(r"[a-zåäö]+", low)) & STATUS_WORDS) or any(p in low for p in STATUS_PHRASES)


def _focus(got: dict[str, Any], area: dict[str, Any]) -> str:
    """One area the question names: what it holds and what moved there in 30 days."""
    from kernel.areas import held

    month = ((got.get("activity") or {}).get("windows") or {}).get("30") or []
    moved = next((m for m in month if m["area"] == area["area"]), None)
    return (f"{area['area']} holds {area['files']} files" + (f" ({held(area)})" if area["assets"] else "")
            + (f"; in 30 days {moved['commits']} commit(s), {moved['files']} file change(s)" if moved
               else "; nothing changed there in 30 days") + ". ")


def areas_answer(project: Any, question: str) -> dict[str, Any] | None:
    """How the project's areas are coming along, from its records (FR-RPJ1), or None when it has none."""
    from kernel.areas import summary

    got = project.read("areas.json", None)
    if not got or not asks_areas(question):
        return None
    low = question.lower()
    named = [a for a in got.get("areas") or [] if a["area"].lower() in low or a["area"].lower().rstrip("s") in low]
    head = f"{project.meta.get('title')}, by area, from its repository's records: "
    focus = "".join(_focus(got, a) for a in named[:2])
    return {"answer": head + focus + summary(got), "navigate": {"route": f"#/p/{project.pid}/overview",
                                                               "control": "project_areas"},
            "propose": [], "dropped": [], "sources": [], "by": "map", "matches": [a["area"] for a in named[:2]]}


def project_in(question: str, factory: Any) -> str | None:
    """A project named by a cockpit link pasted in the question, when that project exists."""
    for pid in LINK.findall(question):
        try:
            factory.project(pid)
        except (KeyError, FileNotFoundError, ValueError):
            continue
        return pid
    return None


def status_answer(project: Any, question: str = "") -> dict[str, Any]:
    """The project's state from its records, with Take me there to the first thing that moves it forward; a
    question about its assets, levels, lore or areas is answered from its areas (kernel/areas.py)."""
    from kernel.next_step import next_step
    from kernel.status import health, now

    by_area = areas_answer(project, question) if question else None
    if by_area is not None:
        return by_area
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
    parts += _agents_line(project)
    first = actions[0] if actions else {}
    view = first.get("view") or "overview"
    nav = {"route": f"#/p/{project.pid}/{view}", "control": first.get("control")}
    return {"answer": " ".join(parts), "navigate": nav, "propose": [], "dropped": [], "sources": [], "by": "map",
            "matches": [a.get("id") for a in actions[:3]]}


def _agents_line(project: Any) -> list[str]:
    """The agents working on it (the overview's Agents strip, kernel/agent_writes.py), when any posted."""
    from kernel.agent_writes import activity

    a = activity(project, limit=3)
    if not a["agents"] and not a["handoffs"]:
        return []
    said = f"Agents working on it: {', '.join(a['agents']) or 'none yet'}; {a['handoffs']} hand-off(s) given"
    waiting = len(a["proposals_waiting"])
    return [said + (f"; {waiting} agent proposal(s) wait on a person in the Agent channel." if waiting else ".")]


def resolve(factory: Any, question: str, project_id: str | None) -> tuple[Any, dict[str, Any] | None]:
    """The project a question is about (the open one, else one whose cockpit link is pasted in it), and,
    when the link alone names it and the question asks to do nothing, the answer about that project."""
    from kernel.assistant_rules import asks_for_action

    linked = None if project_id else project_in(question, factory)
    pid = project_id or linked
    project = factory.project(pid) if pid else None
    if project is not None and not asks_for_action(question):
        from kernel.assess_priority import answer as priorities
        from kernel.assess_priority import asks_priorities

        if asks_priorities(question):
            return project, priorities(project)      # which assessment findings to fix first, and why, by rule
    return project, (status_answer(project, question) if linked and not asks_for_action(question) else None)
