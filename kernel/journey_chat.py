"""Ask Rihma on how to get somewhere (FR-JRN1): the journey, where the person is on it, and the next step, by rule.

The owner (2026-11-25), after asking "how should I get started with brownfield project": "it just told what the
project view shows, this is a terrible walkthrough. Only Claude Code could tell me that I should run the
assessment. Why couldn't the user request hand-holding to feed in an existing project?"

So a question kernel/journey_intent.py places is answered here, from the journeys (kernel/journeys.py) and the
records (kernel/journey_state.py), with no model: right even when the only model is a small local one. The answer
says where the person is, the next step with what it does and why, the button that does it and the command line,
the remaining steps, and offers Guide me step by step (the guided panel, cockpit/static/journey.js). "What should
I do next?" is answered from the open project's state through its journey, or, for the factory, which project
needs what. A how-to question the rules leave to the model gets the matching journey's steps in its prompt
(``grounding``), so the model names steps and buttons and never describes a view instead.

``routed`` is Ask Rihma's hook (kernel/assistant.py): an answer already found stays.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import journey_intent as ji
from kernel import journey_state as js
from kernel import journeys as kj

FACTORY_PID = "_factory"
GROUNDING_BUDGET = 1_400
# A journey about one project that any project may be on, besides the one it started on.
ANY_PROJECT = ("ide", "deploy", "automations")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def _real(project: Any) -> Any:
    return None if project is None or project.pid == FACTORY_PID else project


def _hidden(factory: Any, project: Any) -> set[str]:
    from kernel.modules import hidden_ids

    return set(hidden_ids(project if project is not None else factory))


def _shown(prog: dict[str, Any], hidden: set[str]) -> dict[str, Any]:
    """A step whose control belongs to a module that is not enabled here says so instead of pointing at it."""
    for s in prog["steps"]:
        if s["action"].get("control") in hidden:
            s["action"]["control"] = None
            s["off"] = "its module is not enabled here: Settings, Modules turns it on"
    return prog


def _for(project: Any, name: str) -> Any:
    """The open project, when the journey asked about is one this project is on."""
    if project is None:
        return None
    return project if name in ANY_PROJECT or js.journey_for(project) == name else None


def _step(prog: dict[str, Any]) -> dict[str, Any] | None:
    return next((s for s in prog["steps"] if s["id"] == prog["next"]), None)


def how_line(step: dict[str, Any]) -> str:
    """How to do a step: its button, and the command line."""
    cmd = (step.get("command") or "").split("   ")[0]
    return f"Press {step['button']}" + (f" (or: {cmd})" if cmd else "") + "."


def step_line(step: dict[str, Any]) -> str:
    """The next step in a sentence: what the records say about it, that it is next, and why."""
    state = step.get("said") or step.get("not_yet") or f"{step['title']} is not done yet"
    return f"{state[:1].upper()}{state[1:].rstrip('.')}: that is next ({step['title']}), because " \
           f"{_lower_first(step['why'].rstrip('.'))}."


def where_line(prog: dict[str, Any]) -> str:
    """Where the person is: where the project came from (adopted 2 h ago) and how many steps are done."""
    title, count = prog.get("title"), f"{prog['done']} of {prog['total']} steps are done."
    if title and prog.get("anchor"):
        return f"{title} was {prog['anchor']}; {_lower_first(count)}"
    last = prog.get("last_done") or {}
    said = last.get("said") or last.get("title")
    return " ".join(x for x in (f"{title}:" if title else "", f"{said}." if said else "", count) if x)


def _then(prog: dict[str, Any], after: str | None, most: int = 4) -> str:
    ids = [s["id"] for s in prog["steps"]]
    left = [s for s in prog["steps"][ids.index(after) + 1 if after in ids else 0:]
            if s["state"] not in ("done", "skipped")]
    if not left:
        return ""
    names = [s["title"] for s in left[:most]] + (["and more"] if len(left) > most else [])
    return " Then: " + "; ".join(names) + "."


def journey_text(prog: dict[str, Any]) -> str:
    """The answer about a journey in plain words: where the person is, the next step, how, and what follows."""
    label, title = prog["label"], prog.get("title")
    if prog["complete"]:
        return (f"{title}: every step of {label} is done ({prog['done']} of {prog['total']})." if title else
                f"Every step of {label} is done.")
    step = _step(prog)
    assert step is not None
    if prog["done"] == 0 and not title:
        head = f"{label} takes {prog['total']} steps, and I can take you through each one. First: {step['title']}. " \
               f"{step['why']} {how_line(step)}"
        most = len(prog["steps"])
    else:
        head = f"{where_line(prog)} {step_line(step)} {how_line(step)}"
        most = 4
    return head + _then(prog, step["id"], most) + " Or press Guide me step by step, and I stay with you through " \
                                                  "each one."


def _out(text: str, prog: dict[str, Any] | None, *, matches: list[str], by: str = "journey",
         extra: dict[str, Any] | None = None) -> dict[str, Any]:
    pid = (prog or {}).get("project")
    step = _step(prog) if prog and not prog.get("complete") else None
    action = (step or {}).get("action") or {}
    nav = {"route": action.get("route"), "control": action.get("control")} if step else None
    return {"answer": text, "navigate": nav, "propose": [], "dropped": [], "sources": [pid] if pid else [], "by": by,
            "matches": matches, **({"journey": prog} if prog else {}), **(extra or {})}


def _elsewhere(factory: Any, persona: str | None) -> str:
    """For feeding in, asked outside a project: the projects already fed in that are not through yet."""
    rows = [r for r in js.factory_next(factory, persona=persona, limit=20)
            if r["journey"] == "brownfield" and r["next"] is not None][:3]
    if not rows:
        return ""
    return " Already fed in: " + "; ".join(f"{r['title']} ({r['done']} of {r['total']} done), next: "
                                           f"{r['next']['title']}" for r in rows) + "."


def journey_answer(factory: Any, project: Any, name: str, *, persona: str | None = None) -> dict[str, Any]:
    """The answer about one journey, measured on the open project when it is on that journey."""
    on = _for(_real(project), name)
    prog = _shown(js.progress(factory, name, project=on, persona=persona), _hidden(factory, on))
    text = journey_text(prog) + (_elsewhere(factory, persona) if name == "brownfield" and on is None else "")
    return _out(text, prog, matches=[name], extra={"guide": {"journey": name, "project": prog["project"]}})


def next_answer(factory: Any, project: Any, *, persona: str | None = None) -> dict[str, Any]:
    """What to do next: the open project's next step through its journey, or which project needs what."""
    on = _real(project)
    if on is None:
        return factory_answer(factory, persona=persona)
    name = js.journey_for(on)
    prog = _shown(js.progress(factory, name, project=on, persona=persona), _hidden(factory, on))
    text = journey_text(prog)
    if prog["complete"]:
        from kernel.assistant_status import status_answer

        text += " " + status_answer(on)["answer"]
    return _out(text, prog, matches=[name, "next"], extra={"guide": {"journey": name, "project": on.pid}})


def factory_answer(factory: Any, *, persona: str | None = None) -> dict[str, Any]:
    """Which project needs what: each project's journey and its next step, the unfinished first."""
    rows = js.factory_next(factory, persona=persona)
    open_rows = [r for r in rows if r["next"] is not None]
    if not rows:
        return starters_answer(persona=persona)
    if not open_rows:
        return _out(f"Every project here is through its first journey ({len(rows)} project"
                    f"{'s' if len(rows) != 1 else ''}). Open one and ask what is next for its own work.",
                    None, matches=["next"], extra={"projects": rows})
    lines = "; ".join(f"{r['title']} ({_lower_first(r['label'])}, {r['done']} of {r['total']} done): "
                      f"{r['next']['title']}" for r in open_rows[:4])
    return _out(f"Which project needs what: {lines}. Open one, or press its step.", None, matches=["next"],
                extra={"projects": open_rows[:4]})


def starters_answer(*, persona: str | None = None) -> dict[str, Any]:
    """The three ways in, for a person starting out: each one a journey to be guided through."""
    rows = [j for j in kj.catalogue(persona) if j["starter"]]
    names = "; ".join(f"{j['label']}: {j['about']}" for j in rows)
    return _out(f"There are three ways in. {names}. Pick one and I take you through it step by step, or take the "
                "five-stop tour of the cockpit first.", None, matches=["start"], extra={"starters": rows})


def routed(factory: Any, project: Any, question: str, about: dict[str, Any] | None, *, persona: str,
           model: Any = None) -> dict[str, Any] | None:
    """Ask Rihma's hook (kernel/assistant.py): an answer already found stays; else a journey, the next step or the
    ways in, by rule; else the goal help's hooks (kernel/copilot.py ``routed``), as before."""
    from kernel import copilot

    return by_rule(factory, project, question, about, persona=persona) \
        or copilot.routed(factory, project, question, about, persona=persona, model=model)


def by_rule(factory: Any, project: Any, question: str, about: dict[str, Any] | None, *,
            persona: str) -> dict[str, Any] | None:
    """A journey, the next step or the ways in, when the words ask for one (kernel/journey_intent.py)."""
    if about is not None:
        return about
    got = ji.recognise(question)
    if got is None:
        return None
    kind, name = got
    if kind == "journey" and name:
        return journey_answer(factory, project, name, persona=persona)
    if kind == "next" or _real(project) is not None:
        return next_answer(factory, project, persona=persona)
    return starters_answer(persona=persona)


# -- grounding the model's answer ------------------------------------------------------------------------------

_WORD = re.compile(r"[a-zåäö]{4,}")
_STOP = {"what", "where", "does", "this", "that", "with", "from", "have", "should", "would", "could", "there",
         "your", "into", "them", "then", "they", "when", "which", "about", "first"}


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in _WORD.findall(text.lower())} - _STOP


def _matching(question: str) -> tuple[kj.Journey, kj.Step | None] | None:
    """The journey a how-to question is about, and its step that shares the most words with it."""
    named = ji.journey_named(ji.said(question))
    q = _words(question)
    best: tuple[int, kj.Journey, kj.Step] | None = None
    for j in kj.JOURNEYS.values():
        for s in j.steps:
            n = len(q & _words(f"{s.title} {s.button} {s.business}"))
            if n and (best is None or n > best[0] or (n == best[0] and j.name == named)):
                best = (n, j, s)
    if named:
        return kj.journey(named), best[2] if best and best[1].name == named else None
    return (best[1], best[2]) if best else None


def grounding(question: str) -> dict[str, Any] | None:
    """For the model's prompt, when the question asks how to do something: the matching journey's steps, compact
    (each its button and command), and the rule to answer with them. None for any other question."""
    if not ji.asks_how(question):
        return None
    got = _matching(question)
    if got is None:
        return None
    j, step = got
    rows = [f"{i}. {s.title}: press {s.button}" + (f" ({kj.command(s).split('   ')[0]})" if s.command else "")
            + (" <- asked" if step is not None and s.id == step.id else "") for i, s in enumerate(j.steps, 1)]
    out = {"use": "The person asks how to do something. Answer with these steps, in order, naming each step's "
                  "button and its command; say which one they asked about. Never describe a view instead.",
           "journey": j.label, "steps": rows}
    while len(str(out)) > GROUNDING_BUDGET and len(rows) > 3:
        rows.pop()
    return out
