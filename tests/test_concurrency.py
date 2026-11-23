"""Writers at once: the file lock, the canon, the signals and the factory's own canon.

An embed's requests, the pipeline job, the cockpit and the MCP server all write the same factory
home, in threads and in processes. Each record file (cards, decisions, signals) changes under a
lock (kernel/store.py updating_json), so nothing one writer adds is lost to another, no two take
the same id, and the lock waits for its holder on every platform, up to a bounded time.

Standard library only: python -m unittest discover -s tests
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase

from kernel import change, dashboard, filelock, signals, store
from kernel.canon import Canon, DecisionRefused
from kernel.filelock import LockHeld
from kernel.learn import factory_project, model_reliability
from kernel.ledgerstore import LedgerStore
from kernel.model import FakeModel

PEOPLE = ("Aino", "Olli", "Sanna", "Pekka", "Tiina", "Kaisa", "Ilkka", "Dana")

# Holds a lock in another process: prints "held", then keeps it for the seconds given.
HOLDER = """import sys, time
sys.path.insert(0, sys.argv[1])
from kernel.filelock import locked
with locked(sys.argv[2]):
    print("held", flush=True)
    time.sleep(float(sys.argv[3]))
"""

# Opens cards on one project from another process, once the go file exists.
CARD_WRITER = """import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from kernel.canon import Canon
from kernel.store import Factory
home, pid, who, n, go = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), Path(sys.argv[6])
project = Factory(home).project(pid)
print("ready", flush=True)
while not go.exists():
    time.sleep(0.005)
for i in range(n):
    Canon(project).card("change", f"{who} #{i}")
"""


def at_once(n: int, fn) -> list:
    """Run fn(0) .. fn(n - 1) in n threads released together: what each returned, or what it raised."""
    start = threading.Barrier(n)
    out: list = [None] * n

    def run(i: int) -> None:
        try:
            start.wait(10)
            out[i] = fn(i)
        except Exception as exc:  # noqa: BLE001 - returned to the test, which asserts on it
            out[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    return out


def raised(results: list) -> list:
    return [repr(r) for r in results if isinstance(r, BaseException)]


def tree(root: Path) -> dict:
    """Every file under ``root`` by its path, with the sha256 of its bytes."""
    root = Path(root)
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class FileLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-lock-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)   # runs after each holder is stopped

    def hold(self, lock: Path, seconds: float) -> None:
        """Another process takes the lock and keeps it for ``seconds``."""
        proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(ROOT), str(lock), str(seconds)],
                                stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait, 30)
        self.addCleanup(proc.kill)
        self.addCleanup(proc.stdout.close)
        self.assertEqual(proc.stdout.readline().strip(), "held")

    def test_FR_L2_AC_1_an_append_waits_for_a_lock_held_longer_than_ten_seconds(self):
        # msvcrt's own blocking lock gives up after about ten seconds; a writer must wait its turn.
        path = self.tmp / "ledger.jsonl"
        store = LedgerStore(path)
        store.append("first", {"n": 0})
        self.hold(path.with_name(path.name + ".lock"), 12)
        started = time.monotonic()
        record = store.append("second", {"n": 1})
        self.assertGreater(time.monotonic() - started, 5)              # it waited for the holder
        self.assertEqual(record["seq"], 1)
        self.assertTrue(store.verify(head=store.head()).intact)

    def test_FR_L2_AC_1_a_lock_never_let_go_fails_after_a_bounded_wait_and_appends_nothing(self):
        path = self.tmp / "ledger.jsonl"
        lock = path.with_name(path.name + ".lock")
        self.hold(lock, 60)
        started = time.monotonic()
        with mock.patch.object(filelock, "WAIT_SECONDS", 0.5), self.assertRaises(LockHeld) as caught:
            LedgerStore(path).append("step", {"n": 0})
        self.assertLess(time.monotonic() - started, 30)           # the bound, not the default hour
        self.assertIn(str(lock), str(caught.exception))           # the error names the lock
        self.assertIn("0.5 s", str(caught.exception))             # and how long it waited
        self.assertFalse(path.exists())
        with self.assertRaises(LockHeld), filelock.locked(lock, timeout=0.2):   # a caller's own bound
            pass


class CanonAtOnceTest(FactoryTestCase):
    def test_FR_L2_AC_2_cards_and_decisions_made_at_once_are_all_kept_with_their_own_ids(self):
        p = self.new()
        approvals = [Canon(p).card("approval", f"plan {i}") for i in range(8)]

        def work(i: int) -> dict:
            canon = Canon(p)
            canon.card("change", f"feedback {i}")
            return canon.decide(approvals[i]["id"], "approve", person=PEOPLE[i], persona="business_owner")

        results = at_once(8, work)
        self.assertEqual(raised(results), [])
        cards = Canon(p).cards(state=None)
        self.assertEqual([c["id"] for c in cards], [f"C-{n:04d}" for n in range(1, 17)])
        self.assertEqual(sorted(c["title"] for c in cards if c["kind"] == "change"),
                         sorted(f"feedback {i}" for i in range(8)))
        decisions = Canon(p).decisions()
        self.assertEqual(sorted(d["id"] for d in decisions), [f"D-{n:03d}" for n in range(1, 9)])
        for card in Canon(p).cards(state=None, kind="approval"):           # each card holds its own decision
            self.assertEqual(card["state"], "decided")
            mine = [d for d in decisions if d["card"] == card["id"]]
            self.assertEqual([d["id"] for d in mine], [card["decision"]["id"]])
        led = p.ledger()
        self.assertEqual(len(led.of_kind("card_opened")), 16)
        self.assertEqual(len(led.of_kind("decision")), 8)
        self.assertTrue(led.verify().intact)

    def test_FR_L2_AC_2_a_card_two_people_decide_at_once_takes_one_decision(self):
        p = self.new()
        card = Canon(p).card("change", "Show overdue loans first")
        results = at_once(6, lambda i: Canon(p).decide(card["id"], "accept", person=PEOPLE[i],
                                                         persona="business_owner"))
        taken = [r for r in results if isinstance(r, dict)]
        self.assertEqual(len(taken), 1, results)
        self.assertTrue(all(isinstance(r, DecisionRefused) for r in results if not isinstance(r, dict)), results)
        self.assertEqual([d["id"] for d in Canon(p).decisions()], [taken[0]["id"]])
        self.assertEqual(Canon(p).get_card(card["id"])["decision"]["person"], taken[0]["person"])

    def test_FR_L2_AC_2_a_change_decided_while_triage_writes_back_its_class_stays_decided(self):
        p = self.new()
        card = change.submit(p, persona="end_user", person="Dana", text="The list should show overdue loans first")
        path = Canon(p).dir / "inbox" / f"{card['id']}.json"
        read, real = threading.Event(), store.write_json

        def slow(target: Path, obj: object) -> None:
            # Triage read the card and is slow to write it back with its class: the decision lands meanwhile.
            if threading.current_thread().name == "triage" and Path(target) == path:
                read.set()
                time.sleep(0.5)
            real(target, obj)

        def decide() -> None:
            read.wait(5)
            Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner")

        with mock.patch.object(store, "write_json", slow):
            threads = [threading.Thread(target=change.triage, args=(p, card["id"]), name="triage"),
                       threading.Thread(target=decide, name="decider")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        self.assertTrue(read.is_set())
        decided = Canon(p).get_card(card["id"])
        self.assertEqual((decided["state"], decided["decision"]["verdict"]), ("decided", "accept"))
        self.assertIn("triage", decided["payload"])                               # the class is kept too
        with self.assertRaises(DecisionRefused):                                   # and no second decision
            Canon(p).decide(card["id"], "reject", person="Olli", persona="product_owner")
        self.assertEqual([d["verdict"] for d in Canon(p).decisions() if d["card"] == card["id"]], ["accept"])

    def test_FR_L2_AC_2_a_card_written_back_from_a_copy_read_before_its_decision_still_reads_decided(self):
        p = self.new()
        canon = Canon(p)
        card = canon.card("change", "Show overdue loans first")
        stale = canon.get_card(card["id"])                       # a writer outside the lock reads it
        d = canon.decide(card["id"], "accept", person="Aino", persona="business_owner")
        stale["payload"]["note"] = "written back late"
        store.write_json(canon.dir / "inbox" / f"{card['id']}.json", stale)
        got = canon.get_card(card["id"])
        self.assertEqual((got["state"], got["decision"]["id"], got["payload"]["note"]),
                         ("decided", d["id"], "written back late"))
        self.assertEqual([c["id"] for c in canon.cards(state="decided")], [card["id"]])
        self.assertEqual(canon.cards(state="open"), [])
        with self.assertRaises(DecisionRefused):
            canon.decide(card["id"], "reject", person="Olli", persona="product_owner")
        canon.close(card["id"], "done", state="resolved")       # the next locked write keeps the decision
        on_disk = store.read_json(canon.dir / "inbox" / f"{card['id']}.json")
        self.assertEqual((on_disk["state"], on_disk["decision"]["id"]), ("resolved", d["id"]))
        self.assertEqual([x["id"] for x in canon.decisions()], [d["id"]])

    def test_FR_L2_AC_2_cards_opened_by_processes_at_once_are_all_kept(self):
        p = self.new()
        go = self.tmp / "go"
        procs = [subprocess.Popen([sys.executable, "-c", CARD_WRITER, str(ROOT), str(self.factory.home), p.pid,
                                   f"writer {w}", "5", str(go)], stdout=subprocess.PIPE, text=True)
                 for w in range(3)]
        for proc in procs:
            self.addCleanup(proc.stdout.close)
            self.assertEqual(proc.stdout.readline().strip(), "ready")
        go.write_text("go", encoding="utf-8")
        for proc in procs:
            self.assertEqual(proc.wait(120), 0)
        cards = Canon(p).cards()
        self.assertEqual([c["id"] for c in cards], [f"C-{n:04d}" for n in range(1, 16)])
        self.assertEqual(sorted(c["title"] for c in cards), sorted(f"writer {w} #{i}" for w in range(3) for i in range(5)))
        self.assertEqual(len(p.ledger().of_kind("card_opened")), 15)
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_L2_AC_2_project_fields_changed_at_once_are_all_kept(self):
        # The pipeline moves the stage while a person asks for a pause: neither change is written over.
        p = self.new()
        results = at_once(12, lambda i: p.update_meta(**{f"field_{i}": i}))
        self.assertEqual(raised(results), [])
        meta = p.meta
        self.assertEqual({k: v for k, v in meta.items() if k.startswith("field_")}, {f"field_{i}": i for i in range(12)})
        self.assertEqual((meta["id"], meta["title"]), (p.pid, "Equipment loans"))

    def test_FR_P5_AC_1_a_decision_recorded_while_approvals_go_stale_never_erases_the_stale_marks(self):
        p = self.new()
        for rnd in range(3):
            self.stale_while_deciding(p, rnd)

    def stale_while_deciding(self, p, rnd: int) -> None:
        """An amendment marks the plan's approval stale while eight other approvals are recorded."""
        canon = Canon(p)
        plan = canon.card("approval", f"plan {rnd}", refs={"requirements": ["R-1"]})
        canon.decide(plan["id"], "approve", person="Aino", persona="business_owner")
        others = [canon.card("approval", f"task {rnd}.{i}") for i in range(8)]

        def work(i: int):
            if i == 0:
                return Canon(p).mark_stale(["R-1"], reason="R-1 was amended")
            return Canon(p).decide(others[i - 1]["id"], "approve", person=PEOPLE[i - 1], persona="developer")

        self.assertEqual(raised(at_once(9, work)), [])
        by_card = {d["card"]: d for d in Canon(p).decisions()}
        self.assertTrue(by_card[plan["id"]]["stale"], rnd)                     # the stale mark stays
        self.assertEqual([o["id"] for o in others if o["id"] in by_card], [o["id"] for o in others])
        self.assertFalse(any(by_card[o["id"]]["stale"] for o in others))       # and only it was marked


class SignalsAtOnceTest(FactoryTestCase):
    def test_FR_T3_AC_1_signals_sent_in_at_once_are_each_kept_with_their_own_id(self):
        results = at_once(16, lambda i: signals.receive(self.factory, f"need number {i}", channel="embed",
                                                         source="website chat"))
        self.assertEqual(raised(results), [])
        kept = signals.signals(self.factory)
        self.assertEqual(sorted(s["id"] for s in kept), [f"S-{n:03d}" for n in range(1, 17)])
        self.assertEqual(sorted(s["text"] for s in kept), sorted(f"need number {i}" for i in range(16)))
        self.assertEqual(sorted(r["id"] for r in results), sorted(s["id"] for s in kept))
        led = factory_project(self.factory).ledger()
        self.assertEqual(sorted(r["event"]["payload"]["id"] for r in led.of_kind("signal_received")),
                         sorted(s["id"] for s in kept))
        self.assertTrue(led.verify().intact)

    def test_FR_T3_AC_1_a_signal_received_while_triage_waits_on_its_model_is_kept(self):
        first = signals.receive(self.factory, "We need a way to book the meeting rooms", channel="chat",
                                source="team chat", person="Aino")

        def analyst(prompt: str, role: str) -> str:
            # While the analyst thinks, a website visitor's need arrives.
            signals.receive(self.factory, "Invoices wait for approval by email", channel="embed", source="site")
            return '```json\n{"title": "Room booking", "problem": "rooms are double-booked"}\n```'

        routed = signals.triage(self.factory, first["id"], model=FakeModel(analyst))
        self.assertEqual(routed["state"], "concept")
        kept = {s["id"]: s for s in signals.signals(self.factory)}
        self.assertEqual(sorted(kept), ["S-001", "S-002"])
        self.assertEqual((kept["S-001"]["state"], kept["S-002"]["state"]), ("concept", "new"))
        self.assertEqual(kept["S-002"]["text"], "Invoices wait for approval by email")
        third = signals.receive(self.factory, "Badge access for visitors", channel="form", source="intranet")
        self.assertEqual(third["id"], "S-003")                              # no id is taken twice
        second = signals.triage(self.factory, "S-002")
        self.assertNotEqual(second["routed_to"]["card"], routed["routed_to"]["card"])

    def test_FR_P1_AC_1_a_model_answering_a_list_still_makes_the_need_a_concept(self):
        s = signals.receive(self.factory, "Track who borrowed the drills\nand when they come back",
                            channel="chat", source="team chat")
        model = FakeModel(lambda prompt, role: '```json\n[{"title": "Loans", "problem": "lost drills"}]\n```')
        routed = signals.triage(self.factory, s["id"], model=model)
        self.assertEqual(routed["state"], "concept")
        card = Canon(factory_project(self.factory)).get_card(routed["routed_to"]["card"])
        self.assertEqual(card["payload"]["title"], "Track who borrowed the drills")  # the rules' title
        self.assertIsNone(card["payload"]["summary"])

    def test_FR_P1_AC_1_an_edit_made_while_the_concept_is_decided_never_reopens_it(self):
        s = signals.receive(self.factory, "We need a way to book the meeting rooms", channel="chat", source="chat")
        card = signals.triage(self.factory, s["id"])["routed_to"]["card"]
        read, real = threading.Event(), Canon.get_card

        def slow(canon, card_id):
            # The editor reads the card, then is slow to write it back: the decision lands meanwhile.
            got = real(canon, card_id)
            if threading.current_thread().name == "editor":
                read.set()
                time.sleep(0.5)
            return got

        def edit():
            try:
                signals.edit_concept(self.factory, card, person="Pekka", persona="product_owner", title="Room booking")
            except DecisionRefused:  # the concept was decided first: the edit is refused, nothing lost
                pass

        def decide():
            read.wait(1.0)
            Canon(factory_project(self.factory)).decide(card, "validate", person="Aino", persona="business_owner")

        with mock.patch.object(Canon, "get_card", slow):
            threads = [threading.Thread(target=edit, name="editor"), threading.Thread(target=decide, name="decider")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
        fp = factory_project(self.factory)
        decided = Canon(fp).get_card(card)
        self.assertEqual(decided["state"], "decided")
        self.assertEqual([d["id"] for d in Canon(fp).decisions() if d["card"] == card], [decided["decision"]["id"]])

    def test_FR_V2_AC_2_appliers_at_once_carry_out_a_validated_concept_once(self):
        s = signals.receive(self.factory, "We need a way to book the meeting rooms", channel="chat", source="chat")
        card = signals.triage(self.factory, s["id"])["routed_to"]["card"]
        fp = factory_project(self.factory)
        Canon(fp).decide(card, "validate", person="Aino", persona="business_owner")
        results = at_once(4, lambda i: signals.apply_concepts(self.factory))
        self.assertEqual(raised(results), [])
        made = [p for p in self.factory.projects() if not p.pid.startswith("_")]
        self.assertEqual(len(made), 1, [p.pid for p in made])
        self.assertEqual(sorted(len(r) for r in results), [0, 0, 0, 1])
        self.assertEqual(len(fp.ledger().of_kind("concept_applied")), 1)
        self.assertEqual(signals.signals(self.factory)[0]["state"], "validated")


class FactoryCanonTest(FactoryTestCase):
    def test_FR_S1_AC_3_the_signal_list_the_square_and_the_catalogue_never_create_the_factory_canon(self):
        self.new()
        before = tree(self.factory.home)
        self.assertEqual(signals.signals(self.factory), [])
        self.assertEqual(signals.square(self.factory)["concepts_waiting"], [])
        self.assertEqual([i for i in dashboard.catalogue(self.factory)["items"] if i["state"] == "proposed"], [])
        self.assertEqual(signals.apply_concepts(self.factory), [])
        with self.assertRaises(KeyError):
            signals.edit_concept(self.factory, "C-0001", person="Aino", persona="business_owner", title="x")
        self.assertIsNone(factory_project(self.factory, create=False))
        self.assertEqual(tree(self.factory.home), before)


class RetriedTaskTest(FactoryTestCase):
    def test_FR_F8_AC_1_after_a_retry_each_gate_counts_for_the_model_that_built_that_attempt(self):
        p = self.new()
        for rnd in range(3):                                   # model-a: three rounds, none passes
            p.log("cell_ran", {"task": "T-001", "round": rnd, "final_model": "model-a"})
            p.log("gate", {"task": "T-001", "round": rnd, "verdict": "failed"})
        p.log("escalated", {"task": "T-001", "card": "C-0001"})
        p.log("cell_ran", {"task": "T-001", "round": 0, "final_model": "model-b"})   # a person chose retry
        p.log("gate", {"task": "T-001", "round": 0, "verdict": "passed"})
        rel = model_reliability(self.factory)
        a, b = rel["model-a"], rel["model-b"]
        self.assertEqual((a["cells"], a["measured"], a["first_round_warranted_rate"], a["mean_rounds_to_pass"]),
                         (3, True, 0.0, None))
        self.assertEqual((b["cells"], b["measured"], b["first_round_warranted_rate"], b["mean_rounds_to_pass"]),
                         (1, True, 1.0, 1.0))
        self.assertNotIn("unknown", rel)


if __name__ == "__main__":
    unittest.main()
