"""FR-LND2: the clear landing made true, through the real cockpit server on a temp factory (tests/test_cockpit.py
CockpitTestCase), by rule, no model asked:

- Start here says what Alignment reads and what it cannot, and names the sources in the repository it left unread;
- the Board's next development step and Ask Rihma's "where do I start?" agree with Start here; a question about
  syncing a coding agent gets a sync plan;
- the cell's whole log is kept once the cell stops, with what it changed; a job's changes end when it ended, and an
  adoption's are the project it made;
- a task waits for the tasks it depends on and for the decision it is escalated to; a person's done has its own lane
  and moves the board.

Every fixture is invented and neutral: a meal planner whose real plan lives in rule files and an issue log."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402
from test_landing import DEV, adopted  # noqa: E402

from kernel import devbrief, repo_structure, start_here, task_detail  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.canon import Canon  # noqa: E402


def planner_repo(root: Path) -> Path:
    """A repository whose old plan is a requirements document and whose real work lives elsewhere: YAML rule files,
    an issue log and task rows in a round's notes. JSON rule files and a README's status table are read (FR-ASP2)."""
    files = {
        "docs/planning/requirements.md": "# Requirements\n\n- REQ-1: The planner lists the week's meals.\n"
                                         "- REQ-2: The planner exports a shopping list.\n",
        "rules/portions.yaml": "rule: a portion is 400 g\n",
        "rules/allergens.yaml": "rule: nuts are flagged\n",
        "laws/limits.json": json.dumps({"rule": "a week has seven days"}),
        "docs/evidence/issues.jsonl": json.dumps({"id": "IS-1", "title": "the list repeats items"}) + "\n",
        "rounds/round-2/NOTES.md": "# Round 2\n\n| Task | What | State |\n|---|---|---|\n"
                                   "| T-7 | Add the weekly view | open |\n| T-8 | Flag allergens | done |\n",
        "rounds/round-3/README.md": "# Round 3\n\n| Task | What | State |\n|---|---|---|\n"
                                    "| T-9 | Share a plan | open |\n| T-10 | Print it | open |\n",
        "src/planner.py": "def plan():\n    return []\n",
        "tests/test_planner.py": "def test_plan():\n    assert True\n",
        "package.json": json.dumps({"name": "planner", "scripts": {"test": "pytest"}}),
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


class SourcesTest(CockpitTestCase):
    def test_FR_LND2_AC_1_alignment_names_the_sources_it_cannot_read_and_start_here_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            structure = repo_structure.from_folder(planner_repo(Path(tmp)))
        unread = {u["path"]: u for u in structure["unread"]}
        # JSON rule files and a README's status table are read (FR-ASP2): never named unread
        self.assertEqual(set(unread), {"rules/*.yaml", "docs/evidence/issues.jsonl", "rounds/round-2/NOTES.md"})
        self.assertEqual(unread["rules/*.yaml"]["files"], 2)
        self.assertEqual(unread["rounds/round-2/NOTES.md"]["kind"], "task rows in a document")
        # before any scan: what Alignment reads and what it cannot, never "where its real ... live"
        p = adopted(self)
        step = next(s for s in start_here.panel(p)["steps"] if s["id"] == "map_sources")
        self.assertNotIn("where its real requirements", step["why"])
        self.assertIn("it does not read", step["why"])
        self.assertIn("issue", step["why"])
        # after a scan that read only the old document: the items, where from, and what was left unread
        proposal = {"items": [{"id": "I-1", "group": "requirements"}, {"id": "I-2", "group": "requirements"},
                              {"id": "I-3", "group": "gaps"}]}
        p.write("alignment/scan.json", {"n": 1, "structure": structure, "proposal": proposal})
        step = next(s for s in start_here.panel(p)["steps"] if s["id"] == "map_sources")
        self.assertIn("2 items", step["label"])
        self.assertIn("docs/planning/requirements.md", step["why"])
        self.assertIn("rules/*.yaml", step["why"])
        self.assertIn("out of date", step["why"])
        self.assertEqual([u["path"] for u in step["unread"]][:1], ["rules/*.yaml"])
        # every item decided, the real sources still unread: said, not dropped
        p.write("alignment/decisions.json", {i: {"verdict": "reject", "group": "requirements", "key": i}
                                             for i in ("I-1", "I-2")})
        step = next(s for s in start_here.panel(p)["steps"] if s["id"] == "map_sources")
        self.assertIn("not read", step["label"])
        self.assertIn("docs/evidence/issues.jsonl", step["why"])


class OneNextStepTest(CockpitTestCase):
    def merged_only(self):
        p = adopted(self)
        contract = p.read("contract.json")
        contract["tasks"] = [t for t in contract["tasks"] if t["id"] == "T-001"]
        p.write("contract.json", contract)
        return p

    def test_FR_LND2_AC_4_the_board_and_ask_rihma_agree_with_start_here(self):
        p = self.merged_only()
        first = start_here.panel(p)["steps"][0]
        nxt = devbrief.briefing(p)["next"]
        self.assertNotIn("Every task is merged", nxt["title"])
        self.assertEqual((nxt["title"], nxt["action"]["route"], nxt["action"]["control"]),
                         (first["label"], first["route"], first["control"]))
        self.assertEqual(nxt["from"], "start_here")
        model = mock.Mock()
        for q in ("where do I start?", "What now in this project?", "what now?", "Where should I begin?"):
            out = ask(self.factory, q, persona="developer", project_id=p.pid, model=model)
            self.assertIn("start_here", out, q)
            self.assertEqual(out["navigate"]["route"], first["route"], q)
        model.assert_not_called()
        # outside a project the bare question is the guided journeys' still
        out = ask(self.factory, "where do I start?", persona="developer")
        self.assertNotIn("start_here", out)

    def test_FR_LND2_AC_9_asking_how_to_sync_a_coding_agent_gets_a_sync_plan(self):
        p = adopted(self)
        model = mock.Mock()
        out = ask(self.factory, "consult Claude Code on how to sync with Rihmasto and what to monitor",
                  persona="developer", project_id=p.pid, model=model)
        model.assert_not_called()
        self.assertEqual(out.get("topic"), "agent_sync", out.get("answer"))
        self.assertEqual(out["navigate"]["control"], "handoff")
        self.assertIn("Claude Code", out["answer"])
        self.assertIn("monitor", out["answer"].lower())
        self.assertEqual([s["id"] for s in out["sync_plan"]][:2], ["hand_brief", "hand_task"])
        self.assertIn("AL-1", out["answer"])                          # the first task to hand it
        self.assertEqual(out["propose"], [])                          # nothing written unasked
        out = ask(self.factory, "how do I keep Codex in sync with this project?", persona="developer",
                  project_id=p.pid)
        self.assertEqual(out.get("topic"), "agent_sync")
        self.assertIn("Codex", out["answer"])


class CellLogTest(CockpitTestCase):
    def test_FR_LND2_AC_5_a_finished_cell_keeps_its_whole_log_and_what_it_changed(self):
        built = self.built_project()
        lanes = self.tmp / "lanes-done"
        audit = lanes / "lane-2" / ".gnomon-audit"
        audit.mkdir(parents=True)
        trail = [{"kind": "session_start", "role": "builder"}, {"kind": "model_call", "model": "a-model"},
                 *[{"kind": "tool_call", "tool": "edit", "target": f"app/g{i}.py", "ts": "2026-11-26T10:00:0" + str(i)}
                   for i in range(4)], {"kind": "session_end"}]
        (audit / "task-77aa.jsonl").write_text("\n".join(json.dumps(r) for r in trail) + "\n", encoding="utf-8")
        self.clock.advance(minutes=1)
        built.log("gnomon_run", {"run": "task-77aa", "task": "T-002", "round": 0, "role": "builder"})
        built.log("cell_ran", {"task": "T-002", "round": 0, "head": "abc"})
        built.log("gate", {"task": "T-002", "round": 0, "verdict": "failed"})
        stopped = {"running": False, "why": "no lane is held for this project"}
        with mock.patch("kernel.status.live", return_value=stopped), \
                mock.patch("kernel.lanes.lanes_root", return_value=lanes):
            out = self.call("GET", f"/api/run-log?project={built.pid}")[1]
            self.assertEqual((out["running"], out["finished"], out["task"]), (False, True, "T-002"))
            self.assertEqual((out["model"], out["steps"], len(out["lines"])), ("a-model", 4, 4))
            self.assertIn("edit  app/g3.py", out["lines"][-1])
            self.assertIn(f"#/p/{built.pid}/tasks/T-002", [c["route"] for c in out["changed"]])
            self.assertIn("the gate judged T-002: failed", [c["said"] for c in out["changed"]])
            again = self.call("GET", f"/api/run-log?project={built.pid}&from={out['next']}")[1]
            self.assertEqual(again["lines"], [])
        # no cell ever ran under Gnomon here: said, with how one does
        out = self.call("GET", f"/api/run-log?project={self.built_project().pid}")[1]
        self.assertFalse(out.get("finished"))
        self.assertIn("no cell", out["why"])


class JobChangedTest(CockpitTestCase):
    def test_FR_LND2_AC_6_a_job_changed_only_what_came_before_it_ended_and_an_adoption_its_project(self):
        built = self.built_project()
        self.clock.advance(minutes=5)
        job = self.server.start_job("run", built.pid, ["-m", "kernel.cli", "run", built.pid], DEV)
        Path(job["log"]).parent.mkdir(parents=True, exist_ok=True)
        Path(job["log"]).write_text("ran\n", encoding="utf-8")
        self.clock.advance(minutes=1)
        self.call("POST", f"/api/projects/{built.pid}/tasks/T-002/start", DEV)      # while it ran
        self.runner.states[job["id"]] = "done"
        first = self.call("GET", f"/api/run-log?job={job['id']}")[1]
        self.assertTrue(first["job"]["ended"])
        self.assertEqual([c["route"] for c in first["changed"]], [f"#/p/{built.pid}/tasks/T-002"])
        self.clock.advance(minutes=10)
        self.call("POST", f"/api/projects/{built.pid}/tasks/T-002/done", {"evidence": "it passed", **DEV})  # after
        later = self.call("GET", f"/api/run-log?job={job['id']}")[1]
        self.assertEqual(later["job"]["ended"], first["job"]["ended"])
        self.assertEqual([c["kind"] for c in later["changed"]], ["task_started"])
        # an adoption runs under _factory: what it changed is in the project it made
        adopt = self.server.start_job("adopt", "_factory", ["-m", "kernel.cli", "adopt", "x"], DEV)
        Path(adopt["log"]).write_text("adopting\n{\n  \"project\": \"" + built.pid + "\"\n}\n", encoding="utf-8")
        self.clock.advance(minutes=1)
        built.log("inventory_taken", {"id": "inv"})
        self.runner.states[adopt["id"]] = "done"
        out = self.call("GET", f"/api/run-log?job={adopt['id']}")[1]
        self.assertEqual(out["changed_in"], built.pid)
        self.assertIn("inventory_taken", [c["kind"] for c in out["changed"]])


class TaskRulesTest(CockpitTestCase):
    def test_FR_LND2_AC_7_a_task_waits_for_its_dependencies_and_its_decision_and_done_has_a_lane(self):
        built = self.built_project()
        base = f"/api/projects/{built.pid}/tasks"
        status, out, _ = self.call("POST", f"{base}/T-003/start", DEV)              # T-003 waits for T-002
        self.assertEqual(status, 409, out)
        self.assertIn("waits for T-002", out["error"])
        d = task_detail.detail(built, "T-003")
        self.assertNotIn("start", [a["id"] for a in d["actions"]])
        self.assertEqual(d["waits"]["tasks"], ["T-002"])
        out = ask(self.factory, "start T-003", persona="developer", project_id=built.pid)   # Ask Rihma says the same
        self.assertEqual(out["propose"], [])
        self.assertIn("T-003 waits for T-002", out["answer"])
        # T-002 escalated to a decision still open: neither started nor marked done until it is decided
        card = Canon(built).card("escalation", "T-002 did not pass its gate after 2 round(s)", refs={"task": "T-002"},
                                 blocking=True)
        states = built.read("tasks.json")
        states["T-002"] = {"status": "escalated", "card": card["id"], "rounds": []}
        built.write("tasks.json", states)
        before = len(built.ledger().records())
        for verb, body in (("start", DEV), ("done", {"evidence": "looked fine", **DEV})):
            status, out, _ = self.call("POST", f"{base}/T-002/{verb}", body)
            self.assertEqual(status, 409, (verb, out))
            self.assertIn(f"waits on the decision {card['id']}", out["error"])
        self.assertEqual(len(built.ledger().records()), before)
        self.assertEqual([a["id"] for a in task_detail.detail(built, "T-002")["actions"]], ["handoff", "ask"])
        # decided: it may be marked done; the board's signature moves, and the done has a lane of its own
        Canon(built).close(card["id"], "accepted as is by the owner", state="resolved")
        sig = task_detail.rows(built)["signature"]
        status, out, _ = self.call("POST", f"{base}/T-002/done", {"evidence": "the owner accepted it", **DEV})
        self.assertEqual(status, 200, out)
        rows = task_detail.rows(built)
        self.assertNotEqual(rows["signature"], sig)
        self.assertEqual({r["id"]: r["lane"] for r in rows["tasks"]}["T-002"], "done")
        self.assertEqual({t["id"]: t["lane"] for t in self.call("GET", f"/api/projects/{built.pid}")[1]["tasks"]}
                         ["T-002"], "done")
        status, out, _ = self.call("POST", f"{base}/T-003/start", DEV)              # its dependency is done now
        self.assertEqual(status, 200, out)


if __name__ == "__main__":
    unittest.main()
