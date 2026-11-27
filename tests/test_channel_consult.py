"""FR-CHN2: a useful agent channel. Its head says what it is for and who is connected; a person's "ask Claude Code"
makes Rihma put the question to that agent (never "I can't consult"), say how the agent sees it and what the records
say now, or how to connect one; answers carry the next steps from the real state as buttons; a question about
keeping in step with Rihmasto gets a by-rule answer; records are quoted whole; the agent reads the question over MCP
and in its session-start section and answers with reply_to; Ask Rihma does the same. No real agent or model runs."""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_agent_bridge import BridgeCase, call  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agent_channel as ch  # noqa: E402
from kernel import assistant, channel_consult, channel_rihma, ide  # noqa: E402
from kernel.agent_writes import progress  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402

SYNC_ASK = "Rihma, consult Claude Code on how to sync with Rihmasto and what to monitor"
NEVER = ("can't consult", "cannot consult", "i can't", "decision for people")


def person_says(p, text, name="Aino"):
    msg = ch.post(p, author=ch.person(name, "developer"), kind="question", text=text)
    return msg, channel_rihma.reply(p, msg)


class HeadTest(BridgeCase):
    def test_FR_CHN2_AC_1_the_head_says_who_is_connected_and_how_to_connect_one(self):
        head = channel_consult.head(self.p)
        self.assertEqual(head["connected"], [])
        self.assertEqual(head["connect"]["label"], "Connect a coding agent")
        self.assertEqual(head["connect"]["control"], "handoff")                       # built here: the hand-off
        self.assertTrue(any(f"rihmasto ide {self.p.pid}" in s for s in head["setup"]))
        self.assertEqual(head["reads"]["mcp"], "rihma_channel_read")
        self.p.update_meta(source_kind="adopted")
        self.assertEqual(channel_consult.head(self.p)["connect"]["view"], "aitools")   # adopted: its IDE setup
        progress(self.p, ch.agent("claude-code", "Tessa", "developer", "claude-code 2.1"), "Started")
        head = channel_consult.head(self.p)
        self.assertEqual([(a["name"], a["operator"]) for a in head["connected"]], [("claude-code", "Tessa")])
        self.assertIsNone(head["connect"])


class ConsultTest(BridgeCase):
    def test_FR_CHN2_AC_2_with_no_agent_connected_rihma_posts_the_question_and_says_how_to_connect_one(self):
        msg, answer = person_says(self.p, SYNC_ASK)
        text = answer["text"]
        for never in NEVER:
            self.assertNotIn(never, text.lower())
        asked = [m for m in ch.messages(self.p) if m["author"]["kind"] == "rihma" and m["kind"] == "question"]
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0]["to"], ["claude-code"])
        self.assertEqual(asked[0]["refs"]["message"], msg["id"])
        self.assertIn("How to sync with Rihmasto and what to monitor", asked[0]["text"])
        self.assertIn(f"I put your question in this channel ({asked[0]['id']})", text)
        self.assertIn("No coding agent is connected", text)
        self.assertIn(f"`rihmasto ide {self.p.pid}`", text)
        self.assertIn("Meanwhile, from the records:", text)
        self.assertIn("Commits come back through", text)                        # the sync rule answers now
        self.assertEqual(answer["actions"][0]["label"], "Connect a coding agent")
        self.assertEqual(answer["trace"]["basis"], "rule")
        self.assertIn(asked[0]["id"], answer["trace"]["sources"])

    def test_FR_CHN2_AC_2_a_connected_agent_gets_the_question_and_the_person_hears_how_it_sees_it(self):
        progress(self.p, ch.agent("claude-code", "Tessa", "developer", "claude-code 2.1"), "Started on loans")
        _, answer = person_says(self.p, "Can you check with the agent whether R-1 is covered?")
        asked = channel_consult.waiting(self.p)
        self.assertEqual([m["to"] for m in asked], [["claude-code"]])
        self.assertIn("Whether R-1 is covered?", asked[0]["text"])
        text = answer["text"]
        for part in ("I put your question to claude-code", "rihma_channel_read", f"rihmasto ide {self.p.pid} --section",
                     "signed for Tessa", "Meanwhile, from the records: R-1:"):
            self.assertIn(part, text)
        self.assertFalse(any(a["label"] == "Connect a coding agent" for a in answer.get("actions") or []))
        # an agent cannot make Rihma ask another agent: only a person's message does
        q = ch.post(self.p, author=ch.agent("codex", "Pekka", "developer"), kind="question",
                    text="@analyst ask Claude Code what it changed", ask=True)
        channel_rihma.reply(self.p, q)
        self.assertEqual(len(channel_consult.waiting(self.p)), 1)

    def test_FR_CHN2_AC_2_the_words_that_ask_an_agent_and_those_that_do_not(self):
        for text in ("ask Claude Code how to sync", "consult with Cursor on the tests", "Check with Codex whether "
                     "it builds", "put this to the coding agent", "kysy Claude Codelta mitä seurata"):
            self.assertIsNotNone(channel_consult.asks_an_agent(text), text)
        for text in ("what should I build next?", "@analyst what does R-1 mean?", "ask the analyst about R-1"):
            self.assertIsNone(channel_consult.asks_an_agent(text), text)


class GuideTest(BridgeCase):
    def test_FR_CHN2_AC_3_syncing_and_monitoring_get_a_by_rule_answer_with_buttons(self):
        self.p.update_meta(source_kind="adopted", intent="maintain")
        _, answer = person_says(self.p, "How do I keep this in sync with Rihmasto, and what should I monitor?")
        text = answer["text"]
        for part in ("Upstream changed: review", "Set up the watch", "The project's own sources", "findings file",
                     "Checks:", "Automations", "rihma_channel_read"):
            self.assertIn(part, text)
        labels = [a["label"] for a in answer["actions"]]
        self.assertIn("Set up the watch", labels)
        self.assertIn("Add the project's own sources", labels)
        self.assertLessEqual(len(labels), channel_consult.MAX_ACTIONS)
        self.assertEqual(answer["trace"]["basis"], "rule")

    def test_FR_CHN2_AC_3_an_answer_offers_the_waiting_card_and_the_assessment(self):
        self.p.update_meta(source_kind="adopted")
        _, answer = person_says(self.p, "What should I do next?")
        labels = [a["label"] for a in answer["actions"]]
        self.assertTrue(any(lb.startswith((f"Review {self.card}", f"Decide {self.card}")) for lb in labels), labels)
        self.assertIn("Run the assessment", labels)
        card = next(a for a in answer["actions"] if self.card in a["label"])   # one button per decision (FR-CHN3)
        self.assertEqual((card["view"], card["focus"]), ("inbox", self.card))


class WholeTest(BridgeCase):
    def test_FR_CHN2_AC_4_a_requirement_and_an_open_question_are_quoted_whole(self):
        contract = self.p.read("contract.json")
        long = ("Loans show who has each item and since when, so that the team never loses track of a drill or a "
                "laptop again. Overdue loans come first, each with its borrower's name, the due date and a way to "
                "remind them, and returning an item closes its loan at once with the time it came back.")
        contract["requirements"][0]["statement"] = long
        self.p.write("contract.json", contract)
        _, answer = person_says(self.p, "@analyst what are the requirements?")
        self.assertIn(long, answer["text"])
        rid = contract["requirements"][0]["id"]
        _, answer = person_says(self.p, f"@analyst what does {rid} say?")
        self.assertIn(long, answer["text"])
        said, ids = channel_consult.whole([("R-1", long), ("R-2", long), ("R-3", long)], budget=len(long) + 40)
        self.assertEqual(ids, ["R-1"])
        self.assertTrue(said.startswith("R-1 " + long))
        self.assertTrue(said.endswith("And 2 more: ask about one by its id."))
        self.assertNotIn("...", said)


class AgentSeesTest(BridgeCase):
    def test_FR_CHN2_AC_5_the_agent_reads_the_question_over_mcp_and_at_session_start_and_answers_it(self):
        pid = self.p.pid
        res = call(self.server, "rihma_progress", pid=pid, text="Started", agent="claude-code", harness="claude-code")
        self.assertFalse(res["isError"], res)
        person_says(self.p, "ask Claude Code which tests it ran")
        read = call(self.server, "rihma_channel_read", pid=pid)["structuredContent"]
        asked = read["asked_agents"]
        self.assertEqual([m["to"] for m in asked], [["claude-code"]])
        section = ide.section(self.p)
        self.assertIn("Questions for you in the agent channel", section)
        self.assertIn(asked[0]["id"], section)
        res = call(self.server, "rihma_channel_post", pid=pid, kind="answer", text="The loan tests, all passing.",
                   agent="claude-code", reply_to=asked[0]["id"])
        self.assertFalse(res["isError"], res)
        self.assertEqual(res["structuredContent"]["message"]["refs"]["message"], asked[0]["id"])
        self.assertEqual(channel_consult.waiting(self.p), [])
        self.assertNotIn("Questions for you in the agent channel", ide.section(self.p))
        # the command line answers the same way, with --reply-to
        person_says(self.p, "ask Claude Code what it changed")
        qid = channel_consult.waiting(self.p)[0]["id"]
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--home", str(self.factory.home), "channel", pid, "post", "--as", "claude-code", "--kind",
                         "answer", "--reply-to", qid, "--text", "Only the loan list.", "--person", "Tessa",
                         "--persona", "developer"])
        self.assertEqual(code, 0)
        self.assertEqual(channel_consult.waiting(self.p), [])


class ChatParityTest(CockpitTestCase):
    def test_FR_CHN2_AC_6_ask_rihma_offers_to_ask_the_agent_and_confirming_posts_it(self):
        from test_agent_bridge import planned

        p = planned(self.factory, "Equipment loans")
        out = assistant.ask(self.factory, "Ask Claude Code how we should sync with Rihmasto", persona="developer",
                            project_id=p.pid)
        self.assertEqual(out["by"], "rule")
        self.assertIn("Rihma puts it to Claude Code", out["answer"])
        self.assertIn("No coding agent is connected", out["answer"])
        prop = out["propose"][0]["args"]
        self.assertEqual((prop["op"], prop["control"]), ("ask_agent", "channel_post"))
        self.assertEqual(prop["call"]["path"], f"/api/projects/{p.pid}/channel")
        status, body, _ = self.call("POST", prop["call"]["path"], {**prop["call"]["body"], "person": "Aino",
                                                                    "persona": "developer"})
        self.assertEqual(status, 201, body)
        self.assertEqual([m["to"] for m in channel_consult.waiting(p)], [["claude-code"]])
        status, got, _ = self.call("GET", f"/api/projects/{p.pid}/channel")
        self.assertEqual(status, 200, got)
        self.assertEqual(got["head"]["waiting_on_agents"], 1)
        self.assertIn("Connect a coding agent", got["messages"][-1]["actions"][0]["label"])
        out = assistant.ask(self.factory, "How do I keep this project in sync with Rihmasto, what should I monitor?",
                            persona="developer", project_id=p.pid)
        self.assertEqual(out["by"], "rule")
        self.assertIn("Commits come back through", out["answer"])
        self.assertIn("Next steps:", out["answer"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{p.pid}/overview")
        self.assertEqual(Canon(p).cards(kind="change"), [])          # asking wrote no card


if __name__ == "__main__":
    unittest.main()
