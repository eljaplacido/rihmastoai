"""Brief section D (workspace and artifacts), measured against what the kernel really does.

FR-D1 and FR-D2 are partly built and FR-D3 is not built; contract/deferred/d.json says what is
missing. These tests cover the built part only: the hand-off between a builder cell and the gate,
round after round, through `kernel.dispatch.build_task`, with the project ledger as the record of
the paths tried. Every scenario runs the real kernel (intake, spec, compile, lanes, gate) with
scripted cells from factory_fakes.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import GOOD_ROUTES, FactoryTestCase, good_cell, model, no_findings  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task, resolve_escalations  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.workspace import CONTEXT_FILE, MCP_FILE, open_workspace  # noqa: E402
from mcp.server import RihmaMCP  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
HEADING = "## Objections from the last round"


class RecordingCell:
    """A builder cell that writes the correct product, leaves a mark of its own round so that each
    round is a revision of its own, and keeps every envelope it was handed."""

    def __init__(self, model_name="fake-builder"):
        self.prompts = []
        self.model_name = model_name

    def __call__(self, lane_path, prompt):
        n = len(self.prompts)
        self.prompts.append(prompt)
        good_cell(lane_path, prompt)
        Path(lane_path, "app", "routes.py").write_text(GOOD_ROUTES + f"\n# attempt {n}\n", encoding="utf-8",
                                                      newline="\n")
        return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 3,
                "model": self.model_name, "output": "done"}


def objecting_verifier():
    """A verifier that finds one high, in-scope problem each round, worded for that round."""
    calls = []

    def runner(prompt):
        n = len(calls)
        calls.append(prompt)
        return "```json\n" + json.dumps({"findings": [{
            "criterion": "R-1-AC-1", "in_scope": True, "severity": "high",
            "finding": f"path {n} loses the item name", "repro": f"POST /items, attempt {n}"}]}) + "\n```"

    return runner


def found(n: int) -> str:
    return f"path {n} loses the item name"


class BriefDCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.lanes_root = self.tmp / "lanes"

    def compiled(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def lanes(self):
        return Lanes(self.lanes_root, size=1)

    @staticmethod
    def payloads(p, kind):
        return [r["event"]["payload"] for r in p.ledger().of_kind(kind)]


class TypedHandOffTest(BriefDCase):
    def test_FR_D1_AC_1_each_round_hands_off_a_revision_pinned_patch_and_the_objections_on_it(self):
        p = self.compiled()
        contract = p.read("contract.json")
        cell = RecordingCell()
        out = build_task(p, "T-001", lanes=self.lanes(), cell_runner=cell, verifier_runner=objecting_verifier(),
                         max_rounds=1)
        self.assertEqual(out["status"], "escalated")
        cells, gates = self.payloads(p, "cell_ran"), self.payloads(p, "gate")
        self.assertEqual([c["round"] for c in cells], [0, 1])
        self.assertEqual([g["round"] for g in gates], [0, 1])
        repo = p.path("repo.git")
        base = _git(repo, "rev-parse", "main")                       # nothing merged: main is still the base
        heads = [c["head"] for c in cells]
        self.assertNotEqual(heads[0], heads[1])                      # each round's patch is its own revision
        for c, g in zip(cells, gates):
            self.assertEqual(g["head"], c["head"])                   # the objections name the revision they judged
            self.assertEqual(_git(repo, "cat-file", "-t", c["head"]), "commit")   # the product repo keeps it
        self.assertEqual(_git(repo, "rev-parse", "cell/T-001"), heads[1])
        self.assertEqual(_git(repo, "merge-base", heads[0], heads[1]), heads[0])  # round 1 builds on round 0
        self.assertEqual(_git(repo, "merge-base", base, heads[0]), base)
        self.assertTrue(any(found(0) in o for o in gates[0]["objections"]), gates[0])
        # the next envelope is pinned to the contract and base revisions and carries those objections word for word
        self.assertNotIn(HEADING, cell.prompts[0])
        nxt = cell.prompts[1]
        self.assertIn(HEADING, nxt)
        self.assertIn(f"Contract {contract['revision'][:19]}", nxt)
        self.assertIn(f"Base revision {base[:12]}", nxt)
        for o in gates[0]["objections"]:
            self.assertIn(f"- {o}", nxt.splitlines())
        # what the ledger records of the hand-off is what the task's own state says
        rounds = p.read("tasks.json")["T-001"]["rounds"]
        self.assertEqual([r["gate"]["head"] for r in rounds], heads)
        self.assertEqual([r["gate"]["objections"] for r in rounds], [g["objections"] for g in gates])


class PathsTriedTest(BriefDCase):
    def test_FR_D2_AC_1_every_round_is_in_the_ledger_and_a_cell_sees_only_the_last_rounds_objections(self):
        p = self.compiled()
        cell = RecordingCell()
        out = build_task(p, "T-001", lanes=self.lanes(), cell_runner=cell, verifier_runner=objecting_verifier(),
                         max_rounds=2)
        self.assertEqual(out["status"], "escalated")
        self.assertEqual(len(cell.prompts), 3)
        gates = self.payloads(p, "gate")
        self.assertEqual([(g["task"], g["round"], g["verdict"]) for g in gates],
                         [("T-001", 0, "failed"), ("T-001", 1, "failed"), ("T-001", 2, "failed")])
        for n, g in enumerate(gates):                                  # every path tried, with what it met
            self.assertTrue(any(found(n) in o for o in g["objections"]), g)
            self.assertEqual(g["signals"]["verifier"], "failed")
        self.assertTrue(p.ledger().verify(head=p.ledger().head()).intact)
        # each cell's context: the envelope carries the last round's objections and nothing older
        self.assertFalse(any(found(k) in cell.prompts[0] for k in range(3)))
        self.assertIn(found(0), cell.prompts[1])
        self.assertIn(found(1), cell.prompts[2])
        self.assertNotIn(found(0), cell.prompts[2])
        self.assertNotIn(found(2), cell.prompts[2])
        self.assertEqual(cell.prompts[2].count(HEADING), 1)

    def test_FR_D2_AC_2_a_retried_task_starts_with_no_history_in_its_envelope_while_the_ledger_keeps_it(self):
        p = self.compiled()
        first = RecordingCell("model-a")
        out = build_task(p, "T-001", lanes=self.lanes(), cell_runner=first, verifier_runner=objecting_verifier(),
                         max_rounds=0)
        self.assertEqual(out["status"], "escalated")
        canon = Canon(p)
        canon.decide(out["card"], "retry", person="Aino", persona="developer")
        self.assertEqual(resolve_escalations(p), [out["card"]])
        self.assertEqual(p.read("tasks.json")["T-001"]["rounds"], [])  # the task's state forgets the attempt
        again = RecordingCell("model-b")
        out2 = build_task(p, "T-001", lanes=self.lanes(), cell_runner=again, verifier_runner=no_findings)
        self.assertEqual(out2["status"], "merged")
        self.assertEqual(len(again.prompts), 1)
        self.assertNotIn(HEADING, again.prompts[0])                    # no earlier path in the new cell's context
        self.assertNotIn(found(0), again.prompts[0])
        gates = self.payloads(p, "gate")                               # the ledger keeps both attempts
        self.assertEqual([g["verdict"] for g in gates], ["failed", "passed"])
        self.assertTrue(any(found(0) in o for o in gates[0]["objections"]), gates[0])
        self.assertEqual(self.payloads(p, "escalation_resolved")[0]["verdict"], "retry")
        self.assertEqual([c["model"] for c in self.payloads(p, "cell_ran")], ["model-a", "model-b"])
        self.assertTrue(p.ledger().verify(head=p.ledger().head()).intact)
        self.assertEqual(len(p.read("tasks.json")["T-001"]["rounds"]), 1)

    def test_FR_D2_AC_3_a_persons_workspace_gets_earlier_rounds_by_reference_not_in_its_context(self):
        p = self.compiled()
        out = build_task(p, "T-001", lanes=self.lanes(), cell_runner=RecordingCell(),
                         verifier_runner=objecting_verifier(), max_rounds=0)
        self.assertEqual(out["status"], "escalated")
        gate = self.payloads(p, "gate")[0]
        ws = open_workspace(p, person="Aino", persona="developer", agent="shell", root=self.lanes_root)
        path = Path(ws["path"])
        context = (path / CONTEXT_FILE).read_text(encoding="utf-8")
        self.assertIn(out["card"], context)                            # the escalation, by its card id
        self.assertIn("T-001 (escalated)", context)
        self.assertNotIn(found(0), context)                            # none of the objections themselves
        self.assertNotIn("verifier:", context)
        args = json.loads((path / MCP_FILE).read_text(encoding="utf-8"))["mcpServers"]["rihma"]["args"]
        home = Path(args[args.index("--home") + 1])
        self.assertEqual(home, self.factory.home.resolve())
        # the workspace's MCP server serves the project ledger, where the earlier round is kept whole
        server = RihmaMCP(self.factory, person="Aino", persona="developer", lanes_root=self.lanes_root)
        answer = server.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                                "params": {"uri": f"rihma://projects/{p.pid}/ledger"}})
        self.assertIn("result", answer, answer)
        body = json.loads(answer["result"]["contents"][0]["text"])
        served = [r["payload"] for r in body["records"] if r["kind"] == "gate"]
        self.assertEqual(len(served), 1)
        self.assertEqual(served[0]["head"], gate["head"])
        self.assertEqual(served[0]["objections"], gate["objections"])
        self.assertTrue(any(found(0) in o for o in served[0]["objections"]))


if __name__ == "__main__":
    unittest.main()
