"""Live progress for long jobs (FR-PRG1): kernel/progress.py and what reports through it.

A real assessment of the poor fixture repository (tests/fixtures/assess) with a scripted panel model reports its
plan and every step; the estimates come from earlier runs timed on a scripted clock; a cancel stops a run whose
panel model waits on the test; the cockpit's progress route answers with what changed since a cursor; an
adoption's lines and a folder scan's counters map onto their plans; and Ask Rihma answers "how is the
assessment going?" from the progress. No scanner from PATH, no real model.
"""

import json
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_assess import fixture_repo, mirrored, no_scanner, panel_script  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import assess, progress, progress_chat, progress_jobs  # noqa: E402
from kernel.assess_progress import PANEL_LABELS  # noqa: E402
from kernel.assess_repo import PERSPECTIVES  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.model import FakeModel  # noqa: E402

SIGNER = {"person": "Aino", "persona": "developer"}


class Ticks:
    """A clock the test moves: each read is where it was set."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def named(name: str):
    class Named(FakeModel):
        pass

    model = Named(panel_script)
    model.name = name
    return model


class AssessmentProgressTest(FactoryTestCase):
    def test_FR_PRG1_AC_1_a_real_assessment_reports_its_plan_each_step_and_the_findings_so_far_without_changing_its_result(self):
        src = fixture_repo("poor", self.tmp / "src")
        plain = assess.assess(mirrored(self.factory, "Plain", src), person="Aino", persona="developer",
                              model=named("qwen3.6-35b"), which=no_scanner)
        rep = progress.Reporter("assessment", "Assessing Orders")
        record = assess.assess(mirrored(self.factory, "Orders", src), person="Aino", persona="developer",
                               model=named("qwen3.6-35b"), which=no_scanner, progress=rep)
        self.assertEqual(record["checks"], plain["checks"])                  # the progress changes nothing
        self.assertEqual(record["proposals"], plain["proposals"])
        view = rep.since(0)
        self.assertEqual([(g["id"], g["label"]) for g in view["plan"]],
                         [("read", "Reading the code"), ("rules", "Rule checks"), ("panel", "The panel"),
                          ("record", "The record")])
        plan = {g["id"]: g["steps"] for g in view["plan"]}
        self.assertEqual(plan["read"], ["read.mirror", "read.inventory"])
        self.assertEqual(plan["rules"], [f"rules.{p}" for p in PERSPECTIVES] + ["rules.redteam"])
        self.assertEqual(plan["panel"], [f"panel.{p}" for p in PANEL_LABELS])
        steps = view["steps"]
        self.assertEqual({steps[s]["by"] for s in plan["panel"]}, {"qwen3.6-35b"})
        self.assertEqual(steps["panel.it_security"]["label"], "IT and security")
        # each step started, then ended, in the plan's order; the operations perspective's model gave no JSON
        order = [e["step"] for e in view["events"] if e["kind"] == "started"]
        self.assertEqual(order, [s for g in view["plan"] for s in g["steps"]])
        self.assertEqual(steps["panel.operations"]["state"], "failed")
        self.assertIn("not measured", steps["panel.operations"]["why"])
        self.assertEqual({s["state"] for k, s in steps.items() if k != "panel.operations"}, {"done"})
        said = [e["state"]["said"] for e in view["events"] if e["kind"] == "started" and e["step"] == "panel.it_security"]
        self.assertEqual(said, ["The IT and security perspective is reading the inventory and the rules' results "
                                "with qwen3.6-35b"])
        # the counts by area are the record's verdicts, and the findings so far are the record's findings
        for p in PERSPECTIVES:
            mine = [c for c in record["checks"] if c["perspective"] == p and not c["key"].startswith(f"{p}.RT-")
                    and c["key"] != "security.scan_coverage"]
            if p != "security":
                self.assertEqual(steps[f"rules.{p}"]["counts"]["findings"],
                                 sum(1 for c in mine if c["verdict"] == "failed"), p)
        found = sorted(f["key"] for sid in plan["rules"] for f in view["findings"].get(sid, []))
        self.assertEqual(found, sorted(c["key"] for c in record["checks"] if c["verdict"] == "failed"))
        proposed = [f["title"] for sid in plan["panel"] for f in view["findings"].get(sid, [])]
        self.assertEqual(proposed, [p["title"] for p in record["proposals"]])
        self.assertEqual(steps["panel.it_security"]["counts"], {"proposed": 1, "dropped": 1})
        self.assertEqual((view["state"], view["result"]["id"], view["steps_done"], view["steps_total"]),
                         ("done", record["id"], 14, 14))
        self.assertEqual(view["now"], "Finished.")

    def test_FR_PRG1_AC_1_without_a_model_the_plan_has_no_panel_and_a_refusal_before_the_first_step_ends_it_failed(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        rep = progress.Reporter("assessment")
        assess.assess(project, person="Aino", persona="developer", which=no_scanner, progress=rep)
        self.assertEqual([g["id"] for g in rep.since(0)["plan"]], ["read", "rules", "record"])
        empty = self.factory.new_project("Nothing yet")
        rep2 = progress.Reporter("assessment")
        with self.assertRaises(Exception):
            assess.assess(empty, person="Aino", persona="developer", which=no_scanner, progress=rep2)
        rep2.finish("failed", "no repository")
        self.assertEqual(rep2.since(0)["state"], "failed")


class EstimateTest(FactoryTestCase):
    def run_once(self, history: progress.History, ticks: Ticks, took: dict) -> progress.Reporter:
        rep = progress.Reporter("assessment", history=history, clock=ticks)
        rep.plan([progress.group("g", "G", [progress.step(s, s) for s in took])])
        for sid, secs in took.items():
            rep.start(sid)
            ticks.t += secs
            rep.done(sid)
        rep.finish("done")
        return rep

    def test_FR_PRG1_AC_2_the_estimate_is_the_median_of_earlier_runs_and_a_first_run_says_it_has_none(self):
        history, ticks = progress.History(self.tmp / "progress" / "orders.json"), Ticks()
        first = progress.Reporter("assessment", history=history, clock=ticks)
        first.plan([progress.group("g", "G", [progress.step("a", "A"), progress.step("b", "B")])])
        self.assertEqual(first.estimate()["left_s"], None)
        self.assertEqual(first.estimate()["said"], "First assessment here: no estimate yet. The next run is timed "
                                                    "from this one.")
        for a, b in ((10, 100), (30, 140), (20, 120)):
            self.run_once(history, ticks, {"a": a, "b": b})
        rep = progress.Reporter("assessment", history=history, clock=ticks)
        rep.plan([progress.group("g", "G", [progress.step(s, s.upper()) for s in ("a", "b", "c")])])
        self.assertEqual((rep.earlier, rep.steps["a"]["expected_s"], rep.steps["b"]["expected_s"]), (3, 20.0, 120.0))
        est = rep.estimate()
        self.assertEqual((est["left_s"], est["unknown_steps"]), (140.0, 1))
        self.assertEqual(est["said"], "about 2 min left, from 3 earlier runs; 1 step never timed before.")
        rep.start("a")
        ticks.t += 15
        self.assertEqual(rep.estimate()["left_s"], 125.0)          # what the running step already took counts
        ticks.t += 60
        self.assertIn("takes longer than before", rep.estimate()["said"])
        for _ in range(4):                                            # only the last few runs are kept
            self.run_once(history, ticks, {"a": 1, "b": 1})
        self.assertEqual(len(history.runs("assessment")), progress.KEEP_RUNS)
        self.assertEqual(progress.History(self.tmp / "nowhere.json").expected("assessment"), (0, {}))

    def test_FR_PRG1_AC_2_parallel_steps_count_once_by_the_longest(self):
        history, ticks = progress.History(self.tmp / "h.json"), Ticks()
        groups = [progress.group("panel", "The panel", [progress.step("x", "X"), progress.step("y", "Y")], parallel=True)]
        rep = progress.Reporter("audit", history=history, clock=ticks)
        rep.plan(groups)
        for sid, secs in (("x", 30), ("y", 50)):
            rep.start(sid)
            ticks.t += secs
            rep.done(sid)
        rep.finish("done")
        nxt = progress.Reporter("audit", history=history, clock=ticks)
        nxt.plan(groups)
        self.assertEqual(nxt.estimate()["left_s"], 50.0)


class CancelTest(FactoryTestCase):
    def test_FR_PRG1_AC_3_a_cancel_stops_between_two_steps_and_nothing_is_recorded(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        rep = progress.Reporter("assessment")
        asked = threading.Event()

        def script(prompt: str, role: str) -> str:
            if not asked.is_set():
                asked.set()
                rep.cancel({"person": "Aino", "persona": "developer"})   # a person cancels while the model answers
            return '```json\n{"findings": []}\n```'

        with self.assertRaises(progress.Cancelled):
            assess.assess(project, person="Aino", persona="developer", model=FakeModel(script), which=no_scanner,
                          progress=rep)
        view = rep.since(0)
        self.assertEqual(view["state"], "cancelled")
        self.assertEqual(view["steps"]["panel.business"]["state"], "done")            # the step under way ended
        self.assertEqual(view["steps"]["panel.end_user"]["state"], "waiting")         # the next never started
        self.assertEqual(view["now"], "Cancelled: nothing was recorded.")
        self.assertEqual(assess.history(project), [])
        self.assertFalse(rep.cancel())                                                  # it already ended


class ProgressRouteTest(CockpitTestCase):
    def wait_end(self, pid: str) -> dict:
        end = time.monotonic() + 60
        while time.monotonic() < end:
            got = self.call("GET", f"/api/projects/{pid}/assessment/progress")[1]["progress"]
            if got and got["state"] != "running":
                return got
            time.sleep(0.05)
        self.fail("the assessment did not end")

    def test_FR_PRG1_AC_4_the_route_answers_with_what_changed_since_a_cursor_and_times_the_next_run(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        pid = project.pid
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/assessment/progress")[:2], (200, {"progress": None}))
        status, done, _ = self.call("POST", f"/api/projects/{pid}/assessment", SIGNER)      # by rule: at once
        self.assertEqual((status, done["run"]["state"]), (201, "done"))
        whole = self.call("GET", f"/api/projects/{pid}/assessment/progress?since=0")[1]["progress"]
        self.assertTrue(whole["whole"])
        self.assertEqual([g["id"] for g in whole["plan"]], ["read", "rules", "record"])
        self.assertEqual(whole["estimate"]["said"], "")
        cursor = whole["cursor"]
        tail = self.call("GET", f"/api/projects/{pid}/assessment/progress?since={cursor - 2}")[1]["progress"]
        self.assertFalse(tail["whole"])
        self.assertEqual([e["seq"] for e in tail["events"]], [cursor - 1, cursor])
        self.assertNotIn("plan", tail)
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/assessment/progress?since=junk")[1]["progress"]["whole"],
                         True)
        view = self.call("GET", f"/api/projects/{pid}/assessment")[1]
        self.assertEqual(view["progress"]["result"]["id"], "AS-1")
        # the next run is timed from this one, from the project's own history beside the cockpit's files
        self.server.assistant_model = FakeModel(panel_script)
        status, started, _ = self.call("POST", f"/api/projects/{pid}/assessment", {"panel": True, **SIGNER})
        self.assertEqual(status, 202)
        ended = self.wait_end(pid)
        self.assertEqual(ended["result"]["id"], "AS-2")
        history = json.loads((self.factory.home / "_cockpit" / "progress" / f"{pid}.json").read_text(encoding="utf-8"))
        self.assertEqual(len(history["runs"]["assessment"]), 2)

    def test_FR_PRG1_AC_3_cancel_through_the_cockpit_is_signed_audited_and_records_nothing(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        pid = project.pid
        go, waiting = threading.Event(), threading.Event()

        def script(prompt: str, role: str) -> str:
            waiting.set()
            go.wait(30)
            return '```json\n{"findings": []}\n```'

        self.server.assistant_model = FakeModel(script)
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/assessment/cancel", SIGNER)[1]["cancelled"], False)
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/assessment", {"panel": True, **SIGNER})[0], 202)
        self.assertTrue(waiting.wait(30))
        running = self.call("GET", f"/api/projects/{pid}/assessment/progress")[1]["progress"]
        self.assertEqual((running["state"], running["steps"]["panel.business"]["state"]), ("running", "running"))
        self.assertIn("business perspective", running["now"])
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/assessment/cancel",
                                   {"person": "model", "persona": "developer"})[0], 403)
        status, out, _ = self.call("POST", f"/api/projects/{pid}/assessment/cancel", SIGNER)
        self.assertEqual((status, out["cancelled"]), (202, True))
        self.assertEqual(out["progress"]["now"], "Stopping after the step that runs now…")
        go.set()
        ended = self.wait_end(pid)
        self.assertEqual(ended["state"], "cancelled")
        run = self.call("GET", f"/api/projects/{pid}/assessment")[1]
        self.assertEqual((run["run"]["state"], run["latest"]), ("cancelled", None))
        audit = [r["event"]["payload"] for r in project.ledger().records() if r["event"]["kind"] == "cockpit_write"]
        self.assertEqual([a["action"] for a in audit], ["assess", "assess_cancel"])

    def test_FR_PRG1_AC_6_ask_rihma_answers_how_the_assessment_is_going_from_its_progress(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        pid = project.pid
        none = ask(self.factory, "How is the assessment going?", persona="developer", project_id=pid)
        self.assertIn("No assessment of Orders has run since the cockpit started", none["answer"])
        go, waiting = threading.Event(), threading.Event()

        def script(prompt: str, role: str) -> str:
            waiting.set()
            go.wait(30)
            return '```json\n{"findings": []}\n```'

        self.server.assistant_model = FakeModel(script)
        self.call("POST", f"/api/projects/{pid}/assessment", {"panel": True, **SIGNER})
        self.assertTrue(waiting.wait(30))
        status, out, _ = self.call("POST", "/api/assistant", {"question": "how is the assessment going?",
                                                              "project": pid, **SIGNER})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["by"], "map")
        self.assertTrue(out["answer"].startswith("The assessment is 8 of 14 steps in (2 of 4 groups done)"), out["answer"])
        self.assertIn("Now: The business perspective is reading", out["answer"])
        self.assertIn("Found so far: CI/CD governance 5, Maintenance 6", out["answer"])
        self.assertIn("First assessment here: no estimate yet.", out["answer"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{pid}/assessment")
        self.assertEqual(out["progress"]["state"], "running")
        fi = ask(self.factory, "Miten arviointi etenee?", persona="developer", project_id=pid)
        self.assertIn("8 of 14 steps", fi["answer"])
        self.assertIsNone(progress_chat.answer(project, "Run the assessment again"))
        self.assertIsNone(progress_chat.answer(project, "where is the ledger?"))
        go.set()
        end = time.monotonic() + 30
        while self.call("GET", f"/api/projects/{pid}/assessment")[1]["run"]["state"] == "running":
            self.assertLess(time.monotonic(), end)
            time.sleep(0.05)
        after = ask(self.factory, "is the assessment done?", persona="developer", project_id=pid)
        self.assertTrue(after["answer"].startswith("The last assessment finished after"), after["answer"])
        self.assertIn("AS-1 has", after["answer"])


class JobMappingTest(unittest.TestCase):
    def test_FR_PRG1_AC_5_an_adoption_s_lines_map_onto_its_plan(self):
        lines = ["adopt: fetching the code", "adopt: reading the code and the documents"]
        view = progress_jobs.adoption(lines, "running", elapsed_s=12)
        steps = view["steps"]
        self.assertEqual([g["label"] for g in view["plan"]], ["Taking the code", "Reading", "The baseline", "The record"])
        self.assertEqual((steps["adopt.copy"]["state"], steps["adopt.fetch"]["state"], steps["adopt.read"]["state"],
                          steps["adopt.tests"]["state"]), ("skipped", "done", "running", "waiting"))
        self.assertEqual(steps["adopt.copy"]["why"], "not needed for this one")
        self.assertEqual(view["now"], "reading the code and the documents")
        self.assertEqual((view["elapsed_s"], view["estimate"]["left_s"]), (12.0, None))
        ended = progress_jobs.adoption(lines + ["adopt: running its own tests once for a baseline"], "failed")
        self.assertEqual((ended["state"], ended["steps"]["adopt.tests"]["state"], ended["steps"]["adopt.record"]["state"]),
                         ("failed", "failed", "skipped"))
        whole = progress_jobs.adoption(lines + ["adopt: running its own tests once for a baseline",
                                                "adopt: recording the baseline, the as-is spec and the contract"], "done")
        self.assertEqual((whole["state"], whole["steps_done"], whole["steps_total"]), ("done", 5, 5))

    def test_FR_PRG1_AC_5_a_folder_scan_s_counters_and_any_job_s_lines_map_onto_a_plan(self):
        walking = progress_jobs.scan({"files": 120, "read": 0, "folder": "src/app", "phase": "walking", "elapsed_s": 2.5})
        self.assertEqual((walking["steps"]["scan.walk"]["state"], walking["now"]),
                         ("running", "120 files looked at, in src/app"))
        reading = progress_jobs.scan({"files": 300, "read": 7, "folder": "docs", "phase": "reading", "elapsed_s": 4})
        self.assertEqual((reading["steps"]["scan.walk"]["counts"], reading["steps"]["scan.read"]["state"]),
                         ({"files": 300}, "running"))
        done = progress_jobs.scan({"files": 300, "read": 9, "phase": "reading"}, "done")
        self.assertEqual((done["state"], done["steps_done"]), ("done", 3))
        self.assertEqual(progress_jobs.scan({"files": 3}, "cancelled")["state"], "cancelled")
        # a gate round (or a delivery, or an audit) that prints its steps gets the same view from its lines
        plan = [progress.group("gate", "The gate", [progress.step("g.tests", "Tests"), progress.step("g.review", "Review")])]
        gate = progress_jobs.from_lines("gate", "Gate round", plan, ["gate: tests", "noise", "gate: review"],
                                        {"tests": "g.tests", "review": "g.review"}, state="done")
        self.assertEqual([gate["steps"][s]["state"] for s in ("g.tests", "g.review")], ["done", "done"])


class AdoptionAndScanInCockpitTest(CockpitTestCase):
    def test_FR_PRG1_AC_5_the_jobs_and_a_scan_carry_their_live_progress(self):
        log = self.tmp / "adopt.log"
        log.write_text("adopt: fetching the code\nsomething else\n", encoding="utf-8")
        view = self.server.job_view({"id": "J-1", "kind": "adopt", "project": "_factory", "args": [], "log": str(log),
                                     "started": "2026-11-25T10:00:00Z", "by": {}})
        self.assertEqual(view["live"]["steps"]["adopt.fetch"]["state"], "running")
        folder = self.tmp / "folder"
        (folder / "src").mkdir(parents=True)
        (folder / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
        status, out, _ = self.call("POST", "/api/source/scan", {"source": str(folder), **SIGNER, "persona": "business_owner"})
        if status != 202:          # a folder outside the allowed roots is refused under this access: the mapping alone
            self.skipTest(f"the scan was refused here: {out}")
        sid = out["scan"]["id"]
        end = time.monotonic() + 30
        scan = out["scan"]
        while scan["state"] == "running" and time.monotonic() < end:
            time.sleep(0.05)
            scan = self.call("GET", f"/api/source/scan/{sid}")[1]["scan"]
        self.assertEqual(scan["live"]["kind"], "scan")
        self.assertEqual(scan["live"]["state"], scan["state"] if scan["state"] != "refused" else "failed")


if __name__ == "__main__":
    unittest.main()
