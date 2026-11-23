"""Brief section A, intake and contract: FR-A2 and FR-A4, exercised through the kernel (task V-60).

- FR-A2: a vague idea becomes the same contract through classification and guided questions,
  and the answers are signed, so a requirement names who confirmed it. The refusal of a brief
  too ambiguous to classify is not built; contract/deferred/a.json records it.
- FR-A4: a change request becomes a contract amendment, and the factory reopens exactly the
  tasks that trace to the requirements it touched.
- FR-A1 (a closed intake contract: a manifest with hashes, roles and record counts) is not
  built; contract/deferred/a.json says what it would take. No test here claims it.
"""

import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, model, no_findings, script  # noqa: E402

from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.change import apply_change, submit, triage  # noqa: E402
from kernel.compile import compile_project, contract_check  # noqa: E402
from kernel.dispatch import build, ready_tasks  # noqa: E402
from kernel.insight import change_impact  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


def _fenced(obj) -> str:
    return "```json\n" + json.dumps(obj) + "\n```"


# -- a product wide enough for the brief's own example: an amendment touching 14 requirements -----

def _feature(n: int) -> dict:
    return {"statement": f"Feature {n} answers on its own path.", "sources": ["request"], "priority": "must",
            "acceptance": [{"given": "-", "when": f"GET /f{n}", "then": f"200 with feature {n}", "kind": "test"}]}


WIDE_SPEC = {"title": "Wide", "summary": "Twenty small features.", "users": ["staff"],
             "interface": [{"method": "GET", "path": f"/f{n}", "purpose": f"feature {n}"} for n in range(1, 21)],
             "requirements": [_feature(n) for n in range(1, 9)]}       # production maturity takes eight at once
TOUCHED = ["R-1", "R-2", "R-3", "R-5", "R-6", "R-8", "R-9", "R-10", "R-12", "R-13", "R-15", "R-17", "R-18", "R-20"]
UNTOUCHED = ["R-4", "R-7", "R-11", "R-14", "R-16", "R-19"]
GROW = "We also want twelve more features"
RESHAPE = "Every touched feature should answer in JSON"


def wide_script(prompt: str, role: str) -> str:
    if "You turn a brief into a software specification" in prompt:
        return _fenced(WIDE_SPEC)
    if "Classify a piece of feedback" in prompt:
        if GROW in prompt:
            return _fenced({"parts": [{"class": "new_requirement", "requirements": [], "text": GROW,
                                       "summary": "twelve more features"}]})
        return _fenced({"parts": [{"class": "change_request", "requirements": TOUCHED, "text": RESHAPE,
                                   "summary": "answer in JSON"}]})
    if "Amend a software specification" in prompt:
        if GROW in prompt:
            return _fenced({"modify": [], "add": [_feature(n) for n in range(9, 21)], "withdraw": []})
        return _fenced({"modify": [{"id": rid, "statement": f"{rid} answers in JSON.",
                                    "acceptance": [{"given": "-", "when": "GET", "then": "200 with a JSON body",
                                                    "kind": "test"}]} for rid in TOUCHED],
                        "add": [], "withdraw": []})
    return script(prompt, role)


class VagueIdeaToContractTest(FactoryTestCase):
    """FR-A2: a vague explanation becomes the contract through classification and guided questions."""

    def test_FR_A2_AC_1_a_vague_idea_is_classified_by_rule_and_turned_into_guided_questions(self):
        rooms = self.new(mode="mixed", title="Rooms")
        out = intake(rooms, "We need a booking page where staff reserve the meeting rooms.", model=model(),
                     requested_by="Aino")
        orders = self.new(mode="mixed", title="Orders")
        intake(orders, "Orders from our webshop webhook should sync into the ERP.", model=model(), requested_by="Aino")

        # classified by rule: the kind of source, and a work profile with the words it rests on
        self.assertEqual((out["kind"], rooms.read("source.json")["kind"]), ("idea", "idea"))
        self.assertEqual(rooms.meta["profile"], "web_service")
        self.assertEqual(orders.meta["profile"], "integration")
        chosen = [r["event"]["payload"] for r in rooms.ledger().of_kind("profile_chosen")]
        self.assertEqual(chosen, [{"profile": "web_service", "basis": {"by": "rule", "keywords": ["booking", "page"]}}])
        chosen = [r["event"]["payload"]["basis"] for r in orders.ledger().of_kind("profile_chosen")]
        self.assertEqual(chosen, [{"by": "rule", "keywords": ["erp", "sync", "webhook"]}])

        # guided: questions with options, the panel's proposal first; the blocking one is put to a person
        canon = Canon(rooms)
        q1 = canon.question("Q-001")
        self.assertTrue(q1["blocking"])
        self.assertEqual(q1["options"][0], "the team lead approves")
        self.assertTrue(q1["card"])
        self.assertEqual(out["asked"], [q1["card"]])                 # only the blocking question became a card
        self.assertEqual(Canon(rooms).get_card(q1["card"])["refs"]["question"], "Q-001")

        # the run waits on that person instead of writing a spec around the gap
        run = advance(rooms, model=model())
        self.assertEqual((run["state"], run["stage"], run["waiting_on"]), ("waiting", 2, [q1["card"]]))
        self.assertFalse(rooms.path("spec.json").exists())
        self.assertFalse(rooms.path("contract.json").exists())

    def test_FR_A2_AC_2_signed_answers_reach_the_contract_and_name_who_confirmed_each_requirement(self):
        p = self.new(mode="mixed")
        intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        card = canon.question("Q-001")["card"]
        with self.assertRaises(DecisionRefused):                     # an answer is a person's signed act
            canon.answer("Q-001", "anyone may approve", person="factory", persona="business_owner")
        self.assertEqual(Canon(p).question("Q-001")["status"], "open")
        canon.answer("Q-001", "the team lead approves", person="Pekka", persona="business_owner")
        signed = [(d["person"], d["persona"], d["verdict"]) for d in Canon(p).decisions() if d["card"] == card]
        self.assertEqual(signed, [("Pekka", "business_owner", "answer")])

        make_spec(p, model=model())
        compile_project(p)
        contract = p.read("contract.json")
        report, facts = contract_check().check(contract)
        self.assertEqual(report.violations, [])                      # the same checker the factory's own contract meets
        self.assertEqual(facts["revision"], contract["revision"])
        reqs = {r["id"]: r for r in contract["requirements"]}
        self.assertEqual((reqs["R-2"]["provenance"], reqs["R-2"]["decided_by"], reqs["R-2"]["decided_on"]),
                         ("customer-confirmed", "Pekka", "2026-11-22"))   # rests on Pekka's answer to Q-001
        self.assertEqual((reqs["R-1"]["provenance"], reqs["R-1"]["decided_by"]), ("customer-endorsed", "Aino"))
        self.assertEqual(reqs["R-3"]["provenance"], "assumption")    # rests on an assumed question: nobody signed it
        self.assertNotIn("decided_by", reqs["R-3"])

    def test_FR_A2_AC_3_an_empty_request_is_refused_with_its_reason_and_intake_writes_nothing(self):
        empty_folder = self.tmp / "nothing-here"
        empty_folder.mkdir()
        for source in ("   \n  ", str(empty_folder)):
            p = self.new(mode="mixed", title=f"Empty {len(source)}")
            records = len(p.ledger().records())
            m = model()
            with self.assertRaises(ValueError) as ctx:
                intake(p, source, model=m, requested_by="Aino")
            self.assertIn("the request is empty", str(ctx.exception))
            self.assertEqual(m.calls, [])                            # no panel was asked
            self.assertFalse(p.path("source.json").exists())
            self.assertEqual(Canon(p).questions(), [])
            self.assertEqual(len(p.ledger().records()), records)
            self.assertNotIn("profile", p.meta)
            self.assertEqual(p.meta["stage"], 1)


class AmendmentReopensTest(FactoryTestCase):
    """FR-A4: a change request becomes a contract amendment that reopens exactly its tasks."""

    def compiled(self, *, maturity="demo", script_=script):
        p = self.new(mode="assume", maturity=maturity)
        m = FakeModel(script_)
        intake(p, IDEA, model=m, requested_by="Aino")
        make_spec(p, model=m)
        compile_project(p)
        return p, m

    def accepted(self, p, m, text: str) -> str:
        card = submit(p, persona="product_owner", person="Pekka", text=text)
        triage(p, card["id"], model=m)
        Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner")
        return card["id"]

    def test_FR_A4_AC_1_an_amendment_touching_14_requirements_reports_and_reopens_only_their_tasks(self):
        p, m = self.compiled(maturity="production", script_=wide_script)
        apply_change(p, self.accepted(p, m, GROW), model=m)          # the product grows to twenty requirements
        contract = p.read("contract.json")
        self.assertEqual(len(contract["requirements"]), 20)
        self.assertEqual(len(contract["tasks"]), 20)
        # every task merged, as the dispatcher records a merged task (AC-2 builds a product for real)
        p.write("tasks.json", {t["id"]: {"status": "merged", "revision": f"rev-{t['id']}", "rounds": []}
                               for t in contract["tasks"]})
        before = contract["revision"]

        card = submit(p, persona="product_owner", person="Pekka", text=RESHAPE)
        triage(p, card["id"], model=m)
        expected = ["T-001", "T-002", "T-003", "T-005", "T-006", "T-008", "T-009", "T-010", "T-012", "T-013",
                    "T-015", "T-017", "T-018", "T-020"]
        impact = change_impact(p, card["id"])                        # reported before anyone decides
        self.assertEqual(impact["requirements"], sorted(TOUCHED))
        self.assertEqual(impact["tasks_reopened"], expected)
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "merged")   # shown, not done

        Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner")
        out = apply_change(p, card["id"], model=m)
        self.assertEqual(sorted(out["changed"]), sorted(TOUCHED))
        amended = p.read("contract.json")
        self.assertNotEqual(amended["revision"], before)
        self.assertEqual(contract_check().check(amended)[0].violations, [])

        state = p.read("tasks.json")
        reopened = sorted(t for t, s in state.items() if s["status"] == "pending")
        self.assertEqual(reopened, expected)                         # exactly what the impact reported
        for n, tid in zip([int(r.split("-")[1]) for r in TOUCHED], expected):
            self.assertEqual((tid, state[tid]["reopened_by"]), (f"T-{n:03d}", [f"R-{n}"]))
        for rid in UNTOUCHED:
            tid = f"T-{int(rid.split('-')[1]):03d}"
            self.assertEqual((state[tid]["status"], state[tid]["revision"]), ("merged", f"rev-{tid}"))
        self.assertFalse(p.meta["built"])

    def test_FR_A4_AC_2_after_an_amendment_the_build_rebuilds_only_the_reopened_task(self):
        p, m = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        first = build(p, lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertTrue(first["all_merged"])
        self.assertEqual(sorted(first["results"]), ["T-001", "T-002", "T-003", "T-004"])
        merged_at = {t: s["revision"] for t, s in p.read("tasks.json").items()}

        out = apply_change(p, self.accepted(p, m, "The approver should be optional"), model=m)
        self.assertEqual(out["changed"], ["R-2"])
        self.assertEqual(ready_tasks(p), ["T-002"])

        second = build(p, lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertEqual(second["results"], {"T-002": "merged"})     # nothing else was built again
        self.assertTrue(second["all_merged"])
        after = p.read("tasks.json")
        for tid in ("T-001", "T-003", "T-004"):
            self.assertEqual(after[tid]["revision"], merged_at[tid])
        cells = Counter(r["event"]["payload"]["task"] for r in p.ledger().of_kind("cell_ran"))
        self.assertEqual(cells, Counter({"T-001": 1, "T-002": 2, "T-003": 1, "T-004": 1}))

    def test_FR_A4_AC_3_the_amendment_is_a_new_contract_revision_on_the_products_main(self):
        p, m = self.compiled()
        before = p.read("contract.json")["revision"]
        old_r2 = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        out = apply_change(p, self.accepted(p, m, "The approver should be optional"), model=m)

        revision = p.read("contract.json")["revision"]
        self.assertEqual(out["contract"], revision)
        self.assertNotEqual(revision, before)
        on_main = subprocess.run(["git", "show", "main:contract.json"], cwd=p.path("repo.git"), capture_output=True,
                                 text=True, encoding="utf-8", check=True).stdout
        self.assertEqual(json.loads(on_main)["revision"], revision)  # the product's main carries the amendment
        kept = next(r for r in p.read("spec.v1.json")["requirements"] if r["id"] == "R-2")
        self.assertEqual(kept["statement"], old_r2["statement"])     # the spec it amended is kept
        new_r2 = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        self.assertEqual(new_r2["statement"], "A loan records the approver if given.")
        applied = [r["event"]["payload"] for r in p.ledger().of_kind("change_applied")]
        self.assertEqual([(a["changed"], a["contract"]) for a in applied], [(["R-2"], revision)])


if __name__ == "__main__":
    unittest.main()
