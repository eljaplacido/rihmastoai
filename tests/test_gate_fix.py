"""Regression tests for the gate cluster (task V-82): what the gate counts as evidence, what a
workspace can push, what accept as is merges, and what the status read models say.

Standard library only: python -m unittest tests.test_gate_fix
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import (GOOD_ROUTES, GOOD_TEST, TRIVIAL_TEST, FactoryTestCase, good_cell, lazy_cell,  # noqa: E402
                           model, no_findings)

from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build, build_task, resolve_escalations  # noqa: E402
from kernel.gate import signal_verifier  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import GIT_ID, KERNEL_GIT_ENV, Lanes, _git  # noqa: E402
from kernel.projections import gates  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import evidence, health, live, now  # noqa: E402
from kernel.store import write_json  # noqa: E402
from kernel.workspace import WorkspaceRefused, open_workspace, submit_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
AUTHOR = ["-c", "user.name=Aino", "-c", "user.email=aino@example.invalid"]
DONE = {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 2, "model": "fake-builder",
        "output": "done"}

SKIPPED_TEST = '''import unittest


class ItemsTest(unittest.TestCase):
    @unittest.skip("the route comes later")
    def test_R_1_AC_1_post_item_returns_201_with_id(self):
        self.fail("not built")
'''

EXPECTED_FAILURE_TEST = '''import unittest


class ItemsTest(unittest.TestCase):
    @unittest.expectedFailure
    def test_R_1_AC_1_post_item_returns_201_with_id(self):
        self.fail("not built")
'''

NOT_COLLECTED_TEST = '''class ItemsTest:  # not a unittest.TestCase: nothing ever runs it
    def test_R_1_AC_1_post_item_returns_201_with_id(self):
        raise AssertionError("not built")
'''

DOCSTRING_TRIVIAL_TEST = '''import unittest


class ItemsTest(unittest.TestCase):
    def test_R_1_AC_1_items_can_be_added(self):
        """Items can be added."""
        self.assertTrue(True)
'''

DOCSTRING_GOOD_TEST = GOOD_TEST.replace("    def test_R_1_AC_1_post_item_returns_201_with_id(self):\n",
                                        "    def test_R_1_AC_1_post_item_returns_201_with_id(self):\n"
                                        "        \"\"\"An item can be added.\"\"\"\n")

BROKEN_TEST = ("import unittest\n\n\nclass B(unittest.TestCase):\n    def test_broken(self):\n"
               "        self.assertEqual(1, 2)\n")
CONTRACT = {"tasks": [{"id": "T-001", "criteria": ["R-1-AC-1"]}],
            "requirements": [{"id": "R-1", "statement": "Items can be added.", "acceptance": [
                {"id": "R-1-AC-1", "given": "-", "when": "POST /items", "then": "201", "check": {"kind": "test"}}]}]}


def writing(name: str, text: str, *, routes: bool = False, extra: dict | None = None):
    """A builder cell that writes one test file (and the good routes, and any other files)."""
    def cell(lane_path, prompt):
        if routes:
            Path(lane_path, "app", "routes.py").write_text(GOOD_ROUTES, encoding="utf-8", newline="\n")
        Path(lane_path, "tests", name).write_text(text, encoding="utf-8", newline="\n")
        for rel, body in (extra or {}).items():
            Path(lane_path, rel).write_text(body, encoding="utf-8", newline="\n")
        return dict(DONE)
    return cell


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def commit_all(path: Path, message: str) -> str:
    _git(path, "add", "-A")
    _git(path, *AUTHOR, "commit", "-q", "-m", message)
    return _git(path, "rev-parse", "HEAD")


def unverified_answer(prompt: str) -> str:
    return "I ran out of steps before I could finish the review."


def moving_main(project):
    """A verifier that answers with no findings, and the first time it is asked, another lane
    merges into the product's main while the gate runs."""
    calls: list[int] = []

    def runner(prompt):
        if not calls:
            calls.append(1)
            with tempfile.TemporaryDirectory(prefix="gf-elsewhere-") as tmp:
                _git(Path(tmp), "clone", "-q", str(project.path("repo.git")), "w")
                work = Path(tmp) / "w"
                write(work / "NOTES.md", "merged elsewhere while the gate ran\n")
                _git(work, "add", "-A")
                _git(work, *GIT_ID, "commit", "-q", "-m", "Elsewhere")
                _git(work, "push", "-q", "origin", "main")
        return no_findings(prompt)
    return runner


class GateFixCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.lanes_root = self.tmp / "lanes"

    def compiled(self, title: str = "Equipment loans"):
        p = self.new(mode="assume", title=title)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def lanes(self) -> Lanes:
        return Lanes(self.lanes_root, size=1)

    def build(self, p, cell, **kwargs) -> dict:
        kwargs.setdefault("verifier_runner", no_findings)
        return build_task(p, "T-001", lanes=self.lanes(), cell_runner=cell, **kwargs)

    def open(self, p) -> Path:
        return Path(open_workspace(p, person="Aino", persona="developer", agent="shell", root=self.lanes_root)["path"])

    def submit(self, p, path: Path, **kwargs) -> dict:
        kwargs.setdefault("verifier_runner", no_findings)
        return submit_workspace(p, path, person="Aino", persona="developer", lanes=self.lanes(), **kwargs)

    def main(self, p) -> str:
        return _git(p.path("repo.git"), "rev-parse", "main")

    def on_main(self, p) -> list:
        return _git(p.path("repo.git"), "ls-tree", "-r", "--name-only", "main").splitlines()

    def kinds(self, p) -> list:
        return [r["event"]["kind"] for r in p.ledger().records()]

    @staticmethod
    def signals(out: dict) -> dict:
        return {s["name"]: s["verdict"] for s in out["rounds"][-1]["gate"]["signals"]}


# -- what the gate counts as a criterion's evidence -----------------------------------------------------

class CriterionEvidenceTest(GateFixCase):
    def test_FR_G2_AC_1_a_skipped_or_expected_failure_criterion_test_never_shows_the_criterion_met(self):
        for n, (text, at_base) in enumerate(((SKIPPED_TEST, "failed"), (EXPECTED_FAILURE_TEST, "failed"),
                                             (NOT_COLLECTED_TEST, "not measured"))):
            p = self.compiled(f"Loans {n}")
            out = self.build(p, writing("test_items.py", text), max_rounds=0)
            self.assertEqual(out["status"], "escalated", text)
            signals = self.signals(out)
            self.assertEqual((signals["trace"], signals["fail_first"]), ("not measured", at_base), text)
            self.assertEqual(len(self.on_main(p)), len(_git(p.path("repo.git"), "ls-tree", "-r", "--name-only",
                                                          _git(p.path("repo.git"), "rev-list", "--max-parents=0",
                                                               "main")).splitlines()))
            self.assertNotEqual({e["criterion"]: e["state"] for e in evidence(p)}["R-1-AC-1"], "verified")

    def test_FR_G2_AC_2_a_criterion_test_with_a_docstring_is_seen_at_base_and_a_vacuous_one_refused(self):
        p = self.compiled()
        out = self.build(p, writing("test_items.py", DOCSTRING_TRIVIAL_TEST), max_rounds=0)
        self.assertEqual(out["status"], "escalated")
        ff = {s["name"]: s for s in out["rounds"][-1]["gate"]["signals"]}["fail_first"]
        self.assertEqual(ff["verdict"], "failed")
        self.assertEqual(ff["native"]["passed_at_base"], {"R-1-AC-1": ["test_R_1_AC_1_items_can_be_added"]})
        q = self.compiled("Loans with docstrings")                       # a real test with a docstring merges
        good = build_task(q, "T-001", lanes=Lanes(self.tmp / "lanes-q", size=1), verifier_runner=no_findings,
                          cell_runner=writing("test_items.py", DOCSTRING_GOOD_TEST, routes=True))
        self.assertEqual(good["status"], "merged", self.signals(good))
        tests = {s["name"]: s for s in good["rounds"][-1]["gate"]["signals"]}["tests"]["native"]["tests"]
        self.assertEqual(tests["test_R_1_AC_1_post_item_returns_201_with_id"], "ok")

    def test_FR_E3_AC_1_a_verifier_answer_without_a_findings_list_is_not_measured(self):
        high = {"criterion": "R-1-AC-1", "in_scope": True, "severity": "high", "finding": "x", "repro": "y"}
        for answer in ('I stopped early. The last payload was {"name": "drill"}.',
                       "```json\n" + json.dumps({"findings": high}) + "\n```",
                       "```json\n" + json.dumps({"issues": [high]}) + "\n```",
                       "```json\n" + json.dumps({"findings": ["the route crashes on an empty name"]}) + "\n```",
                       "```json\n" + json.dumps({"findings": [high | {"severity": "critical"}]}) + "\n```",
                       "```json\n" + json.dumps([high]) + "\n```"):
            sig = signal_verifier(self.tmp, CONTRACT, "T-001", "0" * 40, runner=lambda prompt, a=answer: a)
            self.assertEqual(sig.verdict, "not measured", answer)
        self.assertEqual(signal_verifier(self.tmp, CONTRACT, "T-001", "0" * 40, runner=no_findings).verdict, "passed")
        shouted = "```json\n" + json.dumps({"findings": [high | {"severity": "HIGH"}]}) + "\n```"
        self.assertEqual(signal_verifier(self.tmp, CONTRACT, "T-001", "0" * 40, runner=lambda p: shouted).verdict,
                         "failed")

    def test_FR_E3_AC_2_evidence_that_could_not_be_read_is_an_objection_for_the_next_round_and_the_card(self):
        p = self.compiled()
        prompts: list[str] = []

        def cell(lane_path, prompt):
            prompts.append(prompt)
            return good_cell(lane_path, prompt)

        out = self.build(p, cell, verifier_runner=unverified_answer, max_rounds=1)
        self.assertEqual(out["status"], "escalated")
        self.assertIn("Objections from the last round", prompts[1])
        self.assertIn("verifier (not measured)", prompts[1])
        card = Canon(p).get_card(out["card"])
        self.assertTrue(any(o.startswith("verifier (not measured)") for o in card["payload"]["objections"]), card)
        self.assertIn("verifier (not measured)", card["body"])


# -- what a cell or a workspace may not change ---------------------------------------------------------

class ProtectedPathsTest(GateFixCase):
    def test_FR_O4_AC_1_a_builder_cell_that_touches_the_contract_or_surface_is_refused_and_cannot_be_accepted(self):
        p = self.compiled()
        before = self.main(p)
        cell = writing("test_items.py", GOOD_TEST, routes=True,
                       extra={"contract.json": "{}\n", ".gnomon/policy.toml": "[sandbox]\nlevel = \"off\"\n"})
        out = self.build(p, cell, max_rounds=0)
        self.assertEqual(out["status"], "escalated")
        signals = self.signals(out)
        self.assertEqual((signals["protected"], out["rounds"][-1]["gate"]["verdict"]), ("violation", "violation"))
        self.assertNotIn("verifier", signals)                              # never under a surface the cell rewrote
        card = Canon(p).get_card(out["card"])
        self.assertTrue(any("contract.json" in o and ".gnomon/policy.toml" in o for o in card["payload"]["objections"]))
        self.assertEqual(self.main(p), before)
        Canon(p).decide(card["id"], "accept_as_is", person="Aino", persona="business_owner")
        self.assertEqual(resolve_escalations(p), [card["id"]])
        self.assertEqual(self.main(p), before)                              # a person cannot accept it either
        refused = [r["event"]["payload"] for r in p.ledger().of_kind("accept_refused")]
        self.assertEqual(len(refused), 1)
        self.assertIn("contract.json", refused[0]["why"])
        again = Canon(p).get_card(refused[0]["again"])
        self.assertEqual((again["state"], again["refs"]["task"]), ("open", "T-001"))
        self.assertEqual(p.read("tasks.json")["T-001"]["card"], again["id"])

    def test_FR_W1_AC_2_a_protected_path_renamed_recased_or_quoted_is_refused(self):
        p = self.compiled()
        path = self.open(p)
        before = self.main(p)
        blob = _git(path, "rev-parse", "HEAD:.gnomon/policy.toml")

        def renamed_contract():
            _git(path, "mv", "contract.json", "docs_contract.json")

        def renamed_design():
            _git(path, "mv", "factory/DESIGN.md", "app/DESIGN.md.txt")

        def recased_surface():
            _git(path, "update-index", "--add", "--cacheinfo", f"100644,{blob},.GNOMON/extra.toml")

        def quoted_surface():
            write(path / ".gnomon" / "rôle.toml", "[sandbox]\nlevel = \"off\"\n")
            _git(path, "add", "-A")

        for change, named in ((renamed_contract, "contract.json"), (renamed_design, "factory/DESIGN.md"),
                              (recased_surface, ".GNOMON/extra.toml"), (quoted_surface, ".gnomon/rôle.toml")):
            _git(path, "reset", "-q", "--hard", "origin/main")
            change()
            _git(path, *AUTHOR, "commit", "-q", "-m", f"Change {named}")
            with self.assertRaises(WorkspaceRefused, msg=named) as caught:
                self.submit(p, path)
            self.assertIn(named, str(caught.exception))
            self.assertEqual(self.main(p), before, named)


# -- a workspace reaches main through the gate only --------------------------------------------------

class WorkspacePushTest(GateFixCase):
    def test_FR_W1_AC_2_a_workspace_cannot_push_to_main_only_submit(self):
        p = self.compiled()
        path = self.open(p)
        before = self.main(p)
        write(path / "app" / "routes.py", GOOD_ROUTES)
        write(path / "tests" / "test_items.py", GOOD_TEST)
        head = commit_all(path, "Items can be added (R-1-AC-1)")
        env = {k: v for k, v in os.environ.items() if k != KERNEL_GIT_ENV}   # the person's own git

        def git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, env=env)

        repo = str(p.path("repo.git"))
        self.assertNotEqual(git("rev-parse", "--abbrev-ref", "@{u}").returncode, 0)      # it tracks nothing
        for attempt in (("push", "-q", "origin", "HEAD:main"), ("-c", "push.default=upstream", "push", "-q"),
                        ("push", "-q", repo, "HEAD:main"), ("push", "-q", repo, "HEAD:refs/heads/MAIN"),
                        ("push", "-q", "-f", repo, "HEAD:refs/heads/cell/T-001")):
            self.assertNotEqual(git(*attempt).returncode, 0, attempt)
            self.assertEqual(self.main(p), before, attempt)
        self.assertEqual(git("push", "-q", repo, "HEAD:refs/heads/work/aino/1").returncode, 0)  # its own branch
        out = self.submit(p, path, task="T-001")
        self.assertEqual((out["status"], self.main(p)), ("merged", head))


# -- accept as is, and every decision on an escalation, carried out once --------------------------------

class EscalationDecisionTest(GateFixCase):
    def test_FR_G8_AC_2_accept_as_is_merges_the_head_judged_on_a_workspace_card_not_the_moved_branch(self):
        p = self.compiled()
        path = self.open(p)
        write(path / "tests" / "test_items.py", TRIVIAL_TEST)
        judged = commit_all(path, "A test for R-1-AC-1")
        first = self.submit(p, path, task="T-001")
        self.assertEqual(first["status"], "escalated")
        self.assertEqual(Canon(p).get_card(first["card"])["payload"]["head"], judged)
        write(path / "app" / "later.py", "BROKEN = True\n")
        commit_all(path, "Later work, never judged with the first card")
        second = self.submit(p, path, task="T-001")
        self.assertEqual(second["status"], "escalated")
        Canon(p).decide(first["card"], "accept_as_is", person="Bea", persona="business_owner")
        self.assertEqual(resolve_escalations(p), [first["card"]])
        files = self.on_main(p)
        self.assertIn("tests/test_items.py", files)
        self.assertNotIn("app/later.py", files)                             # what Bea never saw stays out
        merged = [r["event"]["payload"] for r in p.ledger().of_kind("merged")][-1]
        self.assertEqual((merged["head"], merged["warranted"], merged["revision"]), (judged, "not warranted",
                                                                                      self.main(p)))
        self.assertEqual(Canon(p).get_card(second["card"])["state"], "open")

    def test_FR_G8_AC_2_accept_as_is_merges_the_cells_judged_head_not_a_swapped_branch(self):
        p = self.compiled()
        contract_before = _git(p.path("repo.git"), "show", "main:contract.json")
        esc = self.build(p, lazy_cell, max_rounds=0)
        with tempfile.TemporaryDirectory(prefix="gf-swap-") as tmp:          # someone swaps the cell's branch
            _git(Path(tmp), "clone", "-q", str(p.path("repo.git")), "w")
            work = Path(tmp) / "w"
            _git(work, "checkout", "-q", "cell/T-001")
            write(work / "contract.json", "{}\n")
            _git(work, "add", "-A")
            _git(work, *GIT_ID, "commit", "-q", "-m", "Swapped after the gate")
            _git(work, "push", "-q", "-f", "origin", "cell/T-001")
        Canon(p).decide(esc["card"], "accept_as_is", person="Aino", persona="business_owner")
        resolve_escalations(p)
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "merged")
        self.assertEqual(_git(p.path("repo.git"), "show", "main:contract.json"), contract_before)
        self.assertIn("tests/test_items.py", self.on_main(p))

    def test_FR_G8_AC_2_a_decision_on_a_workspace_card_without_a_task_is_carried_out(self):
        p = self.compiled()
        path = self.open(p)
        write(path / "tests" / "test_broken.py", BROKEN_TEST)
        commit_all(path, "Broken")
        first = self.submit(p, path)
        self.assertEqual(first["status"], "escalated")
        Canon(p).decide(first["card"], "accept_as_is", person="Bea", persona="business_owner")
        self.assertEqual(resolve_escalations(p), [first["card"]])
        self.assertIn("tests/test_broken.py", self.on_main(p))              # accepted as it is
        merged = [r["event"]["payload"] for r in p.ledger().of_kind("merged")][-1]
        self.assertTrue(merged["permitted_by"].startswith("person:Bea"))
        write(path / "app" / "later.py", "LATER = 1\n")
        commit_all(path, "Later")
        second = self.submit(p, path)
        self.assertEqual(second["status"], "escalated")
        Canon(p).decide(second["card"], "stop", person="Bea", persona="business_owner")
        self.assertEqual(resolve_escalations(p), [second["card"]])
        self.assertTrue(p.meta.get("halted"))
        resolved = [r["event"]["payload"] for r in p.ledger().of_kind("escalation_resolved")]
        self.assertEqual([(r["card"], r["verdict"]) for r in resolved],
                         [(first["card"], "accept_as_is"), (second["card"], "stop")])

    def test_FR_G8_AC_2_retry_on_a_workspace_card_never_reopens_a_merged_task(self):
        p = self.compiled()
        path = self.open(p)
        write(path / "app" / "routes.py", GOOD_ROUTES)
        write(path / "tests" / "test_items.py", GOOD_TEST)
        head = commit_all(path, "Items can be added (R-1-AC-1)")
        self.assertEqual(self.submit(p, path, task="T-001")["status"], "merged")
        write(path / "tests" / "test_broken.py", BROKEN_TEST)
        commit_all(path, "A follow-up that fails")
        out = self.submit(p, path, task="T-001")
        self.assertEqual(out["status"], "escalated")
        Canon(p).decide(out["card"], "retry", person="Aino", persona="developer")
        self.assertEqual(resolve_escalations(p), [out["card"]])
        state = p.read("tasks.json")["T-001"]
        self.assertEqual((state["status"], state["revision"]), ("merged", head))

    def test_FR_G8_AC_2_each_decision_is_carried_out_once(self):
        p = self.compiled()
        first = self.build(p, lazy_cell, max_rounds=0)
        Canon(p).decide(first["card"], "retry", person="Dev", persona="developer")
        resolve_escalations(p)
        second = self.build(p, lazy_cell, max_rounds=0)
        Canon(p).decide(second["card"], "accept_as_is", person="Aino", persona="business_owner")
        resolve_escalations(p)
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "merged")
        self.assertEqual(resolve_escalations(p), [])                        # the first retry is not done again
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "merged")

    def test_FR_G8_AC_2_a_decision_made_before_a_workspace_merged_the_task_never_undoes_the_merge(self):
        for verdict in ("stop", "retry", "accept_as_is"):
            p = self.compiled(f"Loans {verdict}")
            esc = self.build(p, lazy_cell, max_rounds=0)
            Canon(p).decide(esc["card"], verdict, person="Bea", persona="business_owner")  # not yet carried out
            path = self.open(p)
            write(path / "app" / "routes.py", GOOD_ROUTES)
            write(path / "tests" / "test_items.py", GOOD_TEST)
            head = commit_all(path, "Items can be added (R-1-AC-1)")
            self.assertEqual(self.submit(p, path, task="T-001")["status"], "merged", verdict)
            self.assertEqual(resolve_escalations(p), [esc["card"]], verdict)
            state = p.read("tasks.json")["T-001"]
            self.assertEqual((state["status"], state["revision"]), ("merged", head), verdict)
            self.assertNotIn("stopped_by", state, verdict)
            self.assertFalse(p.meta.get("halted"), verdict)                 # the build is not halted over it
            self.assertEqual(self.main(p), head, verdict)
            resolved = [r["event"]["payload"] for r in p.ledger().of_kind("escalation_resolved")]
            self.assertEqual([(r["verdict"], r["carried_out"]) for r in resolved], [(verdict, False)], verdict)
            self.assertIn("merged by another path", resolved[0]["why"], verdict)

    def test_FR_W1_AC_2_a_workspace_merge_of_a_task_closes_its_builder_escalation(self):
        p = self.compiled()
        esc = self.build(p, lazy_cell, max_rounds=0)
        path = self.open(p)
        write(path / "app" / "routes.py", GOOD_ROUTES)
        write(path / "tests" / "test_items.py", GOOD_TEST)
        commit_all(path, "Items can be added (R-1-AC-1)")
        self.assertEqual(self.submit(p, path, task="T-001")["status"], "merged")
        self.assertEqual(Canon(p).get_card(esc["card"])["state"], "resolved")
        self.assertEqual(Canon(p).cards(kind="escalation"), [])

    def test_FR_O7_AC_2_a_reopened_task_merged_again_no_longer_says_it_was_reopened(self):
        p = self.compiled()
        p.write("tasks.json", {"T-001": {"status": "pending", "rounds": [], "reopened_by": ["R-1"],
                                         "accepted_as_is_by": "Aino"}})
        out = self.build(p, good_cell)
        self.assertEqual(out["status"], "merged")
        state = p.read("tasks.json")["T-001"]
        self.assertNotIn("reopened_by", state)
        self.assertNotIn("accepted_as_is_by", state)


# -- main moving while the gate runs ---------------------------------------------------------------------

class StaleMainTest(GateFixCase):
    def test_FR_G1_AC_1_a_cell_whose_main_moved_during_its_gate_is_recorded_and_built_again(self):
        p = self.compiled()
        out = self.build(p, good_cell, verifier_runner=moving_main(p))
        self.assertEqual(out["status"], "stale_main")
        rejected = [r["event"]["payload"] for r in p.ledger().of_kind("merge_rejected")]
        self.assertEqual([r["task"] for r in rejected], ["T-001"])
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "pending")
        self.assertNotIn("merged", self.kinds(p))
        again = self.build(p, good_cell)
        self.assertEqual(again["status"], "merged")
        self.assertIn("NOTES.md", self.on_main(p))

    def test_FR_G1_AC_1_a_submission_whose_main_moved_during_its_gate_is_refused_and_recorded(self):
        p = self.compiled()
        path = self.open(p)
        write(path / "app" / "routes.py", GOOD_ROUTES)
        write(path / "tests" / "test_items.py", GOOD_TEST)
        commit_all(path, "Items can be added (R-1-AC-1)")
        with self.assertRaises(WorkspaceRefused):
            self.submit(p, path, task="T-001", verifier_runner=moving_main(p))
        self.assertEqual([r["event"]["payload"]["task"] for r in p.ledger().of_kind("merge_rejected")], ["T-001"])
        submissions = p.read("workspaces.json")[0]["submissions"]
        self.assertEqual(submissions[-1]["status"], "stale_main")
        self.assertEqual(self.submit(p, path, task="T-001")["status"], "merged")

    def test_FR_E1_AC_1_building_a_project_with_no_contract_says_to_compile_it(self):
        p = self.new(mode="assume")
        with self.assertRaises(FileNotFoundError) as caught:
            build(p, lanes=self.lanes(), cell_runner=good_cell, verifier_runner=no_findings)
        self.assertIn("compile", str(caught.exception))


# -- what the status read models say ---------------------------------------------------------------------

def holdout_step(**native) -> dict:
    return {"step": "holdouts:demo", "outcome": native.pop("outcome", "passed"),
            "native": {"verdict": "passed", "scenarios": 0, "passed": 0, "failed": 0, "missing": [], "failing": []}
            | native}


class StatusFixTest(GateFixCase):
    def test_FR_O6_AC_3_a_holdout_criterion_is_held_out_only_after_its_scenario_ran(self):
        p = self.compiled()

        def state() -> str:
            return {e["criterion"]: e["state"] for e in evidence(p)}["R-1-AC-2"]

        write_json(p.path("releases", "1.json"), {"number": 1, "state": "done", "steps": [
            holdout_step(verdict="not applicable", ran=[])]})                 # no holdout criteria then
        self.assertEqual(state(), "not_measured")
        write_json(p.path("releases", "2.json"), {"number": 2, "state": "done", "steps": [
            holdout_step(ran=["R-1-AC-2"], scenarios=1, passed=1)]})
        self.assertEqual(state(), "held_out")
        write_json(p.path("releases", "3.json"), {"number": 3, "state": "failed", "steps": [
            holdout_step(outcome="failed", verdict="not measured", ran=[], missing=["R-1-AC-2"])]})
        self.assertEqual(state(), "not_measured")                           # the latest run never ran it

    def test_FR_T1_AC_4_a_release_the_security_gate_holds_is_waiting_on_a_person(self):
        p = self.compiled()
        self.assertEqual(now(p)["state"], "working")
        write_json(p.path("releases", "1.json"), {
            "number": 1, "state": "waiting", "waiting_on": "the security gate holds release 1 before staging",
            "blocked": {"by": "security", "environment": "staging", "findings": ["SEC-1-1"], "scans": []},
            "steps": [{"step": "deploy:staging", "outcome": "waiting", "native": {}}]})
        n = now(p)
        self.assertEqual(n["state"], "waiting_on_you")
        for part in ("Release 1", "security gate", "staging", "SEC-1-1"):
            self.assertIn(part, n["line"])

    def test_FR_T1_AC_5_an_open_incident_puts_the_project_at_risk(self):
        p = self.compiled()
        self.assertEqual(health(p)["status"], "on_track")
        card = Canon(p).card("incident", "Probe failing in production for release 1", blocking=True)
        h = health(p)
        self.assertEqual(h["status"], "at_risk")
        self.assertTrue(any(card["id"] in r for r in h["reasons"]), h["reasons"])

    def test_FR_M3_AC_4_a_first_round_the_gate_could_not_measure_is_left_out_of_the_rate(self):
        p = self.compiled()
        p.log("gate", {"task": "T-001", "round": 0, "verdict": "not measured", "signals": {}, "objections": []})
        p.log("gate", {"task": "T-002", "round": 0, "verdict": "passed", "signals": {}, "objections": []})
        g = gates(p)
        self.assertEqual((g["tasks_gated"], g["first_round_passed"], g["first_round_rate"]), (1, 1, 1.0))
        self.assertEqual(g["first_round_not_measured"], 1)

    def test_FR_T1_AC_7_live_shows_only_this_holders_trail_and_nothing_for_a_holder_that_died(self):
        a, b = self.compiled("Alpha loans"), self.compiled("Beta loans")
        root = self.tmp / "live-lanes"
        audit = root / "lane-1" / ".gnomon-audit"
        audit.mkdir(parents=True)
        old = audit / "task-1.jsonl"
        old.write_text("\n".join(json.dumps(r) for r in [
            {"kind": "session_start", "role": "builder"}, {"kind": "model_call", "model": "fake-builder"},
            {"kind": "tool_call", "tool": "bash", "target": "cat alpha/secret-plan.txt", "ts": "t"},
            {"kind": "session_end"}]) + "\n", encoding="utf-8")
        past = time.time() - 120
        os.utime(old, (past, past))                                         # project A's run, ended earlier
        with Lanes(root, size=1).lease(f"{b.pid}:T-001"):
            out = live(b, lanes_root=root)
            self.assertEqual((out["running"], out["task"], out["steps"], out["last"], out["ended"], out["role"]),
                             (True, "T-001", 0, None, False, None))
            self.assertFalse(live(a, lanes_root=root)["running"])
        child = (f"import sys, time\nsys.path.insert(0, {str(REPO)!r})\nfrom pathlib import Path\n"
                 f"from kernel.lanes import Lanes\n"
                 f"with Lanes(Path({str(root)!r}), size=1).lease({a.pid + ':T-002'!r}):\n"
                 f"    print('held', flush=True)\n    time.sleep(120)\n")
        proc = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.assertEqual(proc.stdout.readline().strip(), "held")
        proc.stdout.close()
        self.assertEqual((live(a, lanes_root=root)["running"], live(a, lanes_root=root)["task"]), (True, "T-002"))
        proc.kill()                                                         # the holder dies mid-task
        proc.wait(10)
        self.assertFalse(live(a, lanes_root=root)["running"])


if __name__ == "__main__":
    unittest.main()
