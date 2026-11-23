import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, good_cell, model, no_findings  # noqa: E402

from kernel.canon import DecisionRefused  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build, build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.safestop import request_pause, resume  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import live, now, try_it  # noqa: E402
from kernel.store import write_json  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class LiveTest(FactoryTestCase):
    def compiled(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def test_FR_J3_AC_1_a_pause_stops_at_the_next_safe_point_and_waits_for_a_person(self):
        p = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        with self.assertRaises(DecisionRefused):
            request_pause(p, person="factory", persona="developer")
        with self.assertRaises(DecisionRefused):
            request_pause(p, person="Tiina", persona="end_user")
        build_task(p, "T-001", lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        request_pause(p, person="Olli", persona="operations", reason="the GPU box is being patched")
        out = build(p, lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertEqual(out["results"], {})                                  # nothing started
        self.assertEqual(p.meta["pause"]["stopped_at"], "before T-002")
        self.assertEqual(now(p)["state"], "paused")
        self.assertIn("Olli", now(p)["line"])
        piped = advance(p, model=model(), lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertEqual(piped["state"], "paused")
        resume(p, person="Olli", persona="operations")
        self.assertEqual(build(p, lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)["results"]["T-002"],
                         "merged")
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        for k in ("pause_requested", "paused_at_safe_point", "resumed"):
            self.assertIn(k, kinds)

    def test_FR_T1_AC_7_live_reads_what_the_running_cell_does_from_its_audit_trail(self):
        p = self.compiled()
        root = self.tmp / "lanes"
        self.assertFalse(live(p, lanes_root=root)["running"])
        lane = root / "lane-2"
        (lane / ".gnomon-audit").mkdir(parents=True)
        write_json(root / ".lane-2.lease.json", {"holder": f"{p.pid}:T-003"})
        trail = [{"seq": 0, "kind": "session_start", "role": "builder"},
                 {"seq": 1, "kind": "model_call", "model": "deepseek-v4-pro"},
                 {"seq": 2, "kind": "tool_call", "tool": "write", "target": "app/routes.py", "ts": "t1"},
                 {"seq": 3, "kind": "tool_call", "tool": "bash", "target": "python3 -m unittest discover -s tests", "ts": "t2"}]
        (lane / ".gnomon-audit" / "task-1.jsonl").write_text("\n".join(json.dumps(r) for r in trail) + "\n",
                                                             encoding="utf-8")
        out = live(p, lanes_root=root)
        self.assertEqual((out["task"], out["lane"], out["role"], out["model"], out["steps"]),
                         ("T-003", "lane-2", "builder", "deepseek-v4-pro", 2))
        self.assertEqual(out["last"]["tool"], "bash")
        self.assertFalse(out["ended"])

    def test_FR_R1_AC_1_testers_get_a_checklist_against_the_running_release(self):
        p = self.compiled()
        build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=good_cell,
                   verifier_runner=no_findings)
        self.assertIsNone(try_it(p)["url"])                                   # nothing deployed yet
        write_json(p.path("releases", "1.json"), {"number": 1, "state": "waiting", "steps": [
            {"step": "deploy:demo", "outcome": "passed", "native": {"base_url": "http://127.0.0.1:32774"}}]})
        out = try_it(p)
        self.assertEqual((out["release"], out["env"], out["url"]), (1, "demo", "http://127.0.0.1:32774"))
        first = out["items"][0]
        self.assertEqual(first["criterion"], "R-1-AC-1")
        self.assertTrue(first["text"].startswith("Given no items, when POST /items with a name, check that"))
        self.assertEqual(first["evidence"], "verified")
        self.assertEqual({i["evidence"] for i in out["items"] if i["criterion"] == "R-2-AC-1"}, {"not_measured"})


if __name__ == "__main__":
    unittest.main()
