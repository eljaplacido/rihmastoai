"""The mode columns: socratic, assume and mixed (docs/acceptance.md; FR-AM3).

The mode decides what happens to each of the panel's questions: socratic puts every one to a
person, assume takes each proposal as an assumption with a due date, and mixed puts the blocking
ones to a person and assumes the rest. A question nobody proposed an answer to (which kind of work
is this?) goes to a person in every mode, and no spec is written while a blocking one is open.
"""

from kernel.canon import Canon
from kernel.pipeline import advance
from kernel.profiles import PROFILE_QUESTION

from .needs import NEEDS
from .scripts import OWNER, AcceptanceCase, trace

GREENFIELD_AND_SMALL = list(NEEDS)        # every row but B, which has no panel


class ModesTest(AcceptanceCase):
    roads = False

    def test_FR_AM3_AC_1_each_mode_puts_to_a_person_exactly_what_it_says_for_every_need(self):
        for key in GREENFIELD_AND_SMALL:
            for mode in ("socratic", "assume", "mixed"):
                with self.subTest(need=key, mode=mode):
                    p = self.need(key, mode=mode, maturity="demo")
                    canon = Canon(p)
                    questions = canon.questions()
                    to_person = {c["refs"]["question"] for c in canon.cards(kind="question")}
                    assumed = {q["id"] for q in canon.questions("assumed")}
                    unproposed = {q["id"] for q in questions if not q["opinions"].get(q["perspective"])}
                    self.assertEqual(unproposed, {q["id"] for q in questions if q["text"] == PROFILE_QUESTION})
                    if mode == "socratic":
                        self.assertEqual(to_person, {q["id"] for q in questions})
                        self.assertEqual(assumed, set())
                    elif mode == "assume":
                        self.assertEqual(to_person, unproposed)
                    else:
                        self.assertEqual(to_person, {q["id"] for q in questions if q["blocking"]})
                    self.assertEqual(to_person | assumed, {q["id"] for q in questions})
                    self.assertEqual(len(canon.assumptions()), len(assumed))       # each with its due date
                    blocking_open = [q for q in canon.questions("open") if q["blocking"]]
                    one = advance(p, model=self.model, max_steps=1)
                    if blocking_open:
                        self.assertEqual((one["state"], one["stage"]), ("waiting", 2))
                        self.assertFalse(p.path("spec.json").exists())
                    else:
                        self.assertTrue(p.path("spec.json").exists(), one)


class ModesEndToEndTest(AcceptanceCase):
    def test_FR_AM3_AC_2_socratic_mode_asks_every_question_and_the_spec_rests_on_the_persons_answers(self):
        p = self.need("rooms", mode="socratic", maturity="demo")
        canon = Canon(p)
        cards = canon.cards(kind="question")
        self.assertEqual(len(cards), len(canon.questions()))
        self.assertEqual(canon.assumptions(), [])
        waiting = self.run_chain(p)
        blocking = sorted(c["id"] for c in cards if c["blocking"])
        self.assertEqual((waiting["state"], sorted(waiting["waiting_on"])), ("waiting", blocking))
        look = next(q for q in canon.questions() if q["text"].startswith("What look and feel"))
        canon.decide(look["card"], "assume", person=OWNER[0], persona=OWNER[1])    # "let Rihma assume", by Aino
        self.answer_open(p)                                                         # Aino answers every other card
        out, decided = self.ship(p)
        self.assertEqual(decided, [("approval", "business_owner")])
        for r in p.read("spec.json")["requirements"]:
            if any(s.startswith("Q-") for s in r["sources"]):
                self.assertEqual((r["provenance"], r["decided_by"]), ("customer-confirmed", "Aino"), r)
        self.assertDelivered(p, out, "demo")
        t = self.assertTraced(p, decided_by={OWNER})
        self.assertEqual((t["delegated"], len(t["assumed"])), (["Aino"], 1))         # the one she let it assume

    def test_FR_AM3_AC_3_assume_mode_runs_to_the_demo_with_one_decision_and_every_guess_on_record(self):
        p = self.need("rooms", mode="assume", maturity="demo")
        canon = Canon(p)
        self.assertEqual(canon.cards(kind="question"), [])
        out, decided = self.ship(p)
        self.assertEqual(decided, [("approval", "business_owner")])                 # only the demo's acceptance
        prov = {r["id"]: r["provenance"] for r in p.read("spec.json")["requirements"]}
        self.assertEqual(prov, {"R-1": "customer-endorsed", "R-2": "assumption", "R-3": "assumption",
                                "R-4": "vendor-proposed"})
        due = {a["due"] for a in canon.assumptions("open")}
        self.assertEqual(due, {"2026-12-06"})                                       # 14 days after the clock's day
        self.assertDelivered(p, out, "demo")
        t = trace(p)
        self.assertEqual((t["delegated"], len(t["assumed"])), ([], len(canon.questions())))
