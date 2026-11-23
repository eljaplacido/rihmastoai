"""Building the knowledge graph from one project's records (kernel/graph.py; FR-KG1).

Nothing is stored. Every read rebuilds the graph from:
- the ledger, whose hash chain is checked first: when each link began and ended, the stale marks, the
  triage, the builder rounds and the releases;
- the spec snapshots (spec.v<n>.json), spec.json and contract.json, so the provenance an amendment
  overwrote when it replaced a requirement's sources is recovered; tasks.json; and the test names on
  the product's main (this module);
- the canon, the releases, the packs, the rounds and the signals routed here (kernel/graph_records.py).
  Never a card's title, body or payload (only its triage's class and requirements), never a
  decision's reason, never the text of a comment or a signal: outside text never creates an edge.

Every source file is hashed into the stamp, with the ledger's head, main's revision and the
ontology's hash. The holdout custody is never read. Links are collected while the records are read and
resolved at the end, when every node exists: a link to a record that does not exist is a
`dangling_ref` finding, and a link no ledger event places starts at the ledger's head and is reported
(`validity_unplaced`).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from kernel import graph_records
from kernel.graph import Graph, Parts
from kernel.graph_records import CID, FACTORY_PID, RID, At, ids_of, object_of, records_of, signals_name
from kernel.ledger import verify
from kernel.ontology import Ontology, OntologyError, load, validate

SPEC_STARTS = ("spec_written", "as_is_spec_written")
# Sources that name no record: a requirement the analyst proposed, and one observed in an adopted
# project's code (kernel.adopt.OBSERVED). Its provenance says which; nothing upstream links.
UNLINKED_SOURCES = ("proposed", "observed")
VERSION_BUMPS = ("change_applied", "plan_edited", "plan_redone")
RECORDS = ("project.json", "source.json", "spec.json", "contract.json", "tasks.json", "packs.json",
           "canon/questions.json", "canon/assumptions.json", "canon/decisions.json", "canon/comments.json")


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "absent"


def _content(c: dict[str, Any]) -> str:
    """A criterion's content key: the first 12 hex digits of the sha256 of its given, when and then."""
    words = [str(c.get("given") or "-"), str(c.get("when") or "-"), str(c.get("then") or "")]
    return hashlib.sha256(json.dumps(words, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def sources(project: Any) -> dict[str, Path]:
    """Every file the graph reads, by the name its stamp gives it."""
    d = Path(project.dir)
    out = {name: d / name for name in RECORDS}
    out |= {p.name: p for p in sorted(d.glob("spec.v*.json"))}
    out |= {f"canon/inbox/{p.name}": p for p in sorted((d / "canon" / "inbox").glob("C-*.json"))}
    out |= {f"releases/{p.name}": p for p in sorted((d / "releases").glob("*.json")) if p.stem.isdigit()}
    factory = Path(project.factory.projects_dir) / FACTORY_PID
    out[signals_name(project)] = factory / "signals.json"
    return out


def main_revision(project: Any) -> str | None:
    """The product's main, or None when it has no repository yet."""
    repo = Path(project.dir) / "repo.git"
    if not repo.exists():
        return None
    try:
        out = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "main"], cwd=repo, capture_output=True,
                             text=True, check=False)
    except OSError:
        return None
    return out.stdout.strip() or None


def restamp(project: Any) -> dict[str, Any]:
    """The stamp the project's records would get now."""
    try:
        onto = load().stamp()
    except (OSError, OntologyError):
        onto = {"version": "", "sha256": "absent"}
    return {"ontology": onto, "ledger": project.ledger().head(), "main": main_revision(project),
            "files": {name: _sha(path) for name, path in sources(project).items()}}


class Builder:
    """One build: read the sources, make the nodes, collect the links, resolve them at the end."""

    def __init__(self, project: Any, onto: Ontology):
        self.p, self.onto, self.parts = project, onto, Parts()
        self.paths = sources(project)
        self.files: dict[str, str] = {}
        self.first: dict[tuple[str, str, str], int] = {}
        self.events: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        self.by_id: dict[tuple[str, str], dict[str, Any]] = {}
        self.head = -1
        self.ledger_head: dict[str, Any] = {"seq": -1, "hash": None}
        self.starts: dict[int, int | None] = {}
        self.current = 1
        self.pending: list[dict[str, Any]] = []
        self.has_criterion: dict[tuple[str, str], dict[str, Any]] = {}
        self.contract_crit: dict[str, str] = {}
        self.unplaced: list[str] = []
        self.main: str | None = None
        self.questions: list[dict[str, Any]] = []
        self.assumed: list[dict[str, Any]] = []
        self.decided: list[dict[str, Any]] = []
        self.marks: dict[str, tuple[int, dict[str, Any]]] = {}

    # -- reading ---------------------------------------------------------------------------------

    def load(self, name: str, default: Any) -> Any:
        """A source file as JSON, hashed into the stamp; ``default`` when it is absent or unreadable."""
        path = self.paths.get(name)
        try:
            raw = path.read_bytes() if path is not None else None
        except OSError:
            raw = None
        if raw is None:
            self.files[name] = "absent"
            return default
        self.files[name] = hashlib.sha256(raw).hexdigest()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.finding("unreadable_record", record=name)
            return default
        return default if value is None else value

    def ledger(self) -> None:
        records = self.p.ledger().records()
        result = verify(records)
        if not result.intact:
            self.parts.problems.append(f"ledger.jsonl: the hash chain is broken at seq {result.broken_seq}")
        self.head = len(records) - 1
        if records:
            last = records[-1] if isinstance(records[-1], dict) else {}
            self.ledger_head = {"seq": last.get("seq", self.head), "hash": last.get("hash")}
        for rec in records:
            event = rec.get("event") if isinstance(rec, dict) else None
            if isinstance(event, dict) and isinstance(rec.get("seq"), int):
                self._index(rec["seq"], event)

    def _index(self, seq: int, event: dict[str, Any]) -> None:
        fields = self.onto.ledger.get(str(event.get("kind")))
        payload = event.get("payload")
        if fields is None or not isinstance(payload, dict):
            return
        kept = {f: payload.get(f) for f in fields}
        self.events[str(event["kind"])].append((seq, kept))
        for f in fields:
            for v in ids_of(payload.get(f)):
                self.first.setdefault((str(event["kind"]), f, v), seq)
        if "id" in fields:
            self.by_id.setdefault((str(event["kind"]), str(payload.get("id"))), kept)

    def seq(self, kind: str, field: str, value: Any) -> int | None:
        return self.first.get((kind, field, str(value)))

    # -- nodes and links ---------------------------------------------------------------------------

    def finding(self, kind: str, **detail: Any) -> None:
        self.parts.findings.append({"kind": kind, **detail})

    def node(self, nid: str, kind: str, record: str, **attrs: Any) -> dict[str, Any]:
        n = self.parts.nodes.setdefault(nid, {"id": nid, "kind": kind, "record": record})
        n.update({k: v for k, v in attrs.items() if v is not None})
        return n

    def plain(self, pid: str, nid: str) -> None:
        listed = self.parts.plain.setdefault(pid, [])
        if nid not in listed:
            listed.append(nid)

    def person(self, name: str) -> str:
        self.node(f"person:{name}", "person", "the records that name them", name=name, label=name)
        return f"person:{name}"

    def link(self, rel: str, frm: str, to: str | At, origin: str, since: int | None, by: str,
             **attrs: Any) -> dict[str, Any]:
        """A link, resolved when every node exists. One with no ledger event to start it starts at
        the ledger's head, and the build reports it (validity_unplaced)."""
        if since is None:
            self.unplaced.append(by)
            since = max(self.head, 0)
        e = {"rel": rel, "from": frm, "to": to, "origin": origin, "valid_from": since, "valid_to": None, "by": by,
             **{k: v for k, v in attrs.items() if v is not None}}
        self.pending.append(e)
        return e

    def _target(self, at: At) -> str | None:
        """The version of a plain id in force at a sequence number; the latest one when none was."""
        found = [n for n in self.parts.plain.get(at.plain, []) if n in self.parts.nodes]
        if not found:
            return None
        live = [n for n in found if at.seq is None or self.parts.nodes[n].get("since") is None
                or self.parts.nodes[n]["since"] <= at.seq]
        return (live or found)[-1]

    def finish(self) -> None:
        seen: set[tuple[str, str, str, str]] = set()
        for e in self.pending:
            to = self._target(e["to"]) if isinstance(e["to"], At) else e["to"]
            if to is None or e["from"] not in self.parts.nodes or to not in self.parts.nodes:
                self.finding("dangling_ref", record=e["by"], rel=e["rel"], source=e["from"],
                             target=e["to"].plain if isinstance(e["to"], At) else e["to"])
                continue
            key = (e["rel"], e["from"], to, e["by"])
            if key not in seen:
                seen.add(key)
                self.parts.edges.append(e | {"to": to})
        if self.unplaced:               # per record, so a view can keep only the records its audience sees
            self.finding("validity_unplaced", records=dict(sorted(Counter(self.unplaced).items())),
                         text="links whose start no ledger event records start at the ledger's head")

    # -- the spec versions ---------------------------------------------------------------------------

    def _version_starts(self) -> list[int]:
        """Where each spec version starts in the ledger: version 1 at the first spec written, each later
        one at the amendment or plan edit that wrote it."""
        firsts = [s for k in SPEC_STARTS for s, _ in self.events.get(k, [])]
        return ([min(firsts)] if firsts else []) + sorted(s for k in VERSION_BUMPS for s, _ in self.events.get(k, []))

    def requirements(self) -> None:
        self.current = int(object_of(self.load("project.json", {})).get("spec_version", 1))
        names = [(v, f"spec.v{v}.json") for v in range(1, self.current)] + [(self.current, "spec.json")]
        loaded = [(v, name, self.load(name, None)) for v, name in names]
        loaded = [(v, name, spec) for v, name, spec in loaded if isinstance(spec, dict)]
        starts = self._version_starts()
        self.starts = {v: (starts[v - 1] if v <= len(starts) else None) for v in range(1, self.current + 1)}
        if loaded and len(starts) != self.current:
            self.finding("validity_unplaced", text=f"{self.current} spec versions, but the ledger records "
                                                   f"{len(starts)} spec writes and amendments")
        prev: dict[str, str] = {}
        for i, (v, name, spec) in enumerate(loaded):
            until = self.starts.get(loaded[i + 1][0]) if i + 1 < len(loaded) else None
            for pos, r in enumerate(records_of(spec.get("requirements"))):
                self._requirement(v, name, pos, r, until, prev)

    def _requirement(self, v: int, name: str, pos: int, r: dict[str, Any], until: int | None,
                     prev: dict[str, str]) -> None:
        rid = str(r.get("id", ""))
        nid, by, since = f"{rid}@v{v}", f"{name}#{rid}", self.starts.get(v)
        if not RID.match(rid):
            self.finding("unreadable_record", record=f"{name}#{pos}")
            return
        if nid in self.parts.nodes:
            self.parts.duplicates.setdefault(rid, [nid])
            self.finding("duplicate_id", id=rid, record=name, text=f"{name} states {rid} more than once")
            return
        self.node(nid, "requirement", by, rid=rid, version=v, since=since, until=until, n=pos,
                  label=str(r.get("statement", ""))[:160], provenance=r.get("provenance"))
        self.plain(rid, nid)
        for s in ids_of(r.get("sources")):
            self._source(nid, s, since, by)
        for k, c in enumerate(records_of(r.get("acceptance"))):
            cnid = self._criterion(rid, c, since, by)
            if cnid:
                self.has_criterion[(nid, cnid)] = self.link("has_criterion", nid, cnid, "kernel", since, by, n=k)
        if rid in prev:
            self.link("revision_of", nid, prev[rid], "kernel", since, by)
        prev[rid] = nid

    def _source(self, nid: str, source: str, since: int | None, by: str) -> None:
        if source in UNLINKED_SOURCES:
            return
        if source == "request":
            req = object_of(self.load("source.json", {}))
            self.node("request", "request", "source.json", label="the request", source_kind=req.get("kind"),
                      requested_by=req.get("requested_by"))
            target = "request"
        elif source.startswith("edit:"):
            target = self.person(source.split(":", 1)[1])
        else:
            target = source.split(":", 1)[1] if source.startswith("change:") else source
        self.link("derived_from", nid, target, "kernel", since, by)

    def _criterion(self, rid: str, c: dict[str, Any], since: int | None, by: str) -> str | None:
        cid = str(c.get("id", ""))
        if not CID.match(cid) or cid.rsplit("-AC-", 1)[0] != rid:
            self.finding("unreadable_record", record=f"{by}/{cid}")
            return None
        nid = f"{cid}@{_content(c)}"
        kind = c.get("kind") or (c.get("check") or {}).get("kind") or "test"
        if nid not in self.parts.nodes:
            self.node(nid, "criterion", by, plain=cid, since=since, criterion_kind=kind,
                      label=str(c.get("then", ""))[:160] if kind == "test" else None)
            self.plain(cid, nid)
        return nid

    # -- the contract and the tests on main ----------------------------------------------------------

    def contract(self) -> None:
        contract = self.load("contract.json", None)
        if not isinstance(contract, dict):
            return
        rev = contract.get("revision")
        since = self.seq("contract_compiled", "revision", rev)
        since = self.seq("change_applied", "contract", rev) if since is None else since
        for pos, r in enumerate(records_of(contract.get("requirements"))):
            self._contract_requirement(r, pos, since)
        state = object_of(self.load("tasks.json", {}))
        for pos, t in enumerate(records_of(contract.get("tasks"))):
            tid, by = str(t.get("id", "")), f"contract.json#{t.get('id')}"
            self.node(tid, "task", by, n=pos, since=since, label=str(t.get("title", ""))[:160],
                      status=object_of(state.get(tid)).get("status"))
            for cid in ids_of(t.get("criteria")):
                self.link("serves", tid, self.contract_crit.get(cid) or At(cid, since), "kernel", since, by)
            for dep in ids_of(t.get("depends_on")):
                self.link("depends_on", tid, dep, "kernel", since, by)

    def _contract_requirement(self, r: dict[str, Any], pos: int, since: int | None) -> None:
        rid = str(r.get("id", ""))
        nid, by = f"{rid}@v{self.current}", f"contract.json#{rid}"
        if not RID.match(rid):
            return
        if nid not in self.parts.nodes:     # in the contract only: a factory default check (FD-n)
            self.node(nid, "requirement", by, rid=rid, version=self.current, since=since, n=1000 + pos,
                      label=str(r.get("statement", ""))[:160], provenance=r.get("provenance"))
            self.plain(rid, nid)
        self.parts.nodes[nid]["in_contract"] = True
        for k, c in enumerate(records_of(r.get("acceptance"))):
            cnid = self._criterion(rid, c, since, by)
            if cnid is None:
                continue
            check = object_of(c.get("check"))
            self.parts.nodes[cnid]["check"] = check.get("kind", "test")
            self.contract_crit[str(c["id"])] = cnid
            edge = self.has_criterion.get((nid, cnid)) or self.link("has_criterion", nid, cnid, "kernel", since, by)
            edge["contract_n"] = k
            if check.get("kind") in ("holdout", "probe"):
                ref = str(check.get("ref") or f"H-{c['id']}")
                self.node(ref, "holdout_ref", by, criterion=c["id"], criterion_kind=check["kind"])
                self.link("checked_by", cnid, ref, "kernel", since, by)

    def tests(self) -> None:
        if not self.main:
            return
        from kernel.gate import tests_naming
        from kernel.insight import _main_test_names

        names = _main_test_names(self.p)
        moved = [s for k in ("merged", "repo_created") for s, _ in self.events.get(k, [])]
        since = max(moved) if moved else None
        for cid, nodes in sorted(self.parts.plain.items()):
            if not nodes or self.parts.nodes[nodes[-1]]["kind"] != "criterion":
                continue
            target = self.contract_crit.get(cid) or nodes[-1]
            for name in tests_naming(names, cid):
                self.node(f"test:{name}", "test", "repo.git#main", name=name, label=name)
                self.link("checked_by", target, f"test:{name}", "convention", since, "repo.git#main")

    def run(self) -> Parts:
        self.parts.problems += [f"kernel/ontology.json: {p}" for p in validate(self.onto)]
        self.main = main_revision(self.p)
        self.ledger()
        self.requirements()
        self.contract()
        for read in graph_records.READERS:
            read(self)
        self.tests()
        graph_records.consistency(self)
        self.finish()
        files = {name: self.files.get(name) or _sha(path) for name, path in self.paths.items()}
        self.parts.stamp = {"ontology": self.onto.stamp(), "ledger": self.ledger_head, "main": self.main,
                            "files": files}
        return self.parts


def build(project: Any) -> Graph:
    """The project's graph, rebuilt from its records now. An ontology that cannot be read makes it
    not measured, never a guess."""
    try:
        onto = load()
    except (OSError, OntologyError) as exc:
        parts = Parts(problems=[f"kernel/ontology.json cannot be read: {exc}"], stamp=restamp(project))
        return Graph(project, Ontology({}, "absent"), parts, lambda: restamp(project))
    return Graph(project, onto, Builder(project, onto).run(), lambda: restamp(project))
