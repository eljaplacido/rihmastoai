"""The knowledge graph's nodes and edges as a person reads them (kernel/graph_view.py; FR-GRV1).

`collect` turns one built graph (kernel/graph.py, already narrowed to an audience) into view nodes and
edges: each node with its kind, its family, a short id, a label, a state (open, closed or superseded, or
none for a kind with no lifecycle), its ledger sequence number and time, the record that holds it, the
cockpit route that opens that record, and the issues found on it:

- **untested**: a requirement in force none of whose criteria a test or a holdout checks;
- **criterion_untested**: a test criterion of a requirement in force that no test names;
- **orphan_test**: a test that checks no criterion;
- **overturned**: a decision whose approval went stale or that a later change invalidated;
- **refuted_basis**: a requirement in force derived from a question whose assumption was refuted;
- **broken_link** and **ambiguous**: the graph's own findings (a link to a record that does not exist; an
  id an amendment restated).

Only the fields named in DETAIL_KEYS reach the view. A label that looks like a credential is replaced, and
nothing here reads the holdout custody: the graph never holds a scenario's content.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import quote

from kernel.graph import Graph

FACTORY_PID = "_factory"
FAMILIES = (
    ("asked", "What was asked and agreed", ("request", "question", "assumption", "requirement", "criterion")),
    ("decided", "Who decided, and what changed", ("card", "decision", "comment", "signal", "observation", "person")),
    ("built", "What was built and checked", ("task", "round", "model", "revision", "test", "holdout_ref", "release",
                                             "pack")),
)
FAMILY_OF = {kind: fid for fid, _, kinds in FAMILIES for kind in kinds}
# The order a crowded slice keeps nodes in, after the focus and the nodes with issues: the trace first.
KIND_ORDER = ("requirement", "criterion", "test", "holdout_ref", "task", "question", "assumption", "decision", "card",
              "release", "request", "pack", "comment", "signal", "observation", "person", "round", "revision", "model")
DETAIL_KEYS = ("rid", "version", "plain", "status", "criterion_kind", "check", "card", "card_kind", "triage_class",
               "verdict", "approving", "person", "persona", "number", "maturity", "state", "reached", "name", "task",
               "round", "perspective", "due", "blocking", "channel", "provenance", "criterion", "verdicts",
               "in_contract")
ISSUES = {
    "untested": ("warning", "No test checks this requirement: none of its criteria is checked by a test or a holdout."),
    "criterion_untested": ("warning", "No test names this criterion yet."),
    "orphan_test": ("warning", "This test checks no criterion of the contract."),
    "overturned": ("critical", "This decision no longer holds: a later change made its approval stale."),
    "refuted_basis": ("critical", "This requirement rests on an assumption a person refuted."),
    "broken_link": ("critical", "A link from this record names a record that does not exist."),
    "ambiguous": ("critical", "An amendment restated this id: an old link to it is ambiguous."),
}
HIDDEN_LABEL = "[hidden: it looks like a credential]"
CLOSED_TASK = ("merged", "done", "accepted", "skipped", "cancelled", "closed")
CLOSED_RELEASE = ("done", "failed", "rolled_back", "superseded")
_SECRETISH = re.compile(r"(?i)(token|secret|passw|api[_-]?key|bearer|authorization|private[_-]?key)\s*[=:]")


def clean(text: Any) -> str:
    """A label as it may be shown: the text, or a note in its place when it looks like a credential."""
    s = str(text or "")
    if not s:
        return ""
    if _SECRETISH.search(s):
        return HIDDEN_LABEL
    from kernel.material_kinds import secret_in_text

    return HIDDEN_LABEL if secret_in_text("graph-label.txt", s) else s


def short_id(n: dict[str, Any]) -> str:
    """The id a person reads: R-1 v2, R-1-AC-1, a test's name, a person's name, Release 3."""
    kind = n["kind"]
    if kind == "requirement":
        return f"{n.get('rid')} v{n.get('version')}"
    if kind == "criterion":
        return str(n.get("plain") or n["id"])
    if kind in ("test", "person", "model"):
        return str(n.get("name") or n["id"].split(":", 1)[-1])
    if kind == "release":
        return f"Release {n.get('number')}"
    if kind == "pack":
        return f"Pack {n.get('version')}"
    if kind == "round":
        return f"{n.get('task')} run" + (f" {n['round']}" if n.get("round") is not None else f" at {n.get('since')}")
    if kind == "revision":
        return str(n.get("sha") or n["id"])[:12]
    return str(n["id"])


def _label(n: dict[str, Any]) -> str:
    kind = n["kind"]
    if n.get("label"):
        return str(n["label"])
    if kind == "card":
        triage = f", triaged as {str(n['triage_class']).replace('_', ' ')}" if n.get("triage_class") else ""
        return f"{str(n.get('card_kind') or 'a').replace('_', ' ')} card{triage}"
    if kind == "decision":
        by = f" by {n['person']}" if n.get("person") else ""
        return f"{n.get('verdict')} on {n.get('card')}{by}"
    if kind == "release":
        return f"{n.get('state') or 'started'}, {n.get('maturity') or 'no maturity'}"
    if kind == "holdout_ref":
        return f"a held-out check of {n.get('criterion')}"
    if kind == "comment":
        return f"a comment on a {n.get('target_kind') or 'record'}"
    return short_id(n)


def _in_force(graph: Graph, nid: str) -> bool:
    n = graph.nodes.get(nid) or {}
    return n.get("kind") == "requirement" and graph.current(str(n.get("rid"))) == nid


def _overturned(graph: Graph, nid: str, n: dict[str, Any]) -> bool:
    return graph.stale(n) or bool(graph.out_edges(nid, "invalidated_by"))


def _criterion_state(graph: Graph, nid: str) -> str:
    parents = [e["from"] for e in graph.in_edges(nid, "has_criterion")]
    return "open" if not parents or any(_in_force(graph, p) for p in parents) else "superseded"


# How each kind with a lifecycle reads its state: open, closed or superseded.
STATE_OF: dict[str, Any] = {
    "task": lambda g, nid, n: "closed" if n.get("status") in CLOSED_TASK else "open",
    "question": lambda g, nid, n: "open" if n.get("status") in (None, "open") else "closed",
    "card": lambda g, nid, n: "open" if n.get("state") == "open" else "closed",
    "release": lambda g, nid, n: "closed" if n.get("state") in CLOSED_RELEASE else "open",
    "requirement": lambda g, nid, n: "open" if _in_force(g, nid) else "superseded",
    "assumption": lambda g, nid, n: {"refuted": "superseded", "confirmed": "closed"}.get(str(n.get("status")), "open"),
    "decision": lambda g, nid, n: "superseded" if _overturned(g, nid, n) else "closed",
    "criterion": lambda g, nid, n: _criterion_state(g, nid),
}


def _state(graph: Graph, nid: str, n: dict[str, Any]) -> str | None:
    """open, closed or superseded; None for a kind with no lifecycle (a test, a person, a model)."""
    read = STATE_OF.get(n["kind"])
    return read(graph, nid, n) if read else None


def _live_requirements(graph: Graph) -> set[str]:
    return {nid for nid in graph.nodes if _in_force(graph, nid)}


def _refuted_basis(graph: Graph, live: set[str]) -> set[str]:
    out: set[str] = set()
    for nid in live:
        for source in graph.out_edges(nid, "derived_from"):
            for assumed in graph.out_edges(source["to"], "assumed_as"):
                if graph.nodes.get(assumed["to"], {}).get("status") == "refuted":
                    out.add(nid)
    return out


def _finding_issues(graph: Graph, out: dict[str, list[str]]) -> None:
    for f in graph.parts.findings:
        if f.get("kind") == "dangling_ref" and f.get("source") in graph.nodes:
            out[str(f["source"])].append("broken_link")
        elif f.get("kind") == "ambiguous_after_amendment":
            for nid in f.get("nodes") or []:
                if nid in graph.nodes:
                    out[nid].append("ambiguous")


def _untested(graph: Graph, live: set[str], out: dict[str, list[str]]) -> None:
    """A requirement in force none of whose criteria anything checks, and each test criterion no test names."""
    checked = {e["from"] for e in graph.edges if e["rel"] == "checked_by" and e["origin"] != "model_proposed"}
    for nid in live:
        crits = [e["to"] for e in graph.out_edges(nid, "has_criterion")]
        if not any(c in checked for c in crits):
            out[nid].append("untested")
        for c in crits:
            n = graph.nodes.get(c, {})
            if c not in checked and n.get("criterion_kind", "test") == "test" and n.get("check", "test") == "test":
                out[c].append("criterion_untested")


def issues_of(graph: Graph) -> dict[str, list[str]]:
    """The issues on each node, by node id (ISSUES says what each one means)."""
    out: dict[str, list[str]] = defaultdict(list)
    checking = {e["to"] for e in graph.edges if e["rel"] == "checked_by"}
    live = _live_requirements(graph)
    _untested(graph, live, out)
    for nid, n in graph.nodes.items():
        if n["kind"] == "test" and nid not in checking:
            out[nid].append("orphan_test")
        elif n["kind"] == "decision" and _overturned(graph, nid, n):
            out[nid].append("overturned")
    for nid in _refuted_basis(graph, live):
        out[nid].append("refuted_basis")
    _finding_issues(graph, out)
    return {k: sorted(set(v)) for k, v in out.items()}


def href(pid: str, n: dict[str, Any]) -> str | None:
    """The cockpit route that opens the record a node stands for, or None (a person, a model)."""
    kind, q = n["kind"], (lambda x: quote(str(x), safe=""))
    base = f"#/p/{q(pid)}/"
    if pid == FACTORY_PID:
        if kind in ("card", "decision"):
            return base + "inbox/" + q(n.get("card") if kind == "decision" else n["id"])
        return "#/square" if kind in ("signal", "observation") else base + "ledger"
    focus = {"requirement": ("spec", n.get("rid")), "criterion": ("spec", n.get("plain")),
             "holdout_ref": ("spec", n.get("criterion")), "task": ("tasks", n["id"]), "round": ("tasks", n.get("task")),
             "question": ("questions", n["id"]), "assumption": ("assumptions", n["id"]), "card": ("inbox", n["id"]),
             "decision": ("inbox", n.get("card")), "release": ("releases", None), "pack": ("releases", None),
             "request": ("overview", None), "comment": ("spec", None), "test": ("spec", None), "model": ("cell", None),
             "revision": ("cell", None)}
    if kind in ("signal", "observation"):
        return "#/square"
    view = focus.get(kind)
    if view is None:
        return None
    return base + view[0] + (f"/{q(view[1])}" if view[1] else "")


def _detail(n: dict[str, Any]) -> dict[str, Any]:
    out = {k: n[k] for k in DETAIL_KEYS if n.get(k) not in (None, "", [], {})}
    if "provenance" in out and not isinstance(out["provenance"], (str, int)):
        out["provenance"] = clean(str(out["provenance"])[:200])
    return out


def _aliases(n: dict[str, Any], state: str | None) -> list[str]:
    """The plain ids a person may write for a node: a requirement in force by its id, a criterion by its id,
    a test by its name, a release by its number."""
    kind = n["kind"]
    if kind == "requirement" and state == "open":
        return [str(n.get("rid"))]
    if kind == "criterion":
        return [str(n.get("plain"))]
    if kind in ("test", "person", "model") and n.get("name"):
        return [str(n["name"])]
    return [str(n.get("number"))] if kind == "release" else []


def collect(graph: Graph, pid: str, title: str, times: dict[int, str], *, prefix: bool) -> dict[str, Any]:
    """One graph's view nodes and edges. With ``prefix`` (a view across projects) every id is <pid>/<id>."""
    vid = (lambda nid: f"{pid}/{nid}") if prefix else (lambda nid: nid)
    issues = issues_of(graph)
    nodes: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for nid, n in graph.nodes.items():
        state, shown = _state(graph, nid, n), short_id(n)
        label = clean(_label(n))
        seq = n.get("since") if isinstance(n.get("since"), int) else None
        nodes[vid(nid)] = {"id": vid(nid), "node": nid, "kind": n["kind"], "family": FAMILY_OF.get(n["kind"], "other"),
                           "short": shown, "label": label, "state": state, "seq": seq,
                           "at": times.get(seq) if seq is not None else None, "record": str(n.get("record") or ""),
                           "href": href(pid, n), "issues": issues.get(nid, []), "detail": _detail(n), "pid": pid,
                           "project": title, "_text": f"{nid} {shown} {label} {n['kind']}".lower()}
        for alias in _aliases(n, state):
            aliases.setdefault(vid(alias), vid(nid))
        aliases[vid(nid)] = vid(nid)
    edges = [{"from": vid(e["from"]), "to": vid(e["to"]), "rel": e["rel"], "origin": e["origin"], "by": e.get("by"),
              "proposed": e["origin"] == "model_proposed", "ended": e.get("valid_to") is not None}
             for e in graph.edges if e["from"] in graph.nodes and e["to"] in graph.nodes]
    return {"nodes": nodes, "edges": edges, "aliases": aliases}
