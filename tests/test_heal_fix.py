"""FR-HEAL1: Investigate with Rihma, and a fix through the gate sent as a pull request on a person's approval.

A Rihma agent investigates an incident with a scripted model: its diagnosis, classification, proposed fix and trace
in the incident's channel thread; by rule without a model; nothing sent for a confidential project whose analyst is
hosted. The fix it proposes goes through the gate on a branch of its own (fail-first, the suite, the verifier) in a
working clone, and its pull request opens with a fake ``gh`` first on PATH, only on a person's approval, never on a
default branch. A Rihmasto bug is prepared against a development repository the test makes, and needs the IT
persona. No real model and no real GitHub run here (tests/heal_fakes.py).
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import heal_fakes  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agent_channel as ch  # noqa: E402
from kernel import heal_fix, heal_investigate  # noqa: E402
from kernel import incidents as inc  # noqa: E402
from kernel.model import FakeModel  # noqa: E402

DEV = {"person": "Aino Example", "persona": "developer"}
ANSWER = {"classification": "project bug", "diagnosis": "parse() calls int() on an empty text, which raises.",
          "next": {"kind": "fix", "text": "read an empty text as 0"}, "fix": heal_fakes.FIX}


def scripted(prompt: str, role: str) -> str:
    assert role == "analyst" and "investigating an incident" in prompt, prompt[:80]
    return "```json\n" + json.dumps(ANSWER) + "\n```"


class InvestigateTest(CockpitTestCase):
    def test_FR_HEAL1_AC_4_a_rihma_agent_investigates_with_a_trace_in_the_incidents_thread(self):
        project, doc = heal_fakes.attached_incident(self)
        self.server.assistant_model = FakeModel(scripted)
        status, out, _ = self.call("POST", f"/api/incidents/{doc['id']}/investigate", DEV)
        self.assertEqual(status, 200, out)
        found = out["investigation"]
        self.assertEqual((found["classification"], found["next"]["kind"]), ("project bug", "fix"))
        self.assertEqual(found["fix"]["test"]["path"], "tests/test_incident.py")
        trace = found["trace"]
        self.assertEqual((trace["basis"], trace["role"]), ("model", "analyst"))
        self.assertIn("the traceback", trace["read"])
        self.assertIn("the remedies Rihmasto knows for this fingerprint", trace["read"])
        self.assertGreater(trace["context_chars"], 0)
        thread = ch.messages(project, thread=heal_investigate.thread_of(doc["id"]))
        self.assertEqual([m["author"]["kind"] for m in thread], ["person", "rihma"])
        self.assertEqual(thread[1]["trace"]["basis"], "model")
        self.assertEqual(inc.get(self.factory, doc["id"])["state"], "investigating")
        kinds = [r["event"]["kind"] for r in project.ledger().records()]
        self.assertIn("incident_investigated", kinds)

    def test_FR_HEAL1_AC_4_without_a_model_it_reads_by_rule_and_a_confidential_project_sends_nothing(self):
        p = self.new()
        doc = inc.open_incident(self.factory, kind="product_not_running", where="try", project=p.pid,
                                message="release 2 does not run")
        found = heal_investigate.investigate(self.factory, doc["id"], **{"person": "Aino", "persona": "developer"})
        self.assertEqual((found["classification"], found["next"]["remedy"]), ("user setup", "start_on_road"))
        self.assertEqual(found["trace"]["basis"], "rule")
        p.update_meta(confidential=True)
        other = inc.open_incident(self.factory, kind="view_broken", where="spec", project=p.pid, message="boom")
        model = FakeModel(scripted)
        with mock.patch("kernel.confidential.refusal", return_value="refused: hosted"):
            found = heal_investigate.investigate(self.factory, other["id"], model=model, person="Aino",
                                                 persona="developer")
        self.assertEqual(model.calls, [])                               # nothing was sent
        self.assertEqual(found["trace"]["basis"], "rule")

    def test_FR_HEAL1_AC_4_a_traceback_through_rihmastos_own_code_is_a_rihmasto_bug(self):
        doc = inc.open_incident(self.factory, kind="server_error", where="get_outputs", message="KeyError: 'x'",
                                context={"trace": ['  File "/srv/rihmasto/kernel/outputs.py", line 40, in read']})
        found = heal_investigate.investigate(self.factory, doc["id"], person="Aino", persona="developer")
        self.assertEqual((found["classification"], found["next"]["kind"], found["next"]["target"]),
                         ("rihmasto bug", "fix", "rihmasto"))


class FixAndPullRequestTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.project, self.doc = heal_fakes.attached_incident(self)
        self.gh_log = heal_fakes.fake_gh(self, self.tmp / "heal")
        self.server.fix_verifier = lambda prompt: heal_fakes.NO_FINDINGS

    def test_FR_HEAL1_AC_5_a_fix_goes_through_the_gate_and_its_pull_request_opens_only_on_approval(self):
        repo = Path(self.project.meta["attached"]["repo"])
        head_before = heal_fakes._git(repo, "rev-parse", "HEAD")
        status, out, _ = self.call("POST", f"/api/incidents/{self.doc['id']}/fix", {"fix": heal_fakes.FIX, **DEV})
        self.assertEqual(status, 201, out)
        fix = out["fix"]
        self.assertEqual(fix["branch"], "rihmasto/fix-" + self.doc["id"].lower())
        signals = {s["name"]: s["verdict"] for s in fix["gate"]["signals"]}
        self.assertEqual(signals, {"tests": "passed", "fail_first": "passed", "verifier": "passed"})
        self.assertEqual(fix["gate"]["verdict"], "passed")
        self.assertEqual(heal_fakes._git(repo, "rev-parse", "HEAD"), head_before)   # the person's tree untouched
        # refused without approval, and for a persona that may not approve; gh never called
        status, refused, _ = self.call("POST", f"/api/fixes/{fix['id']}/pr", DEV)
        self.assertEqual(status, 403, refused)
        self.assertIn("approval", refused["error"])
        status, refused, _ = self.call("POST", f"/api/fixes/{fix['id']}/pr", {"approve": True, "person": "Sanna",
                                                                               "persona": "stakeholder"})
        self.assertEqual(status, 403, refused)
        self.assertEqual(heal_fakes.gh_calls(self.gh_log), [])
        status, out, _ = self.call("POST", f"/api/fixes/{fix['id']}/pr", {"approve": True, **DEV})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["fix"]["pr"]["url"], "https://github.example/acme/calc/pull/7")
        calls = [c["argv"] for c in heal_fakes.gh_calls(self.gh_log)]
        self.assertEqual(calls[0][:2], ["auth", "status"])
        create = calls[1]
        self.assertEqual(create[:2], ["pr", "create"])
        self.assertEqual(create[create.index("--head") + 1], fix["branch"])
        self.assertEqual(create[create.index("--base") + 1], "main")
        remote = self.tmp / "heal" / "remote.git"
        self.assertEqual(heal_fakes._git(remote, "rev-parse", "main"), head_before)  # main never pushed to
        self.assertEqual(heal_fakes._git(remote, "rev-parse", fix["branch"]), fix["head"])
        kinds = [r["event"]["kind"] for r in self.project.ledger().records()]
        self.assertIn("incident_fix_prepared", kinds)
        self.assertIn("fix_pr_opened", kinds)
        status, again, _ = self.call("POST", f"/api/fixes/{fix['id']}/pr", {"approve": True, **DEV})
        self.assertEqual(status, 409)                                           # one pull request per fix

    def test_FR_HEAL1_AC_5_a_test_that_does_not_fail_first_keeps_the_gate_from_passing(self):
        lazy = dict(heal_fakes.FIX, test={"path": "tests/test_incident.py", "content": heal_fakes.REPRO.replace(
            "parse(''), 0", "parse('3'), 3")})
        made = heal_fix.prepare(self.factory, self.doc["id"], fix=lazy, verifier=lambda p: heal_fakes.NO_FINDINGS,
                                person="Aino", persona="developer")
        self.assertEqual(made["gate"]["verdict"], "failed")
        with self.assertRaisesRegex(heal_fix.FixRefused, "gate did not pass"):
            heal_fix.open_pr(self.factory, made["id"], approve=True, person="Aino", persona="developer")
        with self.assertRaisesRegex(heal_fix.FixRefused, "protected"):
            heal_fix.prepare(self.factory, self.doc["id"], person="Aino", persona="developer",
                             fix=dict(heal_fakes.FIX, change=[{"path": "contract.json", "content": "{}"}]))

    def test_FR_HEAL1_AC_5_without_gh_signed_in_it_gives_the_branch_and_the_exact_commands(self):
        heal_fakes.fake_gh(self, self.tmp / "heal", signed_in=False)
        made = heal_fix.prepare(self.factory, self.doc["id"], fix=heal_fakes.FIX, person="Aino", persona="developer",
                                verifier=lambda p: heal_fakes.NO_FINDINGS)
        out = heal_fix.open_pr(self.factory, made["id"], approve=True, person="Aino", persona="developer")
        self.assertEqual((out["state"], out["pr"]["url"]), ("pr_ready", None))
        self.assertIn("gh pr create", out["pr"]["commands"][1])
        self.assertIn(made["branch"], out["pr"]["commands"][0])

    def test_FR_HEAL1_AC_5_a_rihmasto_bug_is_prepared_against_the_development_repository_and_needs_the_owner(self):
        dev = heal_fakes.make_repo(self.tmp / "rihmasto-dev")
        doc = inc.open_incident(self.factory, kind="server_error", where="get_outputs", message="ValueError: ''")
        with mock.patch.dict(os.environ, {heal_fix.DEV_REPO_ENV: str(dev)}):
            made = heal_fix.prepare(self.factory, doc["id"], fix=heal_fakes.FIX, target="rihmasto", person="Aino",
                                    persona="developer", verifier=lambda p: heal_fakes.NO_FINDINGS)
            self.assertEqual((made["target"], made["gate"]["verdict"]), ("rihmasto", "passed"))
            self.assertIn("CI on the pull request", json.dumps(made["gate"]))
            with self.assertRaisesRegex(heal_fix.FixRefused, "owner of this Rihmasto"):
                heal_fix.open_pr(self.factory, made["id"], approve=True, person="Aino", persona="developer")
            out = heal_fix.open_pr(self.factory, made["id"], approve=True, person="Ilkka", persona="it")
        self.assertEqual(out["state"], "pr_opened")


if __name__ == "__main__":
    unittest.main()
