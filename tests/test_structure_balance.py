"""The two views agree on what is the project's own and what is Rihmasto's, and say it per item (FR-STR2).

A team's repository (tests/alignment_fixture.py) is attached: its specs and task lists were committed in January,
its code in March, so every planning file is weeks older than the code. What Rihmasto takes in from those files is
the project's own: it is neither development nor conformance to Rihmasto's structure, on the Alignment view and in
Where the work went alike. Lowering a convention is not conformance work. Every item says what it counts as and how
old its source is; the IDE text, the command line, the headline and the Assessment follow the levels; a business
owner who enforces a convention decides its card; Ask Rihma answers the owner's own words by rule. The tests drive
the real kernel, ledger and cockpit server; the repository is never written.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_structure_policy as policy_tests  # noqa: E402  (the module, so its tests are not collected here)
from test_structure_policy import AINO, DEV, Structured  # noqa: E402

from kernel import alignment_cli, assistant, structure_sides  # noqa: E402
from kernel import alignment_records as ar  # noqa: E402
from kernel import structure_policy as sp  # noqa: E402
from kernel import work_balance as wb  # noqa: E402
from kernel.canon import CARD_DECIDERS, Canon  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

OWNER = "Olli Owner"
JAN_TO_MAR = 55            # the task lists (2026-01-05) against the newest code (2026-03-01)


class Base(Structured):
    def ids(self, view: dict, gid: str) -> list[str]:
        return [i["id"] for i in self.group(view, gid)["items"]]

    def decide(self, ids: list[str], verdict: str = "accept") -> None:
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/repo-alignment/decide",
                                   {"items": ids, "verdict": verdict, "person": AINO, "persona": DEV})
        self.assertEqual(status, 200, out)

    def balance(self) -> dict:
        return wb.read(self.factory, pid=self.p.pid, window="all")


class SidesTest(Base):
    def test_FR_STR2_AC_1_records_taken_in_count_as_the_projects_own_in_both_views(self):
        view = self.scan()
        tasks = self.ids(view, "tasks")
        self.assertEqual(len(tasks), 5)
        self.assertTrue(all(i["counts_as"] == "take_in" for i in self.group(view, "tasks")["items"]))
        self.decide(tasks)
        out = self.balance()
        self.assertEqual(out["conformance"]["n"], 0, out["conformance"])       # not Rihmasto's structure
        self.assertEqual((out["taken_in"]["n"], out["taken_in"]["by"]), (5, {"records": 5}))
        self.assertIsNone(out["warning"])
        self.assertIn("5 records taken in from the project's own files", out["line"])
        self.assertNotIn("records taken in", out["conformance"]["said"])
        # a fact about the project's own files is the project's own too; a trace of a convention is conformance
        ci = next(i["id"] for i in self.group(view, "gaps")["items"] if i["kind"] == "ci_no_tests")
        trace = self.ids(view, "trace")[:1]
        self.decide([ci])
        self.decide(trace)
        out = self.balance()
        self.assertEqual(out["taken_in"]["by"], {"records": 5, "facts": 1})
        self.assertEqual(out["conformance"]["by"], {"traces": 1})
        # each decided item sits on the side the Alignment view gives it
        view = self.aligned()
        sides = {i["id"]: i["counts_as"] for g in view["groups"] for i in g["items"]}
        self.assertEqual({i["side"] for s in ("taken_in", "conformance") for i in out[s]["items"]},
                         {"take_in", "conform"})
        for iid in tasks + [ci]:
            self.assertEqual(sides[iid], structure_sides.side_of(ar.decisions(self.p)[iid]["item"]))
        self.assertEqual(sides[trace[0]], "convention")

    def test_FR_STR2_AC_2_lowering_a_convention_is_not_conformance_work(self):
        self.scan()
        self.put({"test_trace": "enforce"}, reason="try it")                       # raised: conformance
        card = Canon(self.p).cards(kind="structure")[0]
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/cards/{card['id']}/decide",
                                   {"verdict": "advise", "reason": "not now", "person": AINO, "persona": DEV})
        self.assertEqual(status, 200, out)                                          # lowered: neither
        self.put({"test_trace": "off"}, reason="named by feature")                  # lowered: neither
        self.put({"test_trace": "inherit"}, reason="back to the default")           # Off to Advise: neither
        out = self.balance()
        self.assertEqual((out["conformance"]["n"], out["conformance"]["by"]), (1, {"conventions": 1}),
                         out["conformance"]["items"])
        self.assertIn("set to Enforce", out["conformance"]["items"][0]["title"])
        self.put({"test_trace": "enforce"}, reason="again")
        card = Canon(self.p).cards(kind="structure", state="open")[0]
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/cards/{card['id']}/decide",
                                   {"verdict": "will_fix", "reason": "we rename them", "person": AINO, "persona": DEV})
        self.assertEqual(status, 200, out)
        out = self.balance()
        self.assertEqual(out["conformance"]["by"], {"conventions": 2, "cards": 1})

    def test_FR_STR2_AC_3_each_item_says_what_it_counts_as_and_how_old_its_source_is(self):
        view = self.scan()
        for i in self.group(view, "tasks")["items"]:
            self.assertEqual(i["counts_as"], "take_in")
            self.assertIn("neither development nor conformance", i["counts_as_said"])
            self.assertEqual((i["age"]["days"], i["age"]["older"]), (JAN_TO_MAR, True), i["age"])
            self.assertEqual((i["age"]["source_at"], i["age"]["code_at"]), ("2026-01-05", "2026-03-01"))
            self.assertIn(f"{JAN_TO_MAR} days before the newest code", i["age"]["said"])
        for i in self.group(view, "requirements")["items"]:
            self.assertTrue(i["age"]["older"])
        trace = self.group(view, "trace")["items"][0]
        self.assertEqual(trace["counts_as"], "convention")
        self.assertIn("conformance", trace["counts_as_said"])
        self.assertFalse(trace["age"]["older"])                                    # the test is as new as the code
        ci = next(i for i in self.group(view, "gaps")["items"] if i["kind"] == "ci_no_tests")
        self.assertEqual(ci["counts_as"], "fact")
        older = sum(1 for g in view["groups"] for i in g["items"]
                    if i["counts_as"] != "convention" and (i.get("age") or {}).get("older"))
        self.assertEqual(view["policy"]["older"], older)
        self.assertGreaterEqual(older, 24)
        self.assertIn("older than the newest code", view["policy"]["line"])


class LevelsFollowedTest(Base):
    def test_FR_STR2_AC_4_a_business_owner_who_enforces_a_convention_decides_its_card(self):
        self.assertEqual(set(CARD_DECIDERS["structure"]), set(sp.SETTERS))
        self.scan()
        status, out, _ = self.put({"test_trace": "enforce"}, reason="tests should name what they check",
                                  persona="business_owner", person=OWNER)
        self.assertEqual(status, 200, out)
        status, inbox, _ = self.call("GET", f"/api/projects/{self.p.pid}/inbox?persona=business_owner")
        self.assertEqual(status, 200, inbox)
        cards = [c for c in inbox["cards"] if c["kind"] == "structure"]
        self.assertEqual(len(cards), 1, inbox)
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/cards/{cards[0]['id']}/decide",
                                   {"verdict": "advise", "reason": "not worth it now", "person": OWNER,
                                    "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        self.assertEqual(sp.levels(self.factory, self.p)["test_trace"], "advise")

    def test_FR_STR2_AC_5_the_ide_text_and_the_command_line_follow_the_levels(self):
        view = self.scan()
        lines = "\n".join(ar.ide_lines(self.p))
        self.assertNotIn("traces to no requirement", lines)                        # advised: not asked of an agent
        self.assertNotIn("has no test", lines)
        self.assertIn("The CI does not run the tests", lines)                       # a fact stays
        self.assertIn("left out", lines)
        self.assertEqual(self.aligned()["ide"], ar.ide_lines(self.p))
        self.put({"test_trace": "enforce"}, reason="names matter")
        self.assertIn("traces to no requirement", "\n".join(ar.ide_lines(self.p)))
        self.put({"test_trace": "inherit"}, reason="back")
        # rihmasto align <pid> says what the cockpit says
        args = alignment_cli.argparse.Namespace(pid=self.p.pid, action=None, items=[], scan=False, drift=False,
                                                set=[], reason="", json=False)
        out = alignment_cli.align(self.factory, args)
        gaps = self.group(view, "gaps")
        self.assertEqual(self.group(out, "gaps")["open"], gaps["open"])
        text = alignment_cli.render(out)
        self.assertIn(f"Gaps (10, {gaps['open']} to decide, {gaps['suggested']} suggestions", text)
        self.assertIn(view["policy"]["line"], text)
        self.assertIn("suggestion", next(x for x in text.splitlines() if "traces to no requirement" in x))
        args.drift = True
        with redirect_stdout(io.StringIO()):
            self.assertIn("removed", alignment_cli.align(self.factory, args))

    def test_FR_STR2_AC_6_a_change_needs_a_reason_and_records_nothing_without_one(self):
        before = len(self.p.ledger().records())
        status, out, _ = self.put({"test_trace": "off"}, reason="  ")
        self.assertEqual(status, 400, out)
        self.assertIn("reason", out["error"])
        self.assertEqual(len(self.p.ledger().records()), before)
        self.assertFalse(self.p.path(sp.FILE).exists())
        status, out, _ = self.put({"test_trace": "off"}, reason="named by feature")
        self.assertEqual(status, 200, out)

    def test_FR_STR2_AC_7_the_count_found_stays_what_was_found_and_reads_well(self):
        view = self.scan()
        total = sum(len(g["items"]) for g in view["groups"])
        self.assertEqual(view["policy"]["found"], total)
        self.assertTrue(view["policy"]["line"].startswith(f"Of {total} items found, all open: 24 take in"),
                        view["policy"]["line"])
        tasks = self.ids(view, "tasks")
        self.decide(tasks)
        others = [i for g in ("requirements", "criteria", "decisions", "contracts") for i in self.ids(view, g)]
        self.decide(others[:-1])
        view = self.aligned()
        self.assertEqual(view["policy"]["found"], total)
        self.assertIn(f"Of {total} items found, ", view["policy"]["line"])
        self.assertIn("1 takes in the project's own", view["policy"]["line"])
        self.assertNotIn("1 take in", view["policy"]["line"])
        self.assertEqual(view["policy"]["open"], view["policy"]["split"]["take_in"] + view["policy"]["split"]["own"]
                         + view["policy"]["split"]["conform"])

    def test_FR_STR2_AC_8_the_headline_is_rihmastos_measure_only_where_it_is_enforced(self):
        view = self.scan()
        measure = view["summary"]["measure"]
        self.assertTrue(measure.startswith("5 of 6 tests trace to a criterion"))
        self.assertTrue(view["summary"]["text"].startswith("Taken in from the project's own files: 7 requirements, "
                                                           "9 criteria, 5 tasks, 2 decisions, 1 API contract"),
                        view["summary"]["text"])
        self.assertIn("Advise here", view["summary"]["text"])
        self.put({"test_trace": "off"}, reason="named by feature")
        self.assertIn("Off here", self.aligned()["summary"]["text"])
        self.put({"test_trace": "enforce"}, reason="names matter")
        self.assertEqual(self.aligned()["summary"]["text"], measure)

    def test_FR_STR2_AC_9_the_assessment_says_who_hid_a_finding_why_and_for_whom(self):
        checks = [{"id": "F-1", "key": "maintenance.docs", "verdict": "failed", "title": "No README"},
                  {"id": "F-2", "key": "maintenance.ownership", "verdict": "failed", "title": "No owners"}]
        sp.set_levels(self.factory, self.p, {"layout": "off"}, person=AINO, persona=DEV,
                      reason="we use our own docs folder")
        out = sp.follow_assessment(self.factory, self.p, {"latest": {"checks": [dict(c) for c in checks]},
                                                         "priority": []})
        hidden = out["structure"]["hidden"]
        self.assertEqual(len(hidden), 1)
        self.assertEqual((hidden[0]["n"], hidden[0]["label"]), (2, "Repository layout checks"))
        self.assertEqual(hidden[0]["why"], "Repository layout checks is Off for this project by Aino Example: we use "
                                           "our own docs folder")
        sp.set_levels(self.factory, self.p, {"layout": "inherit"}, person=AINO, persona=DEV, reason="back")
        sp.set_levels(self.factory, None, {"layout": "off"}, person=AINO, persona="it", kind="own",
                      reason="layouts vary")
        out = sp.follow_assessment(self.factory, self.p, {"latest": {"checks": [dict(c) for c in checks]},
                                                         "priority": []})
        self.assertIn("Off for all projects with their own structure by Aino Example: layouts vary",
                      out["structure"]["hidden"][0]["why"])
        self.assertIsNotNone(factory_project(self.factory))
        js = (Path(__file__).parents[1] / "cockpit" / "static" / "assessment.js").read_text(encoding="utf-8")
        self.assertIn("structure.hidden", js)
        self.assertNotIn("is Off for this project (Alignment", js)


class OwnersWordsTest(Base):
    ask = policy_tests.ChatTest.ask             # Ask Rihma inside the project, as FR-STR1's own tests ask

    def test_FR_STR2_AC_10_asking_about_a_convention_never_proposes_to_enforce_it(self):
        self.scan()
        for q in ("Show me the tests trace to requirements convention",
                  "Tell me about the tests trace to requirements convention",
                  "Explain the given/when/then criteria convention"):
            out = self.ask(q)
            self.assertEqual(out["propose"], [], q)
            self.assertEqual(out["by"], "rule", q)
            self.assertIn("Advise (Rihmasto's default)", out["answer"], q)
        out = self.ask("require the tests trace convention for this project")
        self.assertEqual(out["propose"][0]["args"]["levels"], {"test_trace": "enforce"})

    def test_FR_STR2_AC_11_the_owners_own_words_get_the_real_split_and_next_steps_by_rule(self):
        before = len(self.p.ledger().records())
        out = self.ask("Code plan highlights 124 to decide, how do I know what should I do with these results?")
        self.assertEqual((out["by"], out["matches"]), ("rule", ["structure_policy"]))
        self.assertIn("Read the code first", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.p.pid}/align", "control": "align_scan"})
        self.scan()
        before = len(self.p.ledger().records())
        for q in ("Code plan highlights 124 to decide, how do I know what should I do with these results?",
                  "are the tasks highlighted about enforcing rihmasto's own structure?"):
            out = self.ask(q)
            self.assertEqual((out["by"], out["matches"]), ("rule", ["structure_policy"]), q)
            self.assertIn("Of 39 items found", out["answer"], q)
            self.assertIn("5 tasks", out["answer"], q)
            self.assertIn("the project's own", out["answer"], q)
            self.assertIn("not Rihmasto's structure", out["answer"], q)
            routes = {(s.get("route"), s.get("control")) for s in out["steps"]}
            self.assertIn((f"#/p/{self.p.pid}/align", "align_bulk"), routes, out["steps"])
            self.assertIn((f"#/p/{self.p.pid}/align", "align_decide"), routes, out["steps"])
            self.assertTrue(any("older than the newest code" in s["text"] for s in out["steps"]), out["steps"])
            self.assertTrue(any("suggestions" in s["text"] and "nothing" in s["text"] for s in out["steps"]))
            self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/align")
        self.assertEqual(len(self.p.ledger().records()), before)                   # the assistant writes nothing
        out = assistant.ask(self.factory, "are the tasks highlighted about enforcing rihmasto's own structure?",
                            persona=DEV)
        self.assertEqual(out["by"], "rule")
        self.assertIn("Open a project", out["answer"])


if __name__ == "__main__":
    unittest.main()
