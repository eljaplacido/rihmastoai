"""FR-NVL1: never lost, who acted, Harness and enforcement, decision triage and assumption weights, through the real
cockpit server on a temp factory (tests/test_cockpit.py CockpitTestCase). Every model here is a fake; no answer below
asks one: each comes by rule."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import assumption_weight, neverlost, triage, who_acted  # noqa: E402
from kernel import harness_enforcement as enforcement  # noqa: E402  (Gnomon's enforcement on or off, FR-NVL1)
from kernel.canon import Canon  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

DEV = {"person": "Ida Example", "persona": "developer"}
ROUTING = {"roles": {"assistant": {"model": "sonnet", "endpoint": "cc"}, "builder": {"model": "m", "endpoint": "go"}},
           "models": {"sonnet": {"family": "claude"}},
           "endpoints": {"cc": {"kind": "harness", "harness": "claude-code"},
                         "go": {"kind": "openai", "url": "https://models.example/v1/chat/completions"},
                         "here": {"kind": "openai", "url": "http://127.0.0.1:8080/v1/chat/completions"}}}


class NeverLostTest(CockpitTestCase):
    def why(self, pid, **q):
        query = "&".join(f"{k}={v}" for k, v in dict(q, project=pid or "").items())
        status, out, _ = self.call("GET", "/api/why?" + query.replace(" ", "%20"))
        self.assertEqual(status, 200, out)
        return out

    def ask(self, pid, question, **extra):
        status, out, _ = self.call("POST", "/api/assistant", {"question": question, "persona": "developer",
                                                              "project": pid, "person": "Ida Example", **extra})
        self.assertEqual(status, 200, out)
        return out

    # -- AC-1: why, by rule ---------------------------------------------------------------------------------------

    def test_FR_NVL1_AC_1_why_answers_by_rule_from_catalogue_basis_and_error_with_the_step_that_fills_it(self):
        built = self.built_project()
        fresh = self.new(title="Fresh one")
        out = self.why(built.pid, view="releases")
        self.assertEqual(out["by"], "why")
        self.assertIn("work is accepted but nothing has been released yet", out["answer"])
        self.assertEqual(out["fill"], {"label": "Start a release", "view": "releases", "control": "build_pack",
                                       "route": f"#/p/{built.pid}/releases"})
        self.assertEqual(out["navigate"], {"route": f"#/p/{built.pid}/releases", "control": "build_pack"})
        self.assertEqual(out["who"]["how"], "by rule")
        self.assertEqual(out["who"]["model"], "no model")
        # the same view on a project that has built nothing: the first rule whose condition holds
        self.assertIn("none has yet", self.why(fresh.pid, view="releases")["answer"])
        self.assertIn("written once the questions are settled", self.why(fresh.pid, view="spec")["answer"])
        # a field not measured: the field's words pick the rule, the record's own basis is quoted back
        out = self.why(built.pid, view="insights", field="Cost per task", kind="not_measured",
                       basis="the run recorded no token counts")
        self.assertIn("Cost per task on", out["answer"])
        self.assertIn('The record says: "the run recorded no token counts"', out["answer"])
        self.assertEqual((out["fill"]["view"], out["fill"]["control"]), ("models", "models_open"))
        # a value that names a view ("Track: Not measured" in a project's header) is answered by that view's rules
        out = self.why(fresh.pid, view="releases", field="Track", kind="not_measured", basis="Track: Not measured")
        self.assertIn("progress is tracked against tasks", out["answer"])
        # an error, classified by its words
        for message, view, control in (
                ("as business_owner you are not granted the developer persona here", "home", "persona"),
                ("the assistant model gave no usable answer", "models", "models_open"),
                ("refused: the project is paused", "overview", "resume"),
                ("internal error: KeyError", "incidents_all", "investigate_incident"),
                ("something nobody has seen", "incidents_all", "investigate_incident")):
            out = self.why(built.pid, view="tasks", kind="error", basis=message)
            self.assertEqual((out["fill"]["view"], out["fill"]["control"]), (view, control), message)
            self.assertIn("The message was:", out["answer"])
        # Why? Ask Rihma sends its context with the question: the same answer, by rule, in Ask Rihma
        out = self.ask(built.pid, "Why is this empty here?", why={"view": "releases", "field": "", "kind": "empty",
                                                                   "basis": "Nothing delivered yet."})
        self.assertEqual(out["by"], "why")
        self.assertEqual(out["fill"]["control"], "build_pack")
        self.assertIn('The record says: "Nothing delivered yet."', out["answer"])
        self.assertEqual(out["who"]["how"], "by rule")

    # -- AC-2: the same by chat -----------------------------------------------------------------------------------

    def test_FR_NVL1_AC_2_typed_questions_get_the_same_answers_by_rule(self):
        built = self.built_project()
        asking = self.intake_project(mode="socratic")
        out = self.ask(built.pid, "Why is Releases empty?")
        self.assertEqual(out["by"], "why")
        self.assertEqual(out["fill"]["control"], "build_pack")
        self.assertEqual(self.ask(built.pid, "why is the cost per task not measured?")["fill"]["view"], "models")
        out = self.ask(asking.pid, "I have 50 decisions. What blocks work? Assume the rest")
        self.assertEqual(out["by"], "triage")
        self.assertEqual(out["triage"]["blocking"][0]["card"], "C-0001")
        self.assertIn("block", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{asking.pid}/triage", "control": "triage_assume"})
        out = self.ask(built.pid, "Which assumptions grew in importance?")
        self.assertEqual(out["by"], "triage")
        self.assertEqual(self.ask(built.pid, "who acted here?")["navigate"]["route"], f"#/p/{built.pid}/who")
        out = self.ask(built.pid, "If I change harness, does Gnomon still enforce its structure?")
        self.assertIn("never whether the gate decides", out["answer"])
        # outside a project the triage ranks every project's blocking decisions at once (FR-NVL2)
        status, out, _ = self.call("POST", "/api/assistant", {"question": "what blocks work? triage my decisions",
                                                              "persona": "developer", "person": "Ida Example"})
        self.assertEqual((status, out["by"]), (200, "triage"))
        self.assertEqual(out["navigate"]["route"], "#/triage")
        self.assertEqual(out["triage_all"]["blocking"][0]["project"], asking.pid)
        # a question about something else is not taken
        self.assertIsNone(neverlost.chat_answer(self.factory, built, "Why did the gate fail on T-001?"))

    # -- AC-4: who acted --------------------------------------------------------------------------------------------

    def test_FR_NVL1_AC_4_every_answer_and_every_run_says_who_acted_and_whether_gnomon_applied(self):
        built = self.built_project()
        out = self.ask(built.pid, "Where is the evidence?")
        self.assertEqual(out["who"]["agent"], "Ask Rihma")
        self.assertEqual((out["who"]["how"], out["who"]["model"], out["who"]["where"]),
                         ("by rule", "no model", "on this machine"))
        rows = who_acted.runs(self.factory, built)
        first = rows[0]
        self.assertEqual((first["id"], first["role"], first["harness"], first["applied"], first["gate"]),
                         ("T-001/0", "builder", "Gnomon", True, "passed"))
        self.assertIn("contract criteria R-1-AC-1, R-1-AC-2", first["gnomon"])
        self.assertIn("in-run policy enforced by Gnomon", first["gnomon"])
        # a call a harness answered says it was outside Gnomon's lane, and where it ran
        built.log("model_run", {"role": "verifier", "harness": "claude-code", "label": "Claude Code", "model": "sonnet",
                                "task": "T-001"})
        last = who_acted.runs(self.factory, built)[-1]
        self.assertEqual((last["agent"], last["harness"], last["where"], last["applied"]),
                         ("Rihma's verifier", "Claude Code", "hosted", False))
        self.assertIn("no Gnomon audit trail", last["gnomon"])
        # an answer a model wrote: which harness, model and where, from the routing
        with mock.patch("kernel.harness_enforcement.routing_now", return_value=ROUTING):
            said = who_acted.for_answer(self.factory, built, {"by": "assistant"}, model=object())
        self.assertEqual((said["how"], said["harness"], said["model"], said["where"]),
                         ("model", "Claude Code", "sonnet", "hosted"))
        self.assertIn("not through Gnomon's lane", said["gnomon"])
        status, out, _ = self.call("GET", f"/api/projects/{built.pid}/who")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["runs"][0]["id"], "T-001/0")
        self.assertEqual(out["harness"]["roles"][0]["role"], "builder")

    # -- AC-5: Harness and enforcement ------------------------------------------------------------------------------

    def test_FR_NVL1_AC_5_gnomon_enforcement_is_on_by_default_and_an_opt_out_is_explicit_and_recorded(self):
        built = self.built_project()
        status, out, _ = self.call("GET", "/api/harness-enforcement")
        self.assertEqual((status, out["state"]["on"], out["state"]["from"]), (200, True, "default"))
        builder = out["roles"][0]
        self.assertEqual((builder["role"], builder["label"], builder["in_run"]), ("builder", "Gnomon", True))
        claude = next(o for o in builder["others"] if o["harness"] == "claude-code")
        self.assertIn("checked after the run by the same gate", claude["then"])
        # refused: no reason, or a persona that may not set it; nothing is recorded
        status, out, _ = self.call("PUT", "/api/harness-enforcement", {"on": False, "reason": "", "person": "Ilkka",
                                                                 "persona": "it"})
        self.assertEqual(status, 400, out)
        status, out, _ = self.call("PUT", "/api/harness-enforcement", {"on": False, "reason": "a trial", **DEV})
        self.assertEqual(status, 403, out)
        self.assertIsNone(factory_project(self.factory, False))
        status, out, _ = self.call("PUT", "/api/harness-enforcement", {"on": False, "reason": "a harness trial",
                                                                 "person": "Ilkka", "persona": "it"})
        self.assertEqual((status, out["state"]["on"]), (200, False), out)
        rec = factory_project(self.factory).ledger().of_kind("enforcement_set")[-1]["event"]["payload"]
        self.assertEqual((rec["on"], rec["reason"], rec["person"], rec["scope"]), (False, "a harness trial", "Ilkka",
                                                                                     "platform"))
        # a project follows the platform unless it has its own; the gate is never skipped
        st = enforcement.state(self.factory, built)
        self.assertEqual((st["on"], st["from"]), (False, "platform"))
        self.assertIn("never skips it", st["gate"])
        self.assertNotIn("opted out", who_acted.runs(self.factory, built)[0]["gnomon"])   # ran before it (FR-NVL2)
        status, out, _ = self.call("PUT", f"/api/projects/{built.pid}/harness-enforcement", {"on": True, **DEV})
        self.assertEqual((status, out["state"]["on"], out["state"]["from"]), (200, True, "project"), out)
        self.assertEqual(built.ledger().of_kind("enforcement_set")[-1]["event"]["payload"]["person"], "Ida Example")
        self.assertFalse(enforcement.state(self.factory)["on"])
        self.assertTrue(who_acted.runs(self.factory, built)[0]["applied"])

    # -- AC-6: decision triage ------------------------------------------------------------------------------------

    def test_FR_NVL1_AC_6_triage_ranks_what_blocks_work_and_confirms_the_rest_as_the_persons_delegated_choice(self):
        asking = self.intake_project(mode="socratic")
        status, t, _ = self.call("GET", f"/api/projects/{asking.pid}/triage")
        self.assertEqual(status, 200, t)
        self.assertEqual([b["card"] for b in t["blocking"]], ["C-0001"])
        self.assertIn("requirements cannot be written", t["blocking"][0]["why"])
        offered = t["proposal"]["cards"]
        self.assertTrue(offered)
        self.assertNotIn("C-0001", offered)
        self.assertTrue(all(r["assume"]["said"] for r in t["rest"]))
        self.assertIn(f"I propose to assume the other {len(offered)}", t["said"])
        status, out, _ = self.call("POST", f"/api/projects/{asking.pid}/triage/assume",
                                   {"person": "Aino", "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        self.assertEqual(sorted(out["assumed"]), sorted(offered))
        canon = Canon(asking)
        self.assertEqual(canon.get_card("C-0001")["state"], "open")          # what blocks work stays with the person
        rec = asking.ledger().of_kind("triage_assumed")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["blocking"]), ("Aino", ["C-0001"]))
        self.assertEqual(sorted(rec["assumed"]), sorted(offered))
        self.assertEqual(len(canon.assumptions("open")), len(offered))
        # a change is deferred until it matters, decided only by a persona that may; the rest is left, said why
        built = self.built_project()
        change = Canon(built).card("change", "Show overdue loans first", refs={"requirements": ["R-1"]})["id"]
        with self.assertRaisesRegex(triage.TriageRefused, "a developer may not decide this"):
            triage.confirm(built, person="Ida Example", persona="developer", cards=[change, "C-9999"])
        self.assertEqual(built.ledger().of_kind("triage_assumed"), [])          # refused: nothing recorded
        out = triage.confirm(built, person="Pia Example", persona="product_owner", cards=[change, "C-9999"])
        self.assertEqual([x["card"] for x in out["left"]], ["C-9999"])
        self.assertEqual(out["deferred"], [change])
        self.assertIn("decision triage", Canon(built).get_card(change)["decision"]["reason"])

    # -- AC-7: assumption weights -----------------------------------------------------------------------------------

    def test_FR_NVL1_AC_7_an_assumption_grows_as_work_touches_it_and_blocks_only_when_the_next_step_rests_on_it(self):
        p = self.built_project()                         # assume mode: A-001 on Q-001 (R-2, T-002 next), A-002 (R-3)
        rows = {w["id"]: w for w in assumption_weight.weights(p)}
        a1 = rows["A-001"]
        self.assertEqual(a1["requirements"], ["R-2"])
        self.assertEqual(sorted(t["kind"] for t in a1["triggers"]), ["requirement", "task", "test"])
        self.assertFalse(a1["grew"])
        # a change on its requirement: it grew, and T-002 (the next task to build) rests on it, so it blocks
        p.log("change_triaged", {"card": "C-0042", "class": "change_request", "requirements": ["R-2"]})
        a1 = {w["id"]: w for w in assumption_weight.weights(p)}["A-001"]
        self.assertTrue(a1["grew"])
        self.assertEqual(a1["trigger"], "C-0042 changes R-2, which rests on it")
        self.assertTrue(a1["blocking"])
        self.assertIn("T-002, the next task to build", a1["blocks"])
        t = triage.triage(p)
        self.assertEqual([b.get("assumption") for b in t["blocking"]], ["A-001"])
        self.assertIn("grew in importance and now blocks the next step", t["blocking"][0]["why"])
        # an overdue review and a failed gate: A-002 grows, but T-003 is not next, so it is resurfaced, not blocking
        items = json.loads(p.path("canon", "assumptions.json").read_text(encoding="utf-8"))
        for a in items:
            if a["id"] == "A-002":
                a["due"] = "2026-11-01"
        p.path("canon", "assumptions.json").write_text(json.dumps(items), encoding="utf-8")
        p.log("gate", {"task": "T-003", "verdict": "failed", "objections": ["R-3-AC-1 failed"]})
        a2 = {w["id"]: w for w in assumption_weight.weights(p)}["A-002"]
        self.assertTrue(a2["grew"])
        self.assertFalse(a2["blocking"])
        self.assertEqual(a2["trigger"], "a gate failed on T-003, which builds on it")
        self.assertIn("its review was due on 2026-11-01", [x["said"] for x in a2["triggers"]])
        self.assertIn("A-002 grew in importance: reconsider it", a2["said"])
        self.assertIn("A-002", [g["id"] for g in triage.triage(p)["grew"]])


if __name__ == "__main__":
    unittest.main()
