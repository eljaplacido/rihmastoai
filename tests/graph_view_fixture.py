"""Projects for the knowledge graph view's tests (FR-GRV1), built through the kernel as people and the factory
build them, so the graph is read through its own build (kernel/graph_build.py):

- ``every_kind``: one project whose graph holds every kind the ontology defines: the request, questions answered
  and assumed (one assumption refuted), people, requirements in two versions after an amendment, criteria, holdout
  checks, tasks with a builder run (a run, a model, a revision, the tests on main), cards with a signal and an
  observation, decisions (one overturned by the amendment), a comment, a production release and its pack;
- ``synthetic``: a graph of any size, made directly (kernel.graph.Parts), for the limits.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from factory_fakes import good_cell, model, no_findings

from kernel.canon import Canon
from kernel.change import apply_change, submit, triage
from kernel.compile import compile_project
from kernel.dispatch import build_task
from kernel.graph import Graph, Parts
from kernel.intake import intake
from kernel.lanes import Lanes
from kernel.ontology import load
from kernel.spec import make_spec

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
OPTIONAL = "The approver should be optional instead"
FAKE_KEY = "-".join(("sk", "live", "0000aaaa1111bbbb2222"))   # made here, so no file holds what looks like a key


def _release(p: Any) -> None:
    rel = {"release": 1, "project": p.pid, "maturity": "production", "revision": "1" * 40,
           "requirements": ["R-1", "R-2", "R-3"], "state": "done", "steps": [{"step": "promote:production", "outcome": "passed"}],
           "holdouts": {"environment": "demo", "verdict": "passed", "results": [{"criterion": "R-1-AC-2", "kind": "holdout",
                                                                                 "verdict": "passed"}]}}
    p.write("releases/1.json", rel)
    p.log("release_started", {"release": 1, "revision": rel["revision"], "maturity": "production", "plan": []})
    p.log("promoted", {"release": 1, "environment": "production", "previous": None, "revision": rel["revision"]})
    p.write("packs.json", [{"version": "1.0.0", "release": 1, "content_sha256": "a" * 64}])
    p.log("pack_versioned", {"version": "1.0.0", "release": 1, "content_sha256": "a" * 64})


def every_kind(case: Any) -> Any:
    """A project with every kind of node, an overturned decision and a requirement on a refuted assumption."""
    p = case.new(mode="mixed")
    intake(p, IDEA, model=model(), requested_by="Aino")
    canon = Canon(p)
    canon.answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
    make_spec(p, model=model())
    compile_project(p)
    build_task(p, "T-001", lanes=Lanes(case.tmp / "lanes", size=1), cell_runner=good_cell, verifier_runner=no_findings)
    acc = canon.card("validation", "Accept the loans list?", refs={"requirements": ["R-2"], "signal": "S-001",
                                                                   "observation": "O-001"})
    canon.decide(acc["id"], "accept", person="Aino", persona="business_owner")
    card = submit(p, persona="product_owner", person="Pekka", text=OPTIONAL)
    triage(p, card["id"], model=model())
    canon.decide(card["id"], "accept", person="Aino", persona="business_owner")
    apply_change(p, card["id"], model=model())                 # R-2 v2; the validation's approval goes stale
    canon.comment({"kind": "requirement", "id": "R-1"}, "keep the form short", person="Tiina", persona="end_user")
    _release(p)
    refuted = next(a for a in canon.assumptions("open"))
    canon.settle_assumption(refuted["id"], confirmed=False, person="Aino", persona="business_owner",
                            correction="no, anyone may borrow")
    return p


def with_secret_label(p: Any) -> None:
    """R-1's statement written by hand with something that looks like a credential in it."""
    path = p.path("spec.json")
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["requirements"][0]["statement"] = f"Members sign in; the service uses api_key={FAKE_KEY}"
    path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n")


def synthetic(nodes: int = 20000, edges: int = 40000) -> tuple[Any, Graph]:
    """A graph of ``nodes`` nodes (requirements, criteria, tests, tasks and questions) and about ``edges`` links,
    with a stand-in project: what kernel.graph_view needs of one."""
    parts = Parts()
    n_req = nodes // 5
    kinds: dict[str, list[str]] = {"requirement": [], "criterion": [], "test": [], "task": [], "question": []}
    for i in range(n_req):
        rid, nid = f"R-{i + 1}", f"R-{i + 1}@v1"
        parts.nodes[nid] = {"id": nid, "kind": "requirement", "record": f"spec.json#{rid}", "rid": rid, "version": 1,
                            "since": i, "label": f"Requirement {i + 1}", "in_contract": True}
        parts.plain[rid] = [nid]
        kinds["requirement"].append(nid)
        for k, kind in (("criterion", "criterion"), ("test", "test"), ("task", "task"), ("question", "question")):
            vid = f"{k}-{i}"
            parts.nodes[vid] = {"id": vid, "kind": kind, "record": "contract.json", "since": i, "label": f"{k} {i}",
                                "criterion_kind": "test", "name": vid}
            kinds[kind].append(vid)
    links = (("has_criterion", "requirement", "criterion"), ("checked_by", "criterion", "test"),
             ("serves", "task", "criterion"), ("derived_from", "requirement", "question"))
    made = 0
    while made < edges:
        for rel, a, b in links:
            i = made // len(links)
            src, dst = kinds[a][i % n_req], kinds[b][(i * 7 + made) % n_req]
            if rel == "checked_by" and i % 10 == 0:
                continue                                    # every tenth criterion has no test
            parts.edges.append({"rel": rel, "from": src, "to": dst, "origin": "kernel", "valid_from": 0, "valid_to": None,
                                "by": "contract.json"})
            made += 1
    stub = SimpleNamespace(pid="big", meta={"title": "A large project"}, factory=SimpleNamespace(clock=None),
                           ledger=lambda: SimpleNamespace(records=lambda: []))
    return stub, Graph(stub, load(), parts, lambda: {})
