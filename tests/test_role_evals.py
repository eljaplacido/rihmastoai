"""FR-EVL1: Rihmasto's own evals of its agents, per Rihma role, comparing models and endpoints.

A scripted model stands for each endpoint (no model, no network): one answers well and one badly, so the comparison
says which does better on each eval set. The results are recorded per set and candidate, shown for Models setup,
never with a prompt or an answer; a confidential project's comparison refuses a hosted candidate, and a Gnomon eval
that calls models on a confidential project is refused while its role is hosted.
"""

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import gnomon_fakes as gf  # noqa: E402
from console_fakes import PERSON, attached, git_repo  # noqa: E402
from factory_fakes import FactoryTestCase, isolated_routing  # noqa: E402

from kernel import gnomon_evals_run as gr  # noqa: E402
from kernel import role_evals as rv  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.model import FakeModel  # noqa: E402

GOOD_INTAKE = {"questions": [{"text": "Who may cancel a reservation, and how late?", "why": "w", "blocking": False,
                              "proposed_answer": "the guest, until noon", "options": ["the guest", "staff only"]},
                             {"text": "Do guests pay a deposit?", "why": "w", "blocking": False,
                              "proposed_answer": "no", "options": ["no", "yes"]}]}
BAD_INTAKE = {"questions": [{"text": "Tell me more", "why": "w"}]}
GOOD_SPEC = {"criteria": [{"given": "an evening with free tables", "when": "a guest reserves for 4",
                           "then": "the reservation is listed for that evening", "check": {"kind": "test"}},
                          {"given": "a full evening", "when": "a guest reserves", "then": "it is refused with the "
                           "message \"fully booked\"", "check": {"kind": "test"}}]}
BAD_SPEC = {"criteria": [{"given": "a guest", "when": "they reserve", "then": "it works properly and is fast"}]}


def good(prompt, role):
    if "Review a request for a software solution" in prompt:
        return "```json\n" + json.dumps(GOOD_INTAKE) + "\n```"
    if "Write two to four acceptance criteria" in prompt:
        return "```json\n" + json.dumps(GOOD_SPEC) + "\n```"
    if "You are Rihma, helping a person reach a goal" in prompt:
        return "```json\n" + json.dumps({"answer": "a plan", "steps": [
            {"title": "Enable an HTTP probe", "action": {"kind": "enable_check", "check": "probe",
                                                         "route": "#/p/fixture-project/checks"}},
            {"title": "From a terminal", "action": {"kind": "command", "command": "rihmasto checks list"}}]}) + "\n```"
    q = prompt.split("The question:\n<<<\n", 1)[1].split("\n>>>", 1)[0]
    answers = {"Where do I decide": ("Open the Inbox.", {"route": "#/inbox", "control": "decide"}),
               "Where can I see": ("Health shows them.", {"route": "#/health", "control": None}),
               "How many decisions": ("3 decisions wait on you.", None),
               "Which project runs": ("Tool shed runs in production.", None),
               "Why is the tool shed": ("A probe failed in production.", None),
               "How do I pause": ("Use Pause on its overview.", {"route": None, "control": "pause"}),
               "How do I export": ("Export the evidence pack on Evidence.", {"route": None,
                                                                              "control": "export_evidence"})}
    text, nav = next(v for k, v in answers.items() if q.startswith(k))
    return "```json\n" + json.dumps({"answer": text, "navigate": nav, "propose": [], "sources": []}) + "\n```"


def bad(prompt, role):
    if "Review a request for a software solution" in prompt:
        return json.dumps(BAD_INTAKE)
    if "Write two to four acceptance criteria" in prompt:
        return json.dumps(BAD_SPEC)
    if "You are Rihma, helping a person reach a goal" in prompt:
        return json.dumps({"answer": "x", "steps": [{"title": "Fly", "action": {"kind": "teleport"}}]})
    if "How many decisions" in prompt.split("The question:", 1)[1]:
        return json.dumps({"answer": "Some decisions wait.", "navigate": None})
    return "I do not know."


class RoleEvalsTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        routing = isolated_routing(self, self.tmp)
        self.routing = routing

    def models(self, cand):
        return FakeModel(good if cand["endpoint"] == "local" else bad)

    def test_FR_EVL1_AC_8_role_evals_compare_two_endpoints_and_show_in_models_setup(self):
        self.assertEqual([c["id"] for c in rv.candidates("assistant")],          # configured, then its fallback
                         ["qwen3.6-35b@local", "glm-5.3@go"])
        out = rv.run(self.factory, person=PERSON, persona="it", model_for=self.models,
                     models=["qwen3.6-35b@local", "glm-5.3@go"])
        by = {(r["set"], r["endpoint"]): r for r in out["runs"]}
        self.assertEqual(by[("ask_answers", "local")]["score_pct"], 100.0)
        self.assertEqual(by[("ask_answers", "go")]["score_pct"], 0.0)
        self.assertEqual(by[("intake_questions", "local")]["correct"], 3)
        self.assertEqual(by[("spec_testability", "local")]["correct"], 3)
        self.assertEqual(by[("spec_testability", "go")]["correct"], 0)
        self.assertEqual(by[("goal_plans", "local")]["score_pct"], 100.0)
        line = next(x for x in rv.view(self.factory)["lines"] if "ask rihma answers" in x)
        self.assertRegex(line, r"On our evals, ask rihma answers .*100% vs .*0%")
        recorded = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("role_eval_ran")]
        self.assertEqual(len(recorded), 8)                         # four sets, two candidates each
        text = json.dumps(recorded)
        self.assertNotIn("Who may cancel", text)                   # never an answer
        self.assertNotIn("board-game", text)                       # nor a prompt
        self.assertEqual({r["person"] for r in recorded}, {PERSON})
        with self.assertRaises(gr.EvalsRefused):
            rv.run(self.factory, person=PERSON, persona="end_user", model_for=self.models)
        with self.assertRaises(ValueError):
            rv.candidates("assistant", ["no-such@nowhere"])

    def test_FR_EVL1_AC_8_a_confidential_project_refuses_hosted_candidates_and_hosted_model_evals(self):
        repo = git_repo(self.tmp / "vault", {"README.md": "# Vault\n", ".gnomon/config.toml": "[routing]\n"})
        p = attached(self.factory, repo, "Vault")
        p.update_meta(confidential=True)
        asked = []
        out = rv.run(self.factory, person=PERSON, persona="it", role="assistant", for_project=p.pid,
                     models=["m1@local", "m2@go"],
                     model_for=lambda cand: asked.append(cand["id"]) or FakeModel(good))
        self.assertEqual(asked, ["m1@local"])                       # the hosted one was never asked
        refused = [r for r in out["runs"] if r.get("refused")]
        self.assertEqual({r["endpoint"] for r in refused}, {"go"})
        self.assertTrue(p.ledger().of_kind("confidential_refused"))
        # a Gnomon eval that calls the lane's models: refused while the builder role is hosted, nothing run
        fake = gf.install(self, self.tmp / "bin")
        row = gr.run(p, "eval", person=PERSON, persona="developer")
        self.assertEqual((row["verdict"], row.get("refused")), ("not measured", "confidential"))
        self.assertIn("confidential", row["summary"])
        self.assertEqual([c for c in gf.calls(fake) if c["argv"][:1] == ["eval"]], [])
        # one that calls no model runs as usual on a confidential project
        self.assertEqual(gr.run(p, "security", person=PERSON, persona="developer")["verdict"], "passed")

    def test_FR_EVL1_AC_9_evals_roles_on_the_command_line(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(rv, "lane_model", lambda cand: FakeModel(good)), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), "evals", "roles", "--role", "assistant",
                         "--model", "m1@local", "--person", PERSON, "--persona", "developer"])
        self.assertEqual(code, 0, err.getvalue())
        text = out.getvalue()
        self.assertIn("Ask Rihma answers with m1@local", text)
        self.assertEqual(json.loads(text[text.rindex("\n{"):])["runs"][0]["score_pct"], 100.0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--home", str(self.factory.home), "evals", "history"])
        self.assertEqual(len(json.loads(out.getvalue())["results"]), 2)


if __name__ == "__main__":
    unittest.main()
