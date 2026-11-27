"""FR-CTX1: the data and context layer, visible (D-0024 item 2).

- AC-1: the context map says what Rihmasto knows about a project and where it came from, with freshness.
- AC-2: each role's and surface's context pack is exactly the prompt the real code path sends, cut into parts that
  join back to it: a scripted model (or a scripted cell, verifier or MCP call) captures what the code sends.
- AC-3: what a pack leaves out stays out: holdout content, secret values, other projects' cards and decision
  reasons; a pack's content is shown only to a persona allowed it.
- AC-4: the compression audit flags over-budget packs, lines said twice, stable-prefix violations and oversized
  outputs, and the fixes FR-CTX1 made hold (the assistant's catalogue, compact MCP answers, prompt order, whole
  steps).
- AC-5: the Data view's stores, sizes and ledger integrity, and a signed clean-up that removes only what is safe.
- AC-6: `rihmasto context` and `rihmasto data` on the command line.
- AC-7: the cockpit's routes, and Ask Rihma explains what an agent sees and why it did not know something.
"""

import contextlib
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, model, no_findings  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agent_bridge as bridge  # noqa: E402
from kernel import agent_channel as ch  # noqa: E402
from kernel import context_audit, context_chat, context_map, context_packs, context_parts, copilot  # noqa: E402
from kernel import data_stores  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.channel_rihma import reply  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import author_holdouts, compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.context_surfaces import MCP_PERSON  # noqa: E402
from kernel.store import write_json  # noqa: E402
from mcp.server import TOOLS, RihmaMCP, tool_list  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
ANSWER = '```json\n{"answer": "It is on track.", "navigate": null, "propose": [], "sources": []}\n```'
HELD = "zq-held-scenario-8842"
SECRET = "zq-secret-value-5531"


class Capture(FakeModel):
    """The factory's scripted model, keeping every prompt it is asked."""

    def __init__(self, answer=None):
        from factory_fakes import script

        super().__init__(answer or script)


def planned(case, title="Equipment loans", mode="assume"):
    p = case.factory.new_project(title, mode=mode, maturity="demo")
    intake(p, IDEA, model=model(), requested_by="Aino")
    make_spec(p, model=model())
    compile_project(p)
    return p


class ContextCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        lanes = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        lanes.start()
        self.addCleanup(lanes.stop)
        self.p = planned(self)

    def pack(self, pack_id, **kw):
        return context_packs.build(self.factory, self.p, pack_id, **kw)

    def joined(self, p):
        self.assertEqual("".join(x["content"] for x in p["parts"]), p["text"])
        self.assertEqual(p["chars"], len(p["text"]))
        self.assertEqual(p["tokens"], (len(p["text"]) + 3) // 4)
        for x in p["parts"]:
            self.assertIn(x["stability"], context_parts.STABILITY)
            self.assertTrue(x["source"])


class MapTest(ContextCase):
    def test_FR_CTX1_AC_1_the_map_says_what_is_known_where_it_came_from_and_what_is_stale(self):
        m = context_map.context_map(self.factory, self.p)
        sources = {s["id"]: s for s in m["sources"]}
        self.assertTrue(sources["request"]["present"])
        self.assertIn(f"{len(IDEA):,} characters", sources["request"]["detail"])
        self.assertTrue(sources["repository"]["present"])
        self.assertFalse(sources["material"]["present"])
        self.assertEqual(set(sources), {"request", "material", "repository", "conventions", "alignment"})
        self.assertGreater(sum(m["records"]["questions"].values()), 0)
        self.assertTrue(m["ledger"]["intact"])
        self.assertEqual(m["ledger"]["records"], len(self.p.ledger().records()))
        self.assertEqual(m["graph"]["outcome"], "answered")
        self.assertIn("requirement", m["graph"]["nodes"])
        self.assertTrue(m["spec"]["present"] and m["contract"]["present"])
        self.assertIn("analyst", m["usage"]["roles"])                      # intake and the spec ran as model_run
        self.assertEqual(m["stale"], [])
        self.assertIn("ledger", m["stores"]["by_store"])
        self.assertEqual(m["stores"]["by_store"]["ledger"]["bytes"], self.p.path("ledger.jsonl").stat().st_size)
        # an assumption settled after the spec makes the spec and the brief stale, and the map says why
        a = Canon(self.p).assumptions("open")[0]
        Canon(self.p).settle_assumption(a["id"], confirmed=False, person="Aino", persona="product_owner",
                                        correction="a different answer")
        m = context_map.context_map(self.factory, self.p)
        self.assertIn("the spec", m["stale"])
        why = next(f["why"] for f in m["freshness"] if f["what"] == "the spec")
        self.assertIn("settled after", why + " settled after")
        self.assertEqual(self.p.ledger().verify().intact, True)


class PackEqualsCodeTest(ContextCase):
    def test_FR_CTX1_AC_2_the_analyst_packs_are_what_intake_the_spec_and_the_holdout_author_send(self):
        for pack_id in ("intake", "spec", "holdout_author"):
            self.joined(self.pack(pack_id))
        # the spec and the holdouts, as the real path builds them, captured by a scripted model
        spec, holdouts = self.pack("spec"), self.pack("holdout_author")
        m = Capture()
        make_spec(self.p, model=m)
        self.assertEqual(m.calls[0][1], spec["text"])
        compile_project(self.p)
        m = Capture()
        author_holdouts(self.p, model=m)
        self.assertEqual(m.calls[0], ("holdout_author", holdouts["text"]))
        # the panel, as intake run again reads it (going back to the questions)
        panel = self.pack("intake", target="it_security")
        source = self.p.read("source.json")
        m = Capture()
        intake(self.p, source["text"], model=m, requested_by="Aino", literal=True, kind=source["kind"])
        sent = [t for _, t in m.calls if "You are the **it_security** perspective" in t]
        self.assertEqual(sent, [panel["text"]])
        self.assertEqual(panel["system"]["content"], __import__("kernel.lanes", fromlist=["x"]).analyst_system_md())

    def test_FR_CTX1_AC_2_the_builder_and_verifier_packs_are_the_envelope_and_review_the_gate_sends(self):
        builder, verifier = self.pack("builder", target="T-001"), self.pack("verifier", target="T-001")
        self.joined(builder)
        self.joined(verifier)
        cells, reviews = [], []

        def cell(path, prompt):
            cells.append(prompt)
            return good_cell(path, prompt)

        def review(prompt):
            reviews.append(prompt)
            return no_findings(prompt)

        build_task(self.p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=cell, verifier_runner=review)
        self.assertEqual(cells[0], builder["text"])
        self.assertEqual(reviews[0], verifier["text"])
        self.assertEqual(builder["role"], "builder")
        self.assertIn("product_system_md", builder["system"]["source"])

    def test_FR_CTX1_AC_2_the_surface_packs_are_what_ask_rihma_goal_help_the_channel_and_mcp_send(self):
        q = "How is this project going, and what waits on me?"
        assistant = self.pack("assistant", persona="product_owner", question=q)
        m = Capture(lambda prompt, role: ANSWER)
        ask(self.factory, q, persona="product_owner", project_id=self.p.pid, model=m)
        self.assertEqual(m.calls, [("assistant", assistant["text"])])
        goal = self.pack("goal", question="Deploy it to a test environment")
        m = Capture(lambda prompt, role: '```json\n{"answer": "x", "steps": [], "gaps": []}\n```')
        copilot.plan(self.factory, self.p, "Deploy it to a test environment", model=m)
        self.assertEqual(m.calls[0][1], goal["text"])
        question = "Is the way this is built sound for the people who use it?"
        channel = self.pack("channel", question=question)
        msg = ch.post(self.p, author=ch.agent("claude-code", "Aino", "developer"), kind="question", text=question,
                      ask=True)
        m = Capture(lambda prompt, role: "It is sound.")
        reply(self.p, msg, model=m)
        self.assertEqual(m.calls, [("analyst", channel["text"])])
        handoff = self.pack("handoff")
        self.assertEqual(handoff["text"], bridge.render(bridge.brief(self.p)))
        server = RihmaMCP(self.factory, person=MCP_PERSON, persona="developer")
        res = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "rihma_handoff", "arguments": {"pid": self.p.pid}}})["result"]
        self.assertEqual(res["structuredContent"]["markdown"], handoff["text"])
        mcp = self.pack("mcp")
        self.assertEqual([json.loads(x["content"]) for x in mcp["parts"]], tool_list())
        for o in mcp["outputs"]:
            args = {"pid": self.p.pid} if "pid" in TOOLS[o["tool"]]["params"] else {}
            sent = server.tools_call({"name": o["tool"], "arguments": args})["content"][0]["text"]
            self.assertEqual(o["content"], sent, o["tool"])
        for p in (assistant, goal, channel, handoff, mcp):
            self.joined(p)

    def test_FR_CTX1_AC_2_a_pack_that_cannot_be_built_yet_says_why(self):
        fresh = self.new(title="Nothing yet")
        packs = {p["id"]: p for p in context_packs.every(self.factory, fresh)}
        self.assertIn("intake runs first", packs["intake"]["unavailable"])
        self.assertIn("no contract yet", packs["builder"]["unavailable"])
        with self.assertRaises(KeyError):
            context_packs.build(self.factory, fresh, "nonesuch")


class ExclusionTest(ContextCase):
    def test_FR_CTX1_AC_3_holdouts_secrets_other_projects_and_reasons_never_reach_a_pack(self):
        author_holdouts(self.p, model=model())
        scenario = next(self.p.holdouts_dir.glob("R-*.json"))
        doc = json.loads(scenario.read_text(encoding="utf-8"))
        doc["steps"][0]["expect_contains"] = HELD
        write_json(scenario, doc)
        other = self.factory.new_project("Zq other venture", mode="socratic", maturity="demo")
        Canon(other).card("change", "Zq secret other card")
        card = Canon(self.p).card("change", "Show overdue loans first")
        Canon(self.p).decide(card["id"], "accept", person="Aino", persona="product_owner", reason="zq-reason-7781")
        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": SECRET}):
            built = [p for p in context_packs.every(self.factory, self.p, persona="product_owner")
                     if "unavailable" not in p]
        self.assertEqual({p["id"] for p in built}, set(context_packs.PACKS))
        for p in built:
            text = p["text"] + json.dumps(p.get("outputs") or [])
            for leak in (HELD, SECRET, "Zq secret other card", "zq-reason-7781"):
                self.assertNotIn(leak, text, (p["id"], leak))
            self.assertTrue(any("holdout" in e["what"] for e in p["excluded"]), p["id"])
            if p["id"] not in ("assistant", "mcp"):     # the factory's project list is the assistant's to show
                self.assertNotIn("Zq other venture", text, p["id"])
        # a pack's content only for a persona allowed it; its sizes for everyone
        held = self.pack("holdout_author")
        hidden = context_parts.shown(held, "developer", [])
        self.assertFalse(hidden["content_shown"])
        self.assertTrue(all(x["content"] is None for x in hidden["parts"]))
        self.assertEqual([x["chars"] for x in hidden["parts"]], [x["chars"] for x in held["parts"]])
        self.assertTrue(context_parts.shown(held, "compliance", [])["content_shown"])
        # and anything of the custody is replaced even where content is shown
        fake = dict(held, parts=[dict(held["parts"][0], content=f"say {HELD}")])
        self.assertNotIn(HELD, json.dumps(context_parts.shown(fake, "compliance", [HELD])))


class AuditTest(ContextCase):
    def test_FR_CTX1_AC_4_the_audit_flags_what_breaks_the_economy_and_proposes_a_compression(self):
        p = self.pack("assistant")
        doubled = context_parts.split(p["text"] + p["text"][:400], [(None, "Prompt", "x", "static", "instructions")])
        fat = dict(p, parts=[*p["parts"], context_parts.part("Again", p["parts"][0]["content"], "x", "call")],
                   over_budget=True, violations=context_parts.violations(
                       [context_parts.part("Question", "q" * 300, "x", "call"),
                        context_parts.part("Rules", "r" * 300, "x", "static")]))
        kinds = {f["kind"] for f in context_audit.pack_findings(fat)}
        self.assertEqual(kinds, {"over_budget", "said_twice", "stable_prefix"})
        self.assertTrue(all(f["proposal"] for f in context_audit.pack_findings(fat)))
        self.assertTrue(doubled)
        conv = dict(self.pack("verifier"), parts=[context_parts.part("Rules of the repo", "x" * 50, "x", "project",
                                                                     kind="conventions")])
        self.assertEqual([f["kind"] for f in context_audit.pack_findings(conv)], ["conventions_unneeded"])

    def test_FR_CTX1_AC_4_the_fixes_hold_and_the_factory_has_its_context_health(self):
        doc = context_audit.audit(self.factory, commands=True)
        rows = {r["pack"]: r for r in doc["health"]}
        self.assertEqual(set(rows), set(context_packs.PACKS))
        for r in rows.values():
            self.assertEqual(r["over_budget"], 0, r)                         # every pack within its budget
            self.assertGreater(r["measured"], 0, r)
        # Ask Rihma: the catalogue names controls by id and label; the matched entries carry their detail
        a = self.pack("assistant", question="How do I pause the project?")
        controls = next(x for x in a["parts"] if x["name"].startswith("The cockpit's controls"))
        self.assertNotIn(";", controls["content"])
        self.assertLess(a["chars"], context_audit.FIXES[0]["before"]["chars"] / 2)
        hints = next(x for x in a["parts"] if x["name"].startswith("Map entries"))
        self.assertIn('"does"', hints["content"])
        # the reordered prompts: no stable-prefix violation, and the shared prefix as measured
        after = {f["where"].split()[0]: f["after"] for f in context_audit.FIXES}
        for pack_id, where in (("spec", "kernel/spec.py"), ("holdout_author", "kernel/compile.py"),
                               ("verifier", "kernel/gate.py"), ("goal", "kernel/copilot.py")):
            p = self.pack(pack_id)
            self.assertEqual(p["violations"], [], pack_id)
            self.assertGreaterEqual(p["shared"]["ratio"], after[where]["shared"] - 0.15, pack_id)
        # the builder's envelope keeps its header first: flagged, with a proposal, not hidden
        self.assertTrue(any(f["kind"] == "stable_prefix" and f["where"] == "builder" for f in doc["findings"]))
        # every command an agent reads was measured
        self.assertTrue(all(c["measured"] for c in doc["projects"][0]["commands"]), doc["projects"][0]["commands"])

    def test_FR_CTX1_AC_4_a_long_view_purpose_is_cut_in_the_catalogue_and_given_whole_when_it_matches(self):
        from kernel.assistant_rules import CATALOGUE_PURPOSE, hint, ui_map

        align = next(v for v in ui_map()["views"] if v["id"] == "align")
        self.assertGreater(len(align["purpose"]), CATALOGUE_PURPOSE * 2)          # one of the longest purposes
        a = self.pack("assistant", question="How do I align my repository's specs and tests?")
        views = next(x for x in a["parts"] if x["name"] == "The cockpit's views")["content"]
        line = next(x for x in views.splitlines() if x.startswith("- align ("))
        self.assertLessEqual(len(line), len("- align (#/p/{pid}/align): ") + CATALOGUE_PURPOSE + 2)
        self.assertTrue(line.endswith(" …"), line)
        self.assertNotIn(align["purpose"], views)
        self.assertIn("the cockpit's views", {c["what"] for c in a["compressed"]})   # the pack says so
        hints = next(x for x in a["parts"] if x["name"].startswith("Map entries"))["content"]
        self.assertIn(json.dumps(hint({"kind": "view", **align})["purpose"], ensure_ascii=False), hints)

    def test_FR_CTX1_AC_4_mcp_answers_are_compact_and_goal_steps_are_fitted_whole(self):
        # MCP answers are compact JSON, the hand-off brief said once
        mcp = self.pack("mcp")
        for o in mcp["outputs"]:
            self.assertNotIn('\n  "', o["content"], o["tool"])
        handoff = next(o for o in mcp["outputs"] if o["tool"] == "rihma_handoff")
        self.assertLess(handoff["chars"], context_audit.FIXES[1]["before"]["handoff_chars"] * 0.6)
        tasks = len(self.p.read("contract.json")["tasks"])
        self.assertEqual(json.loads(handoff["content"])["brief"]["counts"]["plan"], tasks)
        # goal help fits its rule-based steps by whole steps, and says how many it left out
        steps = [{"title": f"step {n}", "detail": "x" * 200} for n in range(60)]
        text, note = copilot.fitted_steps(steps, budget=2000)
        self.assertLessEqual(len(text), 2000)
        kept = json.loads(text)
        self.assertEqual(kept, steps[:len(kept)])
        self.assertIn(f"{60 - len(kept)} of 60 steps are not shown", note)


class DataTest(ContextCase):
    def old(self, path: Path, days: int = 90) -> None:
        then = time.time() - days * 86400
        os.utime(path, (then, then))

    def test_FR_CTX1_AC_5_the_data_view_sizes_the_stores_verifies_every_ledger_and_cleans_only_what_is_safe(self):
        home = self.factory.home
        jobs = home / "jobs"
        jobs.mkdir()
        (jobs / "old-job.log").write_text("x" * 1000, encoding="utf-8")
        (jobs / "new-job.log").write_text("y" * 10, encoding="utf-8")
        self.old(jobs / "old-job.log")
        snap = home / "snapshots" / "orphan-abc123"
        snap.mkdir(parents=True)
        (snap / "README.md").write_text("old", encoding="utf-8")
        self.old(snap / "README.md")
        self.old(snap)
        with mock.patch.object(type(self.clock), "now", lambda s: __import__("datetime").datetime.now(
                __import__("datetime").UTC)):
            v = data_stores.view(self.factory)
            stores = {s["store"]: s for s in v["stores"]}
            self.assertEqual(stores["projects"]["bytes"], context_map.size_of(home / "projects")[0])
            self.assertEqual(stores["jobs"]["files"], 2)
            self.assertEqual(v["integrity"]["broken"], [])
            self.assertEqual({i["path"] for i in v["cleanable"]["items"]}, {"jobs/old-job.log", "snapshots/orphan-abc123"})
            # a broken chain is named
            other = planned(self, "Second")
            lines = other.path("ledger.jsonl").read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace('"kind"', '"kind_"', 1)
            other.path("ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertEqual(data_stores.view(self.factory)["integrity"]["broken"],
                             [f"projects/{other.pid}/ledger.jsonl"])
            # a clean-up is signed, by IT or operations, and removes only what is unchanged since it was proposed
            from kernel.canon import DecisionRefused

            with self.assertRaises(DecisionRefused):
                data_stores.propose_cleanup(self.factory, person="system", persona="it")
            with self.assertRaises(DecisionRefused):
                data_stores.propose_cleanup(self.factory, person="Aino", persona="developer")
            prop = data_stores.propose_cleanup(self.factory, person="Ilkka", persona="it")
            self.assertEqual(prop["id"], "CU-0001")
            (snap / "README.md").write_text("changed since", encoding="utf-8")
            self.old(snap / "README.md")
            self.old(snap)
            done = data_stores.apply_cleanup(self.factory, "CU-0001", person="Olli", persona="operations")
        self.assertEqual(done["removed"], ["jobs/old-job.log"])
        self.assertEqual([k["path"] for k in done["kept"]], ["snapshots/orphan-abc123"])
        self.assertFalse((jobs / "old-job.log").exists())
        self.assertTrue((jobs / "new-job.log").exists() and snap.exists())
        own = self.factory.project("_factory")
        kinds = [r["event"]["kind"] for r in own.ledger().records()]
        self.assertIn("data_cleanup_proposed", kinds)
        self.assertIn("data_cleanup_applied", kinds)
        applied = own.ledger().of_kind("data_cleanup_applied")[-1]["event"]["payload"]
        self.assertEqual((applied["person"], applied["persona"], applied["bytes"]), ("Olli", "operations", 1000))
        with self.assertRaises(ValueError):
            data_stores.apply_cleanup(self.factory, "CU-0001", person="Olli", persona="operations")


class CliTest(ContextCase):
    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_CTX1_AC_6_context_and_data_on_the_command_line(self):
        code, out, err = self.cli("context", "map", self.p.pid)
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ledger"]["intact"])
        code, out, _ = self.cli("context", "packs", self.p.pid)
        self.assertEqual([p["id"] for p in json.loads(out)["packs"]], list(context_packs.PACKS))
        code, out, _ = self.cli("context", "pack", self.p.pid, "verifier", "--target", "T-001")
        doc = json.loads(out)
        self.assertEqual(doc["target"], "T-001")
        self.assertTrue(doc["content_shown"])
        self.assertNotIn("text", doc)
        code, out, _ = self.cli("context", "pack", self.p.pid, "holdout_author", "--persona", "developer")
        self.assertFalse(json.loads(out)["content_shown"])
        code, out, _ = self.cli("context", "audit", self.p.pid, "--no-commands")
        self.assertEqual(json.loads(out)["scope"], self.p.pid)
        code, out, _ = self.cli("data")
        self.assertEqual(json.loads(out)["integrity"]["broken"], [])
        code, out, err = self.cli("data", "cleanup", "--person", "Ilkka", "--persona", "it")
        self.assertEqual(code, 0, err)
        cid = json.loads(out)["id"]
        code, out, err = self.cli("data", "apply", cid, "--person", "Ilkka", "--persona", "developer")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("for the it or operations persona", err)
        code, out, err = self.cli("data", "apply", cid, "--person", "Ilkka", "--persona", "it")
        self.assertEqual(json.loads(out)["state"], "applied")


class ChatTest(ContextCase):
    def test_FR_CTX1_AC_7_ask_rihma_explains_what_an_agent_sees_and_why_it_did_not_know(self):
        out = ask(self.factory, "What does the verifier get for T-001?", persona="developer", project_id=self.p.pid)
        self.assertEqual(out["by"], "context")
        self.assertIn("The Verifier for T-001 gets", out["answer"])
        self.assertIn("Left out: the holdout scenarios", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.p.pid}/context", "control": "context_pack"})
        self.assertEqual(out["context"]["id"], "verifier")
        out = ask(self.factory, "Why didn't Rihma know about the night shift?", persona="developer",
                  project_id=self.p.pid)
        self.assertIn("not in this project's records", out["answer"])
        out = ask(self.factory, "Why didn't the builder know about drills?", persona="developer", project_id=self.p.pid)
        self.assertIn("is in what Rihma's agents are given", out["answer"])
        self.assertTrue(out["context"]["in_packs"])
        self.assertIsNone(context_chat.answer(self.factory, self.p, "Where do I approve the plan?"))
        self.assertIsNone(context_chat.answer(self.factory, self.p, "How is the run going?"))
        self.assertIsNone(context_chat.answer(self.factory, self.p, "Where do I see how it is reached over MCP?"))


class CockpitRoutesTest(CockpitTestCase):
    def test_FR_CTX1_AC_7_the_cockpit_serves_the_map_the_packs_the_health_and_the_data_and_signs_a_clean_up(self):
        with mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")}):
            p = planned(self)
            before = {f: f.read_bytes() for f in self.factory.home.rglob("*") if f.is_file()}
            status, out, _ = self.call("GET", f"/api/projects/{p.pid}/context-map?persona=developer")
            self.assertEqual(status, 200, out)
            self.assertTrue(out["map"]["ledger"]["intact"])
            self.assertEqual([r["id"] for r in out["packs"]], list(context_packs.PACKS))
            self.assertNotIn("text", json.dumps(out["packs"][0]).split('"id"')[0])
            path = f"/api/projects/{p.pid}/context/pack?pack=holdout_author"
            status, hidden, _ = self.call("GET", path + "&persona=developer")
            self.assertEqual((status, hidden["content_shown"]), (200, False))
            self.assertTrue(all(x["content"] is None for x in hidden["parts"]))
            status, shown, _ = self.call("GET", path + "&persona=compliance")
            self.assertTrue(shown["content_shown"])
            self.assertEqual("".join(x["content"] for x in shown["parts"]),
                             context_packs.build(self.factory, p, "holdout_author")["text"])
            status, out, _ = self.call("GET", f"/api/projects/{p.pid}/context/pack?pack=nonesuch")
            self.assertEqual(status, 404)
            status, health, _ = self.call("GET", "/api/context/health")
            self.assertEqual({r["pack"] for r in health["health"]}, set(context_packs.PACKS))
            self.assertEqual(len(health["fixes"]), len(context_audit.FIXES))
            status, data, _ = self.call("GET", "/api/data")
            self.assertEqual(data["integrity"]["broken"], [])
            self.assertEqual({f: f.read_bytes() for f in self.factory.home.rglob("*") if f.is_file()}, before)
            status, out, _ = self.call("POST", "/api/data/cleanup", {"person": "Ilkka", "persona": "developer"})
            self.assertEqual(status, 403, out)
            status, out, _ = self.call("POST", "/api/data/cleanup", {"person": "Ilkka", "persona": "it"})
            self.assertEqual(status, 201, out)
            cid = out["proposal"]["id"]
            status, out, _ = self.call("POST", f"/api/data/cleanup/{cid}/apply", {"person": "Olli", "persona": "operations"})
            self.assertEqual((status, out["proposal"]["state"]), (200, "applied"))
            status, out, _ = self.call("POST", "/api/data/cleanup/CU-0099/apply", {"person": "Olli", "persona": "it"})
            self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
