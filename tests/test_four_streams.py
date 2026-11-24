"""Four work streams made to work together: the harness runners, the projects' own AI tool conventions, the
owner's decisions (the look at the spec before building, confidential work) and automations.

- FR-HRN1-AC-11: a harness other than Gnomon is given the conventions that apply to the files its task may write,
  matched as a Gnomon builder's envelope matches them (kernel/agent_context_use.py).
- FR-HRN1-AC-12: a confidential project's role run by another harness on a hosted model is refused as a hosted
  role is.
- FR-HRN1-AC-13: the runner card and the go-ahead card show in What's next and the Inbox.
- FR-AUT1-AC-16: an automation never decides the go-ahead card or the runner card.

Every harness is a fake executable (tests/runner_fakes.py); scripted models only; no network.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import model  # noqa: E402
from test_project_change import PO, ChangeCase  # noqa: E402
from test_runners import DEV, IT, RunnerCase, logged  # noqa: E402

from kernel import automations as au  # noqa: E402
from kernel import automations_run as run  # noqa: E402
from kernel import confidential, go_ahead  # noqa: E402
from kernel.agent_context import from_folder  # noqa: E402
from kernel.agent_context_use import HEADING, builder_lines  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.next_step import next_step  # noqa: E402
from kernel.runners import choice  # noqa: E402
from kernel.runners import cell as runner_cell  # noqa: E402
from kernel.runners.base import Envelope, compose_prompt, conventions  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


class HarnessConventionsTest(RunnerCase):
    def folder(self) -> Path:
        root = self.tmp / "work"
        write(root, "AGENTS.md", "# House\n\nUse four-space indents.\n")
        write(root, ".cursor/rules/web.mdc", "---\ndescription: Web pages\nglobs: [\"web/**/*.ts\"]\n---\n\n"
                                             "No inline styles.\n")
        write(root, ".cursor/rules/db.mdc", "---\ndescription: Database migrations\n---\n\nMigrations are "
                                            "reversible.\n")
        return root

    def test_FR_HRN1_AC_11_a_harness_gets_the_rules_for_the_files_it_may_write_matched_as_gnomons_envelope(self):
        root = self.folder()
        python = conventions(root, ["app/**"])
        self.assertIn("Use four-space indents.", python)
        self.assertNotIn("No inline styles.", python)                          # the web rule is not for this task
        self.assertIn("Database migrations", python)                           # a rule on request is named
        self.assertNotIn("Migrations are reversible.", python)
        same = "\n".join(builder_lines(from_folder(root, keep_text=True), ["app/**"])).strip()
        self.assertEqual(python, same)                                         # one matching for both runners
        web = conventions(root, ["web/pages/home.ts"])
        self.assertIn("No inline styles.", web)
        self.assertIn("No inline styles.", conventions(root))                  # a verifier: those that apply anywhere
        # an adopted project's envelope already holds the section: the harness is not given it twice
        envelope = f"# Envelope T-001\n\n{HEADING}\n\nUse four-space indents.\n"
        self.assertEqual(conventions(root, ["app/**"], prompt=envelope), "")
        task = compose_prompt(Envelope(task="T-001", prompt="# Envelope T-001", write_scope=["app/**"],
                                       conventions=python))
        self.assertEqual(task.count(HEADING), 1)
        self.assertEqual(conventions(self.tmp / "empty"), "")

    def test_FR_HRN1_AC_11_a_harness_build_hands_over_the_matched_conventions(self):
        p = self.compiled(agents="Use four-space indents. Name tests after the criterion.\n")
        self.harness("claude-code")
        self.approve("builder", "claude-code", project=p.pid)
        out = self.build(p)
        self.assertEqual(out["status"], "merged", out)
        task = logged(self.log)[-1]["task"]
        self.assertEqual(task.count(HEADING), 1)
        self.assertIn("Use four-space indents.", task)
        self.assertIn("AGENTS.md (Codex, Cursor and other agents; applies to the whole project)", task)


class ConfidentialRunnerTest(RunnerCase):
    def test_FR_HRN1_AC_12_a_confidential_projects_harness_on_a_hosted_model_is_refused_as_a_hosted_role(self):
        p = self.compiled()
        confidential.mark(p, person=PO["person"], persona=PO["persona"])
        self.harness("claude-code")
        self.approve("builder", "claude-code", project=p.pid)
        with self.assertRaises(confidential.ConfidentialRefused) as said:
            self.build(p)
        self.assertIn("confidential", str(said.exception))
        self.assertIn("api.anthropic.com", str(said.exception))
        refused = p.ledger().of_kind("confidential_refused")[-1]["event"]["payload"]
        self.assertEqual(refused["where"], "build")
        self.assertEqual([(h["role"], h["which"], h["endpoint"]) for h in refused["hosted"]],
                         [("builder", "runner", "claude-code")])
        self.assertEqual(p.ledger().of_kind("runner_ran"), [])                   # no cell ran
        self.assertFalse(self.log.exists() and logged(self.log))                 # nothing was sent to the harness

    def test_FR_HRN1_AC_12_outside_the_sandbox_any_harness_is_refused_and_inside_it_a_local_endpoint_is_not(self):
        p = self.compiled()
        confidential.mark(p, person=PO["person"], persona=PO["persona"])
        self.harness("command")
        self.approve("builder", "command", project=p.pid, command="agent --task {prompt_file}", family="acme",
                     endpoints=["localhost:11434"])
        self.assertIn("outside the docker sandbox", runner_cell.hosted(p)[0]["host"])
        with self.assertRaises(confidential.ConfidentialRefused):
            runner_cell.require_local(p)
        self.approve("builder", "command", project=p.pid, command="agent --task {prompt_file}", family="acme",
                     sandbox="docker", image="agent:1", endpoints=["localhost:11434"])
        self.assertEqual(runner_cell.hosted(p), [])
        runner_cell.require_local(p)                                             # not refused
        self.approve("builder", "command", project=p.pid, command="agent --task {prompt_file}", family="acme",
                     sandbox="docker", image="agent:1", endpoints=["api.example.com:443"])
        self.assertIn("api.example.com:443", runner_cell.hosted(p)[0]["host"])
        q = self.compiled()                                                      # not confidential: never refused
        self.harness("claude-code")
        self.approve("builder", "claude-code", project=q.pid)
        runner_cell.require_local(q)


class RunnerCardShownTest(RunnerCase):
    def test_FR_HRN1_AC_13_a_runner_waiting_on_it_is_in_whats_next_and_the_inbox(self):
        p, q = self.compiled(), self.compiled()
        self.harness("claude-code")
        waiting = choice.propose(self.factory, role="builder", runner="claude-code", scope=p.pid, person=DEV[0],
                                 persona=DEV[1], reason="the team's standard harness")
        acts = [a for a in next_step(p)["actions"] if a["id"] == "runner_waiting"]
        self.assertEqual(len(acts), 1, next_step(p)["actions"])
        act = acts[0]
        self.assertEqual((act["control"], act["page"], act["card"], act["personas"]),
                         ("runners_decide", f"runners/{p.pid}", waiting["card"], ["it"]))
        self.assertIn(f"rihmasto decide {factory_project(self.factory).pid} {waiting['card']}", act["command"])
        self.assertFalse([a for a in next_step(q)["actions"] if a["id"] == "runner_waiting"])  # another project's
        fp = factory_project(self.factory)
        self.assertEqual([c["id"] for c in Canon(fp).cards(state="open", persona="it", kind="runner")],
                         [waiting["card"]])                                      # the factory's Inbox, for IT
        self.assertFalse(Canon(fp).cards(state="open", persona="developer", kind="runner"))
        Canon(fp).decide(waiting["card"], "approve", person=IT[0], persona=IT[1])
        self.assertFalse([a for a in next_step(p)["actions"] if a["id"] == "runner_waiting"])
        self.harness("codex")                                       # one for every project shows on each of them
        factory_wide = choice.propose(self.factory, role="builder", runner="codex", person=DEV[0], persona=DEV[1],
                                      reason="for every project")
        for project in (p, q):
            self.assertEqual([a["card"] for a in next_step(project)["actions"] if a["id"] == "runner_waiting"],
                             [factory_wide["card"]])

    def test_FR_HRN1_AC_13_the_inbox_groups_the_runner_card_with_the_cards_a_deploy_waits_on(self):
        screens = (ROOT / "cockpit" / "static" / "screens.js").read_text(encoding="utf-8")
        order = screens.split("const INBOX_ORDER = [", 1)[1].split("];", 1)[0]
        kinds = [k.strip().strip('"') for k in order.replace("\n", " ").split(",") if k.strip()]
        self.assertLess(kinds.index("go_ahead"), kinds.index("change"))
        self.assertEqual(kinds.index("runner"), kinds.index("trust") + 1)
        core = (ROOT / "cockpit" / "static" / "core.js").read_text(encoding="utf-8")
        for said in ('runner: "Cell runner"', 'go_ahead: "Go-ahead"', 'go: "Go: build it"', 'decline: "Decline"'):
            self.assertIn(said, core)


class GoAheadShownTest(ChangeCase):
    def test_FR_HRN1_AC_13_the_go_ahead_card_is_in_whats_next_and_the_inbox(self):
        from kernel.pipeline import _shape

        p = self.specced()
        go_ahead.choose(p, wait=True, person=PO["person"], persona=PO["persona"], where="New project")
        card = _shape(p, model(), [])["waiting_on"][0]
        nx = next_step(p)
        self.assertEqual(nx["state"], "go_ahead")
        self.assertEqual([a["card"] for a in nx["actions"] if a.get("control") == "go_ahead"], [card, card])
        self.assertEqual([c["id"] for c in Canon(p).cards(state="open", persona=PO["persona"], kind="go_ahead")],
                         [card])


class AutomationsLeaveThemTest(ChangeCase):
    def test_FR_AUT1_AC_16_an_automation_never_says_go_or_decides_a_runner(self):
        p = self.new(title="Loans")
        for kind in ("go", "skip", "go_ahead", "runner", "decline", "approve_runner"):
            with self.subTest(kind=kind), self.assertRaises(DecisionRefused):
                au.add(self.factory, {"name": "t", "trigger": {"kind": "schedule", "every": "1h"},
                                      "scope": {"kind": "project", "projects": [p.pid]}, "action": {"kind": kind}},
                       person=PO["person"], persona=PO["persona"])
        for module in sorted((ROOT / "kernel").glob("automations*.py")):
            text = module.read_text(encoding="utf-8")
            self.assertNotIn(".decide(", text, module.name)                       # no automation decides a card

    def test_FR_AUT1_AC_16_an_advance_automation_leaves_the_go_ahead_and_the_runner_card_open(self):
        p = self.specced()
        go_ahead.choose(p, wait=True, person=PO["person"], persona=PO["persona"], where="New project")
        fp = factory_project(self.factory)
        decided = len(p.ledger().of_kind("decision"))
        runner = Canon(fp).card("runner", "Run the builder with Claude Code 2.1.0?", refs={"project": p.pid,
                                                                                           "role": "builder"})
        a = au.add(self.factory, {"name": "nightly", "trigger": {"kind": "schedule", "every": "1h"},
                                  "scope": {"kind": "project", "projects": [p.pid]}, "action": {"kind": "advance"}},
                   person=PO["person"], persona=PO["persona"])
        self.clock.advance(hours=1, minutes=1)
        run.tick(self.factory, run.Tools(model=model))
        rows = [r["event"]["payload"] for r in fp.ledger().of_kind("automation_ran")
                if r["event"]["payload"]["id"] == a["id"]]
        self.assertEqual((rows[0]["outcome"], rows[0]["verdict"]), ("done", "waiting"), rows)
        self.assertEqual([c["kind"] for c in Canon(p).cards(kind="go_ahead")], ["go_ahead"])   # still open
        self.assertEqual(Canon(fp).get_card(runner["id"])["state"], "open")
        self.assertEqual(p.ledger().of_kind("go_ahead_given"), [])
        self.assertEqual(len(p.ledger().of_kind("decision")), decided)          # nothing decided by it
        self.assertFalse(p.path("contract.json").exists())                       # nothing built past the look


if __name__ == "__main__":
    unittest.main()
