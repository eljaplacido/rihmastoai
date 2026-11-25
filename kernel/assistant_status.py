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
    said = set(re.findall(r"[a-zåäö0-9_.-]+", question.lower()))
    said |= {w.rstrip("s") for w in said}
    # an area by its name or its own folder's name: "assets" names a monorepo's apps/game/assets
    named = [a for a in got.get("areas") or [] if {a["area"].lower(), a["area"].lower().rsplit("/", 1)[-1],
                                                   a["area"].lower().rsplit("/", 1)[-1].rstrip("s")} & said]
    head = f"{project.meta.get('title')}, by area, from its repository's records: "
    focus = "".join(_focus(got, a) for a in named[:2])
    return {"answer": head + focus + summary(got), "navigate": {"route": f"#/p/{project.pid}/overview",
                                                               "control": "project_areas"},
            "propose": [], "dropped": [], "sources": [], "by": "map", "matches": [a["area"] for a in named[:2]]}


def with_pid(answer: str, project: Any, factory_pid: str) -> str:
    """A map answer's `<pid>` as the open project's own id: the command as it runs for that project."""
    return answer.replace("<pid>", project.pid) if project is not None and project.pid != factory_pid else answer


def project_in(question: str, factory: Any) -> str | None:
    """A project named by a cockpit link pasted in the question, when that project exists."""
    for pid in LINK.findall(question):
        try:
            factory.project(pid)
        except (KeyError, FileNotFoundError, ValueError):
            continue
        return pid
    return None


def project_answer(project: Any, question: str) -> dict[str, Any] | None:
    """How it (or a part of it) is doing; None for any other question."""
    return status_answer(project, question) if asks_status(question) or areas_answer(project, question) else None


def _health_said(h: dict[str, Any], failing: str = "") -> str:
    """Its health, with the first reasons when it is not on track (a failed baseline names its command), and the
    checks failing (", and 1 check failing: Secret scan (see Health)")."""
    why = "; ".join(str(r) for r in (h.get("reasons") or [])[:2])
    state = h["status"].replace("_", " ")
    return f"Health: {state} ({why}){failing}." if why and h["status"] != "on_track" else f"Health: {state}{failing}."


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
    parts = [f"{project.meta.get('title')}: {line}{'' if line.endswith(('.', '!', '?')) else '.'}",
             _health_said(health(project), _checks_failing(project))]
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


def _checks_failing(project: Any) -> str:
    """", and 1 check failing: Secret scan" when an enabled check failed its last run (the Health view,
    kernel/checks/health.py), as What's next says it; empty otherwise."""
    from kernel.checks.health import project_health

    try:
        h = project_health(project)
    except (OSError, ValueError, KeyError):
        return ""
    return f", and {h['line']} (see Health)" if h["failing"] else ""


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
    when the link alone names it and the question asks to do nothing, the answer about that project. How to
    work on it in a terminal or an IDE is kernel/assistant_work.py's, by rule, model or not."""
    from kernel import progress_chat
    from kernel.assistant_rules import asks_for_action

    linked = None if project_id else project_in(question, factory)
    pid = project_id or linked
    project = factory.project(pid) if pid else None
    acting = asks_for_action(question)
    ruled = None if acting else _by_rule(factory, project, question)
    if ruled is not None:
        return project, ruled
    running = progress_chat.answer(project, question)          # a long job: from its live progress (FR-PRG1)
    return project, running or (status_answer(project, question) if linked and not acting else None)


def _by_rule(factory: Any, project: Any, question: str) -> dict[str, Any] | None:
    """Answers that need no model: what to fix first (an assessment), what Rihmasto understood of the project, and
    why a job failed with what to do (from its own log)."""
    from kernel import assess_priority, job_words, understanding

    if project is not None and assess_priority.asks_priorities(question):
        return assess_priority.answer(project)
    if project is not None and understanding.asks(question):
        known = understanding.answer(project)
        if known is not None:
            return known
    return job_words.answer(factory) if job_words.asks_about_failure(question) else None
