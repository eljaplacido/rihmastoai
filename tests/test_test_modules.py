"""Every test module runs on its own, as CONTRIBUTING advises: `python -m unittest tests.<module>`.

Under `discover -s tests` the tests folder is on the import path, so a module that imports a sibling helper
(`from test_contract_check import base_contract`) works there and fails alone with "No module named". This test
imports every module as `tests.<name>` in a fresh interpreter started from the repository, as the advice runs it.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Each module is imported with the import path as it was at the start, and with no helper a module before it
# imported by its bare name (a module that puts the tests folder on the path itself is not disturbed).
PROBE = """
import importlib, json, pathlib, sys
start, helpers, failed = list(sys.path), {p.stem for p in pathlib.Path("tests").glob("*.py")}, {}
for path in sorted(pathlib.Path("tests").glob("test_*.py")):
    sys.path[:] = start
    for name in [m for m in sys.modules if m.split(".")[0] in helpers]:
        del sys.modules[name]
    try:
        importlib.import_module("tests." + path.stem)
    except ImportError as exc:
        failed[path.stem] = str(exc)
print(json.dumps(failed))
"""


class EachModuleAloneTest(unittest.TestCase):
    def test_every_test_module_imports_as_tests_dot_its_name(self):
        run = subprocess.run([sys.executable, "-c", PROBE], cwd=REPO, capture_output=True, text=True, timeout=600)
        self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        self.assertEqual(json.loads(run.stdout.strip().splitlines()[-1]), {})


if __name__ == "__main__":
    unittest.main()
