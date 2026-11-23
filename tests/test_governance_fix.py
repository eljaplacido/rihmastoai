"""Governance fixes (V-86): what a person decided holds, wherever a change, a build or a delivery
starts.

- A change a person rejected or deferred is never applied, and a submitter's class hint never skips
  the business decision, a developer's included (FR-P4-AC-1); a developer's product-defect ruling
  is still carried out as a defect, and lends no other label its weight (FR-H3-AC-2).
- `rihma build`, `rihma deliver` and the pipeline's rulings ask the autonomy cap first (FR-K4-AC-1).
- A validated need is text, never a path to read (FR-P1-AC-1); a paused project runs nothing (FR-J3-AC-1).
- A user validation decided fix or change reaches the change loop (FR-R3-AC-2).
- Withdrawing a requirement works and its holdouts (and a restated criterion's) never run again, a
  refused compile changes nothing, and adding a requirement renumbers no task, a factory default
  check's included (FR-A4-AC-1, FR-A4-AC-3).
- `rihma tick` carries out decided concepts (FR-V2-AC-2); reading a cap or the observations never
  creates the factory's canon (FR-S1-AC-3); the spec records what the analyst's draft lost (FR-P3-AC-2).
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import SPEC, FactoryTestCase, model, script  # noqa: E402

from kernel.autonomy import AutonomyCapped, cap_of, describe, factory_cap, set_cap  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.change import apply_change, ruling_defect_text, submit, triage  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import CompileError, author_holdouts, compile_project, contract_check  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.learn import FACTORY_PID, factory_project  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.observations import observations  # noqa: E402
from kernel.operate import run_holdouts  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.rulings import apply_rulings, open_ruling  # noqa: E402
from kernel.safestop import request_pause, resume  # noqa: E402
from kernel.signals import receive  # noqa: E402
from kernel.signals import triage as triage_signal  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import Project, read_json, write_json  # noqa: E402
from mcp.server import RihmaMCP  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
REJECTED_IDEA = "The loan should not need an approver at all, make it optional instead"
HELD = "HELD-ONLY-IN-THE-CUSTODY-7f3a"


def amending(answer: dict) -> FakeModel:
    """The scripted analyst, whose amendment for an accepted change is ``answer``."""
    def run(prompt: str, role: str) -> str:
        if "Amend a software specification" in prompt:
            return "```json\n" + json.dumps(answer) + "\n```"
        return script(prompt, role)
    return FakeModel(run)


class GovernanceCase(FactoryTestCase):
    def compiled(self, *, maturity: str = "demo") -> Project:
        p = self.new(mode="assume", maturity=maturity)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def accepted(self, p: Project, m: FakeModel, text: str) -> str:
        card = submit(p, persona="product_owner", person="Pekka", text=text)
        triage(p, card["id"], model=m)
        Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner")
        return str(card["id"])

    def snapshot(self, p: Project) -> dict:
        """What a change may alter: the spec, the contract, the tasks, the lessons, the approvals."""
        meta = p.meta
        return {"files": {n: p.read(n) for n in ("spec.json", "contract.json", "checkplan.json", "tasks.json",
                                                 "lessons.json")},
                "meta": {k: meta.get(k) for k in ("spec_version", "contract_revision", "built", "stage")},
                "decisions": [(d["id"], d["stale"]) for d in Canon(p).decisions()],
                "cards": [(c["id"], c["state"]) for c in Canon(p).cards(state=None)]}

    def built(self, p: Project) -> None:
        """Every task merged, as the dispatcher records it."""
        p.write("tasks.json", {t["id"]: {"status": "merged", "revision": f"rev-{t['id']}", "rounds": []}
                               for t in p.read("contract.json")["tasks"]})
        p.update_meta(built=True)

    def cli(self, *argv: str) -> Any:
        out = io.StringIO()
        with mock.patch("kernel.cli._model", model), contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), *argv])
        self.assertEqual(code, 0, argv)
        return json.loads(out.getvalue())


# -- FR-P4-AC-1: a person's decision on a change holds ---------------------------------------------------

class ChangeDecisionTest(GovernanceCase):
    def test_FR_P4_AC_1_a_change_a_person_rejected_or_deferred_is_never_applied_whatever_its_class(self):
        p = self.compiled()
        canon = Canon(p)
        defect = submit(p, persona="end_user", person="Tiina", text="Adding an item with an empty name crashes with 500")
        self.assertEqual(triage(p, defect["id"], model=model())["class"], "defect")
        canon.decide(defect["id"], "reject", person="Aino", persona="business_owner", reason="works as designed")
        infra = submit(p, persona="it", person="Ilkka", text="All services must use TLS 1.3 from January")
        self.assertEqual(triage(p, infra["id"])["class"], "infra_change")
        canon.decide(infra["id"], "defer", person="Aino", persona="business_owner", reason="next year")
        before = self.snapshot(p)
        for card, verdict in ((defect, "reject"), (infra, "defer")):
            with self.assertRaises(PermissionError) as refused:
                apply_change(p, card["id"], model=model())
            self.assertIn(f"decided {verdict} by Aino", str(refused.exception))
        self.assertEqual(self.snapshot(p), before)                      # no criterion, no reopened task
        self.assertEqual(canon.cards(state=None, kind="road"), [])      # nothing was routed to IT either
        self.assertEqual(p.ledger().of_kind("change_applied", "change_routed"), [])

    def test_FR_P4_AC_1_a_submitters_hint_never_skips_the_business_decision(self):
        p = self.compiled()
        for m in (None, model()):                                       # by the rules, and with the analyst
            card = submit(p, persona="end_user", person="Tiina", text=REJECTED_IDEA, kind_hint="defect")
            tri = triage(p, card["id"], model=m)
            self.assertEqual((tri["class"], tri.get("hint_over"), tri["needs_decision"]),
                             ("defect", "change_request", True))
            before = self.snapshot(p)
            with self.assertRaises(PermissionError):
                apply_change(p, card["id"], model=model())
            self.assertEqual(self.snapshot(p), before)
        Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner", reason="yes, a defect")
        self.assertEqual(apply_change(p, card["id"], model=model())["class"], "defect")   # accepted, it goes on
        # a hint the rules read the same way stands; so does one from a persona who decides change cards
        same = submit(p, persona="end_user", person="Tiina", text="Adding an item with an empty name crashes",
                      kind_hint="defect")
        self.assertFalse(triage(p, same["id"])["needs_decision"])
        owned = submit(p, persona="product_owner", person="Pekka", text=REJECTED_IDEA, kind_hint="defect")
        self.assertFalse(triage(p, owned["id"])["needs_decision"])
        raised = submit(p, persona="end_user", person="Tiina", text="It crashes", kind_hint="new_requirement")
        self.assertTrue(triage(p, raised["id"])["needs_decision"])     # a hint may add a decision

    def test_FR_P4_AC_1_a_developers_defect_label_on_a_change_request_still_needs_the_business_decision(self):
        p = self.compiled()
        for m in (None, model()):                                       # the cockpit's rules, and the analyst
            card = submit(p, persona="developer", person="Dev", text=REJECTED_IDEA, kind_hint="defect")
            tri = triage(p, card["id"], model=m)
            self.assertEqual((tri["class"], tri.get("hint_over"), tri["needs_decision"]),
                             ("defect", "change_request", True))
            before = self.snapshot(p)
            with self.assertRaises(PermissionError) as refused:
                apply_change(p, card["id"], model=model())
            self.assertIn("needs a business decision", str(refused.exception))
            self.assertEqual(self.snapshot(p), before)                  # no criterion, no reopened task
        with self.assertRaises(DecisionRefused):                        # nor may the developer accept it
            Canon(p).decide(card["id"], "accept", person="Dev", persona="developer")
        self.assertFalse(any("approver at all" in c["then"] for r in p.read("spec.json")["requirements"]
                             for c in r["acceptance"]))

    def test_FR_H3_AC_2_a_developers_product_defect_ruling_is_carried_out_and_lends_no_other_label_its_weight(self):
        p = self.compiled()
        canon = Canon(p)
        failing = [{"criterion": "R-1-AC-2", "failed_step": 2, "request": {"method": "GET", "path": "/items"},
                    "expected": "drill", "observed": "[]"}]
        ruling = open_ruling(p, 1, {"revision": "0" * 40, "steps": [
            {"step": "holdouts:demo", "outcome": "failed", "native": {"failing": failing}}]})
        other = canon.card("holdout_ruling", "Release 2: 1 holdout(s) failed. Product or scenario?", body="- R-4-AC-2",
                           refs={"release": 2, "criteria": ["R-4-AC-2"], "requirements": ["R-4"]}, blocking=True)
        canon.decide(other["id"], "scenario_defect", person="Dev", persona="developer", reason="the probe is wrong")
        canon.decide(ruling["id"], "product_defect", person="Dev", persona="developer", reason="the list is empty")
        words = ruling_defect_text(canon.get_card(ruling["id"]))

        def needs_decision(text: str, person: str = "Dev", persona: str = "developer") -> bool:
            card = submit(p, persona=persona, person=person, text=text, kind_hint="defect")
            return bool(triage(p, card["id"], model=model())["needs_decision"])

        # the ruling stands behind its own defect only: not other words, nor another person or persona,
        # and a scenario-defect ruling stands behind none
        for text, person, persona in ((REJECTED_IDEA, "Dev", "developer"),
                                      (f"{words} Make the approver optional", "Dev", "developer"),
                                      (words, "Mia", "developer"), (words, "Dev", "end_user"),
                                      (ruling_defect_text(canon.get_card(other["id"])), "Dev", "developer")):
            self.assertTrue(needs_decision(text, person, persona), (text, person, persona))
        done = apply_rulings(p, model=model())                         # no business decision waits on it
        defect = next(d for d in done if d["verdict"] == "product_defect")
        self.assertEqual((defect["card"], defect["class"], defect["changed"]), (ruling["id"], "defect", ["R-1"]))
        self.assertEqual(Canon(p).get_card(defect["change"])["payload"]["person"], "Dev")
        r1 = p.read("spec.json")["requirements"][0]
        self.assertIn("an end-to-end check the factory holds out failed against release 1", r1["acceptance"][-1]["then"])
        self.assertTrue(needs_decision(words))                         # carried out: its words are only words now


# -- FR-K4-AC-1: every path that builds or delivers asks the cap --------------------------------------------

class CapTest(GovernanceCase):
    def test_FR_K4_AC_1_rihma_build_and_deliver_ask_the_cap_and_deliver_refuses_a_paused_project(self):
        p = self.compiled(maturity="pilot")
        home = str(self.factory.home)
        with mock.patch("kernel.dispatch.build", return_value={"results": {}}) as built, \
                mock.patch("kernel.deliver.deliver", return_value={"state": "done"}) as delivered, \
                contextlib.redirect_stdout(io.StringIO()):
            set_cap(self.factory, 2, person="Aino", persona="business_owner", reason="answers and proposals only")
            with self.assertRaises(AutonomyCapped) as capped:
                main(["--home", home, "build", p.pid])
            self.assertIn("building needs autonomy level 3", str(capped.exception))
            set_cap(self.factory, 3, person="Aino", persona="business_owner", reason="sandbox only")
            with self.assertRaises(AutonomyCapped) as capped:
                main(["--home", home, "deliver", p.pid])
            self.assertIn("delivering to staging needs autonomy level 4", str(capped.exception))
            set_cap(self.factory, 4, person="Aino", persona="business_owner", reason="pilot approved")
            request_pause(p, person="Olli", persona="operations", reason="the GPU box is being patched")
            with self.assertRaises(PermissionError):
                main(["--home", home, "deliver", p.pid])
            built.assert_not_called()
            delivered.assert_not_called()
            resume(p, person="Olli", persona="operations")
            self.assertEqual(main(["--home", home, "deliver", p.pid]), 0)
            self.assertEqual(main(["--home", home, "build", p.pid]), 0)
        self.assertEqual((built.call_count, delivered.call_count), (1, 1))

    def test_FR_K4_AC_1_below_level_3_the_pipeline_carries_out_no_ruling(self):
        p = self.compiled()
        self.built(p)
        canon = Canon(p)
        failing = [{"criterion": "R-1-AC-2", "failed_step": 2, "request": {"method": "GET", "path": "/items"},
                    "expected": "drill", "observed": "[]"}]
        ruling = canon.card("holdout_ruling", "Release 1: 1 holdout(s) failed. Product or scenario?",
                            body="- R-1-AC-2: step 2 GET /items", payload={"failing": failing, "revision": "r1"},
                            refs={"release": 1, "criteria": ["R-1-AC-2"], "requirements": ["R-1"]}, blocking=True)
        canon.decide(ruling["id"], "product_defect", person="Dev", persona="developer", reason="the list is empty")
        set_cap(self.factory, 2, person="Aino", persona="business_owner", reason="answers and proposals only")
        before = self.snapshot(p)
        out = advance(p, model=model())
        self.assertEqual(out["state"], "capped", out)
        self.assertIn("autonomy level 3", out["why"])
        self.assertEqual(self.snapshot(p), before)                     # no change card, no amended spec
        self.assertIsNone(p.read("rulings_applied.json"))


# -- FR-P1-AC-1 and FR-J3-AC-1: a need is text; a paused project runs nothing ----------------------------------

class NeedAndPauseTest(GovernanceCase):
    def test_FR_P1_AC_1_a_validated_need_that_names_a_file_is_read_as_text_never_as_the_file(self):
        secret = self.tmp / "outside" / "holdout.json"
        secret.parent.mkdir()
        secret.write_text("SECRET-SCENARIO-TEXT\n", encoding="utf-8")
        p = self.new()
        p.write("need.json", {"text": str(secret), "requested_by": "Aino", "signal": "S-001", "concept": "C-0001"})
        m = model()
        out = advance(p, model=m)
        self.assertEqual(out["state"], "waiting", out)                 # on the panel's blocking question
        source = p.read("source.json")
        self.assertEqual((source["kind"], source["text"]), ("idea", str(secret)))
        self.assertTrue(m.calls)
        self.assertFalse(any("SECRET-SCENARIO-TEXT" in prompt for _, prompt in m.calls))
        # a request file's contents are its text too: `rihma intake --source-file` reads nothing they name
        request = self.tmp / "request.md"
        request.write_text(str(secret), encoding="utf-8")
        other = self.new(title="Second loans")
        self.cli("intake", other.pid, "--source-file", str(request), "--requested-by", "Aino")
        self.assertEqual((other.read("source.json")["kind"], other.read("source.json")["text"]), ("idea", str(secret)))

    def test_FR_J3_AC_1_a_paused_project_runs_nothing_not_even_its_intake_or_its_spec(self):
        waiting_need = self.new(mode="assume")
        waiting_need.write("need.json", {"text": IDEA, "requested_by": "Aino"})
        intaken = self.new(mode="assume", title="Second loans")
        intake(intaken, IDEA, model=model(), requested_by="Aino")
        for p in (waiting_need, intaken):
            request_pause(p, person="Aino", persona="business_owner", reason="budget review: stop all work")
            silent = FakeModel({})                                     # any call would be an apparatus failure
            out = advance(p, model=silent)
            self.assertEqual((out["state"], out["why"]), ("paused", "paused by Aino: budget review: stop all work"))
            self.assertEqual(silent.calls, [])
            self.assertFalse(p.path("spec.json").exists())
            self.assertFalse(p.path("contract.json").exists())
        self.assertFalse(waiting_need.path("source.json").exists())


# -- FR-R3-AC-2: a validation decided fix or change reaches the change loop -------------------------------------

class HandoffTest(GovernanceCase):
    def validated(self, verdict: str, person: str, persona: str, reason: str) -> tuple:
        """A pilot whose release 1 failed at user validation, decided ``verdict``."""
        p = self.compiled(maturity="pilot")
        self.built(p)
        canon = Canon(p)
        card = canon.card("validation", "Validate release 1 on staging", refs={"release": 1}, blocking=True)
        canon.decide(card["id"], verdict, person=person, persona=persona, reason=reason)
        handoff = {"to": "change", "card": card["id"], "verdict": verdict}
        write_json(p.path("releases", "1.json"), {"release": 1, "state": "failed", "failed_step": "user_validation",
                                                  "handoff": handoff, "waiting_on": card["id"], "steps": []})
        failed = {"state": "failed", "release": 1, "env": "staging", "revision": "r1", "steps": [],
                  "failed_step": "user_validation", "reason": f"validation card {card['id']}: {verdict}",
                  "handoff": handoff, "waiting_on": card["id"]}
        return p, card, failed

    def run_once(self, p: Project, failed: dict, m: FakeModel | None = None) -> dict:
        with mock.patch("kernel.deliver.deliver", return_value=failed):
            return advance(p, model=m or model(), max_steps=1)

    def test_FR_R3_AC_2_a_fix_becomes_a_defect_in_the_deciders_name_and_is_carried_out(self):
        p, validation, failed = self.validated("fix", "Aino", "business_owner", "the return button does nothing")
        out = self.run_once(p, failed)
        [change] = Canon(p).cards(state=None, kind="change")
        self.assertEqual((change["payload"]["person"], change["payload"]["source"], change["payload"]["text"]),
                         ("Aino", "business_owner", "the return button does nothing"))
        self.assertEqual((change["payload"]["triage"]["class"], change["state"]), ("defect", "resolved"))
        self.assertIn({"handoff": {"card": change["id"], "class": "defect", "changed": ["R-2"]}}, out["history"])
        self.assertEqual(p.read("releases/1.json")["handoff"],
                         {"to": "change", "card": validation["id"], "verdict": "fix", "change": change["id"],
                          "applied": True})
        self.assertFalse(p.meta["built"])                              # the repair is queued
        self.assertEqual([t for t, s in p.read("tasks.json").items() if s["status"] == "pending"], ["T-002"])
        self.assertEqual(len(p.ledger().of_kind("handoff_opened")), 1)

    def test_FR_R3_AC_2_a_change_waits_for_a_business_decision_then_amends_the_spec(self):
        p, _, failed = self.validated("change", "Pekka", "product_owner", "Sort the loan list by borrower")
        first = self.run_once(p, failed)
        [change] = Canon(p).cards(state=None, kind="change")
        self.assertEqual((first["state"], first["waiting_on"]), ("waiting", [change["id"]]))
        self.assertEqual((change["payload"]["triage"]["class"], change["payload"]["person"]),
                         ("change_request", "Pekka"))
        again = self.run_once(p, failed)                               # opened once, however often it runs
        self.assertEqual(again["waiting_on"], [change["id"]])
        self.assertEqual(len(Canon(p).cards(state=None, kind="change")), 1)
        Canon(p).decide(change["id"], "accept", person="Aino", persona="business_owner")
        self.run_once(p, failed)
        r2 = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        self.assertEqual((r2["statement"], r2["decided_by"]), ("A loan records the approver if given.", "Aino"))
        self.assertTrue(p.read("releases/1.json")["handoff"]["applied"])

    def test_FR_R3_AC_2_a_change_card_rejected_leaves_the_release_failed_and_says_why(self):
        p, _, failed = self.validated("change", "Pekka", "product_owner", "Sort the loan list by borrower")
        self.run_once(p, failed)
        [change] = Canon(p).cards(state=None, kind="change")
        Canon(p).decide(change["id"], "reject", person="Aino", persona="business_owner", reason="not now")
        before = self.snapshot(p)
        out = self.run_once(p, failed)
        self.assertEqual(out["state"], "failed")
        self.assertIn(f"{change['id']} was decided reject by Aino", out["why"])
        self.assertEqual(self.snapshot(p), before)


# -- FR-A4: withdrawing, a refused compile, and stable task ids ---------------------------------------------

class AmendmentTest(GovernanceCase):
    def test_FR_A4_AC_3_an_amendment_that_withdraws_a_requirement_is_applied_and_leaves_no_work_on_it(self):
        p = self.compiled()
        m = amending({"modify": [], "add": [], "withdraw": ["R-3"]})
        out = apply_change(p, self.accepted(p, m, "We no longer need the benefit report"), model=m)
        self.assertEqual(out["changed"], ["R-3"])
        contract = p.read("contract.json")
        self.assertEqual(contract_check().check(contract)[0].violations, [])
        self.assertEqual(next(r for r in contract["requirements"] if r["id"] == "R-3")["provenance"], "withdrawn")
        self.assertEqual([t["id"] for t in contract["tasks"]], ["T-001", "T-002", "T-004"])   # the others keep ids
        self.assertEqual(contract["tasks"][2]["depends_on"], ["T-002"])
        self.assertFalse(any(r["requirement"] == "R-3" for r in p.read("checkplan.json")["checks"]))
        self.assertEqual(next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-3")["provenance"],
                         "withdrawn")
        self.assertEqual((p.meta["contract_revision"], p.meta["spec_version"]), (contract["revision"], 2))

    def test_FR_A4_AC_3_a_withdrawn_or_restated_criterions_holdout_is_retired_and_never_runs_again(self):
        p = self.compiled()
        self.assertEqual(author_holdouts(p, model=model()), ["R-1-AC-2", "R-4-AC-2"])
        steps = [{"method": "POST", "path": "/items", "body": {"name": HELD}, "expect_status": 201}]
        write_json(p.holdouts_dir / "R-1-AC-2.json", {"criterion": "R-1-AC-2", "kind": "holdout", "steps": steps,
                                                      "author_role": "holdout_author"})
        # withdraw "a team member can add an item": its holdout leaves the runs, the probe's stays
        m = amending({"withdraw": ["R-1"], "add": [], "modify": []})
        withdrawn = self.accepted(p, m, "Items are added by the warehouse system now")
        out = apply_change(p, withdrawn, model=m)
        self.assertEqual((out["changed"], out["holdouts_retired"]), (["R-1"], ["R-1-AC-2"]))
        report, ran = self.holdouts_run(p)
        self.assertEqual(ran, ["R-4-AC-2"])                            # the withdrawn one would have failed
        self.assertEqual((report["verdict"], report["failed"], report["missing"]), ("passed", 0, []))
        self.assertEqual(author_holdouts(p, model=model(), only="missing"), [])           # nor is it written again
        # kept in the custody, out of the runs, and still custody content the MCP server redacts
        self.assertEqual(read_json(p.holdouts_dir / "R-1-AC-2.retired.json"),
                         {"criterion": "R-1-AC-2", "retired": {withdrawn: steps}})
        self.assertIn(HELD, RihmaMCP(self.factory, person="Mia", persona="developer")._held())
        # restate the probe's criterion: its scenario is retired and written anew before the next delivery
        m = amending({"withdraw": [], "add": [], "modify": [{
            "id": "R-4", "statement": "The page loads fast.", "acceptance": [
                {"given": "-", "when": "GET /health", "then": "answers in under 500 ms", "kind": "test"},
                {"given": "-", "when": "GET /health", "then": "answers in under 200 ms", "kind": "probe"}]}]})
        restated = self.accepted(p, m, "The page must be faster")
        self.assertEqual(apply_change(p, restated, model=m)["holdouts_retired"], ["R-4-AC-2"])
        report, ran = self.holdouts_run(p)
        self.assertEqual((ran, report["verdict"], report["missing"]), ([], "not measured", ["R-4-AC-2"]))
        self.assertEqual(author_holdouts(p, model=model(), only="missing"), ["R-4-AC-2"])
        self.assertEqual(sorted(x.name for x in p.holdouts_dir.glob("*.json")),
                         ["R-1-AC-2.retired.json", "R-4-AC-2.json", "R-4-AC-2.retired.json"])
        self.assertEqual([r["event"]["payload"] for r in p.ledger().of_kind("holdouts_retired")],
                         [{"criteria": ["R-1-AC-2"], "because": withdrawn},
                          {"criteria": ["R-4-AC-2"], "because": restated}])
        # a change that leaves a criterion's wording as it was retires nothing
        same = amending({"withdraw": [], "add": [], "modify": [{
            "id": "R-4", "statement": "The page loads very fast.", "acceptance": [
                {"given": "-", "when": "GET /health", "then": "answers in under 500 ms", "kind": "test"},
                {"given": "-", "when": "GET /health", "then": "answers in under 200 ms", "kind": "probe"}]}]})
        self.assertEqual(apply_change(p, self.accepted(p, same, "Reword the speed"), model=same)["holdouts_retired"], [])
        self.assertTrue((p.holdouts_dir / "R-4-AC-2.json").exists())

    @staticmethod
    def holdouts_run(p: Project) -> tuple[dict[str, Any], list[str]]:
        """The holdouts run against a service that fails every R-1 scenario: the report, and what ran."""
        ran: list[str] = []

        def scenario(base_url: str, s: dict[str, Any]) -> dict[str, Any]:
            ran.append(s["criterion"])
            return {"criterion": s["criterion"], "verdict": "failed" if s["criterion"].startswith("R-1-") else "passed"}

        with mock.patch("kernel.operate.run_scenario", side_effect=scenario):
            return run_holdouts(p, "http://127.0.0.1:9"), ran

    def test_FR_A4_AC_3_a_change_the_compiler_refuses_leaves_spec_contract_and_approvals_as_they_were(self):
        p = self.compiled()
        canon = Canon(p)
        approval = canon.card("validation", "Accept the pilot?", refs={"requirements": ["R-2"]})
        canon.decide(approval["id"], "accept", person="Aino", persona="business_owner")
        card = self.accepted(p, model(), "The approver should be optional")
        before = self.snapshot(p)
        refusal = CompileError([{"rule": "R-TRACE", "path": "/tasks/2/criteria/0"}])
        with mock.patch("kernel.change.to_contract", side_effect=refusal), self.assertRaises(CompileError):
            apply_change(p, card, model=model())
        self.assertEqual(self.snapshot(p), before)                     # the spec and the contract still match
        self.assertFalse(p.path("spec.v1.json").exists())

    def test_FR_A4_AC_1_adding_a_requirement_renumbers_no_task_and_a_default_checks_task_keeps_its_state(self):
        write_json(self.factory.home / "factory" / "default_checks.json",
                   [{"class": "empty name refused", "given": "-", "when": "POST /items with an empty name",
                     "then": "400, not 500", "accepted_by": "Aino", "card": "C-0001", "from_projects": ["a", "b"]}])
        p = self.compiled()
        tasks = {t["id"]: t["criteria"] for t in p.read("contract.json")["tasks"]}
        self.assertEqual(tasks["T-005"], ["FD-1-AC-1"])
        self.built(p)
        m = amending({"modify": [], "withdraw": [], "add": [
            {"statement": "Overdue loans are listed.", "acceptance": [
                {"given": "a loan past its date", "when": "GET /overdue", "then": "200 with the loan", "kind": "test"}]}]})
        out = apply_change(p, self.accepted(p, m, "We also need a page that shows overdue loans"), model=m)
        self.assertEqual(out["changed"], ["R-5"])
        tasks = {t["id"]: t["criteria"] for t in p.read("contract.json")["tasks"]}
        self.assertEqual((tasks["T-005"], tasks["T-006"]), (["FD-1-AC-1"], ["R-5-AC-1"]))
        state = p.read("tasks.json")
        self.assertEqual((state["T-005"]["status"], state["T-005"]["revision"]), ("merged", "rev-T-005"))
        self.assertEqual((state["T-006"]["status"], state["T-006"]["reopened_by"]), ("pending", ["R-5"]))
        self.assertEqual([t for t, s in state.items() if s["status"] == "pending"], ["T-006"])


# -- FR-V2-AC-2 and FR-S1-AC-3: tick on the command line; reads create nothing --------------------------------

class FactoryLevelTest(GovernanceCase):
    def test_FR_V2_AC_2_rihma_tick_carries_out_decided_concepts_from_the_command_line(self):
        f = self.factory
        s = receive(f, "Warehouse staff need to report damaged pallets from a phone", channel="meeting",
                    source="ops weekly", person="Sanna", persona="stakeholder")
        concept = triage_signal(f, s["id"])["routed_to"]["card"]
        self.assertEqual(self.cli("tick"), {"concepts_applied": [], "projects_created": []})
        Canon(factory_project(f)).decide(concept, "validate", person="Aino", persona="business_owner",
                                         reason="worth a demo")
        out = self.cli("tick")
        [pid] = out["projects_created"]
        self.assertEqual(out["concepts_applied"][0]["card"], concept)
        self.assertFalse(f.project(pid).path("source.json").exists())  # its intake waits for a run
        self.assertEqual(self.cli("tick")["concepts_applied"], [])     # carried out once

    def test_FR_S1_AC_3_reading_a_cap_or_the_observations_never_creates_the_factorys_canon(self):
        p = self.new()
        self.assertEqual((factory_cap(self.factory), cap_of(p), describe(factory=self.factory)["cap"]), (4, 4, 4))
        self.assertEqual(observations(self.factory), [])
        self.assertFalse((self.factory.projects_dir / FACTORY_PID).exists())
        set_cap(self.factory, 3, person="Aino", persona="business_owner", reason="sandbox only")   # a writer does
        self.assertIsNotNone(factory_project(self.factory, create=False))
        self.assertEqual(factory_cap(self.factory), 3)


# -- FR-P3-AC-2: nothing the analyst drafted is dropped silently ---------------------------------------------

def drafted(requirements: list) -> FakeModel:
    def run(prompt: str, role: str) -> str:
        if "You turn a brief into a software specification" in prompt:
            return "```json\n" + json.dumps(dict(SPEC, requirements=requirements)) + "\n```"
        return script(prompt, role)
    return FakeModel(run)


class DroppedTest(GovernanceCase):
    def test_FR_P3_AC_2_the_spec_records_what_the_analysts_draft_lost_and_keeps_no_dangling_source(self):
        p = self.new(mode="assume")                                    # demo: at most five requirements
        intake(p, IDEA, model=model(), requested_by="Aino")

        def req(n: int, *, sources: tuple = ("request",), criteria: int = 1) -> dict:
            return {"statement": f"Requirement {n}", "sources": list(sources),
                    "acceptance": [{"given": "-", "when": f"GET /r{n}", "then": f"200 number {k}", "kind": "test"}
                                   for k in range(1, criteria + 1)]}
        draft = [req(1, sources=("Q-001", "Q-999", "the consultant")), {"statement": " ", "acceptance": []},
                 dict(req(3), acceptance=[{"given": "-", "when": "-", "then": ""}]), req(4, criteria=4), req(5),
                 req(6), req(7)]
        spec = make_spec(p, model=drafted(draft))
        self.assertEqual([r["statement"] for r in spec["requirements"]],
                         ["Requirement 1", "Requirement 4", "Requirement 5"])
        self.assertEqual(spec["requirements"][0]["sources"], ["Q-001"])
        beyond = "beyond the 5 requirements a demo spec may have"
        self.assertEqual(spec["dropped"], [
            {"what": "source", "requirement": "R-1", "source": "Q-999", "why": "names no question in the canon"},
            {"what": "source", "requirement": "R-1", "source": "the consultant",
             "why": "is not the request, a question or proposed"},
            {"what": "requirement", "item": 2, "why": "it has no statement"},
            {"what": "requirement", "item": 3, "statement": "Requirement 3",
             "why": "it has no usable acceptance criterion"},
            {"what": "criterion", "requirement": "R-2", "item": 4, "then": "200 number 4",
             "why": "beyond the three criteria a requirement may have"},
            {"what": "requirement", "item": 6, "statement": "Requirement 6", "why": beyond},
            {"what": "requirement", "item": 7, "statement": "Requirement 7", "why": beyond}])
        self.assertEqual(p.read("spec.json")["dropped"], spec["dropped"])
        self.assertIn("## Dropped from the analyst's draft", p.path("spec.md").read_text(encoding="utf-8"))
        self.assertEqual(p.ledger().of_kind("spec_written")[-1]["event"]["payload"]["dropped"], 7)


if __name__ == "__main__":
    unittest.main()
