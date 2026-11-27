"""One next step on a project's first screen (FR-LND2).

Start here sits at the top of the Board. Under it, the developer briefing's "Next development step" used to say
"Every task is merged: release it or take the next change" on a project just adopted, while Start here asked to read
its repository and assess it: two answers to the same question on one screen. When the board itself has nothing to
build (``idle``: no task to start, follow, fix or decide), the briefing's step is Start here's first step, the same
place and control, and says so. A step the board has for a task stays the board's.
"""

from __future__ import annotations

from typing import Any


def lead(project: Any, step: dict[str, Any]) -> dict[str, Any]:
    """The briefing's next step: the board's own, or Start here's first when the board is idle."""
    if not step.get("idle"):
        return step
    from kernel import start_here

    if project.pid.startswith("_"):
        return step
    try:
        picked, _ = start_here.steps(project)
    except (OSError, ValueError, KeyError):
        return step
    if not picked:
        return step
    s = picked[0]
    return {"title": s["label"], "why": f"{s['why']} (the first step of Start here above)", "task": None,
            "action": {"label": "Do this now", "route": s["route"], "control": s.get("control")},
            "from": "start_here", "board": step["title"]}


__all__ = ["lead"]
