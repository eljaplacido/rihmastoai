"""A typed "why ...?" for never lost (FR-NVL1), read by rule: what the question is about, and which kind it asks.

The owner (2026-11-25): "If I get some null results on any views ... the agents of Rihmasto will always get me back
on track." Typed, that is "why is Insights empty?", "why is cost not measured?", "why is the page blank?", "why did
it fail?" or "why did my last action fail?". The question's subject is read in this order:

1. a view named exactly ("Insights", "the Track view", "releases"): that view's own rules (kernel/neverlost.py);
2. a figure's words that a field rule knows ("cost", "tokens", "tests"), with the view it names when it names one;
3. "the page", "it", "this": the view the person is on; with none, an answer that asks for the part on screen;
4. anything else: its words, on the view the person is on.

Never a search of the cockpit's map: a word such as "cost" also appears in unrelated views' synonyms.
"""

from __future__ import annotations

import re
from typing import Any

_STATE = (r"(?:not (?:being |yet )?measured|empty|blank|null|missing|undefined|nan|no data|"
          r"show(?:s|ing)? nothing|showing no data)")
_ASK_EMPTY = re.compile(rf"\bwhy\b.*\b{_STATE}(?![a-z])", re.I)
# A failure asked about in general ("why did it fail?", "why is it broken?", "why did my last action fail?"): never a
# named thing ("why did the gate fail on T-001?"), which other answers know.
_ASK_ERROR = re.compile(r"\bwhy (?:do|did|does|am|was|is|has|have) (?:i|it|this|that|my (?:last )?\w+|the last \w+)"
                        r"\s+(?:just\s+)?(?:(?:get|getting|see|seeing|got)\s+)?(?:an? )?(?:fail\w*|broken|break\w*|"
                        r"errors?|gone wrong|go wrong|went wrong|not work\w*)\b", re.I)
_LEAD = re.compile(r"^.*?\bwhy\b\s*(?:is|are|does|do|did|was|were|has|have)?\s*", re.I)
_EDGE = {"the", "my", "this", "that", "our", "these", "those", "a", "an", "here", "there", "so", "still", "now",
         "view", "page", "tab", "screen", "figure", "value", "kpi", "number", "chart", "section", "on", "in", "of",
         "it", "everything", "all", "something", "shown", "showing"}


def asked(question: str) -> bool:
    q = question or ""
    return bool(_ASK_EMPTY.search(q) or _ASK_ERROR.search(q))


def kind_of(question: str) -> str:
    if _ASK_ERROR.search(question or "") and not _ASK_EMPTY.search(question or ""):
        return "error"
    return "not_measured" if re.search(r"\bmeasured\b", question, re.I) else "empty"


def subject_of(question: str) -> str:
    """The words the question asks about: "why is the Track view not measured?" -> "track"."""
    rest = _LEAD.sub("", question.strip().rstrip("?!. "), count=1)
    rest = re.split(rf"\b{_STATE}(?![a-z])", rest, maxsplit=1, flags=re.I)[0]
    words = re.findall(r"[\w€$&'-]+", rest.lower())
    while words and words[0] in _EDGE:
        words.pop(0)
    while words and words[-1] in _EDGE:
        words.pop()
    return " ".join(words)


def _views(project: Any) -> list[dict[str, Any]]:
    from kernel.assistant_rules import ui_map

    inside = project is not None
    views = ui_map()["views"]
    # a project's own views first inside a project ("insights" is its Project insights), the platform's outside
    return sorted(views, key=lambda v: ("{pid}" in v["route"]) != inside)


def _names(v: dict[str, Any]) -> tuple[str, ...]:
    return (v["id"].replace("_", " "), v["id"], str(v["label"]).lower())


def view_of(subject: str, project: Any) -> str | None:
    """The view a subject names: exactly, else the longest view name inside it as whole words."""
    views = _views(project)
    exact = next((v["id"] for v in views if subject in _names(v)), None)
    if exact or not subject:
        return exact
    found = [(len(n), -i, v["id"]) for i, v in enumerate(views) for n in _names(v)   # the longest, the nearer first
             if len(n) > 3 and re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", subject)]
    return max(found)[2] if found else None


def _view_names(view_id: str, project: Any) -> tuple[str, ...]:
    return _names(next(v for v in _views(project) if v["id"] == view_id))


def _figure_said(subject: str, named: str | None, project: Any) -> str:
    """A figure's words as the answer's subject: "Cost per task on Project insights", never the view said twice."""
    from kernel.neverlost import view_label

    said = subject[0].upper() + subject[1:]
    if not named:
        return said
    names = "|".join(re.escape(n) for n in _view_names(named, project))
    said = re.sub(rf"\s*\b(?:on|in|of)?\s*(?:the\s+)?(?:{names})\b", "", said, flags=re.I).strip() or said
    return f"{said} on {view_label(named)}"


def answer(factory: Any, project: Any, question: str, view: str | None = None) -> dict[str, Any] | None:
    """The answer by rule to a typed "why ... empty / not measured / failing?", or None when it is not one."""
    from kernel import neverlost

    if not asked(question):
        return None
    kind = kind_of(question)
    if kind == "error":
        return neverlost.why(factory, project, view=view or "", kind="error", basis="")
    subject = subject_of(question)
    named = view_of(subject, project)
    if named and subject in _view_names(named, project):
        return neverlost.why(factory, project, view=named, kind=kind)
    if not subject:                    # "the page", "it": the view the person is on, or no premise without one
        return neverlost.why(factory, project, view=view or "", kind=kind, subject=None if view else "this page")
    figure = neverlost.field_rule(subject) is not None      # a figure: its own rule, on the view it names if any
    said = _figure_said(subject, named, project) if figure else subject[0].upper() + subject[1:]
    return neverlost.why(factory, project, view=named or view or "", field=subject, kind=kind, subject=said)
