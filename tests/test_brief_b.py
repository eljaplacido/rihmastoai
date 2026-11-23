"""Brief section B (shaping and Cynefin routing), measured against what the kernel does.

FR-B1 to FR-B3 (a Cynefin domain per work item, its classifier in shadow, routing by domain as a
pre-registered hypothesis) are not built: contract/deferred/b.json says what each would take.

FR-B4 is: holdout acceptance scenarios are written outside the build and kept out of reach of
building agents. These tests drive the real kernel (compile, the holdout author through the
CLI's Gnomon model in the analyst lane, dispatch with builder cells, a person's workspace) and
look at what a building agent could actually reach. Each holdout scenario carries a marker no
other text has, so finding it anywhere outside the custody is a leak.

One path is not covered, because it leaks: a product-defect ruling copies the failing step's
expectations into a visible criterion (kernel/rulings.py apply_rulings). It is recorded in
contract/deferred/b.json.
"""

import json
import os
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, good_cell, model, no_findings, script  # noqa: E402

from kernel import cli  # noqa: E402
from kernel.compile import author_holdouts, compile_project  # noqa: E402
from kernel.dispatch import build, build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.workspace import CONTEXT_FILE, open_workspace  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
HOLDOUTS = ("R-1-AC-2", "R-4-AC-2")          # the holdout and the probe criterion of the fakes' spec
MARKERS = ("b4-custody-r1ac2-7f3e", "b4-custody-r4ac2-91c0")


def marked_script(prompt: str, role: str) -> str:
    """The fakes' script, except that the holdout author writes scenarios carrying the markers."""
    if "You write acceptance scenarios" in prompt:
        return "```json\n" + json.dumps({"scenarios": [
            {"criterion": "R-1-AC-2", "steps": [
                {"method": "POST", "path": "/items", "body": {"name": MARKERS[0]}, "expect_status": 201},
                {"method": "GET", "path": "/items", "expect_status": 200, "expect_contains": MARKERS[0]}]},
            {"criterion": "R-4-AC-2", "steps": [
                {"method": "GET", "path": "/health", "expect_status": 200, "max_ms": 500,
                 "expect_not_contains": MARKERS[1]}]}]}) + "\n```"
    return script(prompt, role)


def compiled(case):
    p = case.new(mode="assume")
    intake(p, IDEA, model=model(), requested_by="Aino")
    make_spec(p, model=model())
    compile_project(p)
    return p


def files_under(root: Path) -> dict:
    """Every file under ``root`` outside .git, by its posix relative path, with its text."""
    out = {}
    for f in sorted(Path(root).rglob("*")):
        rel = f.relative_to(root)
        if ".git" in rel.parts or not f.is_file():
            continue
        out[rel.as_posix()] = f.read_text(encoding="utf-8", errors="replace")
    return out


class SpyCell:
    """A builder cell that records what it was given and what its lane holds, then builds."""

    def __init__(self):
        self.prompts, self.lanes = [], []

    def __call__(self, lane_path, prompt):
        self.prompts.append(prompt)
        self.lanes.append(files_under(Path(lane_path)))
        return generic_cell(lane_path, prompt)


class HoldoutCustodyTest(FactoryTestCase):
    def test_FR_B4_AC_1_the_holdout_author_writes_in_the_analyst_lane_from_the_spec_never_the_code(self):
        p = compiled(self)
        out = build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=good_cell,
                         verifier_runner=no_findings)
        self.assertEqual(out["status"], "merged")
        repo = p.path("repo.git")
        routes = _git(repo, "show", "main:app/routes.py")
        self.assertIn("def add_item", routes)               # the product's code exists on main
        self.assertIn("name is required", routes)

        calls = []

        def gnomon(cwd, prompt, *, role, timeout=1800, deadline=None, extra=()):
            calls.append({"cwd": Path(cwd), "role": role, "prompt": prompt})
            return {"bucket": "result", "stop_reason": "answered", "output": script(prompt, role)}

        pool = self.tmp / "pool"
        with mock.patch.dict(os.environ, {"GF_LANES": str(pool)}), \
                mock.patch("kernel.model.run_gnomon_task", side_effect=gnomon):
            saved = author_holdouts(p, model=cli._model())   # the model the CLI's pipeline uses

        self.assertEqual(sorted(saved), list(HOLDOUTS))
        self.assertEqual([c["role"] for c in calls], ["holdout_author"])     # its own role, not the builder
        analyst = (pool / "analyst").resolve()
        self.assertEqual(calls[0]["cwd"].resolve(), analyst)                 # asked in the analyst lane
        lane_files = files_under(analyst)
        self.assertIn(".gnomon/roles.toml", lane_files)
        self.assertEqual([f for f in lane_files if not (f.startswith(".gnomon/") or f == ".gitignore")], [])
        roles = tomllib.loads(lane_files[".gnomon/roles.toml"])["roles"]
        self.assertEqual(roles["holdout_author"]["tools"], [])               # it cannot read anything
        self.assertNotIn("builder", roles)

        prompt = calls[0]["prompt"]
        self.assertIn("A loan needs the approver's name.", prompt)           # the spec
        self.assertIn("- POST /items:", prompt)                              # and its interface
        for line in ("def add_item", "name is required", "load_data("):      # never the product's code
            self.assertNotIn(line, prompt)

        for cid in saved:
            doc = json.loads((p.holdouts_dir / f"{cid}.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["author_role"], "holdout_author")
        product_roles = tomllib.loads(_git(repo, "show", "main:.gnomon/roles.toml"))["roles"]
        self.assertEqual(set(product_roles), {"builder", "verifier"})       # no holdout author where code lives

    def test_FR_B4_AC_2_no_builder_envelope_lane_commit_or_workspace_reaches_a_holdout_scenario(self):
        p = compiled(self)
        self.assertEqual(sorted(author_holdouts(p, model=FakeModel(marked_script))), list(HOLDOUTS))
        custody = {cid: (p.holdouts_dir / f"{cid}.json").read_bytes() for cid in HOLDOUTS}
        for marker, body in zip(MARKERS, custody.values()):
            self.assertIn(marker.encode(), body)          # the markers are there to be found

        spy = SpyCell()
        lanes = Lanes(self.tmp / "lanes", size=1)
        out = build(p, lanes=lanes, cell_runner=spy, verifier_runner=no_findings)
        self.assertTrue(out["all_merged"], out)
        self.assertEqual(len(spy.prompts), len(p.read("contract.json")["tasks"]))

        for prompt in spy.prompts:
            for cid in HOLDOUTS:
                self.assertNotIn(cid, prompt)             # the envelope never names a holdout or probe criterion
            for marker in MARKERS:
                self.assertNotIn(marker, prompt)
        self.assertIn("checked end to end against the running service", spy.prompts[0])
        for seen in spy.lanes:
            self.assertIn("contract.json", seen)          # the cell's whole lane was read
            leaks = [(f, m) for f, text in seen.items() for m in MARKERS if m in text]
            self.assertEqual(leaks, [])

        history = _git(p.path("repo.git"), "log", "--all", "-p", "--format=%H")
        self.assertIn("R_1_AC_1", history)                # every commit's patch is in it
        for marker in MARKERS:
            self.assertNotIn(marker, history)
        names = _git(p.path("repo.git"), "log", "--all", "--name-only", "--format=")
        self.assertFalse([n for n in names.splitlines() if n.endswith(tuple(f"{c}.json" for c in HOLDOUTS))])

        ws = open_workspace(p, person="Aino", persona="developer", agent="shell", root=self.tmp / "lanes")
        seen = files_under(Path(ws["path"]))
        self.assertIn(CONTEXT_FILE, seen)
        self.assertIn("R-1-AC-1", seen[CONTEXT_FILE])
        self.assertEqual([(f, m) for f, text in seen.items() for m in MARKERS if m in text], [])

        for cid, body in custody.items():                 # and the build changed nothing in the custody
            self.assertEqual((p.holdouts_dir / f"{cid}.json").read_bytes(), body)


if __name__ == "__main__":
    unittest.main()
