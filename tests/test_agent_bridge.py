"""FR-BRG1: the agent bridge, both ways. A hand-off brief and each agent's way to take it; the MCP read tools over the
stdio protocol; and agent writes signed as the agent for its operator, recorded, visible, never deciding a card."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel import agent_bridge as bridge  # noqa: E402
from kernel import agent_channel as ch  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import REPO_ROOT  # noqa: E402
from mcp.server import RihmaMCP  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
PERSON = "Tessa"
READS = ("rihma_next", "rihma_plan", "rihma_questions", "rihma_handoff", "rihma_feedback", "rihma_insights",
         "rihma_alignment", "rihma_health")


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def planned(factory, title: str, mode: str = "assume"):
    p = factory.new_project(title, mode=mode, maturity="demo")
    intake(p, IDEA, model=model(), requested_by="Aino")
    make_spec(p, model=model())
    compile_project(p)
    return p


def call(server, name, **arguments):
    return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments}})["result"]


class BridgeCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = planned(self.factory, "Equipment loans")
        self.asking = self.new(mode="socratic", title="Room bookings")
        intake(self.asking, IDEA, model=model(), requested_by="Aino")
        self.card = Canon(self.p).card("change", "Show overdue loans first", body="Overdue loans come first.",
                                       refs={"requirements": ["R-1"]})["id"]
        self.p.log("gate", {"task": "T-002", "round": 1, "head": "abc", "verdict": "failed",
                            "signals": {"tests": "failed", "trace": "passed"}, "objections": ["R-2-AC-1 has no test"]})
        self.server = RihmaMCP(self.factory, person=PERSON, persona="developer", lanes_root=self.tmp / "no-lanes")


class BriefTest(BridgeCase):
    def test_FR_BRG1_AC_1_the_brief_holds_what_an_agent_needs_and_each_agent_gets_its_way_to_use_it(self):
        home = self.factory.home
        before = tree(home)
        b = bridge.brief(self.p, change=self.card)
        self.assertEqual(tree(home), before)                                    # building it writes nothing
        self.assertEqual(b["change"]["id"], self.card)
        self.assertEqual({c["requirement"] for c in b["criteria"]}, {"R-1"})   # only the change's requirement
        self.assertTrue(b["criteria"] and all(c["then"] for c in b["criteria"]))
        self.assertTrue(b["assumptions"])                                       # assume mode: assumptions open
        self.assertTrue(b["plan"])
        self.assertEqual([g["task"] for g in b["failed_gates"]], ["T-002"])
        self.assertEqual(b["failed_gates"][0]["failing"], ["tests"])
        self.assertTrue(b["tests"])
        text = bridge.render(b)
        for part in ("# Hand-off: Equipment loans", "Criteria to meet", "R-1-AC-1", "Open questions", "The plan",
                     "Gate T-002 round 1: failed", "How to run the tests", "rihma_progress", "rihma_propose_answer"):
            self.assertIn(part, text)
        whole = bridge.brief(self.p)
        self.assertGreater(len({c["requirement"] for c in whole["criteria"]}), 1)
        q = bridge.brief(self.asking)
        self.assertTrue(q["questions"])
        self.assertIn(q["questions"][0]["id"], bridge.render(q))
        ways = {to: bridge.for_agent(self.factory, self.p, b, to=to, operator=PERSON) for to in bridge.AGENTS}
        self.assertIn("claude -p", ways["claude-code"]["run"])
        self.assertEqual(ways["claude-code"]["mcp"]["file"], ".mcp.json")
        self.assertIn("codex exec", ways["codex"]["run"])
        self.assertIn("[mcp_servers.rihma]", ways["codex"]["mcp"]["toml"])
        self.assertIn("opencode run", ways["opencode"]["run"])
        self.assertEqual(ways["cursor"]["mcp"]["file"], ".cursor/mcp.json")
        self.assertTrue(all(w["prompt_file"] == f".rihmasto/handoff-{self.p.pid}.md" for w in ways.values()))
        self.assertIn(PERSON, json.dumps(ways["claude-code"]["mcp"]["json"]))
        with self.assertRaises(ValueError):
            bridge.for_agent(self.factory, self.p, b, to="nobody")
        # recording a hand-off: who, to which agent, the brief's sha256; the text stays out of the ledger
        msg = bridge.record(self.p, b, to="codex", person_name="Aino", persona="developer", via="copy")
        rec = self.p.ledger().of_kind("agent_handoff")[-1]["event"]["payload"]
        self.assertEqual((rec["to"], rec["person"], rec["change"], rec["message"]), ("codex", "Aino", self.card,
                                                                                     msg["id"]))
        self.assertEqual(rec["sha256"], bridge.digest(text))
        self.assertNotIn("Criteria to meet", json.dumps(self.p.ledger().records()))
        # the command line prints the brief and the agent's way to use it
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--home", str(home), "handoff", self.p.pid, "--change", self.card, "--to",
                                   "claude-code"]), 0)
        self.assertIn("# Hand-off: Equipment loans", out.getvalue())
        self.assertIn("claude -p", out.getvalue())


class McpReadTest(BridgeCase):
    def test_FR_BRG1_AC_2_the_new_read_tools_answer_over_the_stdio_protocol(self):
        pid = self.p.pid
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}]
        msgs += [{"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call", "params": {"name": name, "arguments": {
            "pid": pid, **({"to": "codex", "change": self.card} if name == "rihma_handoff" else {})}}}
            for i, name in enumerate(READS)]
        env = dict(os.environ, GF_LANES=str(self.tmp / "no-lanes"))
        argv = [sys.executable, "-m", "mcp.server", "--home", str(self.factory.home), "--person", PERSON,
                "--persona", "developer"]
        before = tree(self.factory.home)
        proc = subprocess.run(argv, input="".join(json.dumps(m) + "\n" for m in msgs).encode("utf-8"),
                              capture_output=True, cwd=REPO_ROOT, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        by_id = {a["id"]: a for a in map(json.loads, proc.stdout.decode("utf-8").splitlines())}
        got = {}
        for i, name in enumerate(READS):
            res = by_id[10 + i]["result"]
            self.assertFalse(res["isError"], (name, res))
            got[name] = res["structuredContent"]
        self.assertIn("waits_for", got["rihma_next"])
        self.assertTrue(got["rihma_plan"]["contract"]["requirements"])
        self.assertIn("assumptions", got["rihma_questions"])
        self.assertEqual(got["rihma_handoff"]["brief"]["change"]["id"], self.card)
        self.assertIn("codex exec", got["rihma_handoff"]["use"]["run"])
        self.assertEqual([g["task"] for g in got["rihma_feedback"]["failed_gates"]], ["T-002"])
        self.assertIn(self.card, [c["id"] for c in got["rihma_feedback"]["change_cards"]])
        for name, key in (("rihma_insights", "insights"), ("rihma_alignment", "gaps"), ("rihma_health", "enabled")):
            value = got[name][key]
            if isinstance(value, dict) and value.get("available") is False:
                self.assertIn("not in this Rihmasto yet", value["note"])        # a stream not merged says so
        self.assertEqual(tree(self.factory.home), before)                         # the reads wrote nothing


class AgentWriteTest(BridgeCase):
    def test_FR_BRG1_AC_3_agent_writes_are_signed_for_the_operator_recorded_and_never_decide(self):
        canon = Canon(self.p)
        decisions, states = len(canon.decisions()), {c["id"]: c["state"] for c in canon.cards(state=None)}
        res = call(self.server, "rihma_progress", pid=self.p.pid, text="Overdue loans sort first now",
                   files="app/routes.py, tests/test_loans.py", criteria="R-1-AC-1", commit="abc123", agent="claude-code",
                   harness="claude-code 2.1")
        self.assertFalse(res["isError"], res)
        msg = res["structuredContent"]["message"]
        self.assertEqual((msg["author"]["name"], msg["author"]["operator"], msg["kind"]), ("claude-code", PERSON,
                                                                                          "progress"))
        self.assertEqual(msg["refs"]["files"], ["app/routes.py", "tests/test_loans.py"])
        rec = self.p.ledger().of_kind("agent_progress")[-1]["event"]["payload"]
        self.assertEqual((rec["agent"], rec["operator"], rec["person"], rec["criteria"]), ("claude-code", PERSON,
                                                                                          PERSON, ["R-1-AC-1"]))
        # a proposed answer is a proposal: the question stays open
        q = Canon(self.asking).questions("open")[0]["id"]
        res = call(self.server, "rihma_propose_answer", pid=self.asking.pid, question=q, text="the team lead",
                   agent="codex")
        self.assertFalse(res["isError"], res)
        prop = res["structuredContent"]["message"]
        self.assertEqual((prop["kind"], prop["state"], prop["refs"]["questions"]), ("proposal", "open", [q]))
        self.assertEqual(Canon(self.asking).question(q)["status"], "open")
        done = call(self.server, "rihma_propose_answer", pid=self.asking.pid, question="Q-999", text="x")
        self.assertTrue(done["isError"])
        # the gate on request: refused on a project the factory builds itself
        res = call(self.server, "rihma_request_gate", pid=self.p.pid, agent="claude-code")
        self.assertTrue(res["isError"])
        self.assertIn("built by the factory itself", res["content"][0]["text"])
        # on an attached repository it runs signed as the operator, and its result posts itself
        self.p.update_meta(source_kind="attached")
        seen = []

        def fake_gate(project, *, person, persona, head):
            seen.append((project.pid, person, persona, head))
            return {"project": project.pid, "task": "repo:abc123", "round": 0, "base": "000", "head": "abc123",
                    "verdict": "failed", "signals": [{"name": "tests", "verdict": "failed", "detail": "1 failing"}],
                    "objections": ["no test names R-1-AC-1"]}
        self.server.gate_sync, self.server.gate_fn = True, fake_gate
        res = call(self.server, "rihma_request_gate", pid=self.p.pid, head="abc123", agent="claude-code")
        self.assertFalse(res["isError"], res)
        self.assertEqual(seen, [(self.p.pid, PERSON, "developer", "abc123")])
        result = res["structuredContent"]["result"]
        self.assertEqual((result["kind"], result["author"]["kind"]), ("gate_result", "system"))
        self.assertEqual(result["trace"]["signals"][0]["name"], "tests")
        self.assertIn("not passed: tests", result["text"])
        kinds = [r["event"]["kind"] for r in self.p.ledger().records()]
        self.assertIn("agent_gate_requested", kinds)
        self.assertEqual([m["kind"] for m in ch.messages(self.p)], ["progress", "note", "gate_result"])
        # an adopted project's gate runs on a workspace submission: the request says how
        self.asking.update_meta(source_kind="adopted")
        res = call(self.server, "rihma_request_gate", pid=self.asking.pid, agent="codex")
        self.assertFalse(res["isError"], res)
        self.assertIsNone(res["structuredContent"]["result"])
        self.assertIn("workspace submit", ch.messages(self.asking)[-1]["text"])
        # nothing was decided, and every write names the operator in the MCP record
        self.assertEqual(len(canon.decisions()), decisions)
        self.assertEqual({cid: canon.get_card(cid)["state"] for cid in states}, states)
        notes = [r["event"]["payload"] for r in self.p.ledger().of_kind("mcp_write")]
        self.assertEqual({n["person"] for n in notes}, {PERSON})
        self.assertEqual(ch.who(msg), f"claude-code for {PERSON}")
        # Ask Rihma explains them: how the project is doing says which agents work on it and what waits
        from kernel.assistant import ask
        said = ask(self.factory, "how is this project doing?", persona="developer", project_id=self.asking.pid)
        self.assertIn("Agents working on it: codex", said["answer"])
        self.assertIn("1 agent proposal(s) wait on a person", said["answer"])


if __name__ == "__main__":
    unittest.main()
