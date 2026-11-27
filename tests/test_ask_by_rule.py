"""Ask Rihma with no model (the demo, `--assistant map`): a plain request is proposed by rule, to confirm, through the
chat path kernel/parity.py names for its control; a how-to about one named control goes to that control; a coding
agent asked to answer as Rihmasto's model goes to Models setup; and a built project's AI tools say what is there."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel.assistant import ask  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.parity import CHAT  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class RuleProposalTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(mode="socratic")
        intake(self.p, IDEA, model=model(), requested_by="Aino")

    def ask(self, question, persona="business_owner", project=None):
        return ask(self.factory, question, persona=persona, project_id=project or self.p.pid)

    def test_a_plain_request_is_proposed_by_rule_through_its_controls_chat_path(self):
        cases = {   # the words -> (the control, what is proposed)
            "pause this project": ("pause", "pause"),
            "switch to the light theme": ("theme", "theme"),
            "let Rihma assume": ("assume", "let_rihma_assume"),
            "log a signal: the stores want a weekly CSV": ("log_signal", "log_signal"),
        }
        for words, (control, proposed) in cases.items():
            out = self.ask(words)
            self.assertTrue(out["propose"], (words, out["answer"]))
            p = out["propose"][0]
            kind, name = CHAT[control]
            self.assertEqual(name, p["args"]["op"] if p["action"] == "act" else p["action"], words)
            self.assertEqual(name, proposed, words)
            self.assertNotIn("only point the way", out["answer"], words)
            self.assertIn("Nothing is done until you confirm it", out["answer"], words)
        theme = self.ask("switch to the light theme")["propose"][0]
        self.assertEqual(theme["args"]["settings"], {"mode": "light"})
        assumed = self.ask("let Rihma assume")["propose"]
        self.assertEqual({p["args"]["question"] for p in assumed} <= {q["id"] for q in Canon(self.p).questions("open")},
                         True)
        card = next(c for c in Canon(self.p).cards() if c["kind"] == "question")
        one = self.ask(f"let Rihma assume {card['id']}")["propose"]
        self.assertEqual([p["args"]["question"] for p in one], [card["refs"]["question"]])   # its card's C-id
        signal = self.ask("log a signal: the stores want a weekly CSV")["propose"][0]
        self.assertEqual(signal["args"]["text"], "the stores want a weekly CSV")
        self.assertEqual(signal["args"]["call"]["path"], "/api/signals")

    def test_an_operation_that_needs_nothing_is_proposed_and_one_the_rules_refuse_says_why(self):
        q = self.new(mode="assume", title="Stock levels")
        intake(q, IDEA, model=model(), requested_by="Aino")
        make_spec(q, model=model())
        compile_project(q)
        built = self.ask("build the capability pack", persona="it", project=q.pid)["propose"]
        self.assertEqual([p["args"]["op"] for p in built], ["build_pack"])
        out = self.ask("resume this project")
        self.assertEqual(out["propose"], [])
        self.assertIn("I could not propose it", out["answer"])
        self.assertIn("is not paused", out["answer"])
        out = self.ask("run the health checks now", persona="operations")
        self.assertIn("no check is enabled", out["answer"])
        records = len(self.p.ledger().records())
        self.ask("pause this project")
        self.assertEqual(len(self.p.ledger().records()), records)     # proposing writes nothing

    def test_a_how_to_that_names_a_control_by_its_label_goes_to_that_control(self):
        cases = {"How do I ask Gnomon in the workspace?": "console_gnomon",
                 "track and evaluate this work": "scan_track",
                 "how do I use data-flow diagram?": "itdata_flow"}
        for words, control in cases.items():
            out = self.ask(words, persona="developer")
            self.assertEqual((out["navigate"] or {}).get("control"), control, (words, out["answer"][:200]))
            self.assertNotEqual(out["by"], "goal", words)
            self.assertNotIn("only point the way", out["answer"], words)

    def test_a_coding_agent_as_the_model_goes_to_models_setup_and_connecting_an_ide_does_not(self):
        cases = {"use Claude Code as the model": "models_use_claude",
                 "how do I make claude code answer as rihmasto's model?": "models_use_claude",
                 "how do I use Claude Code as the model?": "models_use_claude",
                 "use opencode": "models_use_opencode", "can I use codex instead of an API key?": "models_use_codex"}
        for words, control in cases.items():
            out = self.ask(words, persona="it")
            self.assertEqual(out["navigate"], {"route": "#/models", "control": control}, words)
            self.assertIn("rihmasto models use", out["answer"], words)
            self.assertIn("Models setup", out["answer"], words)
        ide = self.ask("how do I connect Claude Code to Rihmasto over MCP?", persona="developer")
        self.assertNotEqual((ide["navigate"] or {}).get("route"), "#/models")

    def test_agent_skills_are_answered_platform_wide_and_per_project(self):
        skill = {"name": "release-notes", "path": ".claude/skills/release-notes/SKILL.md",
                 "description": "drafts release notes", "files": []}
        self.p.write("agent_context.json", {"skills": [skill]})
        self.p.update_meta(source_kind="adopted")
        for words in ("which agent skills can I use across all projects?",
                      "which skills are available at platform level and which per project?",
                      "what agent skills does the platform have?"):
            out = ask(self.factory, words, persona="ai_architect")
            self.assertIn("No agent skill applies to every project yet", out["answer"], words)
            self.assertIn("release-notes", out["answer"], words)
            self.assertEqual(out["navigate"], {"route": "#/agentops", "control": "agent_skills"}, words)
        from kernel.agent_skills import overview

        view = overview(self.factory)
        self.assertEqual((view["platform"], [r["project"] for r in view["projects"]]), ([], [self.p.pid]))

    def test_a_built_projects_ai_tools_say_it_has_none_and_open_its_ai_tools_tab(self):
        out = self.ask("show me the skills and AI tools in this project", persona="developer")
        self.assertIn("built by Rihmasto", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.p.pid}/aitools", "control": None})
        from kernel.assistant import from_map

        mapped = from_map("where are the AI tools in this project?", self.p)
        self.assertEqual(mapped["navigate"], {"route": f"#/p/{self.p.pid}/aitools", "control": None})
        self.assertIn("no repository AI-tool setup", mapped["answer"])

    def test_mcp_ask_rihma_answers_by_the_cockpits_rules_when_the_records_do_not(self):
        from mcp.server import RihmaMCP

        server = RihmaMCP(self.factory, person="Dev Example", persona="developer", lanes_root=self.tmp / "no-lanes")

        def asked(question):
            out = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "rihma_ask_rihma", "arguments": {"pid": self.p.pid, "question": question}}})["result"]
            self.assertFalse(out.get("isError"), out)
            return out["structuredContent"]["answer"]

        for question, says in (("what waits on me?", "What's next"), ("how do I pause this project?", "Pause")):
            answer = asked(question)
            self.assertNotIn("I could not answer that from the records", answer["text"], question)
            self.assertIn(says, answer["text"], question)
            self.assertEqual(answer["trace"]["basis"], "rule", question)
        tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        described = next(t for t in tools if t["name"] == "rihma_ask_rihma")["description"]
        self.assertIn("same rules as the cockpit's Ask Rihma", described)

    def test_a_request_with_nothing_to_read_still_only_points_the_way(self):
        out = self.ask("make the decisions widget wide")
        self.assertEqual(out["propose"], [])
        self.assertIn("only point the way", out["answer"])


if __name__ == "__main__":
    unittest.main()
