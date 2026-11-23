"""Types and the one definition of a person (FR-O8-AC-6, FR-O8-AC-7).

FR-O8-AC-6: mypy reports no error on the listed modules, and none in strict mode on the trust
core (the ledger, its store, the factory home, the definition of a person and the verdicts).
mypy is not a dependency (D-0002), so those checks run when RIHMA_QA_PYTHON names an interpreter
that has it, and skip otherwise. They use the quality gate's fixed settings (no config file,
Python 3.11), and follow imports silently: an error in a module outside the list is not theirs.

FR-O8-AC-7: the kernel and the contract checker share one definition of a person, so a decision
the kernel would refuse to record (made by the assistant, a bot or the kernel) cannot pass the
contract check either.

Standard library only: python -m unittest discover -s tests
"""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import contract_check  # noqa: E402
from test_contract_check import base_contract  # noqa: E402

from kernel import people  # noqa: E402
from kernel.compile import contract_check as kernel_contract_check  # noqa: E402

QA_PYTHON_ENV = "RIHMA_QA_PYTHON"
TRUST_CORE = ("kernel/ledger.py", "kernel/ledgerstore.py", "kernel/store.py", "kernel/people.py",
              "kernel/verdicts.py")
TYPED = TRUST_CORE + (
    "kernel/metrics.py", "kernel/pricing.py", "kernel/projections.py", "kernel/status.py", "kernel/insight.py",
    "kernel/plan.py", "kernel/safestop.py", "kernel/change.py", "kernel/spec.py", "kernel/scaffold.py",
    "kernel/design_road.py", "kernel/dispatch.py", "kernel/gate.py", "kernel/model.py", "kernel/filelock.py",
    "kernel/autonomy.py", "kernel/observations.py", "kernel/evidence_pack.py", "kernel/adopt.py",
    "kernel/workspace.py", "kernel/security.py", "kernel/doctor.py", "kernel/demo.py", "kernel/profiles.py",
    "kernel/lenses.py", "adapters", "mcp", "tools/contract_check.py")
MYPY_ARGS = ("--ignore-missing-imports", "--python-version", "3.11", "--config-file", "",
             "--follow-imports=silent", "--show-error-codes", "--no-error-summary", "--no-pretty",
             "--no-color-output")


def qa_python() -> str | None:
    """The interpreter RIHMA_QA_PYTHON names, when it can run mypy."""
    py = os.environ.get(QA_PYTHON_ENV)
    if not py:
        return None
    try:
        proc = subprocess.run([py, "-m", "mypy", "--version"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return py if proc.returncode == 0 else None


def run_mypy(py: str, paths: tuple[str, ...], *extra: str, cache: str) -> tuple[int, list[str], str]:
    """(exit code, error lines, everything mypy printed) for one mypy run from the repository root."""
    cmd = [py, "-m", "mypy", *paths, *MYPY_ARGS, *extra,
           "--cache-dir", str(Path(tempfile.gettempdir()) / f"rihma-test-typing-{cache}")]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=900)
    errors = [line for line in proc.stdout.splitlines() if ": error:" in line]
    return proc.returncode, errors, (proc.stdout + proc.stderr)[-4000:]


class ListedModulesTest(unittest.TestCase):
    def test_FR_O8_AC_6_every_listed_module_exists(self) -> None:
        missing = [p for p in TYPED if not (ROOT / p).exists()]
        self.assertEqual(missing, [], "a module the typing check names is gone: update TYPED")


class MypyTest(unittest.TestCase):
    py: str

    @classmethod
    def setUpClass(cls) -> None:
        py = qa_python()
        if py is None:
            raise unittest.SkipTest(f"mypy not measured: set {QA_PYTHON_ENV} to an interpreter that has mypy")
        cls.py = py

    def assertClean(self, result: tuple[int, list[str], str]) -> None:
        code, errors, output = result
        self.assertEqual(errors, [], output)
        self.assertEqual(code, 0, output)

    def test_FR_O8_AC_6_trust_core_is_clean_under_strict_mypy(self) -> None:
        self.assertClean(run_mypy(self.py, TRUST_CORE, "--strict", cache="strict"))

    def test_FR_O8_AC_6_listed_modules_have_no_mypy_error(self) -> None:
        self.assertClean(run_mypy(self.py, TYPED, cache="listed"))

    def test_FR_O8_AC_6_the_file_lock_types_on_posix_and_windows(self) -> None:
        # kernel/filelock.py has one branch per platform; mypy checks only the one it runs for.
        for platform in ("linux", "win32"):
            with self.subTest(platform=platform):
                self.assertClean(run_mypy(self.py, ("kernel/filelock.py",), "--strict", "--platform", platform,
                                          cache=f"filelock-{platform}"))


class OnePersonTest(unittest.TestCase):
    def judge(self, contract: dict) -> tuple[int, dict]:
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(contract, fh)
        try:
            return contract_check.run(path)
        finally:
            os.unlink(path)

    def human_violations(self, report: dict) -> list[str]:
        return [v["path"] for v in report.get("violations", []) if v["rule"] == "R-HUMAN"]

    def test_FR_O8_AC_7_the_checker_uses_the_kernels_is_person(self) -> None:
        self.assertIs(contract_check.is_person, people.is_person)
        # loaded by the kernel as a module (kernel/compile.py), the checker holds the same function
        self.assertIs(kernel_contract_check().is_person, people.is_person)

    def test_FR_O8_AC_7_the_checker_keeps_no_list_of_its_own(self) -> None:
        tree = ast.parse((ROOT / "tools" / "contract_check.py").read_text(encoding="utf-8"))
        defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assigned = {t.id for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))
                    for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
        self.assertFalse({name for name in defined if "person" in name.lower()}, defined)
        self.assertNotIn("NOT_A_PERSON", assigned)

    def test_FR_O8_AC_7_factory_actors_cannot_decide_in_a_contract(self) -> None:
        names = sorted(people.NOT_A_PERSON) + [" Kernel ", "ASSISTANT", "Bot", "system"]
        for name in names:
            with self.subTest(name=name):
                c = base_contract()
                c["requirements"][0]["decided_by"] = name
                code, report = self.judge(c)
                self.assertEqual(code, 2, report)
                self.assertEqual(self.human_violations(report), ["/requirements/0/decided_by"])

    def test_FR_O8_AC_7_factory_actors_cannot_sign_a_verification_plan(self) -> None:
        signed = base_contract()
        del signed["requirements"][0]["acceptance"][0]["check"]
        signed["verification_plan"] = [{"criterion": "REQ-014-AC-1", "reason": "needs a real meter",
                                        "signed_by": "product-owner", "signed_on": "2026-11-22"}]
        self.assertEqual(self.judge(signed)[0], 0)
        for name in ("assistant", "bot", "system", "kernel"):
            with self.subTest(name=name):
                c = copy.deepcopy(signed)
                c["verification_plan"][0]["signed_by"] = name
                code, report = self.judge(c)
                self.assertEqual(code, 2, report)
                self.assertEqual(self.human_violations(report), ["/verification_plan/0/signed_by"])

    def test_FR_O8_AC_7_a_named_person_still_decides(self) -> None:
        for name in ("product-owner", "Maria Lindqvist", "owner"):
            with self.subTest(name=name):
                self.assertTrue(people.is_person(name))
                c = base_contract()
                c["requirements"][0]["decided_by"] = name
                self.assertEqual(self.judge(c)[0], 0)

    def test_FR_O8_AC_7_the_checker_runs_as_a_script_from_anywhere(self) -> None:
        # The checker finds the kernel beside it, whatever the working folder and with no PYTHONPATH.
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contract.json"
            c = base_contract()
            c["requirements"][0]["decided_by"] = "assistant"
            path.write_text(json.dumps(c), encoding="utf-8")
            proc = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "contract_check.py"), str(path)],
                                  cwd=tmp, capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("R-HUMAN", proc.stdout)


if __name__ == "__main__":
    unittest.main()
