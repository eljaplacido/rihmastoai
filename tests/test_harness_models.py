"""FR-HMD1: the coding agent a person already has answers Rihmasto's text roles (kernel/harness_model.py).

The owner (2026-11-24): "I would use this with Claude Code equivalently if OpenCode is not available. I should be
able to virtually run it with any agentic harness with the help of Gnomon."

Every coding agent here is a fake executable written by the test (tests/harness_fakes.py) that answers as `claude -p
--output-format json`, `codex exec --json` and `opencode run --format json` do. No real Claude Code, Codex or OpenCode
runs, and no model or network is used. Each test has its own routing (factory_fakes.isolated_routing).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, isolated_routing  # noqa: E402
from harness_fakes import ASSISTANT_ANSWER, SHAPE_REPLY, fake_agent  # noqa: E402
from runner_fakes import logged, use  # noqa: E402

from kernel import assistant as kassistant  # noqa: E402
from kernel import confidential, lanes  # noqa: E402
from kernel import harness_model as hm  # noqa: E402
from kernel import harness_setup as hs  # noqa: E402
from kernel import models_setup as kmodels  # noqa: E402
from kernel import shape as kshape  # noqa: E402
from kernel.access_isolation import serving  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.doctor import doctor  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import GIT_ID, _git  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.model import GnomonModel, ModelError  # noqa: E402
from kernel.runners import RunnerRefused, choice  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
IT = ("Ilkka Admin", "it")
MARK = "HOLDOUT-SCENARIO-MARK-7f3a-only-the-author-sees-this"
FACTORY_PLACES = ("RIHMASTO_HOME", "RIHMA_HOME", "GNOMONFACTORY_HOME", "GF_LANES", "RIHMASTO_SECRETS_FILE", "GNOMON_CMD")


class HarnessCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.routing = isolated_routing(self, self.tmp)
        self.bin, self.log = self.tmp / "bin", self.tmp / "agent.jsonl"
        env = mock.patch.dict(os.environ, {"FAKE_HARNESS_LOG": str(self.log), lanes.LANES_ENV: str(self.tmp / "lanes"),
                                           "RIHMASTO_HOME": str(self.factory.home)})
        env.start()
        self.addCleanup(env.stop)
        hm._FOUND.clear()
        self.addCleanup(hm._FOUND.clear)

    def agent(self, kind: str, mode: str = "good") -> None:
        use(self, kind, fake_agent(self.bin, kind, mode))
        hm._FOUND.clear()

    def use(self, harness: str = "claude-code", **kw) -> dict:
        kw.setdefault("roles", "all")
        return hs.use(self.factory, harness, person=IT[0], persona=IT[1], **kw)

    def model(self) -> GnomonModel:
        return GnomonModel(lanes.ensure_analyst_lane(lanes.load_routing(), root=self.tmp / "lanes"), timeout=120)

    def runs(self, project=None) -> list:
        where = project if project is not None else factory_project(self.factory)
        return [r["event"]["payload"] for r in where.ledger().of_kind("model_run")]

    def calls(self) -> list:
        return logged(self.log)


class HeadlessTextTest(HarnessCase):
    def test_FR_HMD1_AC_1_each_harness_runs_headless_as_a_text_completion_with_no_tools(self):
        for kind in ("claude-code", "codex", "opencode"):
            self.agent(kind)
        route = {"model": "", "family": "claude", "role": "analyst"}
        out = {k: hm.run(route | {"harness": k}, "Reply with the single word OK.", role="analyst")
               for k in ("claude-code", "codex", "opencode")}
        self.assertEqual({k: (r["bucket"], r["output"]) for k, r in out.items()},
                         {k: ("result", "OK") for k in out})
        c = out["claude-code"]
        self.assertEqual((c["model"], c["cost_usd"], c["usage"]),
                         ("claude-sonnet-4-5-20250929", 0.0123, {"input": 120, "output": 40, "cache_read": 7,
                                                                 "cache_write": 5}))
        self.assertEqual(c["harness"], {"name": "claude-code", "label": "Claude Code", "version": "2.1.331"})
        self.assertEqual(c["assurance"], "run by Claude Code, not through Gnomon's lane: no Gnomon audit trail for "
                                         "this call")
        self.assertEqual(out["codex"]["usage"]["input"], 90)
        direct = hm.HarnessModel("claude-code")                           # the Model interface, without routing
        self.assertEqual(direct.ask("Reply with the single word OK.", role="assistant"), "OK")
        self.assertEqual(direct.last_record["harness"]["version"], "2.1.331")
        self.assertEqual((out["opencode"]["usage"]["output"], out["opencode"]["cost_usd"]), (20, 0.002))
        seen = {c["kind"]: c for c in self.calls()}
        claude = seen["claude-code"]["argv"]
        self.assertEqual(claude[:4], ["-p", hm.INSTRUCTION, "--output-format", "json"])
        self.assertEqual(claude[claude.index("--tools") + 1], "")                       # no tool at all
        for flag in ("--strict-mcp-config", "--no-session-persistence", "--system-prompt"):
            self.assertIn(flag, claude)
        self.assertIn("Reply with the single word OK.", seen["claude-code"]["task"])     # on standard input
        codex = seen["codex"]["argv"]
        self.assertEqual(codex[codex.index("--sandbox") + 1], "read-only")
        conf = json.loads(seen["opencode"]["config"])
        self.assertFalse(any(conf["tools"].values()))
        self.assertEqual(conf["permission"], {"edit": "deny", "bash": "deny", "webfetch": "deny"})
        for call in seen.values():                                       # an empty folder, never the repository
            self.assertEqual(call["listing"], [], call["kind"])
            self.assertNotEqual(Path(call["cwd"]).resolve(), Path.cwd().resolve())

    def test_FR_HMD1_AC_1_a_harness_that_fails_or_is_not_found_says_so(self):
        self.agent("claude-code", "fail")
        r = hm.run({"harness": "claude-code", "model": "", "family": "claude"}, "hello", role="analyst")
        self.assertEqual(r["bucket"], "apparatus_failure")
        self.assertIn("not logged in", r["stop_reason"])
        r = hm.run({"harness": "codex", "model": "", "family": "gpt"}, "hello", role="analyst")
        self.assertEqual(r["bucket"], "apparatus_failure")
        self.assertIn("Codex was not found", r["stop_reason"])


class RoutedRolesTest(HarnessCase):
    def test_FR_HMD1_AC_2_intake_spec_ask_rihma_and_the_chat_run_through_claude_code_and_are_recorded(self):
        self.agent("claude-code")
        made = self.use()
        self.assertEqual([r["role"] for r in made["roles"]], ["analyst", "holdout_author", "verifier", "assistant"])
        self.assertTrue(all(r["harness"]["name"] == "claude-code" for r in made["roles"]))
        overlay = json.loads((self.routing / "routing.local.json").read_text(encoding="utf-8"))
        self.assertEqual(overlay["endpoints"]["claude-code-custom"], {"kind": "harness", "harness": "claude-code",
                                                                       "version": "2.1.331"})
        model = self.model()
        config = (Path(model.lane_dir) / ".gnomon" / "config.toml").read_text(encoding="utf-8")
        self.assertIn(hm.PLACEHOLDER_URL, config)                       # Gnomon never reaches a model for them
        self.assertNotIn('"harness"', config)
        p = self.new(mode="assume")
        intake(p, IDEA, model=model, requested_by="Aino")
        make_spec(p, model=model)
        self.assertEqual(p.read("spec.json")["title"], "Equipment loans")
        runs = self.runs(p)
        self.assertGreaterEqual(len(runs), 2)
        self.assertTrue(all(r["harness"] == "claude-code" and r["version"] == "2.1.331" and r["ok"] for r in runs))
        self.assertEqual(runs[-1]["tokens"], {"input": 120, "output": 40, "cache_read": 7, "cache_write": 5})
        self.assertEqual((runs[-1]["model"], runs[-1]["family"], runs[-1]["cost_usd"]),
                         ("claude-sonnet-4-5-20250929", "claude", 0.0123))
        self.assertIn("not through Gnomon's lane: no Gnomon audit trail for this call", runs[-1]["assurance"])
        with serving(self.factory):                                       # no project: the factory's own ledger
            asked = kassistant.ask(self.factory, "Where do I set the model?", persona="developer", model=model)
            conv = kshape.start(self.factory, person="Aino", persona="business_owner")
            kshape.say(self.factory, conv["id"], "Drills go missing", person="Aino", persona="business_owner")
            conv = kshape.answer(self.factory, conv["id"], model)
        self.assertEqual((asked["by"], asked["answer"]), ("assistant", ASSISTANT_ANSWER))
        self.assertEqual(conv["messages"][-1]["text"], SHAPE_REPLY)
        self.assertEqual([r["role"] for r in self.runs()], ["assistant", "analyst"])
        self.assertTrue(all(c["kind"] == "claude-code" for c in self.calls()))

    def test_FR_HMD1_AC_2_the_builder_is_never_a_harness_model_and_a_harness_is_never_a_fallback(self):
        self.agent("claude-code")
        with self.assertRaisesRegex(hm.HarnessRefused, "runners set builder"):
            self.use(roles="builder")
        routing = lanes.load_routing()
        bad = {**routing, "endpoints": {**routing["endpoints"], "cc": {"kind": "harness", "harness": "claude-code"}}}
        with self.assertRaisesRegex(ValueError, "cell runner"):
            lanes.check_routing({**bad, "roles": {**bad["roles"], "builder": {"model": "x", "endpoint": "cc"}}})
        fb = {**bad["roles"]["analyst"], "fallback": {"model": "x", "endpoint": "cc"}}
        with self.assertRaisesRegex(ValueError, "never as a fallback"):
            lanes.check_routing({**bad, "roles": {**bad["roles"], "analyst": fb}})


class FamilyTest(HarnessCase):
    def test_FR_HMD1_AC_3_the_verifier_stays_another_family_than_the_builder(self):
        self.agent("claude-code")
        kmodels.set_role(self.factory, "builder", base_url="http://127.0.0.1:9/v1", model="claude-sonnet",
                         family="claude", person=IT[0], persona=IT[1], keep_fallback=False)
        with self.assertRaisesRegex(kmodels.ModelsRefused, "different model family"):
            self.use(roles="verifier")
        self.use(roles="analyst")                                         # any other role may be the same family
        kmodels.remove_role(self.factory, "builder", person=IT[0], persona=IT[1])
        self.use(roles="verifier")
        with self.assertRaisesRegex(RunnerRefused, "another model family than the builder: .* both claude"):    # a Claude Code builder runner clashes too
            choice.propose(self.factory, role="builder", runner="claude-code", person=IT[0], persona=IT[1])

    def test_FR_HMD1_AC_3_a_verifier_that_answers_with_the_builders_family_gives_no_verdict(self):
        self.agent("claude-code", "deepseek")                              # its output names a deepseek model
        self.use(roles="verifier")
        record = hm.answer(self.tmp, "You review a change. Answer findings.", role="verifier")
        self.assertEqual(record["bucket"], "apparatus_failure")
        self.assertIn("the builder's family", record["stop_reason"])
        self.assertEqual((record["family"], record["output"]), ("deepseek", ""))

    def test_FR_HMD1_AC_3_opencode_and_a_command_need_their_family_stated(self):
        self.agent("opencode")
        with self.assertRaisesRegex(hm.HarnessRefused, "name the model family"):
            self.use("opencode", roles="analyst")
        made = self.use("opencode", roles="analyst", model="anthropic/claude-sonnet-4")
        self.assertEqual(made["family"], "claude")


class ConfidentialTest(HarnessCase):
    def test_FR_HMD1_AC_4_a_hosted_harness_is_refused_for_a_confidential_project(self):
        self.agent("claude-code")
        self.use()
        p = self.new(mode="assume")
        confidential.mark(p, person="Aino", persona="product_owner")
        with self.assertRaisesRegex(confidential.ConfidentialRefused, "claude-code-custom"):
            intake(p, IDEA, model=self.model(), requested_by="Aino")
        self.assertEqual(self.calls(), [])                                 # nothing was sent
        self.assertEqual(p.ledger().of_kind("confidential_refused")[-1]["event"]["payload"]["where"], "intake")
        with self.assertRaisesRegex(hm.HarnessRefused, "cannot be declared private"):
            self.use(private=True)
        asked = kassistant.ask(self.factory, "What waits?", persona="developer", project_id=p.pid, model=self.model())
        self.assertEqual(asked["by"], "map")                               # answered from the map, nothing sent

    def test_FR_HMD1_AC_4_an_opencode_on_a_local_model_declared_private_may_serve_a_confidential_project(self):
        self.agent("opencode")
        self.use("opencode", roles="analyst", model="ollama/qwen3:32b", private=True)
        p = self.new(mode="assume")
        confidential.mark(p, person="Aino", persona="product_owner")
        intake(p, IDEA, model=self.model(), requested_by="Aino")
        self.assertTrue(self.calls())
        self.assertTrue(all(r["harness"] == "opencode" and r["family"] == "qwen" for r in self.runs(p)))


class IsolationTest(HarnessCase):
    def test_FR_HMD1_AC_5_no_repository_contract_or_holdout_reaches_a_harness_but_its_role_needs(self):
        self.agent("claude-code")
        self.use()
        p = self.new(mode="assume")
        p.holdouts_dir.mkdir(parents=True, exist_ok=True)
        (p.holdouts_dir / "R-1-AC-2.json").write_text(json.dumps({"criterion": "R-1-AC-2", "steps": [
            {"method": "GET", "path": "/items", "expect_contains": MARK}]}), encoding="utf-8")
        model = hm.ForProject(self.model(), p)
        with self.assertRaisesRegex(ModelError, "holdout scenario"):
            model.ask(f"Review this request: {MARK}", role="analyst")
        self.assertEqual(self.calls(), [])
        self.assertEqual(model.ask(f"You write acceptance scenarios. Keep {MARK}. Reply with the single word OK.",
                                   role="holdout_author"), "OK")              # the author writes them: it may
        call = self.calls()[-1]
        self.assertEqual(call["listing"], [])
        self.assertFalse(set(FACTORY_PLACES) & set(call["env"]))           # nor where the factory keeps them
        self.assertNotIn(str(self.factory.home), json.dumps(call))

    def test_FR_HMD1_AC_5_the_verifier_is_given_the_change_it_reviews_not_the_repository(self):
        self.agent("claude-code")
        self.use(roles="verifier")
        repo = self.tmp / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "app").mkdir()
        (repo / "app" / "items.py").write_text("ITEMS = []\n", encoding="utf-8")
        (repo / "contract.json").write_text('{"secret": "CONTRACT-TEXT"}\n', encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, *GIT_ID, "commit", "-q", "-m", "base")
        base = _git(repo, "rev-parse", "HEAD")
        (repo / "app" / "items.py").write_text("ITEMS = ['drill']\n", encoding="utf-8")
        _git(repo, *GIT_ID, "commit", "-q", "-am", "change")
        record = hm.answer(repo, f"You review a change. Compare it with `git diff {base} -- app tests`.",
                           role="verifier")
        self.assertEqual(record["bucket"], "result", record)
        call = self.calls()[-1]
        self.assertIn("+ITEMS = ['drill']", call["task"])
        self.assertNotIn("CONTRACT-TEXT", call["task"])
        self.assertEqual(call["listing"], [])


class SetupTest(HarnessCase):
    def test_FR_HMD1_AC_6_models_setup_lists_the_harnesses_found_and_tests_one(self):
        self.agent("claude-code")
        view = kmodels.models_view()
        found = {h["id"]: (h["found"], h["version"]) for h in view["harnesses"]}
        self.assertEqual(found, {"claude-code": (True, "2.1.331"), "codex": (False, None), "opencode": (False, None)})
        self.assertEqual([p["label"] for p in view["harness_presets"]],
                         ["Use Claude Code (your login)", "Use Codex", "Use OpenCode"])
        self.assertFalse(view["ready"])
        self.use(roles="analyst,assistant")
        view = kmodels.models_view()
        self.assertTrue(view["ready"])                                     # no Gnomon, no key: the harness answers
        analyst = next(r for r in view["roles"] if r["role"] == "analyst")
        self.assertEqual((analyst["harness"]["label"], analyst["readiness"]["state"], analyst["local"]),
                         ("Claude Code", "ready", False))
        test = kmodels.probe_role("analyst")
        self.assertTrue(test["ok"], test)
        self.assertEqual((test["reply"], test["host"]), ("OK", "Claude Code on this machine"))
        self.assertIsInstance(test["latency_ms"], int)
        self.assertIn("slower than an API endpoint", test["note"])
        self.assertEqual(self.runs(), [])                                  # Test records nothing
        self.agent("claude-code", "fail")
        self.assertIn("not logged in", kmodels.probe_role("analyst")["error"])

    def test_FR_HMD1_AC_6_rihmasto_models_use_is_signed_and_recorded(self):
        self.agent("claude-code")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), "models", "use", "claude-code", "--roles",
                         "analyst,assistant", "--person", IT[0], "--persona", IT[1]])
        self.assertEqual(code, 0)
        shown = json.loads(out.getvalue())
        self.assertEqual(([r["role"] for r in shown["roles"]], shown["version"]), (["analyst", "assistant"], "2.1.331"))
        record = factory_project(self.factory).ledger().of_kind("models_use")[-1]["event"]["payload"]
        self.assertEqual((record["person"], record["harness"], record["roles"], record["family"]),
                         (IT[0], "claude-code", ["analyst", "assistant"], "claude"))
        with self.assertRaises(DecisionRefused):
            hs.use(self.factory, "claude-code", person="factory", persona="it")
        self.agent("codex", "good")
        use(self, "codex", [str(self.tmp / "nowhere" / "codex")])
        hm._FOUND.clear()
        with self.assertRaisesRegex(hm.HarnessRefused, "Codex was not found"):
            self.use("codex")

    def test_FR_HMD1_AC_7_doctor_suggests_the_harness_found_when_a_key_is_missing(self):
        found = [{"id": "claude-code", "label": "Claude Code", "version": "2.1.331", "family": "claude"}]
        report = doctor(self.factory.home, gnomon=["gnomon-not-here"], environ={}, harnesses=found)
        self.assertEqual(len(report["suggestions"]), 1)
        self.assertTrue(report["suggestions"][0].startswith("No API key? Claude Code found: use it."))
        self.assertIn("rihmasto models use claude-code", report["suggestions"][0])
        self.assertEqual(doctor(self.factory.home, environ={}, gnomon=["gnomon-not-here"])["suggestions"], [])
        self.agent("claude-code")
        self.use()
        again = doctor(self.factory.home, gnomon=["gnomon-not-here"], environ={}, harnesses=found)
        self.assertEqual((again["suggestions"], again["harness_roles"]),
                         ([], ["analyst", "holdout_author", "verifier", "assistant"]))
