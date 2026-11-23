"""Regression tests for the website chat (task V-80).

- The chat's model runs in a lane of its own, waits only briefly for it, has a short timeout and
  keeps no task records; a busy lane or any model failure files the message without a model reply
  (FR-I1-AC-5). Found live: a chat turn waited 15 minutes on the analyst lane while intake ran.
- Turns that arrive together each get their own change card or signal; a revoke wins over a turn
  in flight and is never undone by a turn's message count (FR-I1-AC-2).
- A model answer that is not the JSON object asked for, or a question the turn limit cut short,
  still ends in a filed message and a plain thank-you (FR-I1-AC-2).
- A website's feedback is triaged when it is filed, as the cockpit triages the same words: a feature
  request reaches the owners' decision queue instead of waiting untriaged (FR-I3-AC-1).
"""

import contextlib
import os
import shlex
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

import kernel.canon as kcanon  # noqa: E402
import kernel.change as kchange  # noqa: E402
import kernel.signals as ksignals  # noqa: E402
from embed.server import chat_model  # noqa: E402
from kernel import embeds as kembeds  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.dashboard import queue  # noqa: E402
from kernel.status import now  # noqa: E402
from kernel.filelock import LockHeld, locked  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import ensure_analyst_lane, load_routing, lock_path  # noqa: E402
from kernel.model import FakeModel, ModelError  # noqa: E402

SITE = "https://shop.example"
IDEA = "Our team keeps losing track of who borrowed the drills."
CLEAR = '```json\n{"reply": "Thanks, noted.", "ready": true, "summary": "the return button does nothing"}\n```'

# A stand-in for `gnomon task`: it logs its call, may sleep first, and answers like the assistant role.
FAKE_GNOMON = r'''
import json, os, sys, time
time.sleep(float(os.environ.get("FAKE_CHAT_SLEEP", "0")))
with open(os.environ["FAKE_CHAT_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\n")
answer = {"reply": "Thanks, noted.", "ready": True, "summary": "the return button does nothing"}
print(json.dumps({"output": "```json\n" + json.dumps(answer) + "\n```", "stop_reason": "done"}))
'''


class EmbedChatCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(mode="assume", title="Equipment loans")
        intake(self.p, IDEA, model=model(), requested_by="Aino")
        self.e = kembeds.create(self.factory, kind="feedback", origins=[SITE], person="Aino",
                                persona="product_owner", project_id=self.p.pid)

    def turn(self, text: str = "The return button does nothing", embed: dict | None = None, **kw) -> dict:
        e = embed or self.e
        return kembeds.converse(self.factory, e["id"], e["key"], SITE, [{"role": "person", "text": text}], **kw)

    def changes(self) -> list:
        return Canon(self.p).cards(state=None, kind="change")

    def parallel(self, n: int, fn) -> tuple[list, list]:
        """Run fn(0..n-1) on n threads released together; their results and errors."""
        barrier, results, errors = threading.Barrier(n), [], []

        def run(i: int) -> None:
            barrier.wait(10)
            try:
                results.append(fn(i))
            except Exception as exc:  # collected: the test asserts there are none
                errors.append(repr(exc))

        threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        return results, errors


class ChatLaneTest(EmbedChatCase):
    """FR-I1-AC-5: a chat turn never waits on, nor holds up, the factory's own model work."""

    @contextlib.contextmanager
    def gnomon(self, sleep: float = 0):
        script = self.tmp / "fake_gnomon.py"
        script.write_text(FAKE_GNOMON, encoding="utf-8", newline="\n")
        self.log = self.tmp / "chat-runs.jsonl"
        env = {"GNOMON_CMD": shlex.join([Path(sys.executable).as_posix(), script.as_posix()]),
               "FAKE_CHAT_LOG": str(self.log), "FAKE_CHAT_SLEEP": str(sleep)}
        with mock.patch.dict(os.environ, env):
            yield

    def runs(self) -> list:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def test_FR_I1_AC_5_a_chat_turn_runs_in_its_own_lane_while_the_factorys_analyst_lane_is_busy(self):
        routing, root = load_routing(), self.tmp / "lanes"
        factory_lane = ensure_analyst_lane(routing, root=root)        # intake, spec, holdouts, the assistant
        chat = chat_model(routing, root=root)
        self.assertNotEqual(lock_path(chat.lane_dir), lock_path(factory_lane))
        self.assertLessEqual(chat.timeout, 60)
        with self.gnomon(), locked(lock_path(factory_lane)):          # intake holds the factory's lane
            start = time.monotonic()
            out = self.turn(model=chat)
            took = time.monotonic() - start
        self.assertEqual((out["reply"], out["filed"]["kind"]), ("Thanks, noted.", "change"))
        self.assertLess(took, 10)
        self.assertEqual(len(self.runs()), 1)
        self.turn("The list is not sorted", model=chat)
        self.assertFalse(getattr(chat, "records", None))               # a server that runs for months keeps none

    def test_FR_I1_AC_5_a_busy_chat_lane_files_the_message_without_a_model_reply(self):
        chat = chat_model(load_routing(), root=self.tmp / "lanes", lane_wait=0.3)
        with self.gnomon(), locked(lock_path(chat.lane_dir)):          # another turn holds the chat's lane
            start = time.monotonic()
            out = self.turn(model=chat)
            took = time.monotonic() - start
        self.assertEqual((out["reply"], out["filed"]["kind"]), (kembeds.THANKS, "change"))
        self.assertLess(took, 5)
        self.assertEqual(self.runs(), [])                                # the model never ran
        self.assertEqual(len(self.changes()), 1)

    def test_FR_I1_AC_5_a_model_past_its_timeout_files_the_message_without_a_model_reply(self):
        self.assertLessEqual(chat_model(load_routing(), root=self.tmp / "lanes").timeout, 60)   # not 15 minutes
        chat = chat_model(load_routing(), root=self.tmp / "lanes", timeout=2)
        with self.gnomon(sleep=30):
            start = time.monotonic()
            out = self.turn(model=chat)
            took = time.monotonic() - start
        self.assertEqual((out["reply"], out["filed"]["kind"]), (kembeds.THANKS, "change"))
        self.assertLess(took, 20)

    def test_FR_I1_AC_5_any_lock_or_model_failure_files_the_message_without_a_model_reply(self):
        for failure in (LockHeld("the lane"), ModelError("no answer"), RuntimeError("gnomon broke"),
                        OSError("not startable"), TimeoutError("too slow")):
            def fail(prompt, role, exc=failure):
                raise exc

            out = self.turn(f"The return button does nothing ({failure!r})", model=FakeModel(fail))
            self.assertEqual((out["reply"], out["filed"]["kind"]), (kembeds.THANKS, "change"), repr(failure))
        self.assertEqual(len(self.changes()), 5)


class ChatAnswerTest(EmbedChatCase):
    def test_FR_I1_AC_2_an_answer_that_is_not_the_json_object_asked_for_still_files_the_message(self):
        for text in ('```json\n["ok"]\n```', '```json\n"fine"\n```', '```json\n{"ready": false}\n```',
                     '```json\n{"ready": false, "reply": "   "}\n```'):
            out = self.turn(model=FakeModel(lambda prompt, role, t=text: t))
            self.assertEqual(out["reply"], kembeds.THANKS, text)
            self.assertEqual(out["filed"]["kind"], "change", text)
        self.assertEqual(len(self.changes()), 4)

    def test_FR_I1_AC_2_when_the_turn_limit_files_a_thread_its_last_question_is_not_shown(self):
        history = []
        for i in range(kembeds.MAX_TURNS):
            history += [{"role": "person", "text": f"It broke, part {i}"}, {"role": "assistant", "text": "When?"}]
        asks = FakeModel(lambda prompt, role: '```json\n{"reply": "How often does it happen?", "ready": false}\n```')
        out = kembeds.converse(self.factory, self.e["id"], self.e["key"], SITE, history[:-1], model=asks)
        self.assertEqual(out["filed"]["kind"], "change")
        self.assertEqual(out["reply"], kembeds.THANKS)           # not a question the widget's next thread loses


class ChatFilingTest(EmbedChatCase):
    def test_FR_I1_AC_2_feedback_sent_at_the_same_moment_gets_one_change_card_each(self):
        real = kcanon.write_json

        def slow(path, obj):                          # widen the window between choosing an id and writing it
            if Path(path).name.startswith("C-"):
                time.sleep(0.2)
            real(path, obj)

        with mock.patch.object(kcanon, "write_json", slow):
            results, errors = self.parallel(4, lambda i: self.turn(f"Message {i}: the return button does nothing"))
        self.assertEqual(errors, [])
        ids = sorted(r["filed"]["id"] for r in results)
        self.assertEqual(len(set(ids)), 4)
        texts = {c["id"]: c["payload"]["text"] for c in self.changes()}
        self.assertEqual(sorted(texts), ids)
        for i in range(4):
            self.assertEqual(sum(f"Message {i}:" in t for t in texts.values()), 1)
        self.assertEqual(kembeds.embeds(self.factory)[0]["messages"], 4)

    def test_FR_I1_AC_2_needs_sent_at_the_same_moment_get_one_signal_each(self):
        need = kembeds.create(self.factory, kind="need", origins=[SITE], person="Aino", persona="business_owner",
                              label="Ops chat")
        import kernel.store as kstore

        real = kstore.write_json

        def slow(path, obj):
            if Path(path).name == "signals.json":      # widen the read-modify-write window of the signals file
                time.sleep(0.2)
            real(path, obj)

        with mock.patch.object(kstore, "write_json", slow):
            results, errors = self.parallel(4, lambda i: self.turn(f"Need {i}: invoices by hand", embed=need))
        self.assertEqual(errors, [])
        ids = sorted(r["filed"]["id"] for r in results)
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual(sorted(s["id"] for s in ksignals.signals(self.factory)), ids)

    def test_FR_I1_AC_2_a_revoke_while_the_model_answers_files_nothing(self):
        def revoked_meanwhile(prompt, role):
            kembeds.revoke(self.factory, self.e["id"], person="Aino", persona="product_owner")
            return CLEAR

        with self.assertRaises(kembeds.EmbedRefused):
            self.turn(model=FakeModel(revoked_meanwhile))
        self.assertEqual(self.changes(), [])
        self.assertEqual(kembeds.embeds(self.factory)[0]["state"], "revoked")

    def test_FR_I1_AC_2_a_revoke_saved_while_a_turn_is_counted_is_never_undone(self):
        real, counting, revoked, turn = kembeds._save, threading.Event(), threading.Event(), {}

        def save(factory, items):
            if threading.current_thread() is turn.get("thread"):    # the turn's message count
                counting.set()
                revoked.wait(2)
            real(factory, items)

        def revoke_now():
            counting.wait(10)
            kembeds.revoke(self.factory, self.e["id"], person="Aino", persona="product_owner")
            revoked.set()

        with mock.patch.object(kembeds, "_save", save):
            turn["thread"] = threading.Thread(target=self.turn)
            person = threading.Thread(target=revoke_now)
            person.start()
            turn["thread"].start()
            turn["thread"].join(30)
            person.join(30)
        self.assertEqual(kembeds.embeds(self.factory)[0]["state"], "revoked")
        with self.assertRaises(kembeds.EmbedRefused):
            self.turn()


class ChatTriageTest(EmbedChatCase):
    """FR-I3-AC-1: a change filed from a website is classified when it is filed, like one typed in the
    cockpit, so a feature request reaches the decision queue."""

    WORDS = ("Please add a new feature: export every loan to a spreadsheet each month",
             "The return page crashes when I press save", "Could the list be sorted by date instead?",
             "Can I return a drill after six?")

    def triage_of(self, card_id: str) -> dict:
        return Canon(self.p).get_card(card_id)["payload"].get("triage") or {}

    def test_FR_I3_AC_1_a_feature_request_from_a_website_is_triaged_and_waits_in_the_decision_queue(self):
        out = self.turn(self.WORDS[0])
        card = out["filed"]["id"]
        tri = self.triage_of(card)
        self.assertEqual((tri.get("class"), tri.get("way_back"), tri.get("needs_decision")),
                         ("new_requirement", 2, True))
        self.assertEqual([i["card"] for i in queue(self.factory)["items"]], [card])     # what waits on you
        self.assertEqual(now(self.p)["state"], "waiting_on_you")
        self.assertEqual(ksignals.square(self.factory)["end_user_feedback_waiting"], 0)

    def test_FR_I3_AC_1_website_feedback_gets_the_class_the_cockpit_gives_the_same_words(self):
        for words in self.WORDS:
            filed = self.turn(words, model=FakeModel(lambda prompt, role: CLEAR))["filed"]["id"]
            typed = kchange.submit(self.p, persona="end_user", person="Tester", text=words)   # the cockpit's path
            cockpit = kchange.triage(self.p, typed["id"], model=None)
            got = self.triage_of(filed)
            self.assertEqual((got.get("class"), got.get("needs_decision")),
                             (cockpit["class"], cockpit["needs_decision"]), words)

    def test_FR_I3_AC_1_a_triage_that_cannot_be_written_still_files_the_feedback(self):
        def broken(project, card_id, *, model=None):
            raise OSError("disk full")

        with mock.patch.object(kchange, "triage", broken):
            out = self.turn(self.WORDS[0])
        self.assertEqual((out["reply"], out["filed"]["kind"]), (kembeds.THANKS, "change"))
        self.assertEqual(self.triage_of(out["filed"]["id"]), {})
        self.assertEqual(ksignals.square(self.factory)["end_user_feedback_waiting"], 1)   # still in sight
        failed = [r["event"]["payload"] for r in self.p.ledger().records()
                  if isinstance(r, dict) and (r.get("event") or {}).get("kind") == "embed_triage_failed"]
        self.assertEqual(failed, [{"card": out["filed"]["id"], "embed": self.e["id"], "error": "OSError"}])


if __name__ == "__main__":
    unittest.main()
