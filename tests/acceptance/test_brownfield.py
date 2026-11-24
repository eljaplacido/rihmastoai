"""Brownfield: adopt an existing service, assess it, develop it further (docs/acceptance.md, row B;
FR-AM5).

The existing service is the demo's stock levels repository: a small git repository with its own
unittest suite. Two cells fail today and are marked as expected failures, so the suite stays green
and reports an unexpected success the day either gap closes (then update docs/acceptance.md):
- no paved road runs an adopted repository yet (the README says so);
- the run does not carry out an accepted change: `rihmasto apply` does, and the cockpit has no
  step for it.
The multi-perspective assessment (CI/CD governance, maintenance, security, compliance,
architecture) is being built in another stream; its cell is pending.
"""

import unittest
from pathlib import Path

from adapters import sarif
from kernel.adopt import adopt
from kernel.canon import Canon
from kernel.change import apply_change, submit, triage
from kernel.gate import signal_tests
from kernel.profiles import PROFILE_QUESTION
from kernel.redteam.report import write_sarif
from kernel.redteam.static import scan
from kernel.security import security_gate

from .needs import LOW_STOCK
from .scripts import DEVELOPER, OWNER, PRODUCT, AcceptanceCase, StockCell, payloads

DOC = Path(__file__).resolve().parents[2] / "docs" / "acceptance.md"


class BrownfieldTest(AcceptanceCase):
    def adopted(self):
        """Olli adopts the existing service to maintain it, at explore maturity."""
        repo = self.existing_service()
        p = adopt(self.factory, "Stock levels service", source=repo, intent="maintain", person=DEVELOPER[0],
                  persona=DEVELOPER[1], maturity="explore", timeout=120)
        # Its kind of work is not clear from its files: Olli says which (FR-X1-AC-4, kernel/adopt_kind.py).
        for q in Canon(p).questions("open"):
            if q["text"] == PROFILE_QUESTION:
                Canon(p).answer(q["id"], next(o for o in q["options"] if o.endswith("(web_service)")),
                                person=DEVELOPER[0], persona=DEVELOPER[1])
        return repo, p

    def accepted_change(self, p) -> dict:
        """Pekka files the change, the rules triage it, and Aino accepts it."""
        card = submit(p, persona=PRODUCT[1], person=PRODUCT[0], text=LOW_STOCK)
        tri = triage(p, card["id"], model=self.model)
        self.assertEqual((tri["class"], tri["needs_decision"]), ("new_requirement", True))
        self.decide(p, card["id"], "accept", OWNER, "We need it before the quarterly stock count")
        return card

    def test_FR_AM5_AC_1_an_existing_service_is_adopted_assessed_and_developed_further_through_the_gate(self):
        repo, p = self.adopted()
        baseline = p.read("baseline.json")
        counts = next(r["counts"] for r in baseline["runs"] if r.get("counts"))
        self.assertEqual((baseline["verdict"], counts["ran"], counts["passed"]), ("passed", 3, 3))
        observed = p.read("spec.json")["requirements"]
        self.assertEqual([r["sources"] for r in observed], [["observed"]])          # what it does, not a spec
        self.assertEqual(security_gate(p, record=False)["verdict"], "not measured")  # no scan yet: never "passed"
        report = scan([repo], root=repo)                                            # Rihmasto's own static layer
        write_sarif(self.tmp / "scan.sarif", report)
        scanned = sarif.ingest(p, self.tmp / "scan.sarif", person=DEVELOPER[0], persona=DEVELOPER[1])
        self.assertEqual(scanned["counts"]["error"], 0)
        self.assertEqual(security_gate(p)["verdict"], "passed")                     # measured, nothing open
        idle = self.run_chain(p)
        self.assertEqual((idle["state"], idle["intent"]), ("waiting", "maintain"))
        card = self.accepted_change(p)
        applied = apply_change(p, card["id"], model=self.model)                     # Olli: rihmasto apply
        self.assertEqual((applied["class"], applied["changed"]), ("new_requirement", ["R-2"]))
        added = p.read("spec.json")["requirements"][-1]
        self.assertEqual(added["statement"], "Items whose level is below a threshold are listed as low stock.")
        out = self.run_chain(p, StockCell())
        merged = [m["task"] for m in payloads(p, "merged")]
        self.assertEqual(merged, ["T-002"])                                          # the change, through the gate
        gate = [g for g in payloads(p, "gate") if g["task"] == "T-002"][-1]
        self.assertEqual((gate["verdict"], gate["signals"]["tests"], gate["signals"]["trace"],
                          gate["signals"]["fail_first"]), ("passed", "passed", "passed", "passed"))
        self.assertEqual(out["history"][0], {"build": {"T-002": "merged"}})
        t = self.assertTraced(p)
        self.assertIn((OWNER[0], OWNER[1], "change", "accept"), t["decided"])

    def test_FR_AM5_AC_4_a_suite_at_the_repository_root_is_measured_at_adoption_and_the_gate_runs_only_tests(self):
        repo = self.root_suite_service()
        p = adopt(self.factory, "Job scheduler", source=repo, intent="improve", person=DEVELOPER[0],
                  persona=DEVELOPER[1], maturity="explore", timeout=120)
        baseline = p.read("baseline.json")
        run = next(r for r in baseline["runs"] if r.get("counts"))
        self.assertEqual(run["command"], ["python", "-m", "unittest", "discover", "-v"])   # from the root
        self.assertEqual((baseline["verdict"], run["counts"]["ran"], run["counts"]["passed"]), ("passed", 2, 2))
        gate = signal_tests(repo)                                                    # discover("tests") only
        self.assertEqual((gate.verdict, gate.native["ran"]), ("not measured", 0))
        row = next(line for line in DOC.read_text(encoding="utf-8").splitlines() if line.startswith("| [schedule]"))
        self.assertIn("the adoption baseline runs and measures it", row)            # the page says what was found
        self.assertIn("the gate discovers only under `tests/`", row)
        self.assertNotIn('"not measured" until', row)

    @unittest.expectedFailure
    def test_FR_AM5_AC_2_an_adopted_service_developed_further_is_delivered_on_a_paved_road(self):
        _, p = self.adopted()
        apply_change(p, self.accepted_change(p)["id"], model=self.model)
        out = self.run_chain(p, StockCell())
        self.assertEqual((out["state"], out.get("env")), ("done", "preview"), out.get("why"))

    @unittest.expectedFailure
    def test_FR_AM5_AC_3_the_run_carries_out_an_accepted_change_as_the_cockpits_advance_would(self):
        _, p = self.adopted()
        card = self.accepted_change(p)
        self.run_chain(p, StockCell())                                               # the cockpit's Advance
        self.assertEqual([c["card"] for c in payloads(p, "change_applied")], [card["id"]])
        self.assertEqual(Canon(p).get_card(card["id"])["state"], "decided")
