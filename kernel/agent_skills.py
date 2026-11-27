"""Agent skills, platform-wide and per project: what applies to every project and what to one (FR-AOP1, FR-AGC1).

A skill (`.claude/skills/<name>/SKILL.md`) is found by rule in an adopted or attached project's repository
(kernel/agent_context.py) and applies to that project only: the team's coding agents load it there. Rihmasto has no
platform-wide skills yet: none is offered to every project, and a skill found in a repository is only a candidate for
Rihmasto's own catalogue, after a person approves (kernel/agent_context.py). This module says so plainly, lists each
project's skills, and names a skill found in more than one project (a candidate to share), for the AI architect's
Agent operations page (Agent skills) and Ask Rihma ("which agent skills can I use across all projects?"). It reads
each project's agent_context.json and writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

PLATFORM_NOTE = ("No agent skill applies to every project yet: Rihmasto has no platform-wide skills. Each skill "
                 "Rihmasto lists was found in one project's repository and applies to that project only; one found in "
                 "more than one project is a candidate to share, after a person approves it for Rihmasto's own "
                 "catalogue.")
HOW = "adopt or attach a repository whose team keeps skills in .claude/skills/<name>/SKILL.md"
ASKS = re.compile(r"\bskills?\b")
SCOPE = re.compile(r"\b(platform|all projects|every project|each project|across|per project|whole|everywhere|"
                   r"which|what|available|have|list|show|shared?|common|global)\b")


def _skills(project: Any) -> list[dict[str, Any]]:
    ctx = project.read("agent_context.json", None) or {}
    rows = ctx.get("skills") if isinstance(ctx, dict) else None
    return [{"name": str(s.get("name") or s.get("path") or "skill"),
             "description": str(s.get("description") or "")[:200], "path": str(s.get("path") or ""),
             "files": len(s.get("files") or [])}
            for s in rows or [] if isinstance(s, dict)]


def overview(factory: Any, pid: str | None = None) -> dict[str, Any]:
    """The platform's skills (none yet, said plainly), each project's, and the ones more than one project has."""
    projects = [factory.project(pid)] if pid else [p for p in factory.projects() if not p.pid.startswith("_")]
    rows = [{"project": p.pid, "title": p.meta.get("title") or p.pid, "source_kind": p.meta.get("source_kind"),
             "skills": _skills(p)} for p in projects]
    by_name: dict[str, list[str]] = {}
    for r in rows:
        for s in r["skills"]:
            by_name.setdefault(s["name"], []).append(r["project"])
    return {"platform": [], "platform_note": PLATFORM_NOTE, "projects": [r for r in rows if r["skills"]],
            "without": [r["project"] for r in rows if not r["skills"]], "how": HOW,
            "shared": [{"name": n, "projects": ps} for n, ps in sorted(by_name.items()) if len(ps) > 1],
            "count": sum(len(r["skills"]) for r in rows)}


def _own_line(project: Any) -> str:
    """What the open project has of its own, in one sentence."""
    own, title = _skills(project), project.meta.get("title") or project.pid
    if own:
        return (f"{title} has {len(own)} skill{'' if len(own) == 1 else 's'} of its own "
                f"({', '.join(s['name'] for s in own[:6])}): its AI tools tab lists them. ")
    why = ("it was built by Rihmasto, not adopted from a repository" if project.meta.get("source_kind") not in
           ("adopted", "attached") else "none was found in its repository")
    return f"{title} has no skills of its own: {why}; its AI tools tab says so. "


# A repository's own AI-tool setup is on an adopted or attached project's Overview; a project Rihmasto built has none,
# and its AI tools tab says so (Ask Rihma's Take me there opens that tab, kernel/assistant.py ``_target``).
REPO_ONLY = ("ai_tools", "ide_section")
BUILT_NOTE = (" {title} was built by Rihmasto, not adopted, so it has no repository AI-tool setup of its own (no "
              "CLAUDE.md, AGENTS.md, skills or MCP servers to read): its AI tools tab says so, and adopting or "
              "attaching a repository shows that team's.")


def built_target(item: dict[str, Any], project: Any, views: dict[str, Any]) -> tuple[str, str] | None:
    """For a repository-only control asked about in a project Rihmasto built: its AI tools tab and why; else None."""
    if item.get("id") not in REPO_ONLY or project is None or project.pid.startswith("_"):
        return None
    if project.meta.get("source_kind") in ("adopted", "attached"):
        return None
    return views["aitools"]["route"].replace("{pid}", project.pid), BUILT_NOTE.format(title=project.meta["title"])


def asks(question: str) -> bool:
    said = " ".join(question.rsplit("\n\nNow: ", 1)[-1].lower().split())
    return bool(ASKS.search(said) and SCOPE.search(said))


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """Ask Rihma's answer about agent skills, platform-wide and per project; None for another question."""
    if not asks(question):
        return None
    view = overview(factory)
    found = "; ".join(f"{r['title']}: {', '.join(s['name'] for s in r['skills'][:6])}" for r in view["projects"][:6])
    text = PLATFORM_NOTE + (f" Per project: {found}." if found else f" No project has skills of its own yet: {HOW}.")
    if view["shared"]:
        text += " In more than one project: " + ", ".join(s["name"] for s in view["shared"][:6]) + "."
    here = project is not None and not project.pid.startswith("_")
    if here:      # the open project first, then the platform
        text = _own_line(project) + text
    route = f"#/p/{project.pid}/aitools" if here else "#/agentops"
    return {"answer": text, "navigate": {"route": route, "control": None if here else "agent_skills"},
            "propose": [], "dropped": [], "sources": [r["project"] for r in view["projects"]], "by": "rule",
            "matches": ["agent_skills", "ai_tools"], "persona": persona}
