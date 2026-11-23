"""FR-H10: what independent attackers slipped past the static layer, each now a seeded defect it catches.

tests/fixtures/redteam/bypass_app holds every bypass the attackers reported, each on a line marked
`seeded: <rule>` (or the line after `seeded below: <rule>`): every one must be caught at that line
and nothing else reported. tests/fixtures/redteam/bypass_clean holds the safe forms and the false
alarms they found on safe code: nothing may be reported there. The scope escapes of the walk
(junctions, folders skipped by name, rules that depended on where the scan started, long paths)
and the canary marker are tested on trees built at run time. Credentials are assembled at run
time, so no literal secret sits in this file.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from adapters.sarif import parse
from kernel.redteam import static
from kernel.redteam.pyrules import check_python
from kernel.redteam.report import CANARY_RULE, Report, to_sarif
from kernel.redteam.secretscan import check_secrets
from kernel.redteam.webrules import check_javascript

FIXTURES = Path(__file__).parent / "fixtures" / "redteam"
BYPASS, BYPASS_CLEAN = FIXTURES / "bypass_app", FIXTURES / "bypass_clean"
SEED = re.compile(r"seeded( below)?:\s*((?:RT-[A-Z]+-[A-Z]+\s*)+)")
GITHUB_TOKEN = "ghp_" + "R3dT3amBypassOnlyNotARealToken0000042"
AWS_KEY = "AKIA" + "Q7REDTEAMBYPASS9"
MARK = "# redteam" + ": canary"
LAYERS = ("python", "javascript", "html", "dockerfile", "actions", "secrets")


def seeds(root: Path) -> set[tuple[str, str, int]]:
    """Every (rule, path, line) a fixture tree seeds; lines counted at `\\n` only, as the rules count them."""
    out = set()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            m = SEED.search(line)
            for rid in (m.group(2).split() if m else []):
                out.add((rid, rel, n + 1 if m.group(1) else n))
    return out


def scan(*paths: Path, **kw: object) -> Report:
    return static.scan(list(paths), which=lambda tool: None, **kw)  # type: ignore[arg-type]


def states(report: Report) -> dict[str, str]:
    return {c.layer: c.state for c in report.coverage if not c.layer.startswith("external:")}


def tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    return root


class StaticBypassTest(unittest.TestCase):
    def test_FR_H10_AC_30_every_static_bypass_is_caught_at_its_seed_and_nothing_else_is_reported(self) -> None:
        planted = seeds(BYPASS)
        self.assertGreaterEqual(len(planted), 90, "the attackers' bypasses are all seeded")
        report = scan(BYPASS)
        found = {(f.rule, f.path, f.line) for f in report.findings}
        self.assertEqual(sorted(planted - found), [], "every bypass is caught at its seed")
        self.assertEqual(sorted(found - planted), [], "nothing else in the tree is reported")
        self.assertEqual(states(report), dict.fromkeys(LAYERS, "measured"))
        self.assertEqual(report.verdict, "failed")

    def test_FR_H10_AC_30_the_safe_forms_and_the_false_alarms_found_on_safe_code_stay_quiet(self) -> None:
        report = scan(BYPASS_CLEAN)
        self.assertEqual([f"{f.location} {f.rule}" for f in report.findings], [])
        self.assertEqual(states(report), dict.fromkeys(LAYERS, "measured"))
        self.assertEqual(report.verdict, "passed")

    def test_FR_H10_AC_30_a_source_encoding_declaration_is_read_as_python_reads_it(self) -> None:
        cookie = BYPASS / "py" / "encoding_cookie.py"
        raw = cookie.read_bytes()
        self.assertEqual(check_python(ast.parse(raw.decode("utf-8"))), [], "read as UTF-8 the code is a comment")
        self.assertEqual(check_python(ast.parse(raw)), [("RT-PY-SHELL", 8)], "Python itself runs it")
        found = [(f.rule, f.line) for f in scan(cookie).findings]
        self.assertEqual(found, [("RT-PY-SHELL", 7)], "reported at the file's own line")
        with tempfile.TemporaryDirectory() as tmp:
            bad = tree(Path(tmp), {"x.py": "# -*- coding: no-such-codec -*-\nx = 1\n"})
            python = next(c for c in scan(bad).coverage if c.layer == "python")
            self.assertEqual(python.state, "not measured")
            self.assertIn("declares a source encoding Python cannot read", python.reason)

    def test_FR_H10_AC_30_a_comment_ends_where_javascript_ends_a_line(self) -> None:
        for ending in ("\r", " ", " ", "\r\n"):
            source = f"// render the greeting{ending}document.getElementById('o').innerHTML = location.hash;"
            with self.subTest(ending=repr(ending)):
                self.assertEqual([rid for rid, _ in check_javascript(source)], ["RT-JS-DOMXSS"])
        self.assertEqual(check_javascript("// el.innerHTML = location.hash;\nlet a = 1;"), [])


class WalkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._clean)

    def _clean(self) -> None:
        for root, dirs, _ in os.walk(self.tmp, topdown=False):
            for d in dirs:
                path = Path(root) / d
                if path.is_symlink() or getattr(os.path, "isjunction", lambda _p: False)(path):
                    os.rmdir(path) if os.name == "nt" else path.unlink()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_FR_H10_AC_31_the_actions_rules_apply_wherever_the_scan_starts(self) -> None:
        workflows = BYPASS / ".github" / "workflows"
        whole = {(f.rule, f.line) for f in scan(BYPASS).findings if f.path.endswith("inject.yml")}
        self.assertTrue(whole)
        for target in (BYPASS / ".github", workflows, workflows / "inject.yml"):
            with self.subTest(target=target.name):
                report = scan(target)
                self.assertEqual({(f.rule, f.line) for f in report.findings}, whole)
                self.assertEqual(states(report)["actions"], "measured")

    def _link(self, link: Path, target: Path) -> None:
        if os.name == "nt":
            done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            if done.returncode:
                self.skipTest("this machine cannot make a junction")
        else:
            os.symlink(target, link, target_is_directory=True)

    def test_FR_H10_AC_32_a_junction_or_link_out_of_the_tree_is_not_read_and_is_listed(self) -> None:
        outside = tree(self.tmp / "outside", {"private_notes.py": f'GH = "{GITHUB_TOKEN}"\n'})
        repo = tree(self.tmp / "repo", {"app/main.py": "def main():\n    return 1\n"})
        self._link(repo / "app" / "shared", outside)
        report = scan(repo)
        self.assertEqual(report.findings, [], "nothing outside the tree is read")
        self.assertEqual(next(c for c in report.coverage if c.layer == "python").files, 1)
        self.assertTrue(any("app/shared/" in n and "link or junction" in n for n in report.notes), report.notes)

    def test_FR_H10_AC_32_folders_skipped_by_name_are_listed_and_a_package_named_venv_is_read(self) -> None:
        repo = tree(self.tmp / "repo", {
            "app/venv/manage.py": "import os\ndef make(name):\n    os.system('virtualenv ' + name)\n",
            "app/node_modules/helper/config.js": f'const token = "{GITHUB_TOKEN}";\n',
            ".venv/pyvenv.cfg": "home = /usr/bin\n", ".venv/lib/site.py": "x = 1\n"})
        report = scan(repo)
        self.assertEqual([(f.rule, f.path) for f in report.findings], [("RT-PY-SHELL", "app/venv/manage.py")],
                         "a product package named venv is read; installed dependencies are not")
        skipped = next(n for n in report.notes if n.startswith("Not read, by folder name"))
        self.assertIn("app/node_modules (1 file, installed dependencies)", skipped)
        self.assertIn(".venv (2 files, a virtual environment)", skipped)

    def test_FR_H10_AC_32_a_person_can_exclude_paths_and_the_exclusion_is_listed(self) -> None:
        repo = tree(self.tmp / "repo", {"vendor/lib.py": "import os\nos.system('x ' + y)\n", "app.py": "x = 1\n"})
        report = scan(repo, exclude=["vendor/*"])
        self.assertEqual(report.findings, [])
        self.assertTrue(any("Excluded by the person running the scan: 1 file(s), e.g. vendor/lib.py" in n
                            for n in report.notes), report.notes)

    @unittest.skipUnless(os.name == "nt", "the 260-character limit is Windows's")
    def test_FR_H10_AC_32_a_path_over_the_windows_limit_is_read_like_any_other(self) -> None:
        deep = self.tmp / "repo" / "/".join(["a-folder-name-of-forty-characters-long-x"] * 7)
        os.makedirs("\\\\?\\" + str(deep), exist_ok=True)
        with open("\\\\?\\" + str(deep / "tool.py"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("import os\ndef run(cmd):\n    os.system('sh ' + cmd)\n")
        self.assertGreater(len(str(deep / "tool.py")), 260)
        report = scan(self.tmp / "repo")
        self.assertEqual([f.rule for f in report.findings], ["RT-PY-SHELL"])
        self.assertEqual(states(report)["python"], "measured")


class CanaryTest(unittest.TestCase):
    def test_FR_H10_AC_33_a_canary_marker_in_the_products_own_code_silences_nothing(self) -> None:
        line = f'AWS_KEY = "{AWS_KEY}"  {MARK}\n'
        hits, canaries = check_secrets("app/aws.py", line)
        self.assertEqual(hits, [("RT-SECRET-PATTERN", 1)], "outside a test suite the key is reported")
        self.assertIn("marker ignored outside a test suite", canaries[0][1])
        hits, canaries = check_secrets("tests/test_aws.py", line)
        self.assertEqual((hits, [kind for _, kind, _ in canaries]), ([], ["AWS access key id"]))

    def test_FR_H10_AC_33_a_planted_canary_reaches_the_security_gate_as_a_note_to_review(self) -> None:
        report = scan(FIXTURES / "vulnerable_app")
        doc = to_sarif(report.findings, report.coverage, canaries=report.canaries)
        planted = [r for r in doc["runs"][0]["results"] if r["ruleId"] == CANARY_RULE]
        self.assertEqual([(r["kind"], r["level"], r["suppressions"][0]["kind"]) for r in planted],
                         [("review", "note", "inSource")])
        self.assertNotIn(GITHUB_TOKEN, json.dumps(doc))
        found = [f for f in parse(doc)["findings"] if f["rule"] == CANARY_RULE]
        self.assertEqual([(f["location"]["uri"], f["suppressed_in_source"]) for f in found],
                         [("tests/test_leaks.py", True)])


if __name__ == "__main__":
    unittest.main()
