"""FR-SRC2: a project's own sources, said truly: old plans by real commits, each test's own verdict, every root, the
latest revision fetched, the review in Alignment, stopped sources, its own tests and findings where its state is
said, and Ask Rihma's words.

Over tests/native_fixture.py's repository and a second invented one (a signup service whose plan and task list are
from August while two code files changed in twenty commits since; a handoff note at the root; a gate's run report
in gates/), attached or adopted as projects. Nothing here reads a real project.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import native_fixture as fx  # noqa: E402
from factory_fakes import FixedClock  # noqa: E402

from kernel import native_apply, native_chat, native_readers, native_sources, native_tests  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.store import Factory  # noqa: E402

WHO = {"person": "Aino Example", "persona": "developer"}
GATE = ("import json\njson.dump({'gates': [{'name': 'test_rule_001_mutant', 'status': 'pass'}]}, "
        "open('gate-results.json', 'w'))\nprint('1 passed')\n")
HANDOFF = """# Handoff

| Task | Status |
|------|--------|
| Signup sends a welcome note | done |
| Signup expires an unused code | open |
"""
RUN_REPORT = json.dumps({"gates": [{"name": "gate_signup_01", "status": "pass"},
                                   {"name": "gate_signup_010", "status": "fail"}]}, indent=2) + "\n"
ISSUES = "\n".join([json.dumps({"issue_id": "I-41", "title": "A user signs up twice", "sev": "critical",
                                "status": "open", "loc": "server/main.py:12"}),
                    "not a json object", "[1, 2]",
                    json.dumps({"issue_id": "I-42", "title": "A slow signup", "sev": "low", "status": "open"})]) + "\n"


def py(_tool):
    return sys.executable


def signup_repo(root: Path) -> Path:
    """A plan and a task list from August; then twenty commits to two code files; then a handoff note, a run report
    and an issues file."""
    root.mkdir(parents=True, exist_ok=True)
    fx.git(root, "init", "-q", "-b", "main")
    fx.write(root, {"README.md": "# Signup\n", "docs/PRD.md": fx.OLD_PLAN,
                    "specs/001-signup/tasks.md": "# Tasks\n\n- [ ] T001 Join\n- [ ] T002 Leave\n- [x] T003 List\n"})
    fx.git(root, "add", "-A")
    fx.git(root, "commit", "-q", "-m", "The plan", when="2026-08-03T10:00:00+00:00")
    for i in range(20):
        name = "server/main.py" if i % 2 else "client/app.py"
        fx.write(root, {name: f"STEP = {i}\n"})
        fx.git(root, "add", "-A")
        fx.git(root, "commit", "-q", "-m", f"Step {i}", when=f"2026-09-{i + 1:02d}T10:00:00+00:00")
    fx.write(root, {"HANDOFF.md": HANDOFF, "gates/run-report.json": RUN_REPORT, "evidence/issues.jsonl": ISSUES})
    fx.git(root, "add", "-A")
    fx.git(root, "commit", "-q", "-m", "Handoff", when="2026-09-25T10:00:00+00:00")
    return root


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-src2-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home", clock=FixedClock())

    def board(self):
        return attach(self.factory, "Board engine", repo=fx.make_repo(self.tmp / "repo"), **WHO)

    def signup(self):
        return attach(self.factory, "Signup", repo=signup_repo(self.tmp / "signup"), **WHO)

    def map_found(self, p, kind, glob=None):
        key = next(d["key"] for d in native_apply.view(p)["detected"] if d["kind"] == kind
                   and (glob is None or d["glob"] == glob))
        return native_sources.map_source(p, key=key, **WHO)["source"]


class OldPlansTest(_Base):
    def test_FR_SRC2_AC_1_an_old_plan_is_found_by_real_commits_and_root_notes_and_gate_reports_are_found(self):
        p = self.signup()
        v = native_apply.view(p)
        stale = {s["path"]: s for s in v["stale"]}
        self.assertEqual(sorted(stale), ["docs/PRD.md", "specs/001-signup/tasks.md"],
                         "twenty commits to two files since August: the plan and its task list may be old plans")
        self.assertEqual(stale["specs/001-signup/tasks.md"]["commits_since"], 20)
        found = {(d["kind"], d["glob"]) for d in v["detected"]}
        self.assertNotIn(("tasks", "specs/001-signup/tasks.md"), found)
        self.assertIn(("tasks", "HANDOFF.md"), found, "a handoff note at the root is where the plan lives")
        self.assertIn(("results", "gates/run-report.json"), found, "a run report in a gates/ folder")
        self.assertNotEqual(v["next"][0]["do"].get("key"), "tasks:specs/001-signup/tasks.md")
        self.assertNotIn("tasks:specs/001-signup/tasks.md", [s["do"].get("key") for s in v["next"]])


class TraceTest(_Base):
    def test_FR_SRC2_AC_2_a_requirement_gets_only_its_own_tests_verdict_and_every_root_must_pass(self):
        run = {"id": "RUN-1"}
        self.assertEqual(native_tests.status_of("gate_law_01", {"gate_law_010": ("passed", run)})[0], "not run")
        self.assertEqual(native_tests.status_of("test_rule_1", {"test_rule_10": ("passed", run)})[0], "not run")
        self.assertEqual(native_tests.status_of("test_rule_001_mutant", {"rules.test_rule_001_mutant":
                                                                         ("passed", run)})[0], "passed")
        self.assertEqual(native_tests.status_of("tests/test_alpha.py::test_score_floor",
                                                {"test_score_floor": ("passed", run)})[0], "passed")
        self.assertEqual(native_tests.status_of("tests/test_alpha.py", {
            "tests/test_alpha.py::test_a": ("passed", run), "tests/test_alpha.py::test_b": ("failed", run)})[0],
            "failed", "a file named as the test: its cases' worst verdict")
        p = self.board()
        native_sources.map_source(p, spec={"kind": "tests", "roots": [
            {"root": "pkg_a", "command": "python -m pytest -q"}, {"root": "pkg_b", "command": "python -m pytest -q"}]},
            **WHO)
        native_tests._keep(p, {"from": "run here", "root": "pkg_a", "command": "python -m pytest -q",
                               "verdict": "passed", "counts": {"passed": 1}, "cases": []})
        self.assertFalse(native_apply.baseline_passes_by_root(p), "pkg_b never ran: the baseline still counts")
        native_tests._keep(p, {"from": "run here", "root": "pkg_b", "command": "python -m pytest -q",
                               "verdict": "passed", "counts": {"passed": 1}, "cases": []})
        self.assertTrue(native_apply.baseline_passes_by_root(p))


class AdoptedFetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-src2-adopt-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = fx.make_repo(self.tmp / "repo")
        fx.write(self.repo, {"tools/gate.py": GATE})
        fx.git(self.repo, "add", "-A")
        fx.git(self.repo, "commit", "-q", "-m", "A gate", when="2026-03-13T10:00:00+00:00")
        fx.git(self.repo, "branch", "-m", "main", "trunk")

    def adopt(self, home):
        from kernel.adopt import adopt

        self.factory = Factory(home, clock=FixedClock())
        return adopt(self.factory, "Board engine", source=str(self.repo), intent="maintain", suite_timeout=120, **WHO)

    def test_FR_SRC2_AC_3_read_again_fetches_the_upstream_first_and_the_watch_is_said_truly(self):
        from kernel import adopt_watch

        p = self.adopt(self.tmp / "home")
        key = next(d["key"] for d in native_apply.view(p)["detected"] if d["kind"] == "requirements")
        native_sources.map_source(p, key=key, **WHO)
        v = native_apply.view(p)
        self.assertIn("not watched yet", v["mapped"][0]["every_said"])
        self.assertIn({"kind": "watch"}, [s["do"] for s in v["next"]])
        fx.write(self.repo, {"rules/rule_005.json": fx.rule(5, "A piece moves once a turn", ["a second move is "
                                                                                             "refused"], "t5")})
        fx.git(self.repo, "add", "-A")
        fx.git(self.repo, "commit", "-q", "-m", "Rule 5", when="2026-03-20T10:00:00+00:00")
        got = native_sources.read(p, why="asked", fetch=True, **WHO)
        self.assertTrue(got["fetch"]["moved"], got["fetch"])
        self.assertEqual(len(got["requirements"]), 5, "the new commit's rule is read")
        self.assertIn("moved to", got["fetch"]["line"])
        adopt_watch.setup(p, **WHO)
        v = native_apply.view(p)
        self.assertEqual(v["mapped"][0]["every_said"], "on every new commit")
        self.assertNotIn({"kind": "watch"}, [s["do"] for s in v["next"]])

    def test_FR_SRC2_AC_3_a_cockpit_started_with_a_relative_home_runs_its_tests(self):
        here = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, here)
        p = self.adopt(Path("home"))
        self.assertTrue(native_sources.where(p)[0].is_absolute())
        native_sources.map_source(p, spec={"kind": "tests", "roots": [
            {"root": "", "command": "python tools/gate.py", "results": "gate-results.json"}]}, **WHO)
        ran = native_tests.run(p, "", confirmed=True, which=py, **WHO)
        self.assertEqual(ran["verdict"], "passed")

    def test_FR_SRC2_AC_8_its_own_tests_replace_the_root_baseline_where_its_state_is_said(self):
        from kernel import adopted_state, automation_suggest, automations_actions

        p = self.adopt(self.tmp / "home")
        native_sources.map_source(p, spec={"kind": "tests", "roots": [
            {"root": "", "command": "python tools/gate.py", "results": "gate-results.json"}]}, **WHO)
        self.assertIn("python tools/gate.py in the repository's root", automation_suggest._stated_tests(p))
        native_tests.run(p, "", confirmed=True, which=py, **WHO)
        st = adopted_state.state(p)
        self.assertEqual(st["baseline"]["own"]["line"], "its own tests: the repository's root passed")
        self.assertIn("its own tests: the repository's root passed", st["line"])
        self.assertNotIn("baseline", st["line"])
        auto = {"id": "AUTO-1", "owner": WHO, "action": {"kind": "command"}}

        class Tools:
            suite_timeout = 120

        real = native_tests.run
        with mock.patch.object(native_tests, "run", lambda *a, **k: real(*a, which=py, **k)):
            got = automations_actions._command(self.factory, auto, {"project": p.pid}, Tools())
        self.assertEqual(got["detail"], "the project's own tests: the repository's root passed")
        self.assertEqual(native_tests.runs(p)[-1]["by"]["person"], "Aino Example")


class ReviewTest(_Base):
    def test_FR_SRC2_AC_4_mapped_requirements_and_tasks_lead_to_review_and_own_findings_show_in_health(self):
        from cockpit.eval_routes import EvalRoutes
        from kernel import alignment_records as kalign

        p = self.board()
        self.map_found(p, "requirements")
        self.map_found(p, "tasks")
        self.map_found(p, "findings")
        step = next(s for s in native_apply.view(p)["next"] if s["do"]["kind"] == "align")
        self.assertEqual(step["label"], "Review 4 requirements and 6 tasks to import")
        scan = kalign.scan(p, **WHO)
        mine = [i["id"] for g in scan["groups"] if g["id"] in ("requirements", "tasks") for i in g["items"]]
        kalign.decide(p, mine, "accept", **WHO)
        self.assertNotIn("align", [s["do"]["kind"] for s in native_apply.view(p)["next"]])
        routes = EvalRoutes()
        routes.factory = self.factory
        own = routes.get_project_evals(p.pid)[1]["own_findings"]
        self.assertEqual([(f["id"], f["severity"], f["where"]) for f in own["findings"]],
                         [("ISS-1", "high", "engine/core_3.py (evidence/issues.jsonl:1)"),
                          ("ISS-2", "medium", "evidence/issues.jsonl:2")])


class ChatTest(_Base):
    def ask(self, p, q):
        return native_chat.answer(self.factory, q, p, "developer")

    def act(self, out):
        return next((x for x in out["propose"] if x["action"] == "act"), None)

    def test_FR_SRC2_AC_5_ask_rihma_reads_results_words_and_says_what_is_mapped_stopped_or_not_old(self):
        p = self.signup()
        act = self.act(self.ask(p, "use gates/run-report.json as test results"))
        self.assertEqual(act["args"]["key"], "results:gates/run-report.json")
        act = self.act(self.ask(p, "use the gate results as test runs"))
        self.assertEqual(act["args"]["key"], "results:gates/run-report.json")
        src = self.map_found(p, "findings")
        out = self.ask(p, "use the issues file as findings")
        self.assertIn(f"already mapped as {src['id']}", out["answer"])
        self.assertIsNone(self.act(out))
        out = self.ask(p, "use README.md anyway")
        self.assertIn("is not marked as an old plan", out["answer"])
        self.assertIsNone(self.act(out))
        native_sources.stop(p, src["id"], reason="moved to the tracker", **WHO)
        act = self.act(self.ask(p, f"resume {src['id']}"))
        self.assertEqual((act["args"]["op"], act["args"]["source"]), ("map_source", src["id"]))
        native_sources.map_source(p, spec={"kind": "tests", "roots": [{"root": "", "command": "python -m pytest -q"}]},
                                  **WHO)
        native_tests.import_results(p, '{"gate_signup_01": "pass"}', name="gate run", **WHO)
        answer = self.ask(p, "Where does this project keep its requirements?")["answer"]
        self.assertNotIn("its test roots (SRC-2, not read yet", answer)
        self.assertIn("Its latest runs:", answer)
        self.assertIn("gate run: passed", answer)


class ReadersTest(_Base):
    def test_FR_SRC2_AC_6_common_finding_keys_are_guessed_and_unreadable_lines_are_said(self):
        m = native_readers.guess_mapping([json.loads(x) for x in ISSUES.splitlines() if x.startswith("{")])
        self.assertEqual((m["id"], m["severity"], m["where"]), ("issue_id", "sev", "loc"))
        found = native_readers.jsonl(ISSUES, "evidence/issues.jsonl")
        self.assertEqual([(f["id"], f["severity"], f["where"]) for f in found],
                         [("I-41", "critical", "server/main.py:12"), ("I-42", "low", None)])
        self.assertEqual(native_readers.jsonl_unread(ISSUES), [2, 3])
        p = self.signup()
        src = self.map_found(p, "findings")
        last = native_apply.view(p)["mapped"][0]["last"]
        self.assertEqual(last["records"], 2)
        self.assertIn("evidence/issues.jsonl: 2 line(s) are not JSON objects and were not read (lines 2, 3)",
                      last["errors"])
        self.assertEqual(src["id"], "SRC-1")


class StoppedTest(_Base):
    def test_FR_SRC2_AC_7_a_stopped_source_is_listed_with_resume_and_not_offered_again(self):
        p = self.board()
        src = self.map_found(p, "findings")
        native_sources.stop(p, src["id"], reason="moved to the tracker", **WHO)
        v = native_apply.view(p)
        self.assertEqual([(s["id"], s["stopped"]["reason"]) for s in v["stopped"]],
                         [(src["id"], "moved to the tracker")])
        self.assertNotIn("findings:evidence/issues.jsonl", [d["key"] for d in v["detected"]])
        self.assertNotIn("findings:evidence/issues.jsonl", [s["do"].get("key") for s in v["next"]])
        native_sources.map_source(p, sid=src["id"], spec={}, **WHO)
        v = native_apply.view(p)
        self.assertEqual(v["stopped"], [])
        self.assertEqual([s["id"] for s in v["mapped"] if s["state"] == "mapped"], [src["id"]])


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
