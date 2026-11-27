"""The next-step buttons on Rihma's answers in the agent channel (FR-CHN3; FR-CHN2 made them).

The check found the buttons repeated on every answer, two of them for one decision ("Review C-0001" and "Answer
Q-001" for the same question card), kept after the card was decided, landing at the top of a view without the
control or the record they name, and leading with another step than Ask Rihma's "what should I do next". Here:

- ``actions``: the project's next steps from its real state. The first is the step Ask Rihma's "what should I do
  next" gives (the project's journey, kernel/journey_chat.py), then the sync steps when asked about syncing, a card
  waiting on a decision (a question's card is answered through its question, so it is offered once, as the
  question), the assessment, and what the project waits for (kernel/next_step.py). Each keeps the control it names
  and the record it is about (``focus``: the question or the card), so its button lands on them;
- ``live``: how the channel view shows them. Only the latest of Rihma's answers in a thread shows its buttons, and
  a button whose card or question is no longer open is left out; the record keeps what was posted.
"""

from __future__ import annotations

import copy
import re
from typing import Any

MAX_ACTIONS = 4
_ROUTE = re.compile(r"^#/p/(?P<pid>[^/]+)/(?P<view>[a-z0-9_-]+)(?:/(?P<focus>[^/?#]+))?$")


def _journey(project: Any) -> list[dict[str, Any]]:
    """The step Ask Rihma's "what should I do next" gives for the project, as a button."""
    from kernel import journey_state as js
    from kernel.journey_chat import _hidden, _shown

    prog = _shown(js.progress(project.factory, js.journey_for(project), project=project),
                  _hidden(project.factory, project))
    step = next((s for s in prog["steps"] if s["id"] == prog["next"]), None)
    if step is None or not step["action"].get("route"):
        return []
    route = step["action"]["route"]
    out: dict[str, Any] = {"label": step["title"], "route": route, "control": step["action"].get("control"),
                           "command": (step.get("command") or "").split("   ")[0] or None}
    m = _ROUTE.match(route)
    if m:
        out.update(view=m["view"], focus=m["focus"])
    return [{k: v for k, v in out.items() if v}]


def _waiting_card(project: Any) -> list[dict[str, Any]]:
    """The first card waiting on a decision; a question's card is offered through its question instead."""
    from kernel.canon import Canon

    cards = [c for c in Canon(project).cards() if c["kind"] != "question"]
    if not cards:
        return []
    c = cards[0]
    return [{"label": f"Review {c['id']}: {c['title']}", "view": "inbox", "focus": c["id"], "control": "decide",
             "command": f"rihmasto decide {project.pid} {c['id']} <verdict>"}]


def _assessment(project: Any) -> list[dict[str, Any]]:
    if project.meta.get("source_kind") != "adopted":
        return []
    from kernel import assess

    if assess.history(project):
        return []
    return [{"label": "Run the assessment", "view": "assessment", "control": "run_assessment",
             "command": f"rihmasto assess {project.pid}"}]


def _next_actions(project: Any) -> list[dict[str, Any]]:
    """What the project waits for, each with the record it is about: an answer opens its question."""
    from kernel.next_step import next_step

    out = []
    for a in next_step(project).get("actions") or []:
        if not (a.get("label") and (a.get("view") or a.get("page"))):
            continue
        row = {k: a[k] for k in ("label", "view", "page", "control", "command") if a.get(k)}
        focus = a.get("question") or a.get("card")
        if focus:
            row["focus"] = focus
        if a.get("card") and a.get("question"):
            row["covers"] = [a["card"]]              # the question's card: one decision, one button
        out.append(row)
    return out


def _same(a: dict[str, Any], seen_labels: set[str], seen_records: set[str]) -> bool:
    records = {a.get("focus"), *(a.get("covers") or [])} - {None}
    if a["label"] in seen_labels or records & seen_records:
        return True
    seen_labels.add(a["label"])
    seen_records.update(records)
    return False


def actions(project: Any, first: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The next steps as buttons: ``first`` (the answer's own, such as connecting an agent or the sync steps), then
    the project's, Ask Rihma's next step leading; at most ``MAX_ACTIONS``, one per label and one per decision."""
    found: list[dict[str, Any]] = list(first or [])
    for part in (_journey, _next_actions, _waiting_card, _assessment):
        try:
            found += part(project)
        except (KeyError, ValueError, OSError, LookupError, TypeError):
            continue                       # a part that cannot be read offers no button, the others still do
    labels: set[str] = set()
    records: set[str] = set()
    out = [{k: v for k, v in a.items() if k != "covers"} for a in found if not _same(a, labels, records)]
    return out[:MAX_ACTIONS]


# -- the view -------------------------------------------------------------------------------------------

def _open_records(project: Any) -> set[str]:
    from kernel.canon import Canon

    canon = Canon(project)
    return {c["id"] for c in canon.cards()} | {q["id"] for q in canon.questions("open")}


def _stale(a: dict[str, Any], open_ids: set[str]) -> bool:
    focus = a.get("focus")
    return bool(focus) and bool(re.fullmatch(r"[CQ]-\d+", str(focus))) and focus not in open_ids


def live(project: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The messages as the channel view shows them: buttons only on the latest of Rihma's answers in each thread,
    without those whose card or question is no longer open. The records are not changed."""
    latest: dict[str, str] = {}
    for m in rows:
        if m["author"]["kind"] == "rihma" and m.get("actions"):
            latest[m["thread"]] = m["id"]
    if not latest:
        return rows
    try:
        open_ids = _open_records(project)
    except (KeyError, ValueError, OSError):
        open_ids = None
    out = []
    for m in rows:
        if m.get("actions"):
            m = copy.copy(m)
            keep = m["id"] == latest.get(m["thread"])
            m["actions"] = [a for a in m["actions"] if open_ids is None or not _stale(a, open_ids)] if keep else []
        out.append(m)
    return out
