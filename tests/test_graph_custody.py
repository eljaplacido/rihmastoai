"""The knowledge graph and the holdout custody (docs/knowledge-graph.md, section 3; requirement FR-KG1).

- A canary: scenarios carrying sentinel strings, a failed holdout that quotes one, a ruling whose reason
  quotes one, and outside text that carries others. The graph is built and every query and rendering is
  run; no sentinel appears, and no graph module names the custody's folder (AC-1).
- The redaction moved into kernel/custody.py, the one module the MCP server and delivery use (AC-2).
- The new kernel modules import only the standard library, as the quality gate judges it (AC-10).
- The assistant evaluation baseline: cited-id recall and the rate of unbacked citations, or not measured
  when no model endpoint answers (AC-11).
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model, script  # noqa: E402

from kernel import custody  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.change import submit  # noqa: E402
from kernel.compile import author_holdouts, compile_project  # noqa: E402
from kernel.custody import custody_safe, held_strings, ledger_record, redact  # noqa: E402
from kernel.graph import build  # noqa: E402
from kernel.graph_ask import (  # noqa: E402
    criteria_from_answers,
    eval_baseline,
    eval_cases,
    parity,
    production_approvals,
    rests_on_refuted,
)
from kernel.intake import intake  # noqa: E402
from kernel.model import FakeModel, ModelError  # noqa: E402
from kernel.rulings import apply_rulings, open_ruling  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import quality  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
GRAPH_MODULES = ("kernel/graph.py", "kernel/graph_build.py", "kernel/graph_records.py", "kernel/graph_ask.py",
                 "kernel/ontology.py", "kernel/ontology.json")
SENT_BODY = "zq-graph-sentinel-body-4417"          # what a scenario sends
SENT_EXPECT = "zq-graph-sentinel-expect-9031"      # what a scenario expects
SENT_REASON = "zq-graph-sentinel-ruling-2208"      # what a person said when they ruled on it
OUTSIDE = "zq-graph-outside-text-7777"             # outside text: a change's words, a comment's
TARGET = "zq-graph-outside-target-5150"            # outside text where an id belongs: a comment's target
SENTINELS = (SENT_BODY, SENT_EXPECT, SENT_REASON, OUTSIDE, TARGET)


def sentinel_script(prompt, role):
    """The fakes' script, except that the holdout author writes scenarios carrying the sentinels."""
    if "You write acceptance scenarios" in prompt:
        return "```json\n" + json.dumps({"scenarios": [
            {"criterion": "R-1-AC-2", "steps": [
                {"method": "POST", "path": "/items", "body": {"name": SENT_BODY}, "expect_status": 201},
                {"method": "GET", "path": "/items", "expect_status": 200, "expect_contains": SENT_EXPECT}]},
            {"criterion": "R-4-AC-2", "steps": [{"method": "GET", "path": "/health", "expect_status": 200,
                                                 "max_ms": 500}]}]}) + "\n```"
    if role == "assistant":                            # the cockpit assistant, asked by the eval
        return '```json\n{"answer": "It rests on what was asked.", "sources": ["Q-001", "A-001", "Q-999"]}\n```'
    return script(prompt, role)


class CustodyCanaryTest(FactoryTestCase):
    def held_out_project(self):
        p = self.new(mode="mixed")
        m = FakeModel(sentinel_script)
        intake(p, IDEA, model=m, requested_by="Aino")
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=m)
        compile_project(p)
        author_holdouts(p, model=m)
        failing = [{"criterion": "R-1-AC-2", "kind": "holdout", "verdict": "failed", "failed_step": 2, "steps": 2,
                    "request": {"method": "POST", "path": "/items", "body": {"name": SENT_BODY}},
                    "expected": {"expect_contains": SENT_EXPECT}, "observed": {"status": 200, "body": SENT_BODY},
                    "reason": f"expected {SENT_EXPECT}"}]
        reason = f"holdout R-1-AC-2 failed at step 2: expected {SENT_EXPECT}"
        release = {"release": 1, "project": p.pid, "maturity": "demo", "revision": "1" * 40, "state": "failed",
                   "requirements": ["R-1", "R-2", "R-3", "R-4"], "reason": reason, "failed_step": "holdouts:demo",
                   "holdouts": {"environment": "demo", "verdict": "failed", "results": failing},
                   "steps": [{"step": "holdouts:demo", "outcome": "failed",
                              "native": {"failing": failing, "why": reason, "ran": ["R-1-AC-2"]}}]}
        p.write("releases/1.json", release)
        p.log("release_started", {"release": 1, "revision": release["revision"], "maturity": "demo", "plan": []})
        p.log("release_failed", {"release": 1, "step": "holdouts:demo", "reason": custody_safe(reason)})
        ruling = open_ruling(p, 1, release)                               # its body quotes the scenario
        Canon(p).decide(ruling["id"], "scenario_defect", person="Dev", persona="developer",
                        reason=f"The scenario wanted {SENT_REASON} before creating it")
        apply_rulings(p, model=m)                                          # rewritten; the ledger keeps a pointer
        submit(p, persona="end_user", person="Tiina", text=f"Please also show {OUTSIDE} on the list")
        Canon(p).comment({"kind": "criterion", "id": "R-1-AC-2"}, f"I saw {OUTSIDE} here", person="Tiina",
                         persona="end_user")
        Canon(p).comment({"kind": "task", "id": f"please {TARGET} now"}, "hello", person="Tiina", persona="end_user")
        return p

    def test_FR_KG1_AC_1_no_sentinel_reaches_any_query_or_rendering_and_no_graph_module_names_the_custody(self):
        p = self.held_out_project()
        held = json.dumps([json.loads(f.read_text(encoding="utf-8")) for f in p.holdouts_dir.glob("*.json")])
        self.assertIn(SENT_BODY, held)                                     # the custody does hold them
        self.assertIn(SENT_REASON, (p.holdouts_dir / "rulings.jsonl").read_text(encoding="utf-8"))
        graph = build(p)
        self.assertEqual(graph.parts.problems, [])
        self.assertEqual(graph.nodes["H-R-1-AC-2"]["verdicts"], {"1": "failed"})   # verdicts, in a closed shape
        self.assertEqual(graph.nodes["release-1"]["reason"], "holdout R-1-AC-2 failed at step 2: [held out]")
        rendered = [graph.show(a) for a in ("person", "assistant", "verifier", "builder")]
        rendered += [graph.check(), graph.impact(sorted(graph.nodes)), rests_on_refuted(graph),
                     production_approvals(graph), parity(p, ["R-1", "R-2"])]
        rendered += [graph.trace(n) for n in sorted(graph.nodes)]
        rendered += [criteria_from_answers(graph, n.split(":", 1)[1]) for n in graph.nodes if n.startswith("person:")]
        rendered += [graph.path(a, b) for a, b in (("R-1", "H-R-1-AC-2"), ("release-1", "person:Dev"))]
        rendered += [graph.as_of(seq).impact(["R-1"]) for seq in (3, len(p.ledger().records()) // 2)]
        rendered.append(eval_baseline(p, FakeModel(sentinel_script)))
        text = json.dumps(rendered, ensure_ascii=False)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, text, sentinel)
        self.assertTrue(all(r["outcome"] != "not_measured" for r in rendered), [r.get("causes") for r in rendered])
        for name in GRAPH_MODULES:
            self.assertNotIn("holdouts_dir", (ROOT / name).read_text(encoding="utf-8"), name)
        builder = graph.view("builder")
        self.assertFalse({v["kind"] for v in builder.nodes.values()} & {"holdout_ref", "signal", "comment", "card"})


class AudienceTest(FactoryTestCase):
    HIDDEN_FROM_BUILDERS = ("canon/", "ledger.jsonl", "signals.json", "C-0", "D-0", "CM-0", "S-0", "person:")

    def with_findings(self):
        """A project whose graph has findings about a card, its decision and two comments: refs the ontology
        does not map, a requirement that does not exist, and a comment target that is no record id."""
        p = self.new(mode="mixed")
        intake(p, IDEA, model=model(), requested_by="Aino")
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        compile_project(p)
        canon = Canon(p)
        card = canon.card("approval", "Approve something", refs={"mystery": "X-1", "requirements": ["R-77"]})
        canon.decide(card["id"], "approve", person="Aino", persona="developer")
        canon.comment({"kind": "requirement", "id": "R-88"}, "about a requirement that is gone", person="Tiina",
                      persona="end_user")
        canon.comment({"kind": "task", "id": f"please {TARGET} now"}, "hello", person="Tiina", persona="end_user")
        return p

    def test_FR_KG1_AC_15_each_audience_sees_only_the_findings_about_records_it_may_see(self):
        p = self.with_findings()
        graph = build(p)
        shown = {a: graph.show(a) for a in ("person", "assistant", "verifier", "builder")}
        self.assertTrue(all(s["outcome"] == "answered" for s in shown.values()), [s.get("causes") for s in shown.values()])
        person = shown["person"]["findings"]
        cited = {f.get("record", "") for f in person}
        self.assertTrue({"canon/inbox/C-0002.json", "canon/decisions.json#D-002", "canon/comments.json#CM-001",
                         "canon/comments.json#CM-002"} <= cited, cited)
        self.assertEqual(shown["assistant"]["findings"], person)          # the assistant may see every kind
        verifier = json.dumps(shown["verifier"]["findings"])
        self.assertIn("canon/inbox/C-0002.json", verifier)                 # a verifier sees cards and decisions
        builder = shown["builder"]["findings"]
        for f in builder:
            for hidden in self.HIDDEN_FROM_BUILDERS:
                self.assertNotIn(hidden, json.dumps(f), f)
        self.assertEqual([f for f in builder if f["kind"] == "unmapped_ref"], [])
        # the comment's target is reported to a person without its words, and appears nowhere
        target = [f for f in person if f.get("record") == "canon/comments.json#CM-002"]
        self.assertEqual([(f["kind"], f["target"]) for f in target], [("dangling_ref", None)])
        self.assertNotIn(TARGET, json.dumps([graph.check(), *shown.values(), graph.trace("R-1")]))

    def test_FR_KG1_AC_15_an_audience_that_may_not_see_every_kind_is_not_told_which_records_disagree(self):
        p = self.with_findings()
        decisions = p.path("canon", "decisions.json")
        items = json.loads(decisions.read_text(encoding="utf-8"))
        items[-1]["person"] = "Mallory"                                     # edited by hand: no ledger event
        decisions.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8", newline="\n")
        graph = build(p)
        person = graph.show("person")
        self.assertEqual(person["outcome"], "not_measured")
        self.assertTrue(any("D-002" in c for c in person["causes"]), person["causes"])
        for audience in ("verifier", "builder"):
            hidden = graph.show(audience)
            self.assertEqual(hidden["outcome"], "not_measured")
            self.assertEqual(len(hidden["causes"]), 1)
            self.assertNotIn("D-002", hidden["causes"][0])
            self.assertIn(f"the {audience} audience may not see", hidden["causes"][0])
            self.assertEqual(graph.view(audience).trace("R-1")["causes"], hidden["causes"])


class CustodyModuleTest(unittest.TestCase):
    def test_FR_KG1_AC_2_the_redaction_lives_in_kernel_custody_and_the_mcp_server_and_delivery_use_it(self):
        import mcp.server as mcp_server
        from kernel import deliver, recipes, status

        self.assertIs(deliver.custody_safe, custody.custody_safe)
        self.assertIs(mcp_server.redact, custody.redact)
        self.assertIs(mcp_server.held_strings, custody.held_strings)
        self.assertIs(mcp_server.ledger_record, custody.ledger_record)
        for module in (recipes, status):                       # they import it from delivery, as before
            self.assertIn("from kernel.deliver import custody_safe", Path(module.__file__).read_text(encoding="utf-8"))
        pattern = "failed at step \\S"                         # the failed-holdout detail's regular expression
        for rel in ("mcp/server.py", "kernel/deliver.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for own in (pattern, "HOLDOUT_FIELDS =", '"[held out]"', "SCENARIO_META =", "def _strings("):
                self.assertFalse(own in text, f"{rel} keeps its own redaction ({own})")
        self.assertIn(pattern, (ROOT / "kernel" / "custody.py").read_text(encoding="utf-8"))
        # what the moved code does
        self.assertEqual(custody_safe(f"holdout R-1-AC-2 failed at step 2: expected {SENT_EXPECT}"),
                         "holdout R-1-AC-2 failed at step 2: [held out]")
        self.assertEqual(custody_safe(None), None)
        record = {"seq": 4, "hash": "h", "event": {"kind": "holdouts_authored", "at": "t",
                                                    "payload": {"criteria": ["R-1-AC-2"], "reauthored_because": "x"}}}
        self.assertEqual(ledger_record(record), {"seq": 4, "kind": "holdouts_authored", "at": "t", "hash": "h",
                                                 "payload": {"criteria": ["R-1-AC-2"]}, "redacted": ["reauthored_because"]})

        class Mine(str):
            pass

        self.assertEqual(redact({"a": [f"x {SENT_BODY} y", Mine(SENT_BODY)]}, [SENT_BODY], keep=(Mine,)),
                         {"a": ["x [held out] y", SENT_BODY]})
        root = Path(tempfile.mkdtemp(prefix="gf-custody-"))
        try:
            (root / "holdouts" / "p1").mkdir(parents=True)
            (root / "projects" / "p1").mkdir(parents=True)
            (root / "holdouts" / "p1" / "R-1-AC-2.json").write_text(json.dumps(
                {"criterion": "R-1-AC-2", "kind": "holdout", "steps": [{"path": "/items", "body": {"name": SENT_BODY}}]}),
                encoding="utf-8")
            (root / "projects" / "p1" / "spec.json").write_text('{"interface": "/items"}', encoding="utf-8")
            self.assertEqual(held_strings(root / "holdouts", root / "projects"), [SENT_BODY])   # /items is visible
        finally:
            shutil.rmtree(root, ignore_errors=True)


class StdlibOnlyTest(unittest.TestCase):
    def test_FR_KG1_AC_10_the_new_kernel_modules_import_only_the_standard_library(self):
        first = quality.first_party(ROOT)
        for rel in ("kernel/custody.py", "kernel/ontology.py", "kernel/graph.py", "kernel/graph_build.py",
                    "kernel/graph_records.py", "kernel/graph_ask.py"):
            self.assertTrue(rel.startswith(quality.RUNTIME), rel)           # inside what the gate keeps stdlib-only
            report = quality.analyse_file(ROOT / rel, rel, first)
            self.assertNotIn("unparsable", report, rel)
            self.assertEqual(report["third_party"], [], rel)
        seeded = Path(tempfile.mkdtemp(prefix="gf-stdlib-"))
        try:
            copy = seeded / "graph.py"
            copy.write_text("import requests\n" + (ROOT / "kernel" / "graph.py").read_text(encoding="utf-8"),
                            encoding="utf-8", newline="\n")
            self.assertEqual([t["module"] for t in quality.analyse_file(copy, "kernel/graph.py", first)["third_party"]],
                             ["requests"])                                  # the gate would name it
        finally:
            shutil.rmtree(seeded, ignore_errors=True)


class EvalBaselineTest(FactoryTestCase):
    def specced(self):
        p = self.new(mode="mixed")
        intake(p, IDEA, model=model(), requested_by="Aino")
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def test_FR_KG1_AC_11_the_eval_reports_recall_and_unbacked_citations_or_not_measured_without_a_model(self):
        p = self.specced()
        assumed = Canon(p).question("Q-002")["answer"]["assumption"]
        self.assertEqual(assumed, "A-001")
        cases = {c["about"]: c["expected"] for c in eval_cases(build(p))}
        self.assertEqual(cases, {"R-2": ["Q-001"], "R-3": ["A-001", "Q-002"]})       # what the graph knows
        none = eval_baseline(p, None)
        self.assertEqual(none["outcome"], "not_measured")
        self.assertIn("no model endpoint was asked (--with-model asks one)", none["causes"])

        def down(prompt, role):
            raise ModelError("connection refused: no endpoint answers")

        silent = eval_baseline(p, FakeModel(down))
        self.assertEqual(silent["outcome"], "not_measured")
        self.assertTrue(all(c.startswith("no model endpoint answered") for c in silent["causes"]), silent["causes"])
        self.assertTrue(any("connection refused" in c for c in silent["causes"]), silent["causes"])

        before = {str(f): f.read_bytes() for f in sorted(self.factory.home.rglob("*")) if f.is_file()}
        asked = eval_baseline(p, FakeModel(sentinel_script))          # cites Q-001, A-001 and Q-999 every time
        self.assertEqual({str(f): f.read_bytes() for f in sorted(self.factory.home.rglob("*")) if f.is_file()},
                         before)                                       # it keeps nothing
        self.assertEqual((asked["outcome"], asked["measured"], asked["asked"]), ("answered", 2, 2))
        self.assertEqual(asked["cited_id_recall"], round(2 / 3, 3))   # R-2: Q-001 of 1; R-3: A-001 of 2
        self.assertEqual(asked["unbacked_citation_rate"], round(2 / 6, 3))   # Q-999 backs nothing, twice
        self.assertEqual(sorted(asked["cases"][0]), ["about", "cited", "expected", "hits", "measured", "question",
                                                     "unbacked"])

        def quiet(prompt, role):
            return '```json\n{"answer": "I cannot say.", "sources": []}\n```'

        self.assertEqual(eval_baseline(p, FakeModel(quiet))["unbacked_citation_rate"], "not measured")


if __name__ == "__main__":
    unittest.main()
