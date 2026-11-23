import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import (GOOD_ROUTES, GOOD_TEST, FactoryTestCase, good_cell, lazy_cell, model,  # noqa: E402
                           no_findings)

from kernel.canon import Canon  # noqa: E402
from kernel.change import apply_change, submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.learn import (FACTORY_PID, apply_accepted, factory_project, immune_memory, model_reliability,  # noqa: E402
                          people_reliability, propose)
from kernel.spec import make_spec  # noqa: E402
from kernel.workspace import open_workspace, submit_workspace  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
DEFECT = "Adding an item with an empty name crashes with 500"


class LearnTest(FactoryTestCase):
    def compiled(self, title):
        p = self.new(mode="assume", title=title)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def defect(self, p):
        card = submit(p, persona="end_user", person="Tester", text=DEFECT)
        triage(p, card["id"], model=model())
        apply_change(p, card["id"], model=model())

    def test_FR_K3_AC_1_a_lesson_recurring_in_two_projects_becomes_a_default_check_after_a_person_accepts(self):
        a, b = self.compiled("Loans A"), self.compiled("Loans B")
        self.defect(a)
        self.assertEqual(propose(self.factory), [])           # one project: not yet the factory's problem
        self.defect(b)
        cards = propose(self.factory)
        self.assertEqual(len(cards), 1)
        self.assertEqual(sorted(cards[0]["payload"]["projects"]), sorted([a.pid, b.pid]))
        self.assertEqual(propose(self.factory), [])           # not proposed twice
        before = self.compiled("Loans C")
        self.assertFalse(any(r["id"].startswith("FD-") for r in before.read("contract.json")["requirements"]))
        fp = factory_project(self.factory)
        Canon(fp).decide(cards[0]["id"], "approve", person="Aino", persona="business_owner")
        added = apply_accepted(self.factory)
        self.assertEqual(len(added), 1)
        after = self.compiled("Loans D")
        fd = [r for r in after.read("contract.json")["requirements"] if r["id"].startswith("FD-")]
        self.assertEqual(len(fd), 1)
        self.assertIn("400", fd[0]["acceptance"][0]["then"])
        self.assertTrue(any("FD-1-AC-1" in t["criteria"] for t in after.read("contract.json")["tasks"]))
        self.assertNotIn(FACTORY_PID, [p.pid for p in self.factory.projects() if p.pid != FACTORY_PID])

    def test_FR_F8_AC_1_each_builder_models_reliability_comes_from_the_ledgers(self):
        a, b = self.compiled("Loans A"), self.compiled("Loans B")
        build_task(a, "T-001", lanes=Lanes(self.tmp / "la", size=1), cell_runner=good_cell, verifier_runner=no_findings)
        build_task(b, "T-001", lanes=Lanes(self.tmp / "lb", size=1), cell_runner=lazy_cell,
                   verifier_runner=no_findings, max_rounds=1)
        stats = model_reliability(self.factory)["fake-builder"]
        self.assertEqual(stats["cells"], 3)                    # 1 round in A, 2 in B
        self.assertEqual(stats["first_round_warranted_rate"], 0.5)
        self.assertEqual(stats["mean_rounds_to_pass"], 1.0)
        self.assertTrue(stats["measured"])

    def test_FR_F8_AC_2_a_persons_gate_rounds_are_reported_as_people_never_under_a_model(self):
        a, b = self.compiled("Loans A"), self.compiled("Loans B")
        build_task(a, "T-001", lanes=Lanes(self.tmp / "la", size=1), cell_runner=good_cell, verifier_runner=no_findings)
        build_task(b, "T-001", lanes=Lanes(self.tmp / "lb", size=1), cell_runner=lazy_cell,
                   verifier_runner=no_findings, max_rounds=1)            # escalated after rounds 0 and 1
        lanes = Lanes(self.tmp / "lw", size=1)
        for persona, routes in (("developer", GOOD_ROUTES), ("product_owner", GOOD_ROUTES + "\n")):
            ws = open_workspace(b, person="Aino", persona=persona, agent="shell", root=self.tmp / "lw")
            path = Path(ws["path"])
            for rel, text in (("app/routes.py", routes), ("tests/test_items.py", GOOD_TEST)):
                (path / rel).parent.mkdir(parents=True, exist_ok=True)
                (path / rel).write_text(text, encoding="utf-8", newline="\n")
            _git(path, "add", "-A")
            _git(path, "-c", "user.name=Aino", "-c", "user.email=aino@example.invalid", "commit", "-q", "-m", "Items")
            submit_workspace(b, ws["path"], person="Aino", persona=persona, task="T-001", lanes=lanes,
                             verifier_runner=no_findings)
        gates = [r["event"]["payload"] for r in b.ledger().of_kind("gate")]
        self.assertEqual([(g["round"], "author" in g) for g in gates], [(0, False), (1, False), (2, True), (3, True)])
        models = model_reliability(self.factory)
        self.assertEqual(set(models), {"fake-builder"})                  # no "unknown" model made of a person
        self.assertEqual((models["fake-builder"]["cells"], models["fake-builder"]["first_round_warranted_rate"],
                          models["fake-builder"]["mean_rounds_to_pass"]), (3, 0.5, 1.0))
        people = people_reliability(self.factory)
        self.assertEqual(set(people), {"Aino"})
        self.assertEqual(people["Aino"]["rounds"], 2)
        self.assertEqual(people["Aino"]["personas"], ["developer", "product_owner"])
        self.assertEqual(people["Aino"]["warranted_rate"], people["Aino"]["warranted"] / 2)
        self.assertEqual(people["Aino"]["warranted"], sum(1 for g in gates[2:] if g["verdict"] == "passed"))

    def test_FR_S1_AC_3_reading_the_factorys_own_canon_never_creates_it(self):
        self.compiled("Loans A")
        folder = self.factory.projects_dir / FACTORY_PID
        self.assertFalse(folder.exists())
        self.assertIsNone(factory_project(self.factory, create=False))
        self.assertEqual(apply_accepted(self.factory), [])
        self.assertEqual(propose(self.factory), [])                        # nothing recurs: no card to open
        self.assertEqual((immune_memory(self.factory), people_reliability(self.factory)), ([], {}))
        model_reliability(self.factory)
        self.assertFalse(folder.exists())                                   # every read left it uncreated
        self.assertNotIn(FACTORY_PID, [p.pid for p in self.factory.projects()])
        made = factory_project(self.factory)                                # a writer creates it on first use
        self.assertEqual(Canon(made).goal, "Make the factory stronger from what happens to its products.")
        self.assertEqual(factory_project(self.factory, create=False).pid, FACTORY_PID)


if __name__ == "__main__":
    unittest.main()
