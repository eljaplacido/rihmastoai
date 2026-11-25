"""What people ask the knowledge graph, its parity with the hand-written walkers, the assistant
evaluation baseline, and the read-only `rihmasto graph` command (docs/knowledge-graph.md; FR-KG1).

- `rests_on_refuted`: which releases rest on a refuted assumption (a release carries a requirement
  version derived from a question whose assumption a person refuted).
- `criteria_from_answers`: which criteria trace back to a named person's answer (through the
  requirement's earlier versions, when an amendment replaced its sources).
- `production_approvals`: who approved each release that reached production, and whether that approval
  still holds (it went stale when a change touched what it rested on).
- `parity`: `Graph.impact` against `kernel.insight.impact` on the same ids. It reports any field where
  they differ, the releases the old walker listed although they do not carry the ids (it listed every
  release), and whether the `refs.scope == "release"` branch the walkers keep is dead.
- `eval_baseline`: the cockpit assistant, as it is today (a flat snapshot, no graph), asked "why"
  questions whose answers the graph knows. It reports cited-id recall and the rate of citations no record
  backs, or `not_measured` when no model endpoint answers. Nothing is kept and nothing is written:
  graph context never reaches the analyst lane, which the holdout author shares.

Every answer cites the records it rests on and ends in answered, ambiguous, not_found or not_measured.
Every `rihmasto graph` command only reads, and `check` reports without blocking: it exits 0 whatever it
finds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel import graph_view_cli
from kernel.graph import Graph, build

CITABLE = ("question", "assumption", "card", "decision", "signal")
AUDIENCES = ("person", "assistant", "verifier", "builder")
EVAL_LIMIT = 6


def _rids(graph: Graph) -> list[str]:
    return sorted({n["rid"] for n in graph.nodes.values() if n["kind"] == "requirement"})


def rests_on_refuted(graph: Graph) -> dict[str, Any]:
    """Each release that carries a requirement version derived from a question whose assumption was
    refuted, with the chain that shows it."""
    query = graph.query_of("rests_on_refuted", [])
    causes = graph.unmeasured()
    if causes:
        return graph.not_measured(query, causes)
    rows: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for release in graph.ordered("release"):
        for carry in graph.out_edges(release, "carries"):
            for source in graph.out_edges(carry["to"], "derived_from"):
                for assumed in graph.out_edges(source["to"], "assumed_as"):
                    if graph.nodes[assumed["to"]].get("status") != "refuted":
                        continue
                    rows.append({"release": graph.nodes[release]["number"],
                                 "requirement": graph.nodes[carry["to"]]["rid"], "version": carry["to"],
                                 "question": source["to"], "assumption": assumed["to"],
                                 "by": [carry["by"], source["by"], assumed["by"],
                                        graph.nodes[assumed["to"]]["record"]]})
                    steps += [carry, source, assumed]
    return graph.answer(query, "answered", rows=rows, **graph.cite(steps, []))


def _behind(graph: Graph, current: str, person: str) -> list[tuple[dict[str, Any], ...]]:
    """The chains from a requirement's version in force back to the person's answers: any number of
    revision_of steps, then derived_from to a question, then answered_by to the person."""
    chains: list[tuple[dict[str, Any], ...]] = []
    hops: tuple[dict[str, Any], ...] = ()
    version: str | None = current
    while version is not None:
        for source in graph.out_edges(version, "derived_from"):
            chains += [(*hops, source, a) for a in graph.out_edges(source["to"], "answered_by") if a["to"] == person]
        back = graph.out_edges(version, "revision_of")
        hops, version = (hops + (back[0],), back[0]["to"]) if back else (hops, None)
    return chains


def criteria_from_answers(graph: Graph, person: str) -> dict[str, Any]:
    """The criteria in force whose requirement traces back to the named person's answer."""
    query = graph.query_of("criteria_from_answers", [person])
    causes = graph.unmeasured()
    if causes:
        return graph.not_measured(query, causes)
    pid = f"person:{person}"
    if pid not in graph.nodes:
        return graph.answer(query, "not_found", missing=[person])
    rows: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for rid in _rids(graph):
        current = graph.current(rid)
        for chain in _behind(graph, current, pid) if current else []:
            for hc in sorted(graph.out_edges(current or "", "has_criterion"), key=lambda e: e.get("n", 0)):
                rows.append({"criterion": graph.nodes[hc["to"]]["plain"], "node": hc["to"], "requirement": rid,
                             "question": chain[-1]["from"], "person": person, "persona": chain[-1].get("persona"),
                             "through": [e["to"] for e in chain if e["rel"] == "revision_of"]})
                steps += [hc, *chain]
    return graph.answer(query, "answered", rows=rows, **graph.cite(steps, []))


def production_approvals(graph: Graph) -> dict[str, Any]:
    """For each release that reached production: each approval of it, who gave it as which persona,
    and whether it still holds."""
    query = graph.query_of("production_approvals", [])
    causes = graph.unmeasured()
    if causes:
        return graph.not_measured(query, causes)
    rows: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for release in graph.ordered("release"):
        if "production" not in graph.nodes[release].get("reached", []):
            continue
        for approval in graph.in_edges(release, "approves"):
            d = graph.nodes[approval["from"]]
            stale = graph.out_edges(d["id"], "invalidated_by")
            rows.append({"release": graph.nodes[release]["number"], "decision": d["id"], "card": d.get("card"),
                         "kind": d.get("card_kind"), "verdict": d.get("verdict"), "person": d.get("person"),
                         "persona": d.get("persona"), "holds": not graph.stale(d),
                         "invalidated_by": [e["to"] for e in stale]})
            steps += [approval, *graph.out_edges(d["id"], "signed_by"), *stale]
    return graph.answer(query, "answered", rows=rows, **graph.cite(steps, []))


def parity(project: Any, ids: list[str]) -> dict[str, Any]:
    """`Graph.impact` and `kernel.insight.impact` on the same ids: where they differ, and what the
    hand-written walkers got wrong (the release hop) or can never reach (the release scope)."""
    from kernel.insight import impact

    graph = build(project)
    query = graph.query_of("parity", list(ids))
    answer = graph.impact(list(ids))
    if answer["outcome"] == "not_measured":
        return graph.not_measured(query, answer["causes"])
    mine, theirs = answer["result"], impact(project, list(ids))
    differences = [{"field": k, "graph": mine.get(k), "insight": theirs.get(k)}
                   for k in sorted(set(mine) | set(theirs)) if mine.get(k) != theirs.get(k)]
    every = [graph.nodes[n]["number"] for n in graph.ordered("release")]
    carrying = [r["release"] for r in mine["releases_carrying"]]
    scoped = [n for n in graph.ordered("decision") if graph.nodes[n].get("scope") == "release"]
    notes = [f"{len(carrying)} of {len(every)} releases carry {', '.join(ids)}; before this fix insight.impact "
             f"listed every release as carrying them"]
    if not scoped:
        notes.append("no decision carries refs.scope == 'release' (nothing in kernel/ writes it): the branch in "
                     "Canon._rests_on and insight.impact is dead")
    return graph.answer(query, "answered", agree=not differences, differences=differences,
                        releases={"every": every, "carrying": carrying,
                                  "listed_before_the_fix": [n for n in every if n not in carrying]},
                        scope_release_decisions=scoped, notes=notes)


# -- the assistant evaluation baseline -----------------------------------------------------------------

def _record_id(node: dict[str, Any]) -> list[str]:
    """The ids a person or the assistant would cite a node by."""
    keys = {"requirement": "rid", "criterion": "plain", "test": "name", "person": "name", "pack": "version"}
    ids = [str(node[keys[node["kind"]]])] if node["kind"] in keys else [node["id"]]
    return ids + ([str(node["number"])] if node["kind"] == "release" else [])


def eval_cases(graph: Graph, limit: int = EVAL_LIMIT) -> list[dict[str, Any]]:
    """'Why' questions whose answers the graph knows: for each requirement in force, the records its
    trace reaches that the assistant could cite."""
    cases: list[dict[str, Any]] = []
    for rid in _rids(graph):
        current = graph.current(rid)
        reached = graph.walk([current], upstream=True)[0] if current else []
        expected = sorted({graph.nodes[n]["id"] for n in reached if graph.nodes[n]["kind"] in CITABLE})
        if expected:
            cases.append({"about": rid, "question": f"Why does requirement {rid} exist? Name the records it rests "
                                                    f"on, by their ids.", "expected": expected})
    return cases[:limit]


def _ask(project: Any, model: Any, persona: str, case: dict[str, Any], known: set[str]) -> dict[str, Any]:
    from kernel.assistant import ask
    from kernel.model import ModelError

    try:
        out = ask(project.factory, case["question"], persona=persona, project_id=project.pid, model=model)
    except ModelError as exc:
        return {**case, "measured": False, "why": f"no model endpoint answered: {exc}"}
    if out.get("by") != "assistant":
        return {**case, "measured": False,
                "why": f"no model endpoint answered: {out.get('note') or 'the answer came from the cockpit map'}"}
    cited = [s for s in out.get("sources") or [] if isinstance(s, str)]
    return {**case, "measured": True, "cited": cited, "hits": sorted(set(cited) & set(case["expected"])),
            "unbacked": [s for s in cited if s not in known]}


def eval_baseline(project: Any, model: Any, *, persona: str = "product_owner",
                  limit: int = EVAL_LIMIT) -> dict[str, Any]:
    """The assistant's cited-id recall on the graph's 'why' questions, and the rate of its citations no
    record backs. Not measured when no model is asked or none answers; a rate with nothing to count
    has no value, never zero."""
    graph = build(project)
    query = graph.query_of("eval_baseline", [], persona=persona, model=type(model).__name__ if model else None)
    causes = graph.unmeasured()
    if not causes and model is None:
        causes = ["no model endpoint was asked (--with-model asks one)"]
    if causes:
        return graph.not_measured(query, causes)
    cases = eval_cases(graph, limit)
    if not cases:
        return graph.answer(query, "not_found", missing=[],
                            why="no requirement rests on a record the assistant could cite")
    known = {i for n in graph.nodes.values() for i in _record_id(n)}
    from kernel.model_usage import quiet

    with quiet():        # an evaluation keeps nothing: its runs are not the project's usage
        rows = [_ask(project, model, persona, case, known) for case in cases]
    measured = [r for r in rows if r["measured"]]
    if not measured:
        return graph.not_measured(query, sorted({r["why"] for r in rows}))
    return graph.answer(query, "answered", cases=rows, measured=len(measured), asked=len(rows), **_scores(measured))


def _scores(measured: list[dict[str, Any]]) -> dict[str, Any]:
    """Cited-id recall over every expected id, and the share of citations no record backs (not
    measured when the assistant cited nothing)."""
    def total(key: str) -> int:
        return sum(len(r[key]) for r in measured)

    cited = total("cited")
    return {"cited_id_recall": round(total("hits") / total("expected"), 3),
            "unbacked_citation_rate": round(total("unbacked") / cited, 3) if cited else "not measured"}


# -- `rihmasto graph`: read only ------------------------------------------------------------------------

def add_parsers(sub: Any) -> None:
    """`rihmasto graph <command> <pid> ...`, as the command line's parser adds it."""
    group = sub.add_parser("graph", help="one project's knowledge graph, read only (kernel/graph.py)")
    cmds = group.add_subparsers(dest="sub", required=True)
    for name, about in (("trace", "what the records rest on, upstream"), ("impact", "what rests on them, downstream")):
        p = cmds.add_parser(name, help=about)
        p.add_argument("pid")
        p.add_argument("ids", nargs="+")
        p.add_argument("--as-of", type=int, help="the graph as it stood at this ledger sequence number")
    p = cmds.add_parser("parity", help="graph impact against insight.impact on the same requirement ids")
    p.add_argument("pid")
    p.add_argument("ids", nargs="+")
    p = cmds.add_parser("path", help="the shortest chain of links between two records")
    for arg in ("pid", "start", "goal"):
        p.add_argument(arg)
    p.add_argument("--as-of", type=int)
    for name, about in (("check", "closed-world rules; it reports and never blocks"),
                        ("refuted", "releases that rest on a refuted assumption"),
                        ("approvals", "who approved each production release, and whether it still holds")):
        p = cmds.add_parser(name, help=about)
        p.add_argument("pid")
        p.add_argument("--as-of", type=int)
    p = cmds.add_parser("answers", help="criteria that trace back to a person's answer")
    p.add_argument("pid")
    p.add_argument("person")
    p.add_argument("--as-of", type=int)
    p = cmds.add_parser("show", help="every node and edge an audience may see")
    p.add_argument("pid")
    p.add_argument("--audience", choices=AUDIENCES, default="person")
    p = cmds.add_parser("eval", help="the assistant evaluation baseline (not measured without a model)")
    p.add_argument("pid")
    p.add_argument("--with-model", action="store_true", help="ask the assistant's model through Gnomon")
    p.add_argument("--persona", default="product_owner")
    graph_view_cli.add_parser(cmds)                     # the view with filters (kernel/graph_view_cli.py, FR-GRV1)


def _graph(factory: Any, args: Any) -> Graph:
    graph = build(factory.project(args.pid))
    return graph.as_of(args.as_of) if getattr(args, "as_of", None) is not None else graph


def _trace(factory: Any, args: Any) -> Any:
    """One trace answer per id, from one build."""
    graph = _graph(factory, args)
    answers = [graph.trace(i) for i in args.ids]
    return answers[0] if len(answers) == 1 else answers


def handlers(emit: Callable[[Any], None], model: Callable[[], Any]) -> dict[str, Callable[[Any, Any], int | None]]:
    """The `rihmasto graph` handlers. ``emit`` prints an answer; ``model`` makes the assistant's model."""
    return {
        "graph trace": lambda f, a: emit(_trace(f, a)),
        "graph impact": lambda f, a: emit(_graph(f, a).impact(a.ids)),
        "graph path": lambda f, a: emit(_graph(f, a).path(a.start, a.goal)),
        "graph check": lambda f, a: emit(_graph(f, a).check()),
        "graph show": lambda f, a: emit(_graph(f, a).show(a.audience)),
        "graph refuted": lambda f, a: emit(rests_on_refuted(_graph(f, a))),
        "graph answers": lambda f, a: emit(criteria_from_answers(_graph(f, a), a.person)),
        "graph approvals": lambda f, a: emit(production_approvals(_graph(f, a))),
        "graph parity": lambda f, a: emit(parity(f.project(a.pid), a.ids)),
        "graph eval": lambda f, a: emit(eval_baseline(f.project(a.pid), model() if a.with_model else None,
                                                      persona=a.persona)),
        "graph view": graph_view_cli.run,
    }
