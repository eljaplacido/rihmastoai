"""The knowledge graph view (docs/guides/knowledge-graph.md; requirement FR-GRV1).

The read model (kernel/graph_view.py) on a project whose graph holds every kind the ontology defines, read through
the graph's own build (tests/graph_view_fixture.py): nodes, states, times, records, routes and issues (AC-1); the
filters and the focus (AC-2); the limits on a graph of 20,000 nodes (AC-3); what is never shown and who may see what
(AC-4); saved views in the cockpit (AC-5); `rihmasto graph view` (AC-6); and Ask Rihma (AC-7). The browser drive
is tests/test_ui_graph.py (AC-8).
"""

from collections import Counter
import contextlib
import io
import json
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qsl

sys.path.insert(0, str(Path(__file__).parent))

import test_access as ta  # noqa: E402
from factory_fakes import model  # noqa: E402
from graph_view_fixture import FAKE_KEY, IDEA, every_kind, synthetic, with_secret_label  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_graph_custody import SENTINELS, CustodyCanaryTest  # noqa: E402

from kernel import cli  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.assistant_rules import CONTROL_PAGES, route_ok, ui_map  # noqa: E402
from kernel.graph import build  # noqa: E402
from kernel.graph_view import Filters, factory_view, parse_filters, project_view  # noqa: E402
from kernel.graph_view_nodes import HIDDEN_LABEL  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.ontology import load  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VIEW_MODULES = ("kernel/graph_view.py", "kernel/graph_view_nodes.py", "kernel/graph_view_cli.py", "kernel/graph_assist.py",
                "cockpit/graph_routes.py")


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class ReadModelTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.p = every_kind(self)

    def view(self, **query):
        return project_view(self.p, parse_filters(query))

    def node(self, model, nid):
        return next(n for n in model["nodes"] if n["id"] == nid)

    def test_FR_GRV1_AC_1_every_node_and_edge_of_the_graph_with_its_kind_state_time_record_route_and_issues(self):
        graph = build(self.p)
        self.assertEqual(graph.unmeasured(), [])
        self.assertEqual({n["kind"] for n in graph.nodes.values()}, set(load().kinds))    # every kind is here
        model = self.view(limit="2000")
        self.assertEqual(model["outcome"], "answered")
        self.assertEqual(sorted(n["id"] for n in model["nodes"]), sorted(graph.view("person").nodes))
        self.assertEqual(len(model["edges"]), len(graph.view("person").edges))
        self.assertIsNone(model["more"])
        for n in model["nodes"]:
            for key in ("kind", "family", "short", "label", "state", "seq", "at", "record", "href", "issues", "detail"):
                self.assertIn(key, n, n["id"])
            self.assertIn(n["state"], ("open", "closed", "superseded", None), n["id"])
            if n["seq"] is not None:
                self.assertTrue(n["at"].endswith("Z"), n)
        r1 = self.node(model, "R-1@v2")
        self.assertEqual((r1["state"], r1["record"], r1["href"]), ("open", "spec.json#R-1", f"#/p/{self.p.pid}/spec/R-1"))
        self.assertEqual(self.node(model, "R-1@v1")["record"], "spec.v1.json#R-1")
        self.assertEqual(self.node(model, "R-2@v1")["state"], "superseded")             # the amendment wrote v2
        self.assertEqual(self.node(model, "R-2@v2")["state"], "open")
        self.assertEqual(self.node(model, "T-001")["state"], "closed")                  # merged
        self.assertEqual(self.node(model, "Q-001")["state"], "closed")                  # answered
        decision = next(n for n in model["nodes"] if n["kind"] == "decision" and n["detail"].get("card_kind") == "validation")
        self.assertEqual((decision["state"], decision["issues"]), ("superseded", ["overturned"]))
        refuted = {n["id"] for n in model["nodes"] if "refuted_basis" in n["issues"]}
        self.assertTrue(refuted and all(i.startswith("R-") for i in refuted), refuted)
        self.assertTrue(any("untested" in n["issues"] for n in model["nodes"] if n["kind"] == "requirement"))
        self.assertTrue(any("criterion_untested" in n["issues"] for n in model["nodes"]))
        rels = {e["rel"] for e in model["edges"]}
        self.assertTrue({"has_criterion", "checked_by", "serves", "derived_from", "carries", "invalidated_by"} <= rels, rels)
        self.assertTrue(all(set(e) >= {"from", "to", "rel", "origin", "proposed"} for e in model["edges"]))
        counted = {i["id"]: i["count"] for i in model["issues"]}
        self.assertEqual(counted["overturned"], 1)

    def test_FR_GRV1_AC_2_filters_focus_and_the_route_query(self):
        trace = self.view(kinds="requirement,criterion,test", states="open")
        self.assertEqual({n["kind"] for n in trace["nodes"]}, {"requirement", "criterion", "test"})
        self.assertTrue(all(n["state"] in ("open", None) for n in trace["nodes"]))     # a test has no lifecycle
        self.assertNotIn("R-2@v1", {n["id"] for n in trace["nodes"]})                  # superseded
        self.assertTrue(all(e["rel"] in ("has_criterion", "checked_by") for e in trace["edges"]))
        self.assertEqual(trace["route_query"], "kinds=requirement,criterion,test&states=open")
        again = parse_filters(dict(parse_qsl(trace["route_query"])))
        self.assertEqual(again, Filters(kinds=("requirement", "criterion", "test"), states=("open",)))
        only = self.view(rels="has_criterion")
        self.assertEqual({e["rel"] for e in only["edges"]}, {"has_criterion"})
        words = self.view(q="T-001")
        self.assertIn("T-001", {n["id"] for n in words["nodes"]})
        self.assertTrue(all("t-001" in (n["id"] + n["short"] + n["label"]).lower() or n["kind"] == "round"
                            for n in words["nodes"]))
        issues = self.view(issues="1")
        self.assertTrue(issues["nodes"] and all(n["issues"] for n in issues["nodes"]))
        near = self.view(focus="R-1", hops="1")
        self.assertEqual(near["focus"], "R-1@v2")
        dist = {n["id"]: n["distance"] for n in near["nodes"]}
        self.assertEqual(dist["R-1@v2"], 0)
        self.assertTrue(all(d <= 1 for d in dist.values()))
        self.assertTrue(any(n["kind"] == "criterion" for n in near["nodes"]))
        farther = self.view(focus="R-1", hops="2")
        self.assertGreater(len(farther["nodes"]), len(near["nodes"]))
        self.assertTrue(any(n["kind"] == "test" for n in farther["nodes"]))             # requirement, criterion, test
        self.assertTrue(self.view(focus="R-99")["focus_missing"])
        self.assertEqual(len(self.view(window="24h")["nodes"]), len(self.view()["nodes"]))   # all made just now
        for bad in ({"kinds": "requirment"}, {"rels": "owns"}, {"states": "done"}, {"window": "1y"}, {"hops": "9"},
                    {"limit": "0x"}, {"audience": "anyone"}):
            with self.assertRaises(ValueError, msg=bad):
                parse_filters(bad)

    def test_FR_GRV1_AC_4_no_credential_label_and_an_audience_sees_only_its_kinds(self):
        with_secret_label(self.p)
        model = self.view()
        r1 = next(n for n in model["nodes"] if n["id"] == "R-1@v2")
        self.assertEqual(r1["label"], HIDDEN_LABEL)
        self.assertNotIn(FAKE_KEY, json.dumps(model))
        self.assertNotIn(FAKE_KEY, json.dumps(self.view(q=FAKE_KEY[:7])))
        builder = project_view(self.p, Filters(audience="builder"))
        self.assertFalse({n["kind"] for n in builder["nodes"]} & {"card", "decision", "person", "comment", "signal"})
        self.assertNotIn("holdout_ref", {n["kind"] for n in project_view(self.p, Filters(audience="verifier"))["nodes"]})

    def test_FR_GRV1_AC_7_ask_rihma_opens_the_graph_with_filters_and_explains_a_node(self):
        other = self.new(title="Room bookings")
        out = ask(self.factory, f"Show me how requirements trace to tests in {self.p.meta['title']}", persona="developer")
        self.assertEqual(out["by"], "graph")
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/graph?kinds=criterion,requirement,test")
        self.assertTrue(route_ok(out["navigate"]["route"], self.factory))
        self.assertIn("requirement", out["answer"])
        both = ask(self.factory, f"show me how requirements trace to tests in {self.p.meta['title']} and Room bookings",
                   persona="developer")
        route = both["navigate"]["route"]
        self.assertTrue(route.startswith("#/graph?kinds=criterion,requirement,test&projects="), route)
        self.assertEqual(set(dict(parse_qsl(route.split("?", 1)[1]))["projects"].split(",")), {self.p.pid, other.pid})
        self.assertTrue(route_ok(route, self.factory))
        self.assertFalse(route_ok(f"#/p/{self.p.pid}/spec?kinds=requirement", self.factory))   # only the graph's
        told = ask(self.factory, "Explain R-1 in the knowledge graph", persona="developer", project_id=self.p.pid)
        self.assertIn("R-1 v2 is a requirement (open)", told["answer"])
        self.assertIn("has criterion", told["answer"])
        self.assertEqual(told["navigate"]["route"], f"#/p/{self.p.pid}/graph?focus=R-1&hops=1")
        where = ask(self.factory, "Where is the knowledge graph?", persona="developer")   # the map answers it
        self.assertEqual(where["navigate"]["route"], "#/graph")
        m = ui_map()
        self.assertEqual({v["id"]: v["label"] for v in m["views"] if v["id"] in ("graph", "graph_all")},
                         {"graph": "Project knowledge graph", "graph_all": "Knowledge graph"})
        labels = {c["id"]: c["label"] for c in m["controls"]}
        self.assertEqual(labels["graph_filters"], "Graph filters")
        for cid in ("graph_filters", "graph_mode", "graph_focus", "graph_presets", "graph_pin"):
            self.assertEqual(CONTROL_PAGES[cid], ("graph", "graph_all"), cid)


class CustodyTest(CustodyCanaryTest):
    def test_FR_GRV1_AC_4_no_holdout_sentinel_reaches_the_view_and_no_view_module_names_the_custody(self):
        p = self.held_out_project()
        rendered = [project_view(p, parse_filters({"limit": "2000"})), factory_view(self.factory, Filters(limit=2000)),
                    project_view(p, Filters(focus="R-1", hops=4, audience="assistant"))]
        text = json.dumps(rendered, ensure_ascii=False)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, text, sentinel)
        self.assertIn("H-R-1-AC-2", text)                     # the held-out check is a node; its content is not
        for name in VIEW_MODULES:
            self.assertNotIn("holdouts_dir", (ROOT / name).read_text(encoding="utf-8"), name)


class LimitsTest(unittest.TestCase):
    def test_FR_GRV1_AC_3_a_graph_of_20000_nodes_answers_fast_and_says_how_many_more_are_not_shown(self):
        stub, graph = synthetic(20000, 40000)
        self.assertEqual(len(graph.nodes), 20000)
        self.assertGreaterEqual(len(graph.edges), 40000)
        started = time.monotonic()
        model = project_view(stub, Filters(), graph=graph)
        took = time.monotonic() - started
        self.assertLess(took, 10.0)
        self.assertEqual(len(model["nodes"]), 300)
        self.assertEqual(model["more"]["count"], 20000 - 300)
        self.assertEqual(sum(model["more"]["by_kind"].values()), 19700)
        self.assertTrue(model["more"]["note"].startswith("19700 more not shown ("), model["more"]["note"])
        shown = model["nodes"]
        flagged = [i for i, n in enumerate(shown) if n["issues"]]
        self.assertTrue(flagged and flagged == list(range(len(flagged))), "the nodes with issues come first")
        focused = project_view(stub, Filters(focus="R-5", hops=2, limit=50), graph=graph)
        self.assertEqual(focused["nodes"][0]["id"], "R-5@v1")
        self.assertLessEqual(len(focused["nodes"]), 50)
        self.assertEqual([n["distance"] for n in focused["nodes"]], sorted(n["distance"] for n in focused["nodes"]))
        ids = {n["id"] for n in focused["nodes"]}
        self.assertTrue(all(e["from"] in ids and e["to"] in ids for e in focused["edges"]))

    def test_FR_GRV1_AC_3_many_requirements_never_crowd_out_the_other_kinds(self):
        from kernel.graph_view import _fair

        node = lambda kind, i: {"id": f"{kind}-{i}", "kind": kind}   # noqa: E731
        ranked = [node("requirement", i) for i in range(400)] + [node("task", i) for i in range(19)] \
            + [node("decision", i) for i in range(70)] + [node("card", i) for i in range(70)]
        shown = _fair(ranked, 300)
        kinds = Counter(n["kind"] for n in shown)
        self.assertEqual(len(shown), 300)
        self.assertEqual(kinds["task"], 19)                                    # every task, a small kind
        self.assertEqual((kinds["decision"], kinds["card"]), (70, 70))
        self.assertEqual(kinds["requirement"], 300 - 19 - 140)
        self.assertEqual(shown, sorted(shown, key=ranked.index))               # still in rank order


class PresetsRouteTest(CockpitTestCase):
    def prefs(self, **body):
        return self.call("PUT", "/api/graph/prefs", {"person": "Aino Virtanen", "persona": "developer", **body})

    def test_FR_GRV1_AC_5_saved_views_per_person_outside_every_ledger_with_a_mode_a_default_and_reset(self):
        p = self.new()
        intake(p, IDEA, model=model(), requested_by="Aino")
        before = {q.pid: len(q.ledger().records()) for q in self.factory.projects()}
        status, out, _ = self.call("GET", f"/api/graph/prefs?scope={p.pid}&person=Aino%20Virtanen")
        self.assertEqual((status, out["saved"], out["prefs"]["mode"]), (200, False, "auto"))
        views = [{"name": "Only open requirements and their tests", "query": "kinds=requirement,criterion,test&states=open"}]
        status, out, _ = self.prefs(scope=p.pid, presets=views, mode="table")
        self.assertEqual(status, 200, out)
        status, out, _ = self.prefs(scope=p.pid, default_preset=views[0]["name"])
        self.assertEqual((out["prefs"]["presets"], out["prefs"]["mode"], out["prefs"]["default_preset"]),
                         (views, "table", views[0]["name"]))
        status, out, _ = self.call("GET", f"/api/graph/prefs?scope={p.pid}&person=Aino%20Virtanen")
        self.assertEqual((out["saved"], out["prefs"]["presets"]), (True, views))
        self.assertFalse(self.call("GET", f"/api/graph/prefs?scope={p.pid}&person=Ida")[1]["saved"])   # theirs only
        self.assertFalse(self.call("GET", "/api/graph/prefs?scope=*&person=Aino%20Virtanen")[1]["saved"])
        saved = list((self.factory.home / "_cockpit" / "graph_views").glob("*.json"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(json.loads(saved[0].read_text(encoding="utf-8"))["person"], "Aino Virtanen")
        self.assertEqual({q.pid: len(q.ledger().records()) for q in self.factory.projects()}, before)
        for bad in ({"presets": [{"name": "x", "query": "kinds=nope"}]}, {"mode": "cards"},
                    {"default_preset": "not saved"}, {"presets": [{"name": "", "query": ""}]}):
            self.assertEqual(self.prefs(scope=p.pid, **bad)[0], 400, bad)
        home = _tree(self.factory.home)
        status, out, _ = self.call("PUT", "/api/graph/prefs", {"person": "system", "persona": "developer",
                                                              "scope": p.pid, "mode": "graph"})
        self.assertEqual(status, 403, out)
        self.assertEqual(_tree(self.factory.home), home)
        status, out, _ = self.prefs(scope=p.pid, reset=True)
        self.assertEqual((status, out["prefs"], out["saved"]), (200, {"mode": "auto", "presets": [], "default_preset": None},
                                                                False))
        self.assertFalse(self.call("GET", f"/api/graph/prefs?scope={p.pid}&person=Aino%20Virtanen")[1]["saved"])
        # the graph itself, as the cockpit reads it, and a slice pinned to Home is a widget of its own
        status, seen, _ = self.call("GET", f"/api/projects/{p.pid}/graph?kinds=question&limit=3")
        self.assertEqual((status, seen["outcome"], len(seen["nodes"])), (200, "answered", 3))
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/graph?kinds=nope")[0], 400)
        self.assertEqual(self.call("GET", "/api/projects/no-such-project/graph")[0], 404)
        layout = {"v": 1, "lens": "delivery", "widgets": [{"id": "graph-1", "type": "graph", "size": "M", "view": "chart",
                                                           "filter": {"project": p.pid, "query": "kinds=question", "name": ""}}]}
        status, out, _ = self.call("PUT", "/api/layout?persona=developer&lens=delivery",
                                   {"person": "Aino Virtanen", "layout": layout})
        self.assertEqual(status, 200, out)
        self.assertIn("graph", self.call("GET", "/api/dashboard")[1])


class VisibilityTest(ta.EnforcedCockpitCase):
    def test_FR_GRV1_AC_4_with_access_enforced_only_the_projects_a_person_holds_a_persona_on(self):
        mine, theirs = self.new(title="Equipment loans"), self.new(title="Room bookings")
        self.enforce(ta.access_doc(project_scope=mine.pid))
        self.sign_in(ta.DEV)
        status, out = self.pcall("GET", f"/api/projects/{mine.pid}/graph", who=ta.DEV)
        self.assertEqual((status, out["outcome"]), (200, "answered"), out)
        status, out = self.pcall("GET", f"/api/projects/{theirs.pid}/graph", who=ta.DEV)
        self.assertEqual(status, 403, out)
        status, out = self.pcall("GET", "/api/graph", who=ta.DEV)
        self.assertEqual([p["id"] for p in out["projects"]], [mine.pid])
        self.assertTrue(all(n["pid"] == mine.pid for n in out["nodes"]))
        self.sign_in(ta.AINO)
        status, out = self.pcall("GET", "/api/graph", who=ta.AINO)
        self.assertTrue({mine.pid, theirs.pid} <= {p["id"] for p in out["projects"]})


class CommandTest(CockpitTestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_GRV1_AC_6_rihmasto_graph_view_prints_the_read_model_and_writes_nothing(self):
        p = every_kind(self)
        before = _tree(self.factory.home)
        code, text, _ = self.run_cli("graph", "view", p.pid, "--kinds", "requirement,criterion,test", "--states", "open")
        self.assertEqual(code, 0)
        self.assertIn("Knowledge graph: Equipment loans", text)
        self.assertIn("Filters: kinds=requirement,criterion,test&states=open", text)
        self.assertIn("R-1 v2", text)
        self.assertIn("--has_criterion-->", text)
        code, raw, _ = self.run_cli("graph", "view", p.pid, "--focus", "R-1", "--hops", "2", "--json")
        model = json.loads(raw)
        self.assertEqual((code, model["focus"]), (0, "R-1@v2"))
        self.assertEqual(model, json.loads(json.dumps(project_view(p, Filters(focus="R-1", hops=2)))))
        code, text, _ = self.run_cli("graph", "view", "--all", "--limit", "5")
        self.assertEqual(code, 0)
        self.assertIn("Knowledge graph: every project", text)
        self.assertIn("more not shown", text)
        self.assertEqual(_tree(self.factory.home), before)
        code, text, err = self.run_cli("graph", "view", p.pid, "--kinds", "nope")
        self.assertEqual((code, text), (2, ""))
        self.assertIn("kinds: nope is not one of", err)


if __name__ == "__main__":
    unittest.main()
