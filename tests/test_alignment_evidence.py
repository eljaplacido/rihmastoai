"""Origin, impact and triage that agree with the decisions and the project's own evidence (FR-ORG2,
docs/guides/alignment.md).

An independent check of FR-ORG1 found the triage's promises and the view disagreeing: a test counted against a
criterion the contract never took, gaps about rejected items still to decide, a plan the code still tests called old,
the owner's own questions missed by Ask Rihma, two numbers for "to decide", deferred items decided without a word,
suggestions that ignore what was rejected and a committed secret called a convention. The same team's repository as
tests/test_alignment_origin.py (tests/alignment_fixture.py: plans from January, code and tests from March) shows each
one fixed. The repository is never written.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_alignment import AINO, DEV, Aligned  # noqa: E402
from test_alignment_origin import items  # noqa: E402

from kernel import alignment_impact as imp  # noqa: E402
from kernel import alignment_origin as org  # noqa: E402
from kernel import alignment_records as ar  # noqa: E402
from kernel import alignment_triage as tri  # noqa: E402
from kernel import assistant  # noqa: E402
from kernel import assistant_ops as ops  # noqa: E402


def trace_to(view: dict, cid: str) -> dict:
    return next(i for i in items(view, "trace") if i["proposal"]["criterion_id"] == cid)


class Base(Aligned):
    def reject(self, *ids: str) -> None:
        ar.decide(self.p, list(ids), "reject", person=AINO, persona=DEV)

    def acts(self, view: dict) -> dict:
        return {a["do"]: a for a in view["triage"]["actions"]}


class CountedTest(Base):
    def test_FR_ORG2_AC_1_a_test_counts_only_once_its_criterion_is_in_the_contract(self):
        v = self.scan()
        traces = [i["id"] for i in items(v, "trace")]
        alone = imp.impact(self.p, traces, "accept")
        self.assertIn("5 tests not counted until", alone["said"])
        self.assertNotIn("become counted", alone["said"])
        self.assertEqual(alone["measured"]["after"]["tests_counted"], 0)
        us1 = trace_to(v, "US-1-AC-1")
        self.assertIn("counted once US-1-AC-1 is in the contract", us1["impact"])
        crit = self.by_title(v, "criteria", "US-1-AC-1")
        both = imp.impact(self.p, [crit["id"], us1["id"]], "accept")
        self.assertIn("1 test becomes counted when the gate runs it", both["said"])
        self.assertEqual(both["measured"]["after"]["tests_counted"], 1)
        # a trace to a criterion that was rejected: never offered by Accept from current sources, and named
        self.reject(self.by_title(v, "requirements", "FR-001")["id"])
        v = ar.view(self.p)
        fr1 = trace_to(v, "FR-001-AC-1")
        self.assertNotIn(fr1["id"], self.acts(v)["accept_current"]["items"])
        self.assertEqual(v["triage"]["dangling"], 1)
        self.assertIn("which you rejected", fr1["impact"])
        said = " ".join(a["text"] for a in v["triage"]["advice"])
        self.assertIn("1 test trace points to a criterion you rejected (FR-001-AC-1)", said)
        current = self.acts(v)["accept_current"]
        self.assertIn("4 tests become counted when the gate runs them", current["impact"])
        tri.act(self.p, "accept_current", person=AINO, persona=DEV)
        accepted = {k for k, d in ar.decisions(self.p).items() if d["verdict"] == "accept"}
        for t in ar.accepted(self.p, "trace"):
            self.assertIn(t["proposal"]["criterion"], accepted, t["title"])
        self.assertEqual(imp.Context(self.p).measured()["tests_counted"], 4)
        self.untouched()


class NumbersAgreeTest(Base):
    def test_FR_ORG2_AC_2_gaps_about_rejected_items_close_and_the_view_shows_one_number_to_decide(self):
        v = self.scan()
        fr3 = self.by_title(v, "requirements", "FR-003")
        promised = imp.impact(self.p, [fr3["id"]], "reject")
        self.assertIn("2 gaps about them close", promised["said"])
        self.reject(fr3["id"])
        v = ar.view(self.p)
        gap = self.by_title(v, "gaps", "FR-003 has no test")
        self.assertEqual((gap["status"], gap["closed_by"]), ("closed", ["FR-003"]))
        self.assertEqual(self.by_title(v, "gaps", "FR-003-AC-1 is not testable")["status"], "closed")
        still = sum(1 for i in items(v, "gaps") if i["status"] == "open")
        self.assertEqual(still, promised["measured"]["after"]["open_gaps"])
        self.assertEqual(still, imp.Context(self.p).measured()["open_gaps"])
        self.assertEqual(v["status"]["closed"], 2)
        self.assertEqual(next(g for g in v["groups"] if g["id"] == "gaps")["open"], still)
        # deferring lowers the one number to decide; the filters count the rows they show
        tri.act(self.p, "defer_convention", person=AINO, persona=DEV)
        v = ar.view(self.p)
        t = v["triage"]
        self.assertEqual(v["status"]["open"], t["to_decide"])
        self.assertEqual(v["status"]["deferred"], t["deferred"])
        self.assertGreater(t["deferred"], 0)
        rows = [(i["origin_tags"] + (" deferred" if i.get("deferred") else "")).split() for i in items(v)]
        for f in ("project", "old", "convention", "deferred"):
            self.assertEqual(t["filters"][f], sum(1 for r in rows if f in r), f)
        self.assertEqual(t["filters"]["all"], len(rows))
        self.assertGreater(t["filters"]["convention"], t["convention"])      # the deferred ones are shown, and counted
        self.untouched()


class EvidenceTest(Base):
    def test_FR_ORG2_AC_3_a_plan_the_current_tests_check_is_not_an_old_plan(self):
        v = self.scan()
        fr1 = self.by_title(v, "requirements", "FR-001")
        o = fr1["origin"]
        self.assertEqual((o["old"], o["days_behind"]), (False, 56))
        self.assertEqual(o["checked_by"], ["test_FR_001_lists_every_item_with_its_state"])
        self.assertIn("56 days older than the code's latest change, but current tests check it "
                      "(test_FR_001_lists_every_item_with_its_state): not an old plan", o["said"])
        self.assertEqual(fr1["origin_tags"], "project current")
        self.assertFalse(self.by_title(v, "requirements", "User Story 1")["origin"]["old"])
        self.assertFalse(self.by_title(v, "criteria", "US-1-AC-2")["origin"]["old"])    # its requirement is tested
        self.assertFalse(self.by_title(v, "tasks", "T003")["origin"]["old"])             # it serves US-1
        self.assertTrue(self.by_title(v, "requirements", "FR-002")["origin"]["old"])
        self.assertTrue(self.by_title(v, "tasks", "T001")["origin"]["old"])
        stale = self.acts(v)["reject_stale"]["items"]
        tested = [self.by_title(v, g, t)["id"] for g, t in (("requirements", "FR-001"), ("requirements", "User Story"),
                                                            ("criteria", "US-1-AC-1"), ("requirements", "Requirement 1"))]
        self.assertEqual([i for i in tested if i in stale], [])
        out = tri.act(self.p, "reject_stale", person=AINO, persona=DEV)
        rejected = set(out["items"])
        self.assertEqual([i for i in tested if i in rejected], [])
        self.assertIn(self.by_title(v, "requirements", "FR-002")["id"], rejected)
        self.untouched()


class AskTest(Base):
    QUESTIONS = [
        ("Do I just spend accepting changes that forces project to rihmasto structure or actually moving the needle "
         "with dev?", "align"),
        ("Are the tasks highlighted about enforcing rihmasto's own structure?", None),
        ("how much is rihmasto able to ingest existing structures of my project?", None),
        ("which of these are stale?", "align"),
        ("Which should I accept?", "align"),
        ("what happens if I accept all gaps?", "align"),
    ]

    def ask(self, q: str, view: str | None) -> dict:
        return assistant.ask(self.factory, q, persona=DEV, project_id=self.p.pid, view=view)

    def test_FR_ORG2_AC_4_the_owners_own_questions_are_answered_by_rule_and_proposals_say_what_they_take(self):
        self.scan()
        for q, view in self.QUESTIONS:
            out = self.ask(q, view)
            self.assertEqual(out["by"], "rule", q)
            self.assertIn("align_triage", out, q)
        needle = self.ask(self.QUESTIONS[0][0], "align")["answer"]
        self.assertTrue(needle.startswith("None of these decisions is development work"), needle[:120])
        self.assertIn("Development moves in Tasks and Changes", needle)
        whatif = self.ask("what happens if I accept all gaps?", "align")["answer"]
        self.assertTrue(whatif.startswith("If you accept the 10 open gaps: "), whatif[:120])
        self.assertIn("10 gaps kept open in the project's records", whatif)
        self.assertNotIn("align_triage", self.ask("What should I do with these?", "tasks"))
        # each proposal names the items it takes; confirming one after another acts on what is left and says so
        out = self.ask("What should I do with these?", "align")
        calls = {p["args"]["call"]["body"]["do"]: p["args"]["call"]["body"] for p in out["propose"]}
        stale = calls["reject_stale"]["items"]
        self.assertEqual(stale, self.acts(ar.view(self.p))["reject_stale"]["items"])
        tri.act(self.p, "defer_convention", person=AINO, persona=DEV, items=calls["defer_convention"]["items"])
        again = self.ask("What should I do with these?", "align")
        restore = next(p for p in again["propose"] if p["args"]["call"]["body"]["do"] == "restore")
        deferred = restore["args"]["call"]["body"]["items"]
        tri.act(self.p, "reject_stale", person=AINO, persona=DEV, items=stale)     # takes deferred criteria with them
        left = set(tri.deferred(self.p)) & {i["id"] for i in items(ar.view(self.p)) if i["status"] == "open"}
        back = tri.act(self.p, "restore", person=AINO, persona=DEV, items=deferred)
        self.assertEqual(set(back["items"]), left)
        self.assertEqual(len(back["skipped"]), len(deferred) - len(left))
        self.assertGreater(len(back["skipped"]), 0)
        self.assertIn(f"{len(back['skipped'])} of the {len(deferred)} proposed", back["said"])
        with self.assertRaises(ar.AlignRefused):                                 # all of it decided since
            tri.act(self.p, "reject_stale", person=AINO, persona=DEV, items=stale)
        self.assertIn("align_triage", ops.OPS)
        self.untouched()


class SaidBeforeTest(Base):
    def test_FR_ORG2_AC_5_the_impact_names_deferred_items_taken_along_the_origin_mix_and_real_risks(self):
        v = self.scan()
        t = v["triage"]
        advice = {a.get("about") or a["do"]: a["text"] for a in t["advice"]}
        self.assertTrue(advice["development"].startswith("None of these decisions is development work"))
        self.assertIn("The CI does not run the tests", advice["risk"])
        self.assertIn("FR-003-AC-1 is not testable as written", advice["risk"])
        self.assertNotIn("not work your project is missing", advice["defer_convention"])
        risky = {self.by_title(v, "gaps", "The CI does not run")["id"], self.by_title(v, "gaps", "FR-003-AC-1")["id"]}
        self.assertEqual(risky & set(self.acts(v)["defer_convention"]["items"]), set())
        self.assertEqual(t["risk"], 2)
        ci = self.by_title(v, "gaps", "The CI does not run")["origin"]
        self.assertIn("may be a real risk in your project", ci["said"])
        # bulk: the origin mix is said before anything
        tasks = [i["id"] for i in items(v, "tasks")]
        bulk = imp.impact(self.p, tasks, "accept")
        self.assertIn("2 of them may be from an old plan (specs/001-loan-items/tasks.md)", bulk["said"])
        # deferred items decided with their requirement are named, and so are the items taken with the ones asked
        tri.act(self.p, "defer_convention", person=AINO, persona=DEV)
        fr1 = self.by_title(v, "requirements", "FR-001")["id"]
        out = imp.impact(self.p, [fr1], "accept")
        self.assertIn("1 more item comes with them (FR-001-AC-1)", out["said"])
        self.assertIn("1 of these you had deferred (FR-001-AC-1): deciding now decides it too", out["said"])
        self.assertEqual(out["deferred_taken"], [self.by_title(v, "criteria", "FR-001-AC-1")["id"]])
        self.assertIn("you had deferred", self.acts(ar.view(self.p))["accept_current"]["impact"])
        self.untouched()


class SuggestAndFindingsTest(Base):
    def test_FR_ORG2_AC_6_suggestions_follow_decisions_and_findings_in_the_project_are_not_conventions(self):
        v = self.scan()
        sug = {s["kind"]: s for s in v["suggestions"]}
        self.assertIn("FR-003", sug["write_tests"]["text"])
        stale = sug["stale_spec"]["impact"]
        self.assertEqual(stale["files"], [".kiro/specs/overdue/requirements.md", "specs/001-loan-items/spec.md"])
        self.assertNotIn("new files of your choosing", stale["said"])
        self.assertEqual(sug["testable"]["impact"]["files"], ["specs/001-loan-items/spec.md"])
        self.reject(*[self.by_title(v, "requirements", r)["id"] for r in ("FR-002", "FR-003", "REQ-SEARCH")])
        v = ar.view(self.p)
        kinds = {s["kind"]: s for s in v["suggestions"]}
        self.assertNotIn("write_tests", kinds)                                  # every untested one was rejected
        self.assertNotIn("testable", kinds)
        entries = " ".join(s["text"] for s in v["suggestions"] if s["kind"] == "tasks_entry")
        for rid in ("FR-002", "FR-003", "REQ-SEARCH"):
            self.assertNotIn(rid, entries)
        secret = {"key": "security.secret:.env:4f9b2c7d", "title": "A secret is committed", "by": "rule",
                  "severity": "critical", "evidence": [{"file": ".env", "line": 1}]}
        o = org.of_finding(secret)
        self.assertEqual((o["kind"], o["label"]), ("found", "Found in your project"))
        self.assertTrue(o["said"].startswith("Found in your project: A secret is committed"), o["said"])
        self.assertNotIn("convention", o["said"])
        self.assertEqual(org.of_finding({"key": "maintenance.baseline", "title": "The tests pass", "by": "rule",
                                         "severity": "high"})["kind"], "found")
        self.assertEqual(org.of_finding({"key": "cicd.pipeline", "title": "A pipeline", "by": "rule",
                                         "severity": "high"})["kind"], "convention")
        self.assertEqual(org.finding_files({"evidence": ["C:/x/y.py:3: z", "src/a.py:12: b", "D:\\w\\v.py:1: c"]}),
                         ["C:/x/y.py", "D:\\w\\v.py", "src/a.py"])
        self.untouched()


if __name__ == "__main__":
    unittest.main()
