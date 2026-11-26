"""The knowledge graph as a view: one project's records, or every project's, filtered (docs/guides/knowledge-graph.md;
FR-GRV1).

A read model over kernel/graph.py, which rebuilds the graph from the records on every read; nothing here
writes. ``project_view`` and ``factory_view`` give the nodes and edges the ontology defines (kernel/ontology.json),
each node with its kind, label, state, time and record (kernel/graph_view_nodes.py), narrowed by ``Filters``:

- **kinds** and **relations** (rels): only these node kinds, only these edge kinds;
- **states**: open, closed or superseded (a kind with no lifecycle, such as a test or a person, always passes);
- **window**: the records of the last 24 hours, 7, 30 or 90 days (a node with no time of its own passes);
- **q**: words in the id, the short id, the label or the kind;
- **focus** and **hops**: one node and what lies within that many links of it, in either direction;
- **issues**: only the nodes with an issue (a requirement no test checks, a decision overturned...);
- **projects** (across projects only) and **audience** (the ontology's: person, assistant, verifier, builder).

A slice larger than ``limit`` keeps the focus first, then the nodes with issues, then the kinds of the trace
(requirements, criteria, tests), newest first, and says honestly how many more are not shown, by kind. A graph
that cannot be measured now (kernel/graph.py: its records disagree with the ledger) shows no nodes and names why.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from kernel.graph import Graph, build
from kernel.graph_view_nodes import FAMILIES, ISSUES, KIND_ORDER, collect
from kernel.ontology import load

STATES = ("open", "closed", "superseded")
WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90),
           "all": None}
AUDIENCES = ("person", "assistant", "verifier", "builder")
DEFAULT_LIMIT, MAX_LIMIT, MAX_HOPS, MAX_PROJECTS = 300, 2000, 4, 40
NOUNS = {"criterion": ("criterion", "criteria"), "holdout_ref": ("held-out check", "held-out checks"),
         "person": ("person", "people"), "request": ("request", "requests")}
LABELS = {"holdout_ref": "Held-out check", "round": "Agent run"}     # where the ontology's label is a code name


@dataclass(frozen=True)
class Filters:
    """What a view shows. The defaults show everything, up to DEFAULT_LIMIT nodes."""

    kinds: tuple[str, ...] = ()
    rels: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    window: str = "all"
    q: str = ""
    focus: str = ""
    hops: int = 1
    issues: bool = False
    limit: int = DEFAULT_LIMIT
    projects: tuple[str, ...] = ()
    audience: str = "person"

    def as_dict(self) -> dict[str, Any]:
        return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(self).items()}

    def query(self) -> str:
        """The filters as a route's query string, only what differs from the defaults: kinds=a,b&focus=R-1."""
        base = Filters()
        out: dict[str, str] = {}
        for k, v in asdict(self).items():
            if v == getattr(base, k):
                continue
            out[k] = ",".join(v) if isinstance(v, tuple) else ("1" if v is True else str(v))
        return urlencode(out, safe=",@:/")


def _listed(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return [str(x).strip() for x in items if str(x).strip()]


def _choose(name: str, given: list[str], allowed: Any) -> tuple[str, ...]:
    bad = [g for g in given if g not in allowed]
    if bad:
        raise ValueError(f"{name}: {', '.join(bad[:5])} is not one of {', '.join(sorted(allowed))}")
    return tuple(dict.fromkeys(given))


def _number(query: Mapping[str, Any], name: str, default: int, top: int) -> int:
    raw = query.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(str(raw))
    except ValueError:
        raise ValueError(f"{name} is a whole number") from None
    if not 0 <= value <= top:
        raise ValueError(f"{name} is between 0 and {top}")
    return value


def parse_filters(query: Mapping[str, Any]) -> Filters:
    """Filters from a request's query (or a saved preset): unknown kinds, relations or states are refused
    (ValueError), as are a window, hops or limit out of range. Parameters it does not know are ignored."""
    onto = load()
    window = str(query.get("window") or "all")
    if window not in WINDOWS:
        raise ValueError(f"window is one of {', '.join(WINDOWS)}")
    audience = str(query.get("audience") or "person")
    if audience not in AUDIENCES:
        raise ValueError(f"audience is one of {', '.join(AUDIENCES)}")
    projects = tuple(p for p in _listed(query.get("projects")) if p)[:MAX_PROJECTS]
    return Filters(kinds=_choose("kinds", _listed(query.get("kinds")), onto.kinds),
                   rels=_choose("rels", _listed(query.get("rels")), onto.relations),
                   states=_choose("states", _listed(query.get("states")), STATES), window=window,
                   q=str(query.get("q") or "").strip()[:200], focus=str(query.get("focus") or "").strip()[:200],
                   hops=max(1, _number(query, "hops", 1, MAX_HOPS)),
                   issues=str(query.get("issues") or "") in ("1", "true"),
                   limit=max(1, _number(query, "limit", DEFAULT_LIMIT, MAX_LIMIT)), projects=projects,
                   audience=audience)


# -- choosing the slice ------------------------------------------------------------------------------------

def _since(window: str, now: datetime) -> str | None:
    span = WINDOWS[window]
    return None if span is None else (now - span).strftime("%Y-%m-%dT%H:%M:%SZ")


def _passes(n: dict[str, Any], f: Filters, since: str | None, words: list[str]) -> bool:
    if f.kinds and n["kind"] not in f.kinds:
        return False
    if f.states and n["state"] is not None and n["state"] not in f.states:
        return False
    if since and n["at"] and str(n["at"]) < since:
        return False
    if f.issues and not n["issues"]:
        return False
    return all(w in n["_text"] for w in words)


def _near(focus: str, edges: list[dict[str, Any]], hops: int) -> dict[str, int]:
    """Every node within ``hops`` links of the focus, in either direction, with its distance."""
    both: dict[str, list[str]] = {}
    for e in edges:
        both.setdefault(e["from"], []).append(e["to"])
        both.setdefault(e["to"], []).append(e["from"])
    dist, queue = {focus: 0}, deque([focus])
    while queue:
        at = queue.popleft()
        if dist[at] >= hops:
            continue
        for other in both.get(at, []):
            if other not in dist:
                dist[other] = dist[at] + 1
                queue.append(other)
    return dist


def _rank(n: dict[str, Any], dist: dict[str, int]) -> tuple[Any, ...]:
    kind = KIND_ORDER.index(n["kind"]) if n["kind"] in KIND_ORDER else len(KIND_ORDER)
    return (dist.get(n["id"], 99), 0 if n["issues"] else 1, kind, -(n["seq"] if n["seq"] is not None else -1), n["id"])


def noun(kind: str, count: int) -> str:
    """A kind as a word, singular or plural: 1 criterion, 3 criteria, 2 held-out checks."""
    one, many = NOUNS.get(kind, (kind.replace("_", " "), kind.replace("_", " ") + "s"))
    return f"{count} {one if count == 1 else many}"


def _more(dropped: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not dropped:
        return None
    by_kind = Counter(n["kind"] for n in dropped)
    parts = ", ".join(noun(k, c) for k, c in by_kind.most_common())
    return {"count": len(dropped), "by_kind": dict(by_kind),
            "note": f"{len(dropped)} more not shown ({parts}). Narrow the filters or focus on a node to see them."}


Kept = tuple[set[str], str | None, dict[str, int], list[dict[str, Any]]]


def _kept(found: dict[str, Any], f: Filters, now: datetime) -> Kept:
    """The node ids the filters keep, the focus and each kept node's distance from it, and the edges kept."""
    edges = [e for e in found["edges"] if not f.rels or e["rel"] in f.rels]
    since, words = _since(f.window, now), f.q.lower().split()
    keep = {k for k, n in found["nodes"].items() if _passes(n, f, since, words)}
    focus = found["aliases"].get(f.focus) if f.focus else None
    if focus is None:
        return keep, None, {}, edges
    dist = _near(focus, edges, f.hops)
    return (keep & set(dist)) | {focus}, focus, dist, edges


def _shown(n: dict[str, Any], dist: dict[str, int]) -> dict[str, Any]:
    out = {k: v for k, v in n.items() if not k.startswith("_")}
    return out | {"distance": dist[n["id"]]} if dist else out


def _kinds(nodes: dict[str, dict[str, Any]], keep: set[str]) -> list[dict[str, Any]]:
    totals, matching = Counter(n["kind"] for n in nodes.values()), Counter(nodes[k]["kind"] for k in keep)
    return [{"id": k, "label": LABELS.get(k, v.get("label", k).split("@")[0]), "total": totals.get(k, 0),
             "matching": matching.get(k, 0)} for k, v in load().kinds.items()]


def select(found: dict[str, Any], f: Filters, *, now: datetime) -> dict[str, Any]:
    """The slice of collected nodes and edges the filters keep, at most ``f.limit`` nodes."""
    nodes = found["nodes"]
    keep, focus, dist, edges = _kept(found, f, now)
    ranked = sorted((nodes[k] for k in keep), key=lambda n: _rank(n, dist))
    shown, dropped = ranked[:f.limit], ranked[f.limit:]
    ids = {n["id"] for n in shown}
    out_edges = [e for e in edges if e["from"] in ids and e["to"] in ids]
    return {"nodes": [_shown(n, dist) for n in shown], "edges": out_edges, "focus": focus,
            "focus_missing": bool(f.focus) and focus is None, "more": _more(dropped),
            "counts": {"nodes": len(nodes), "matching": len(keep), "shown": len(shown), "edges": len(out_edges)},
            "kinds": _kinds(nodes, keep),
            "relations": [{"id": r, "label": v.get("label", r)} for r, v in load().relations.items()],
            "issues": _issue_counts(nodes, keep)}


def _issue_counts(nodes: dict[str, dict[str, Any]], keep: set[str]) -> list[dict[str, Any]]:
    counted = Counter(i for k in keep for i in nodes[k]["issues"])
    return [{"id": i, "severity": sev, "text": text, "count": counted[i]} for i, (sev, text) in ISSUES.items()
            if counted[i]]


# -- the views ----------------------------------------------------------------------------------------------

def _times(project: Any) -> dict[int, str]:
    out: dict[int, str] = {}
    for rec in project.ledger().records():
        event = rec.get("event") if isinstance(rec, dict) else None
        if isinstance(event, dict) and isinstance(rec.get("seq"), int) and event.get("at"):
            out[rec["seq"]] = str(event["at"])
    return out


def _now(factory: Any) -> datetime:
    clock = getattr(factory, "clock", None)
    now = clock.now() if clock is not None else datetime.now(UTC)
    return now if now.tzinfo else now.replace(tzinfo=UTC)


def _shell(scope: str, f: Filters) -> dict[str, Any]:
    return {"scope": scope, "filters": f.as_dict(), "route_query": f.query(),
            "families": [{"id": fid, "label": label, "kinds": list(kinds)} for fid, label, kinds in FAMILIES],
            "states": list(STATES), "windows": list(WINDOWS), "audiences": list(AUDIENCES),
            "issue_kinds": [{"id": i, "severity": s, "text": t} for i, (s, t) in ISSUES.items()]}


def _gathered(project: Any, f: Filters, graph: Graph | None, prefix: bool) -> tuple[dict[str, Any] | None, list[str]]:
    """One project's collected nodes, or the causes that keep its graph from being measured now."""
    seen = (graph or build(project)).view(f.audience)
    causes = seen.unmeasured()
    if causes:
        return None, causes
    return collect(seen, project.pid, str(project.meta.get("title") or project.pid), _times(project), prefix=prefix), []


def project_view(project: Any, f: Filters, *, graph: Graph | None = None) -> dict[str, Any]:
    """One project's knowledge graph, filtered: answered, or not_measured with the causes and no nodes."""
    out = _shell("project", f) | {"project": project.pid, "title": project.meta.get("title") or project.pid}
    found, causes = _gathered(project, f, graph, prefix=False)
    if found is None:
        return out | {"outcome": "not_measured", "causes": causes, "nodes": [], "edges": [], "more": None}
    return out | select(found, f, now=_now(project.factory)) | {"outcome": "answered", "causes": []}


def factory_view(factory: Any, f: Filters, *, visible: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """Every project's knowledge graph in one view (ids are <pid>/<id>), only the projects ``visible`` lets the
    person see (access enforced: those they hold a persona on), and only ``f.projects`` when it names some."""
    merged: dict[str, Any] = {"nodes": {}, "edges": [], "aliases": {}}
    projects, unmeasured = [], []
    for p in factory.projects():
        if (f.projects and p.pid not in f.projects) or (visible is not None and not visible(p.pid)):
            continue
        projects.append({"id": p.pid, "title": p.meta.get("title") or p.pid})
        if len(projects) > MAX_PROJECTS:
            break
        found, causes = _gathered(p, f, None, prefix=True)
        if found is None:
            unmeasured.append({"project": p.pid, "causes": causes})
            continue
        merged["nodes"].update(found["nodes"])
        merged["edges"] += found["edges"]
        merged["aliases"].update(found["aliases"])
    body = select(merged, f, now=_now(factory))
    return _shell("factory", f) | body | {"outcome": "answered", "causes": [], "projects": projects[:MAX_PROJECTS],
                                          "unmeasured": unmeasured}


def with_focus(f: Filters, node: str, hops: int = 1) -> Filters:
    """The same filters, focused on one node."""
    return replace(f, focus=node, hops=max(1, min(MAX_HOPS, hops)))
