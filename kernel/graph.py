"""The knowledge graph: a read model of one project's records (docs/knowledge-graph.md; FR-KG1).

Rihmasto's records already link to each other: requirements to the questions they rest on, criteria
to the tests that name them, decisions to the cards they decide and the requirements they rest on,
releases to the requirements they carry. The graph makes those links explicit, as the ontology
(kernel/ontology.json) declares them. It is never a store and never a second source of truth:
`build(project)` rebuilds it from the ledger and the record files every time it is read
(kernel/graph_build.py), and nothing is written.

- **Edges.** Every edge carries an origin (kernel, convention, model_proposed or person_confirmed), a
  validity window in ledger sequence numbers (``valid_from``, and ``valid_to`` once a later event ended
  it, such as a stale mark) and a ``by`` pointer to the record that holds the link.
- **Stamp.** Every graph is stamped with the ontology's version and hash, the ledger's head, the
  product's main revision and the sha256 of every source file read. Before it answers, a graph checks
  its stamp: if a file changed since (questions.json and tasks.json change without a ledger event),
  the ledger moved, or the ledger's hash chain is broken, the answer is ``not_measured`` and names the
  cause. It is never silently wrong.
- **Queries.** ``trace`` (upstream), ``impact`` (downstream), ``path``, ``as_of`` and ``check``. Every
  step of an answer cites the record that holds its link, and every answer ends in one of four
  outcomes: answered, ambiguous, not_found or not_measured. Edges a model proposed come back
  separately (``proposed``), are never walked through, and never feed a write path.
- **Check** validates a built graph against closed-world rules, the native counterpart of SHACL. It
  only reports: it never blocks anything.

The graph never reads the holdout custody (kernel/custody.py says how its verdicts are read).
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kernel.ontology import Ontology

STEP_KEYS = ("from", "rel", "to", "by", "origin", "valid_from", "valid_to")
# The kind of record each file holds, so an audience's view keeps only the findings about records it may
# see. The spec, the contract, the tasks, the request and main hold records every audience sees; a pointer
# into any other file is kept only for an audience that sees every kind.
OPEN_RECORDS = ("spec.json", "spec.v", "contract.json", "tasks.json", "source.json", "project.json", "repo.git")
RECORD_KINDS = (("canon/inbox/", "card"), ("canon/decisions.json", "decision"), ("canon/comments.json", "comment"),
                ("canon/questions.json", "question"), ("canon/assumptions.json", "assumption"),
                ("releases/", "release"), ("packs.json", "pack"), ("ledger.jsonl", "round"),
                ("_factory/signals.json", "signal"), ("signals.json", "signal"), ("refs.", "card"))


def record_kind(pointer: str) -> str | None:
    """The kind of record a ``by`` or ``record`` pointer names: None for a record every audience sees,
    and "" for one this map does not know."""
    name = str(pointer).split("#", 1)[0]
    if name.startswith(OPEN_RECORDS):
        return None
    return next((kind for prefix, kind in RECORD_KINDS if name.startswith(prefix)), "")


@dataclass
class Parts:
    """What a build produces: the nodes and edges, what it found, what keeps it from being measured,
    its stamp, and the indexes from a plain id (R-1, R-1-AC-2) to its nodes."""

    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    stamp: dict[str, Any] = field(default_factory=dict)
    plain: dict[str, list[str]] = field(default_factory=dict)
    duplicates: dict[str, list[str]] = field(default_factory=dict)


def stamp_changes(before: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """Why a graph built under ``before`` no longer describes the records as they are ``now``."""
    causes: list[str] = []
    if before.get("ontology") != now.get("ontology"):
        causes.append("kernel/ontology.json changed since the graph was built")
    was, is_now = before.get("ledger") or {}, now.get("ledger") or {}
    moved = was != is_now
    if moved:
        causes.append(f"the ledger moved from seq {was.get('seq')} to seq {is_now.get('seq')} "
                      "since the graph was built")
    if before.get("main") != now.get("main"):
        causes.append("the product's main moved since the graph was built")
    files_before, files_now = before.get("files") or {}, now.get("files") or {}
    for name in sorted(set(files_before) | set(files_now)):
        if files_before.get(name, "absent") != files_now.get(name, "absent"):
            causes.append(f"{name} changed since the graph was built" + ("" if moved else ", with no ledger event"))
    return causes


def build(project: Any) -> Graph:
    """The project's graph, rebuilt from its records now (kernel/graph_build.py)."""
    from kernel.graph_build import build as build_graph

    return build_graph(project)


class Graph:
    """One project's graph, as built at its stamp, or as of a ledger sequence number."""

    def __init__(self, project: Any, onto: Ontology, parts: Parts, restamp: Callable[[], dict[str, Any]],
                 as_of: int | None = None, audience: str | None = None):
        self.project, self.onto, self.parts, self._restamp = project, onto, parts, restamp
        self.as_of_seq, self.audience = as_of, audience
        self.nodes, self.edges = parts.nodes, parts.edges
        self.stamp = parts.stamp
        self._index()

    def _index(self) -> None:
        self._up: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
        self._down: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
        self._out: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self._in: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for e in self.edges:
            up, down = (e["to"], e["from"]) if self.onto.upstream_is_to(e["rel"]) else (e["from"], e["to"])
            self._up[down].append((e, up))
            self._down[up].append((e, down))
            self._out[(e["from"], e["rel"])].append(e)
            self._in[(e["to"], e["rel"])].append(e)

    # -- reading the graph ---------------------------------------------------------------------------

    def out_edges(self, node: str, rel: str) -> list[dict[str, Any]]:
        return list(self._out.get((node, rel), []))

    def in_edges(self, node: str, rel: str) -> list[dict[str, Any]]:
        return list(self._in.get((node, rel), []))

    def ordered(self, kind: str) -> list[str]:
        """The nodes of one kind, in the order their records hold them."""
        return sorted((n for n, v in self.nodes.items() if v["kind"] == kind),
                      key=lambda n: (self.nodes[n].get("n", 0), n))

    def node(self, node_id: str) -> dict[str, Any]:
        return dict(self.nodes[node_id])

    def current(self, rid: str) -> str | None:
        """The version node of a requirement in force (now, or as of this graph's sequence number)."""
        found = None
        for nid in self.parts.plain.get(rid, []):
            n = self.nodes.get(nid)
            if n is None or n["kind"] != "requirement":
                continue
            s = self.as_of_seq
            begun = s is None or n.get("since") is None or n["since"] <= s
            if begun and (s is None or n.get("until") is None or n["until"] > s):
                found = nid
        return found

    def versions(self, rid: str) -> list[str]:
        return [n for n in self.parts.plain.get(rid, []) if n in self.nodes]

    def stale(self, decision: dict[str, Any]) -> bool:
        """Whether an approval had gone stale (now, or as of this graph's sequence number), as the
        ledger's approvals_stale mark says: never decisions.json's flag, which a hand can remove."""
        seq = decision.get("stale_seq")
        return seq is not None and (self.as_of_seq is None or seq <= self.as_of_seq)

    def resolve(self, ref: str) -> tuple[str, list[str]]:
        """A reference as people write it, to the nodes it names, with the outcome: answered,
        ambiguous (a duplicated id, or a criterion id an amendment restated) or not_found."""
        ref = str(ref).strip()
        if ref in self.parts.duplicates:
            return "ambiguous", list(self.parts.duplicates[ref])
        for candidate in (ref, f"person:{ref}", f"test:{ref}", f"release-{ref}", f"pack-{ref}"):
            if candidate in self.nodes:
                return "answered", [candidate]
        versions = self.versions(ref)
        if not versions:
            return "not_found", []
        if self.nodes[versions[0]]["kind"] == "requirement":
            current = self.current(ref)
            return ("answered", [current]) if current else ("not_found", [])
        return ("answered", versions) if len(versions) == 1 else ("ambiguous", versions)

    # -- answers -------------------------------------------------------------------------------------

    def unmeasured(self) -> list[str]:
        """Why this graph cannot answer now: a broken ledger chain, records that disagree with the
        ledger, an invalid ontology, or records that changed since it was built. Empty when it can. The
        causes name records, so an audience that may not see every kind is told only that there are some."""
        causes = list(self.parts.problems) + stamp_changes(self.stamp, self._restamp())
        if causes and self.audience is not None and not self._sees_every_kind(self.audience):
            return [f"the records cannot be measured now; the causes name records the {self.audience} audience "
                    "may not see, and a person's view names them"]
        return causes

    def query_of(self, name: str, ids: list[str], **extra: Any) -> dict[str, Any]:
        return {"query": name, "ids": list(ids), "as_of": self.as_of_seq, **extra}

    def answer(self, query: dict[str, Any], outcome: str, **body: Any) -> dict[str, Any]:
        """An answer: the query, the stamp, what was found, and the outcome last."""
        out = {"query": query, "stamp": self.stamp, **body}
        out["outcome"] = outcome
        return out

    def not_measured(self, query: dict[str, Any], causes: list[str]) -> dict[str, Any]:
        return self.answer(query, "not_measured", causes=causes)

    def unresolved(self, query: dict[str, Any], outcome: str, refs: list[str], candidates: list[str]) -> dict[str, Any]:
        if outcome == "ambiguous":
            return self.answer(query, outcome, candidates=[self.node(c) for c in candidates if c in self.nodes])
        return self.answer(query, "not_found", missing=list(refs))

    @staticmethod
    def step(e: dict[str, Any]) -> dict[str, Any]:
        out = {k: e.get(k) for k in STEP_KEYS}
        if "persona" in e:
            out["persona"] = e["persona"]
        return out

    def cite(self, steps: list[dict[str, Any]], proposed: list[dict[str, Any]]) -> dict[str, Any]:
        """Steps, the model's proposals apart, and every record they rest on."""
        return {"steps": [self.step(e) for e in steps], "proposed": [self.step(e) for e in proposed],
                "cites": sorted({e["by"] for e in steps + proposed})}

    # -- the queries ---------------------------------------------------------------------------------

    def walk(self, starts: list[str], *, upstream: bool) -> tuple[list[str], list[dict], list[dict]]:
        """Breadth first from ``starts``, upstream (provenance) or downstream (what rests on them). An
        edge a model proposed is reported and never walked through."""
        index = self._up if upstream else self._down
        seen, queue = set(starts), deque(starts)
        reached: list[str] = []
        steps: list[dict[str, Any]] = []
        proposed: list[dict[str, Any]] = []
        while queue:
            for e, other in index.get(queue.popleft(), []):
                if e["origin"] == "model_proposed":
                    proposed.append(e)
                    continue
                steps.append(e)
                if other not in seen:
                    seen.add(other)
                    reached.append(other)
                    queue.append(other)
        return reached, steps, proposed

    def trace(self, ref: str) -> dict[str, Any]:
        """Upstream: everything the record rests on, back to the people who asked and answered."""
        query = self.query_of("trace", [ref])
        causes = self.unmeasured()
        if causes:
            return self.not_measured(query, causes)
        outcome, ids = self.resolve(ref)
        if outcome != "answered":
            return self.unresolved(query, outcome, [ref], ids)
        reached, steps, proposed = self.walk(ids, upstream=True)
        return self.answer(query, "answered", start=ids, reached=[self.node(n) for n in reached],
                           **self.cite(steps, proposed))

    def impact(self, refs: list[str]) -> dict[str, Any]:
        """Downstream: everything that rests on the records. ``result`` is the change-card view of
        requirement ids (the same fields as kernel.insight.impact): their criteria, the tests on main
        that name them, the tasks that would reopen, the approvals that would go stale and the
        releases that carry them."""
        query = self.query_of("impact", refs)
        causes = self.unmeasured()
        if causes:
            return self.not_measured(query, causes)
        starts: list[str] = []
        missing: list[str] = []
        ambiguous: list[str] = []
        for ref in refs:
            outcome, ids = self.resolve(ref)
            if outcome == "answered":
                starts += [v for i in ids for v in (self.versions(self.nodes[i].get("rid", "")) or [i])]
            elif outcome == "ambiguous":
                ambiguous += ids
            else:
                missing.append(ref)
        reached, steps, proposed = self.walk(sorted(set(starts)), upstream=False)
        body = {"start": sorted(set(starts)), "missing": missing, "result": self.impact_result(refs),
                "reached": [self.node(n) for n in reached], **self.cite(steps, proposed)}
        if ambiguous:
            return self.answer(query, "ambiguous", candidates=[self.node(c) for c in ambiguous], **body)
        return self.answer(query, "answered" if starts else "not_found", **body)

    def _criteria_of(self, known: list[str], current: dict[str, str | None]) -> list[tuple[str, str]]:
        """Each known requirement's criteria as the contract lists them, or (for a version the current
        contract does not hold, as of an earlier sequence number) as its spec version did: (plain id, node)."""
        out: list[tuple[str, str]] = []
        for rid in known:
            edges = self.out_edges(current[rid] or "", "has_criterion")
            listed = [e for e in edges if "contract_n" in e]
            ordered = (sorted(listed, key=lambda e: e["contract_n"]) if listed
                       else sorted(edges, key=lambda e: e.get("n", 0)))
            out += [(self.nodes[e["to"]]["plain"], e["to"]) for e in ordered]
        return out

    def _known(self, rids: list[str], current: dict[str, str | None]) -> list[str]:
        """The requirements the contract holds; as of a sequence number, those whose version was in force."""
        in_force = self.as_of_seq is not None
        return [r for r in rids if current[r] and (in_force or self.nodes[current[r] or ""].get("in_contract"))]

    def _kind(self, node: str) -> str:
        return str(self.nodes[node].get("check") or self.nodes[node].get("criterion_kind") or "test")

    def _tests_of(self, node: str) -> list[str]:
        return sorted(self.nodes[e["to"]]["name"] for e in self.out_edges(node, "checked_by")
                      if self.nodes[e["to"]]["kind"] == "test")

    def _going_stale(self, want: set[str]) -> list[dict[str, Any]]:
        """The approvals Canon.mark_stale would mark for these requirements: approving, not stale yet,
        resting on one of them (or on the release as a whole, a scope nothing in kernel/ writes)."""
        out: list[dict[str, Any]] = []
        for d in (self.nodes[n] for n in self.ordered("decision")):
            rests = want & set(d.get("rids", [])) or d.get("scope") == "release"
            if d.get("approving") and not self.stale(d) and rests:
                out.append({"id": d["id"], "card": d.get("card"), "kind": d.get("card_kind"),
                            "person": d.get("person")})
        return out

    def _carrying(self, want: set[str]) -> list[dict[str, Any]]:
        """The releases that carry one of these requirements, and only those."""
        return [{"release": r["number"], "revision": r.get("revision"), "state": r.get("state")}
                for r in (self.nodes[n] for n in self.ordered("release")) if want & set(r.get("rids", []))]

    def impact_result(self, ids: list[str]) -> dict[str, Any]:
        """The requirement view of an impact, field for field as kernel.insight.impact gives it, except
        that releases are only those that carry the ids."""
        rids = sorted(set(ids))
        current = {r: self.current(r) for r in rids}
        known = self._known(rids, current)
        crits = self._criteria_of(known, current)
        tasks = {e["from"] for _, n in crits for e in self.in_edges(n, "serves")}
        return {"requirements": known, "unknown_requirements": [r for r in rids if r not in known],
                "criteria": [p for p, _ in crits], "kinds": {p: self._kind(n) for p, n in crits},
                "tests": {p: self._tests_of(n) for p, n in crits},
                "tasks_reopened": [t for t in self.ordered("task") if t in tasks],
                "approvals_going_stale": self._going_stale(set(rids)), "releases_carrying": self._carrying(set(rids))}

    def path(self, a: str, b: str) -> dict[str, Any]:
        """The shortest chain of links between two records, in either direction, each step cited."""
        query = self.query_of("path", [a, b])
        causes = self.unmeasured()
        if causes:
            return self.not_measured(query, causes)
        ends = []
        for ref in (a, b):
            outcome, ids = self.resolve(ref)
            if outcome != "answered" or len(ids) != 1:
                return self.unresolved(query, outcome if outcome != "answered" else "ambiguous", [ref], ids)
            ends.append(ids[0])
        chain = self._shortest(ends[0], ends[1])
        if chain is None:
            return self.answer(query, "not_found", missing=[], why=f"no chain of links joins {a} and {b}")
        return self.answer(query, "answered", start=ends, **self.cite(chain, []))

    def _shortest(self, start: str, goal: str) -> list[dict[str, Any]] | None:
        both: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
        for e in self.edges:
            if e["origin"] != "model_proposed":
                both[e["from"]].append((e, e["to"]))
                both[e["to"]].append((e, e["from"]))
        came: dict[str, tuple[dict[str, Any], str] | None] = {start: None}
        queue = deque([start])
        while queue and goal not in came:
            n = queue.popleft()
            for e, other in both.get(n, []):
                if other not in came:
                    came[other] = (e, n)
                    queue.append(other)
        if goal not in came:
            return None
        chain: list[dict[str, Any]] = []
        at = goal
        while (link := came[at]) is not None:
            chain.append(link[0])
            at = link[1]
        return chain[::-1]

    def as_of(self, seq: int) -> Graph:
        """The graph as it stood at a ledger sequence number: the edges valid then, between the
        records that existed then. Tests are read from main as it is now."""
        nodes = {k: v for k, v in self.nodes.items() if v.get("since") is None or v["since"] <= seq}
        edges = [e for e in self.edges if e["from"] in nodes and e["to"] in nodes and e["valid_from"] <= seq
                 and (e.get("valid_to") is None or e["valid_to"] > seq)]
        parts = Parts(nodes, edges, self.parts.findings, self.parts.problems, self.stamp, self.parts.plain,
                      self.parts.duplicates)
        return Graph(self.project, self.onto, parts, self._restamp, as_of=seq, audience=self.audience)

    def view(self, audience: str) -> Graph:
        """The graph as one audience may see it: only the kinds the ontology lets it see, and only the
        findings that name no record or node it may not see."""
        if audience not in (self.onto.data.get("audiences") or {}):
            raise ValueError(f"unknown audience {audience!r}")
        nodes = {k: v for k, v in self.nodes.items() if self.onto.visible_to(v["kind"], audience)}
        edges = [e for e in self.edges if e["from"] in nodes and e["to"] in nodes]
        parts = Parts(nodes, edges, self._findings_for(audience, nodes), self.parts.problems, self.stamp,
                      self.parts.plain, self.parts.duplicates)
        return Graph(self.project, self.onto, parts, self._restamp, as_of=self.as_of_seq, audience=audience)

    def _sees_every_kind(self, audience: str) -> bool:
        return all(self.onto.visible_to(k, audience) for k in self.onto.kinds)

    def _sees_record(self, audience: str, pointer: Any) -> bool:
        kind = record_kind(str(pointer))
        if kind is None:
            return True
        return self.onto.visible_to(kind, audience) if kind else self._sees_every_kind(audience)

    def _finding_seen(self, f: dict[str, Any], audience: str, nodes: dict[str, Any]) -> bool:
        """Whether every node a finding names is one the audience sees (a node the graph does not hold is
        judged by its record), and every record it cites is."""
        edge = f.get("edge") or {}
        named = [f.get("source"), f.get("node"), *(f.get("nodes") or []), edge.get("from"), edge.get("to")]
        cited = [f.get("record"), edge.get("by")]
        return (all(n in nodes or n not in self.nodes for n in named if n)
                and all(self._sees_record(audience, p) for p in cited if p))

    def _findings_for(self, audience: str, nodes: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for f in self.parts.findings:
            if isinstance(f.get("records"), dict):      # one finding over many records: keep the ones it sees
                seen = {p: n for p, n in f["records"].items() if self._sees_record(audience, p)}
                f = {**f, "records": seen} if seen else {}
            if f and self._finding_seen(f, audience, nodes):
                out.append(f)
        return out

    def show(self, audience: str = "person") -> dict[str, Any]:
        """Every node and edge one audience may see, with the findings it may see: the graph rendered whole."""
        view = self.view(audience)
        query = self.query_of("show", [], audience=audience)
        causes = view.unmeasured()
        if causes:
            return self.not_measured(query, causes)
        return self.answer(query, "answered", nodes=[view.node(n) for n in sorted(view.nodes)],
                           edges=[self.step(e) for e in view.edges], findings=list(view.parts.findings))

    # -- check: closed-world rules, reported, never blocking ---------------------------------------

    def _edge_findings(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in self.edges:
            rel = self.onto.relations.get(e["rel"])
            kinds = (self.nodes[e["from"]]["kind"], self.nodes[e["to"]]["kind"])
            allowed = rel is not None and kinds[0] in rel["from"] and kinds[1] in rel["to"]
            if rel is None or not allowed or e["origin"] not in rel["origins"]:
                out.append({"kind": "edge_breaks_ontology", "edge": self.step(e), "kinds": list(kinds)})
            elif not isinstance(e.get("valid_from"), int) or not e.get("by"):
                out.append({"kind": "edge_unstamped", "edge": self.step(e)})
            elif e["origin"] == "model_proposed":
                out.append({"kind": "model_proposed", "edge": self.step(e),
                            "text": f"{e['from']} {e['rel']} {e['to']} is a model's proposal no person has decided"})
        return out

    def _node_findings(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"kind": "unknown_kind", "node": n} for n, v in self.nodes.items()
                                     if v["kind"] not in self.onto.kinds]
        for rid in sorted({v["rid"] for v in self.nodes.values() if v["kind"] == "requirement"}):
            current = self.current(rid)
            if current and not self.out_edges(current, "has_criterion"):
                out.append({"kind": "requirement_without_criterion", "node": current})
        for plain, nodes in sorted(self.parts.plain.items()):
            crits = [n for n in nodes if n in self.nodes and self.nodes[n]["kind"] == "criterion"]
            if len(crits) > 1:
                out.append({"kind": "ambiguous_after_amendment", "id": plain, "nodes": crits,
                            "text": f"{plain} was restated: an old link to it is ambiguous"})
        return out

    def check(self) -> dict[str, Any]:
        """The built graph against the ontology's closed-world rules. It reports; it never blocks."""
        query = self.query_of("check", [])
        causes = self.unmeasured()
        if causes:
            return self.not_measured(query, causes)
        findings = list(self.parts.findings) + self._edge_findings() + self._node_findings()
        return self.answer(query, "answered", blocks=False, nodes=len(self.nodes), edges=len(self.edges),
                           counts=dict(Counter(f["kind"] for f in findings)), findings=findings)
