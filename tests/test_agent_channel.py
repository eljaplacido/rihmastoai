"""FR-CHN1: a project's agent channel. Two fake coding agents talk with Rihma's agents over the MCP stdio protocol;
Rihma answers by rule or through a scripted model with a trace; a person confirms a proposal; loops are capped and
a pause holds the agents; the command line reads, follows and posts. No real coding agent or model runs here."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import model  # noqa: E402
from test_agent_bridge import BridgeCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agent_channel as ch  # noqa: E402
from kernel import channel_rihma  # noqa: E402
from kernel.agent_writes import propose_answer  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.store import REPO_ROOT  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


def tool(mid: int, name: str, **arguments) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


class ScriptedModel:
    """Rihma's agents' model in a test: it answers with fixed words and remembers who asked."""

    def __init__(self, text: str):
        self.text, self.roles = text, []
        self.last_record = {"model": "scripted-1", "usage": {"total_tokens": 321}, "tool_calls": [{"name": "read"}]}

    def ask(self, prompt: str, *, role: str) -> str:
        self.roles.append(role)
        return self.text


class StdioTest(BridgeCase):
    def agent(self, person: str, lines: list) -> dict:
        env = dict(os.environ, GF_LANES=str(self.tmp / "no-lanes"))
        msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, *lines]
        proc = subprocess.run([sys.executable, "-m", "mcp.server", "--home", str(self.factory.home), "--person", person,
                               "--persona", "developer"], input="".join(json.dumps(m) + "\n" for m in msgs).encode(),
                              capture_output=True, cwd=REPO_ROOT, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        out = {a["id"]: a["result"] for a in map(json.loads, proc.stdout.decode("utf-8").splitlines())}
        for mid, res in out.items():
            self.assertFalse(mid and res.get("isError"), res)
        return {k: v.get("structuredContent") for k, v in out.items()}

    def test_FR_CHN1_AC_1_two_coding_agents_converse_with_rihma_over_mcp_and_the_ledger_keeps_no_text(self):
        pid = self.p.pid
        first = self.agent("Tessa", [
            tool(1, "rihma_progress", pid=pid, text="Started on overdue loans", agent="claude-code", criteria="R-1-AC-1"),
            tool(2, "rihma_channel_post", pid=pid, kind="question", text="@verifier why did the gate fail?",
                 agent="claude-code")])
        answer = first[2]["answer"]
        self.assertEqual((answer["author"]["role"], answer["kind"]), ("verifier", "answer"))
        self.assertIn("said failed", answer["text"])
        self.assertIn("tests: failed", answer["text"])
        self.assertEqual(answer["trace"]["basis"], "rule")
        second = self.agent("Pekka", [
            tool(1, "rihma_channel_read", pid=pid),
            tool(2, "rihma_ask_rihma", pid=pid, question="What does R-1-AC-1 mean?", agent="codex"),
            tool(3, "rihma_channel_read", pid=pid, since="M-0003")])
        seen = [(m["author"]["name"], m["kind"]) for m in second[1]["messages"]]
        self.assertEqual(seen, [("claude-code", "progress"), ("claude-code", "question"), ("Rihma", "answer")])
        said = second[2]["answer"]
        self.assertEqual(said["author"]["role"], "analyst")
        self.assertIn("R-1-AC-1", said["trace"]["sources"])
        criterion = next(c for r in self.p.read("contract.json")["requirements"] for c in r["acceptance"]
                         if c["id"] == "R-1-AC-1")
        self.assertIn(criterion["then"], said["text"])
        self.assertEqual([m["author"].get("operator") for m in second[3]["messages"]], ["Pekka", None])
        posted = [r["event"]["payload"] for r in self.p.ledger().of_kind("channel_posted")]
        self.assertEqual([(p["id"], p["author_kind"], p["kind"]) for p in posted],
                         [("M-0001", "agent", "progress"), ("M-0002", "agent", "question"), ("M-0003", "rihma", "answer"),
                          ("M-0004", "agent", "question"), ("M-0005", "rihma", "answer")])
        ledger = json.dumps(self.p.ledger().records())
        for m in ch.messages(self.p):
            self.assertNotIn(m["text"], ledger)                                     # never the body text
        self.assertTrue(all("text" not in p for p in posted))


class ModelAnswerTest(BridgeCase):
    def test_FR_CHN1_AC_2_rihma_answers_through_a_model_with_a_trace_and_a_confidential_project_never_sends(self):
        m = ScriptedModel("Make the borrowing screen show who has each item. I have recorded that for you.")
        author = ch.agent("claude-code", "Tessa", "developer")
        q = ch.post(self.p, author=author, kind="question", text="@analyst how should borrowing feel to a newcomer?")
        ans = channel_rihma.reply(self.p, q, model=m)
        self.assertEqual(m.roles, ["analyst"])
        self.assertEqual(ans["trace"]["basis"], "model")
        self.assertEqual((ans["trace"]["role"], ans["trace"]["model"], ans["trace"]["tokens"], ans["trace"]["tool_calls"]),
                         ("analyst", "scripted-1", 321, 1))
        self.assertIsInstance(ans["trace"]["duration_ms"], int)
        self.assertNotIn("I have recorded", ans["text"])                          # a claim that it acted goes
        q2 = ch.post(self.p, author=author, kind="question", text="@rihma is this diff right?",
                     refs={"commits": ["abc123"]})
        channel_rihma.reply(self.p, q2, model=m)
        self.assertEqual(m.roles[-1], "verifier")                                 # pointed at a commit
        self.p.update_meta(confidential=True)
        m3 = ScriptedModel("anything")
        q3 = ch.post(self.p, author=author, kind="question", text="@analyst what would a newcomer expect here?")
        with mock.patch("kernel.confidential.refusal", return_value="refused: hosted"):
            ans3 = channel_rihma.reply(self.p, q3, model=m3)
        self.assertEqual(m3.roles, [])
        self.assertIn("confidential", ans3["text"])
        self.assertIn("Models setup", ans3["text"])
        # no rule, no model: said plainly
        q4 = ch.post(self.p, author=author, kind="question", text="@analyst is the colour scheme pleasant?")
        self.assertIn("no model is set up", channel_rihma.reply(self.p, q4)["text"])
        # nobody asked Rihma: no answer; the holdout author never posts
        self.assertIsNone(channel_rihma.reply(self.p, ch.post(self.p, author=author, kind="note", text="done for today")))
        with self.assertRaises(ch.ChannelRefused):
            ch.post(self.p, author={"kind": "rihma", "role": "holdout_author"}, kind="note", text="x")


class SettleTest(CockpitTestCase):
    def test_FR_CHN1_AC_3_a_person_confirms_a_proposal_through_the_answer_route_and_rejects_another(self):
        p = self.new(mode="socratic")
        intake(p, IDEA, model=model(), requested_by="Aino")
        agent = ch.agent("codex", "Tessa", "developer")
        one = propose_answer(p, agent, "Q-001", "the team lead approves")
        two = propose_answer(p, agent, "Q-002", "a week")
        self.assertEqual(Canon(p).question("Q-001")["status"], "open")             # never an answer by itself
        base = f"/api/projects/{p.pid}/channel"
        status, out, _ = self.call("POST", f"{base}/{one['id']}/settle", {"verdict": "confirm", "person": "Aino",
                                                                           "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        q = Canon(p).question("Q-001")
        self.assertEqual((q["status"], q["answer"]["text"] if isinstance(q.get("answer"), dict) else q.get("answer")),
                         ("answered", "the team lead approves"))
        self.assertEqual(out["message"]["state"], "confirmed")
        self.assertEqual(out["message"]["settled"]["person"], "Aino")
        answers = [r["event"]["payload"] for r in p.ledger().of_kind("cockpit_write") if r["event"]["payload"]["action"]
                   == "answer"]
        self.assertEqual([(a["target"], a["person"]) for a in answers], [("Q-001", "Aino")])
        status, out, _ = self.call("POST", f"{base}/{two['id']}/settle", {"verdict": "reject", "person": "Aino",
                                                                           "persona": "business_owner"})
        self.assertEqual((status, out["message"]["state"]), (200, "rejected"))
        self.assertEqual(Canon(p).question("Q-002")["status"], "open")
        status, out, _ = self.call("POST", f"{base}/{one['id']}/settle", {"verdict": "confirm", "person": "Aino",
                                                                           "persona": "business_owner"})
        self.assertEqual(status, 409)                                                # settled once
        status, out, _ = self.call("POST", f"{base}/{two['id']}/settle", {"verdict": "confirm", "person": "assistant",
                                                                           "persona": "business_owner"})
        self.assertEqual(status, 403)                                                # a person confirms
        status, out, _ = self.call("GET", "/api/agents")
        self.assertEqual(out["channels"][0]["project"], p.pid)
        self.assertEqual(out["channels"][0]["proposals_waiting"], [])


class CatchUpTest(CockpitTestCase):
    def test_FR_CHN1_AC_7_a_message_nobody_answered_is_answered_when_the_channel_opens(self):
        p = self.new(mode="socratic")
        intake(p, IDEA, model=model(), requested_by="Aino")
        # posted straight into the channel, as before a restart: no reply ran
        left = ch.post(p, author=ch.person("Aino", "developer"), kind="note", text="what should I do next?")
        base = f"/api/projects/{p.pid}/channel"
        status, out, _ = self.call("GET", base)
        self.assertEqual(status, 200, out)
        answers = [m for m in ch.read(p)["messages"] if (m.get("refs") or {}).get("message") == left["id"]]
        self.assertEqual([(m["author"]["kind"], m["kind"], m["thread"]) for m in answers],
                         [("rihma", "answer", left["thread"])])
        self.call("GET", base)                                                       # opened again: nothing more
        again = [m for m in ch.read(p)["messages"] if (m.get("refs") or {}).get("message") == left["id"]]
        self.assertEqual(len(again), 1)


class LimitsTest(BridgeCase):
    def test_FR_CHN1_AC_4_repeats_and_the_hourly_cap_stop_loops_and_a_pause_holds_the_agents(self):
        a = ch.agent("claude-code", "Tessa", "developer")
        ask = lambda text: channel_rihma.reply(self.p, ch.post(self.p, author=a, kind="question", text=text, ask=True))  # noqa: E731
        first = ask("What should I build next?")
        self.assertEqual(first["author"]["kind"], "rihma")
        again = ask("what should I build next")
        self.assertEqual((again["author"]["kind"], again["refs"]["message"]), ("system", "M-0001"))
        self.assertIn("does not answer a question twice", again["text"])
        self.assertIsNone(ask("What should I build next?"))                         # then silence
        for n in range(channel_rihma.REPLIES_PER_HOUR - 1):
            self.assertEqual(ask(f"What does R-{n + 1} say about the criteria?")["author"]["kind"], "rihma")
        capped = ask("Which criteria does the contract hold?")
        self.assertEqual(capped["author"]["kind"], "system")
        self.assertIn("capped", capped["text"])
        self.assertIsNone(ask("Is Q-001 still open?"))
        # another thread has its own limit
        other = channel_rihma.reply(self.p, ch.post(self.p, author=a, kind="question", text="What next?", ask=True,
                                                    thread="drive-sync"))
        self.assertEqual(other["author"]["kind"], "rihma")
        # a pause holds an agent's post, unanswered and hidden from the agents, until a person resumes
        ch.pause(self.p, person_name="Aino", persona="product_owner", reason="reviewing")
        held = ch.post(self.p, author=a, kind="question", text="@analyst anything else?", thread="later")
        self.assertTrue(held["held"])
        self.assertIsNone(channel_rihma.reply(self.p, held))
        self.assertNotIn(held["id"], [m["id"] for m in ch.messages(self.p, held=False)])
        with self.assertRaises(ch.ChannelRefused):
            ch.pause(self.p, person_name="Aino", persona="product_owner")
        released = ch.resume(self.p, person_name="Aino", persona="product_owner")
        self.assertEqual([m["id"] for m in released], [held["id"]])
        self.assertIn(held["id"], [m["id"] for m in ch.messages(self.p, held=False)])
        kinds = [r["event"]["kind"] for r in self.p.ledger().records()]
        self.assertIn("channel_paused", kinds)
        self.assertIn("channel_resumed", kinds)


class CliTest(BridgeCase):
    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_CHN1_AC_5_an_agent_without_mcp_posts_and_a_person_reads_and_follows_the_channel(self):
        pid = self.p.pid
        code, out, err = self.cli("channel", pid, "post", "--as", "opencode", "--text", "Added the overdue filter",
                                  "--criteria", "R-1-AC-1", "--commit", "abc123", "--person", "Tessa",
                                  "--persona", "developer")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["message"]["refs"], {"criteria": ["R-1-AC-1"], "commits": ["abc123"]})
        rec = self.p.ledger().of_kind("agent_progress")[-1]["event"]["payload"]
        self.assertEqual((rec["agent"], rec["person"]), ("opencode", "Tessa"))
        code, out, err = self.cli("channel", pid, "post", "--as", "opencode", "--kind", "question", "--text",
                                  "@analyst what does R-1-AC-1 mean?", "--person", "Tessa", "--persona", "developer")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["answer"]["author"]["role"], "analyst")
        code, out, err = self.cli("channel", pid, "post", "--as", "opencode", "--text", "x", "--person", "assistant",
                                  "--persona", "developer")
        self.assertEqual(code, 2)                                                    # a person signs for the agent
        code, out, err = self.cli("channel", pid)
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("M-0001 "))
        self.assertIn("opencode for Tessa [progress]: Added the overdue filter [criteria: R-1-AC-1]", lines[0])
        self.assertIn("Rihma (analyst) [answer]", lines[2])
        code, out, err = self.cli("channel", pid, "--json", "--since", "M-0002")
        self.assertEqual([m["id"] for m in json.loads(out)["messages"]], ["M-0003"])
        calls = []

        def sleep(_):
            if calls:
                raise KeyboardInterrupt
            calls.append(1)
            ch.post(self.p, author=ch.person("Aino", "product_owner"), kind="note", text="Looks good to me")
        with mock.patch("kernel.bridge_cli.time.sleep", sleep):
            code, out, err = self.cli("channel", pid, "--follow")
        self.assertEqual(code, 0, err)
        self.assertIn("Aino [note]: Looks good to me", out.splitlines()[-1])
        code, out, err = self.cli("goal", pid, "Hook this to Google Drive")
        self.assertEqual(code, 0, err)
        self.assertIn("Declare the Google Drive integration", out)          # the Drive kind is here (FR-GDR1)


if __name__ == "__main__":
    unittest.main()
