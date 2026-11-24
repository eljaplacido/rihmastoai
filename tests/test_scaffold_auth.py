"""FR-OUT2: the paved road's sign-in for a web app people sign in to (kernel/scaffold_auth.py), and the guard
hook in the product's server (kernel/scaffold.py). Each product is written to a temp folder and its own suite
runs there, in a process of its own, as the gate runs it."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kernel.redteam import static
from kernel.scaffold import files
from kernel.scaffold_auth import ROAD_SIGN_IN_TESTS, SIGN_IN_FILE, SIGN_IN_GUIDE, SIGN_IN_PY, unprivileged


def write_product(folder: Path, sign_in: bool, changes: dict | None = None) -> Path:
    for rel, text in {**files("Equipment loans", "loans-abc123", "demo", sign_in=sign_in), **(changes or {})}.items():
        if text is None:
            continue
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8", newline="\n")
    return folder


def suite(folder: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("DATA_DIR", "TRAFFIC_LOG", "PYTHONPATH")}
    return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=folder, env=env,
                          capture_output=True, text=True, timeout=600)


def run_in(folder: Path, code: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("DATA_DIR", "TRAFFIC_LOG", "PYTHONPATH")}
    return subprocess.run([sys.executable, "-c", code], cwd=folder, env={**env, "DATA_DIR": str(folder / "data")},
                          capture_output=True, text=True, timeout=120)


class SignInTemplateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rihma-sign-in-")
        self.addCleanup(self.tmp.cleanup)

    def product(self, name: str, sign_in: bool = True, changes: dict | None = None) -> Path:
        return write_product(Path(self.tmp.name) / name, sign_in, changes)

    def test_FR_OUT2_AC_1_the_product_with_sign_in_passes_its_own_suite_and_fails_without_the_sign_in(self):
        proc = suite(self.product("whole"))
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        ran = int(re.search(r"Ran (\d+) test", proc.stderr).group(1))
        checks = re.findall(r"def (test_ROAD_SIGNIN_\w+)", files("T", "p", "explore", sign_in=True)[ROAD_SIGN_IN_TESTS])
        self.assertGreaterEqual(len(checks), 10)
        self.assertGreaterEqual(ran, len(checks) + 7)                       # the scaffold's and the road's checks too
        weakened = {
            "no sign-in": {SIGN_IN_FILE: None},
            "a cheap hash": {SIGN_IN_FILE: SIGN_IN_PY.replace("ITERATIONS = 600_000", "ITERATIONS = 1_000")},
            "no CSRF check": {SIGN_IN_FILE: SIGN_IN_PY.replace("if req.method in CHANGING and not", "if False and not")},
            "no lockout": {SIGN_IN_FILE: SIGN_IN_PY.replace("if acc[\"failures\"] >= MAX_FAILURES:", "if False:")},
            "a cookie scripts read": {SIGN_IN_FILE: SIGN_IN_PY.replace('"HttpOnly", ', "")},
        }
        for name, change in weakened.items():
            with self.subTest(weakened=name):
                text = change[SIGN_IN_FILE]
                self.assertTrue(text is None or text != SIGN_IN_PY, f"the {name} mutation changed nothing")
                self.assertNotEqual(suite(self.product(name.replace(" ", "-"), changes=change)).returncode, 0)

    def test_FR_OUT2_AC_5_the_road_checks_catch_a_sign_in_that_keeps_a_session_token_sent_with_it(self):
        fresh = "    token = _new_session(user)\n"
        self.assertEqual(SIGN_IN_PY.count(fresh), 1)
        fixated = SIGN_IN_PY.replace(fresh, fresh + (                      # session fixation: adopt the sent token
            "    sent = _cookies(req, COOKIE)\n"
            "    if sent:\n"
            "        with _LOCK:\n"
            "            _SESSIONS[_digest(sent[0])] = _SESSIONS.pop(_digest(token))\n"
            "        token = sent[0]\n"))
        proc = suite(self.product("fixated", changes={SIGN_IN_FILE: fixated}))
        self.assertNotEqual(proc.returncode, 0, "a sign-in that keeps a planted session token passed the road's checks")
        self.assertIn("test_ROAD_SIGNIN_a_session_token_sent_with_the_sign_in_is_never_kept", proc.stderr)

    def test_FR_OUT2_AC_2_the_red_team_static_rules_find_nothing_in_a_product_with_sign_in(self):
        folder = self.product("scanned")
        report = static.scan([folder], which=lambda tool: None)
        self.assertEqual([(f.rule, f.path, f.line) for f in report.findings], [])
        layers = {c.layer: c.state for c in report.coverage}
        self.assertEqual((layers["python"], layers["dockerfile"], layers["secrets"]), ("measured", "measured", "measured"))
        dockerfile = (folder / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^USER 10001:10001$")             # the service is not root
        self.assertIn("chown 10001:10001 /data", dockerfile)
        guide = (folder / SIGN_IN_GUIDE).read_text(encoding="utf-8")
        for setting in ("FIRST_ADMIN_USER", "FIRST_ADMIN_PASSWORD", "SIGN_IN_MODE", "SIGN_IN_PROXY_SECRET"):
            self.assertIn(f"`{setting}`", guide)                             # the operator's guide names each
        with self.assertRaises(ValueError):
            unprivileged("FROM scratch\n")

    def test_FR_OUT2_AC_4_the_product_answers_every_request_through_its_guards_and_keeps_passwords_out_of_the_log(self):
        folder = self.product("plain", sign_in=False)
        self.assertFalse((folder / SIGN_IN_FILE).exists())
        code = (
            "import json, os\n"
            "import app.routes\n"
            "from app import server\n"
            "from app.server import guard, handle, respond\n"
            "seen = []\n"
            "@guard\n"
            "def closed(req):\n"
            "    seen.append(req.path)\n"
            "    req.out_headers.append(('X-Guarded', '1'))\n"
            "    return None if (req.method, req.path) == ('GET', '/health') else (401, {'error': 'closed'})\n"
            "out = {'health': respond('GET', '/health')[0], 'missing': respond('GET', '/no-such')[0],\n"
            "       'method': respond('DELETE', '/health')[0], 'header': respond('GET', '/health')[3],\n"
            "       'unguarded': handle('GET', '/no-such')[0], 'seen': seen}\n"
            "class Message:\n"
            "    def items(self):\n"
            "        return [('X-Proxy-Secret', 'forged'), ('X-Proxy-Secret', 'real')]\n"
            "out['joined'] = server._headers(Message())\n"
            "os.environ['TRAFFIC_LOG'] = os.path.join(os.environ['DATA_DIR'], 'traffic.jsonl')\n"
            "os.makedirs(os.environ['DATA_DIR'], exist_ok=True)\n"
            "server.UNRECORDED.add('/sign-in')\n"
            "server._record('POST', '/sign-in?next=/', {'password': 'hidden'}, 303)\n"
            "server._record('POST', '/items', {'name': 'drill'}, 201)\n"
            "out['log'] = open(os.environ['TRAFFIC_LOG'], encoding='utf-8').read()\n"
            "print(json.dumps(out))\n")
        proc = run_in(folder, code)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual((out["health"], out["missing"], out["method"], out["unguarded"]), (200, 401, 401, 404))
        self.assertIn(["X-Guarded", "1"], out["header"])
        self.assertIn("/no-such", out["seen"])                               # a guard answers before a 404
        self.assertEqual(out["joined"], {"X-Proxy-Secret": "forged, real"})   # a repeated header is never one value
        self.assertIn("drill", out["log"])
        self.assertNotIn("hidden", out["log"])


if __name__ == "__main__":
    unittest.main()
