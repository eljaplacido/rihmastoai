"""FR-H10: what a red team scan reports (kernel/redteam/report.py): SARIF the security gate reads,
coverage said honestly per layer, evidence without secrets, canaries listed, and the command line.

The made-up credentials come from test_redteam_static, assembled at run time.
"""

from __future__ import annotations

import ast
import contextlib
import datetime as dt
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_redteam_static import (  # noqa: E402
    AWS_KEY,
    CLEAN,
    DB_PASSWORD,
    DB_URL,
    ENTROPY_VALUE,
    GITHUB_TOKEN,
    JWT,
    REPO,
    SLACK_TOKEN,
    STRIPE_KEY,
    VULNERABLE,
    py,
    scan,
    seeds,
)

from adapters.sarif import ingest, parse  # noqa: E402
from kernel.redteam import static  # noqa: E402
from kernel.redteam.__main__ import main  # noqa: E402
from kernel.redteam import collect  # noqa: E402
from kernel.redteam.masking import evidence, mask  # noqa: E402
from kernel.redteam.report import (  # noqa: E402
    COVERAGE_RULE,
    Coverage,
    NothingMeasured,
    markdown,
    to_sarif,
    write_sarif,
)
from kernel.redteam.rules import RULES  # noqa: E402
from kernel.redteam.secretscan import check_file, check_secrets  # noqa: E402
from kernel.security import accept_risk, findings, security_gate  # noqa: E402

# The canary marker, assembled so that this file carries no marker of its own for a scan to list.
MARK = "# redteam" + ": canary"


def tree(base: Path, files: dict[str, str | bytes]) -> Path:
    """A fresh folder under ``base`` holding ``files`` (text is written as UTF-8)."""
    root = Path(tempfile.mkdtemp(dir=base))
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return root



def parses(source: str) -> bool:
    """Whether this Python can build the syntax tree: 3.12 stops at a nesting depth that 3.13 and
    later reach, and the scan then records the file as a gap instead of checking it (FR-H10-AC-4)."""
    try:
        ast.parse(source)
    except RecursionError:
        return False
    return True

class SarifTest(FactoryTestCase):
    def test_FR_H10_AC_3_the_sarif_is_read_by_the_security_gate_and_blocks_on_the_vulnerable_product(self) -> None:
        report = scan(VULNERABLE)
        out = self.tmp / "vulnerable.sarif"
        doc = write_sarif(out, report)
        self.assertEqual((doc["version"], len(doc["runs"])), ("2.1.0", 1))
        run = doc["runs"][0]
        descriptors = run["tool"]["driver"]["rules"]
        for res in run["results"]:
            self.assertEqual(descriptors[res["ruleIndex"]]["id"], res["ruleId"])
        p = self.new()
        record = ingest(p, out, person="Kaisa", persona="compliance")
        self.assertEqual(record["tools"][0]["name"], "Rihmasto red team (static)")
        by_rule = {f["rule"]: f for f in record["findings"]}
        self.assertEqual(set(by_rule), set(RULES) | {"RT-CANARY"}, "every rule, and the planted canary to review")
        for f in report.findings:
            got = by_rule[f.rule]
            self.assertEqual((got["level"], got["cwe"], got["location"]["uri"], got["location"]["line"]),
                             (f.level, [f.cwe], f.path, f.line))
        self.assertEqual(record["counts"], {"error": 14, "warning": 8, "note": 1, "none": 0})
        gate = security_gate(p)
        self.assertEqual((gate["verdict"], len(gate["blocking"])), ("failed", 14))

        clean = self.tmp / "clean.sarif"
        write_sarif(clean, scan(CLEAN))
        q = self.new(title="Clean loans")
        self.assertEqual([(f["rule"], f["level"]) for f in ingest(q, clean)["findings"]], [("RT-CANARY", "note")])
        self.assertEqual(security_gate(q)["verdict"], "passed")

    def test_FR_H10_AC_3_a_finding_keeps_its_fingerprint_when_lines_move_so_an_acceptance_follows_it(self) -> None:
        moved = self.tmp / "moved"
        shutil.copytree(VULNERABLE, moved)
        routes = moved / "app" / "routes.py"
        routes.write_text("# a new first line\n\n" + routes.read_text(encoding="utf-8"), encoding="utf-8")
        p = self.new()
        first, second = self.tmp / "first.sarif", self.tmp / "second.sarif"
        write_sarif(first, scan(VULNERABLE))
        before = ingest(p, first)["findings"]
        sql = next(f for f in before if f["rule"] == "RT-PY-SQL")
        until = (self.clock.today() + dt.timedelta(days=30)).isoformat()
        accept_risk(p, sql["id"], person="Kaisa", persona="compliance", reason="internal tool, fixed next sprint",
                    expires=until)
        write_sarif(second, scan(moved))
        after = ingest(p, second)["findings"]
        self.assertEqual({f["fingerprint"] for f in before}, {f["fingerprint"] for f in after})
        moved_sql = next(f for f in after if f["rule"] == "RT-PY-SQL")
        self.assertEqual(moved_sql["location"]["line"], seeds(VULNERABLE)["RT-PY-SQL"][1] + 2)
        states = {f["rule"]: f["state"] for f in findings(p)}
        self.assertEqual(states["RT-PY-SQL"], "accepted", "the person's acceptance followed the finding")
        self.assertEqual(states["RT-PY-EVAL"], "open")

    def test_FR_H10_AC_3_each_kind_of_scan_is_its_own_tool_so_a_later_run_never_hides_the_static_findings(
            self) -> None:
        p = self.new()
        static_out, dynamic_out = self.tmp / "static.sarif", self.tmp / "dynamic.sarif"
        write_sarif(static_out, scan(VULNERABLE))
        later = to_sarif([], [Coverage("http", "measured", "3 endpoints probed", 3)], kind="dynamic")
        dynamic_out.write_text(json.dumps(later), encoding="utf-8")
        ingest(p, static_out)
        ingest(p, dynamic_out)
        gate = security_gate(p)
        self.assertEqual(gate["verdict"], "failed", "the dynamic run's silence does not replace the static findings")
        self.assertEqual([s["tool"] for s in gate["scans"]],
                         ["Rihmasto red team (dynamic)", "Rihmasto red team (static)"])


class CoverageTest(FactoryTestCase):
    def test_FR_H10_AC_4_a_layer_with_a_file_it_could_not_read_is_partial_and_nothing_unmeasured_passes(self) -> None:
        report = scan(tree(self.tmp, {"app/ok.py": "x = 1\n", "app/broken.py": "def (:\n", "app/main.js": "let a;\n"}))
        python = next(c for c in report.coverage if c.layer == "python")
        self.assertEqual((python.state, python.files), ("partial", 2))
        self.assertIn("app/broken.py does not parse at line 1", python.reason)
        self.assertEqual(python.verdict(report.findings), "not measured")
        self.assertEqual((report.findings, report.verdict), ([], "not measured"),
                         "a partial layer with no finding is not a pass")
        docker = next(c for c in report.coverage if c.layer == "dockerfile")
        self.assertEqual((docker.state, docker.applicable, docker.reason, docker.verdict([])),
                         ("not measured", False, "no Dockerfiles in the tree", "not applicable"))
        doc = to_sarif(report.findings, report.coverage)
        gaps = [r for r in doc["runs"][0]["results"] if r["ruleId"] == COVERAGE_RULE]
        self.assertEqual([(g["kind"], g["level"]) for g in gaps], [("open", "none")])
        self.assertIn("python: partial", gaps[0]["message"]["text"])
        p = self.new()
        out = self.tmp / "partial.sarif"
        out.write_text(json.dumps(doc), encoding="utf-8")
        recorded = ingest(p, out)["findings"]
        self.assertEqual([(f["rule"], f["level"]) for f in recorded], [(COVERAGE_RULE, "none")],
                         "the gap reaches the ledger beside the findings")
        self.assertEqual(security_gate(p, block_on=("error", "none"))["verdict"], "failed")
        self.assertIn("not measured", markdown(report))

    def test_FR_H10_AC_4_a_scan_that_measured_nothing_writes_no_sarif_and_says_not_measured(self) -> None:
        media = scan(tree(self.tmp, {"assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00"}))
        secrets = next(c for c in media.coverage if c.layer == "secrets")
        self.assertEqual((secrets.state, media.verdict), ("measured", "passed"))
        self.assertIn("1 of them media, judged by name only", secrets.reason)
        store = scan(tree(self.tmp, {"data/loans.sqlite": b"SQLite format 3\x00\x01\x02"}))
        secrets = next(c for c in store.coverage if c.layer == "secrets")
        self.assertEqual((secrets.state, store.verdict), ("not measured", "not measured"),
                         "a database could hold a secret the scan cannot read")
        self.assertIn("data/loans.sqlite is binary, its content not read", secrets.reason)
        nothing = scan(tree(self.tmp, {}))
        self.assertEqual(nothing.verdict, "not measured")
        with self.assertRaises(NothingMeasured):
            to_sarif(nothing.findings, nothing.coverage)
        with mock.patch.object(collect, "MAX_BYTES", 10):
            big = scan(tree(self.tmp, {"notes.txt": "x" * 50, "app.py": "y = 2\n"}))
        secrets = next(c for c in big.coverage if c.layer == "secrets")
        self.assertEqual(secrets.state, "partial")
        self.assertIn("notes.txt", secrets.reason)

    def test_FR_H10_AC_4_generated_code_nested_thousands_deep_is_checked_and_a_crash_would_be_a_gap(self) -> None:
        chain = "import os\ndef f(name):\n    os.system(" + " + ".join(["'x'"] * 3000) + " + name)\n"
        report = scan(tree(self.tmp, {"gen/big.py": chain}))
        python = next(c for c in report.coverage if c.layer == "python")
        if parses(chain):
            self.assertEqual([(f.rule, f.location) for f in report.findings], [("RT-PY-SHELL", "gen/big.py:3")])
            self.assertEqual(python.state, "measured")
        else:                                     # this Python cannot build the tree: never a silent pass
            self.assertEqual(report.findings, [])
            self.assertNotEqual(python.state, "measured")
            self.assertIn("gen/big.py", python.reason)
        real = static.check_python

        def crash_on_functions(module: ast.Module, **kw: Any) -> list[tuple[str, int]]:
            if any(isinstance(node, ast.FunctionDef) for node in module.body):
                raise RecursionError("maximum recursion depth exceeded")
            return real(module, **kw)

        with mock.patch.object(static, "check_python", side_effect=crash_on_functions):
            gap = scan(tree(self.tmp, {"gen/big.py": chain, "gen/ok.py": "x = 1\n"}))
        python = next(c for c in gap.coverage if c.layer == "python")
        self.assertEqual(python.state, "partial")
        self.assertIn("gen/big.py is nested too deeply to check", python.reason)

    def test_FR_H10_AC_9_optional_scanners_are_never_needed_and_say_not_measured(self) -> None:
        absent = static.external_scanners(lambda tool: None)
        self.assertEqual([(c.layer, c.state, c.applicable) for c in absent],
                         [(f"external:{t}", "not measured", False) for t in ("bandit", "semgrep", "trivy")])
        self.assertTrue(all("not on PATH" in c.reason for c in absent))
        present = static.external_scanners(lambda tool: f"/usr/bin/{tool}")
        self.assertTrue(all(c.state == "not measured" and "not run by this layer" in c.reason for c in present))
        self.assertEqual(scan(CLEAN).verdict, "passed", "absent scanners do not hold a measured scan back")


class EvidenceTest(unittest.TestCase):
    def test_FR_H10_AC_5_evidence_is_trimmed_and_no_secret_reaches_a_report(self) -> None:
        report = scan(VULNERABLE)
        outputs = [json.dumps(report.to_dict()), markdown(report),
                   json.dumps(to_sarif(report.findings, report.coverage, canaries=report.canaries))]
        for text in outputs:
            for value in (AWS_KEY, ENTROPY_VALUE, GITHUB_TOKEN):
                self.assertNotIn(value, text)
        self.assertTrue(all(len(f.evidence) <= 160 for f in report.findings))
        self.assertLessEqual(len(evidence("x = 1  " + "y" * 400)), 160)
        for value in (AWS_KEY, GITHUB_TOKEN, SLACK_TOKEN, STRIPE_KEY, JWT, ENTROPY_VALUE):
            with self.subTest(value=value[:6]):
                masked = mask(f'client_secret = "{value}"')
                self.assertNotIn(value[:5], masked, "at most four characters, a sixth of the value, stay readable")
        self.assertNotIn(DB_PASSWORD[:3], mask(DB_URL), "a twelve-character password shows two characters")
        self.assertEqual(mask("server = SimpleHTTPRequestHandler"), "server = SimpleHTTPRequestHandler",
                         "a long name is not a secret")

    def test_FR_H10_AC_5_a_canary_marker_silences_only_its_own_line_and_is_listed_in_the_summary(self) -> None:
        text = (f'canary = "{AWS_KEY}"  {MARK}\n'
                f'leaked = "{AWS_KEY}"\n'
                f'mention = "{AWS_KEY}"  # see the {MARK[2:]} docs\n'
                f'result = eval(user_text)  {MARK}\n')
        hits, canaries = check_secrets("tests/test_keys.py", text)
        self.assertEqual(hits, [("RT-SECRET-PATTERN", 2), ("RT-SECRET-PATTERN", 3)],
                         "the marker does not reach the next line, and a mere mention is not a marker")
        self.assertEqual([(line, kind) for line, kind, _ in canaries],
                         [(1, "AWS access key id"), (4, "marker without a secret")])
        self.assertNotIn(AWS_KEY, canaries[0][2])
        self.assertEqual(py(text), {"RT-PY-EVAL"}, "a marker silences only the secret rules")
        report = scan(VULNERABLE)
        self.assertEqual([(c.location, c.kind) for c in report.canaries], [("tests/test_leaks.py:3", "GitHub token")])
        summary = markdown(report)
        self.assertIn("## Canary markers", summary)
        self.assertIn("`tests/test_leaks.py:3`: GitHub token", summary)
        props = to_sarif(report.findings, report.coverage, canaries=report.canaries)["runs"][0]["properties"]
        self.assertEqual([c["location"] for c in props["canaries"]], ["tests/test_leaks.py:3"])
        self.assertEqual([(c.location, c.kind) for c in scan(CLEAN).canaries], [("tests/test_leaks.py:3", "GitHub token")])

    def test_FR_H10_AC_5_a_planted_secret_file_is_a_canary_and_a_real_secret_beside_it_is_still_found(self) -> None:
        env = f"{MARK} (fake keys for a leak test)\nCANARY_TOKEN={GITHUB_TOKEN}  {MARK}\nAWS_ACCESS_KEY_ID={AWS_KEY}\n"
        hits, canaries = check_file("tests/fixtures/.env", env)
        self.assertEqual(hits, [("RT-SECRET-PATTERN", 3)], "the unmarked line is read and reported")
        self.assertEqual([(line, kind) for line, kind, _ in canaries],
                         [(1, "secret file (environment file)"), (2, "GitHub token")])
        self.assertEqual(check_file("deploy/.env", f"AWS_ACCESS_KEY_ID={AWS_KEY}\n"), ([("RT-SECRET-FILE", 1)], []),
                         "an unmarked secret file is one finding")


class CommandLineTest(unittest.TestCase):
    def run_main(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_FR_H10_AC_8_static_scans_a_path_writes_sarif_and_a_summary_and_exits_by_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sarif, md = Path(tmp) / "out" / "scan.sarif", Path(tmp) / "scan.md"
            code, out, _ = self.run_main("static", str(VULNERABLE), "--sarif", str(sarif), "--markdown", str(md))
            self.assertEqual(code, 1)
            self.assertIn("**Verdict: failed.**", out)
            found = parse(json.loads(sarif.read_text(encoding="utf-8")))["findings"]
            self.assertEqual(len([f for f in found if f["rule"] != "RT-CANARY"]), len(RULES))
            self.assertEqual([(f["level"], f["suppressed_in_source"]) for f in found if f["rule"] == "RT-CANARY"],
                             [("note", True)], "the planted canary reaches the gate, as a note to review")
            self.assertIn("RT-PY-SQL", md.read_text(encoding="utf-8"))
            self.assertNotIn(b"\r\n", sarif.read_bytes())
            code, out, _ = self.run_main("static", str(CLEAN), "--json")
            self.assertEqual((code, json.loads(out)["verdict"]), (0, "passed"))
            empty, none_sarif = Path(tmp) / "empty", Path(tmp) / "none.sarif"
            empty.mkdir()
            code, _, err = self.run_main("static", str(empty), "--sarif", str(none_sarif))
            self.assertEqual(code, 4)
            self.assertIn("not measured", err)
            self.assertFalse(none_sarif.exists())
            self.assertEqual(self.run_main("static", str(Path(tmp) / "missing"))[0], 2)
        code, out, _ = self.run_main("rules")
        self.assertEqual((code, len(out.strip().splitlines())), (0, len(RULES)))

    def test_FR_H10_AC_8_python_m_kernel_redteam_runs_as_a_module(self) -> None:
        proc = subprocess.run([sys.executable, "-m", "kernel.redteam", "static", str(CLEAN), "--json"], cwd=REPO,
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["findings"], [])


if __name__ == "__main__":
    unittest.main()
