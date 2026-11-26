"""Which Rihmasto this is, About and help, Ask Rihma's answers about Rihmasto itself, the repository settings
check and an Unreleased section that stays open (FR-PUB2)."""

import contextlib
import copy
import io
import json
import re
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

import repo_settings  # noqa: E402
from kernel import about, version  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.assistant_howto import ANY_PLACEHOLDER, practical  # noqa: E402
from kernel.assistant_rules import CONTROL_PAGES, ui_map  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.doctor import doctor  # noqa: E402
from kernel.parity import CHAT, READS  # noqa: E402
from mcp.server import RihmaMCP  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DECLARED = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
NO_GNOMON = {"found": False, "command": ["gnomon"], "raw": None, "version": None, "build": None}


def quiet_doctor(home):
    with mock.patch("kernel.doctor.gnomon_version", return_value=dict(NO_GNOMON)):
        return doctor(home, routing={}, environ={}, harnesses=[], lanes_root=Path(home) / "lanes")


class VersionTest(FactoryTestCase):
    def test_FR_PUB2_AC_1_rihmasto_version_prints_the_declared_version_and_exits_0(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as done:
            main(["--version"])
        self.assertEqual(done.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"rihmasto {DECLARED}")
        self.assertEqual(version.rihmasto_version(), DECLARED)

    def test_FR_PUB2_AC_1_doctor_reports_rihmastos_own_version_and_whether_it_is_a_pre_release(self):
        report = quiet_doctor(self.factory.home)
        self.assertEqual(report["rihmasto"], {"version": DECLARED, "prerelease": version.is_prerelease(DECLARED)})
        for v, pre in (("1.0.0a1", True), ("1.0.0rc2", True), ("1.0.0.dev0", True), ("1.0.0", False)):
            self.assertEqual(version.is_prerelease(v), pre, v)

    def test_FR_PUB2_AC_1_the_mcp_server_tells_the_declared_version_never_a_hard_coded_one(self):
        server = RihmaMCP(self.factory, person="Tessa", persona="developer", lanes_root=self.tmp / "no-lanes")
        init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                         "clientInfo": {"name": "t", "version": "0"}}})
        self.assertEqual(init["result"]["serverInfo"]["version"], DECLARED)
        self.assertNotIn('SERVER_VERSION = "', (REPO / "mcp" / "server.py").read_text(encoding="utf-8"))

    def test_FR_PUB2_AC_1_a_checkout_without_a_readable_pyproject_says_none_never_a_made_up_number(self):
        self.assertIsNone(version.declared(self.tmp))
        (self.tmp / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "2.3.4b1"\n', encoding="utf-8")
        self.assertEqual(version.declared(self.tmp), "2.3.4b1")


class AboutViewTest(FactoryTestCase):
    def test_FR_PUB2_AC_2_about_lists_the_version_the_commands_and_every_guide_that_exists(self):
        a = about.view()
        self.assertEqual((a["version"], a["commands"]), (DECLARED, {"version": "rihmasto --version",
                                                                    "doctor": "rihmasto doctor"}))
        self.assertEqual({d["for"] for d in a["docs"]}, {"everyone", "contributors", "maintainers"})
        for d in a["docs"]:
            path = d["path"].split("#")[0]
            self.assertTrue((REPO / path).exists(), path)
            self.assertTrue(d["url"].startswith("https://github.com/") and d["url"].endswith(d["path"]))
            anchor = d["path"].partition("#")[2]
            if anchor:                                          # the anchor is a heading of that page
                heads = [re.sub(r"[^a-z0-9 -]", "", h.lstrip("#").strip().lower()).replace(" ", "-")
                         for h in (REPO / path).read_text(encoding="utf-8").splitlines() if h.startswith("#")]
                self.assertIn(anchor, heads, d["path"])

    def test_FR_PUB2_AC_2_the_machine_check_is_doctor_trimmed_to_versions_problems_and_warnings(self):
        with mock.patch("kernel.doctor.gnomon_version", return_value=dict(NO_GNOMON)):
            m = about.machine(self.factory.home, routing={}, environ={}, harnesses=[], lanes_root=self.tmp / "l")
        self.assertEqual(m["rihmasto"]["version"], DECLARED)
        self.assertFalse(m["ok"])                                # no Gnomon: a problem, said plainly
        self.assertTrue(m["python"]["found"] and m["python"]["version"])
        self.assertTrue(any("Gnomon was not found" in p for p in m["problems"]))
        self.assertNotIn("executable", json.dumps(m["python"]))  # no paths of the machine's programs

    def test_FR_PUB2_AC_2_about_help_is_a_read_control_on_the_settings_page(self):
        control = next(c for c in ui_map()["controls"] if c["id"] == "about_help")
        self.assertEqual(control["where"], "Settings")
        self.assertEqual(CONTROL_PAGES["about_help"], (None, "settings"))
        self.assertIn("about_help", READS)
        self.assertNotIn("about_help", CHAT)
        js = (REPO / "cockpit" / "static" / "about.js").read_text(encoding="utf-8")
        self.assertIn('"data-control": "about_help"', js)
        self.assertIn("datum(a.version)", js)                    # kernel data, marked data-ud
        self.assertIn("aboutCard()", (REPO / "cockpit" / "static" / "screens.js").read_text(encoding="utf-8"))


class AboutRoutesTest(CockpitTestCase):
    def test_FR_PUB2_AC_2_the_routes_give_the_view_and_the_machine_check_and_record_nothing(self):
        before = sorted(p.name for p in Path(self.factory.home).rglob("*"))
        status, body, _ = self.call("GET", "/api/about")
        self.assertEqual((status, body["version"]), (200, DECLARED))
        with mock.patch("kernel.doctor.gnomon_version", return_value=dict(NO_GNOMON)):
            status, m, _ = self.call("GET", "/api/about/doctor")
        self.assertEqual(status, 200, m)
        self.assertEqual((m["rihmasto"]["version"], m["command"]), (DECLARED, "rihmasto doctor"))
        self.assertEqual(sorted(p.name for p in Path(self.factory.home).rglob("*")), before)


QUESTIONS = {
    "version": ["what version of Rihmasto is this?", "which version am I running?", "rihmasto --version"],
    "verify": ["how do I verify the Gnomon install/checksums?", "how can I check the SHA256 of the installer?"],
    "doctor": ["is my setup working? check my machine", "how do I run rihmasto doctor?"],
    "ungoverned": ["how do I fix a project that has no governance or traceability?"],
    "structure": ["how much structure should I enforce?", "what are the levels of structure?"],
    "contribute": ["how do I contribute?", "how do I contribute to Rihmasto?"],
    "docs": ["where is the documentation?", "where are the docs for contributors?"],
}
UNCHANGED = ["how do I get started?", "how do I connect Claude Code?", "how do I bring in an existing project?",
             "how do I run its tests?", "what version is the capability pack?", "where is the Cell view?"]


class AskRihmaTest(FactoryTestCase):
    def asked(self, q: str, project=None) -> dict:
        out = ask(self.factory, q, persona="developer", project_id=project.pid if project else None)
        return practical(out, q, project=project, person="Aino Virtanen", persona="developer")

    def test_FR_PUB2_AC_3_each_question_about_rihmasto_gets_its_rule_answer_with_steps_and_take_me_there(self):
        for topic, questions in QUESTIONS.items():
            for q in questions:
                out = self.asked(q)
                self.assertEqual(out.get("topic"), topic, q)
                self.assertEqual(out["by"], "rule", q)
                self.assertTrue(out["navigate"] and out["navigate"]["route"], q)
                self.assertTrue(out["steps"] and out["docs"], q)
                said = out["answer"] + " ".join(s["text"] + " ".join(s.get("commands") or []) for s in out["steps"])
                self.assertIsNone(ANY_PLACEHOLDER.search(said), (q, said))
        self.assertIn(DECLARED, self.asked("what version of Rihmasto is this?")["answer"])
        self.assertEqual(self.asked("where are the docs for contributors?")["docs"][0]["path"], "CONTRIBUTING.md")
        self.assertIn("five levels", self.asked("how much structure should I enforce?")["answer"])

    def test_FR_PUB2_AC_3_inside_a_project_structure_and_governance_open_its_alignment(self):
        p = self.new()
        for q in ("how much structure should I enforce?",
                  "how do I fix a project that has no governance or traceability?"):
            self.assertEqual(self.asked(q, p)["navigate"]["route"], f"#/p/{p.pid}/align", q)
        self.assertEqual(self.asked("how much structure should I enforce?")["navigate"],
                         {"route": "#/projects", "control": "adopt_project"})

    def test_FR_PUB2_AC_3_the_questions_that_already_worked_are_answered_as_before(self):
        for q in UNCHANGED:
            self.assertIsNone(self.asked(q).get("topic"), q)


def fetcher(ruleset: dict, repo: dict, endpoints: dict):
    def fetch(path: str):
        if path.endswith("/rulesets"):
            return 200, [{"id": ruleset["id"], "target": "branch", "enforcement": "active"}]
        if "/rulesets/" in path:
            return 200, copy.deepcopy(ruleset)
        tail = path.split("rihmastoai", 1)[1]
        return endpoints[tail] if tail else (200, copy.deepcopy(repo))
    return fetch


GOOD_RULESET = {"id": 7, "name": "Protect main", "target": "branch", "enforcement": "active", "node_id": "x",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                          {"type": "pull_request", "parameters": dict(repo_settings.PULL_REQUEST)},
                          {"type": "required_status_checks", "parameters": {
                              "strict_required_status_checks_policy": True,
                              "required_status_checks": [{"context": c} for c in repo_settings.REQUIRED_CHECKS]}}],
                "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]}
GOOD_REPO = {**repo_settings.REPO_FLAGS, "security_and_analysis": {k: {"status": "enabled"}
                                                                   for k in repo_settings.SECURITY}}
GOOD_ENDPOINTS = {"/vulnerability-alerts": (204, None), "/private-vulnerability-reporting": (200, {"enabled": True}),
                  "/actions/permissions/workflow": (200, {"default_workflow_permissions": "read"})}


def as_found_live() -> tuple[dict, dict, dict]:
    """The settings the independent check found on 2026-11-25: bypass always, no approval, Dependabot off."""
    rs = copy.deepcopy(GOOD_RULESET)
    rs["rules"][2]["parameters"].update(required_approving_review_count=0, require_code_owner_review=False,
                                        dismiss_stale_reviews_on_push=False)
    rs["rules"][3]["parameters"]["strict_required_status_checks_policy"] = False
    rs["bypass_actors"][0]["bypass_mode"] = "always"
    repo = copy.deepcopy(GOOD_REPO)
    repo["security_and_analysis"]["dependabot_security_updates"] = {"status": "disabled"}
    return rs, repo, {**GOOD_ENDPOINTS, "/vulnerability-alerts": (404, None)}


class RepoSettingsTest(FactoryTestCase):
    def test_FR_PUB2_AC_4_matching_settings_pass_and_exit_0(self):
        result = repo_settings.check(fetcher(GOOD_RULESET, GOOD_REPO, GOOD_ENDPOINTS))
        self.assertEqual((result["ok"], result["gaps"], result["fixed_ruleset"]), (True, [], None))

    def test_FR_PUB2_AC_4_each_drift_is_listed_with_the_owners_command_and_the_fixed_ruleset(self):
        rs, repo, endpoints = as_found_live()
        result = repo_settings.check(fetcher(rs, repo, endpoints), fix_file="rs.json")
        found = {g["setting"]: g["fix"] for g in result["gaps"]}
        self.assertEqual(found["bypass list: pull requests only"],
                         "gh api -X PUT repos/eljaplacido/rihmastoai/rulesets/7 --input rs.json")
        self.assertIn("pull request: require_code_owner_review", found)
        self.assertIn("pull request: required_approving_review_count", found)
        self.assertEqual(found["Dependabot alerts"], "gh api -X PUT repos/eljaplacido/rihmastoai/vulnerability-alerts")
        self.assertEqual(found["dependabot_security_updates"],
                         "gh api -X PUT repos/eljaplacido/rihmastoai/automated-security-fixes")
        fixed = result["fixed_ruleset"]
        self.assertNotIn("id", fixed)                                     # a PUT body: no read-only fields
        self.assertEqual(repo_settings.ruleset_gaps({**fixed, "id": 7}), [])  # the fix closes every ruleset gap
        self.assertEqual(fixed["bypass_actors"][0]["bypass_mode"], "pull_request")

    def test_FR_PUB2_AC_4_the_tool_only_reads_and_writes_the_fix_file_only_when_asked(self):
        rs, repo, endpoints = as_found_live()
        seen = []
        base = fetcher(rs, repo, endpoints)

        def fetch(path):
            seen.append(path)
            return base(path)
        out, fix = io.StringIO(), self.tmp / "rs.json"
        with contextlib.redirect_stdout(out):
            code = repo_settings.main(["check", "--write-fix", str(fix)], fetch=fetch)
        self.assertEqual(code, 1)
        self.assertIn("nothing here changed GitHub", out.getvalue())
        self.assertEqual(json.loads(fix.read_text(encoding="utf-8"))["bypass_actors"][0]["bypass_mode"],
                         "pull_request")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(repo_settings.main(["check"], fetch=fetcher(GOOD_RULESET, GOOD_REPO, GOOD_ENDPOINTS)), 0)
        source = (REPO / "tools" / "repo_settings.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'"-X"|"--method"', source), [])     # gh api is only ever called to GET
        self.assertTrue(all(p.startswith("repos/") for p in seen))

    def test_FR_PUB2_AC_4_the_maintainers_page_names_the_check_and_the_dependabot_settings(self):
        page = " ".join((REPO / "docs" / "maintainers.md").read_text(encoding="utf-8").split())
        for phrase in ("python tools/repo_settings.py check", "Dependabot alerts", "Dependabot security updates",
                       "the Repository admin role, for pull requests only", "gh attestation verify"):
            self.assertIn(phrase, page)


class ChangelogTest(unittest.TestCase):
    def test_FR_PUB2_AC_5_unreleased_has_its_headings_before_the_first_dated_version(self):
        log = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = log.split("## [Unreleased]", 1)[1]
        dated = re.search(r"(?m)^## \[[^\]]+\] - \d{4}-\d{2}-\d{2}$", unreleased)
        self.assertIsNotNone(dated)
        head = unreleased[:dated.start()]
        self.assertEqual(re.findall(r"(?m)^### (\w+)$", head), ["Added", "Changed", "Fixed"])
        first_added = log.index("\n### Added")                   # where an open branch files its entry
        self.assertLess(log.index("## [Unreleased]"), first_added)
        self.assertLess(first_added, log.index("## [" + DECLARED + "]"))
        self.assertIn("Unreleased keeps its empty Added", " ".join((REPO / "CONTRIBUTING.md").read_text(
            encoding="utf-8").split()))


if __name__ == "__main__":
    unittest.main()
