import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel.canon import Canon, DecisionRefused
from kernel.store import write_json


class CanonTest(FactoryTestCase):
    def test_FR_S1_AC_1_new_project_has_a_full_canon(self):
        p = self.new()
        c = p.path("canon")
        for name in ("goal.md", "brief.md", "questions.json", "assumptions.json", "decisions.json"):
            self.assertTrue((c / name).exists(), name)
        self.assertTrue((c / "inbox").is_dir())
        self.assertTrue((c / "exchange").is_dir())
        self.assertEqual(Canon(p).goal, "Equipment loans")
        self.assertEqual(p.meta["stage"], 1)

    def test_FR_S1_AC_2_every_canon_change_is_in_the_ledger_and_it_verifies(self):
        p = self.new()
        canon = Canon(p)
        q = canon.add_question("Who approves?", "business", blocking=True)
        card = canon.ask(q["id"])
        canon.answer(q["id"], "the team lead", person="Aino", persona="business_owner")
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        for kind in ("project_created", "question_added", "card_opened", "decision", "question_answered"):
            self.assertIn(kind, kinds)
        head = p.ledger().head()
        result = p.ledger().verify(head=head)
        self.assertTrue(result.intact)
        self.assertTrue(result.tail_checked)
        # cutting the last line off the file is reported against the head
        lines = p.path("ledger.jsonl").read_text(encoding="utf-8").splitlines()
        p.path("ledger.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        self.assertFalse(p.ledger().verify(head=head).intact)
        self.assertEqual(Canon(p).get_card(card["id"])["state"], "decided")

    def test_FR_S4_AC_1_assumptions_have_due_dates_and_overdue_ones_are_listed(self):
        p = self.new()
        canon = Canon(p)
        a = canon.add_assumption("office hours are enough", "operations", due_days=7)
        self.assertEqual(a["due"], "2026-11-29")
        self.assertEqual(canon.overdue(), [])
        self.clock.advance(days=8)
        self.assertEqual([x["id"] for x in Canon(p).overdue()], [a["id"]])
        canon.settle_assumption(a["id"], confirmed=True, person="Aino", persona="business_owner")
        self.assertEqual(Canon(p).overdue(), [])

    def test_FR_M6_AC_1_a_non_person_cannot_decide(self):
        p = self.new()
        canon = Canon(p)
        card = canon.card("approval", "Merge T-001?")
        for who in ("factory", "claude", "model", "Gnomon", "", "agent"):
            with self.assertRaises(DecisionRefused):
                canon.decide(card["id"], "approve", person=who, persona="business_owner")
        d = canon.decide(card["id"], "approve", person="Aino", persona="business_owner")
        self.assertEqual(d["person"], "Aino")

    def test_FR_M6_AC_2_wrong_persona_or_verdict_is_refused(self):
        p = self.new()
        canon = Canon(p)
        gate = canon.card("deploy_gate", "Deploy release 1 to production?")
        with self.assertRaises(DecisionRefused):
            canon.decide(gate["id"], "approve", person="Aino", persona="business_owner")  # only IT decides
        with self.assertRaises(DecisionRefused):
            canon.decide(gate["id"], "accept", person="Ilkka", persona="it")  # not a deploy-gate verdict
        canon.decide(gate["id"], "approve", person="Ilkka", persona="it")
        with self.assertRaises(DecisionRefused):
            canon.decide(gate["id"], "refuse", person="Ilkka", persona="it")  # already decided
        decisions = json.loads(p.path("canon", "decisions.json").read_text(encoding="utf-8"))
        self.assertEqual(len(decisions), 1)

    def test_FR_M6_AC_3_settling_or_letting_the_factory_assume_is_a_signed_decision(self):
        p = self.new()
        canon = Canon(p)
        q = canon.add_question("Office hours enough?", "operations")
        canon.assume(q["id"], "office hours", chosen_by="Aino", persona="business_owner")
        a = canon.assumptions()[0]
        Canon(p).settle_assumption(a["id"], confirmed=False, person="Olli", persona="operations",
                                   correction="24/7 for the warehouse")
        ds = Canon(p).decisions()
        self.assertEqual([(d["person"], d["persona"], d["verdict"]) for d in ds],
                         [("Aino", "business_owner", "assume"), ("Olli", "operations", "answer")])
        self.assertIn("refuted", ds[1]["reason"])
        settled = [r["event"]["payload"] for r in p.ledger().of_kind("assumption_settled")]
        self.assertEqual(settled[0]["persona"], "operations")

    def test_FR_P3_AC_1_deciding_a_question_card_settles_its_question(self):
        # `rihma decide <pid> C-0001 answer --reason ...` decides the card through Canon.decide: the
        # question must move with it, or it stays open and blocking behind a decided card.
        p = self.new()
        canon = Canon(p)
        q = canon.add_question("Who approves a loan?", "business", blocking=True, opinions={"business": "the team lead"})
        card = canon.ask(q["id"])
        refused = [lambda: canon.decide(card["id"], "answer", person="Aino", persona="business_owner"),  # no text
                   lambda: canon.decide(card["id"], "answer", person="factory", persona="business_owner",
                                        reason="the team lead"),
                   lambda: canon.decide(card["id"], "approve", person="Aino", persona="business_owner")]
        for fn in refused:
            with self.assertRaises(DecisionRefused):
                fn()
        self.assertEqual((Canon(p).question(q["id"])["status"], Canon(p).decisions()), ("open", []))
        d = canon.decide(card["id"], "answer", person="Aino", persona="business_owner",
                         reason="the team lead approves")
        self.assertEqual((d["card"], d["verdict"], d["person"]), (card["id"], "answer", "Aino"))
        answered = Canon(p).question(q["id"])
        self.assertEqual((answered["status"], answered["answer"]["text"], answered["answer"]["by"]),
                         ("answered", "the team lead approves", "Aino"))
        self.assertEqual(Canon(p).get_card(card["id"])["state"], "decided")
        self.assertEqual(Canon(p).questions("open"), [])                    # nothing blocks the spec now
        self.assertEqual([x["id"] for x in Canon(p).decisions()], [d["id"]])
        # "assume" on the card takes the asking perspective's proposed answer as an assumption
        q2 = canon.add_question("Are office hours enough?", "operations", opinions={"operations": "office hours"})
        c2 = canon.ask(q2["id"])
        canon.decide(c2["id"], "assume", person="Olli", persona="operations")
        self.assertEqual(Canon(p).question(q2["id"])["status"], "assumed")
        self.assertEqual([(a["text"], a["question"]) for a in Canon(p).assumptions()], [("office hours", q2["id"])])
        # with no proposed answer there is nothing to assume: the card stays open
        q3 = canon.add_question("Which colours?", "end_user")
        c3 = canon.ask(q3["id"])
        with self.assertRaises(DecisionRefused):
            canon.decide(c3["id"], "assume", person="Olli", persona="operations")
        self.assertEqual((Canon(p).get_card(c3["id"])["state"], Canon(p).question(q3["id"])["status"]),
                         ("open", "open"))

    def strand(self, p, card_id: str, verdict: str, person: str, persona: str) -> None:
        """Leave a question open behind its decided card, as deciding the card once did."""
        path = p.path("canon", "inbox", f"{card_id}.json")
        card = json.loads(path.read_text(encoding="utf-8"))
        card["state"], card["decision"] = "decided", {"id": "D-001", "verdict": verdict, "person": person,
                                                      "persona": persona, "reason": "", "at": "2026-11-22T12:00:00Z"}
        write_json(path, card)

    def test_FR_P3_AC_1_a_question_left_open_behind_its_decided_card_can_still_be_settled(self):
        p = self.new()
        canon = Canon(p)
        q = canon.add_question("Who approves a loan?", "business", blocking=True)
        self.strand(p, canon.ask(q["id"])["id"], "answer", "Aino", "business_owner")
        with self.assertRaises(DecisionRefused):                              # still only a person
            canon.answer(q["id"], "the team lead", person="factory", persona="business_owner")
        canon.answer(q["id"], "the team lead approves", person="Aino", persona="business_owner")
        self.assertEqual(Canon(p).question(q["id"])["status"], "answered")
        self.assertEqual([(d["person"], d["verdict"]) for d in Canon(p).decisions()], [("Aino", "answer")])
        q2 = canon.add_question("Are office hours enough?", "operations")
        self.strand(p, canon.ask(q2["id"])["id"], "assume", "Olli", "operations")
        with self.assertRaises(DecisionRefused):                              # the factory cannot on its own
            canon.assume(q2["id"], "office hours")
        canon.assume(q2["id"], "office hours", chosen_by="Olli", persona="operations")
        self.assertEqual(Canon(p).question(q2["id"])["status"], "assumed")


if __name__ == "__main__":
    unittest.main()
