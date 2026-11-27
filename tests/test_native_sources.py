"""FR-SRC1: a project's own sources: detected, mapped, read as the truth, run, imported, traced and asked about.

Over tests/native_fixture.py's repository (rule files, an issues file, rounds' READMEs, two packages with their own
test roots, a committed gate results file, and a plan untouched since January while the code moved on), attached or
adopted as a project. Nothing here reads a real project.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import native_fixture as fx  # noqa: E402
from factory_fakes import FixedClock  # noqa: E402

from kernel import native_apply, native_chat, native_detect, native_readers, native_sources, native_tests  # noqa: E402
from kernel import adopt_watch, parity, understanding  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.store import Factory  # noqa: E402

WHO = {"person": "Aino Example", "persona": "developer"}
GATE = ("import json\njson.dump({'gates': [{'name': 'test_rule_001_mutant', 'status': 'pass'}, "
        "{'name': 'test_rule_003_mutant', 'status': 'pass'}]}, open('gate-results.json', 'w'))\nprint('2 passed')\n")


def py(_tool):
    return sys.executable


class _Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-src-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = fx.make_repo(self.tmp / "repo")
        self.factory = Factory(self.tmp / "home", clock=FixedClock())
        self.p = attach(self.factory, "Board engine", repo=self.repo, **WHO)

    def head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()

    def map_found(self, kind):
        key = next(d["key"] for d in native_apply.view(self.p)["detected"] if d["kind"] == kind)
        return native_sources.map_source(self.p, key=key, **WHO)["source"]


class DetectTest(_Repo):
    def test_FR_SRC1_AC_1_the_projects_own_sources_are_detected_by_rule_and_old_plans_marked(self):
        v = native_apply.view(self.p)
        found = {d["kind"]: d for d in v["detected"]}
        self.assertEqual(found["requirements"]["glob"], "rules/*")
        self.assertEqual(found["requirements"]["mapping"], {"id": "id", "title": "title", "criteria": "criteria",
                                                            "test": "mutant"})
        self.assertEqual(found["findings"]["glob"], "evidence/issues.jsonl")
        self.assertEqual(found["tasks"]["glob"], "rounds/*/README.md")
        self.assertEqual(found["results"]["glob"], "results/gates.json")
        self.assertEqual([r["root"] for r in found["tests"]["roots"]], ["pkg_a", "pkg_b"])
        self.assertIn("pytest run from the repository's root does not find their imports", v["root_note"])
        stale = {s["path"]: s for s in v["stale"]}
        self.assertEqual(sorted(stale), ["docs/requirements.md", "docs/tasks.md"])
        self.assertIn("may be an old plan", stale["docs/requirements.md"]["why"])
        self.assertGreaterEqual(stale["docs/requirements.md"]["commits_since"], native_detect.STALE_COMMITS)
        self.assertNotIn("docs/tasks.md", [d["glob"] for d in v["detected"]])
        self.assertEqual(v["rule"], {"stale_days": native_detect.STALE_DAYS, "stale_commits": native_detect.STALE_COMMITS})
        self.assertIn("Platform-wide", v["scope"]["platform"])
        self.assertIn("Project-specific", v["scope"]["project"])
        self.assertEqual(v["next"][0]["do"], {"kind": "map", "key": "requirements:rules/*"})
        self.assertIn({"kind": "use_anyway", "path": "docs/requirements.md"}, [s["do"] for s in v["next"]])
        self.assertEqual(self.p.read(native_sources.FILE), None, "detection records nothing")

    def test_FR_SRC1_AC_1_a_plan_still_current_is_not_an_old_plan_and_a_project_without_a_repository_says_why(self):
        src = native_sources._src(self.p)
        self.assertIsNone(native_detect.staleness(src, "rules/rule_001.json"))
        plain = self.factory.new_project("Just an idea", mode="assume", maturity="demo")
        v = native_apply.view(plain)
        self.assertFalse(v["applies"])
        self.assertIn("no repository of its own", v["why"])


class ReadersTest(unittest.TestCase):
    def test_FR_SRC1_AC_2_each_adapter_reads_its_format_with_path_and_line(self):
        reqs = native_readers.records(fx.RULES["rules/rule_002.json"], "rules/rule_002.json",
                                      {"id": "id", "title": "title", "criteria": "criteria", "test": "mutant"})
        self.assertEqual((reqs[0]["ref"], reqs[0]["line"], reqs[0]["tests"]), ("RULE-002", 2, ["test_rule_002_mutant"]))
        self.assertEqual(reqs[0]["criteria"][0]["then"], "the fourth move starts the next turn")
        yaml = native_readers.records(fx.RULES["rules/rule_004.yaml"], "rules/rule_004.yaml",
                                      {"id": "id", "title": "title", "criteria": "criteria", "test": "mutant"})
        self.assertEqual((yaml[0]["ref"], yaml[0]["criteria"][0]["then"]), ("RULE-004", "a ninth piece is refused"))
        listed = native_readers.yaml_load("- id: A-1\n  title: One\n  criteria:\n    - given x then y\n- id: A-2\n"
                                          "  title: Two\n")
        self.assertEqual([x["id"] for x in listed], ["A-1", "A-2"])
        self.assertEqual(listed[0]["criteria"], ["given x then y"])
        found = native_readers.jsonl(fx.ISSUES + "not json\n", "evidence/issues.jsonl")
        self.assertEqual([(f["id"], f["severity"], f["status"], f["line"]) for f in found],
                         [("ISS-1", "high", "open", 1), ("ISS-2", "medium", "open", 2), ("ISS-3", "low", "closed", 3)])
        tasks = native_readers.markdown_tasks(fx.ROUND.format(n=1, tie="open") + "\n- [x] T009 A checkbox\n", "r.md")
        self.assertEqual([(t["title"], t["done"]) for t in tasks],
                         [("Scores never go below zero", True), ("Ties go to the earlier player", False),
                          ("The board refuses a ninth piece", False), ("A checkbox", True)])
        self.assertEqual(tasks[0]["line"], 5)
        junit = native_readers.results(fx.JUNIT)
        self.assertEqual((junit["format"], junit["counts"]), ("junit", {"passed": 3, "failed": 1, "skipped": 0}))
        tap = native_readers.results("TAP version 13\nok 1 - a\nnot ok 2 - b\nok 3 - c # SKIP later\n")
        self.assertEqual(tap["counts"], {"passed": 1, "failed": 1, "skipped": 1})
        self.assertEqual(native_readers.results('{"passed": 655, "failed": 5}')["counts"], {"passed": 655, "failed": 5})
        self.assertEqual(native_readers.results('{"law_a": "pass", "law_b": false}')["counts"],
                         {"passed": 1, "failed": 1, "skipped": 0})
        with self.assertRaises(native_readers.SourceUnreadable):
            native_readers.results('<!DOCTYPE x [<!ENTITY a "b">]><testsuite/>')
        with self.assertRaises(native_readers.SourceUnreadable):
            native_readers.results("[]")


class MapTest(_Repo):
    def test_FR_SRC1_AC_3_mapping_is_signed_read_at_once_with_path_and_line_and_changed_or_stopped(self):
        before = self.head()
        src = self.map_found("requirements")
        self.assertEqual(src["id"], "SRC-1")
        got = native_sources.latest_read(self.p)
        self.assertEqual([(r["ref"], r["path"], r["line"]) for r in got["requirements"]],
                         [("RULE-001", "rules/rule_001.json", 2), ("RULE-002", "rules/rule_002.json", 2),
                          ("RULE-003", "rules/rule_003.json", 2), ("RULE-004", "rules/rule_004.yaml", 1)])
        self.assertEqual(got["sources"]["SRC-1"]["records"], 4)
        mapped = self.p.ledger().of_kind("native_source_mapped")[-1]["event"]["payload"]
        self.assertEqual((mapped["source"], mapped["person"], mapped["glob"]), ("SRC-1", "Aino Example", "rules/*"))
        self.assertEqual(self.p.ledger().of_kind("native_sources_read")[-1]["event"]["payload"]["counts"]["requirements"], 4)
        with self.assertRaises(native_sources.SourcesRefused):
            native_sources.map_source(self.p, key="findings:evidence/issues.jsonl", person="Aino Example",
                                      persona="stakeholder")
        with self.assertRaises(native_sources.SourcesRefused):
            native_sources.map_source(self.p, key="findings:evidence/issues.jsonl", person="assistant", persona="developer")
        with self.assertRaises(ValueError):
            native_sources.map_source(self.p, spec={"kind": "requirements", "glob": "../outside/*.json"}, **WHO)
        with self.assertRaises(ValueError):
            native_sources.map_source(self.p, key="requirements:rules/*", **WHO)       # it is mapped already
        out = native_sources.map_source(self.p, sid="SRC-1", spec={"glob": "nowhere/*.json"}, every="weekly", **WHO)
        self.assertEqual(out["source"]["every"], "weekly")
        last = out["mapped"][0]["last"]
        self.assertIn("no file of the repository matches nowhere/*.json", last["errors"])
        self.assertTrue(out["schedule"]["weekly"]["automation"], "a weekly read is an automation in the person's name")
        native_sources.stop(self.p, "SRC-1", reason="the rules moved", **WHO)
        self.assertEqual(native_sources.active(self.p), [])
        self.assertEqual(self.p.ledger().of_kind("native_source_stopped")[-1]["event"]["payload"]["reason"],
                         "the rules moved")
        self.assertEqual(self.head(), before, "nothing is written to the repository")
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True,
                                        text=True).stdout, "")

    def test_FR_SRC1_AC_3_a_new_commit_or_the_schedule_reads_the_sources_again(self):
        self.map_found("tasks")
        fx.write(self.repo, {"rounds/round-3/README.md": fx.ROUND.format(n=3, tie="done")})
        fx.git(self.repo, "add", "-A")
        fx.git(self.repo, "commit", "-q", "-m", "Round 3", when="2026-03-20T10:00:00+00:00")
        v = native_apply.view(self.p)
        self.assertTrue(v["newer"])
        self.assertEqual(v["next"][0]["do"], {"kind": "read"})
        self.assertTrue(native_sources.reread(self.p, "a new commit"))
        self.assertEqual(len(native_sources.latest_read(self.p)["tasks"]), 9)
        self.assertIsNone(native_sources.reread(self.p, "daily"), "no source asks to be read daily")
        got = adopt_watch.fire(self.p, "sources")
        self.assertIn("read again: 0 requirements, 9 tasks", got["detail"])


class RunTest(_Repo):
    def test_FR_SRC1_AC_4_a_mapped_command_runs_after_yes_and_results_from_elsewhere_are_imported_and_traced(self):
        fx.write(self.repo, {"tools/gate.py": GATE})
        fx.git(self.repo, "add", "-A")
        fx.git(self.repo, "commit", "-q", "-m", "A gate", when="2026-03-13T10:00:00+00:00")
        self.map_found("requirements")
        native_sources.map_source(self.p, spec={"kind": "tests", "roots": [
            {"root": "", "command": "python tools/gate.py", "results": "gate-results.json"}]}, **WHO)
        with self.assertRaises(native_tests.RunRefused):
            native_tests.run(self.p, "", confirmed=False, which=py, **WHO)
        with self.assertRaises(native_tests.RunRefused):
            native_tests.run(self.p, "pkg_b", confirmed=True, which=py, **WHO)
        with self.assertRaises(native_tests.RunRefused):
            native_tests.run(self.p, "", confirmed=True, which=py, person="Aino Example", persona="stakeholder")
        with self.assertRaises(native_tests.RunRefused):
            native_tests.argv("python gate.py | tee out")
        ran = native_tests.run(self.p, "", confirmed=True, which=py, **WHO)
        self.assertEqual((ran["verdict"], ran["counts"], ran["cases"]), ("passed", {"passed": 2, "failed": 0,
                                                                                    "skipped": 0}, 2))
        self.assertEqual(self.p.ledger().of_kind("native_tests_run")[-1]["event"]["payload"]["verdict"], "passed")
        tr = {r["ref"]: r for r in native_apply.trace(self.p)["rows"]}
        self.assertEqual((tr["RULE-001"]["result"], tr["RULE-002"]["result"], tr["RULE-004"]["result"]),
                         ("passed", "not run", "not run"))
        with self.assertRaises(ValueError):
            native_tests.import_results(self.p, fx.JUNIT, produced_at="last night", **WHO)
        got = native_tests.import_results(self.p, fx.JUNIT, produced_at="2026-11-26T03:00:00Z", machine="the build host",
                                          **WHO)
        self.assertEqual((got["from"], got["machine"], got["counts"]["failed"]), ("imported", "the build host", 1))
        tr = {r["ref"]: r for r in native_apply.trace(self.p)["rows"]}
        self.assertEqual((tr["RULE-002"]["result"], tr["RULE-004"]["result"]), ("passed", "failed"))
        self.assertIn("imported from the build host, produced 2026-11-26T03:00:00Z", tr["RULE-004"]["from"])
        self.assertIn("4 requirement(s) from the project's own source: 3 passed, 1 failed",
                      native_apply.trace(self.p)["line"])


class AlignUnderstandTest(_Repo):
    def items(self, group=None):
        from kernel import alignment_records as kalign

        found = [i for g in kalign.scan(self.p, **WHO)["groups"] for i in g["items"]]
        return [i for i in found if group is None or i["group"] == group]

    def titled(self, words):
        return [i["title"] for i in self.items() if words in i["title"]]

    def test_FR_SRC1_AC_5_alignment_takes_the_projects_own_sources_and_leaves_old_plans_out(self):
        from kernel import alignment_records as kalign

        self.assertEqual(self.titled("REQ-001") + self.titled("T010"), [], "the old plan is left out")
        self.assertEqual(self.p.read(kalign.SCAN)["structure"]["old_plans"], ["docs/requirements.md", "docs/tasks.md"])
        native_sources.use_anyway(self.p, "docs/requirements.md", **WHO)
        self.assertTrue(self.titled("REQ-001"), "used anyway, as the person said")
        self.map_found("requirements")
        self.map_found("tasks")
        reqs = self.items("requirements")
        self.assertEqual(sorted(i["proposal"]["id"] for i in reqs), ["RULE-001", "RULE-002", "RULE-003", "RULE-004"])
        self.assertEqual(reqs[0]["native"]["path"], "rules/rule_001.json")
        crit = {i["proposal"]["id"]: i for i in self.items("criteria")}["RULE-002-AC-1"]
        self.assertEqual(crit["proposal"]["then"], "the fourth move starts the next turn")
        trace = {i["proposal"]["test"]: i for i in self.items("trace")}["test_rule_002_mutant"]
        self.assertEqual((trace["basis"], trace["confidence"], trace["proposal"]["criterion_id"]),
                         ("by the project's own source", 1.0, "RULE-002-AC-1"))
        tasks = [i["proposal"]["title"] for i in self.items("tasks")]
        self.assertIn("The board refuses a ninth piece", tasks)
        self.assertNotIn("Old task one", tasks)


class AdoptedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-src-adopt-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        repo = fx.make_repo(self.tmp / "repo")
        fx.write(repo, {"tools/gate.py": GATE})
        fx.git(repo, "add", "-A")
        fx.git(repo, "commit", "-q", "-m", "A gate", when="2026-03-13T10:00:00+00:00")
        from kernel.adopt import adopt

        self.factory = Factory(self.tmp / "home", clock=FixedClock())
        self.p = adopt(self.factory, "Board engine", source=str(repo), intent="maintain", suite_timeout=120, **WHO)

    def test_FR_SRC1_AC_5_the_understanding_says_its_own_tests_contract_and_findings(self):
        from kernel import status

        before = understanding.take(self.p)
        self.assertIsNone(before.get("native"))
        for kind in ("requirements", "findings"):
            key = next(d["key"] for d in native_apply.view(self.p)["detected"] if d["kind"] == kind)
            native_sources.map_source(self.p, key=key, **WHO)
        native_sources.map_source(self.p, spec={"kind": "tests", "roots": [
            {"root": "", "command": "python tools/gate.py", "results": "gate-results.json"}]}, **WHO)
        native_tests.run(self.p, "", confirmed=True, which=py, **WHO)
        u = understanding.take(self.p)
        self.assertTrue(u["tests"].startswith("from the project's own runs: python tools/gate.py: passed"))
        self.assertFalse([g for g in u["not_understood"] if g.startswith("how to run its tests")])
        self.assertEqual(u["contract"], "4 requirement(s) in the project's own source (rules/*)")
        self.assertEqual(u["native"]["open_findings"], 2)
        self.assertIn("ISS-1 A tie is given to the later player (high, open) at engine/core_3.py "
                      "(evidence/issues.jsonl:1)",
                      u["native"]["findings"])
        self.assertIn("Its own sources: 3 of its own source(s) mapped", understanding.answer(self.p)["answer"])
        self.p.write("baseline.json", {"verdict": "failed", "runs": [{"counts": {"errors": 2}}]})
        self.assertEqual(status.failed_baseline(self.p), "", "its own roots pass: a run from the root misled")


class ChatTest(_Repo):
    def ask(self, q):
        return native_chat.answer(self.factory, q, self.p, "developer")

    def test_FR_SRC1_AC_6_ask_rihma_says_where_and_proposes_the_mapping_by_rule(self):
        out = self.ask("Where does this project keep its requirements?")
        self.assertIn("Found by rule, not mapped yet:", out["answer"])
        self.assertIn("rules/*", out["answer"])
        self.assertIn("docs/requirements.md", out["answer"])
        acts = [p for p in out["propose"] if p["action"] == "act"]
        self.assertEqual(acts[0]["args"]["key"], "requirements:rules/*")
        self.assertEqual(acts[0]["args"]["call"]["path"], f"/api/projects/{self.p.pid}/sources/map")
        out = self.ask("use the rule files as requirements")
        act = next(p for p in out["propose"] if p["action"] == "act")
        self.assertEqual((act["args"]["op"], act["args"]["key"]), ("map_source", "requirements:rules/*"))
        self.assertEqual(out["navigate"]["control"], "sources_map")
        out = self.ask("use plans/*.md as tasks")
        act = next(p for p in out["propose"] if p["action"] == "act")
        self.assertEqual(act["args"]["spec"], {"kind": "tasks", "glob": "plans/*.md"})
        self.assertEqual(next(p for p in self.ask("use docs/requirements.md anyway")["propose"] if p["action"] == "act")
                         ["args"]["op"], "use_old_plan")
        self.assertEqual(next(p for p in self.ask("stop reading SRC-1")["propose"] if p["action"] == "act")
                         ["args"]["call"]["path"], f"/api/projects/{self.p.pid}/sources/SRC-1/stop")
        self.map_found("requirements")
        self.assertEqual(next(p for p in self.ask("read the sources again")["propose"] if p["action"] == "act")
                         ["args"]["op"], "read_sources")
        self.assertIn("Requirements and criteria: rules/* (SRC-1", self.ask("what are this project's own sources?")
                      ["answer"])
        self.assertIsNone(self.ask("what is the weather like"))
        from kernel.assistant import ask

        full = ask(self.factory, "Where does this project keep its requirements?", persona="developer",
                   project_id=self.p.pid)
        self.assertEqual(full["matches"], ["sources"])

    def test_FR_SRC1_AC_8_every_control_operation_and_command_has_its_other_half(self):
        from cockpit import solo_routes
        from kernel import assistant_ops
        from kernel.assistant_rules import ui_map
        from kernel.control_pages import CONTROL_PAGES

        controls = {c["id"] for c in ui_map()["controls"]}
        mine = {"sources_panel", "sources_map", "sources_change", "sources_stop", "sources_read", "sources_use_anyway",
                "sources_import", "sources_run"}
        self.assertLessEqual(mine, controls)
        self.assertTrue(all(CONTROL_PAGES[c] == ("overview", None) for c in mine))
        self.assertTrue(all(c in parity.READS or c in parity.CHAT for c in mine))
        self.assertLessEqual({"map_source", "stop_source", "read_sources", "use_old_plan"}, set(assistant_ops.OPS))
        self.assertLessEqual({"sources map", "sources stop", "sources read", "sources import", "sources run",
                              "sources use-anyway", "sources change"}, set(parity.CLI_ROUTES))
        routes = {"post_native_map", "post_native_stop", "post_native_read", "post_native_use_anyway",
                  "post_native_import", "post_native_run"}
        self.assertLessEqual(routes, set(solo_routes.NEEDS))


class CliTest(_Repo):
    def test_FR_SRC1_AC_8_the_terminal_shows_maps_and_imports_signed(self):
        from kernel.cli import main

        home = ["--home", str(self.factory.home)]
        with mock.patch("sys.stdout") as out:
            self.assertEqual(main([*home, "sources", "show", self.p.pid]), 0)
        shown = json.loads("".join(c.args[0] for c in out.write.call_args_list))
        self.assertEqual(shown["detected"][0]["key"], "requirements:rules/*")
        results = self.tmp / "gates.xml"
        results.write_text(fx.JUNIT, encoding="utf-8")
        with mock.patch("sys.stdout"):
            self.assertEqual(main([*home, "sources", "map", self.p.pid, "--key", "requirements:rules/*",
                                   "--person", "Aino Example", "--persona", "developer"]), 0)
            self.assertEqual(main([*home, "sources", "import", self.p.pid, str(results), "--machine", "build host",
                                   "--produced-at", "2026-11-26T03:00:00Z", "--person", "Aino Example",
                                   "--persona", "developer"]), 0)
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(main([*home, "sources", "run", self.p.pid, ".", "--yes", "--person", "Aino Example",
                                   "--persona", "developer"]), 2, "a root that is not mapped is refused")
        self.assertEqual(native_tests.runs(self.p)[-1]["machine"], "build host")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
