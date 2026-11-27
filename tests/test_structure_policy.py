"""Rihmasto's structure per project and where the work went (FR-STR1).

A team's repository (tests/alignment_fixture.py) is attached: it keeps its own specs, tests, tasks, decisions and API
contracts. Rihmasto takes that structure as given: each of its own conventions only advises there until a person
chooses otherwise. The tests drive the real kernel, the real ledger and the real cockpit server; the repository is
never written.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from alignment_fixture import git, make_repo  # noqa: E402
from structure_fakes import recent_work  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from cockpit.solo_routes import NEEDS  # noqa: E402
from kernel import assistant, parity  # noqa: E402
from kernel import structure_cards as sc  # noqa: E402
from kernel import structure_policy as sp  # noqa: E402
from kernel import work_balance as wb  # noqa: E402
from kernel.assistant_rules import CONTROL_PAGES, ui_map  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

AINO, DEV = "Aino Example", "developer"


class Structured(CockpitTestCase):
    def setUp(self):
        super().setUp()
        if shutil.which("git") is None:
            self.skipTest("git is needed for the repository")
        self.repo = make_repo(self.tmp / "loans")
        self.p = attach(self.factory, "Tool loans", repo=self.repo, person=AINO, persona=DEV)
        self.head = git(self.repo, "rev-parse", "HEAD")

    def scan(self) -> dict:
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/repo-alignment/scan",
                                   {"person": AINO, "persona": DEV})
        self.assertEqual(status, 201, out)
        return out

    def aligned(self) -> dict:
        status, out, _ = self.call("GET", f"/api/projects/{self.p.pid}/repo-alignment")
        self.assertEqual(status, 200, out)
        return out

    @staticmethod
    def group(view: dict, gid: str) -> dict:
        return next(g for g in view["groups"] if g["id"] == gid)

    def put(self, levels: dict, reason: str = "", persona: str = DEV, person: str = AINO):
        return self.call("PUT", f"/api/projects/{self.p.pid}/structure",
                         {"levels": levels, "reason": reason, "person": person, "persona": persona})

    def untouched(self) -> None:
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)
        self.assertEqual(git(self.repo, "status", "--porcelain", "--untracked-files=all"), "")


class PolicyTest(Structured):
    def test_FR_STR1_AC_1_each_convention_has_a_level_its_scope_the_platforms_beside_it_and_a_signed_reason(self):
        status, out, _ = self.call("GET", f"/api/projects/{self.p.pid}/structure")
        self.assertEqual(status, 200, out)
        self.assertEqual([r["id"] for r in out["rows"]], list(sp.CONVENTIONS))
        self.assertEqual(len(out["rows"]), 7)
        self.assertEqual({(r["level"], r["scope"]) for r in out["rows"]}, {("advise", "default")})   # taken as given
        built = self.new()
        self.assertEqual(set(sp.levels(self.factory, built).values()), {"enforce"})                 # Rihmasto's own
        # the preview says what moves and records nothing
        before = len(self.p.ledger().records())
        status, seen, _ = self.call("POST", "/api/structure/preview", {"project": self.p.pid, "levels": {
            "test_trace": "off"}, "person": AINO, "persona": DEV})
        self.assertEqual(status, 200, seen)
        self.assertEqual((seen["changes"][0]["from"], seen["changes"][0]["to"]), ("advise", "off"))
        self.assertIn("Tests trace to requirements: Advise to Off for this project", seen["lines"][0])
        self.assertEqual(len(self.p.ledger().records()), before)
        self.assertFalse(self.p.path(sp.FILE).exists())
        # a person outside the setters, or no person, is refused and nothing is recorded
        status, out, _ = self.put({"test_trace": "off"}, persona="operations")
        self.assertEqual(status, 403, out)
        status, out, _ = self.put({"test_trace": "off"}, person="assistant")
        self.assertEqual(status, 403, out)
        with self.assertRaises(DecisionRefused):
            sp.set_levels(self.factory, self.p, {"test_trace": "off"}, person=AINO, persona="end_user")
        self.assertEqual(len(self.p.ledger().records()), before)
        # a signed change, with its reason, in the project's ledger
        status, out, _ = self.put({"test_trace": "off"}, reason="our tests are named by feature")
        self.assertEqual(status, 200, out)
        row = next(r for r in out["rows"] if r["id"] == "test_trace")
        self.assertEqual((row["level"], row["scope"], row["platform"]["level"]), ("off", "project", "advise"))
        self.assertEqual((row["why"]["person"], row["why"]["reason"]), (AINO, "our tests are named by feature"))
        logged = self.p.ledger().of_kind("structure_set")[-1]["event"]["payload"]
        self.assertEqual((logged["person"], logged["reason"], logged["changes"][0]["to"]),
                         (AINO, "our tests are named by feature", "off"))
        # the platform's level for projects with their own structure, beside the project's own
        status, out, _ = self.call("PUT", "/api/structure", {"levels": {"criteria": "enforce"}, "kind": "own",
                                                             "reason": "criteria pay off", "person": AINO,
                                                             "persona": "it"})
        self.assertEqual(status, 200, out)
        self.assertEqual(factory_project(self.factory).ledger().of_kind("structure_set")[-1]["event"]["payload"]
                         ["kind"], "own")
        crit = next(r for r in sp.describe(self.factory, self.p)["rows"] if r["id"] == "criteria")
        self.assertEqual((crit["level"], crit["scope"]), ("enforce", "platform"))
        status, out, _ = self.call("GET", "/api/structure")
        self.assertEqual(next(r for r in out["kinds"]["own"] if r["id"] == "criteria")["scope"], "platform")
        self.assertEqual(next(r for r in out["kinds"]["built"] if r["id"] == "criteria")["level"], "enforce")
        # inherit gives the convention back to all projects
        status, out, _ = self.put({"test_trace": "inherit"}, reason="back to the default")
        self.assertEqual(next(r for r in out["rows"] if r["id"] == "test_trace")["scope"], "default")
        status, out, _ = self.put({"test_trace": "loud"})
        self.assertEqual(status, 400, out)
        self.untouched()

    def test_FR_STR1_AC_2_the_alignment_follows_the_levels_and_says_what_is_taken_in_and_what_is_left(self):
        out = self.scan()
        policy = out["policy"]
        self.assertEqual(policy["kind"], "own")
        self.assertGreater(policy["split"]["take_in"], 0)
        self.assertGreater(policy["split"]["conform"], 0)
        self.assertEqual(policy["by_level"]["advise"], policy["split"]["conform"])        # all advised by default
        self.assertEqual(policy["to_decide"], policy["split"]["take_in"] + policy["split"]["own"])
        self.assertIn("yours to decide", policy["line"])
        self.assertEqual(out["status"]["open"] + out["status"]["changed"], policy["to_decide"])   # the chips agree
        trace = self.group(out, "trace")
        self.assertTrue(trace["items"] and all(i["folded"] and i["level"] == "advise" for i in trace["items"]))
        self.assertEqual((trace["open"], trace["suggested"]), (0, len(trace["items"])))
        tasks = self.group(out, "tasks")
        self.assertEqual(tasks["open"], len(tasks["items"]))                     # the team's own tasks: theirs
        # Off: the items leave the view, a count stays with why
        self.put({"test_trace": "off"}, reason="tests are named by feature")
        view = self.aligned()
        trace = self.group(view, "trace")
        self.assertEqual(trace["items"], [])
        self.assertEqual(trace["hidden"]["n"], 5)
        self.assertIn("tests are named by feature", trace["hidden"]["why"])
        self.assertIn(AINO, trace["hidden"]["why"])
        self.assertFalse(any(i.get("kind") == "no_requirement" for i in self.group(view, "gaps")["items"]))
        # Enforce: counted, one card in the Inbox, named at the repo gate
        before = view["policy"]["to_decide"]
        status, out, _ = self.put({"criteria": "enforce"}, reason="criteria pay off here")
        self.assertEqual(out["cards"]["opened"], [c["id"] for c in Canon(self.p).cards(kind="structure")])
        card = Canon(self.p).cards(kind="structure")[0]
        self.assertEqual((card["refs"]["structure"], card["payload"]["count"]), ("criteria", 3))
        self.assertEqual(self.aligned()["policy"]["to_decide"], before + 3)
        self.assertEqual(sp.gate_part(self.factory, self.p)["enforced"][0]["open"], 3)
        self.assertEqual(sc.sync(self.factory, self.p), {"opened": [], "withdrawn": []})       # the same: kept
        # Advise instead on the card: the convention becomes a suggestion, signed
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/cards/{card['id']}/decide",
                                   {"verdict": "advise", "reason": "not now", "person": AINO, "persona": DEV})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["structure"]["level"], "advise")
        self.assertEqual(sp.levels(self.factory, self.p)["criteria"], "advise")
        self.assertIsNone(sp.gate_part(self.factory, self.p))
        self.assertEqual(self.p.ledger().of_kind("structure_set")[-1]["event"]["payload"]["reason"], "not now")
        # enforced again, then off: the open card is withdrawn
        self.put({"criteria": "enforce"}, reason="again")
        self.assertEqual(len(Canon(self.p).cards(kind="structure")), 1)
        self.put({"criteria": "off"}, reason="out of the way")
        self.assertEqual(Canon(self.p).cards(kind="structure"), [])
        self.untouched()

    def test_FR_STR1_AC_2_assessment_findings_of_a_convention_follow_its_level(self):
        checks = [{"id": "F-1", "key": "maintenance.docs", "verdict": "failed", "title": "No README"},
                  {"id": "F-2", "key": "cicd.pipeline", "verdict": "failed", "title": "No pipeline"},
                  {"id": "F-3", "key": "compliance.audit_trail", "verdict": "failed", "title": "No audit trail"}]
        view = {"latest": {"checks": [dict(c) for c in checks]},
                "priority": [{"id": "F-1"}, {"id": "F-2"}, {"id": "F-3"}]}
        out = sp.follow_assessment(self.factory, self.p, view)
        marked = {c["id"]: (c.get("structure") or {}).get("level") for c in out["latest"]["checks"]}
        self.assertEqual(marked, {"F-1": "advise", "F-2": None, "F-3": "advise"})
        self.assertEqual([(p["id"], p.get("advised")) for p in out["priority"]],    # a suggestion is not put first
                         [("F-2", None), ("F-1", True), ("F-3", True)])
        sp.set_levels(self.factory, self.p, {"layout": "enforce"}, person=AINO, persona=DEV, reason="README matters")
        out = sp.follow_assessment(self.factory, self.p, {"latest": {"checks": [dict(c) for c in checks]},
                                                         "priority": [{"id": "F-1"}, {"id": "F-2"}]})
        self.assertEqual([p["id"] for p in out["priority"]], ["F-1", "F-2"])
        self.assertEqual(out["structure"]["counts"], {"off": 0, "advise": 1, "enforce": 1})


class WorkBalanceTest(Structured):
    def test_FR_STR1_AC_3_where_the_work_went_counts_development_and_conformance_with_the_items_behind(self):
        status, out, _ = self.call("GET", f"/api/work-balance?project={self.p.pid}")
        self.assertEqual(status, 200, out)
        self.assertFalse(out["measured"])
        self.assertIn("Nothing moved development", out["line"])
        recent_work(self.repo)                                      # code and a test, two days ago
        self.scan()
        view = self.aligned()
        gaps = [i["id"] for i in self.group(view, "gaps")["items"] if i.get("folded")]
        trace = [i["id"] for i in self.group(view, "trace")["items"]]
        for ids in (trace, gaps):
            status, done, _ = self.call("POST", f"/api/projects/{self.p.pid}/repo-alignment/decide",
                                        {"items": ids, "verdict": "accept", "person": AINO, "persona": DEV})
            self.assertEqual(status, 200, done)
        self.put({"test_trace": "enforce"}, reason="try it")
        out = wb.read(self.factory, pid=self.p.pid, window="30d")
        self.assertEqual(out["development"]["n"], 1)
        self.assertEqual(out["development"]["by"], {"code": 1})
        self.assertIn("Flag overdue loans", out["development"]["items"][0]["title"])
        self.assertEqual(out["conformance"]["n"], len(trace) + len(gaps) + 1)
        self.assertEqual(out["conformance"]["by"], {"traces": len(trace) + len(gaps), "conventions": 1})
        self.assertTrue(all(i["href"].startswith(f"#/p/{self.p.pid}/") for i in out["conformance"]["items"]))
        self.assertIn("moved development (1 code change)", out["line"])
        self.assertIn("Conformance work dominates", out["warning"])
        controls = [s["control"] for s in out["suggestions"]]
        self.assertEqual(controls, ["structure_policy", "align_scan"])
        self.assertIn("Tests trace to requirements", out["suggestions"][0]["text"])
        # across projects, and the route's refusals
        status, every, _ = self.call("GET", "/api/work-balance?window=all")
        self.assertEqual((status, every["scope"]), (200, "factory"))
        self.assertTrue(next(r for r in every["projects"] if r["project"] == self.p.pid)["warning"])
        self.assertEqual(self.call("GET", "/api/work-balance?project=no-such-project")[0], 404)
        self.assertEqual(self.call("GET", f"/api/work-balance?project={self.p.pid}&window=1y")[0], 400)
        # a period before the change counts nothing of it
        self.assertEqual(wb.read(self.factory, pid=self.p.pid, window="7d")["development"]["n"], 1)
        self.clock.advance(days=40)
        self.assertFalse(wb.read(self.factory, pid=self.p.pid, window="30d")["measured"])

    def test_FR_STR1_AC_3_a_built_projects_merges_and_decisions_move_development(self):
        b = self.new()
        b.log("merged", {"task": "T-001", "revision": "abc", "warranted": "passed"})
        b.log("gate", {"task": "T-002", "verdict": "passed"})
        b.log("change_applied", {"card": "C-0002", "class": "defect"})
        b.log("decision", {"card": "C-0003", "kind": "change", "verdict": "accept"})
        b.log("decision", {"card": "C-0004", "kind": "question", "verdict": "answer"})   # in neither bar
        out = wb.read(self.factory, pid=b.pid)
        self.assertEqual(out["development"]["by"], {"code": 1, "tests": 1, "fix": 1, "decision": 1})
        self.assertEqual(out["conformance"]["n"], 0)
        self.assertIsNone(out["warning"])


class ChatTest(Structured):
    def ask(self, question: str, persona: str = DEV) -> dict:
        return assistant.ask(self.factory, question, persona=persona, project_id=self.p.pid)

    def test_FR_STR1_AC_4_ask_rihma_answers_the_balance_and_proposes_a_level_change_by_rule(self):
        self.scan()
        before = len(self.p.ledger().records())
        out = self.ask("Am I just conforming to Rihmasto or moving development?")
        self.assertEqual((out["by"], out["matches"]), ("rule", ["structure_policy"]))
        self.assertIn("conformed to Rihmasto's structure", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.p.pid}/overview", "control": "work_balance"})
        self.assertTrue(out["steps"])
        out = self.ask("turn off the test-trace convention for this project")
        self.assertEqual(len(out["propose"]), 1)
        prop = out["propose"][0]
        self.assertEqual((prop["action"], prop["project"], prop["args"]["levels"]),
                         ("structure_set", self.p.pid, {"test_trace": "off"}))
        self.assertIn("turn off the test-trace convention", prop["args"]["reason"])
        self.assertIn("Advise to Off", out["answer"])
        self.assertEqual(out["navigate"]["control"], "structure_policy")
        out = self.ask("make the given/when/then criteria convention advise only because the specs are old")
        self.assertEqual(out["propose"], [])                                  # already Advise: nothing to change
        self.assertIn("already how", out["answer"])
        out = self.ask("enforce the decision records convention here because ADRs matter")
        self.assertEqual(out["propose"][0]["args"], {"project": self.p.pid, "levels": {"decisions": "enforce"},
                                                     "reason": "ADRs matter"})
        out = self.ask("turn off the test-trace convention for this project", persona="operations")
        self.assertEqual(out["propose"], [])
        self.assertIn("sets it", out["answer"])
        out = self.ask("Which of Rihmasto's conventions apply here?")
        self.assertIn("Tests trace to requirements: Advise (Rihmasto's default)", out["answer"])
        self.assertEqual(len(self.p.ledger().records()), before)              # the assistant writes nothing
        # the confirmed proposal is the same signed route a Save calls
        status, saved, _ = self.call("PUT", f"/api/projects/{self.p.pid}/structure",
                                     {"levels": {"test_trace": "off"}, "reason": prop["args"]["reason"],
                                      "person": AINO, "persona": DEV})
        self.assertEqual((status, saved["changed"]), (200, True))


class WiringTest(unittest.TestCase):
    def test_FR_STR1_AC_5_routes_personas_controls_and_chat_paths_are_in_the_tables(self):
        names = {name for _, _, name in cockpit.ROUTES}
        for name in ("get_structure", "put_structure", "post_structure_preview", "get_project_structure",
                     "put_project_structure", "get_work_balance"):
            self.assertIn(name, names)
        for name in ("put_structure", "put_project_structure", "post_structure_preview"):
            self.assertIn(name, NEEDS)
        controls = {c["id"] for c in ui_map()["controls"]}
        for cid in ("structure_policy", "structure_preview", "work_balance"):
            self.assertIn(cid, controls)
            self.assertIn(cid, CONTROL_PAGES)
        self.assertEqual(parity.CHAT["structure_policy"], ("chat", "kernel.structure_chat:answer"))
        self.assertLessEqual({"structure_preview", "work_balance"}, parity.READS)
        static = Path(cockpit.__file__).parent / "static"
        js = "".join((static / f).read_text(encoding="utf-8") for f in ("structure.js", "workbalance.js"))
        for cid in ("structure_policy", "structure_preview", "work_balance"):
            self.assertIn(f'"{cid}"', js)


if __name__ == "__main__":
    unittest.main()
