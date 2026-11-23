"""The knowledge graph, phase 1 (docs/knowledge-graph.md; requirement FR-KG1).

The graph is a read model of one project's records, rebuilt on every read and checked against the
ontology (kernel/ontology.json). These tests prove its acceptance criteria on projects the scripted
fakes build: the ontology and the refs scan, the edges' origin, validity and pointer, parity with the
hand-written walker, a trace through an amendment, the questions people ask, the four outcomes, the
protected ontology and the read-only command. The custody canary, the redaction module, the stdlib
rule and the assistant baseline are in tests/test_graph_custody.py.
"""

import ast
import contextlib
import copy
import hashlib
import io
import json
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, model, no_findings  # noqa: E402

from kernel import cli  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.change import apply_change, submit, triage  # noqa: E402
from kernel.compile import compile_project, contract_check  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.graph import build  # noqa: E402
from kernel.graph_ask import criteria_from_answers, parity, production_approvals, rests_on_refuted  # noqa: E402
from kernel.insight import impact  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.ontology import ORIGINS, Ontology, load, resolve, validate  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
OPTIONAL = "The approver should be optional instead"


class GraphCase(FactoryTestCase):
    def specced(self, mode="mixed"):
        """A compiled project: in mixed mode Aino answers Q-001 (R-2 rests on it) and the factory
        assumes Q-002 (R-3 rests on it); in assume mode both are assumed."""
        p = self.new(mode=mode)
        intake(p, IDEA, model=model(), requested_by="Aino")
        if mode == "mixed":
            Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def amend_r2(self, p):
        """A change request on R-2, accepted by Aino and applied: R-2's sources become the change."""
        card = submit(p, persona="product_owner", person="Pekka", text=OPTIONAL)
        triage(p, card["id"], model=model())
        Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner")
        apply_change(p, card["id"], model=model())
        return card

    @staticmethod
    def release(p, n, requirements, *, maturity="demo", production=False):
        """A release record as delivery keeps it, with the ledger events delivery writes."""
        steps = [{"step": "promote:production", "outcome": "passed"}] if production else []
        rel = {"release": n, "project": p.pid, "maturity": maturity, "revision": f"{n:040d}",
               "requirements": list(requirements), "state": "done", "steps": steps}
        p.write(f"releases/{n}.json", rel)
        p.log("release_started", {"release": n, "revision": rel["revision"], "maturity": maturity, "plan": []})
        if production:
            p.log("promoted", {"release": n, "environment": "production", "previous": None, "revision": rel["revision"]})
        return rel

    @staticmethod
    def edit_canon(p, name, change):
        """Change a canon file by hand, as no kernel code would: no ledger event records it."""
        path = p.path("canon", name)
        records = json.loads(path.read_text(encoding="utf-8"))
        change(records)
        path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8", newline="\n")


def one(records, rid):
    return next(r for r in records if r["id"] == rid)


# -- the ontology (AC-3) and the refs scan (AC-4) ---------------------------------------------------------

def _names(node, consts):
    """The strings a tuple or list literal holds, or a name bound to one in the same function."""
    if isinstance(node, ast.Name):
        return consts.get(node.id, set())
    if isinstance(node, (ast.Tuple, ast.List)):
        return {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _dict_keys(node, out, consts=None):
    """The keys of a dict literal, of the dicts it unpacks, and of `{k: ... for k in KEYS}`."""
    consts = consts or {}
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values, strict=True):
            if k is None:
                _dict_keys(v, out, consts)
            elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                out.add(k.value)
    elif isinstance(node, ast.IfExp):
        _dict_keys(node.body, out, consts)
        _dict_keys(node.orelse, out, consts)
    elif isinstance(node, ast.DictComp) and node.generators:
        out |= _names(node.generators[0].iter, consts)
    return out


def _local_tuples(tree):
    """For each node of a module, the string tuples its enclosing function binds to a name."""
    scope = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            consts = {t.id: _names(a.value, {}) for a in ast.walk(fn) if isinstance(a, ast.Assign)
                      for t in a.targets if isinstance(t, ast.Name) and _names(a.value, {})}
            for node in ast.walk(fn):
                scope.setdefault(id(node), {}).update(consts)
    return scope


def refs_keys_written(root=ROOT / "kernel"):
    """Every refs key a kernel module writes: `refs={...}` on a call, the refs a decision records
    (Canon._record_decision's seventh argument), and `x["refs"]["key"] = ...`."""
    found = {}
    for path in sorted(root.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            keys = set()
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "refs":
                        keys |= _dict_keys(kw.value, set())
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name == "_record_decision" and len(node.args) > 6:
                    keys |= _dict_keys(node.args[6], set())
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Subscript)
                            and isinstance(t.value.slice, ast.Constant) and t.value.slice.value == "refs"
                            and isinstance(t.slice, ast.Constant)):
                        keys.add(t.slice.value)
            for k in keys:
                found.setdefault(k, []).append(f"{path.name}:{node.lineno}")
    return found


def ledger_writes(root=ROOT / "kernel"):
    """Each ledger event kind a kernel module writes, with the payload keys it writes."""
    found = {}
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scope = _local_tuples(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("log", "_log", "append")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                continue
            keys = _dict_keys(node.args[1], set(), scope.get(id(node))) if len(node.args) > 1 else set()
            keys |= {kw.arg for kw in node.keywords if kw.arg}
            if path.name == "deliver.py" and node.keywords:
                keys.add("release")       # Delivery.log puts the release number on every event it writes
            found.setdefault(node.args[0].value, set()).update(keys)
    return found


class OntologyTest(GraphCase):
    def test_FR_KG1_AC_3_every_kind_and_relation_has_an_id_a_description_and_a_consumer_and_every_enum_resolves(self):
        onto = load()
        self.assertEqual(validate(onto), [])
        self.assertRegex(onto.version, r"^\d+\.\d+\.\d+$")
        for group in (onto.kinds, onto.relations):
            for key, entry in group.items():
                self.assertEqual(entry["id"], key)
                self.assertTrue(entry["description"].strip() and entry["label"].strip())
                self.assertTrue(entry["consumers"], key)
                for consumer in entry["consumers"]:
                    self.assertTrue(callable(resolve(consumer)), consumer)
        import kernel.canon as canon
        import kernel.people as people

        self.assertIs(resolve(onto.kinds["card"]["enums"]["kind"]), canon.CARD_VERDICTS)   # referenced, not copied
        self.assertIs(resolve(onto.relations["signed_by"]["qualifiers"]["persona"]), people.PERSONAS)
        # who may see what: builders never see held-out checks or outside text
        for kind in ("holdout_ref", "signal", "comment", "card", "decision"):
            self.assertFalse(onto.visible_to(kind, "builder"), kind)
        self.assertFalse(onto.visible_to("holdout_ref", "verifier"))
        # a broken copy is named, problem by problem
        broken = copy.deepcopy(onto.data)
        broken["kinds"]["task"]["description"] = ""
        broken["kinds"]["card"]["enums"]["kind"] = "canon.NO_SUCH_LIST"
        broken["relations"]["serves"]["consumers"] = ["graph.Graph.no_such_query"]
        broken["relations"]["about"]["consumers"] = []
        problems = validate(Ontology(broken, "x"))
        self.assertTrue(any("kinds.task: no description" in p for p in problems), problems)
        self.assertTrue(any("canon.NO_SUCH_LIST" in p and "does not resolve" in p for p in problems), problems)
        self.assertTrue(any("graph.Graph.no_such_query does not resolve" in p for p in problems), problems)
        self.assertTrue(any("relations.about: no consumer" in p for p in problems), problems)
        # every graph is stamped with the ontology it was checked against
        stamp = build(self.specced()).stamp["ontology"]
        self.assertEqual(stamp, {"version": onto.version, "sha256": onto.sha256})

    def test_FR_KG1_AC_4_every_refs_key_the_kernel_writes_maps_to_a_declared_relation(self):
        onto = load()
        written = refs_keys_written()
        self.assertTrue({"question", "requirements", "release", "signal", "redone"} <= set(written), written)
        for key, where in sorted(written.items()):
            self.assertIn(key, onto.refs, f"refs key {key!r} ({where}) maps to nothing in kernel/ontology.json")
            entry = onto.refs[key]
            if "relation" in entry:
                self.assertIn(entry["relation"], onto.relations, key)
            else:
                self.assertTrue(entry["attribute"].strip(), key)
        # the ledger fields the graph reads are ones the kernel writes, so the ontology cannot drift from the code
        from kernel.dispatch import _cell_summary

        logged = ledger_writes()
        logged["cell_ran"] |= set(_cell_summary({}))      # cell_ran spreads the run's summary into its payload
        for event, fields in onto.ledger.items():
            self.assertIn(event, logged, f"no kernel module writes {event}")
            self.assertTrue(set(fields) <= logged[event], (event, set(fields) - logged[event]))

    def test_FR_KG1_AC_4_an_unknown_refs_key_in_a_project_is_an_unmapped_ref_finding(self):
        p = self.specced()
        card = Canon(p).card("approval", "Approve something", refs={"mystery": "X-1", "requirements": ["R-1"]})
        graph = build(p)
        unmapped = [f for f in graph.parts.findings if f["kind"] == "unmapped_ref"]
        self.assertEqual([(f["key"], f["record"]) for f in unmapped], [("mystery", f"canon/inbox/{card['id']}.json")])
        checked = graph.check()
        self.assertEqual(checked["outcome"], "answered")
        self.assertEqual(checked["counts"].get("unmapped_ref"), 1)
        self.assertEqual([e["to"] for e in graph.out_edges(card["id"], "rests_on")], ["R-1@v1"])   # the rest links


# -- edges (AC-5) ------------------------------------------------------------------------------------------

class EdgeTest(GraphCase):
    def test_FR_KG1_AC_5_every_edge_has_an_origin_a_validity_start_and_a_by_pointer_and_triage_stays_proposed(self):
        p = self.specced()
        canon = Canon(p)
        acc = canon.card("validation", "Accept?", refs={"requirements": ["R-2"]})
        canon.decide(acc["id"], "accept", person="Aino", persona="business_owner")
        card = submit(p, persona="product_owner", person="Pekka", text=OPTIONAL)
        triage(p, card["id"], model=model())
        graph = build(p)
        self.assertTrue(graph.edges)
        for e in graph.edges:
            self.assertIn(e["origin"], ORIGINS, e)
            self.assertIsInstance(e["valid_from"], int, e)
            self.assertTrue(e["by"], e)
            self.assertIn(e["origin"], load().relations[e["rel"]]["origins"], e)
        touches = graph.out_edges(card["id"], "touches")
        self.assertEqual([(e["to"], e["origin"]) for e in touches], [("R-2@v1", "model_proposed")])
        answer = graph.impact(["R-2"])
        self.assertIn(("touches", card["id"]), [(s["rel"], s["from"]) for s in answer["proposed"]])
        self.assertNotIn("touches", [s["rel"] for s in answer["steps"]])      # proposed edges come back apart
        triaged = next(r["seq"] for r in p.ledger().of_kind("change_triaged") if r["event"]["payload"]["card"] == card["id"])
        self.assertEqual(touches[0]["valid_from"], triaged)
        canon.decide(card["id"], "accept", person="Aino", persona="business_owner")
        self.assertEqual([e["origin"] for e in build(p).out_edges(card["id"], "touches")], ["person_confirmed"])
        # an approval that goes stale: what it rested on ends at the stale mark
        apply_change(p, card["id"], model=model())
        graph = build(p)
        stale = next(r["seq"] for r in p.ledger().of_kind("approvals_stale"))
        decision = next(d["id"] for d in canon.decisions() if d["card"] == acc["id"])
        self.assertEqual([e["valid_to"] for e in graph.out_edges(decision, "rests_on")], [stale])
        self.assertEqual([e["to"] for e in graph.out_edges(decision, "invalidated_by")], [card["id"]])
        self.assertEqual(graph.as_of(stale - 1).out_edges(decision, "rests_on")[0]["to"], "R-2@v1")
        self.assertEqual(graph.as_of(stale).out_edges(decision, "rests_on"), [])
        then = graph.as_of(stale - 1).impact(["R-2"])["result"]           # as it stood before the amendment
        self.assertEqual([a["id"] for a in then["approvals_going_stale"]], [decision])
        self.assertEqual(graph.impact(["R-2"])["result"]["approvals_going_stale"], [])


# -- parity with insight.impact (AC-6) --------------------------------------------------------------------

class ParityTest(GraphCase):
    def test_FR_KG1_AC_6_graph_impact_agrees_with_insight_impact_and_finds_what_mark_stale_would_mark(self):
        p = self.specced(mode="assume")
        build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=good_cell,
                   verifier_runner=no_findings)
        canon = Canon(p)
        for kind, refs, verdict, who in (("validation", {"requirements": ["R-1"]}, "accept", "business_owner"),
                                         ("approval", {"requirement": "R-2"}, "approve", "developer"),
                                         ("approval", {"requirements": ["R-1"]}, "reject", "developer")):
            card = canon.card(kind, f"{kind} {refs}", refs=refs)
            canon.decide(card["id"], verdict, person="Aino", persona=who)
        triage(p, submit(p, persona="end_user", person="Tester", text="Adding an item with an empty name crashes")["id"],
               model=model())
        self.release(p, 1, ["R-2", "R-3"])
        self.release(p, 2, ["R-1", "R-2", "R-3", "R-4"])
        for ids in (["R-1"], ["R-2", "R-9"], ["R-3", "R-4"], ["R-9"], ["R-1", "R-2", "R-3", "R-4"]):
            self.assertEqual(build(p).impact(ids)["result"], impact(p, ids), ids)
        self.assertEqual(impact(p, ["R-1"])["releases_carrying"], [{"release": 2, "revision": f"{2:040d}", "state": "done"}])
        self.assertEqual(build(p).impact(["R-1"])["result"]["tests"]["R-1-AC-1"],
                         ["test_R_1_AC_1_post_item_returns_201_with_id"])
        report = parity(p, ["R-1"])
        self.assertEqual((report["outcome"], report["agree"], report["differences"]), ("answered", True, []))
        self.assertEqual(report["releases"], {"every": [1, 2], "carrying": [2], "listed_before_the_fix": [1]})
        self.assertEqual(report["scope_release_decisions"], [])
        self.assertTrue(any("refs.scope == 'release'" in n and "dead" in n for n in report["notes"]))
        # the approvals the graph finds are exactly the ones Canon.mark_stale marks
        found = [a["id"] for a in build(p).impact(["R-1", "R-2"])["result"]["approvals_going_stale"]]
        marked = [d["id"] for d in Canon(p).mark_stale(["R-1", "R-2"], reason="parity check")]
        self.assertEqual(found, marked)
        self.assertEqual(len(found), 2)
        self.assertEqual(build(p).impact(["R-1", "R-2"])["result"], impact(p, ["R-1", "R-2"]))


# -- trace through an amendment (AC-7) ----------------------------------------------------------------------

class TraceTest(GraphCase):
    def test_FR_KG1_AC_7_a_requirement_an_amendment_replaced_still_traces_to_the_original_question_and_answer(self):
        p = self.specced(mode="mixed")
        card = self.amend_r2(p)
        self.assertEqual(next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")["sources"],
                         [f"change:{card['id']}"])                       # the amendment replaced the sources
        answer = build(p).trace("R-2")
        self.assertEqual((answer["outcome"], answer["start"]), ("answered", ["R-2@v2"]))
        steps = {(s["from"], s["rel"], s["to"]) for s in answer["steps"]}
        self.assertIn(("R-2@v2", "revision_of", "R-2@v1"), steps)
        self.assertIn(("R-2@v1", "derived_from", "Q-001"), steps)
        self.assertIn(("Q-001", "answered_by", "person:Aino"), steps)
        self.assertIn(("R-2@v2", "derived_from", card["id"]), steps)
        self.assertIn("spec.v1.json#R-2", answer["cites"])
        self.assertEqual(list(answer)[-1], "outcome")                     # every answer ends in its outcome

    def test_FR_KG1_AC_7_an_amended_requirement_on_an_assumption_traces_to_the_question_and_the_assumption(self):
        p = self.specced(mode="assume")
        self.amend_r2(p)
        steps = {(s["from"], s["rel"], s["to"]) for s in build(p).trace("R-2")["steps"]}
        assumption = Canon(p).question("Q-001")["answer"]["assumption"]
        self.assertIn(("R-2@v1", "derived_from", "Q-001"), steps)
        self.assertIn(("Q-001", "assumed_as", assumption), steps)


# -- the questions people ask (AC-8) ---------------------------------------------------------------------------

class QuestionsTest(GraphCase):
    def test_FR_KG1_AC_8_refuted_assumptions_answers_and_production_approvals_match_hand_written_answers(self):
        p = self.specced(mode="mixed")
        canon = Canon(p)
        self.release(p, 1, ["R-1", "R-2", "R-3", "R-4"], maturity="production", production=True)
        self.release(p, 2, ["R-1"])
        gate = canon.card("deploy_gate", "Deploy release 1?", refs={"release": 1})
        canon.decide(gate["id"], "approve", person="Ilkka", persona="it")
        accept = canon.card("validation", "Accept release 1?", refs={"release": 1, "requirements": ["R-2"]})
        canon.decide(accept["id"], "accept", person="Aino", persona="business_owner")
        assumption = canon.question("Q-002")["answer"]["assumption"]
        canon.settle_assumption(assumption, confirmed=False, person="Olli", persona="operations", correction="no")
        change = self.amend_r2(p)
        graph = build(p)
        decided = {d["card"]: d["id"] for d in canon.decisions()}

        refuted = rests_on_refuted(graph)
        self.assertEqual(refuted["outcome"], "answered")
        self.assertEqual([(r["release"], r["requirement"], r["question"], r["assumption"]) for r in refuted["rows"]],
                         [(1, "R-3", "Q-002", assumption)])

        answers = criteria_from_answers(graph, "Aino")
        self.assertEqual([(r["criterion"], r["requirement"], r["question"], r["persona"], r["through"])
                          for r in answers["rows"]], [("R-2-AC-1", "R-2", "Q-001", "business_owner", ["R-2@v1"])])
        self.assertEqual(criteria_from_answers(graph, "Nobody")["outcome"], "not_found")

        approvals = production_approvals(graph)
        rows = sorted((r["release"], r["decision"], r["kind"], r["person"], r["persona"], r["holds"], r["invalidated_by"])
                      for r in approvals["rows"])
        self.assertEqual(rows, sorted([(1, decided[gate["id"]], "deploy_gate", "Ilkka", "it", True, []),
                                       (1, decided[accept["id"]], "validation", "Aino", "business_owner", False,
                                        [change["id"]])]))
        for answer in (refuted, answers, approvals):
            self.assertTrue(answer["cites"])
            self.assertEqual(list(answer)[-1], "outcome")


# -- the four outcomes (AC-9) ----------------------------------------------------------------------------------

class OutcomeTest(GraphCase):
    def test_FR_KG1_AC_9_a_canon_file_changed_without_a_ledger_event_makes_an_answer_not_measured_and_names_it(self):
        p = self.specced()
        graph = build(p)
        self.assertEqual(graph.trace("R-2")["outcome"], "answered")
        path = p.path("canon", "questions.json")
        questions = json.loads(path.read_text(encoding="utf-8"))
        questions[2]["text"] = "edited by hand"
        path.write_text(json.dumps(questions, indent=2) + "\n", encoding="utf-8", newline="\n")
        held = graph.trace("R-2")
        self.assertEqual(held["outcome"], "not_measured")
        self.assertIn("canon/questions.json changed since the graph was built, with no ledger event", held["causes"])
        # a fresh build that reads an answer the ledger never recorded is not measured either
        questions[0]["answer"]["by"] = "Mallory"
        path.write_text(json.dumps(questions, indent=2) + "\n", encoding="utf-8", newline="\n")
        fresh = build(p).trace("R-2")
        self.assertEqual(fresh["outcome"], "not_measured")
        self.assertTrue(any("Q-001 is answered (by Mallory)" in c and "question_answered" in c
                            for c in fresh["causes"]), fresh["causes"])

    def test_FR_KG1_AC_9_a_broken_ledger_chain_makes_every_answer_not_measured(self):
        p = self.specced()
        ledger = p.path("ledger.jsonl")
        lines = ledger.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[3])
        record["event"]["payload"]["tampered"] = True
        lines[3] = json.dumps(record, sort_keys=True, separators=(",", ":"))
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        graph = build(p)
        for answer in (graph.trace("R-1"), graph.impact(["R-1"]), graph.check(), rests_on_refuted(graph)):
            self.assertEqual(answer["outcome"], "not_measured")
            self.assertIn("ledger.jsonl: the hash chain is broken at seq 3", answer["causes"])

    def test_FR_KG1_AC_9_an_unknown_id_is_not_found_and_a_duplicated_or_restated_id_is_ambiguous(self):
        p = self.specced()
        graph = build(p)
        self.assertEqual(graph.trace("R-99")["outcome"], "not_found")
        self.assertEqual(graph.trace("R-99")["missing"], ["R-99"])
        self.assertEqual(graph.impact(["R-99"])["outcome"], "not_found")
        self.assertEqual(graph.path("R-1", "Q-999")["outcome"], "not_found")
        self.amend_r2(p)                                     # R-2-AC-1 is restated: an old link to it is ambiguous
        restated = build(p).trace("R-2-AC-1")
        self.assertEqual(restated["outcome"], "ambiguous")
        self.assertEqual(len(restated["candidates"]), 2)
        exact = build(p).trace(restated["candidates"][0]["id"])        # its content key names one version
        self.assertEqual(exact["outcome"], "answered")
        spec = p.read("spec.json")
        spec["requirements"].append(copy.deepcopy(spec["requirements"][0]))   # R-1 stated twice
        p.write("spec.json", spec)
        duplicated = build(p)
        self.assertEqual(duplicated.trace("R-1")["outcome"], "ambiguous")
        self.assertIn("duplicate_id", duplicated.check()["counts"])


# -- the canon against the ledger (AC-14) -----------------------------------------------------------------------

class CanonLedgerTest(GraphCase):
    def production(self):
        """AC-8's project: production release 1 carries every requirement; Ilkka approved deploying it (as IT),
        Aino accepted it resting on R-2, and Aino (as a developer) rejected an approval card about it."""
        p = self.specced(mode="mixed")
        canon = Canon(p)
        self.release(p, 1, ["R-1", "R-2", "R-3", "R-4"], maturity="production", production=True)
        decided = []
        for kind, refs, verdict, person, persona in (
                ("deploy_gate", {"release": 1}, "approve", "Ilkka", "it"),
                ("validation", {"release": 1, "requirements": ["R-2"]}, "accept", "Aino", "business_owner"),
                ("approval", {"release": 1}, "reject", "Aino", "developer")):
            card = canon.card(kind, f"{kind} of release 1", refs=refs)
            decided.append(canon.decide(card["id"], verdict, person=person, persona=persona)["id"])
        return p, *decided

    def test_FR_KG1_AC_14_an_assumption_status_the_ledger_does_not_record_makes_the_answer_not_measured(self):
        p, *_ = self.production()
        assumption = Canon(p).question("Q-002")["answer"]["assumption"]
        self.assertEqual((rests_on_refuted(build(p))["outcome"], rests_on_refuted(build(p))["rows"]), ("answered", []))
        self.edit_canon(p, "assumptions.json", lambda items: one(items, assumption).update(status="refuted"))
        forged = rests_on_refuted(build(p))
        self.assertEqual(forged["outcome"], "not_measured")
        self.assertNotIn("rows", forged)
        self.assertIn(f"canon/assumptions.json says {assumption} is refuted, but the ledger records it open "
                      "(no assumption_settled event settles it)", forged["causes"])
        self.edit_canon(p, "assumptions.json", lambda items: one(items, assumption).update(status="open"))
        Canon(p).settle_assumption(assumption, confirmed=False, person="Olli", persona="operations", correction="no")
        self.assertEqual([(r["release"], r["assumption"]) for r in rests_on_refuted(build(p))["rows"]], [(1, assumption)])
        self.edit_canon(p, "assumptions.json", lambda items: one(items, assumption).update(status="open"))
        hidden = rests_on_refuted(build(p))                       # a refutation hidden by hand
        self.assertEqual(hidden["outcome"], "not_measured")
        self.assertIn(f"canon/assumptions.json says {assumption} is open, but the ledger records it refuted",
                      hidden["causes"])

    def test_FR_KG1_AC_14_a_decision_whose_refs_persona_kind_or_approving_flag_was_edited_makes_the_answer_not_measured(self):
        p, gate, accept, rejected = self.production()
        self.release(p, 2, ["R-1"], maturity="production", production=True)
        rows = [(r["release"], r["decision"], r["persona"]) for r in production_approvals(build(p))["rows"]]
        self.assertEqual(rows, [(1, gate, "it"), (1, accept, "business_owner")])
        decisions = p.path("canon", "decisions.json")
        original = decisions.read_bytes()
        for did, change, named in ((gate, {"refs": {"release": 2}, "persona": "business_owner"}, "persona, refs"),
                                   (accept, {"kind": "deploy_gate"}, "kind"),
                                   (rejected, {"approving": True}, "approving")):     # a rejection made an approval
            self.edit_canon(p, "decisions.json", lambda items, did=did, change=change: one(items, did).update(change))
            answer = production_approvals(build(p))
            self.assertEqual(answer["outcome"], "not_measured", named)
            self.assertIn(f"canon/decisions.json holds {did} with fields its decision event in the ledger does not "
                          f"record ({named})", answer["causes"])
            decisions.write_bytes(original)
        self.assertEqual(production_approvals(build(p))["outcome"], "answered")

    def test_FR_KG1_AC_14_an_approval_the_ledger_marked_stale_stays_stale_when_decisions_json_drops_the_flag(self):
        p, gate, accept, _ = self.production()
        change = self.amend_r2(p)
        rows = {r["decision"]: (r["holds"], r["invalidated_by"]) for r in production_approvals(build(p))["rows"]}
        self.assertEqual(rows, {gate: (True, []), accept: (False, [change["id"]])})
        self.edit_canon(p, "decisions.json", lambda items: one(items, accept).update(stale=False))
        graph = build(p)
        answer = production_approvals(graph)
        self.assertEqual(answer["outcome"], "not_measured")
        mark = next(r["seq"] for r in p.ledger().of_kind("approvals_stale"))
        self.assertIn(f"canon/decisions.json does not mark {accept} stale, which the approvals_stale event at "
                      f"ledger seq {mark} records", answer["causes"])
        self.assertTrue(graph.stale(graph.nodes[accept]))               # the ledger's mark, never the flag
        self.assertEqual(graph.impact(["R-2"])["outcome"], "not_measured")

    def test_FR_KG1_AC_14_a_question_answer_or_status_the_ledger_does_not_record_makes_the_answer_not_measured(self):
        p = self.specced(mode="mixed")
        questions = p.path("canon", "questions.json")
        original = questions.read_bytes()
        self.edit_canon(p, "questions.json", lambda items: one(items, "Q-001")["answer"].update(persona="it"))
        forged = criteria_from_answers(build(p), "Aino")
        self.assertEqual(forged["outcome"], "not_measured")
        self.assertIn("canon/questions.json says Q-001 is answered (persona it), which no question_answered event in "
                      "the ledger records", forged["causes"])
        questions.write_bytes(original)
        self.edit_canon(p, "questions.json", lambda items: one(items, "Q-001").update(status="open", answer=None))
        hidden = criteria_from_answers(build(p), "Aino")
        self.assertEqual(hidden["outcome"], "not_measured")
        self.assertIn("canon/questions.json says Q-001 is open, but a question_answered event in the ledger records "
                      "it answered", hidden["causes"])


# -- an adopted project (AC-16) ----------------------------------------------------------------------------------

class AdoptedTest(GraphCase):
    def test_FR_KG1_AC_16_an_adopted_project_s_observed_requirements_report_no_dangling_source(self):
        from kernel.adopt import OBSERVED, adopt
        from kernel.lanes import GIT_ID, _git

        src = self.tmp / "src"
        src.mkdir()
        (src / "README.md").write_text("# Stock levels\n\nA small service that counts stock.\n", encoding="utf-8",
                                       newline="\n")
        (src / "stock.py").write_text("def count(items):\n    return len(items)\n", encoding="utf-8", newline="\n")
        _git(src, "init", "-q", "-b", "main")
        _git(src, "add", "-A")
        _git(src, *GIT_ID, "commit", "-q", "-m", "initial")
        p = adopt(self.factory, "Stock levels", source=str(src), intent="maintain", person="Aino", persona="developer",
                  which=lambda name: None)
        self.assertEqual({s for r in p.read("spec.json")["requirements"] for s in r["sources"]}, {OBSERVED})
        graph = build(p)
        checked = graph.check()
        self.assertEqual(checked["outcome"], "answered")
        self.assertEqual([f for f in checked["findings"] if f["kind"] == "dangling_ref"], [])
        traced = graph.trace("R-1")
        self.assertEqual(traced["outcome"], "answered")
        self.assertNotIn("derived_from", [s["rel"] for s in traced["steps"]])     # observed: nothing upstream


# -- the protected ontology (AC-12) and the read-only command (AC-13) -----------------------------------------

def _tree_hashes(root: Path) -> dict:
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file() and not f.name.endswith(".lock")}


class ProtectedAndCommandTest(GraphCase):
    def test_FR_KG1_AC_12_the_ontology_is_write_protected_in_the_contract_check_and_the_builder_surface(self):
        cc = contract_check()
        contract = json.loads((ROOT / "contract" / "contract.json").read_text(encoding="utf-8"))
        bad = copy.deepcopy(contract)
        bad["tasks"][-1]["scope"] = {"write": ["kernel/ontology.json"]}
        report, _ = cc.check(bad)
        self.assertTrue(any(v["rule"] == "R-SCOPE" and v["got"] == "kernel/ontology.json" for v in report.violations),
                        report.violations)
        for task in contract["tasks"]:
            self.assertNotIn("kernel/ontology.json", (task.get("scope") or {}).get("write", []), task["id"])
        policy = tomllib.loads((ROOT / ".gnomon" / "policy.toml").read_text(encoding="utf-8"))
        self.assertIn("kernel/ontology.json", policy["governance"]["paths"]["ci"])
        self.assertEqual(policy["governance"]["ci"], "enforce")

    def test_FR_KG1_AC_12_a_glob_or_spelling_that_covers_a_protected_path_fails_and_one_that_does_not_passes(self):
        cc = contract_check()
        contract = json.loads((ROOT / "contract" / "contract.json").read_text(encoding="utf-8"))

        def refused(glob):
            bad = copy.deepcopy(contract)
            bad["tasks"][-1]["scope"] = {"write": [glob]}
            report, _ = cc.check(bad)
            return any(v["rule"] == "R-SCOPE" and v["got"] == glob for v in report.violations)

        claims = ("kernel/ontology.json", "./kernel/ontology.json", "kernel/**", "kernel/*.json", "kernel/ontology.*",
                  "kernel/onto*", "kernel//ontology.json", "kernel/./ontology.json", "kernel", "kernel/",
                  "**/ontology.json", "kernel/**/ontology.json", "Kernel/Ontology.JSON", "kernel\\ontology.json",
                  "src/../kernel/ontology.json", "kernel/{ontology,other}.json", "kernel/[o]ntology.json",
                  "kernel/?ntology.json", "*", "**", ".", "/kernel/ontology.json", "k*",
                  "contract/x.json", "contract", "./contract/**", "*/contract.json", "c*/contract.json", "specs/**",
                  "**/specs/a.md", "{contract,docs}/a.md", "decisions/D-1.md", "intake/**")
        free = ("kernel/*.py", "kernel/graph.py", "kernel/ontology.py", "kernel/ontology.jsonl", "kernel/graph*.py",
                "kernel/[!o]*.json", "kernel/routing.json", "docs/guides/*.md", "docs/**/*.md", "tests/fixtures/gnomon/**",
                "cockpit/**", "contracts/x", "specs.md")
        self.assertEqual([g for g in claims if not refused(g)], [])
        self.assertEqual([g for g in free if refused(g)], [])

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue()

    def test_FR_KG1_AC_13_rihmasto_graph_only_reads_and_check_reports_without_blocking(self):
        p = self.specced()
        Canon(p).card("approval", "Approve something", refs={"mystery": "X-1"})
        self.amend_r2(p)
        before = _tree_hashes(self.factory.home)
        code, text = self.run_cli("graph", "check", p.pid)
        checked = json.loads(text)
        self.assertEqual((code, checked["outcome"], checked["blocks"]), (0, "answered", False))
        self.assertIn("unmapped_ref", checked["counts"])                  # it found something, and exits 0
        for argv in (("trace", p.pid, "R-2"), ("trace", p.pid, "R-1", "Q-001"), ("impact", p.pid, "R-1", "R-2"),
                     ("path", p.pid, "R-2", "person:Aino"), ("show", p.pid, "--audience", "builder"),
                     ("refuted", p.pid), ("answers", p.pid, "Aino"), ("approvals", p.pid), ("parity", p.pid, "R-2"),
                     ("eval", p.pid), ("trace", p.pid, "R-2", "--as-of", "5")):
            code, text = self.run_cli("graph", *argv)
            self.assertEqual(code, 0, argv)
            answers = json.loads(text)
            for answer in answers if isinstance(answers, list) else [answers]:
                self.assertIn(answer["outcome"], ("answered", "ambiguous", "not_found", "not_measured"), argv)
        self.assertEqual(json.loads(self.run_cli("graph", "eval", p.pid)[1])["outcome"], "not_measured")
        self.assertEqual(_tree_hashes(self.factory.home), before)            # nothing was written
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.run_cli("graph", "trace", "no-such-project", "R-1")[0], 2)


if __name__ == "__main__":
    unittest.main()
