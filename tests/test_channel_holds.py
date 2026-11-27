"""FR-CHN3: the agent channel holds up in daily use. A long question never breaks it; a person's questions never use
up the limit meant to stop agents setting each other off, and a dropped ask is said; each message is answered once,
even while the panel polls; only a request to ask an agent puts a question to one; the buttons land where they say
and are not repeated or stale; an agent's answer counts only with reply_to, and the reply command it is given runs;
the sync answer is short and offers a way to state the test command. No real agent or model runs."""

import argparse
import contextlib
import io
import shlex
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_agent_bridge import BridgeCase, planned  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agent_channel as ch  # noqa: E402
from kernel import assistant, bridge_cli, channel_consult, channel_guard, channel_rihma  # noqa: E402
from kernel.agent_writes import progress  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG_LINE = "2026-11-20 10:00:01 ERROR worker-3 job 4411 failed: TimeoutError while reading the queue at offset 991\n"


def person_says(p, text, name="Aino"):
    msg = ch.post(p, author=ch.person(name, "developer"), kind="question", text=text)
    return msg, channel_rihma.reply(p, msg)


def rihma_to(p, mid):
    return [m for m in ch.messages(p, limit=100000) if m["author"]["kind"] in ("rihma", "system")
            and (m.get("refs") or {}).get("message") == mid]


def long_question() -> str:
    head = "Ask Claude Code: why does the worker time out? The log:\n"
    body = (LOG_LINE * 200)[: 7837 - len(head)]
    return head + body


class SlowModel:
    """A model that takes its time, so a poll can arrive while it answers."""

    name = "slow-test-model"
    last_record = None

    def ask(self, prompt, role=None):
        time.sleep(0.4)
        return "From the records: R-1 is the loan list."


class LongQuestionTest(BridgeCase):
    def test_FR_CHN3_AC_1_a_long_question_to_an_agent_is_put_to_it_shortened_and_never_breaks_the_channel(self):
        text = long_question()
        self.assertLessEqual(len(text), ch.MAX_TEXT)
        msg, answer = person_says(self.p, text)
        self.assertIsNotNone(answer)
        self.assertEqual(answer["kind"], "answer")
        asked = channel_consult.waiting(self.p)
        self.assertEqual(len(asked), 1)
        self.assertLessEqual(len(asked[0]["text"]), ch.MAX_TEXT)
        self.assertIn(msg["id"], asked[0]["text"])                  # the whole question is in the person's message
        self.assertEqual(channel_rihma.unanswered(self.p), [])
        self.assertEqual(channel_rihma.catch_up(self.p), [])

    def test_FR_CHN3_AC_1_a_refused_post_becomes_a_note_and_the_message_counts_as_answered(self):
        msg = ch.post(self.p, author=ch.person("Aino", "developer"), kind="question", text="ask Claude Code why")
        with mock.patch.object(channel_consult, "consult", side_effect=ch.ChannelRefused("a message is at most 8000 "
                                                                                          "characters")):
            got = channel_rihma.reply(self.p, msg)
        self.assertEqual(got["author"]["kind"], "system")
        self.assertIn("could not answer", got["text"])
        self.assertIn("at most 8000 characters", got["text"])
        self.assertEqual(channel_rihma.unanswered(self.p), [])
        with mock.patch.object(channel_rihma, "reply", side_effect=ch.ChannelRefused("refused")):
            ch.post(self.p, author=ch.person("Aino", "developer"), kind="question", text="@analyst what is next?")
            self.assertEqual(channel_rihma.catch_up(self.p), [])    # a refusal never escapes catch_up
        self.assertGreater(len(channel_guard.fit("word. " * 3000)), ch.MAX_TEXT - 100)
        self.assertLessEqual(len(channel_guard.fit("word. " * 3000)), ch.MAX_TEXT)


class LongQuestionRouteTest(CockpitTestCase):
    def test_FR_CHN3_AC_1_the_channel_view_answers_after_a_long_question_with_no_model(self):
        p =planned(self.factory, "Equipment loans")
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/channel",
                                    {"text": long_question(), "person": "Aino", "persona": "developer"})
        self.assertEqual(status, 201, body)
        self.assertIsNotNone(body["answer"])
        for _ in range(2):
            status, got, _ = self.call("GET", f"/api/projects/{p.pid}/channel")
            self.assertEqual(status, 200, got)
        self.assertEqual(len(rihma_to(p, body["message"]["id"])), 2)   # the question to the agent and the answer


class LimitTest(BridgeCase):
    def test_FR_CHN3_AC_2_a_persons_questions_never_use_up_the_limit_and_rihmas_question_is_no_reply(self):
        for i in range(4):
            _, got = person_says(self.p, f"ask Claude Code which tests cover loan rule {i + 1}")
            self.assertEqual(got["kind"], "answer", got["text"])
        for i in range(4):
            _, got = person_says(self.p, f"@analyst what does R-{i + 1} say?")
            self.assertEqual(got["kind"], "answer", got["text"])
        self.assertEqual(len(channel_consult.waiting(self.p)), 4)
        self.assertFalse(any("capped" in m["text"] for m in ch.messages(self.p, limit=100000)))
        # an agent's questions are still capped: that is what the limit is for
        agent = ch.agent("codex", "Pekka", "developer")
        said = []
        for i in range(channel_rihma.REPLIES_PER_HOUR + 1):
            q = ch.post(self.p, author=agent, kind="question", text=f"@analyst what does R-{i + 1}-AC-1 mean?",
                        ask=True)
            said.append(channel_rihma.reply(self.p, q))
        self.assertEqual([m["kind"] for m in said[:-1]], ["answer"] * channel_rihma.REPLIES_PER_HOUR)
        self.assertIn("capped", said[-1]["text"])


class LimitRouteTest(CockpitTestCase):
    def test_FR_CHN3_AC_2_ask_rihma_hears_what_happened_to_its_ask(self):
        p = planned(self.factory, "Equipment loans")
        base = f"/api/projects/{p.pid}/channel"
        signer = {"person": "Aino", "persona": "developer"}
        status, body, _ = self.call("POST", base, {"text": "ask Claude Code which tests it ran", **signer})
        self.assertEqual(status, 201, body)
        self.assertIn("put your question", body["said"])
        status, body, _ = self.call("POST", base, {"text": "ask Claude Code which tests it ran", **signer})
        self.assertEqual(status, 201, body)
        self.assertIn("Not put to the agent", body["said"])
        self.assertIn("same question", body["said"])


class OnceTest(BridgeCase):
    def test_FR_CHN3_AC_3_a_poll_while_rihma_answers_never_answers_twice(self):
        msg = ch.post(self.p, author=ch.person("Aino", "developer"), kind="question", text="@analyst hello there")
        slow = SlowModel()
        t = threading.Thread(target=channel_rihma.reply, args=(self.p, msg), kwargs={"model": slow})
        t.start()
        time.sleep(0.1)
        self.assertEqual(channel_rihma.catch_up(self.p, model=slow), [])
        t.join(5)
        self.assertEqual(len(rihma_to(self.p, msg["id"])), 1)

    def test_FR_CHN3_AC_3_two_answers_at_once_without_a_model_make_one(self):
        msg = ch.post(self.p, author=ch.person("Aino", "developer"), kind="question",
                      text="@analyst what are the requirements?")
        real = channel_consult.actions

        def slow_actions(*a, **k):
            time.sleep(0.3)
            return real(*a, **k)
        with mock.patch.object(channel_consult, "actions", side_effect=slow_actions):
            threads = [threading.Thread(target=channel_rihma.reply, args=(self.p, msg)) for _ in range(2)]
            threads += [threading.Thread(target=channel_rihma.catch_up, args=(self.p,))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5)
        self.assertEqual(len(rihma_to(self.p, msg["id"])), 1)


class IntentTest(BridgeCase):
    def test_FR_CHN3_AC_4_a_question_about_asking_an_agent_is_not_put_to_one(self):
        for text in ("what should I ask the coding agent to do next?", "Can I ask my agent to fix the login bug?",
                     "Should we ask Claude Code about this?", "how do I ask cursor for a review"):
            self.assertIsNone(channel_consult.asks_an_agent(text), text)
            _, got = person_says(self.p, text)
            self.assertEqual(channel_consult.waiting(self.p), [], text)
            self.assertNotIn("I put your question", got["text"])
        for text in ("ask Claude Code how to sync", "Rihma, consult Claude Code on what to monitor",
                     "Can you check with the agent whether R-1 is covered?", "please ask cursor which tests ran",
                     "Thanks. Now ask Codex what it changed", "kysy Claude Codelta mitä seurata"):
            self.assertIsNotNone(channel_consult.asks_an_agent(text), text)

    def test_FR_CHN3_AC_4_with_nothing_to_ask_rihma_asks_the_person_what_to_ask(self):
        for text in ("ask claude code", "Could you ask Cursor? ", "please ask the agent?"):
            _, got = person_says(self.p, text)
            self.assertEqual(channel_consult.waiting(self.p), [], text)
            self.assertIn("What should I ask", got["text"])
        out = assistant.ask(self.factory, "ask Claude Code", persona="developer", project_id=self.p.pid)
        self.assertIn("What should I ask", out["answer"])
        self.assertEqual(out["propose"], [])


class LandingTest(BridgeCase):
    def test_FR_CHN3_AC_5_connect_a_coding_agent_lands_on_a_part_the_page_shows(self):
        self.p.update_meta(source_kind="adopted")
        act = channel_consult.connect_action(self.p)
        source = (ROOT / "cockpit" / "static" / "aitools.js").read_text(encoding="utf-8")
        self.assertIn(f'dataId: "{act["focus"]}"', source)

    def test_FR_CHN3_AC_6_next_steps_keep_the_control_and_the_record_they_name(self):
        self.p.update_meta(source_kind="adopted", intent="maintain")
        acts = channel_consult.actions(self.p, "how do I keep this in sync with Rihmasto?")
        watch = next(a for a in acts if a["label"] == "Set up the watch")
        self.assertEqual(watch["control"], "watch_setup")
        canon = Canon(self.p)
        q = canon.add_question("Which kind of work is this?", "end_user", blocking=True)
        canon.ask(q["id"])
        acts = channel_consult.actions(self.p, "what next?")
        answer = next(a for a in acts if a["label"].startswith(f"Answer {q['id']}"))
        self.assertEqual((answer["view"], answer["focus"]), ("questions", q["id"]))
        source = (ROOT / "cockpit" / "static" / "agents.js").read_text(encoding="utf-8")
        self.assertIn("nav.takeThere", source)


class AnsweredTest(BridgeCase):
    def test_FR_CHN3_AC_7_only_an_answer_with_reply_to_answers_a_question(self):
        progress(self.p, ch.agent("cursor", "Tessa", "developer", "cursor"), "Started")
        person_says(self.p, "ask Cursor which tests it ran")
        qid = channel_consult.waiting(self.p)[0]["id"]
        ch.post(self.p, author=ch.agent("cursor", "Tessa", "developer"), kind="progress",
                text=f"Started on {qid} next, after the timeout fix.")
        self.assertEqual([m["id"] for m in channel_consult.waiting(self.p)], [qid])
        self.assertEqual(channel_consult.head(self.p)["waiting_on_agents"], 1)

    def test_FR_CHN3_AC_8_the_reply_command_given_to_the_agent_runs_as_written(self):
        progress(self.p, ch.agent("claude-code", "Tessa", "developer", "claude-code"), "Started")
        msg, _ = person_says(self.p, "ask Claude Code which tests it ran")
        asked = channel_consult.waiting(self.p)[0]
        cmd = next(line for line in asked["text"].split("`") if line.startswith("rihmasto channel"))
        self.assertNotIn("<this message", cmd)
        self.assertIn('--person "Tessa"', cmd)                      # the connected agent's operator, filled in
        argv = shlex.split(cmd)[1:]
        parser = argparse.ArgumentParser(prog="rihmasto")
        bridge_cli.add_parsers(parser.add_subparsers(dest="cmd"))
        args = parser.parse_args(argv)                               # no required argument is missing
        self.assertIn(args.reply_to, (asked["id"], msg["id"]))
        argv = [a.replace("<your name>", "Tessa") for a in argv]
        argv[argv.index("--text") + 1] = "The loan tests."
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--home", str(self.factory.home), *argv]), 0)
        self.assertEqual(channel_consult.waiting(self.p), [])


class ButtonsTest(CockpitTestCase):
    def ask_twice(self, p):
        signer = {"person": "Aino", "persona": "developer"}
        for text in ("@analyst what should I do next?", "@analyst what are the requirements?"):
            status, body, _ = self.call("POST", f"/api/projects/{p.pid}/channel", {"text": text, **signer})
            self.assertEqual(status, 201, body)
        return body["answer"]["actions"]

    def live_labels(self, p):
        status, got, _ = self.call("GET", f"/api/projects/{p.pid}/channel")
        self.assertEqual(status, 200, got)
        return got, [a["label"] for a in got["messages"][-1].get("actions") or []]

    def test_FR_CHN3_AC_9_one_button_per_decision_only_on_the_latest_answer_and_the_next_step_as_ask_rihma(self):
        p = planned(self.factory, "Equipment loans")
        p.update_meta(source_kind="adopted")
        canon = Canon(p)
        card = canon.card("change", "Show overdue loans first", body="Overdue loans come first.",
                          refs={"requirements": ["R-1"]})
        acts = self.ask_twice(p)
        decided = [a.get("focus") for a in acts if a.get("focus")]
        self.assertEqual(len(decided), len(set(decided)), acts)
        out = assistant.ask(self.factory, "what should I do next?", persona="developer", project_id=p.pid)
        first = acts[0]
        self.assertEqual(first.get("route") or f"#/p/{p.pid}/{first['view']}", out["navigate"]["route"])
        got, live = self.live_labels(p)
        answers = [m for m in got["messages"] if m["author"]["kind"] == "rihma" and m["kind"] == "answer"]
        self.assertEqual([bool(m.get("actions")) for m in answers], [False, True])
        stored = [m for m in ch.messages(p) if m["author"]["kind"] == "rihma"]
        self.assertTrue(stored[0].get("actions"))                    # the record keeps them: only the view hides them
        self.assertTrue(any(card["id"] in lb for lb in live), live)
        canon.close(card["id"], "done elsewhere")
        _, live = self.live_labels(p)
        self.assertFalse(any(card["id"] in lb for lb in live), live)     # a card no longer open offers no button

    def test_FR_CHN3_AC_9_a_question_card_and_its_question_make_one_button(self):
        p = planned(self.factory, "Equipment loans")
        p.update_meta(source_kind="adopted")
        canon = Canon(p)
        q = canon.add_question("Which kind of work is this?", "end_user", blocking=True)
        card = canon.ask(q["id"])
        acts = channel_consult.actions(p, "what next?")
        self.assertFalse(any(a["label"].startswith(f"Review {card['id']}") for a in acts), acts)
        self.assertTrue(any(a["label"].startswith(f"Answer {q['id']}") for a in acts), acts)


class SyncTest(BridgeCase):
    def test_FR_CHN3_AC_10_the_sync_answer_is_short_and_offers_a_way_to_state_the_test_command(self):
        self.p.update_meta(source_kind="adopted", intent="maintain")
        self.p.write("baseline.json", {"verdict": "not measured", "reason": "not measured: no test ran",
                                       "command": "python -m unittest discover -v"})
        self.p.write("adopted.json", {"intent": "maintain", "source": "a local folder"})
        said, _, _, acts = channel_consult.sync_rule(self.p)
        self.assertLessEqual(len(said), 1200, said)
        for part in ("Upstream changed: review", "The project's own sources", "findings file", "Checks:",
                     "Automations", "rihma_channel_read", "Baseline: not measured"):
            self.assertIn(part, said)
        test = next(a for a in acts if a["label"] == "State the test command")
        self.assertEqual((test["view"], test["control"]), ("console", "console_settings"))
        _, answer = person_says(self.p, "ask Claude Code how to sync with Rihmasto and what to monitor")
        self.assertLessEqual(len(answer["text"]), 1700, answer["text"])
        self.assertIn(f"rihmasto ide {self.p.pid}", answer["text"])
        from kernel import adopted_state

        self.assertIn("not measured (tried python -m unittest discover -v)", adopted_state.state(self.p)["line"])
        js = (ROOT / "cockpit" / "static" / "adopted.js").read_text(encoding="utf-8")
        self.assertIn('"tried "', js)


if __name__ == "__main__":
    unittest.main()
