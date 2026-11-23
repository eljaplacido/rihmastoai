"""Brief section E, the phase machine (FR-E1, FR-E2, FR-E3), measured against what the kernel does.

The kernel carries the owner's seven stages (`STAGES` in kernel/store.py), not the brief's nine
phases; contract/deferred/e.json records what is not built. These tests drive the real paved road
(kernel/pipeline.py), the real dispatch loop and the real gate (kernel/dispatch.py, kernel/gate.py)
with the shared fakes: a scripted model, scripted builder cells and a scripted verifier. Every
gate here runs the product's suite and fail-first in git, as it does in production.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, good_cell, lazy_cell, no_findings, script  # noqa: E402

from kernel.canon import PERSPECTIVES, Canon  # noqa: E402
from kernel.change import apply_change, submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build, build_task  # noqa: E402
from kernel.gate import signal_tests  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import STAGES  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."

# One requirement with one visible criterion: one task to build, so each build is one gate.
ONE_REQUIREMENT = {
    "title": "Equipment loans", "summary": "Track which team equipment is lent to whom.",
    "users": ["team members"],
    "requirements": [
        {"statement": "A team member can add an item with a name.", "sources": ["request"], "priority": "must",
         "acceptance": [{"given": "no items", "when": "POST /items with a name",
                         "then": "201 and the item has an id", "kind": "test"}]}],
    "out_of_scope": ["billing"],
}


def small_script(prompt: str, role: str) -> str:
    if "You turn a brief into a software specification" in prompt:
        return "```json\n" + json.dumps(ONE_REQUIREMENT) + "\n```"
    if "You write acceptance scenarios" in prompt:
        return '```json\n{"scenarios": []}\n```'
    return script(prompt, role)


def small_model() -> FakeModel:
    return FakeModel(small_script)


def agreeing_script(prompt: str, role: str) -> str:
    """Every perspective on the panel agrees with the answer the business proposed to Q-001."""
    if "perspective on a panel" not in prompt and "A panel of perspectives" in prompt:
        return "```json\n" + json.dumps({"opinions": [
            {"question": "Q-001", "perspective": p, "opinion": "the team lead approves"}
            for p in PERSPECTIVES if p != "business"]}) + "\n```"
    return small_script(prompt, role)


def objecting_verifier(prompt: str) -> str:
    return '```json\n' + json.dumps({"findings": [
        {"criterion": "R-1-AC-1", "in_scope": True, "severity": "high",
         "finding": "a name of spaces only is stored as an item", "repro": "POST /items {\"name\": \" \"}"}]}) + "\n```"


def unusable_verifier(prompt: str) -> str:
    return "I could not finish the review."


def untraced_cell(lane_path, prompt):
    """Builds the behaviour and a passing test, reports success, but no test names the criterion."""
    record = good_cell(lane_path, prompt)
    tests = Path(lane_path, "tests", "test_items.py")
    tests.write_text(tests.read_text(encoding="utf-8").replace("test_R_1_AC_1_", "test_"),
                     encoding="utf-8", newline="\n")
    return record | {"output": "done: R-1-AC-1 is met and tested"}


class PhaseMachineTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.lanes = Lanes(self.tmp / "lanes", size=1)

    def compiled(self, maturity: str):
        p = self.new(mode="assume", maturity=maturity)
        intake(p, IDEA, model=small_model(), requested_by="Aino")
        make_spec(p, model=small_model())
        compile_project(p)
        return p

    def main_log(self, p) -> list:
        return _git(p.path("repo.git"), "log", "--format=%H", "main").split()

    # -- FR-E1: the stages a project moves through ----------------------------------------------

    def test_FR_E1_AC_1_a_project_starts_at_stage_1_and_moves_forward_only_as_each_output_exists(self):
        self.assertEqual(list(STAGES), [1, 2, 3, 4, 5, 6, 7])
        p = self.new(mode="mixed", maturity="demo")
        self.assertEqual((p.meta["stage"], STAGES[p.meta["stage"]]), (1, "need and decision"))
        kw = dict(model=small_model(), max_steps=1)

        out = advance(p, **kw)                      # nothing has been asked yet: nothing moves
        self.assertEqual((out["state"], out["stage"], p.meta["stage"]), ("failed", 1, 1))

        intake(p, IDEA, model=small_model(), requested_by="Aino")
        self.assertEqual((p.meta["stage"], STAGES[2]), (2, "concept"))

        out = advance(p, **kw)                      # a blocking question is open: the step is blocked
        self.assertEqual((out["state"], out["stage"], p.meta["stage"]), ("waiting", 2, 2))
        self.assertFalse(p.path("spec.json").exists())

        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        out = advance(p, **kw)
        self.assertEqual((out["state"], out["history"], p.meta["stage"]), ("progress", ["spec"], 4))
        self.assertTrue(p.path("spec.json").exists())

        out = advance(p, **kw)
        self.assertEqual((out["state"], out["history"], p.meta["stage"]), ("progress", ["compile"], 5))
        self.assertEqual(p.meta["contract_revision"], p.read("contract.json")["revision"])

        # Each move is on the record, in order, beside the output that caused it.
        kinds = [r["event"]["kind"] for r in p.ledger().of_kind("intake_done", "spec_written", "contract_compiled")]
        self.assertEqual(kinds, ["intake_done", "spec_written", "contract_compiled"])

    def test_FR_E1_AC_2_once_every_task_merged_a_pilot_moves_to_user_validation_and_a_demo_stays_in_build(self):
        after = {}
        for maturity in ("pilot", "demo"):
            p = self.compiled(maturity)
            self.assertEqual((p.meta["stage"], bool(p.meta.get("built"))), (5, False))
            out = build(p, lanes=self.lanes, cell_runner=generic_cell, verifier_runner=no_findings)
            self.assertTrue(out["all_merged"], out)
            after[maturity] = (p.meta["stage"], p.meta["built"])
        self.assertEqual(after, {"pilot": (6, True), "demo": (5, True)})
        self.assertEqual(STAGES[6], "user validation")

    def test_FR_E1_AC_2_while_a_task_is_escalated_the_project_does_not_leave_build(self):
        p = self.compiled("pilot")
        out = build(p, lanes=self.lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=0)
        self.assertEqual((out["results"], out["all_merged"]), ({"T-001": "escalated"}, False))
        self.assertEqual((p.meta["stage"], bool(p.meta.get("built"))), (5, False))

    def test_FR_E1_AC_3_a_change_returns_a_built_project_to_build_and_it_moves_on_again_once_rebuilt(self):
        p = self.compiled("pilot")
        build(p, lanes=self.lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertEqual((p.meta["stage"], p.meta["built"]), (6, True))
        before = p.meta["contract_revision"]

        card = submit(p, persona="end_user", person="Tester", text="Adding an item with an empty name crashes with 500")
        self.assertEqual(triage(p, card["id"], model=small_model())["class"], "defect")
        apply_change(p, card["id"], model=small_model())
        self.assertEqual((p.meta["stage"], p.meta["built"]), (5, False))
        self.assertNotEqual(p.meta["contract_revision"], before)
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "pending")

        out = build(p, lanes=self.lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertTrue(out["all_merged"], out)
        self.assertEqual((p.meta["stage"], p.meta["built"]), (6, True))

    # -- FR-E2: distinct kinds of evidence, never a count of agreeing agents ---------------------

    def test_FR_E2_AC_1_one_failing_kind_of_evidence_outweighs_three_passing_ones(self):
        p = self.compiled("demo")
        main_before = self.main_log(p)
        out = build_task(p, "T-001", lanes=self.lanes, cell_runner=good_cell, verifier_runner=objecting_verifier,
                         max_rounds=0)
        gate = out["rounds"][-1]["gate"]
        self.assertEqual({s["name"]: s["verdict"] for s in gate["signals"]},
                         {"tests": "passed", "trace": "passed", "fail_first": "passed", "verifier": "failed"})
        self.assertEqual((gate["verdict"], gate["warranted"], out["status"]), ("failed", False, "escalated"))
        self.assertEqual(p.ledger().of_kind("merged"), [])
        self.assertEqual(self.main_log(p), main_before)

    def test_FR_E2_AC_1_a_builder_and_a_verifier_that_agree_do_not_merge_a_change_no_test_names(self):
        p = self.compiled("demo")
        main_before = self.main_log(p)
        out = build_task(p, "T-001", lanes=self.lanes, cell_runner=untraced_cell, verifier_runner=no_findings,
                         max_rounds=0)
        last = out["rounds"][-1]
        signals = {s["name"]: s["verdict"] for s in last["gate"]["signals"]}
        self.assertEqual(last["cell"]["stop_reason"], "answered")      # the builder says it is done
        self.assertEqual((signals["tests"], signals["verifier"]), ("passed", "passed"))  # and the reviewer agrees
        self.assertEqual(signals["trace"], "failed")                    # the kernel's own evidence does not
        self.assertEqual((last["gate"]["verdict"], out["status"]), ("failed", "escalated"))
        self.assertEqual(p.ledger().of_kind("merged"), [])
        self.assertEqual(self.main_log(p), main_before)

    def test_FR_E2_AC_2_every_perspective_agreeing_does_not_answer_a_blocking_question(self):
        p = self.new(mode="mixed", maturity="demo")
        agreeing = FakeModel(agreeing_script)
        intake(p, IDEA, model=agreeing, requested_by="Aino")
        q = Canon(p).question("Q-001")
        self.assertTrue(q["blocking"])
        self.assertEqual(set(q["opinions"]), set(PERSPECTIVES))                   # every perspective spoke
        self.assertEqual(set(q["opinions"].values()), {"the team lead approves"})  # and all agree

        for _ in range(2):                              # asking again does not count the agreement up
            out = advance(p, model=agreeing, max_steps=1)
            self.assertEqual((out["state"], out["stage"], out["waiting_on"]), ("waiting", 2, [q["card"]]))
        self.assertFalse(p.path("spec.json").exists())
        self.assertEqual(Canon(p).question("Q-001")["status"], "open")

        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        out = advance(p, model=agreeing, max_steps=1)
        self.assertEqual((out["state"], out["history"], p.meta["stage"]), ("progress", ["spec"], 4))

    # -- FR-E3: insufficient evidence is a valid outcome ----------------------------------------

    def test_FR_E3_AC_1_a_gate_whose_verifier_gives_no_usable_answer_is_not_measured_and_never_merges(self):
        p = self.compiled("demo")
        main_before = self.main_log(p)
        out = build_task(p, "T-001", lanes=self.lanes, cell_runner=good_cell, verifier_runner=unusable_verifier,
                         max_rounds=0)
        gate = out["rounds"][-1]["gate"]
        self.assertEqual({s["name"]: s["verdict"] for s in gate["signals"]},
                         {"tests": "passed", "trace": "passed", "fail_first": "passed", "verifier": "not measured"})
        self.assertEqual((gate["verdict"], gate["warranted"]), ("not measured", False))
        logged = [r["event"]["payload"] for r in p.ledger().of_kind("gate")]
        self.assertEqual([(g["verdict"], g["signals"]["verifier"]) for g in logged],
                         [("not measured", "not measured")])
        self.assertEqual(p.ledger().of_kind("merged"), [])
        self.assertEqual(self.main_log(p), main_before)

    def test_FR_E3_AC_1_a_suite_that_runs_no_tests_is_not_measured_not_passed_or_failed(self):
        with tempfile.TemporaryDirectory(prefix="gf-empty-suite-") as tmp:
            Path(tmp, "tests").mkdir()
            Path(tmp, "tests", "__init__.py").write_text("", encoding="utf-8")
            sig = signal_tests(Path(tmp))
        self.assertEqual((sig.name, sig.verdict, sig.detail), ("tests", "not measured", "no tests ran"))
        self.assertEqual(sig.native["ran"], 0)
        self.assertNotEqual(sig.native["exit"], 0)  # unittest exits non-zero, and that is not read as failed

    def test_FR_E3_AC_2_not_measured_work_goes_back_for_more_rounds_then_to_a_person_who_can_send_it_again(self):
        p = self.new(mode="assume", maturity="demo")
        intake(p, IDEA, model=small_model(), requested_by="Aino")
        kw = dict(model=small_model(), lanes=self.lanes, cell_runner=generic_cell, deliver_kwargs={})

        out = advance(p, verifier_runner=unusable_verifier, **kw)
        self.assertEqual((out["state"], out["stage"]), ("waiting", 5), out)
        card = Canon(p).get_card(out["waiting_on"][0])
        self.assertEqual((card["kind"], card["blocking"], card["refs"]["task"]), ("escalation", True, "T-001"))
        rounds = p.read("tasks.json")["T-001"]["rounds"]
        self.assertEqual([r["gate"]["verdict"] for r in rounds], ["not measured"] * 3)
        self.assertEqual(p.ledger().of_kind("merged"), [])
        self.assertFalse(p.meta.get("built"))

        Canon(p).decide(card["id"], "retry", person="Dev", persona="developer")
        advance(p, verifier_runner=no_findings, **kw)
        state = p.read("tasks.json")["T-001"]
        self.assertEqual((state["status"], state["rounds"][-1]["gate"]["verdict"]), ("merged", "passed"))
        self.assertTrue(p.meta["built"])


if __name__ == "__main__":
    unittest.main()
