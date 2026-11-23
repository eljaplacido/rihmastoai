"""Brief section C: work envelopes, cells and the Gnomon integration (FR-C1, FR-C3, FR-C4).

These tests measure what the kernel does today, through its own code paths: the envelope it
writes, the dispatcher that leases a lane and starts Gnomon, the gate that runs the verifier, and
the live view the cockpit serves. Where a Gnomon run is needed, ``GNOMON_CMD`` points at a
stand-in script, so the kernel's real invocation (`kernel.model.run_gnomon_task`) is exercised:
the stand-in records how it was started, the lease it ran under and its role's block on the
lane's surface, then answers as that role.

What section C asks for and the kernel does not do is recorded in contract/deferred/c.json.
"""

import contextlib
import copy
import json
import os
import shlex
import sys
import threading
import tomllib
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, model, no_findings  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task, envelope  # noqa: E402
from kernel.gate import verifier_prompt  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git, load_routing, model_family, write_product_surface  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import live  # noqa: E402
from kernel.store import write_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."

# A stand-in for `gnomon task`. It records how the kernel started it (argv, working directory,
# the task file's text), whether the lane was leased while it ran (the lease file's holder, and
# whether the lane's lock could be taken from outside), and its role's block on the lane's
# compiled surface. Then it answers as that role: a builder from factory_fakes, a verifier with
# the findings the test chose.
FAKE_GNOMON = r'''
import json
import os
import sys
import tomllib
from pathlib import Path

root = os.environ["FAKE_GNOMON_ROOT"]
sys.path[:0] = [root, os.path.join(root, "tests")]
from factory_fakes import good_cell, lazy_cell
from kernel.filelock import LockHeld, locked
from kernel.lanes import lock_path

args = sys.argv[1:]
role = args[args.index("--role") + 1]
task = Path(args[args.index("--task-file") + 1]).read_text(encoding="utf-8")
cwd = Path.cwd()
lease = cwd.parent / f".{cwd.name}.lease.json"
try:
    with locked(lock_path(cwd), blocking=False):
        lane_free = True
except LockHeld:
    lane_free = False
surface = tomllib.loads((cwd / ".gnomon" / "roles.toml").read_text(encoding="utf-8"))["roles"]
entry = {"argv": args, "cwd": str(cwd), "role": role, "task": task, "lane_free": lane_free,
         "holder": json.loads(lease.read_text(encoding="utf-8")).get("holder") if lease.exists() else None,
         "surface": surface.get(role)}
with open(os.environ["FAKE_GNOMON_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(entry) + "\n")
if role == "builder":
    cell = {"good": good_cell, "lazy": lazy_cell}[os.environ["FAKE_GNOMON_BUILDER"]]
    record = cell(cwd, task)
else:
    findings = json.loads(os.environ["FAKE_GNOMON_FINDINGS"])
    record = {"code": 0, "bucket": "result", "stop_reason": "answered", "model": "fake-verifier",
              "output": "```json\n" + json.dumps({"findings": findings}) + "\n```"}
print(json.dumps(record))
'''

HIGH_FINDING = {"criterion": "R-1-AC-1", "in_scope": True, "severity": "high",
                "finding": "an item with a blank name is stored", "repro": "POST /items {\"name\": \" \"}"}


class BriefCTestCase(FactoryTestCase):
    def compiled(self, title="Equipment loans"):
        p = self.new(mode="assume", title=title)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    @contextlib.contextmanager
    def gnomon(self, *, builder="good", findings=()):
        """Point the kernel's Gnomon command at the stand-in for the duration."""
        script = self.tmp / "fake_gnomon.py"
        script.write_text(FAKE_GNOMON, encoding="utf-8", newline="\n")
        self.gnomon_log = self.tmp / "gnomon-runs.jsonl"
        env = {"GNOMON_CMD": shlex.join([Path(sys.executable).as_posix(), script.as_posix()]),
               "FAKE_GNOMON_ROOT": str(ROOT), "FAKE_GNOMON_LOG": str(self.gnomon_log),
               "FAKE_GNOMON_BUILDER": builder, "FAKE_GNOMON_FINDINGS": json.dumps(list(findings))}
        with mock.patch.dict(os.environ, env):
            yield

    def runs(self) -> list:
        if not self.gnomon_log.exists():
            return []
        return [json.loads(line) for line in self.gnomon_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def main_commits(p) -> int:
        return len(_git(p.path("repo.git"), "log", "--oneline", "main").splitlines())


class EnvelopeTest(BriefCTestCase):
    """FR-C1: the envelope a unit of work is sent in."""

    def test_FR_C1_AC_1_the_envelope_names_goal_revisions_requirements_scope_and_required_evidence(self):
        p = self.compiled()
        contract = p.read("contract.json")
        base = "0123456789ab" + "0" * 28
        text = envelope(p, contract, "T-001", base=base)
        self.assertIn("- **R-1**: A team member can add an item with a name.", text)       # goal, by requirement
        self.assertIn(f"Contract {contract['revision'][:19]}.", text)                        # contract revision
        self.assertIn("Base revision 0123456789ab.", text)                                  # base revision
        self.assertIn("Write only: app/**, tests/**.", text)                                # write scope
        self.assertIn("- **R-1-AC-1**: given no items; when POST /items with a name; "      # required evidence
                      "then 201 and the item has an id", text)
        self.assertIn("named `test_<ID with hyphens as underscores>_...`", text)
        self.assertIn("it must fail before your code exists", text)
        self.assertNotIn("A loan needs the approver's name.", text)                          # only what T-001 serves

        # Another revision, base and scope: the envelope says so, and nothing of the first remains.
        other = copy.deepcopy(contract)
        other["revision"] = "sha256:" + "f" * 64
        next(t for t in other["tasks"] if t["id"] == "T-001")["scope"]["write"] = ["app/items.py", "tests/test_items.py"]
        text2 = envelope(p, other, "T-001", base="fedcba987654" + "1" * 28)
        self.assertIn("Contract sha256:ffffffffffff.", text2)
        self.assertIn("Base revision fedcba987654.", text2)
        self.assertIn("Write only: app/items.py, tests/test_items.py.", text2)
        self.assertNotIn("app/**", text2)
        self.assertNotIn("0123456789ab", text2)

        # Another task: its own requirement and criteria, none of T-001's.
        text3 = envelope(p, contract, "T-002", base=base)
        self.assertIn("# Envelope T-002", text3)
        self.assertIn("- **R-2**: A loan needs the approver's name.", text3)
        self.assertIn("- **R-2-AC-1**:", text3)
        self.assertNotIn("R-1-AC-1", text3)

    def test_FR_C1_AC_2_a_cell_runs_its_envelope_as_the_task_file_with_its_role_and_wall_time_budget(self):
        p = self.compiled()
        contract = p.read("contract.json")
        base = _git(p.path("repo.git"), "rev-parse", "main")
        lanes = Lanes(self.tmp / "lanes", size=1)
        with self.gnomon(builder="good"):
            out = build_task(p, "T-001", lanes=lanes, deadline=900, lane_wait=0)
        self.assertEqual(out["status"], "merged", out)
        builder = [r for r in self.runs() if r["role"] == "builder"]
        self.assertEqual(len(builder), 1)
        argv = builder[0]["argv"]
        self.assertEqual(argv[0], "task")
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("--role") + 1], "builder")                 # the role travels with it
        self.assertEqual(argv[argv.index("--deadline") + 1], "900")                 # and the wall-time budget
        self.assertEqual(builder[0]["task"], envelope(p, contract, "T-001", base=base))  # the task file is the envelope
        steps = builder[0]["surface"]                                               # the role is on the lane's surface
        self.assertIsNotNone(steps, "the role the cell runs as is not defined on the lane's surface")
        self.assertIsInstance(steps["max_steps"], int)
        self.assertGreater(steps["max_steps"], 0)
        self.assertGreaterEqual(steps["max_steps_total"], steps["max_steps"])
        tasks_dir = Path(builder[0]["cwd"]) / ".factory-tasks"
        self.assertEqual(list(tasks_dir.iterdir()), [])                             # the task file is not left behind


class RolesTest(BriefCTestCase):
    """FR-C3: the roles a cell runs as, each a Gnomon surface. Built: the builder and the verifier."""

    def test_FR_C3_AC_1_a_product_lane_surface_holds_a_scoped_builder_and_a_read_only_verifier_on_another_family(self):
        routing = load_routing()
        wide, narrow = self.tmp / "wide", self.tmp / "narrow"
        write_product_surface(wide, routing, ["app/**", "tests/**"])
        write_product_surface(narrow, routing, ["src/reports/**"])
        surfaces = {}
        for name, path in (("wide", wide), ("narrow", narrow)):
            surfaces[name] = tomllib.loads((path / ".gnomon" / "roles.toml").read_text(encoding="utf-8"))["roles"]
        self.assertEqual(surfaces["wide"]["builder"]["write_allow"], ["app/**", "tests/**"])
        self.assertEqual(surfaces["narrow"]["builder"]["write_allow"], ["src/reports/**"])
        for roles in surfaces.values():
            self.assertEqual(set(roles), {"builder", "verifier"})
            self.assertTrue({"write", "edit", "bash"} <= set(roles["builder"]["tools"]))
            self.assertTrue(set(roles["verifier"]["tools"]) <= {"read", "glob", "grep"})
            self.assertNotIn("write_allow", roles["verifier"])
            self.assertNotIn("fallback", roles["verifier"])
            self.assertEqual(roles["builder"]["model"], routing["roles"]["builder"]["model"])
            self.assertEqual(roles["verifier"]["model"], routing["roles"]["verifier"]["model"])
        self.assertNotEqual(model_family(routing, "builder"), model_family(routing, "verifier"))

        same_family = copy.deepcopy(routing)
        same_family["roles"]["verifier"] = {k: v for k, v in routing["roles"]["builder"].items() if k != "fallback"}
        write_json(self.tmp / "routing.json", same_family)
        with self.assertRaises(ValueError) as caught:
            load_routing(self.tmp / "routing.json")
        self.assertIn("different model family", str(caught.exception))

    def test_FR_C3_AC_2_the_builder_runs_in_a_lane_leased_to_its_task_and_the_verifier_reviews_in_that_lane(self):
        p = self.compiled()
        contract = p.read("contract.json")
        base = _git(p.path("repo.git"), "rev-parse", "main")
        root = self.tmp / "lanes"
        with self.gnomon(builder="good"):
            out = build_task(p, "T-001", lanes=Lanes(root, size=1), lane_wait=0)
        self.assertEqual(out["status"], "merged", out)
        runs = self.runs()
        self.assertEqual([r["role"] for r in runs], ["builder", "verifier"])
        builder, verifier = runs
        self.assertEqual(Path(builder["cwd"]).name, "lane-1")
        self.assertEqual(builder["cwd"], verifier["cwd"])
        for run in runs:
            self.assertEqual(run["holder"], f"{p.pid}:T-001")           # leased to its task while it ran
            self.assertFalse(run["lane_free"], f"{run['role']} ran in a lane nobody held")
        self.assertEqual(verifier["task"], verifier_prompt(contract, "T-001", base))
        self.assertIn("You may read files and run nothing else", verifier["task"])
        self.assertIn("write", builder["surface"]["tools"])             # each under its own role's block
        self.assertEqual(builder["surface"]["write_allow"], ["app/**", "tests/**"])
        self.assertTrue(set(verifier["surface"]["tools"]) <= {"read", "glob", "grep"})
        self.assertIsNone(json.loads((root / ".lane-1.lease.json").read_text(encoding="utf-8"))["holder"])
        with Lanes(root, size=1).lease("next:T-001") as lane:          # released: the next holder gets it
            self.assertEqual(lane.name, "lane-1")

    def test_FR_C3_AC_3_a_builder_whose_tests_pass_without_its_change_stays_off_main(self):
        p = self.compiled()
        with self.gnomon(builder="lazy"):
            out = build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), max_rounds=0, lane_wait=0)
        self.assertEqual(out["status"], "escalated")
        gate = out["rounds"][-1]["gate"]
        signals = {s["name"]: s["verdict"] for s in gate["signals"]}
        self.assertEqual(signals["fail_first"], "failed")
        self.assertEqual((signals["tests"], signals["trace"]), ("passed", "passed"))  # only fail-first catches it
        self.assertTrue(any(o.startswith("fail_first:") for o in gate["objections"]), gate["objections"])
        self.assertEqual(self.main_commits(p), 1)                       # nothing reached main

    def test_FR_C3_AC_3_a_high_in_scope_verifier_finding_keeps_a_change_off_main_and_a_minor_one_does_not(self):
        blocked = self.compiled()
        with self.gnomon(builder="good", findings=[HIGH_FINDING]):
            out = build_task(blocked, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), max_rounds=0, lane_wait=0)
        self.assertEqual(out["status"], "escalated")
        gate = out["rounds"][-1]["gate"]
        signals = {s["name"]: s["verdict"] for s in gate["signals"]}
        self.assertEqual(signals, {"tests": "passed", "trace": "passed", "fail_first": "passed", "verifier": "failed"})
        self.assertTrue(any("an item with a blank name is stored" in o for o in gate["objections"]), gate["objections"])
        self.assertEqual(self.main_commits(blocked), 1)

        minor = [dict(HIGH_FINDING, severity="low"), dict(HIGH_FINDING, in_scope=False)]
        passed = self.compiled(title="Tool loans")
        with self.gnomon(builder="good", findings=minor):
            out = build_task(passed, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), max_rounds=0, lane_wait=0)
        self.assertEqual(out["status"], "merged", out)
        self.assertEqual(self.main_commits(passed), 2)


class LiveProgressTest(BriefCTestCase):
    """FR-C4: live progress of a running cell reaches the factory. Built: read from Gnomon's audit trail."""

    TRAIL = [{"seq": 0, "kind": "session_start", "role": "builder"},
             {"seq": 1, "kind": "model_call", "model": "deepseek-v4-pro"},
             {"seq": 2, "kind": "tool_call", "tool": "write", "target": "app/routes.py", "ts": "2026-11-23T10:00:01Z"},
             {"seq": 3, "kind": "tool_call", "tool": "bash", "target": "python3 -m unittest discover -s tests",
              "ts": "2026-11-23T10:00:05Z", "bucket": "result"},
             {"seq": 4, "kind": "session_end"}]

    def cell_writing_trail(self, on_step):
        """A builder cell that does good_cell's work while appending Gnomon audit records to its lane,
        calling ``on_step(index)`` after each record."""
        def cell(lane_path, prompt):
            trail = Path(lane_path) / ".gnomon-audit" / "task-live.jsonl"
            trail.parent.mkdir(parents=True, exist_ok=True)
            record = None
            for i, rec in enumerate(self.TRAIL):
                if rec["kind"] == "tool_call" and record is None:
                    record = good_cell(lane_path, prompt)
                with trail.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps(rec) + "\n")
                on_step(i)
            return record
        return cell

    def test_FR_C4_AC_1_while_a_builder_cell_runs_the_live_view_follows_its_audit_trail_step_by_step(self):
        p = self.compiled()
        bystander = self.new(title="Other loans")
        root = self.tmp / "lanes"
        self.assertFalse(live(p, lanes_root=root)["running"])
        seen, others = [], []

        def on_step(_):
            seen.append(live(p, lanes_root=root))
            others.append(live(bystander, lanes_root=root))

        out = build_task(p, "T-001", lanes=Lanes(root, size=1), cell_runner=self.cell_writing_trail(on_step),
                         verifier_runner=no_findings, lane_wait=0)
        self.assertEqual(out["status"], "merged", out)
        self.assertEqual({(s["running"], s["task"], s["lane"], s["role"]) for s in seen},
                         {(True, "T-001", "lane-1", "builder")})
        self.assertEqual([s["steps"] for s in seen], [0, 0, 1, 2, 2])
        self.assertEqual([(s["last"] or {}).get("tool") for s in seen], [None, None, "write", "bash", "bash"])
        self.assertEqual(seen[3]["last"]["target"], "python3 -m unittest discover -s tests")
        self.assertEqual([s["model"] for s in seen], [None] + ["deepseek-v4-pro"] * 4)
        self.assertEqual([s["ended"] for s in seen], [False, False, False, False, True])
        self.assertFalse(any(o["running"] for o in others))             # a project holding no lane runs nothing
        after = live(p, lanes_root=root)
        self.assertFalse(after["running"])                               # the lane is released
        self.assertIn("no lane", after["why"])

    def test_FR_C4_AC_2_the_cockpit_serves_the_running_cells_progress_while_the_dispatcher_builds(self):
        p = self.compiled()
        root = self.tmp / "gf-lanes"
        server, bootstrap = make_server(self.factory, 0)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def call(method, path, body=None, token=None):
            headers = {"Origin": server.origin} if method != "GET" else {}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            data = json.dumps(body).encode("utf-8") if body is not None else None
            if data:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(server.origin + path, data=data, headers=headers, method=method)
            try:
                with direct.open(req, timeout=10) as res:
                    return res.status, json.loads(res.read() or b"null")
            except urllib.error.HTTPError as exc:
                with exc:
                    return exc.code, json.loads(exc.read() or b"null")

        try:
            status, body = call("POST", "/auth", {"bootstrap": bootstrap})
            self.assertEqual(status, 200, body)
            token = body["token"]

            def view():
                lv = call("GET", f"/api/projects/{p.pid}/live", token=token)
                rows = call("GET", "/api/projects", token=token)
                self.assertEqual((lv[0], rows[0]), (200, 200))
                return lv[1], next(r for r in rows[1] if r["id"] == p.pid)["running"]

            during = {}

            def on_step(i):
                if i == 3:  # the cell has written, then run the suite; its session is still open
                    during["live"], during["running"] = view()

            with mock.patch.dict(os.environ, {"GF_LANES": str(root)}):
                before = view()
                out = build_task(p, "T-001", lanes=Lanes(root, size=1), cell_runner=self.cell_writing_trail(on_step),
                                 verifier_runner=no_findings, lane_wait=0)
                after = view()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
        self.assertEqual(out["status"], "merged", out)
        self.assertEqual((before[0]["running"], before[1]), (False, False))
        lv = during["live"]
        self.assertEqual((lv["running"], lv["task"], lv["role"], lv["model"], lv["steps"], lv["ended"]),
                         (True, "T-001", "builder", "deepseek-v4-pro", 2, False))
        self.assertEqual(lv["last"]["tool"], "bash")
        self.assertTrue(during["running"])                                # the project list marks it running
        self.assertEqual((after[0]["running"], after[1]), (False, False))


if __name__ == "__main__":
    unittest.main()
