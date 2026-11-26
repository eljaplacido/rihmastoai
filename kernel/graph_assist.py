"""Ask Rihma and the knowledge graph (kernel/graph_view.py; FR-GRV1).

Two questions are answered from the graph's read model without a model:

- **"Show me how requirements trace to tests in Home and Horizon"**: the Knowledge graph opened with those
  filters. The kinds named (a requirement and a test bring the criteria between them), the states (open, closed,
  superseded or overturned), "untested" or "contradictions" (only the nodes with an issue), and the projects
  named by title become the route's query: one project opens its Knowledge graph tab, several open the page
  across projects with just those. The answer says what the slice holds, and Take me there opens it.
- **"Explain R-2 in the knowledge graph"**: the node, its state, its links one step away and its issues,
  as the assistant audience may see them, with Take me there to the graph focused on it.

Everything else is left to the rest of Ask Rihma (``routed`` returns None).
"""

from __future__ import annotations

import re
from typing import Any

from kernel.graph_view import Filters, factory_view, noun, project_view
from kernel.graph_view_nodes import FACTORY_PID

GRAPH_WORDS = {"graph", "ontology"}
TRACE_WORDS = {"trace", "traces", "tracing", "traced", "link", "links", "linked", "connect", "connects", "connected",
               "relate", "relates", "related"}
KIND_WORDS = {"requirement": "requirement", "criterion": "criterion", "criteria": "criterion", "test": "test",
              "task": "task", "question": "question", "assumption": "assumption", "decision": "decision",
              "card": "card", "change": "card", "incident": "card", "release": "release", "holdout": "holdout_ref",
              "round": "round", "run": "round", "model": "model", "comment": "comment", "signal": "signal",
              "person": "person", "people": "person", "pack": "pack"}
STATE_WORDS = {"open": "open", "closed": "closed", "settled": "closed", "superseded": "superseded",
               "overturned": "superseded", "stale": "superseded"}
ISSUE_WORDS = {"untested", "orphan", "orphans", "contradiction", "contradictions", "issue", "issues", "gap", "gaps"}
NODE_ID = re.compile(r"\b(R-\d+(?:-AC-\d+)?|FD-\d+(?:-AC-\d+)?|T-\d{3,}|Q-\d{3,}|A-\d{3,}|C-\d{4,}|D-\d{4,}|"
                     r"release-\d+)\b")
_WORD = re.compile(r"[a-z]+")


def _words(question: str) -> set[str]:
    raw = set(_WORD.findall(question.lower()))
    return raw | {w[:-1] for w in raw if len(w) > 3 and w.endswith("s")}


def asks_graph(question: str) -> bool:
    """A question for the knowledge graph: it names the graph or the ontology, or asks how two kinds of record
    trace or link to each other."""
    said = _words(question)
    if said & GRAPH_WORDS:
        return True
    return bool(said & TRACE_WORDS) and len({KIND_WORDS[w] for w in said if w in KIND_WORDS}) >= 2


def projects_in(factory: Any, question: str) -> list[Any]:
    """The projects a question names by title (longest title first), or by id."""
    text, found = question.lower(), []
    for p in sorted(factory.projects(), key=lambda x: -len(str(x.meta.get("title") or ""))):
        title = str(p.meta.get("title") or "").lower()
        if p.pid == FACTORY_PID or not title:
            continue
        if title in text or p.pid in text:
            found.append(p)
            text = text.replace(title, " ")
    return found


def filters_of(question: str) -> Filters:
    """The filters a question asks for: kinds, states and issues."""
    said = _words(question)
    kinds = list(dict.fromkeys(KIND_WORDS[w] for w in sorted(said) if w in KIND_WORDS))
    if "requirement" in kinds and "test" in kinds and "criterion" not in kinds:
        kinds.append("criterion")                     # a requirement reaches its tests through its criteria
    states = sorted({STATE_WORDS[w] for w in said if w in STATE_WORDS})
    return Filters(kinds=tuple(sorted(kinds)), states=tuple(states), issues=bool(said & ISSUE_WORDS))


def _summary(model: dict[str, Any]) -> str:
    kinds = [k for k in model["kinds"] if k["matching"]]
    held = ", ".join(noun(k["id"], k["matching"]) for k in kinds[:6]) or "nothing that matches"
    issues = "; ".join(f"{i['count']}: {i['text'].rstrip('.').lower()}" for i in model["issues"][:3])
    return f"it holds {held}" + (f". Issues: {issues}" if issues else "")


def open_answer(factory: Any, project: Any, question: str) -> dict[str, Any]:
    """The Knowledge graph opened with the filters the question asks for."""
    f = filters_of(question)
    named = projects_in(factory, question) or ([project] if project is not None and project.pid != FACTORY_PID else [])
    if len(named) == 1:
        p = named[0]
        model = project_view(p, f)
        route, where = f"#/p/{p.pid}/graph", str(p.meta.get("title") or p.pid)
    else:
        from dataclasses import replace

        f = replace(f, projects=tuple(p.pid for p in named))
        model = factory_view(factory, f)
        route = "#/graph"
        where = " and ".join(str(p.meta.get("title") or p.pid) for p in named) or "every project"
    query = f.query()
    route += f"?{query}" if query else ""
    shown = ("Not measured now: " + "; ".join(model["causes"])) if model["outcome"] != "answered" else _summary(model)
    answer = (f"The Knowledge graph of {where}, filtered as you asked: {shown}. Take me there opens it with those "
              "filters; the graph filters change them, and Save view keeps them for you.")
    return {"answer": answer, "navigate": {"route": route, "control": "graph_filters"}, "propose": [], "dropped": [],
            "sources": [p.pid for p in named], "by": "graph", "matches": ["graph" if len(named) == 1 else "graph_all"]}


def _neighbours(model: dict[str, Any], focus: str) -> list[str]:
    short = {n["id"]: n["short"] for n in model["nodes"]}
    out = []
    for e in model["edges"][:24]:
        rel = e["rel"].replace("_", " ")
        if e["from"] == focus and e["to"] in short:
            out.append(f"{rel} {short[e['to']]}" + (" (a model's proposal)" if e["proposed"] else ""))
        elif e["to"] == focus and e["from"] in short:
            out.append(f"{short[e['from']]} {rel} it" + (" (a model's proposal)" if e["proposed"] else ""))
    return out


def explain_answer(project: Any, node: str) -> dict[str, Any]:
    """One node explained from the graph: what it is, its state, its links one step away, its issues."""
    model = project_view(project, Filters(focus=node, hops=1, audience="assistant", limit=60))
    route = f"#/p/{project.pid}/graph?focus={node}&hops=1"
    if model["outcome"] != "answered":
        answer = f"The graph of {model['title']} cannot be measured now: {'; '.join(model['causes'])}."
    elif model["focus"] is None:
        answer = f"{node} is not a node of {model['title']}'s knowledge graph."
        route = f"#/p/{project.pid}/graph"
    else:
        n = next(x for x in model["nodes"] if x["id"] == model["focus"])
        links = _neighbours(model, n["id"])
        state = f" ({n['state']})" if n["state"] else ""
        answer = (f"{n['short']} is a {n['kind'].replace('_', ' ')}{state} in {model['title']}: "
                  f"{n['label'].rstrip('.')}. "
                  + (f"Links: {'; '.join(links)}. " if links else "It links to nothing yet. ")
                  + " ".join(f"Issue: {i}" for i in _issue_texts(model, n)) + f" It is kept in {n['record']}.")
    return {"answer": answer.replace("  ", " ").strip(), "navigate": {"route": route, "control": None},
            "propose": [], "dropped": [], "sources": [project.pid, node], "by": "graph", "matches": ["graph"]}


def _issue_texts(model: dict[str, Any], n: dict[str, Any]) -> list[str]:
    texts = {i["id"]: i["text"] for i in model["issue_kinds"]}
    return [texts[i] for i in n["issues"] if i in texts]


def routed(factory: Any, project: Any, question: str) -> dict[str, Any] | None:
    """Ask Rihma's hook (kernel/copilot.py): a graph question's answer, or None for every other question."""
    said = _words(question)
    ids = NODE_ID.findall(question)
    named = projects_in(factory, question)
    where = project if project is not None else (named[0] if len(named) == 1 else None)
    if ids and where is not None and where.pid != FACTORY_PID and ("explain" in said or said & GRAPH_WORDS):
        return explain_answer(where, ids[0])
    if asks_graph(question) and (named or filters_of(question) != Filters()):
        return open_answer(factory, project, question)
    return None                       # "where is the knowledge graph?" is the map's (cockpit/ui_map.json)
