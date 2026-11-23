import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import PANEL, SPEC, FactoryTestCase, model, script  # noqa: E402

from kernel.canon import PERSPECTIVES, Canon  # noqa: E402
from kernel.intake import SendBack, intake  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops. We want a simple way to lend and return things."
N_QUESTIONS = sum(len(q) for q in PANEL.values()) + 1  # + the look, asked once at setup


class IntakeTest(FactoryTestCase):
    def test_FR_A6_AC_1_socratic_puts_every_question_to_a_person(self):
        p = self.new(mode="socratic")
        out = intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        self.assertEqual(len(out["asked"]), N_QUESTIONS)
        self.assertEqual(out["assumed"], [])
        self.assertEqual(canon.assumptions(), [])
        self.assertEqual(len(canon.cards(kind="question")), N_QUESTIONS)

    def test_FR_A6_AC_2_assume_mode_assumes_everything_with_due_dates(self):
        p = self.new(mode="assume")
        out = intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        self.assertEqual(out["asked"], [])
        self.assertEqual(len(canon.assumptions()), N_QUESTIONS)
        self.assertTrue(all(a["due"] for a in canon.assumptions()))
        self.assertEqual(canon.cards(kind="question"), [])
        self.assertIn("[assumed]", canon.brief)

    def test_FR_A6_AC_3_mixed_mode_asks_blocking_and_lets_a_person_assume(self):
        p = self.new(mode="mixed")
        out = intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        self.assertEqual(len(out["asked"]), 1)  # only the blocking business question
        self.assertEqual(len(out["assumed"]), N_QUESTIONS - 1)
        q = canon.questions("open")[0]
        self.assertTrue(q["blocking"])
        a = canon.assume(q["id"], q["opinions"][q["perspective"]], chosen_by="Aino", persona="business_owner")
        self.assertEqual(Canon(p).question(q["id"])["status"], "assumed")
        self.assertEqual(Canon(p).question(q["id"])["answer"]["chosen_by"], "Aino")
        self.assertTrue(a["due"])
        self.assertEqual(Canon(p).get_card(q["card"])["state"], "decided")

    def test_FR_A7_AC_1_every_perspective_is_asked_and_recorded(self):
        p = self.new(mode="assume")
        m = model()
        intake(p, IDEA, model=m, requested_by="Aino")
        asked = [prompt for role, prompt in m.calls if "perspective on a panel" in prompt]
        self.assertEqual(len(asked), len(PERSPECTIVES))
        recorded = {q["perspective"] for q in Canon(p).questions()}
        self.assertEqual(recorded, set(PERSPECTIVES))

    def test_FR_A7_AC_2_differing_opinions_are_kept_side_by_side(self):
        p = self.new(mode="socratic")
        intake(p, IDEA, model=model(), requested_by="Aino")
        q1 = Canon(p).question("Q-001")
        self.assertEqual(set(q1["opinions"]), {"business", "it_security", "end_user"})
        self.assertIn("audit", q1["opinions"]["it_security"])
        self.assertIn("team lead", q1["opinions"]["business"])
        brief = Canon(p).brief
        self.assertIn("opinion, it_security", brief)

    def test_FR_A5_AC_1_no_spec_while_blocking_questions_are_open(self):
        p = self.new(mode="mixed")
        intake(p, IDEA, model=model(), requested_by="Aino")
        with self.assertRaises(SendBack) as ctx:
            make_spec(p, model=model())
        self.assertEqual([q["id"] for q in ctx.exception.questions], ["Q-001"])
        self.assertFalse(p.path("spec.json").exists())

    def test_FR_A3_AC_1_provenance_is_decided_by_rule(self):
        p = self.new(mode="mixed")
        intake(p, IDEA, model=model(), requested_by="Aino")
        Canon(p).answer("Q-001", "the team lead approves", person="Pekka", persona="business_owner")
        spec = make_spec(p, model=model())
        prov = {r["id"]: (r["provenance"], r.get("decided_by")) for r in spec["requirements"]}
        self.assertEqual(prov["R-1"], ("customer-endorsed", "Aino"))      # from the request
        self.assertEqual(prov["R-2"], ("customer-confirmed", "Pekka"))    # from an answered question
        self.assertEqual(prov["R-3"], ("assumption", None))               # from an assumed question
        self.assertEqual(prov["R-4"], ("vendor-proposed", None))          # proposed by the analyst
        self.assertEqual(p.meta["stage"], 4)

    def test_FR_A3_AC_2_the_customers_own_requirement_ids_are_kept(self):
        import copy
        import json as _json

        from kernel.model import FakeModel

        spec = copy.deepcopy(SPEC)
        spec["requirements"][0]["id"] = "fr-krit-001"   # the customer's id, any case
        spec["requirements"][1]["id"] = "R-9"            # a generated-looking id is not the customer's
        spec["requirements"][2]["id"] = "FR-KRIT-001"    # a duplicate is not kept twice

        def with_ids(prompt, role):
            if "You turn a brief into a software specification" in prompt:
                self.assertIn("keep the id", prompt)
                return "```json\n" + _json.dumps(spec) + "\n```"
            return script(prompt, role)

        p = self.new(mode="assume")
        intake(p, IDEA, model=FakeModel(with_ids), requested_by="Aino")
        out = make_spec(p, model=FakeModel(with_ids))
        ids = [r["id"] for r in out["requirements"]]
        self.assertEqual(ids, ["FR-KRIT-001", "R-1", "R-2", "R-3"])
        self.assertEqual(out["requirements"][0]["acceptance"][0]["id"], "FR-KRIT-001-AC-1")


if __name__ == "__main__":
    unittest.main()
