"""Ask Rihma on a long job ("how is the assessment going?", "miten arviointi etenee?"), from its live progress.

Asked on a project's page, a question that names a long job and asks how far it is is answered from the job's
progress (kernel/progress.py), without a model: the steps done of all and the groups done, what runs now, the
findings so far by area, the time it has taken and the estimate, with Take me there to the job's own view. The
answer carries the progress itself, so the chat draws the same tiles, small (cockpit/static/progress.js). When
no such job runs, it says so, and when the last one ended, how.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.progress import key_for, live
from kernel.progress_estimate import human

# kind -> (words that name it, the view that shows it, its name in a sentence)
JOBS = {"assessment": (("assessment", "assessing", "assess", "arviointi", "arvioi", "arviointia", "arvio"),
                       "assessment", "assessment")}
HOW_FAR = {"going", "progress", "far", "left", "done", "finished", "finish", "status", "long", "running", "ready",
           "etenee", "valmis", "kauanko", "kestää", "missä", "vaiheessa", "tilanne"}
HOW_FAR_PHRASES = ("how is", "how's", "how far", "how long", "is it done", "still running", "miten menee")
ENDED = {"done": "finished", "cancelled": "was cancelled: nothing was recorded", "failed": "failed"}


def asks(question: str) -> str | None:
    """The kind of job the question asks about how far it is, or None."""
    low = question.lower()
    said = set(re.findall(r"[a-zåäö]+", low))
    if not (said & HOW_FAR or any(p in low for p in HOW_FAR_PHRASES)):
        return None
    return next((kind for kind, (words, _, _) in JOBS.items() if said & set(words)), None)


def _by_area(view: dict[str, Any]) -> str:
    """The findings so far, area by area, as far as they landed."""
    parts = []
    for sid, s in (view.get("steps") or {}).items():
        n = (s.get("counts") or {}).get("findings", (s.get("counts") or {}).get("proposed"))
        if s.get("state") == "done" and isinstance(n, int) and sid.split(".")[0] in ("rules", "panel"):
            parts.append(f"{s['label']} {n}")
    return ("Found so far: " + ", ".join(parts) + ". ") if parts else ""


def _groups(view: dict[str, Any]) -> tuple[int, int]:
    steps = view.get("steps") or {}
    plan = view.get("plan") or []
    done = sum(1 for g in plan if all((steps.get(sid) or {}).get("state") in ("done", "failed", "skipped")
                                      for sid in g["steps"]))
    return done, len(plan)


def said(view: dict[str, Any], name: str) -> str:
    """A job's progress in a few sentences."""
    gdone, groups = _groups(view)
    took = human(view.get("elapsed_s")).replace("about ", "")
    if view["state"] != "running":
        result = view.get("result") or {}
        what = f" {result['id']} has {result.get('findings', 0)} findings by rule." if result.get("id") else ""
        return f"The last {name} {ENDED.get(view['state'], view['state'])} after {took}.{what}" + \
               (f" {view['why']}." if view.get("why") and view["state"] == "failed" else "")
    head = (f"The {name} is {view['steps_done']} of {view['steps_total']} steps in ({gdone} of {groups} groups done), "
            f"running for {took}. Now: {view['now']}. ")
    est = (view.get("estimate") or {}).get("said") or ""
    return head + _by_area(view) + est


def answer(project: Any, question: str) -> dict[str, Any] | None:
    """The answer about a long job of ``project`` the question asks after, or None when it asks about none."""
    from kernel.assistant_rules import asks_for_action

    kind = asks(question) if project is not None and not asks_for_action(question) else None
    if kind is None:
        return None
    _, view_name, name = JOBS[kind]
    rep = live(key_for(project, kind))
    view = rep.since(0) if rep is not None else None
    text = said(view, name) if view else f"No {name} of {project.meta.get('title') or project.pid} has run since the " \
                                         f"cockpit started; the {name} view shows the versions recorded."
    return {"answer": text, "navigate": {"route": f"#/p/{project.pid}/{view_name}", "control": None},
            "progress": view, "propose": [], "dropped": [], "sources": [], "by": "map", "matches": [kind]}


__all__ = ["JOBS", "answer", "asks", "said"]
