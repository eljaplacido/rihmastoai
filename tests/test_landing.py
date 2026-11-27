"""FR-LND1: a clear landing and live tasks, through the real cockpit server on a temp factory (tests/test_cockpit.py
CockpitTestCase): Start here on a project's first view, its hide per person, Ask Rihma's "what should I do here?", the
tasks you open with their source, criteria, tests, commits and history, a person's start, done and hand-off (cockpit,
command line and Ask Rihma), and the whole log of a run. Every answer here comes by rule; no model is asked.

The adopted project is invented and neutral: a rules service whose own spec sits in rule files, adopted to maintain."""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import run_log, start_here, task_detail  # noqa: E402
from kernel.agent_channel import read as channel  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.change import submit  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

DEV = {"person": "Ida Example", "persona": "developer"}
README = "Checks shipping rules for a small parcel service. Each rule lives in its own file with a mutant test."


def adopted(case):
    """An adopted project as adoption and Alignment leave it: an inventory and its README, a kind of work only guessed,
    one requirement imported from its repository's own rule files (AL-1) and one as-is task (T-001)."""
    p = case.factory.new_project("Parcel rules")
    p.update_meta(source_kind="adopted", intent="maintain", stage=5)
    p.write("adopted.json", {"source": "/work/parcel-rules", "intent": "maintain",
                             "profile": {"profile": "web_app", "confidence": "uncertain", "why": "nothing stood out"}})
    p.write("inventory.json", {"languages": [{"language": "Python", "files": 12}],
                               "readme": {"file": "README.md", "first_paragraph": README},
                               "test_command": {"detected": False}, "dockerfile": {"present": False},
                               "endpoints": {"scanned": False}})
    p.write("contract.json", {"requirements": [
        {"id": "R-1", "statement": "The service answers health checks.", "provenance": "vendor-proposed",
         "notes": "observed: existing behaviour at adoption, not a spec",
         "acceptance": [{"id": "R-1-AC-1", "given": "-", "when": "GET /health", "then": "200", "check": {"kind": "test"}}]},
        {"id": "RULE-1", "statement": "A parcel over 30 kg is refused.", "provenance": "customer-endorsed",
         "notes": "imported from the repository (rules/heavy.json:1, their heavy, rules), accepted by Ida on 2026-11-26",
         "acceptance": [{"id": "RULE-1-AC-1", "given": "a 31 kg parcel", "when": "it is checked", "then": "refused",
                         "check": {"kind": "test"}}]}],
        "tasks": [{"id": "T-001", "title": "The service as it is", "criteria": ["R-1-AC-1"]},
                  {"id": "AL-1", "title": "A parcel over 30 kg is refused.", "criteria": ["RULE-1-AC-1"]}]})
    p.write("tasks.json", {"T-001": {"status": "merged", "rounds": [], "adopted": True,
                                     "note": "the existing code at adoption; not built or gated by the factory"}})
    return p


class StartHereTest(CockpitTestCase):
    def here(self, pid, person=""):
        status, out, _ = self.call("GET", f"/api/projects/{pid}/start-here?person={person.replace(' ', '%20')}")
        self.assertEqual(status, 200, out)
        return out

    def test_FR_LND1_AC_1_start_here_says_what_it_understood_and_the_steps_from_the_real_state(self):
        p = adopted(self)
        out = self.here(p.pid)
        self.assertTrue(out["applies"])
        self.assertIn("Checks shipping rules for a small parcel service.", out["understood"]["line"])
        self.assertIn("web app (a guess: confirm it)", out["understood"]["line"])
        self.assertIn("README.md", out["understood"]["basis"])
        self.assertEqual(out["understood"]["correct"]["control"], "understood_correct")
        self.assertEqual([s["id"] for s in out["steps"]], ["confirm_kind", "map_sources", "assess"])
        sources = out["steps"][1]
        self.assertEqual((sources["route"], sources["control"]), (f"#/p/{p.pid}/align", "align_scan"))
        self.assertLessEqual(len(out["steps"]), start_here.MAX_STEPS)
        # nothing runs on its own yet: the watch an adopted project to maintain is offered
        self.assertEqual(out["meanwhile"]["rows"], [])
        self.assertEqual(out["meanwhile"]["none"]["control"], "watch_setup")
        self.assertIn("Meanwhile: nothing runs here on its own yet", out["said"])
        # an upstream change waiting for a decision comes before mapping the sources
        card = submit(p, persona="developer", person="upstream sync", text="Upstream moved: 3 new commits")
        before = len(p.ledger().records())
        ids = [s["id"] for s in self.here(p.pid)["steps"]]
        self.assertEqual(ids, ["confirm_kind", "upstream_change", "map_sources"])
        step = self.here(p.pid)["steps"][1]
        self.assertEqual((step["route"], step["card"]), (f"#/p/{p.pid}/inbox/{card['id']}", card["id"]))
        self.assertEqual(len(p.ledger().records()), before)           # reading recorded nothing
        # a project the factory builds: what kernel/next_step.py says it waits for
        built = self.built_project()
        out = self.here(built.pid)
        self.assertIn("a new project, stage", out["understood"]["line"])
        self.assertIn("advance", [s["id"] for s in out["steps"]])
        self.assertTrue(all(s["route"].startswith(f"#/p/{built.pid}/") for s in out["steps"]))
        # Rihma's own canon has no Start here, and says so
        factory_project(self.factory)
        status, out, _ = self.call("GET", "/api/projects/_factory/start-here")
        self.assertEqual((status, out["applies"]), (200, False))

    def test_FR_LND1_AC_2_a_person_hides_it_for_themselves_and_a_new_step_brings_it_back(self):
        p = adopted(self)
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/start-here", {"hide": True, **DEV})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["steps"], ["confirm_kind", "map_sources", "assess"])
        self.assertTrue(self.here(p.pid, "Ida Example")["hidden"])
        self.assertFalse(self.here(p.pid, "Aino Example")["hidden"])          # another person still sees it
        rec = p.ledger().of_kind("start_here_hidden")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"]), ("Ida Example", "developer"))
        before = len(p.ledger().records())
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/start-here",
                                   {"hide": True, "person": "assistant", "persona": "developer"})
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/start-here", {"hide": "yes", **DEV})
        self.assertEqual(status, 400, out)
        self.assertEqual(len(p.ledger().records()), before)
        submit(p, persona="developer", person="upstream sync", text="Upstream moved")
        back = self.here(p.pid, "Ida Example")
        self.assertFalse(back["hidden"])
        self.assertEqual(back["new"], ["upstream_change"])
        self.call("POST", f"/api/projects/{p.pid}/start-here", {"hide": False, **DEV})
        self.assertEqual(p.ledger().of_kind("start_here_shown")[-1]["event"]["payload"]["person"], "Ida Example")

    def test_FR_LND1_AC_3_ask_rihma_what_should_i_do_here_answers_the_same_by_rule(self):
        p = adopted(self)
        model = mock.Mock()
        out = ask(self.factory, "What should I do here?", persona="developer", project_id=p.pid, model=model)
        model.assert_not_called()
        self.assertEqual(out["by"], "rule")
        self.assertEqual([s["id"] for s in out["start_here"]["steps"]],
                         [s["id"] for s in start_here.panel(p)["steps"]])
        self.assertIn("Do now: 1. Confirm what kind of work it is", out["answer"])
        self.assertEqual(out["navigate"]["route"], out["start_here"]["steps"][0]["route"])
        out = ask(self.factory, "where do I start with this project?", persona="business_owner", project_id=p.pid)
        self.assertIn("start_here", out)
        out = ask(self.factory, "what should I do here?", persona="developer")
        self.assertIn("Open a project and ask again", out["answer"])
        out = ask(self.factory, "what should I do next?", persona="developer", project_id=p.pid)
        self.assertNotIn("start_here", out)                                   # the guided journeys' question


class TasksTest(CockpitTestCase):
    def test_FR_LND1_AC_4_every_task_says_its_source_and_status_and_the_list_has_a_signature(self):
        p = adopted(self)
        status, out, _ = self.call("GET", f"/api/projects/{p.pid}/tasks")
        self.assertEqual(status, 200, out)
        by = {t["id"]: t for t in out["tasks"]}
        self.assertEqual((by["T-001"]["source"], by["T-001"]["status"]), ("adopted", "merged"))
        self.assertEqual(by["AL-1"]["source"], "repository")
        self.assertIn("rules/heavy.json:1", by["AL-1"]["source_said"])
        self.assertEqual(by["AL-1"]["open"], f"#/p/{p.pid}/tasks/AL-1")
        sig = out["signature"]
        self.call("POST", f"/api/projects/{p.pid}/tasks/AL-1/start", DEV)
        again = self.call("GET", f"/api/projects/{p.pid}/tasks")[1]
        self.assertNotEqual(again["signature"], sig)
        self.assertEqual({t["id"]: t["status"] for t in again["tasks"]}["AL-1"], "started")
        # the project's own payload carries the same, for the board's filters
        rows = {t["id"]: t for t in self.call("GET", f"/api/projects/{p.pid}")[1]["tasks"]}
        self.assertEqual((rows["AL-1"]["source"], rows["AL-1"]["shown_status"]), ("repository", "started"))
        self.assertEqual(rows["AL-1"]["mark"]["started"]["person"], "Ida Example")
        built = self.built_project()
        self.assertEqual({t["source"] for t in task_detail.rows(built)["tasks"]}, {"plan"})

    def test_FR_LND1_AC_5_a_task_opens_with_criteria_tests_commits_agents_and_history(self):
        built = self.built_project()
        status, d, _ = self.call("GET", f"/api/projects/{built.pid}/task?id=T-001")
        self.assertEqual(status, 200, d)
        self.assertTrue(d["found"])
        self.assertEqual((d["status"], d["source"], d["lane"]), ("merged", "plan", "done"))
        crit = {c["id"]: c for c in d["criteria"]}
        self.assertEqual(crit["R-1-AC-1"]["state"], "verified")
        self.assertTrue(crit["R-1-AC-1"]["then"])
        self.assertTrue(any(t["from"] == "the last gate round" for t in d["tests"]), d["tests"])
        self.assertTrue(d["commits"] and "T-001" in d["commits"][0]["tasks"])
        self.assertTrue(d["agents"])
        kinds = [h["kind"] for h in d["history"]]
        self.assertIn("gate", kinds)
        self.assertIn("merged", kinds)
        self.assertEqual([a["id"] for a in d["actions"]], ["handoff", "ask"])       # merged: no start, no done
        pending = self.call("GET", f"/api/projects/{built.pid}/task?id=T-002")[1]
        self.assertEqual([a["id"] for a in pending["actions"]], ["handoff", "start", "done", "ask"])
        self.assertTrue(pending["commits_why"])
        status, out, _ = self.call("GET", f"/api/projects/{built.pid}/task?id=T-999")
        self.assertEqual((status, out["found"]), (200, False))
        self.assertIn("Tasks lists this project's tasks", out["why"])
        status, out, _ = self.call("GET", f"/api/projects/{built.pid}/task?id=..%2Fx")
        self.assertEqual(status, 400, out)
        # the repository's own test traced to an imported criterion: not measured here, and why
        p = adopted(self)
        p.write("alignment/decisions.json", {"I-1": {"verdict": "accept", "group": "trace", "person": "Ida",
                                                     "at": "2026-11-26T09:00:00Z", "item": {
                                                         "id": "I-1", "group": "trace", "proposal": {
                                                             "test": "test_heavy_refused", "file": "tests/test_rules.py",
                                                             "criterion_id": "RULE-1-AC-1"}}}})
        d = task_detail.detail(p, "AL-1")
        traced = next(t for t in d["tests"] if t["name"] == "tests/test_rules.py::test_heavy_refused")
        self.assertEqual(traced["result"], "not measured here")
        self.assertIn("own runner", traced["why"])

    def test_FR_LND1_AC_6_start_done_and_hand_off_are_signed_refused_when_they_may_not_and_recorded(self):
        built = self.built_project()
        base = f"/api/projects/{built.pid}/tasks"
        status, out, _ = self.call("POST", f"{base}/T-002/start", {"person": "Ida Example", "persona": "compliance"})
        self.assertEqual(status, 403, out)
        self.assertIn("may not start a task", out["error"])
        status, out, _ = self.call("POST", f"{base}/T-002/done", DEV)
        self.assertEqual(status, 400, out)
        status, out, _ = self.call("POST", f"{base}/T-001/done", {"evidence": "it works", **DEV})
        self.assertEqual(status, 409, out)                                    # the gate's merge stays the gate's
        status, out, _ = self.call("POST", f"{base}/T-001/start", DEV)
        self.assertEqual(status, 409, out)
        self.assertEqual(built.ledger().of_kind("task_started"), [])
        status, out, _ = self.call("POST", f"{base}/T-002/start", DEV)
        self.assertEqual((status, out["status"]), (200, "started"))
        status, out, _ = self.call("POST", f"{base}/T-002/done", {"evidence": "suite passed at abc1234", **DEV})
        self.assertEqual((status, out["status"]), (200, "done"))
        rec = built.ledger().of_kind("task_marked_done")[-1]["event"]["payload"]
        self.assertEqual((rec["task"], rec["evidence"], rec["person"]), ("T-002", "suite passed at abc1234",
                                                                         "Ida Example"))
        self.assertIn("not claimed", rec["note"])
        d = task_detail.detail(built, "T-002")
        self.assertEqual((d["status"], d["gate_status"]), ("done", "pending"))
        self.assertIn("marked done with evidence: suite passed at abc1234", [h["said"] for h in d["history"]][-1])
        status, out, _ = self.call("POST", f"{base}/T-003/handoff", {"to": "claude-code", **DEV})
        self.assertEqual(status, 200, out)
        self.assertIn("Task T-003", out["markdown"])
        msg = channel(built)["messages"][-1]
        self.assertEqual((msg["kind"], msg["refs"]["tasks"]), ("handoff", ["T-003"]))
        self.assertEqual(built.ledger().of_kind("agent_handoff")[-1]["event"]["payload"]["task"], "T-003")
        self.assertIn("handed to an agent", [h["said"] for h in task_detail.history(built, "T-003")])
        status, out, _ = self.call("POST", f"{base}/T-003/handoff", {"to": "a robot", **DEV})
        self.assertEqual(status, 400, out)
        # the same from the command line, signed; and Start here and the task list from it
        home = str(self.factory.home)
        with contextlib.redirect_stdout(io.StringIO()) as said:
            self.assertEqual(main(["--home", home, "task", "start", built.pid, "T-003", "--person", "Ida Example",
                                   "--persona", "developer"]), 0)    # T-002 it waits for is marked done (FR-LND2)
        self.assertEqual(json.loads(said.getvalue())["status"], "started")
        with contextlib.redirect_stdout(io.StringIO()) as said:
            self.assertEqual(main(["--home", home, "start-here", built.pid]), 0)
        self.assertIn("steps", json.loads(said.getvalue()))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(["--home", home, "task", "done", built.pid, "T-004", "--evidence", " ",
                                   "--person", "Ida Example", "--persona", "developer"]), 2)
        self.assertIn("rihmasto task done: say what shows it is done", err.getvalue())

    def test_FR_LND1_AC_7_ask_rihma_about_a_task_and_to_start_hand_off_or_mark_it_done(self):
        built = self.built_project()
        model = mock.Mock()
        out = ask(self.factory, "What about T-001?", persona="developer", project_id=built.pid, model=model)
        model.assert_not_called()
        self.assertEqual(out["by"], "rule")
        self.assertIn("T-001: ", out["answer"])
        self.assertIn("Status: merged", out["answer"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{built.pid}/tasks/T-001")
        out = ask(self.factory, "start T-002", persona="developer", project_id=built.pid)
        call = out["propose"][0]["args"]["call"]
        self.assertEqual((call["method"], call["path"]), ("POST", f"/api/projects/{built.pid}/tasks/T-002/start"))
        out = ask(self.factory, "hand T-002 to Claude Code", persona="developer", project_id=built.pid)
        self.assertEqual(out["propose"][0]["args"]["call"]["body"], {"to": "claude-code"})
        out = ask(self.factory, "mark T-002 done: the suite passed at abc1234", persona="developer",
                  project_id=built.pid)
        self.assertEqual(out["propose"][0]["args"]["call"]["body"], {"evidence": "the suite passed at abc1234"})
        out = ask(self.factory, "mark T-002 done", persona="developer", project_id=built.pid)
        self.assertEqual(out["propose"], [])
        self.assertIn("say what shows it is done", out["answer"])
        self.assertEqual(built.ledger().of_kind("task_started"), [])           # proposed, never done unasked
        out = ask(self.factory, "T-002 is stuck: retry it, and pause the project.", persona="developer",
                  project_id=built.pid)
        self.assertNotIn("task", out)                                          # not a task question: not taken


class RunLogTest(CockpitTestCase):
    def test_FR_LND1_AC_8_the_whole_log_of_a_job_followed_and_what_a_finished_one_changed(self):
        built = self.built_project()
        self.clock.advance(minutes=5)                                 # the job starts after the project was built
        job = self.server.start_job("run", built.pid, ["-m", "kernel.cli", "run", built.pid],
                                    {"person": "Ida Example", "persona": "developer"})
        log = Path(job["log"])
        log.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"line {i:06d} of the run" for i in range(20000)]
        log.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        status, out, _ = self.call("GET", f"/api/run-log?job={job['id']}")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["job"]["state"], "running")
        self.assertGreater(out["skipped"], 0)                         # a long log from its last 256 KiB, saying so
        self.assertTrue(out["text"].startswith("line "))
        self.assertTrue(out["text"].endswith("line 019999 of the run\n"))
        with open(log, "ab") as fh:
            fh.write(b"the next line\n")
        more = self.call("GET", f"/api/run-log?job={job['id']}&from={out['next']}")[1]
        self.assertEqual(more["text"], "the next line\n")
        self.assertNotIn("changed", more)                             # still running
        self.call("POST", f"/api/projects/{built.pid}/tasks/T-002/start", DEV)
        self.runner.states[job["id"]] = "done"
        done = self.call("GET", f"/api/run-log?job={job['id']}&from={more['next']}")[1]
        self.assertEqual(done["text"], "")
        self.assertEqual([c["route"] for c in done["changed"]], [f"#/p/{built.pid}/tasks/T-002"])
        runs = self.call("GET", "/api/run-log")[1]["runs"]
        self.assertEqual(runs[0]["open"], f"#/jobs/{job['id']}")
        status, out, _ = self.call("GET", "/api/run-log?job=J-9999")
        self.assertEqual(status, 404, out)
        self.assertEqual(run_log.job_text(self.tmp / "missing.log")["exists"], False)

    def test_FR_LND1_AC_8_the_cell_building_a_task_is_every_step_of_its_audit_trail(self):
        built = self.built_project()
        out = self.call("GET", f"/api/run-log?project={built.pid}")[1]
        self.assertEqual((out["running"], out["lines"]), (False, []))
        self.assertIn("no cell is building", out["why"])
        lanes = self.tmp / "lanes-live"
        audit = lanes / "lane-1" / ".gnomon-audit"
        audit.mkdir(parents=True)
        trail = [{"kind": "session_start", "role": "builder"}, {"kind": "model_call", "model": "a-model"},
                 *[{"kind": "tool_call", "tool": "edit", "target": f"app/f{i}.py", "ts": "2026-11-26T10:00:0" + str(i)}
                   for i in range(3)]]
        (audit / "task-1.jsonl").write_text("\n".join(json.dumps(r) for r in trail) + "\n", encoding="utf-8")
        live = {"running": True, "task": "T-002", "lane": "lane-1", "steps": 3, "ended": False}
        with mock.patch("kernel.status.live", return_value=live), mock.patch("kernel.lanes.lanes_root",
                                                                             return_value=lanes):
            out = self.call("GET", f"/api/run-log?project={built.pid}")[1]
            self.assertEqual((out["running"], out["task"], out["model"], out["steps"]), (True, "T-002", "a-model", 3))
            self.assertEqual(len(out["lines"]), 3)
            self.assertIn("edit  app/f2.py", out["lines"][-1])
            again = self.call("GET", f"/api/run-log?project={built.pid}&from={out['next']}")[1]
            self.assertEqual(again["lines"], [])
            runs = self.call("GET", "/api/run-log")[1]["runs"]
            self.assertEqual(runs[0]["open"], f"#/jobs/cell:{built.pid}")
            here = start_here.meanwhile(built)
            self.assertEqual(here["rows"][0]["log"], {"project": built.pid})


if __name__ == "__main__":
    unittest.main()
