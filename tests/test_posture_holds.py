"""What a posture holds, and who may release it (FR-POS7): a tightened posture does not ask again about a
revision already built; under a confirming posture only the customer's side approves the plan or a
go-ahead; regulated at pilot needs its evidence pack before staging; what a posture requires is no risk
to accept; and a change that ends the reason a plan waited withdraws its card.
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, model, no_findings  # noqa: E402

from adapters.sarif import ingest  # noqa: E402
from kernel import cli  # noqa: E402
from kernel.autonomy import cleared_to_build  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.deliver import _Delivery  # noqa: E402
from kernel.evidence_pack import export  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.plan import edit_requirement, gate as plan_gate  # noqa: E402
from kernel.posture import effects, lines  # noqa: E402
from kernel.posture_change import change  # noqa: E402
from kernel.posture_rules import Held, go_ahead_cards  # noqa: E402
from kernel.security import accept_risk, security_gate  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import _held_release  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
COVERS_ALL = [{"given": "an item", "when": "POST /items/{id}/loan without a credential", "then": "401 and nothing changes"},
              {"given": "a loan", "when": "it changes", "then": "an audit record says who made the change and when"},
              {"given": "a borrower", "when": "they ask", "then": "their personal data is deleted on request"}]


def kinds(project) -> list:
    return [r["event"]["kind"] for r in project.ledger().records()]


def sarif(path: Path, tool: str) -> Path:
    path.write_text(json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver": {"name": tool, "version": "1.0.0",
                                                                                  "rules": []}}, "results": []}]}),
                    encoding="utf-8")
    return path


class HoldsCase(FactoryTestCase):
    def posed(self, name, weights=None, **kw):
        return self.factory.new_project("Equipment loans", posture={"name": name, "weights": weights, "by": "Aino",
                                                                    "persona": "business_owner"}, **kw)

    def run_until(self, p, stop, *, decide=("Aino", "business_owner"), rounds=10):
        """Advance, answering questions and approving cards as ``decide``, until ``stop(card)`` for an
        open card (or nothing is open). Returns the last outcome and the card it stopped on."""
        kw = dict(model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=generic_cell,
                  verifier_runner=no_findings, deliver_kwargs={})
        canon = Canon(p)
        for _ in range(rounds):
            out = advance(p, **kw)
            cards = canon.cards()
            card = next((c for c in cards if stop(c)), None)
            if card is not None or not cards:
                return out, card
            for c in cards:
                if c["kind"] == "question":
                    canon.answer(c["refs"]["question"], "the team lead approves", person=decide[0], persona=decide[1])
                elif c["kind"] == "approval":
                    canon.decide(c["id"], "approve", person=decide[0], persona=decide[1], reason="go")
        self.fail(f"no card matched in {rounds} rounds: {[c['title'] for c in canon.cards()]}")


class TightenedAfterTheBuildTest(HoldsCase):
    def test_FR_POS7_AC_1_a_posture_tightened_after_the_build_asks_only_about_the_delivery(self):
        p = self.posed("prototype")
        intake(p, IDEA, model=model(), requested_by="Aino")
        self.run_until(p, lambda c: c["kind"] == "road")                       # built; release 1 waits on IT's road
        self.assertTrue(p.meta["built"])
        merged = kinds(p).count("merged")
        open_ones = [a["id"] for a in Canon(p).assumptions("open")]
        self.assertTrue(open_ones)                                              # assume mode made assumptions
        said = change(p, "balanced", {"compliance": 3}, person="Pia", persona="product_owner",
                      reason="customer data after all")
        self.assertIn(f"confirmation reopened: {', '.join(open_ones)} must be confirmed or refuted by a person before "
                      "the next build", said["now"])
        out = advance(p, model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=generic_cell,
                      verifier_runner=no_findings, deliver_kwargs={})
        self.assertEqual(out["state"], "capped")
        asked = go_ahead_cards(p)
        self.assertEqual([c["payload"]["key"].split(":")[0] for c in asked], ["deliver"])   # not "build" again
        self.assertIn("delivering revision", out["why"])
        Canon(p).decide(asked[0]["id"], "approve", person="Aino", persona="business_owner", reason="go")
        advance(p, model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=generic_cell,
                verifier_runner=no_findings, deliver_kwargs={})
        self.assertEqual(kinds(p).count("merged"), merged)                     # nothing was built again
        self.assertEqual(go_ahead_cards(p), [])
        # the open assumptions hold the next build, as the change said
        p.update_meta(built=False)
        with self.assertRaises(Held) as held:
            cleared_to_build(p)
        self.assertIn(open_ones[0], str(held.exception))


class CustomerSideDecidesTest(HoldsCase):
    def test_FR_POS7_AC_2_under_a_confirming_posture_only_the_customer_side_approves_the_plan_and_the_go_ahead(self):
        p = self.posed("regulated", maturity="demo")
        intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        for q in canon.questions("open"):
            canon.answer(q["id"], q["opinions"].get(q["perspective"]) or "yes", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        card = canon.get_card(plan_gate(p, model=model())["waiting_on"][0])
        self.assertEqual(card["deciders"], ["business_owner"])                 # topics missing: approving waives them
        self.assertIn("only a business owner approves this plan", card["body"])
        for persona in ("developer", "product_owner"):
            with self.assertRaises(DecisionRefused):
                canon.decide(card["id"], "approve", person="Dev", persona=persona)
        with self.assertRaises(DecisionRefused):                                # an edit confirms: not the vendor's
            edit_requirement(p, "R-2", person="Dev", persona="developer", acceptance=COVERS_ALL)
        edit_requirement(p, "R-2", person="Pia", persona="product_owner", acceptance=COVERS_ALL)
        card = canon.get_card(plan_gate(p, model=model())["waiting_on"][0])
        self.assertEqual(card["deciders"], ["business_owner", "product_owner"])
        with self.assertRaises(DecisionRefused):
            canon.decide(card["id"], "approve", person="Dev", persona="developer")
        canon.decide(card["id"], "approve", person="Pia", persona="product_owner", reason="as agreed")
        self.assertIsNone(plan_gate(p, model=model()))
        confirmed = {r["confirmed"]["persona"] for r in p.read("spec.json")["requirements"] if r.get("confirmed")}
        self.assertEqual(confirmed, {"product_owner"})
        p.update_meta(contract_revision="sha256:" + "ab" * 32)
        with self.assertRaises(Held) as held:
            cleared_to_build(p)
        go = canon.get_card(held.exception.card)
        self.assertEqual(go["deciders"], ["business_owner", "product_owner"])
        with self.assertRaises(DecisionRefused):
            canon.decide(go["id"], "approve", person="Dev", persona="developer")
        set_on = [r["event"]["payload"]["card"] for r in p.ledger().of_kind("card_deciders_set")]
        self.assertIn(go["id"], set_on)                                         # who decides is in the ledger
        # a posture that does not confirm keeps the approval card's own deciders
        b = self.posed("balanced")
        b.update_meta(contract_revision="sha256:" + "cd" * 32)
        with self.assertRaises(Held) as held:
            cleared_to_build(b)
        self.assertIn("developer", Canon(b).get_card(held.exception.card)["deciders"])


class EvidenceAtPilotTest(HoldsCase):
    def test_FR_POS7_AC_3_regulated_at_pilot_needs_its_attestable_evidence_pack_before_staging(self):
        self.assertIn("Before a release lands on staging, an evidence pack", " ".join(lines(effects("regulated"))["gates"]))
        p = self.posed("regulated")
        self.assertEqual(p.meta["maturity"], "pilot")
        ingest(p, sarif(self.tmp / "static.sarif", "Rihmasto red team (static)"))
        intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        make = self.run_until(p, lambda c: c["kind"] == "approval" and c["refs"].get("scope") == "plan")[1]
        edit_requirement(p, "R-2", person="Aino", persona="business_owner", acceptance=COVERS_ALL)
        self.assertNotEqual(make["id"], canon.get_card(plan_gate(p, model=model())["waiting_on"][0])["id"])
        self.run_until(p, lambda c: c["kind"] == "road")                       # the release started: IT's road
        gate = security_gate(p, record=False)
        self.assertIn("POSTURE-EVIDENCE", [b["id"] for b in gate["blocking"]])
        self.assertIn("attestable, exported before staging", gate["reason"])
        export(p, self.tmp / "packs", person="Kaisa", persona="compliance")
        self.assertEqual([r["event"]["payload"]["verdict"] for r in p.ledger().of_kind("evidence_exported")],
                         ["attestable"])
        self.assertNotIn("POSTURE-EVIDENCE", [b["id"] for b in security_gate(p, record=False)["blocking"]])


class NoRiskToAcceptTest(HoldsCase):
    def test_FR_POS7_AC_4_what_a_posture_requires_is_held_without_offering_a_risk_acceptance(self):
        p = self.posed("production", maturity="pilot")
        with self.assertRaises(DecisionRefused) as refused:
            accept_risk(p, "POSTURE-SCAN", person="Kaisa", persona="compliance", reason="x", expires="2099-01-01")
        self.assertIn("not a security finding", str(refused.exception))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--home", str(self.factory.home), "security", "accept", p.pid, "POSTURE-SCAN", "--person",
                             "Kaisa", "--persona", "compliance", "--reason", "x", "--expires", "2099-01-01"])
        self.assertEqual(code, 2)
        self.assertIn("cannot be accepted as a risk", err.getvalue())
        delivery = _Delivery(p, None, None, None)
        delivery.rel = {"release": 1}
        _, held = delivery.security("staging")
        self.assertIn("cannot be accepted as a risk", held["waiting_on"])
        self.assertNotIn("accepts the risk until a date", held["waiting_on"])
        line = _held_release([{"number": 1, "state": "waiting", "blocked": held["blocked"]}])
        self.assertIn("no risk to accept", line)
        self.assertNotIn("accepts the risk", line)


class PlanCardFollowsTheChangeTest(HoldsCase):
    def test_FR_POS7_AC_5_a_change_that_ends_the_reason_a_plan_waited_withdraws_its_card(self):
        p = self.posed("balanced", {"security": 2})
        intake(p, IDEA, model=model(), requested_by="Aino")
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        card = plan_gate(p, model=model())["waiting_on"][0]
        out = change(p, "balanced", {"security": 1}, person="Aino", persona="business_owner", reason="internal only")
        self.assertIn(f"{card} withdrawn: the plan needs no approval now", out["applied"])
        self.assertEqual(Canon(p).get_card(card)["state"], "withdrawn")
        self.assertIsNone(plan_gate(p, model=model()))
        # a change that keeps the plan waiting but changes who approves it reopens the card as it now reads
        q = self.posed("balanced", {"security": 2})
        intake(q, IDEA, model=model(), requested_by="Aino")
        Canon(q).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(q, model=model())
        first = plan_gate(q, model=model())["waiting_on"][0]
        out = change(q, "balanced", {"security": 2, "compliance": 3}, person="Pia", persona="product_owner",
                     reason="customer data")
        self.assertIn(f"{first} withdrawn", out["applied"])
        again = Canon(q).get_card(plan_gate(q, model=model())["waiting_on"][0])
        self.assertNotEqual(again["id"], first)
        self.assertEqual(again["deciders"], ["business_owner"])
        self.assertIn("Approving confirms each requirement in your name", again["body"])


if __name__ == "__main__":
    unittest.main()
