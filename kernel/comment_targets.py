"""Whether a comment's target is there: a requirement, criterion, task, release or card of the project (FR-V1).

The canon keeps a comment about any id (a requirement removed later keeps its comments, and the graph shows them
as about something gone). A new comment through a face (MCP's rihma_comment, the cockpit's comments route, Ask
Rihma's comment proposal) is refused when its target does not exist, as an unknown project or argument is, with
the ids there are: a comment on R-999 of a project with three requirements is never filed.
"""

from __future__ import annotations

from typing import Any

from kernel.store import read_json

SHOWN = 8


def _spec(project: Any) -> list[dict[str, Any]]:
    spec = project.read("spec.json", {}) or {}
    return [r for r in spec.get("requirements") or [] if isinstance(r, dict)]


def _requirements(project: Any) -> list[str]:
    return [str(r.get("id")) for r in _spec(project)]


def _criteria(project: Any) -> list[str]:
    return [str(c.get("id")) for r in _spec(project) for c in r.get("acceptance") or [] if isinstance(c, dict)]


def _tasks(project: Any) -> list[str]:
    tasks = project.read("tasks.json", {}) or {}
    contract = project.read("contract.json", {}) or {}
    named = [str(t.get("id")) for t in contract.get("tasks") or [] if isinstance(t, dict)]
    return sorted(set(tasks) | set(named)) if isinstance(tasks, dict) else named


def _releases(project: Any) -> list[str]:
    folder = project.path("releases")
    found = [read_json(p) for p in folder.glob("*.json") if p.stem.isdigit()] if folder.exists() else []
    return [str(r.get("release")) for r in sorted((r for r in found if r), key=lambda r: r.get("release") or 0)]


def _cards(project: Any) -> list[str]:
    inbox = project.path("canon", "inbox")
    return sorted(p.stem for p in inbox.glob("C-*.json")) if inbox.exists() else []


BY_KIND = {"requirement": _requirements, "criterion": _criteria, "task": _tasks, "release": _releases, "card": _cards}


def ids(project: Any, kind: str) -> list[str] | None:
    """The ids a target of this kind may name in the project; None for a kind any id names (the project itself)."""
    found = BY_KIND.get(kind)
    return found(project) if found else None


def unknown(project: Any, kind: str, target_id: str) -> str | None:
    """Why a comment on this target is refused, with the ids there are; None when the target exists."""
    there = ids(project, str(kind))
    if there is None or str(target_id) in there:
        return None
    word = "criteria" if kind == "criterion" else f"{kind}s"
    listed = ", ".join(there[:SHOWN]) + (f" and {len(there) - SHOWN} more" if len(there) > SHOWN else "")
    return f"no {kind} {target_id} in {project.pid}: " + (f"its {word} are {listed}" if there
                                                          else f"it has no {word} yet")


def require(project: Any, kind: str, target_id: str) -> None:
    """A ValueError with the ids there are when the target does not exist."""
    why = unknown(project, kind, target_id)
    if why:
        raise ValueError(why)
