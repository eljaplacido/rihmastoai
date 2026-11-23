import hashlib
import json
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_deliver import DeliveryTestCase  # noqa: E402

from adapters.sarif import SarifError, ingest  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.security import accept_risk, findings, security_gate, summary  # noqa: E402

SARIF = Path(__file__).parent / "fixtures" / "sarif"


def kinds(project) -> list:
    return [r["event"]["kind"] for r in project.ledger().records()]


class SarifTest(FactoryTestCase):
    def test_FR_H8_AC_1_a_sarif_file_from_any_scanner_becomes_findings_in_the_ledger(self):
        p = self.new()
        scan = ingest(p, SARIF / "bandit.sarif", person="Kaisa", persona="compliance")
        self.assertEqual(scan["scan"], 1)
        self.assertEqual(scan["counts"], {"error": 1, "warning": 1, "note": 1, "none": 0})
        first = scan["findings"][0]
        self.assertEqual((first["id"], first["rule"], first["level"]), ("SEC-1-1", "B602", "error"))
        self.assertEqual(first["message"], "subprocess call with shell=True identified, security issue.")
        self.assertEqual(first["location"], {"uri": "app/routes.py", "line": 14, "column": 5})
        self.assertEqual(first["cwe"], ["CWE-78"])
        self.assertEqual(first["tool"], {"name": "Bandit", "version": "1.7.9"})
        self.assertEqual(scan["findings"][1]["cwe"], ["CWE-259"])
        self.assertEqual(p.read("security/1.json")["findings"], scan["findings"])
        rec = [r["event"]["payload"] for r in p.ledger().of_kind("security_scan")][0]
        self.assertEqual(rec["sha256"], hashlib.sha256((SARIF / "bandit.sarif").read_bytes()).hexdigest())
        self.assertEqual((rec["tool"], rec["counts"]["error"], rec["findings"]), (first["tool"], 1, 3))
        # another scanner, another shape: the level from the rule's default, the version from semanticVersion
        sem = ingest(p, SARIF / "semgrep.sarif")
        f = sem["findings"][0]
        self.assertEqual((f["level"], f["cwe"], f["tool"]["version"]), ("error", ["CWE-89"], "1.90.0"))
        self.assertEqual(f["location"]["uri"], "app/report.py")
        # and the owner's: CWE from taxa and relationships; a passing check is not a finding; a suppression is flagged
        tb = ingest(p, SARIF / "example-hardening.sarif")
        self.assertEqual([x["rule"] for x in tb["findings"]], ["TB-HDR-001", "TB-CFG-003"])
        self.assertEqual(tb["findings"][0]["cwe"], ["CWE-693"])
        self.assertEqual((tb["findings"][1]["cwe"], tb["findings"][1]["suppressed_in_source"]), (["CWE-16"], True))
        self.assertEqual(tb["tools"], [{"name": "Example Hardening Scanner", "version": "2.3.0"}])
        with self.assertRaises(SarifError):
            ingest(p, SARIF / "wrong-version.sarif")
        self.assertIn("security_scan_refused", kinds(p))
        self.assertFalse(p.path("security", "4.json").exists())
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_H8_AC_1_the_security_gate_blocks_until_a_person_accepts_the_risk_until_its_expiry(self):
        p = self.new()
        none = security_gate(p)
        self.assertEqual((none["verdict"], none["reason"]), ("not measured", "not measured: no security scan"))
        self.assertEqual(summary(p)["note"], "not measured: no security scan")
        ingest(p, SARIF / "bandit.sarif")
        gate = security_gate(p)
        self.assertEqual((gate["verdict"], gate["blocked"]), ("failed", True))
        self.assertEqual([b["id"] for b in gate["blocking"]], ["SEC-1-1"])
        for who, persona, reason, until in (("Pekka", "developer", "fine", "2026-12-31"),
                                            ("assistant", "it", "fine", "2026-12-31"),
                                            ("Ilkka", "it", " ", "2026-12-31"),
                                            ("Ilkka", "it", "fine", "2026-11-22"),
                                            ("Ilkka", "it", "fine", "next week")):
            with self.assertRaises(DecisionRefused, msg=(who, persona, reason, until)):
                accept_risk(p, "SEC-1-1", person=who, persona=persona, reason=reason, expires=until)
        acc = accept_risk(p, "SEC-1-1", person="Ilkka", persona="it", expires="2026-12-31",
                          reason="the shell call runs only in the admin tool, behind the VPN; fix planned in Q1")
        self.assertEqual((acc["person"], acc["persona"], acc["expires"]), ("Ilkka", "it", "2026-12-31"))
        self.assertIn("risk_accepted", kinds(p))
        gate = security_gate(p)
        self.assertEqual((gate["verdict"], [a["id"] for a in gate["accepted"]]), ("passed", ["SEC-1-1"]))
        self.assertEqual(security_gate(p, block_on=("error", "warning"))["verdict"], "failed")    # B105 is a warning
        ingest(p, SARIF / "bandit.sarif")                                            # the same finding, rescanned
        gate = security_gate(p)
        self.assertEqual((gate["verdict"], [a["id"] for a in gate["accepted"]]), ("passed", ["SEC-2-1"]))
        self.clock.advance(days=40)                                                  # 2027-01-01: expired
        gate = security_gate(p)
        self.assertEqual((gate["verdict"], [r["id"] for r in gate["reopened"]]), ("failed", ["SEC-2-1"]))
        self.assertEqual([f["state"] for f in findings(p) if f["rule"] == "B602"], ["open"])
        self.assertIn("risk_acceptance_expired", kinds(p))
        ingest(p, SARIF / "bandit-clean.sarif")                                      # fixed: the tool reports nothing
        self.assertEqual(security_gate(p)["verdict"], "passed")
        verdicts = [r["event"]["payload"]["verdict"] for r in p.ledger().of_kind("security_gate")]
        self.assertEqual(verdicts[0], "not measured")
        self.assertEqual(verdicts[-1], "passed")


class SecurityPackTest(DeliveryTestCase):
    maturity = "explore"

    def test_FR_H8_AC_1_the_capability_and_evidence_packs_name_the_scan_or_say_not_measured(self):
        from kernel.deliver import deliver
        from kernel.evidence_pack import export
        from kernel.packs import build_pack

        self.factory.paved_roads_path.unlink()
        deliver(self.project)
        pack = build_pack(self.project)
        self.assertEqual((pack["security"]["verdict"], pack["security"]["note"]),
                         ("not measured", "not measured: no security scan"))
        path = export(self.project, self.tmp / "out", person="Kaisa", persona="compliance")
        with zipfile.ZipFile(path) as z:
            sec = json.loads(z.read("security.json"))
            readme = z.read("README.md").decode("utf-8")
        self.assertEqual(sec["verdict"], "not measured")
        self.assertIn("Security: not measured: no security scan", readme)
        self.assertNotIn("passed", json.dumps(sec))
        ingest(self.project, SARIF / "bandit.sarif", person="Kaisa", persona="compliance")
        accept_risk(self.project, "SEC-1-2", person="Kaisa", persona="compliance", expires="2027-03-31",
                    reason="a test fixture password, never deployed")
        again = build_pack(self.project)
        self.assertEqual(again["version"], pack["version"])                          # a scan is evidence, not behaviour
        sec = again["security"]
        self.assertEqual([(s["tool"], s["version"], s["counts"]["error"]) for s in sec["scans"]], [("Bandit", "1.7.9", 1)])
        self.assertEqual([(a["finding"], a["person"], a["expires"]) for a in sec["accepted_risks"]],
                         [("SEC-1-2", "Kaisa", "2027-03-31")])
        self.assertEqual((sec["verdict"], sec["open"]["error"]), ("failed", 1))
        path = export(self.project, self.tmp / "out2", person="Kaisa", persona="compliance")
        with zipfile.ZipFile(path) as z:
            sec = json.loads(z.read("security.json"))
            readme = z.read("README.md").decode("utf-8")
            att = json.loads(z.read("attestation.json"))
            manifest = json.loads(z.read("MANIFEST.json"))
        self.assertEqual(sec["scans"][0]["sha256"], hashlib.sha256((SARIF / "bandit.sarif").read_bytes()).hexdigest())
        self.assertIn("Bandit 1.7.9", readme)
        self.assertIn("1 risk(s) accepted", readme)
        art15 = next(c for c in att["controls"] if c["control"] == "ai-act:art15")
        self.assertIn("Bandit", art15["by"])
        self.assertIn("security.json", manifest["files"])


if __name__ == "__main__":
    unittest.main()
