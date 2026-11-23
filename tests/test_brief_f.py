"""Brief section F (scheduler, leases and quotas): what the kernel really does, exercised end to end.

FR-F3 and FR-F7 are partly built; the rest of section F is recorded in contract/deferred/f.json
with what is missing. FR-F5 and FR-F8 have their own tests (test_compile.py, test_learn.py).
"""

import json
import os
import re
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, good_cell, lazy_cell, model, no_findings  # noqa: E402

from adapters.gnomon_ingest import ingest  # noqa: E402
from kernel.compile import compile_project, contract_check  # noqa: E402
from kernel.dashboard import timeline  # noqa: E402
from kernel.dispatch import build, build_task, ingest_latest_run, ready_tasks  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.learn import model_reliability  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
FIX = Path(__file__).parent / "fixtures" / "gnomon"
ESCALATION = {"trigger": "stuck", "at_step": 12, "detail": "no_progress", "carried": "handover",
              "from": {"model": "local-builder", "endpoint": "local"},
              "to": {"model": "cloud-builder", "endpoint": "cloud"}, "final_model": "cloud-builder"}


def _task_of(prompt: str) -> str:
    return re.search(r"^# Envelope (T-\d+)", prompt, re.MULTILINE).group(1)


class SchedulerBriefTest(FactoryTestCase):
    def compiled(self, title="Equipment loans"):
        p = self.new(mode="assume", title=title)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    # -- FR-F3: one cell on a shared write scope ------------------------------------------------

    def test_FR_F3_AC_1_tasks_on_one_write_scope_are_chained_so_one_is_ready_at_a_time(self):
        p = self.compiled()
        tasks = p.read("contract.json")["tasks"]
        self.assertGreaterEqual(len(tasks), 3)
        scopes = {tuple(sorted(t["scope"]["write"])) for t in tasks}
        self.assertEqual(len(scopes), 1)                         # every task writes the same scope
        for before, after in zip(tasks, tasks[1:]):
            self.assertEqual(after["depends_on"], [before["id"]])
        self.assertEqual(ready_tasks(p), [tasks[0]["id"]])       # one ready, though none has started
        lanes = Lanes(self.tmp / "lanes", size=3)
        first = build_task(p, tasks[0]["id"], lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings)
        self.assertEqual(first["status"], "merged")
        self.assertEqual(ready_tasks(p), [tasks[1]["id"]])       # the next one, and only it
        second = build_task(p, tasks[1]["id"], lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings,
                            max_rounds=0)
        self.assertEqual(second["status"], "escalated")
        self.assertEqual(ready_tasks(p), [])                     # a task waiting on a person holds the scope

    def test_FR_F3_AC_2_the_build_runs_one_cell_at_a_time_even_with_free_lanes_and_ready_tasks(self):
        p = self.compiled()
        contract = p.read("contract.json")
        for t in contract["tasks"]:                              # take the chain away: all tasks ready at once
            t.pop("depends_on", None)
        contract["revision"] = contract_check().canonical_revision(contract)
        p.write("contract.json", contract)
        ids = [t["id"] for t in contract["tasks"]]
        self.assertEqual(ready_tasks(p), ids)

        seen, active = [], {"now": 0, "most": 0}

        def cell(lane_path, prompt):
            active["now"] += 1
            active["most"] = max(active["most"], active["now"])
            try:
                task = _task_of(prompt)
                state = p.read("tasks.json", {}) or {}
                building = sorted(t for t, s in state.items() if s.get("status") == "building")
                merged = sorted(t for t, s in state.items() if s.get("status") == "merged")
                seen.append({"task": task, "lane": Path(lane_path).name, "building": building, "merged": merged})
                time.sleep(0.05)                                  # a window in which a second cell would show
                return generic_cell(lane_path, prompt)
            finally:
                active["now"] -= 1

        out = build(p, lanes=Lanes(self.tmp / "lanes", size=3), cell_runner=cell, verifier_runner=no_findings)
        self.assertTrue(out["all_merged"], out)
        self.assertEqual(active["most"], 1)
        self.assertEqual([s["task"] for s in seen], ids)         # one after another, in contract order
        for i, s in enumerate(seen):
            self.assertEqual(s["building"], [s["task"]])          # no other task's cell was running
            self.assertEqual(s["merged"], ids[:i])                # every earlier task had merged first
            self.assertEqual(s["lane"], "lane-1")                 # lanes 2 and 3 stayed free

    # -- FR-F7: each escalation charged to its task and round ----------------------------------

    def test_FR_F7_AC_1_an_escalation_is_recorded_against_its_task_and_round_with_the_final_model(self):
        p = self.compiled()
        rounds = []

        def cell(lane_path, prompt):
            rounds.append(prompt)
            if len(rounds) == 1:                                  # round 0: the local model, no escalation
                return dict(lazy_cell(lane_path, prompt), model="local-builder")
            return dict(good_cell(lane_path, prompt), model="cloud-builder", escalation=dict(ESCALATION))

        out = build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=cell,
                         verifier_runner=no_findings, max_rounds=1)
        self.assertEqual(out["status"], "merged")
        cells = [r["event"]["payload"] for r in p.ledger().of_kind("cell_ran")]
        self.assertEqual([(c["task"], c["round"], c["escalated"], c["final_model"]) for c in cells],
                         [("T-001", 0, False, "local-builder"), ("T-001", 1, True, "cloud-builder")])
        self.assertEqual([r["cell"]["escalated"] for r in out["rounds"]], [False, True])
        shown = next(t for t in timeline(p)["tasks"] if t["task"] == "T-001")["rounds"]
        self.assertEqual([(r["round"], r["escalated"], r["model"]) for r in shown],
                         [(0, False, "local-builder"), (1, True, "cloud-builder")])
        stats = model_reliability(self.factory)
        self.assertEqual((stats["cloud-builder"]["cells"], stats["cloud-builder"]["escalated"]), (1, 1))
        self.assertEqual((stats["local-builder"]["cells"], stats["local-builder"]["escalated"]), (1, 0))

    def test_FR_F7_AC_2_the_run_a_cell_just_made_is_charged_to_its_task_and_round(self):
        p = self.new()
        audit = self.tmp / "lane-1" / ".gnomon-audit"
        audit.mkdir(parents=True)
        base = json.loads((FIX / "analyst-run.record.json").read_text(encoding="utf-8"))
        older = dict(base, role="builder", model="older-builder")
        (audit / "task-older.record.json").write_text(json.dumps(older), encoding="utf-8")
        past = time.time() - 600
        os.utime(audit / "task-older.record.json", (past, past))  # a run from an earlier round
        started = time.time()
        record = dict(base, role="builder", model="cloud-builder", escalation=dict(ESCALATION))
        (audit / "task-latest.record.json").write_text(json.dumps(record), encoding="utf-8")
        trail = audit / f"{record['session']}.jsonl"
        shutil.copy(FIX / "analyst-run.jsonl", trail)

        payload = ingest_latest_run(p, self.tmp / "lane-1", started, task="T-001", round_no=1)
        runs = [r["event"]["payload"] for r in p.ledger().of_kind("gnomon_run")]
        self.assertEqual(runs, [payload])                         # one run charged, the older one not again
        self.assertEqual((payload["task"], payload["round"]), ("T-001", 1))
        self.assertEqual(payload["model"], "cloud-builder")       # the model the escalated run ended on
        self.assertTrue(payload["chain"]["intact"])
        self.assertEqual((payload["tokens"]["in"], payload["tokens"]["out"]),
                         (record["volatile"]["tokens_in"], record["volatile"]["tokens_out"]))
        self.assertFalse(payload["cost"]["measured"])            # no price for it in the table: not measured
        self.assertIsNone(payload["cost"]["amount"])             # never a zero that looks free

        prices = {"currency": "USD", "models": {"cloud-builder": {"input": 1.0, "output": 2.0}}}
        priced = ingest(p, record, trail, task="T-001", round_no=1, prices=prices)
        self.assertEqual((priced["task"], priced["round"]), ("T-001", 1))
        self.assertTrue(priced["cost"]["measured"])
        self.assertEqual(priced["cost"]["kind"], "cloud")
        self.assertGreater(priced["cost"]["amount"], 0)


if __name__ == "__main__":
    unittest.main()
