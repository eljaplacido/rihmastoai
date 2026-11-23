"""Brief section O, spec to verify: FR-O4, FR-O5 and FR-O7, as far as the kernel builds them.

Each test drives the real kernel (compile, dispatch, gate, change loop) on a scripted product.
What is not built is recorded in contract/deferred/o.json, and nothing here pretends it is:
the product surface carries no [verify] block and no [governance.paths] list, the kernel never
runs `gnomon check --base`, and an amendment does not recompile the surface.
"""

import copy
import fnmatch
import json
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import GOOD_ROUTES, GOOD_TEST, FactoryTestCase, generic_cell, model, no_findings  # noqa: E402

from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.change import apply_change, submit, triage  # noqa: E402
from kernel.compile import compile_project, update_repo_surface  # noqa: E402
from kernel.dispatch import build, build_task, envelope, ready_tasks  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git, load_routing  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."

# A real regression test for R-1-AC-3 (the defect amendment's criterion: an empty name is 400, not 500).
EMPTY_NAME_TEST = '''import unittest

import app.routes  # noqa: F401
from app.server import handle


class EmptyNameTest(unittest.TestCase):
    def test_R_1_AC_3_an_empty_name_is_400(self):
        status, body, _ = handle("POST", "/items", {"name": ""})
        self.assertEqual(status, 400)
'''

# A test that names R-1-AC-3 and checks nothing: it passes with or without the behaviour.
VACUOUS_TEST = '''import unittest


class EmptyNameTest(unittest.TestCase):
    def test_R_1_AC_3_always_true(self):
        self.assertTrue(True)
'''


def _write(lane_path, rel: str, text: str) -> None:
    Path(lane_path, rel).write_text(text, encoding="utf-8", newline="\n")


def _record(**extra) -> dict:
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 3, "model": "fake-builder",
            "output": "done", **extra}


def _signals(out: dict) -> dict:
    return {s["name"]: s for s in out["rounds"][-1]["gate"]["signals"]}


class BriefOTest(FactoryTestCase):
    def compiled(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def lanes(self):
        return Lanes(self.tmp / "lanes", size=1)

    def clone(self, p, name: str = "clone") -> Path:
        _git(self.tmp, "clone", "-q", str(p.path("repo.git")), name)
        return self.tmp / name

    def with_defect_criterion(self, p) -> dict:
        """Amend R-1 through the change loop with a defect: T-001 then serves R-1-AC-1 and R-1-AC-3."""
        card = submit(p, persona="end_user", person="Tester", text="Adding an item with an empty name crashes with 500")
        triage(p, card["id"], model=model())
        apply_change(p, card["id"], model=model())
        contract = p.read("contract.json")
        t1 = next(t for t in contract["tasks"] if t["id"] == "T-001")
        self.assertIn("R-1-AC-3", t1["criteria"])
        return contract

    # -- FR-O4: the kernel compiles each cell's Gnomon surface ---------------------------------------

    def test_FR_O4_AC_1_the_compiled_surface_writes_exactly_the_scope_every_task_and_envelope_names(self):
        p = self.compiled()
        contract = p.read("contract.json")
        work = self.clone(p)
        self.assertEqual(_git(work, "rev-list", "--count", "HEAD"), "1")        # the product's first commit
        tracked = set(_git(work, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
        self.assertTrue({".gnomon/policy.toml", ".gnomon/roles.toml", "contract.json"} <= tracked, tracked)
        roles = tomllib.loads((work / ".gnomon" / "roles.toml").read_text(encoding="utf-8"))["roles"]
        scope = roles["builder"]["write_allow"]
        base = _git(work, "rev-parse", "HEAD")
        for task in contract["tasks"]:
            self.assertEqual(task["scope"]["write"], scope, task["id"])
            self.assertIn("Write only: " + ", ".join(scope) + ".", envelope(p, contract, task["id"], base=base))
        for rel in ("app/routes.py", "tests/test_items.py"):                    # where the cells work
            self.assertTrue(any(fnmatch.fnmatch(rel, g) for g in scope), rel)
        protected = [f for f in tracked if f == "contract.json" or f.startswith((".gnomon/", "factory/"))]
        self.assertTrue(any(f.startswith("factory/") for f in protected))
        for rel in protected:                                                   # the contract and the surface
            self.assertFalse(any(fnmatch.fnmatch(rel, g) for g in scope), rel)
        for name, role in roles.items():                                        # only the builder writes
            if name != "builder":
                self.assertNotIn("write_allow", role, name)
                self.assertFalse({"write", "edit"} & set(role["tools"]), name)

    def test_FR_O4_AC_2_each_cell_runs_under_the_surface_the_kernel_last_compiled_on_main(self):
        p = self.compiled()
        routing = load_routing()
        self.assertIn("fallback", routing["roles"]["builder"])
        without = copy.deepcopy(routing)
        del without["roles"]["builder"]["fallback"]
        seen = []

        def observing_cell(lane_path, prompt):
            seen.append({"roles": tomllib.loads(Path(lane_path, ".gnomon", "roles.toml").read_text(encoding="utf-8")),
                         "head": _git(Path(lane_path), "rev-parse", "HEAD")})
            return generic_cell(lane_path, prompt)

        first = update_repo_surface(p, without, reason="test: the builder loses its fallback")
        self.assertEqual(build_task(p, "T-001", lanes=self.lanes(), cell_runner=observing_cell,
                                    verifier_runner=no_findings)["status"], "merged")
        second = update_repo_surface(p, routing, reason="test: the fallback is back")
        self.assertTrue(first and second and first != second)
        self.assertEqual(build_task(p, "T-002", lanes=self.lanes(), cell_runner=observing_cell,
                                    verifier_runner=no_findings)["status"], "merged")
        self.assertEqual([s["head"] for s in seen], [first, second])            # each cell starts at the recompile
        self.assertNotIn("fallback", seen[0]["roles"]["roles"]["builder"])
        self.assertEqual(seen[1]["roles"]["roles"]["builder"]["fallback"]["model"],
                         routing["roles"]["builder"]["fallback"]["model"])
        reasons = [r["event"]["payload"]["reason"] for r in p.ledger().of_kind("surface_updated")]
        self.assertEqual(reasons, ["test: the builder loses its fallback", "test: the fallback is back"])

    # -- FR-O5: the kernel traces each criterion at head and at base -------------------------------

    def test_FR_O5_AC_1_each_criterions_tests_are_run_at_base_one_criterion_at_a_time(self):
        p = self.compiled()
        self.with_defect_criterion(p)

        def half_vacuous(lane_path, prompt):
            _write(lane_path, "app/routes.py", GOOD_ROUTES)
            _write(lane_path, "tests/test_items.py", GOOD_TEST)
            _write(lane_path, "tests/test_empty_name.py", VACUOUS_TEST)
            return _record()

        bad = build_task(p, "T-001", lanes=self.lanes(), cell_runner=half_vacuous, verifier_runner=no_findings,
                         max_rounds=0)
        self.assertEqual(bad["status"], "escalated")
        ff = _signals(bad)["fail_first"]
        self.assertEqual(ff["verdict"], "failed")
        self.assertEqual(ff["native"]["criteria"], ["R-1-AC-1", "R-1-AC-3"])
        self.assertEqual(sorted(ff["native"]["passed_at_base"]), ["R-1-AC-3"])  # R-1-AC-1's test failed at base
        self.assertEqual(sorted(ff["native"]["passed_on_template"]), ["R-1-AC-3"])
        objection = next(o for o in bad["rounds"][-1]["gate"]["objections"] if o.startswith("fail_first:"))
        self.assertIn("R-1-AC-3", objection)
        self.assertNotIn("R-1-AC-1", objection)

        def honest(lane_path, prompt):
            _write(lane_path, "app/routes.py", GOOD_ROUTES)
            _write(lane_path, "tests/test_items.py", GOOD_TEST)
            _write(lane_path, "tests/test_empty_name.py", EMPTY_NAME_TEST)
            return _record()

        good = build_task(p, "T-001", lanes=self.lanes(), cell_runner=honest, verifier_runner=no_findings,
                          max_rounds=0)
        self.assertEqual(good["status"], "merged")
        ff = _signals(good)["fail_first"]
        self.assertEqual((ff["verdict"], ff["native"]["passed_at_base"]), ("passed", {}))
        self.assertEqual(ff["native"]["base"], good["rounds"][-1]["gate"]["base"])

    def test_FR_O5_AC_2_at_head_each_criterion_is_traced_to_the_tests_naming_it_and_every_outcome_kept(self):
        p = self.compiled()
        self.with_defect_criterion(p)

        def half_done(lane_path, prompt):
            _write(lane_path, "app/routes.py", GOOD_ROUTES)
            _write(lane_path, "tests/test_items.py", GOOD_TEST)                  # nothing names R-1-AC-3
            return _record()

        out = build_task(p, "T-001", lanes=self.lanes(), cell_runner=half_done, verifier_runner=no_findings,
                         max_rounds=0)
        self.assertEqual(out["status"], "escalated")
        sig = _signals(out)
        self.assertEqual(sig["tests"]["verdict"], "passed")                     # the suite itself is green
        self.assertEqual(sig["tests"]["native"]["tests"]["test_R_1_AC_1_post_item_returns_201_with_id"], "ok")
        self.assertEqual(sig["trace"]["verdict"], "failed")
        self.assertEqual(sig["trace"]["native"], {"criteria": ["R-1-AC-1", "R-1-AC-3"], "unnamed": ["R-1-AC-3"]})
        self.assertIn("trace: no test names R-1-AC-3", out["rounds"][-1]["gate"]["objections"])
        card = Canon(p).get_card(out["card"])
        self.assertIn("R-1-AC-3", card["body"])
        gate = [r["event"]["payload"] for r in p.ledger().of_kind("gate")][-1]
        self.assertEqual((gate["task"], gate["verdict"], gate["signals"]["trace"]), ("T-001", "failed", "failed"))

    # -- FR-O7: the contract changes only through a signed amendment --------------------------------

    def test_FR_O7_AC_1_the_contract_changes_only_after_a_person_accepts_the_amendment_in_the_inbox(self):
        p = self.compiled()
        repo = p.path("repo.git")
        before, main_before = p.read("contract.json")["revision"], _git(repo, "rev-parse", "main")

        def unchanged():
            self.assertEqual(p.read("contract.json")["revision"], before)
            self.assertEqual(_git(repo, "rev-parse", "main"), main_before)
            self.assertFalse(p.path("spec.v1.json").exists())

        card = submit(p, persona="product_owner", person="Pekka", text="The approver should be optional")
        triage(p, card["id"], model=model())
        with self.assertRaises(PermissionError):                                # not decided yet
            apply_change(p, card["id"], model=model())
        with self.assertRaises(DecisionRefused):                                # not a decider of change cards
            Canon(p).decide(card["id"], "accept", person="Dev", persona="developer")
        with self.assertRaises(DecisionRefused):                                # not a person
            Canon(p).decide(card["id"], "accept", person="autopilot", persona="business_owner")
        unchanged()
        other = submit(p, persona="product_owner", person="Pekka", text="The approver should be the IT desk")
        triage(p, other["id"], model=model())
        Canon(p).decide(other["id"], "reject", person="Aino", persona="business_owner", reason="no")
        with self.assertRaises(PermissionError):                                # rejected
            apply_change(p, other["id"], model=model())
        unchanged()

        Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner", reason="optional is fine")
        out = apply_change(p, card["id"], model=model())
        contract = p.read("contract.json")
        self.assertNotEqual(contract["revision"], before)
        self.assertEqual(out["contract"], contract["revision"])
        r2 = next(r for r in contract["requirements"] if r["id"] == "R-2")
        self.assertEqual((r2["provenance"], r2["decided_by"]), ("customer-confirmed", "Aino"))
        work = self.clone(p)
        self.assertEqual(json.loads((work / "contract.json").read_text(encoding="utf-8"))["revision"],
                         contract["revision"])                                  # the product's main carries it
        applied = [r["event"]["payload"] for r in p.ledger().of_kind("change_applied")]
        self.assertEqual([(a["card"], a["contract"]) for a in applied], [(card["id"], contract["revision"])])

    def test_FR_O7_AC_2_an_accepted_amendment_reopens_exactly_the_tasks_whose_criteria_changed(self):
        p = self.compiled()
        first = build(p, lanes=self.lanes(), cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertTrue(first["all_merged"], first)
        merged_at = {t: s["revision"] for t, s in p.read("tasks.json").items()}
        self.assertEqual(sorted(merged_at), ["T-001", "T-002", "T-003", "T-004"])

        card = submit(p, persona="product_owner", person="Pekka", text="The approver should be optional")
        triage(p, card["id"], model=model())
        Canon(p).decide(card["id"], "accept", person="Aino", persona="business_owner")
        self.assertEqual(apply_change(p, card["id"], model=model())["changed"], ["R-2"])

        state = p.read("tasks.json")
        self.assertEqual((state["T-002"]["status"], state["T-002"]["reopened_by"]), ("pending", ["R-2"]))
        for tid in ("T-001", "T-003", "T-004"):                                 # untouched work stays merged
            self.assertEqual((state[tid]["status"], state[tid]["revision"]), ("merged", merged_at[tid]), tid)
        self.assertEqual(ready_tasks(p), ["T-002"])
        self.assertFalse(p.meta["built"])
        again = build(p, lanes=self.lanes(), cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertEqual(again["results"], {"T-002": "merged"})                 # only the reopened task is rebuilt
        self.assertTrue(again["all_merged"])

    def test_FR_O7_AC_3_a_cell_that_rewrites_the_products_contract_changes_nothing_the_kernel_judges_by(self):
        p = self.compiled()
        before = p.read("contract.json")

        def rewriting_cell(lane_path, prompt):
            path = Path(lane_path, "contract.json")
            c = json.loads(path.read_text(encoding="utf-8"))
            c["requirements"] = [r for r in c["requirements"] if r["id"] != "R-1"]
            c["tasks"] = [t for t in c["tasks"] if t["id"] != "T-001"]
            path.write_text(json.dumps(c, indent=2), encoding="utf-8", newline="\n")
            _write(lane_path, "app/routes.py", GOOD_ROUTES)                     # the behaviour, but no test
            return _record()

        out = build_task(p, "T-001", lanes=self.lanes(), cell_runner=rewriting_cell, verifier_runner=no_findings,
                         max_rounds=0)
        self.assertEqual(out["status"], "escalated")
        trace = _signals(out)["trace"]
        self.assertEqual((trace["verdict"], trace["native"]["unnamed"]), ("failed", ["R-1-AC-1"]))
        self.assertEqual(p.read("contract.json"), before)                       # the kernel's contract is as it was
        self.assertEqual(p.meta["contract_revision"], before["revision"])
        main = self.clone(p)
        self.assertEqual(json.loads((main / "contract.json").read_text(encoding="utf-8"))["revision"],
                         before["revision"])
        cell = self.clone(p, "cell")
        _git(cell, "checkout", "-q", "cell/T-001")                              # the rewrite stays on its branch
        self.assertNotIn("R-1", {r["id"] for r in json.loads((cell / "contract.json").read_text(encoding="utf-8"))
                                 ["requirements"]})


if __name__ == "__main__":
    unittest.main()
