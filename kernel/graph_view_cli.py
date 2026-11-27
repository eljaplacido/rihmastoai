"""`rihmasto graph view`: the knowledge graph view on the command line, read only (kernel/graph_view.py; FR-GRV1).

    rihmasto graph view <pid> [--kinds requirement,criterion,test] [--states open] [--focus R-1 --hops 2] [--json]
    rihmasto graph view --all [--projects a,b] ...

The same read model the cockpit's Knowledge graph shows, with the same filters. Without --json it prints the
nodes and links as two lists, the issues found, and how many more are not shown. It writes nothing.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from kernel.graph_view import AUDIENCES, STATES, WINDOWS, factory_view, parse_filters, project_view

FILTER_ARGS = ("kinds", "rels", "states", "window", "focus", "hops", "limit", "projects", "audience")


def add_parser(cmds: Any) -> None:
    """`graph view`, beside the other `rihmasto graph` commands (kernel/graph_ask.py)."""
    p = cmds.add_parser("view", help="the knowledge graph view, filtered: nodes, links and issues")
    p.add_argument("pid", nargs="?", help="the project; leave it out with --all")
    p.add_argument("--all", action="store_true", help="every project you may see, in one view")
    p.add_argument("--projects", help="with --all: only these projects (comma separated)")
    p.add_argument("--kinds", help="node kinds, comma separated (kernel/ontology.json): requirement,criterion,test")
    p.add_argument("--rels", help="relations, comma separated, e.g. has_criterion,checked_by")
    p.add_argument("--states", help=f"comma separated: {', '.join(STATES)}")
    p.add_argument("--window", choices=list(WINDOWS), help="only the records of this window")
    p.add_argument("--search", help="words in the id or the label")
    p.add_argument("--focus", help="one node (R-1, T-001, Q-002...) and what lies near it")
    p.add_argument("--hops", type=int, help="with --focus: how many links away (1 to 4)")
    p.add_argument("--issues", action="store_true", help="only the nodes with an issue")
    p.add_argument("--limit", type=int, help="at most this many nodes (default 300)")
    p.add_argument("--audience", choices=list(AUDIENCES), help="the graph as this audience may see it")
    p.add_argument("--json", action="store_true", help="the read model as JSON")


def view(factory: Any, args: Any) -> dict[str, Any]:
    """The read model the command prints. A project and --all together, or neither, is a ValueError."""
    if bool(args.pid) == bool(args.all):
        raise ValueError("name one project, or --all for every project")
    query = {k: getattr(args, k) for k in FILTER_ARGS if getattr(args, k, None) is not None}
    query |= {"q": args.search or "", "issues": "1" if args.issues else ""}
    filters = parse_filters(query)
    return factory_view(factory, filters) if args.all else project_view(factory.project(args.pid), filters)


def _line(n: dict[str, Any], scoped: bool) -> str:
    where = f"{n['pid']}/" if scoped else ""
    flags = f"  [{', '.join(n['issues'])}]" if n["issues"] else ""
    return f"  {where + n['short']:<28} {n['kind']:<12} {n['state'] or '-':<11} {n['label'][:70]}{flags}"


def _head(model: dict[str, Any]) -> list[str]:
    c = model["counts"]
    out = [f"{c['nodes']} nodes, {c['matching']} match the filters, {c['shown']} shown, {c['edges']} links"]
    if model["route_query"]:
        out.append(f"Filters: {model['route_query']}")
    if model.get("focus_missing"):
        out.append(f"No node {model['filters']['focus']} in this graph: the focus is left out.")
    return out + [f"Issue ({i['severity']}, {i['count']}): {i['text']}" for i in model["issues"]]


def _lists(model: dict[str, Any]) -> list[str]:
    scoped = model["scope"] == "factory"
    short = {n["id"]: (f"{n['pid']}/" if scoped else "") + n["short"] for n in model["nodes"]}
    links = [f"  {short[e['from']]} --{e['rel']}--> {short[e['to']]}" + (" (proposed)" if e["proposed"] else "")
             for e in model["edges"]]
    return ["Nodes:"] + [_line(n, scoped) for n in model["nodes"]] + ["Links:"] + links


def text(model: dict[str, Any]) -> str:
    """The read model as a person reads it in a terminal."""
    out = [f"Knowledge graph: {model.get('title') or 'every project'}"]
    if model["outcome"] == "not_measured":
        return "\n".join(out + ["Not measured now:"] + [f"  {cause}" for cause in model["causes"]])
    out += _head(model) + _lists(model)
    if model.get("more"):
        out.append(model["more"]["note"])
    out += [f"Not measured now: {u['project']}: {'; '.join(u['causes'])}" for u in model.get("unmeasured") or []]
    return "\n".join(out)


def run(factory: Any, args: Any) -> int:
    """Print the view (text, or JSON with --json). A filter it refuses is a message on stderr and exit 2."""
    try:
        model = view(factory, args)
    except (ValueError, KeyError) as exc:
        sys.stderr.write(f"rihmasto graph view: {exc.args[0] if exc.args else exc}\n")
        return 2
    sys.stdout.write((json.dumps(model, indent=2, ensure_ascii=False) if args.json else text(model)) + "\n")
    return 0
