"""Ask Rihma about Rihmasto's structure and where the work went, by rule and without a model (FR-STR1).

- "am I just conforming to Rihmasto or moving development?", "where did the work go?": the balance of the last 30
  days (kernel/work_balance.py) in one sentence, the warning when conformance dominates, and the next steps from the
  real state, each with Take me there;
- "turn off the test-trace convention for this project", "make the criteria convention advise only", "enforce
  decision records here": a proposal (``structure_set``) with the preview's lines; the person confirms it in the
  cockpit, signed with their name; their "because ..." is the reason recorded, else their own words are;
- "what does Rihmasto enforce here?", "which of Rihmasto's conventions apply?", "show me the test-trace
  convention": each convention's level and where it comes from (this project, all projects, the default); a
  question never gets a proposal (FR-STR2);
- "Code plan highlights 124 to decide, what should I do with these results?", "are the tasks highlighted about
  enforcing Rihmasto's own structure?": the Alignment's real split and the next steps (kernel/structure_guide.py).

Inside a project the change is the project's own unless the question names all projects or the platform. The
assistant itself writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import structure_policy as sp
from kernel import work_balance as wb
from kernel.enforcement_chat import REASON, reason_of  # the person's own "because ...", as for enforcement

WORK = re.compile(r"\bconform(?:ing|s|ed|ance)?\b|\bmov(?:e|es|ing)\s+(?:the\s+)?(?:development|dev|needle|work)\b"
                  r"|\bwhere\s+(?:did\s+|does\s+|has\s+)?(?:the\s+|my\s+|our\s+)?(?:work|time)\s+(?:go|went|gone)\b"
                  r"|\bwork\s+balance\b|\bwhere\s+the\s+work\s+went\b")
CONVENTION_WORDS = {
    "test_trace": ("test-trace", "test trace", "tests trace", "test tracing", "trace convention", "traceability "
                   "convention", "tests to requirements"),
    "criteria": ("given/when/then", "given when then", "criteria convention", "criteria rule", "acceptance criteria "
                 "convention"),
    "task_links": ("task links", "tasks link", "task-link", "task link"),
    "decisions": ("decisions recorded", "decision records", "record decisions", "adr convention", "decision record"),
    "api_contracts": ("api contract", "api contracts", "contracts declared"),
    "commit_hygiene": ("commit hygiene", "commit message convention", "commit convention"),
    "layout": ("layout check", "layout checks", "repository layout", "layout convention"),
}
ALL_WORDS = ("all conventions", "every convention", "all of rihmasto's conventions", "rihmasto's conventions",
             "rihmasto conventions", "rihmasto's structure", "rihmasto structure", "all the conventions")
# Whole words only (FR-STR2): "require" must not be read inside "requirements".
LEVEL_WORDS = (("advise", re.compile(r"\b(?:stop enforcing|don't enforce|do not enforce|advise|advice|suggestions?"
                                     r"|just suggest|only suggest)\b")),
               ("off", re.compile(r"\b(?:turn off|switch off|disable|hide|turn it off|off)\b")),
               ("enforce", re.compile(r"\b(?:enforce|require|required|mandatory)\b")),
               ("inherit", re.compile(r"\b(?:as for all projects|like all projects|back to the default|reset)\b")))
ASKING = ("what ", "which ", "how ", "is ", "are ", "does ", "do ", "why ", "show ", "tell ", "explain ",
          "describe ", "what's ", "can you show", "can you tell", "could you show", "could you tell", "let me see",
          "i want to see", "help me understand")
STATUS = re.compile(r"\b(?:conventions?|rihmasto'?s?\s+structure|structure\s+polic(?:y|ies))\b")
PLATFORM = ("all projects", "every project", "the platform", "platform-wide", "all my projects")


def _low(q: str) -> str:
    return " ".join(q.lower().split())


def _conventions(low: str) -> list[str]:
    if any(w in low for w in ALL_WORDS):
        return list(sp.CONVENTIONS)
    return [c for c, words in CONVENTION_WORDS.items() if any(w in low for w in words)]


def _level(low: str) -> str | None:
    return next((lvl for lvl, words in LEVEL_WORDS if words.search(low)), None)


def asks(question: str) -> str | None:
    """Which question it is: ``work`` (the balance), ``set`` (a level for a convention), ``decide`` (what the
    Alignment's items are and what to do with them, kernel/structure_guide.py), ``status`` or None."""
    from kernel import structure_guide

    low = _low(question)
    convs = _conventions(low)
    if convs and _level(REASON.sub("", low)) and not low.startswith(ASKING):
        return "set"
    if structure_guide.asks(low):
        return "decide"
    if WORK.search(low) and ("rihma" in low or "structure" in low or "develop" in low or "work" in low
                             or "needle" in low):
        return "work"
    if convs or (STATUS.search(low) and ("rihma" in low or "structure" in low)):
        return "status"
    return None


def _out(answer: str, steps: list[dict[str, Any]], nav: dict[str, Any] | None,
         propose: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"answer": answer, "steps": steps, "navigate": nav, "propose": propose or [], "dropped": [],
            "sources": [], "by": "rule", "matches": ["structure_policy"]}


def _nav(project: Any) -> dict[str, Any]:
    if project is None:
        return {"route": "#/settings", "control": "structure_policy"}
    return {"route": f"#/p/{project.pid}/align", "control": "structure_policy"}


def _project(project: Any) -> Any:
    from kernel.learn import FACTORY_PID

    return None if project is None or project.pid == FACTORY_PID else project


def answer(factory: Any, question: str, project: Any, persona: str,
           holding: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    """The answer, or None when the question is about neither Rihmasto's structure nor where the work went."""
    kind = asks(question)
    if kind is None:
        return None
    project = _project(project)
    if kind == "work":
        return work_answer(factory, project)
    if kind == "decide":
        from kernel import structure_guide

        return structure_guide.answer(factory, project)
    platform = project is None or any(w in _low(question) for w in PLATFORM)
    scope = None if platform else project
    if kind == "status":
        return status_answer(factory, scope)
    may = persona in sp.SETTERS or any(p in sp.SETTERS for p in holding or ())
    return set_answer(factory, scope, question, persona, may)


def work_answer(factory: Any, project: Any) -> dict[str, Any]:
    w = wb.read(factory, pid=project.pid if project is not None else None, window="30d")
    steps = [{"text": s["text"] + ".", "action": "navigate", "route": s["route"], "control": s["control"]}
             for s in w["suggestions"]]
    nav = ({"route": f"#/p/{project.pid}/overview", "control": "work_balance"} if project is not None
           else {"route": "#/insights", "control": "work_balance"})
    steps.append({"text": "Open Where the work went to see the items behind each bar (Take me there opens it).",
                  "action": "navigate"})
    if not w["warning"] and w["measured"]:
        steps.insert(0, {"text": "Development is moving: keep Rihmasto's conventions at Advise where they are not "
                                 "worth the time; they stay suggestions, never counted against you."})
    if not w["measured"]:
        steps.insert(0, {"text": "Nothing counted yet: accept or reject Alignment items, merge a change or commit "
                                 "to the repository and it shows here."})
    text = w["line"] + (" " + w["warning"] if w["warning"] else "")
    return _out(text, steps, nav)


def _row_said(r: dict[str, Any]) -> str:
    where = {"project": "this project's own", "platform": "all projects'", "default": "Rihmasto's default"}
    return f"{r['label']}: {sp.LEVEL_WORD[r['level']]} ({where[r['scope']]})"


def status_answer(factory: Any, project: Any) -> dict[str, Any]:
    if project is None:
        d = sp.describe(factory)
        own = "; ".join(_row_said(r) for r in d["kinds"]["own"])
        built = "; ".join(_row_said(r) for r in d["kinds"]["built"])
        text = (f"Rihmasto's structure for projects with their own structure: {own}. For projects Rihmasto builds: "
                f"{built}.")
        steps = [{"text": "Open Settings > Rihmasto's structure to change a default, with a preview first (Take me "
                          "there opens it).", "action": "navigate"}]
        return _out(text, steps, _nav(None))
    d = sp.describe(factory, project)
    rows = d["rows"]
    said = {"own": "a project brought in with a structure of its own: Rihmasto takes that structure as given where a "
                   "convention is at Advise", "built": "a project Rihmasto builds: its conventions are the project's "
                                                       "own structure"}
    text = (f"{d['title']} is {said[d['kind']]}. " +"; ".join(_row_said(r) + (f", {r['found']} found now" if r["found"]
                                                                              else "") for r in rows) + ".")
    enforced = [r for r in rows if r["level"] == "enforce" and r["found"]]
    steps = [{"text": f"{r['label']} is enforced with {r['found']} open: decide its card in the Inbox, or set it to "
                      "Advise (Take me there opens it).", "action": "navigate"} for r in enforced]
    steps.append({"text": "Open Alignment > Rihmasto's structure to change a level: the preview says what moves "
                          "before you save (Take me there opens it).", "action": "navigate"})
    return _out(text, steps, _nav(project))


def set_answer(factory: Any, project: Any, question: str, persona: str, may: bool) -> dict[str, Any]:
    low = _low(question)
    level = _level(REASON.sub("", low)) or "advise"
    levels = {c: level for c in _conventions(low)}
    platform = project is None
    try:
        seen = sp.preview(factory, project, levels, kind="own")
    except ValueError as exc:
        return _out(f"That change cannot be made: {exc}.", [], _nav(project))
    where = "all projects with their own structure" if platform else str(project.meta.get("title") or project.pid)
    if all(c["from"] == c["to"] for c in seen["changes"]):
        now = "; ".join(f"{c['label']} is {sp.LEVEL_WORD[c['to']]}" for c in seen["changes"]) or "nothing changes"
        return _out(f"That is already how {where} is set: {now}.", [{"text": "Open Rihmasto's structure to see each "
                    "convention's level and where it comes from (Take me there opens it).", "action": "navigate"}],
                    _nav(project))
    lines = " ".join(seen["lines"])
    if not may:
        return _out(f"{lines} A business owner, product owner, developer or IT sets it, on the view I open.",
                    [{"text": "Ask one of them, or switch persona if you hold one.", "action": "navigate"}],
                    _nav(project))
    reason = reason_of(question) or f"asked in Ask Rihma: {question.strip()[:240]}"
    pid = project.pid if project is not None else None
    prop = {"action": "structure_set", "why": lines, "persona": persona, "project": pid,
            "args": {"project": pid, "levels": levels, "reason": reason, **({"kind": "own"} if platform else {})}}
    return _out(f"For {where}: {lines} Nothing is written to the repository. I can make the change; you confirm it, "
                f"signed with your name. The reason recorded: {reason}.",
                [{"text": "Confirm the proposal below, or open the preview to change it first (Take me there opens "
                          "it).", "action": "navigate"}], _nav(project), [prop])
