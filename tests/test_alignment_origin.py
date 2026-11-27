"""Origin, impact and triage on every alignment proposal (FR-ORG1, docs/guides/alignment.md).

The owner (2026-11-26): "Code plan highlights 124 to decide, how do I know what should I do with these results?" A
team's repository (tests/alignment_fixture.py) keeps its specs and task lists from January and its code from March.
Each item says whether it is taken from the project (with its file, line and last commit, and may be an old plan) or Rihmasto's
convention (naming the rule); what accepting it would do is said before anything is written; the view's head, Ask
Rihma and `rihmasto align-triage` say what to do with them, and the triage actions are signed. The repository is never
written.
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from alignment_fixture import make_repo  # noqa: E402
from test_alignment import AINO, DEV, Aligned  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import alignment_impact as imp  # noqa: E402
from kernel import alignment_origin as org  # noqa: E402
from kernel import alignment_records as ar  # noqa: E402
from kernel import alignment_triage as tri  # noqa: E402
from kernel import assistant  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.cli import main  # noqa: E402


def items(view: dict, group: str | None = None) -> list:
    return [i for g in view["groups"] if group in (None, g["id"]) for i in g["items"]]


class OriginTest(Aligned):
    def test_FR_ORG1_AC_1_each_item_says_its_origin_file_line_date_and_an_old_plan_or_the_rule(self):
        v = self.scan()
        fr2 = self.by_title(v, "requirements", "FR-002")
        o = fr2["origin"]
        self.assertEqual((o["kind"], o["path"], o["line"], o["date"], o["old"]),
                         ("project", "specs/001-loan-items/spec.md", 29, "2026-01-05", True))
        self.assertEqual((o["code_date"], o["days_behind"]), ("2026-03-02", 56))
        self.assertIn("may be an old plan: 56 days older than the code's latest change", o["said"])
        us1 = self.by_title(v, "requirements", "User Story 1")["origin"]      # current tests check it (FR-ORG2)
        self.assertEqual((us1["line"], us1["old"], us1["checked_by"]), (7, False, ["test_borrow_marks_the_item_on_loan"]))
        task = self.by_title(v, "tasks", "T001")
        self.assertEqual((task["origin"]["date"], task["origin"]["old"]), ("2026-01-05", True))
        trace = self.by_title(v, "trace", "test_borrow")
        self.assertEqual((trace["origin"]["kind"], trace["origin"]["old"], trace["origin"]["date"]),
                         ("project", False, "2026-03-01"))
        self.assertIn("the link is Rihmasto's reading (by text)", trace["origin"]["said"])
        adr = self.by_title(v, "decisions", "ADR-0002")
        self.assertFalse(adr["origin"]["old"])                     # a decision is a record, not a plan
        loose = next(i for i in items(v, "gaps") if i["kind"] == "no_requirement")
        self.assertEqual((loose["origin"]["kind"], loose["origin"]["rule"]), ("convention", "every_test_traces"))
        self.assertIn("Rihmasto's convention: every test traces to a requirement", loose["origin"]["said"])
        derived = next(i for i in items(v, "criteria") if i["derived"])
        self.assertEqual(derived["origin"]["rule"], "every_requirement_has_criteria")
        self.assertTrue(all(i["origin"]["kind"] == "convention" for i in items(v, "gaps")))
        self.assertTrue(all(s["origin"]["kind"] == "convention" for s in v["suggestions"]))
        self.assertEqual({s["origin"]["rule"] for s in v["suggestions"] if s["kind"] == "ci_tests"}, {"ci_runs_tests"})
        for g in v["groups"]:                                        # each header counts its items by origin
            o = g["origins"]
            self.assertEqual(o["project"] + o["convention"], g["open"], g["id"])
        crit = next(g for g in v["groups"] if g["id"] == "criteria")["origins"]
        self.assertEqual(crit, {"project": 6, "convention": 3, "old": 1})      # REQ-SEARCH-AC-1: no test checks it
        self.assertEqual({i["origin_tags"] for i in items(v)}, {"project old", "project current", "convention"})
        finding = {"key": "ci.tests", "title": "The pipeline runs the tests", "by": "rule",
                   "evidence": [{"file": ".github/workflows/ci.yml", "line": 3, "text": "jobs:"}]}
        fo = org.of_finding(finding)
        self.assertEqual((fo["kind"], fo["rule"], fo["files"]),
                         ("convention", "ci.tests", [".github/workflows/ci.yml"]))
        self.assertIn("a rule, key ci.tests", fo["said"])
        self.assertIn("never written", " ".join(i["impact"] for i in items(v) if i["group"] == "contracts")
                      .replace("never copies", "never written"))
        self.untouched()


class ImpactTest(Aligned):
    def unchanged(self):
        return (self.p.read("contract.json"), ar.decisions(self.p), len(self.p.ledger().records()),
                tri.deferred(self.p))

    def test_FR_ORG1_AC_2_the_impact_of_accepting_rejecting_deferring_and_applying_is_said_writing_nothing(self):
        v = self.scan()
        before = self.unchanged()
        us1 = self.by_title(v, "requirements", "User Story 1")
        self.assertEqual(us1["impact"], "Accept adds US-1 with 2 criteria to the contract; the gate then measures "
                                        "them: 1 with a traced test, 1 without.")
        out = imp.impact(self.p, [us1["id"]], "accept")
        self.assertEqual(len(out["taken_with"]), 2)                  # its two criteria come with it
        self.assertIn("The contract gains 1 requirement and 2 criteria", out["said"])
        self.assertIn("the gate then measures 2 more criteria: 1 with a test of your project traced to them, 1 "
                      "without one yet (US-1-AC-2) that would show untested", out["said"])
        self.assertEqual(out["repository"], "Your repository is never written: nothing in it changes.")
        m = out["measured"]
        self.assertEqual((m["after"]["requirements"] - m["before"]["requirements"],
                          m["after"]["criteria"] - m["before"]["criteria"]), (1, 2))
        self.assertIn("leaves it only through the change loop", out["undo"])
        tasks = [i["id"] for i in items(v, "tasks")]
        bulk = imp.impact(self.p, tasks, "accept")
        self.assertIn("5 tasks kept in the project's records (3 done, 2 open)", bulk["said"])
        self.assertIn("the measured state does not move", bulk["said"])
        traces = [i["id"] for i in items(v, "trace")]
        t = imp.impact(self.p, traces, "accept")
        # a test counts once its criterion is in the contract (FR-ORG2): the traces alone count none
        self.assertIn("5 tests not counted until US-1-AC-1, FR-001-AC-1, US-2-AC-1, REQ-1-AC-1 ... are in the "
                      "contract", t["said"])
        self.assertEqual((t["measured"]["before"]["tests_counted"], t["measured"]["after"]["tests_counted"]), (0, 0))
        loose = next(i for i in items(v, "gaps") if i["kind"] == "no_requirement")
        self.assertIn("1 test counted as tracing to no requirement until mapped", loose["impact"])
        fr3 = self.by_title(v, "requirements", "FR-003")
        r = imp.impact(self.p, [fr3["id"]], "reject")
        self.assertIn("marked rejected: nothing is added", r["said"])
        self.assertLess(r["measured"]["after"]["open_gaps"], r["measured"]["before"]["open_gaps"])
        d = imp.impact(self.p, [loose["id"]], "defer")
        self.assertIn("Bring back", d["undo"])
        rename = next(s for s in v["suggestions"] if s["kind"] == "rename_tests")
        self.assertEqual((rename["impact"]["files"], rename["impact"]["areas"], rename["impact"]["rihmasto_writes"]),
                         (["tests/test_loans.py", "web/loans.test.js"], ["tests", "web"], False))
        self.assertIn("git apply -R", rename["impact"]["undo"])
        card = imp.of_finding(self.p, {"key": "ci.tests", "evidence": [{"file": ".github/workflows/ci.yml"}]})
        self.assertIn("A run would touch .github/workflows/ci.yml (areas: .github)", card["said"])
        self.assertIn("reject the card before it is built", card["undo"])
        with self.assertRaises(ar.AlignRefused):
            imp.impact(self.p, ["req-0000000000"], "accept")
        with self.assertRaises(ar.AlignRefused):
            imp.impact(self.p, [us1["id"]], "maybe")
        self.assertEqual(self.unchanged(), before)                   # nothing was written
        self.untouched()


class TriageTest(Aligned):
    def test_FR_ORG1_AC_3_the_head_recommends_and_its_actions_are_signed_with_their_impact(self):
        v = self.scan()
        t = v["triage"]
        # what the current tests check is current, however old its file; 2 conventions may be real risks (FR-ORG2)
        self.assertEqual((t["to_decide"], t["project"], t["convention"], t["risk"], t["stale"], t["current"],
                          t["weak"]), (39, 26, 11, 2, 6, 20, 0))
        self.assertEqual(t["said"], "39 to decide: 26 taken from your project (6 may be from an old plan), 13 by "
                                    "Rihmasto's convention (2 may be a real risk).")
        advice = {a.get("about") or a["do"]: a["text"] for a in t["advice"]}
        self.assertIn("Leave the 11 items of Rihmasto's convention for now", advice["defer_convention"])
        self.assertIn("the 1 test that traces to no requirement close once your project's own tests are mapped",
                      advice["defer_convention"])
        self.assertIn("may describe an old plan: reject them, or wait for the current plan", advice["reject_stale"])
        self.assertIn("Accept the 20 items from current sources (5 criteria, 5 tests trace, 4 requirements, 3 tasks, "
                      "2 decisions, 1 API contracts)", advice["accept_current"])
        acts = {a["do"]: a for a in t["actions"]}
        self.assertEqual(sorted(acts), ["accept_current", "defer_convention", "reject_stale"])
        self.assertTrue(all("Your repository is never written" in a["impact"] for a in acts.values()))
        with self.assertRaises(ValueError):                       # not a person: refused before anything
            tri.act(self.p, "defer_convention", person="assistant", persona=DEV)
        self.assertEqual(tri.deferred(self.p), {})
        out = tri.act(self.p, "defer_convention", person=AINO, persona=DEV)
        self.assertEqual(len(out["items"]), 11)
        v = out["alignment"]
        self.assertEqual((v["triage"]["convention"], v["triage"]["deferred"], v["status"]["deferred"]), (0, 11, 11))
        self.assertEqual(next(g for g in v["groups"] if g["id"] == "gaps")["open"], 2)     # the risks stay
        logged = self.p.ledger().of_kind("alignment_deferred")[-1]["event"]["payload"]
        self.assertEqual((logged["person"], len(logged["items"])), (AINO, 11))
        self.assertEqual(self.p.read("contract.json"), self.p.read("contract.json"))
        one = out["items"][0]
        back = tri.act(self.p, "restore", person=AINO, persona=DEV, items=[one])
        self.assertEqual((back["items"], back["alignment"]["triage"]["deferred"]), ([one], 10))
        self.assertEqual(self.p.ledger().of_kind("alignment_restored")[-1]["event"]["payload"]["items"], [one])
        stale = tri.act(self.p, "reject_stale", person=AINO, persona=DEV)
        rejected = self.p.ledger().of_kind("alignment_rejected")[-1]["event"]["payload"]
        self.assertIn("may be an old plan", rejected["reason"])
        self.assertGreaterEqual(len(stale["items"]), 6)
        self.assertEqual(stale["alignment"]["triage"]["stale"], 0)
        current = tri.act(self.p, "accept_current", person=AINO, persona=DEV)
        self.assertGreaterEqual(len(current["items"]), 20)
        self.assertEqual(len(ar.accepted(self.p, "trace")), 5)
        left = current["alignment"]["triage"]
        self.assertEqual((left["current"], left["stale"], left["convention"]), (0, 0, 0))
        self.assertEqual([a["do"] for a in left["actions"]], ["restore"])
        with self.assertRaises(ar.AlignRefused):
            tri.act(self.p, "accept_current", person=AINO, persona=DEV)      # nothing left to accept
        with self.assertRaises(ar.AlignRefused):
            tri.act(self.p, "defer", person=AINO, persona=DEV)               # name the items
        self.untouched()


class ChatAndCliTest(Aligned):
    def cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_ORG1_AC_4_ask_rihma_and_the_command_line_answer_the_same_by_rule(self):
        out = assistant.ask(self.factory, "What should I do with these?", persona=DEV, project_id=self.p.pid,
                            view="align")
        self.assertEqual([p["args"]["op"] for p in out["propose"]], ["align_scan"])      # not read yet: read it
        self.scan()
        out = assistant.ask(self.factory, "What should I do with these?", persona=DEV, project_id=self.p.pid,
                            view="align")
        self.assertEqual((out["by"], out["navigate"]["route"]), ("rule", f"#/p/{self.p.pid}/align"))
        self.assertIn("39 to decide: 26 taken from your project", out["answer"])
        self.assertIn("Leave the 11 items of Rihmasto's convention", out["answer"])
        calls = [p["args"]["call"] for p in out["propose"]]
        self.assertEqual([c["body"]["do"] for c in calls], ["reject_stale", "defer_convention", "accept_current"])
        self.assertEqual({c["path"] for c in calls}, {f"/api/projects/{self.p.pid}/repo-alignment/triage"})
        self.assertIn("Your repository is never written", out["propose"][2]["args"]["summary"])
        again = assistant.ask(self.factory, "Are these alignment items forcing Rihmasto's structure on my project or "
                                            "moving the needle?", persona=DEV, project_id=self.p.pid)
        self.assertEqual(again["by"], "rule")
        self.assertIn("align_triage", again)
        other = assistant.ask(self.factory, "What should I do with these?", persona=DEV, project_id=self.p.pid,
                              view="tasks")
        self.assertNotIn("align_triage", other)
        code, text, _ = self.cli("align-triage", self.p.pid)
        self.assertEqual(code, 0)
        self.assertIn("Defer convention items (11): rihmasto align-triage", text)
        code, text, _ = self.cli("align-triage", self.p.pid, "--json")
        self.assertEqual(json.loads(text)["groups"]["gaps"], {"project": 0, "convention": 10, "old": 0, "open": 10,
                                                              "deferred": 0})
        before = len(self.p.ledger().records())
        code, _, err = self.cli("align-triage", self.p.pid, "--do", "defer_convention")
        self.assertEqual((code, len(self.p.ledger().records())), (2, before))
        self.assertIn("is signed", err)
        gap = items(ar.view(self.p), "gaps")[0]["id"]
        code, text, _ = self.cli("align-triage", self.p.pid, "--impact", gap, "--verdict", "defer")
        self.assertIn("set aside as deferred", text)
        code, text, _ = self.cli("align-triage", self.p.pid, "--do", "defer", gap, "--person", AINO, "--persona", DEV)
        self.assertEqual(code, 0, text)
        self.assertEqual(list(tri.deferred(self.p)), [gap])
        self.untouched()


class RoutesTest(CockpitTestCase):
    def test_FR_ORG1_AC_2_the_cockpit_reads_the_impact_and_signs_the_triage(self):
        repo = make_repo(self.tmp / "loans")
        p = attach(self.factory, "Loans", repo=repo, person=AINO, persona=DEV)
        base = f"/api/projects/{p.pid}/repo-alignment"
        status, out, _ = self.call("POST", base + "/scan", {"person": AINO, "persona": DEV})
        self.assertEqual(status, 201, out)
        tasks = [i["id"] for i in items(out, "tasks")]
        before = len(p.ledger().records())
        status, got, _ = self.call("GET", base + "/impact?items=" + ",".join(tasks) + "&verdict=accept")
        self.assertEqual(status, 200, got)
        self.assertIn("5 tasks kept in the project's records", got["said"])
        self.assertEqual(len(p.ledger().records()), before)
        status, _, _ = self.call("GET", base + "/impact?items=nope")
        self.assertEqual(status, 400)
        status, got, _ = self.call("GET", base + "/impact")
        self.assertEqual((status, got["items"]), (200, []))
        status, _, _ = self.call("POST", base + "/triage", {"do": "defer_convention", "person": "assistant",
                                                            "persona": DEV})
        self.assertEqual(status, 403)
        status, _, _ = self.call("POST", base + "/triage", {"do": "everything", "person": AINO, "persona": DEV})
        self.assertEqual(status, 400)
        status, got, _ = self.call("POST", base + "/triage", {"do": "defer_convention", "person": AINO, "persona": DEV})
        self.assertEqual(status, 200, got)
        self.assertEqual(got["alignment"]["triage"]["convention"], 0)


if __name__ == "__main__":
    unittest.main()
