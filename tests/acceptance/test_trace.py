"""Every path writes the same trace (D-0017; docs/acceptance.md, "The trace"; FR-AM8).

Who asked, who decided or let the factory assume, what was assumed and what proves it, in the
hash-chained ledger, on the quickest path and on the strictest. Who asked (and who chose the mode)
reaches the ledger only through the cockpit today (its `cockpit_write` record); on the command line
and the kernel's path it is kept in source.json and project.json, outside the chain. That cell
fails, and is marked as an expected failure until intake records it.
"""

import json
import unittest
import zipfile

from kernel.canon import Canon
from kernel.evidence_pack import export

from .scripts import COMPLIANCE, IT, OWNER, AcceptanceCase, payloads, trace


class TraceTest(AcceptanceCase):
    def test_FR_AM8_AC_1_the_quickest_and_the_strictest_paths_both_record_decisions_assumptions_and_proof(self):
        quick = self.need("invoices", mode="assume", maturity="explore")
        out, _ = self.ship(quick)
        self.assertDelivered(quick, out, "preview")
        strict = self.need("rooms", mode="socratic", maturity="production")
        self.answer_open(strict)
        out, _ = self.ship(strict)
        self.assertDelivered(strict, out, "production")
        q, s = trace(quick), trace(strict)
        self.assertTrue(q["intact"] and s["intact"])
        self.assertEqual(q["decided"], [])                                      # nobody decided ...
        self.assertEqual(len(q["assumed"]), len(Canon(quick).questions()))     # ... every answer was assumed
        self.assertEqual(s["assumed"], [])                                      # ... or nothing was assumed
        self.assertEqual({(p, r) for p, r, _, _ in s["decided"]}, {OWNER, IT})
        for t, env in ((q, "preview"), (s, "production")):                      # what proves it, on both
            self.assertTrue(t["gates"] and {v for _, v in t["gates"]} == {"passed"})
            self.assertEqual(len(t["packs"]), 1)
            self.assertEqual([r["environment"] for r in payloads(quick if t is q else strict, "release_done")], [env])
        path = export(strict, self.tmp / "exports", person=COMPLIANCE[0], persona=COMPLIANCE[1])
        with zipfile.ZipFile(path) as z:
            self.assertEqual(json.loads(z.read("attestation.json"))["verdict"], "attestable")

    @unittest.expectedFailure
    def test_FR_AM8_AC_2_who_asked_and_who_chose_the_mode_are_in_the_ledger_on_every_path(self):
        p = self.need("rooms", mode="assume", maturity="demo", requested_by=OWNER[0])
        self.assertEqual(trace(p)["asked"], [OWNER[0]])
        chosen = [r for r in payloads(p, "project_created", "intake_done") if r.get("mode")]
        self.assertTrue(any(r.get("requested_by") == OWNER[0] for r in chosen))
