"""Regression tests for the SARIF adapter and the security gate (FR-H8-AC-1, task V-84).

Each test is a way a scan could pass the gate without anyone having seen or accepted the finding:
a failed scanner run read as a clean scan, a tool fingerprint that leaves out the file or lets a
shared line hash decide, rules kept in a CodeQL extension, a clean scan of another target by the
same tool, an unknown level lowered, an acceptance that outlives a rise in level, malformed SARIF
(a raw line or column, text UTF-8 cannot hold) that crashes instead of being refused, an expiry
recorded as reopening a finding that is still accepted, and an unsigned ingest.

Standard library only: python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from adapters import sarif  # noqa: E402
from adapters.sarif import SarifError, ingest  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.security import accept_risk, findings, security_gate  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "sarif"


def result(rule_id: str, uri: str, line: int, level: Any = "error", **extra: Any) -> dict:
    out: dict[str, Any] = {"ruleId": rule_id, "message": {"text": f"{rule_id} at {uri}:{line}"},
                           "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri},
                                                               "region": {"startLine": line}}}]}
    if level is not None:
        out["level"] = level
    return out | extra


def run(name: str = "Bandit", results: Any = None, rules: list | None = None, **extra: Any) -> dict:
    out: dict[str, Any] = {"tool": {"driver": {"name": name, "version": "1.0", "rules": rules or []}}}
    if results is not None:
        out["results"] = results
    return out | extra


def log(*runs: Any) -> dict:
    return {"version": "2.1.0", "runs": list(runs)}


class SarifCase(FactoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.p = self.new()
        self.files = 0

    def put(self, doc: Any) -> Path:
        self.files += 1
        path = self.tmp / f"scan-{self.files}.sarif"
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
        return path

    def ingest(self, doc: Any) -> dict:
        return ingest(self.p, self.put(doc))

    def refused(self, doc: Any) -> str:
        """Ingesting ``doc`` raises SarifError, records the refusal and stores no scan."""
        before = len(list(self.p.ledger().of_kind("security_scan_refused")))
        stored = len(list(self.p.path("security").glob("[0-9]*.json"))) if self.p.path("security").exists() else 0
        with self.assertRaises(SarifError) as cm:
            self.ingest(doc)
        refusals = list(self.p.ledger().of_kind("security_scan_refused"))
        self.assertEqual(len(refusals), before + 1, "the refusal is recorded")
        after = len(list(self.p.path("security").glob("[0-9]*.json"))) if self.p.path("security").exists() else 0
        self.assertEqual(after, stored, "a refused file stores no scan")
        return str(cm.exception)

    def gate(self) -> dict:
        return security_gate(self.p, record=False)


class FailedRunTest(SarifCase):
    def test_FR_H8_AC_1_a_scanner_run_that_failed_or_never_ran_is_refused_and_never_replaces_the_last_scan(self) -> None:
        self.ingest(log(run(results=[result("B602", "app/routes.py", 14)])))
        self.assertEqual(self.gate()["verdict"], "failed")
        crashed = {"executionSuccessful": False,
                   "toolExecutionNotifications": [{"level": "error", "message": {"text": "syntax error"}}]}
        for broken in (run(invocations=[crashed]),                                   # no results at all
                       run() | {"results": None},                                     # results: null
                       run(),                                                         # no results, no invocations
                       run(results=[], invocations=[crashed]),                        # an empty array, but failed
                       run(results=[], invocations=[{"executionSuccessful": "false"}])):
            self.assertIn("not measured", self.refused(log(broken)))
        gate = self.gate()
        self.assertEqual((gate["verdict"], [b["id"] for b in gate["blocking"]]), ("failed", ["SEC-1-1"]))
        self.assertEqual([s["scan"] for s in gate["scans"]], [1])
        self.ingest(log(run(results=[], invocations=[{"executionSuccessful": True}])))  # a clean, complete run
        self.assertEqual(self.gate()["verdict"], "passed")


class FingerprintTest(SarifCase):
    def test_FR_H8_AC_1_one_acceptance_never_covers_a_finding_in_another_file_or_another_line(self) -> None:
        commit = {"commitSha": "abc123", "email": "dev@example.org", "author": "dev", "date": "2026-11-01",
                  "commitMessage": "wip"}                                       # gitleaks: the same for one commit
        empty = {k: "" for k in commit}                                         # gitleaks --no-git
        line_hash = {"primaryLocationLineHash": "4b1d8a5c0e2f:1"}               # CodeQL: no path in it
        scan = self.ingest(log(run(name="gitleaks", rules=[{"id": "generic-api-key"}], results=[
            result("generic-api-key", "tests/fixture.py", 3, partialFingerprints=commit),
            result("generic-api-key", "app/payments.py", 88, partialFingerprints=commit),
            result("generic-api-key", "app/payments.py", 90, partialFingerprints=empty),
            result("generic-api-key", "app/payments.py", 91, partialFingerprints=empty),
            result("generic-api-key", "admin/tool.py", 7, partialFingerprints=line_hash),
            result("generic-api-key", "app/public_routes.py", 7, partialFingerprints=line_hash),
            result("generic-api-key", "app/twice.py", 5, partialFingerprints=line_hash),
            result("generic-api-key", "app/twice.py", 5, partialFingerprints=line_hash)])))
        prints = [f["fingerprint"] for f in scan["findings"]]
        self.assertEqual(len(set(prints)), len(prints), "every finding of a scan has its own fingerprint")
        accept_risk(self.p, "SEC-1-1", person="Ilkka", persona="it", expires="2027-03-31",
                    reason="a test fixture key, never deployed")
        states = {f["id"]: f["state"] for f in findings(self.p)}
        self.assertEqual(states.pop("SEC-1-1"), "accepted")
        self.assertEqual(set(states.values()), {"open"})
        self.assertEqual(self.gate()["verdict"], "failed")
        # the same scan again: the acceptance still follows its own finding, and only that one
        again = self.ingest(log(run(name="gitleaks", rules=[{"id": "generic-api-key"}], results=[
            result("generic-api-key", "tests/fixture.py", 3, partialFingerprints=commit)])))
        self.assertEqual(again["findings"][0]["fingerprint"], prints[0])
        self.assertEqual([f["state"] for f in findings(self.p)], ["accepted"])
        # a fingerprint with nothing in it counts for nothing: the place decides, so a new secret next to an
        # accepted one leaves the acceptance on its own finding
        self.ingest(log(run(name="gitleaks", rules=[{"id": "generic-api-key"}], results=[
            result("generic-api-key", "app/payments.py", 90, partialFingerprints=empty)])))
        accept_risk(self.p, "SEC-3-1", person="Ilkka", persona="it", expires="2027-03-31", reason="a revoked key")
        self.ingest(log(run(name="gitleaks", rules=[{"id": "generic-api-key"}], results=[
            result("generic-api-key", "app/payments.py", 90, partialFingerprints=empty),
            result("generic-api-key", "app/payments.py", 91, partialFingerprints=empty)])))
        self.assertEqual({f["id"]: f["state"] for f in findings(self.p)}, {"SEC-4-1": "accepted", "SEC-4-2": "open"})

    def test_FR_H8_AC_1_a_tools_full_fingerprint_decides_before_its_partial_one(self) -> None:
        line_hash = {"primaryLocationLineHash": "9c1e2f40b7d3:1"}             # the same line text, the same hash

        def codeql(full: str) -> dict:
            return log(run(name="CodeQL", rules=[{"id": "py/clear-text-logging"}], results=[
                result("py/clear-text-logging", "app/a.py", 3, partialFingerprints=line_hash,
                       fingerprints={"stableResultId/v1": full})]))

        self.ingest(codeql("F1"))
        accept_risk(self.p, "SEC-1-1", person="Ilkka", persona="it", expires="2027-03-31",
                    reason="logs a test token, never a real one")
        self.ingest(codeql("F1"))                                                  # the same result again
        self.assertEqual([(f["id"], f["state"]) for f in findings(self.p)], [("SEC-2-1", "accepted")])
        # another result on that line: its partial fingerprint is the same, the tool's full one is not
        self.ingest(codeql("F2"))
        self.assertEqual([(f["id"], f["state"]) for f in findings(self.p)], [("SEC-3-1", "open")])
        self.assertEqual(self.gate()["verdict"], "failed")


class ExtensionRulesTest(SarifCase):
    CODEQL_RULE: ClassVar[dict] = {
        "id": "py/sql-injection", "shortDescription": {"text": "SQL query built from user input"},
        "defaultConfiguration": {"level": "error"}, "properties": {"tags": ["security", "external/cwe/cwe-089"]}}

    def codeql(self, driver_rules: list, ref: dict, **extra: Any) -> dict:
        res = result("py/sql-injection", "app/db.py", 12, level=None, rule=ref, **extra)
        r = run(name="CodeQL", rules=driver_rules, results=[res])
        r["tool"]["extensions"] = [{"name": "codeql/python-queries", "version": "1.2.0",
                                    "rules": [self.CODEQL_RULE]}]
        return log(r)

    def test_FR_H8_AC_1_rules_kept_in_a_tool_extension_give_the_finding_its_level_and_cwe(self) -> None:
        ref = {"id": "py/sql-injection", "index": 0, "toolComponent": {"index": 0}}
        f = self.ingest(self.codeql([], ref))["findings"][0]
        self.assertEqual((f["level"], f["cwe"]), ("error", ["CWE-89"]))
        self.assertEqual(self.gate()["verdict"], "failed")
        # the driver has rules of its own: the index is read in the extension the result names
        note = {"id": "py/unused-import", "defaultConfiguration": {"level": "note"}}
        g = self.ingest(self.codeql([note], {"index": 0, "toolComponent": {"index": 0}}, ruleIndex=0))["findings"][0]
        self.assertEqual((g["level"], g["cwe"]), ("error", ["CWE-89"]))
        named = self.ingest(self.codeql([note], {"index": 0, "toolComponent": {"name": "codeql/python-queries"}}))
        self.assertEqual(named["findings"][0]["level"], "error")
        # a reference the log cannot resolve is refused, never read as a warning
        self.refused(self.codeql([], {"index": 0, "toolComponent": {"index": 3}}))
        by_index = self.codeql([], {"index": 5, "toolComponent": {"index": 0}})
        del by_index["runs"][0]["results"][0]["ruleId"]                         # only the index names the rule
        self.refused(by_index)
        self.refused(self.codeql([], {"toolComponent": {"name": "codeql/javascript-queries"}}))
        lost = log(run(rules=[{"id": "B101"}], results=[result("B999", "app/x.py", 1, level=None)]))
        self.assertIn("level cannot be known", self.refused(lost))


class ScopeTest(SarifCase):
    def codeql(self, category: str | None, results: list, packs: tuple = ()) -> dict:
        r = run(name="CodeQL", results=results)
        r["tool"]["extensions"] = [{"name": p} for p in packs]
        if category is not None:
            r["automationDetails"] = {"id": category}
        return log(r)

    def test_FR_H8_AC_1_a_clean_scan_of_another_target_by_the_same_tool_leaves_the_open_errors_standing(self) -> None:
        self.ingest(self.codeql("/language:python/", [result("py/sql-injection", "app/db.py", 12)]))
        self.ingest(self.codeql("/language:javascript/", []))
        gate = self.gate()
        self.assertEqual((gate["verdict"], [b["id"] for b in gate["blocking"]]), ("failed", ["SEC-1-1"]))
        self.assertEqual([(s["tool"], s.get("scope")) for s in gate["scans"]],
                         [("CodeQL", "category /language:javascript"), ("CodeQL", "category /language:python")])
        # with no category, the query packs tell the languages apart
        self.ingest(self.codeql(None, [result("js/xss", "web/app.js", 3)], ("codeql/javascript-queries",)))
        self.ingest(self.codeql(None, [], ("codeql/python-queries",)))
        self.assertEqual([b["id"] for b in self.gate()["blocking"]], ["SEC-1-1", "SEC-3-1"])
        # a new run of the same category replaces the last one (the instance id after the last / differs)
        self.ingest(self.codeql("/language:python/2026-11-24", []))
        self.assertEqual([b["id"] for b in self.gate()["blocking"]], ["SEC-3-1"])

    def test_FR_H8_AC_1_a_run_that_names_no_tool_is_refused_not_scanned_as_an_unnamed_tool(self) -> None:
        self.ingest(log(run(name="home-made", results=[result("X1", "app/a.py", 1)])))
        for nameless in (log({"tool": {"driver": {"rules": []}}, "results": []}),
                         log({"tool": {"driver": {"name": "  "}}, "results": []}),
                         log({"results": []}), log(0), log("garbage")):
            self.assertIn("run 1", self.refused(nameless))
        self.assertEqual(self.gate()["verdict"], "failed")

    def test_FR_H8_AC_1_a_scan_stored_before_scopes_were_recorded_gives_way_to_a_later_scan_of_its_tool(self) -> None:
        self.ingest(log(run(name="ExampleScanner", results=[result("TB-1", "app/a.py", 1)])))
        old = self.p.read("security/1.json")
        old.pop("keyed_by")
        self.p.write("security/1.json", old)                     # as a scan was stored before this change
        tb = run(name="ExampleScanner", results=[]) | {"automationDetails": {"id": "examplescanner/run-2"}}
        self.ingest(log(tb))
        gate = self.gate()
        self.assertEqual((gate["verdict"], [(s["tool"], s["scan"]) for s in gate["scans"]]),
                         ("passed", [("ExampleScanner", 2)]))


class LevelTest(SarifCase):
    def test_FR_H8_AC_1_a_level_outside_sarifs_four_is_refused_never_lowered_to_a_warning(self) -> None:
        for level in ("Error", "ERROR", "high", "critical", "", 3):
            doc = log(run(results=[result("B602", "app/routes.py", 14, level=level)]))
            self.assertIn("not a SARIF level", self.refused(doc))
        rule = {"id": "B602", "defaultConfiguration": {"level": "severe"}}
        self.refused(log(run(rules=[rule], results=[result("B602", "app/routes.py", 14, level=None)])))
        self.assertEqual(self.gate()["verdict"], "not measured")
        plain = self.ingest(log(run(results=[result("B1", "app/a.py", 1, level=None)])))   # no rules: SARIF's default
        self.assertEqual(plain["findings"][0]["level"], "warning")

    def test_FR_H8_AC_1_an_acceptance_is_void_once_the_tool_reports_the_finding_at_a_more_severe_level(self) -> None:
        self.ingest(log(run(results=[result("B101", "app/a.py", 9, level="note")])))
        accept_risk(self.p, "SEC-1-1", person="Ilkka", persona="it", expires="2027-03-31", reason="informational")
        self.assertEqual(security_gate(self.p, block_on=("error", "warning", "note"))["verdict"], "passed")
        self.ingest(log(run(results=[result("B101", "app/a.py", 9, level="error")])))     # same finding, now error
        gate = self.gate()
        self.assertEqual((gate["verdict"], [b["id"] for b in gate["blocking"]], gate["accepted"]),
                         ("failed", ["SEC-2-1"], []))
        self.assertEqual([(r["id"], r["accepted_level"], r["level"]) for r in gate["reopened"]],
                         [("SEC-2-1", "note", "error")])
        self.ingest(log(run(results=[result("B101", "app/a.py", 9, level="none")])))      # less severe: still covered
        self.assertEqual([f["state"] for f in findings(self.p)], ["accepted"])


class MalformedTest(SarifCase):
    def test_FR_H8_AC_1_malformed_sarif_is_refused_as_a_sarif_error_and_recorded_never_a_crash(self) -> None:
        ok = result("R1", "app/a.py", 1)
        bad = [log(run(results=[ok | {"message": "plain text"}])),
               log({"tool": {"driver": "bandit"}, "results": []}),
               log({"tool": "x", "results": []}),
               log(run(results=[ok | {"locations": ["a.py"]}])),
               log(run(results=[ok | {"ruleId": ["R"]}])),
               log(run(results=5)),
               log(run(results=["not a result"])),
               log(run(results=[ok], invocations={"executionSuccessful": True})),
               log(run(rules={"id": "R1"}, results=[ok])),
               log(run(results=[ok | {"rule": "R1"}])),
               log(run(results=[ok], automationDetails="ci")),
               "[" * 100000 + "]" * 100000,                                  # too deep to decode
               "not json at all"]
        for doc in bad:
            self.refused(doc)
        refusals = [r["event"]["payload"] for r in self.p.ledger().of_kind("security_scan_refused")]
        self.assertTrue(all(len(r.get("sha256", "")) == 64 for r in refusals))
        # a taxon pointing at a taxonomy the run does not have is not a crash: it names no CWE
        taxon = ok | {"taxa": [{"id": "79", "toolComponent": {"index": -1}}]}
        self.assertEqual(self.ingest(log(run(results=[taxon])))["findings"][0]["cwe"], [])
        self.assertTrue(self.p.ledger().verify().intact)

    def test_FR_H8_AC_1_a_line_or_column_that_is_not_a_whole_number_is_refused_never_stored_raw(self) -> None:
        deep = "[" * 10400 + "]" * 10400              # json reads it this deep, but cannot write it back
        region = '"region":{"startLine":1,"startColumn":' + deep + "}"
        plain = json.dumps(log(run(results=[result("B1", "app/a.py", 1)])))
        # Python 3.14 parses this depth and the adapter refuses the value; 3.11 and 3.12 stop at
        # parsing. Either way the file is refused and nothing of it is stored.
        self.assertRegex(self.refused(plain.replace('"region": {"startLine": 1}', region)),
                         "not an integer|is not JSON")
        # where the tool's fingerprint stands in for the line, the line is not hashed either
        with_fp = json.dumps(log(run(results=[result("B1", "app/a.py", 1, partialFingerprints={"h": "x"})])))
        self.assertRegex(self.refused(with_fp.replace('"startLine": 1', '"startLine": ' + deep)),
                         "not an integer|is not JSON")
        for bad in ("14", 1.5, True, [3], {"line": 3}):
            for key in ("startLine", "startColumn"):
                res = result("B1", "app/a.py", 1)
                res["locations"][0]["physicalLocation"]["region"][key] = bad
                self.assertIn(f"region.{key} is a", self.refused(log(run(results=[res]))))
        self.assertEqual(self.gate()["verdict"], "not measured")
        res = result("B1", "app/a.py", 14)
        res["locations"][0]["physicalLocation"]["region"]["startColumn"] = 5
        self.assertEqual(self.ingest(log(run(results=[res])))["findings"][0]["location"],
                         {"uri": "app/a.py", "line": 14, "column": 5})
        self.assertTrue(self.p.ledger().verify().intact)

    def test_FR_H8_AC_1_text_the_store_or_the_ledger_cannot_hold_is_refused_or_escaped_never_a_crash(self) -> None:
        # a lone surrogate in a message the fingerprint does not hash: refused when the scan is stored
        lone = result("B1", "app/a.py", 1, fingerprints={"f": "x"}) | {"message": {"text": "bad \ud800 text"}}
        self.assertIn("cannot be stored", self.refused(log(run(results=[lone]))))
        # a lone surrogate in what a refusal repeats: the refusal is still recorded, with it escaped
        self.assertIn("not measured", self.refused(log(run(name="Ban\udc80dit"))))
        reasons = [r["event"]["payload"]["reason"] for r in self.p.ledger().of_kind("security_scan_refused")]
        self.assertIn("Ban\\udc80dit", reasons[-1])
        # a refusal that repeats a huge value records it cut, not the whole of it
        self.refused(log(run(results=[result("B1", "app/a.py", 1) | {"ruleId": list(range(100000))}])))
        reason = [r["event"]["payload"]["reason"] for r in self.p.ledger().of_kind("security_scan_refused")][-1]
        self.assertLessEqual(len(reason), sarif.REASON_CHARS)
        self.assertEqual(self.gate()["verdict"], "not measured")
        # a file name the file system gave as a lone surrogate: the scan names it escaped
        named = self.tmp / "scan-\udce4.sarif"
        try:
            named.write_text(json.dumps(log(run(results=[]))), encoding="utf-8")
        except (OSError, UnicodeError):
            self.skipTest("this file system does not hold such a name")
        scan = ingest(self.p, named)
        self.assertEqual(scan["file"], "scan-\\udce4.sarif")
        self.assertEqual(self.gate()["verdict"], "passed")
        self.assertTrue(self.p.ledger().verify().intact)

    def test_FR_H8_AC_1_a_file_over_the_size_cap_is_refused_before_it_is_read(self) -> None:
        with mock.patch.object(sarif, "MAX_BYTES", 64), self.assertRaises(SarifError):
            ingest(self.p, FIXTURES / "bandit.sarif")
        refusal = [r["event"]["payload"] for r in self.p.ledger().of_kind("security_scan_refused")][-1]
        size = (FIXTURES / "bandit.sarif").stat().st_size
        self.assertEqual((refusal["file"], refusal["bytes"]), ("bandit.sarif", size))
        self.assertEqual(self.gate()["verdict"], "not measured")


class ExpiryRecordTest(SarifCase):
    def test_FR_H8_AC_1_an_expired_acceptance_that_a_later_one_replaced_is_not_recorded_as_reopening(self) -> None:
        ingest(self.p, FIXTURES / "bandit.sarif")
        accept_risk(self.p, "SEC-1-1", person="Ilkka", persona="it", expires="2026-12-31", reason="behind the VPN")
        self.clock.advance(days=20)                                                  # 2026-12-12: extended
        accept_risk(self.p, "SEC-1-1", person="Ilkka", persona="it", expires="2027-06-30", reason="fix in Q2")
        accept_risk(self.p, "SEC-1-2", person="Ilkka", persona="it", expires="2026-12-20", reason="fixture")
        ingest(self.p, FIXTURES / "bandit.sarif")
        self.clock.advance(days=20)                                                  # 2027-01-01
        gate = security_gate(self.p)
        self.assertEqual((gate["verdict"], [a["id"] for a in gate["accepted"]]), ("passed", ["SEC-2-1"]))
        records = {tuple(r["event"]["payload"]["acceptances"]): r["event"]["payload"]["why"]
                   for r in self.p.ledger().of_kind("risk_acceptance_expired")}
        self.assertNotIn("open again", records[("RA-001",)])
        self.assertIn("replaced", records[("RA-001",)])
        self.assertIn("open again", records[("RA-003",)])                         # SEC-2-2 is open now
        ingest(self.p, FIXTURES / "bandit-clean.sarif")
        self.clock.advance(days=200)                                                 # RA-002 ends, nothing reports it
        security_gate(self.p)
        last = [r["event"]["payload"] for r in self.p.ledger().of_kind("risk_acceptance_expired")][-1]
        self.assertEqual((last["acceptances"], "no current scan" in last["why"]), (["RA-002"], True))


class SignedIngestTest(SarifCase):
    def test_FR_H8_AC_1_a_scan_handed_in_by_someone_is_signed_by_a_named_person_with_a_persona(self) -> None:
        for person, persona in (("assistant", "it"), ("Claude", "compliance"), ("  ", "it"), ("Kaisa", "hacker"),
                                ("Kaisa", None), (None, "it")):
            with self.assertRaises(DecisionRefused, msg=(person, persona)):
                ingest(self.p, FIXTURES / "bandit.sarif", person=person, persona=persona)
        self.assertEqual(list(self.p.ledger().of_kind("security_scan")), [])
        self.assertFalse(self.p.path("security", "1.json").exists())
        scan = ingest(self.p, FIXTURES / "bandit.sarif", person="Kaisa", persona="compliance")
        self.assertEqual(scan["ingested_by"], {"person": "Kaisa", "persona": "compliance"})
        self.assertIsNone(ingest(self.p, FIXTURES / "bandit.sarif")["ingested_by"])  # a pipeline signs nothing


if __name__ == "__main__":
    unittest.main()
