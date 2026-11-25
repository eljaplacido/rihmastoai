"""Alignment with a repository's own structure (FR-ALN1, docs/guides/alignment.md).

A team's repository, kept the way IDE tools keep it (tests/alignment_fixture.py: spec-kit, Kiro, ADRs, Gherkin,
OpenAPI, pytest, jest, GitHub Actions), is captured by rule, proposed item by item for the project, accepted,
edited or rejected by a person, and read again after it changed. Nothing is ever written to the repository and
nothing found there is run.
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from alignment_fixture import SECRET_VALUE, change_repo, git, make_repo, write  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import alignment as al  # noqa: E402
from kernel import alignment_records as ar  # noqa: E402
from kernel import alignment_suggest as sg  # noqa: E402
from kernel import repo_structure as rs  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import contract_check  # noqa: E402

AINO, DEV = "Aino Virtanen", "developer"
MARKER = "ran-from-the-repository"
# Files that would leave a mark if anything found in the repository were run.
TRAPS = {"tests/conftest.py": f"open('{MARKER}', 'w').write('x')\n",
         "scripts/setup.sh": f"#!/bin/sh\ntouch {MARKER}\n"}


def tree_of(repo: Path) -> tuple[str, str]:
    """The repository's committed head and its working tree's status: what alignment must never change."""
    return (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain", "--untracked-files=all"))


class Aligned(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp / "loans")
        write(self.repo, TRAPS)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "Traps", when="2026-03-02T10:00:00+00:00")
        self.before = tree_of(self.repo)
        self.p = attach(self.factory, "Loans", repo=self.repo, person=AINO, persona=DEV)

    def scan(self) -> dict:
        return ar.scan(self.p, person=AINO, persona=DEV)

    @staticmethod
    def by_title(view: dict, group: str, start: str) -> dict:
        g = next(x for x in view["groups"] if x["id"] == group)
        return next(i for i in g["items"] if i["title"].startswith(start))

    def untouched(self) -> None:
        self.assertEqual(tree_of(self.repo), self.before)
        self.assertFalse((self.repo / MARKER).exists())
        self.assertEqual(list(self.tmp.rglob(MARKER)), [])


class CaptureTest(Aligned):
    def test_FR_ALN1_AC_1_the_structure_map_names_each_convention_and_where_it_is_and_runs_nothing(self):
        for m in (rs.from_git(self.repo, "main"), rs.from_folder(self.repo)):
            self.assertTrue({"spec-kit", "Kiro", "ADR", "Gherkin", "OpenAPI", "pytest", "jest", "GitHub Actions"}
                            <= set(m["conventions"]), m["conventions"])
            specs = {s["path"]: s for s in m["specs"]}
            sk = specs["specs/001-loan-items/spec.md"]
            self.assertEqual((sk["convention"], sk["feature"]), ("spec-kit", "001-loan-items"))
            self.assertEqual([r["ref"] for r in sk["requirements"]], ["User Story 1", "User Story 2", "FR-001", "FR-002",
                                                                      "FR-003"])
            story = sk["requirements"][0]
            self.assertEqual([(c["given"], c["when"], c["then"]) for c in story["criteria"]][0],
                             ("an item that is in the store", "a member borrows it", "the item is marked as on loan"))
            kiro = specs[".kiro/specs/overdue/requirements.md"]["requirements"][0]
            self.assertEqual((kiro["ref"], kiro["story"]["who"]), ("Requirement 1", "store keeper"))
            self.assertEqual([c["form"] for c in kiro["criteria"]], ["ears", "ears"])
            self.assertEqual(kiro["criteria"][0]["when"], "a loan is older than 14 days")
            feature = specs["features/search.feature"]["requirements"][0]
            self.assertEqual((feature["ref"], feature["criteria"][0]["form"]), ("REQ-SEARCH", "gherkin"))
            self.assertEqual({(t["ref"], t["done"]) for t in m["tasks"]},
                             {("T001", True), ("T002", False), ("T003", True), ("1", False), ("2", True)})
            self.assertEqual([(d["ref"], d["status"]) for d in m["decisions"]],
                             [("ADR-0001", "accepted"), ("ADR-0002", "proposed")])
            api = m["contracts"][0]
            self.assertEqual((api["kind"], api["title"], api["version"]), ("OpenAPI", "Loans API", "1.2.0"))
            self.assertEqual([(o["method"], o["path"], o["operation"]) for o in api["operations"]],
                             [("GET", "/items", "listItems"), ("POST", "/items/{id}/borrow", "borrowItem")])
            tests = {f["path"]: f for f in m["tests"]["files"]}
            self.assertEqual(tests["tests/test_loans.py"]["framework"], "pytest")
            self.assertEqual(tests["web/loans.test.js"]["framework"], "jest")
            self.assertIn("marks a loan older than 14 days overdue", [t["name"] for t in tests["web/loans.test.js"]["tests"]])
            self.assertEqual(m["tests"]["count"], 6)
            self.assertEqual(set(m["tests"]["run"]), {"npm test", "pytest"})
            jobs = [(j["name"], j["runs_tests"]) for c in m["ci"] for j in c["jobs"]]
            self.assertEqual(jobs, [("lint", False), ("build", False)])
            self.assertEqual({q["tool"] for q in m["quality"]}, {"ruff", "pre-commit"})
            self.assertIn("CLAUDE.md", m["ai_tools"]["files"])
            self.assertIn({"path": ".env", "why": "may hold secrets: never opened, by its name"}, m["skipped"])
            self.assertNotIn(SECRET_VALUE, json.dumps(m))
        dated = rs.from_git(self.repo, "main")
        self.assertTrue(dated["dated"])
        speckit = next(s for s in dated["specs"] if s["convention"] == "spec-kit")
        self.assertEqual([m["path"] for m in speckit["mentioned"]], ["src/items.py"])
        self.assertLess(speckit["date"], speckit["mentioned"][0]["date"])             # commit dates, not this clock
        self.untouched()

    def test_FR_ALN1_AC_1_a_folder_without_git_is_read_without_dates_and_a_secret_in_text_is_not_read(self):
        plain = self.tmp / "plain"
        shutil.copytree(self.repo, plain, ignore=shutil.ignore_patterns(".git"))
        (plain / "docs" / "requirements.md").write_text(
            "# Requirements\n\n- REQ-7: The export holds every loan\n\nservice_token = \"" + SECRET_VALUE + "\"\n",
            encoding="utf-8")
        m = rs.from_folder(plain)
        self.assertFalse(m["dated"])
        self.assertIn("docs/requirements.md", [s["path"] for s in m["skipped"]])
        self.assertNotIn(SECRET_VALUE, json.dumps(m))
        self.assertFalse(any(g["kind"] == "stale_spec" for g in al.propose(m)["items"] if g["group"] == "gaps"))


class ProposalTest(Aligned):
    def test_FR_ALN1_AC_2_requirements_criteria_trace_tasks_decisions_and_contracts_are_proposed_with_sources(self):
        v = self.scan()
        reqs = {i["source"]["ref"]: i for i in next(g for g in v["groups"] if g["id"] == "requirements")["items"]}
        self.assertEqual({k: r["proposal"]["id"] for k, r in reqs.items()},
                         {"User Story 1": "US-1", "User Story 2": "US-2", "FR-001": "FR-001", "FR-002": "FR-002",
                          "FR-003": "FR-003", "Requirement 1": "REQ-1", "REQ-SEARCH": "REQ-SEARCH"})
        us1 = reqs["User Story 1"]
        self.assertEqual((us1["source"]["path"], us1["source"]["lines"][0], us1["source"]["convention"]),
                         ("specs/001-loan-items/spec.md", 7, "spec-kit"))
        self.assertIn("Requirement US-1 in the project's contract", us1["adds"])
        self.assertIn("as User Story 1", us1["why"])
        crit = self.by_title(v, "criteria", "REQ-1-AC-1")
        self.assertEqual((crit["proposal"]["when"], crit["source"]["form"]), ("a loan is older than 14 days", "ears"))
        derived = self.by_title(v, "criteria", "FR-002-AC-1")
        self.assertTrue(derived["derived"])
        trace = {i["proposal"]["test"]: i for i in next(g for g in v["groups"] if g["id"] == "trace")["items"]}
        named = trace["test_FR_001_lists_every_item_with_its_state"]
        self.assertEqual((named["proposal"]["criterion_id"], named["basis"], named["confidence"]),
                         ("FR-001-AC-1", "by name", 0.9))
        by_file = trace["marks a loan older than 14 days overdue"]
        self.assertEqual((by_file["proposal"]["criterion_id"], by_file["basis"]), ("REQ-1-AC-1", "by file"))
        self.assertGreater(by_file["confidence"], 0.55)
        by_text = trace["test_return_puts_the_item_back_in_the_store"]
        self.assertEqual((by_text["proposal"]["criterion_id"], by_text["basis"]), ("US-2-AC-1", "by text"))
        self.assertLessEqual(by_text["confidence"], 0.7)
        self.assertNotIn("test_configuration_loads_defaults", trace)
        tasks = {i["source"]["ref"]: i for i in next(g for g in v["groups"] if g["id"] == "tasks")["items"]}
        self.assertEqual((tasks["T002"]["proposal"]["done"], tasks["T002"]["proposal"]["serves"]), (False, ["FR-002"]))
        self.assertEqual(tasks["T003"]["proposal"]["serves"], ["US-1"])
        self.assertEqual(tasks["1"]["proposal"]["serves"], ["REQ-1-AC-1"])
        self.assertEqual([d["proposal"]["status"] for d in next(g for g in v["groups"] if g["id"] == "decisions")["items"]],
                         ["accepted", "proposed"])
        api = next(g for g in v["groups"] if g["id"] == "contracts")["items"][0]
        self.assertEqual(api["proposal"]["operations"], ["GET /items", "POST /items/{id}/borrow"])
        again = al.propose(rs.from_git(self.repo, "main"))
        self.assertEqual(sorted(i["id"] for i in again["items"]),
                         sorted(i["id"] for g in v["groups"] for i in g["items"]))       # stable ids
        self.untouched()

    def test_FR_ALN1_AC_3_gaps_are_items_with_their_reasons_and_suggestions_never_touch_the_repository(self):
        v = self.scan()
        gaps = {i["kind"]: i for i in next(g for g in v["groups"] if g["id"] == "gaps")["items"]}
        self.assertTrue({"no_test", "untestable", "no_requirement", "stale_spec", "ci_no_tests", "no_criteria"}
                        <= set(gaps), sorted(gaps))
        self.assertIn("'user-friendly'", gaps["untestable"]["why"])
        self.assertIn("test_configuration_loads_defaults", gaps["no_requirement"]["why"])
        self.assertIn("lint", gaps["ci_no_tests"]["why"])
        stale = [g for g in next(x for x in v["groups"] if x["id"] == "gaps")["items"] if g["kind"] == "stale_spec"]
        self.assertIn("specs/001-loan-items/spec.md", [g["source"]["path"] for g in stale])
        self.assertEqual(v["summary"]["text"], "5 of 6 tests trace to a criterion; 3 of 7 requirements have no test; "
                                               "1 criterion is not testable as written")
        kinds = {s["kind"]: s for s in v["suggestions"]}
        self.assertTrue({"rename_tests", "tasks_entry", "ci_tests", "write_tests", "testable", "stale_spec"} <= set(kinds))
        patch = kinds["rename_tests"]["patch"]
        self.assertIn("+def test_US_1_AC_1_borrow_marks_the_item_on_loan():", patch)
        self.assertIn("+  it('REQ-1-AC-1: marks a loan older than 14 days overdue', () => {", patch)
        self.assertIn("- run: pytest", kinds["ci_tests"]["text"])
        self.assertIn("never writes", kinds["ci_tests"]["applies_to"])
        clone = self.tmp / "clone"                         # the patch applies to the repository as it is
        subprocess.run(["git", "clone", "-q", str(self.repo), str(clone)], check=True, capture_output=True)
        (self.tmp / "rename.patch").write_text(patch, encoding="utf-8")
        check = subprocess.run(["git", "apply", "--check", str(self.tmp / "rename.patch")], cwd=clone,
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.untouched()


class DecideTest(Aligned):
    def test_FR_ALN1_AC_4_accept_edit_and_reject_are_signed_written_into_the_contract_and_recorded(self):
        v = self.scan()
        us1 = self.by_title(v, "requirements", "User Story 1")
        out = ar.decide(self.p, [us1["id"]], "accept", person=AINO, persona=DEV)
        self.assertEqual(out["requirements"], ["US-1"])
        self.assertEqual(len(out["items"]), 3)                          # the requirement takes its two criteria
        contract = self.p.read("contract.json")
        req = next(r for r in contract["requirements"] if r["id"] == "US-1")
        self.assertEqual((req["provenance"], req["decided_by"]), ("customer-endorsed", AINO))
        self.assertIn("imported from the repository (specs/001-loan-items/spec.md:7, their User Story 1", req["notes"])
        self.assertIn(f"accepted by {AINO}", req["notes"])
        self.assertEqual([c["id"] for c in req["acceptance"]], ["US-1-AC-1", "US-1-AC-2"])
        report, _ = contract_check().check(contract)
        self.assertEqual(report.violations, [])
        self.assertEqual(self.p.meta["contract_revision"], contract["revision"])
        crit = self.by_title(v, "criteria", "REQ-1-AC-1")             # a criterion takes its requirement
        ar.decide(self.p, [crit["id"]], "accept", person=AINO, persona=DEV,
                  edits={crit["id"]: {"then": "the loan is marked overdue"}})
        req1 = next(r for r in self.p.read("contract.json")["requirements"] if r["id"] == "REQ-1")
        self.assertEqual([(c["id"], c["then"]) for c in req1["acceptance"]], [("REQ-1-AC-1", "the loan is marked overdue")])
        renamed = self.by_title(v, "requirements", "FR-001")
        ar.decide(self.p, [renamed["id"]], "accept", person=AINO, persona=DEV, edits={renamed["id"]: {"id": "LIST-1"}})
        ids = [r["id"] for r in self.p.read("contract.json")["requirements"]]
        self.assertIn("LIST-1", ids)
        self.assertIn("LIST-1-AC-1", [c["id"] for r in self.p.read("contract.json")["requirements"] for c in r["acceptance"]])
        fr2 = self.by_title(v, "requirements", "FR-002")
        out = ar.decide(self.p, [fr2["id"]], "reject", person=AINO, persona="product_owner", reason="not for this team")
        self.assertEqual(len(out["items"]), 2)
        self.assertNotIn("FR-002", [r["id"] for r in self.p.read("contract.json")["requirements"]])
        tasks = next(g for g in ar.view(self.p)["groups"] if g["id"] == "tasks")["items"]
        ar.decide(self.p, [t["id"] for t in tasks], "accept", person=AINO, persona=DEV)        # bulk
        self.assertEqual(len(ar.accepted(self.p, "tasks")), 5)
        self.assertEqual(ar.view(self.p)["status"]["accepted"], 3 + 2 + 2 + 5)
        led = self.p.ledger()
        acc = [r["event"]["payload"] for r in led.of_kind("alignment_accepted")]
        self.assertEqual(acc[0]["items"], out_items(us1))
        self.assertEqual({a["person"] for a in acc}, {AINO})
        rej = led.of_kind("alignment_rejected")[-1]["event"]["payload"]
        self.assertEqual((rej["person"], rej["persona"], rej["reason"]), (AINO, "product_owner", "not for this team"))
        self.assertTrue(led.verify().intact)
        records = len(led.records())
        contract_before = self.p.read("contract.json")
        with self.assertRaises(DecisionRefused):
            ar.decide(self.p, [fr2["id"]], "accept", person="assistant", persona=DEV)
        with self.assertRaisesRegex(ar.AlignRefused, "in the contract already"):
            ar.decide(self.p, [us1["id"]], "reject", person=AINO, persona=DEV)
        with self.assertRaisesRegex(ar.AlignRefused, "already a requirement"):
            ar.decide(self.p, [self.by_title(v, "requirements", "FR-003")["id"]], "accept", person=AINO, persona=DEV,
                      edits={self.by_title(v, "requirements", "FR-003")["id"]: {"id": "US-1"}})
        with self.assertRaisesRegex(ar.AlignRefused, "cannot be edited"):
            ar.decide(self.p, [crit["id"]], "accept", person=AINO, persona=DEV, edits={crit["id"]: {"statement": "x"}})
        self.assertEqual((len(led.records()), self.p.read("contract.json")), (records, contract_before))
        self.untouched()


def out_items(req: dict) -> list:
    return [req["id"], *req["children"]]


class DriftTest(Aligned):
    def test_FR_ALN1_AC_5_a_changed_repository_shows_new_changed_and_removed_items_for_the_same_decisions(self):
        v1 = self.scan()
        us2 = self.by_title(v1, "requirements", "User Story 2")
        ar.decide(self.p, [us2["id"]], "accept", person=AINO, persona=DEV)
        kept = {i["id"] for g in v1["groups"] for i in g["items"] if i["group"] == "requirements"}
        change_repo(self.repo)
        v2 = self.scan()
        index = {i["id"]: i for g in v2["groups"] for i in g["items"]}
        d = v2["drift"]
        self.assertEqual(d["since"], 1)
        new = [index[i]["title"] for i in d["new"]]
        self.assertIn("FR-004: System MUST export loans as CSV", new)
        self.assertIn("test_FR_004_exports_loans_as_csv -> FR-004-AC-1", new)
        changed = [index[i] for i in d["changed"]]
        self.assertEqual([(c["title"], c["status"]) for c in changed],
                         [("US-2-AC-1: then the item is back in the store and its loan closed", "changed")])
        self.assertIn("REQ-SEARCH: Search items", [r["title"] for r in d["removed"]])
        self.assertTrue(kept - {r["id"] for r in d["removed"]} <= set(index))       # the others keep their ids
        self.assertEqual(index[us2["id"]]["status"], "accepted")
        ar.decide(self.p, [changed[0]["id"]], "accept", person=AINO, persona=DEV)
        req = next(r for r in self.p.read("contract.json")["requirements"] if r["id"] == "US-2")
        self.assertEqual(req["acceptance"][0]["then"], "the item is back in the store and its loan closed")
        self.assertEqual(index[changed[0]["id"]]["id"], changed[0]["id"])
        self.assertEqual(ar.view(self.p)["status"]["changed"], 0)
        scanned = self.p.ledger().of_kind("alignment_scanned")[-1]["event"]["payload"]
        self.assertEqual((scanned["scan"], scanned["drift"]["changed"]), (2, 1))


class CommandLineTest(Aligned):
    def cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_ALN1_AC_6_the_command_line_shows_scans_decides_and_refuses_an_unsigned_write(self):
        code, out, _ = self.cli("structure", str(self.repo))
        self.assertEqual(code, 0)
        self.assertIn("Conventions: ADR, Gherkin, GitHub Actions, Kiro, OpenAPI, jest, pytest, spec-kit", out)
        code, out, _ = self.cli("structure", str(self.repo), "--json")
        self.assertEqual(json.loads(out)["counts"]["tests"], 6)
        code, out, _ = self.cli("align", self.p.pid)
        self.assertIn("Not aligned yet", out)
        before = len(self.p.ledger().records())
        code, _, err = self.cli("align", self.p.pid, "--scan")
        self.assertEqual((code, len(self.p.ledger().records())), (2, before))
        self.assertIn("is signed", err)
        code, out, _ = self.cli("align", self.p.pid, "--scan", "--person", AINO, "--persona", DEV)
        self.assertEqual(code, 0)
        self.assertIn("5 of 6 tests trace to a criterion", out)
        code, out, _ = self.cli("align", self.p.pid, "--json")
        view = json.loads(out)
        us1 = self.by_title(view, "requirements", "User Story 1")["id"]
        adr = self.by_title(view, "decisions", "ADR-0002")["id"]
        task = self.by_title(view, "tasks", "1 ")["id"]
        code, out, _ = self.cli("align", self.p.pid, "accept", us1, adr, "--person", AINO, "--persona", DEV)
        self.assertEqual(code, 0, out)
        self.assertIn("The contract is now", out)
        code, out, _ = self.cli("align", self.p.pid, "edit", task, "--set", "done=yes", "--person", AINO, "--persona", DEV)
        self.assertEqual(code, 0, out)
        self.assertTrue(ar.accepted(self.p, "tasks")[0]["proposal"]["done"])
        code, _, err = self.cli("align", self.p.pid, "reject", "req-nope", "--person", AINO, "--persona", DEV)
        self.assertEqual(code, 2)
        self.assertIn("no item req-nope", err)
        change_repo(self.repo)
        self.cli("align", self.p.pid, "--scan", "--person", AINO, "--persona", DEV)
        code, out, _ = self.cli("align", self.p.pid, "--drift", "--json")
        drift = json.loads(out)
        self.assertIn("FR-004: System MUST export loans as CSV", [i["title"] for i in drift["new"]])
        code, out, _ = self.cli("align", self.p.pid, "--drift")
        self.assertIn("Drift of scan 2 since scan 1", out)
        lines = ar.ide_lines(self.p)
        self.assertIn("### Aligned from your repository", lines)
        self.assertTrue(any(line.startswith("- **US-1** (specs/001-loan-items/spec.md, your User Story 1)") for line in lines))
        self.assertIn("### Open gaps", lines)
        trace = self.by_title(ar.view(self.p), "trace", "test_borrow")
        ar.decide(self.p, [trace["id"]], "accept", person=AINO, persona=DEV)
        note = ar.gate_note(self.p, ["tests/test_loans.py"])
        self.assertEqual((note["criteria_touched"], note["accepted_requirements"]), (["US-1-AC-1"], ["US-1"]))
        self.untouched_but_changed()

    def untouched_but_changed(self) -> None:
        self.assertFalse((self.repo / MARKER).exists())
        self.assertEqual(git(self.repo, "status", "--porcelain", "--untracked-files=all"), "")


class AdoptedTest(FactoryTestCase):
    def test_FR_ALN1_AC_7_an_adopted_project_takes_imported_requirements_as_existing_work(self):
        from kernel.adopt import adopt

        repo = make_repo(self.tmp / "loans")
        not_run = {"verdict": "not measured", "reason": "not run in this test", "meaning": "", "runs": []}
        with mock.patch("kernel.adopt.characterise", return_value=not_run):
            p = adopt(self.factory, "Loans", source=str(repo), intent="maintain", person=AINO, persona=DEV)
        before = p.read("contract.json")
        v = ar.scan(p, person=AINO, persona=DEV)
        self.assertIn("refs/remotes/upstream/main", v["scan"]["read_from"])
        us1 = Aligned.by_title(v, "requirements", "User Story 1")
        ar.decide(p, [us1["id"]], "accept", person=AINO, persona=DEV)
        spec = p.read("spec.json")
        self.assertEqual([r["id"] for r in spec["requirements"]], ["R-1", "US-1"])
        contract = p.read("contract.json")
        old = {t["id"]: t["criteria"] for t in before["tasks"]}
        new = {t["id"]: t["criteria"] for t in contract["tasks"]}
        self.assertTrue(all(new[k] == v for k, v in old.items()))                    # every other task keeps its id
        added = next(k for k, c in new.items() if c[0].startswith("US-1-"))
        state = p.read("tasks.json")[added]
        self.assertEqual((state["status"], state["imported"]), ("merged", True))
        self.assertIn("not built by the factory", state["note"])
        shown = subprocess.run(["git", "show", "main:contract.json"], cwd=p.path("repo.git"), capture_output=True,
                               text=True, check=True).stdout
        self.assertEqual(json.loads(shown)["revision"], contract["revision"])


class RoutesTest(CockpitTestCase):
    def test_FR_ALN1_AC_6_the_cockpit_reads_scans_and_decides_signed_and_refuses_a_non_person(self):
        repo = make_repo(self.tmp / "loans")
        p = attach(self.factory, "Loans", repo=repo, person=AINO, persona=DEV)
        base = f"/api/projects/{p.pid}/repo-alignment"
        status, out, _ = self.call("GET", base)
        self.assertEqual((status, out["applies"], out["scanned"]), (200, True, False))
        status, out, _ = self.call("POST", base + "/scan", {"person": "assistant", "persona": DEV})
        self.assertEqual(status, 403)
        self.assertFalse(p.path("alignment").exists())
        status, out, _ = self.call("POST", base + "/scan", {"person": AINO, "persona": DEV})
        self.assertEqual(status, 201, out)
        item = out["groups"][0]["items"][0]["id"]
        status, out, _ = self.call("POST", base + "/decide", {"items": [item], "verdict": "maybe", "person": AINO,
                                                              "persona": DEV})
        self.assertEqual(status, 400)
        status, out, _ = self.call("POST", base + "/decide", {"items": [item], "verdict": "accept", "person": AINO,
                                                              "persona": DEV})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["alignment"]["status"]["accepted"], len(out["items"]))
        status, out, _ = self.call("GET", f"/api/projects/{self.new().pid}/repo-alignment")
        self.assertEqual((status, out["applies"]), (200, False))
        self.assertEqual(sg.suggestions({"items": []}, {}), [])


if __name__ == "__main__":
    unittest.main()
