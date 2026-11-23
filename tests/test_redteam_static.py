"""FR-H10: Rihmasto's own static rules (kernel/redteam), each proven by a seeded defect and a clean twin.

tests/fixtures/redteam/vulnerable_app holds one seeded defect per rule, each on a line marked
`seeded: <rule>` (or the line after `seeded below: <rule>`); clean_app is the same product written
safely. Beside the fixtures, each rule has variants it must catch and near misses it must not
report. Credentials in this file are assembled at run time, so no literal secret sits in the source.
"""

from __future__ import annotations

import ast
import re
import sys
import tempfile
import unittest
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from kernel.redteam import static
from kernel.redteam.configrules import check_actions, check_dockerfile, entry_points, is_entry_point
from kernel.redteam.pyrules import check_python
from kernel.redteam.report import Report
from kernel.redteam.rules import OWASP_2025, RULES, SEVERITY_LEVEL
from kernel.redteam.secretscan import check_secrets, secret_file
from kernel.redteam.webrules import check_html, check_javascript

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "redteam"
VULNERABLE, CLEAN = FIXTURES / "vulnerable_app", FIXTURES / "clean_app"
SEED = re.compile(r"seeded( below)?:\s*((?:RT-[A-Z]+-[A-Z]+\s*)+)")

# Made-up credentials, assembled so that this file holds none as a literal.
AWS_KEY = "AKIA" + "Q7REDTEAMSEED042"
GITHUB_TOKEN = "ghp_" + "R3dT3amCanaryOnlyNotARealToken000042"
SLACK_TOKEN = "xox" + "b-123456789012-abcdefghijkl"
STRIPE_KEY = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0." + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----\\n" + "MIIEowIBAAKCAQEA" + "q7RedTeamFakeKeyBody" * 3
DB_PASSWORD = "Vx9Kt7" + "Wp3Nb6"
DB_URL = "postgres://loans:" + DB_PASSWORD + "@db.internal:5432/loans"
ENTROPY_VALUE = "tq8Vz3" + "LmW9pXr2Kd7NfYb4Hs"

# A generated module with a `+` chain thousands of terms deep: checked, not skipped.
DEEP_CHAIN = "import os\ndef f(name):\n    cmd = " + " + ".join(["'x'"] * 3000) + " + name\n    os.system(cmd)\n"

PY_RECALL = {
    "import subprocess\nsubprocess.run(cmd, shell=True)\n": "RT-PY-SHELL",
    "import os\nos.system('ls ' + folder)\n": "RT-PY-SHELL",
    "from subprocess import Popen\nPopen(f'tar xf {name}', shell=True)\n": "RT-PY-SHELL",
    DEEP_CHAIN: "RT-PY-SHELL",
    "exec(code)\n": "RT-PY-EVAL",
    "import yaml\nyaml.load(text)\n": "RT-PY-DESER",
    "import pickle as pk\npk.load(fh)\n": "RT-PY-DESER",
    "import marshal\nmarshal.loads(blob)\n": "RT-PY-DESER",
    "import torch\ntorch.load(path)\n": "RT-PY-DESER",
    "import numpy as np\nnp.load(path, allow_pickle=True)\n": "RT-PY-DESER",
    "cur.execute('SELECT * FROM t WHERE id = %s' % uid)\n": "RT-PY-SQL",
    "cur.execute('SELECT * FROM t WHERE id = {}'.format(uid))\n": "RT-PY-SQL",
    "cur.execute('DELETE FROM t WHERE id = ' + uid)\n": "RT-PY-SQL",
    "def f(uid):\n    q = f'UPDATE t SET seen = 1 WHERE id = {uid}'\n    cur.execute(q)\n": "RT-PY-SQL",
    "import urllib.request\nurllib.request.urlopen(url, timeout=None)\n": "RT-PY-TIMEOUT",
    "import requests\nrequests.get(url)\n": "RT-PY-TIMEOUT",
    "import socket\nsocket.create_connection(address)\n": "RT-PY-TIMEOUT",
    "import http.client\nhttp.client.HTTPSConnection(host)\n": "RT-PY-TIMEOUT",
    "import urllib.request\nOPENER = urllib.request.build_opener()\nOPENER.open(req)\n": "RT-PY-TIMEOUT",
    "import urllib.request\ndef fetch(url, direct):\n    opener = urllib.request.build_opener() if direct else None\n"
    "    return opener.open(url)\n": "RT-PY-TIMEOUT",
    "import hashlib\ndef make_token(seed):\n    return hashlib.sha1(seed).hexdigest()\n": "RT-PY-WEAKHASH",
    "import hashlib\napi_key_digest = hashlib.md5(raw).hexdigest()\n": "RT-PY-WEAKHASH",
    "import hashlib\nhashlib.new('md5', password)\n": "RT-PY-WEAKHASH",
    "from tempfile import mktemp\nmktemp()\n": "RT-PY-MKTEMP",
    "app.debug = True\n": "RT-PY-DEBUG",
    "app.config['DEBUG'] = True\n": "RT-PY-DEBUG",
    "from werkzeug.serving import run_simple\nrun_simple('127.0.0.1', 5000, app, use_debugger=True)\n": "RT-PY-DEBUG",
    "sock.bind(('', 8080))\n": "RT-PY-BINDALL",
    "uvicorn.run(app, host='0.0.0.0')\n": "RT-PY-BINDALL",
    "HOST = '0.0.0.0'\nHTTPServer((HOST, 80), Handler)\n": "RT-PY-BINDALL",
    "def serve(port):\n    host = '0.0.0.0'\n    return HTTPServer((host, port), Handler)\n": "RT-PY-BINDALL",
    "def serve(port, host='0.0.0.0'):\n    return port\n": "RT-PY-BINDALL",
    "parser.add_argument('--host', default='0.0.0.0')\n": "RT-PY-BINDALL",
    "import os\nhost = os.environ.get('BIND_ADDR', '::')\n": "RT-PY-BINDALL",
    "requests.get(url, timeout=5, verify=False)\n": "RT-PY-TLS",
    "import ssl\nctx.verify_mode = ssl.CERT_NONE\n": "RT-PY-TLS",
    "ctx.check_hostname = False\n": "RT-PY-TLS",
    "def h(req):\n    return open(req.query['f']).read()\n": "RT-PY-PATH",
    "def h(request):\n    name = request.args.get('f')\n    p = os.path.join(BASE, name)\n"
    "    return Path(p).read_text()\n": "RT-PY-PATH",
    "def h(req):\n    for part in req.query['files']:\n        os.remove(part)\n": "RT-PY-PATH",
    "def h(req):\n    p = os.path.join(BASE, req.params['f'])\n    if not p.startswith(BASE):\n        return 403\n"
    "    return open(p).read()\n": "RT-PY-PATH",
    "from http.server import BaseHTTPRequestHandler\nclass H(BaseHTTPRequestHandler):\n    def do_GET(self):\n"
    "        with open('www' + self.path) as fh:\n            self.wfile.write(fh.read())\n": "RT-PY-PATH",
}

PY_QUIET = (
    "import subprocess\nsubprocess.run('ls -l', shell=True)\n",
    "import subprocess\ndef f():\n    cmd = 'uptime'\n    subprocess.run(cmd, shell=True)\n",
    "import subprocess\nsubprocess.run(['ls', path])\n", "import os\nos.system('ls')\n",
    "eval('1 + 1')\n", "import ast\nast.literal_eval(text)\n", "model.eval()\n",
    "import yaml\nyaml.load(text, Loader=yaml.SafeLoader)\n", "import yaml\nyaml.safe_load(text)\n",
    "import torch\ntorch.load(path, weights_only=True)\n", "import numpy as np\nnp.load(path)\n",
    "cur.execute('SELECT * FROM t WHERE id = ?', (uid,))\n",
    "cur.execute('SELECT * FROM t WHERE id = %s', (uid,))\n",
    "TABLE = 'loans'\ncur.execute(f'SELECT * FROM {TABLE}')\n",
    "def f(ids):\n    marks = ','.join('?' * len(ids))\n"
    "    cur.execute(f'SELECT * FROM t WHERE id IN ({marks})', ids)\n",
    "log.execute(f'{name} started')\n",
    "import urllib.request\nurllib.request.urlopen(url, timeout=5)\n",
    "import urllib.request\nurllib.request.urlopen(url, None, 5)\n",
    "import requests\nrequests.post(url, json=body, timeout=10)\n",
    "import requests\nrequests.get(url, **opts)\n",
    "import urllib.request\nOPENER = urllib.request.build_opener()\nOPENER.open(req, timeout=3)\n",
    "import urllib.request\nDIRECT = urllib.request.build_opener()\ndef fetch(req, direct):\n"
    "    opener = DIRECT if direct else urllib.request.build_opener()\n"
    "    with opener.open(req, timeout=5) as resp:\n        return resp.read()\n",
    "import hashlib\nhashlib.md5(password, usedforsecurity=False)\n",
    "import hashlib\nhashlib.md5(url.encode()).hexdigest()\n",
    "import tempfile\ntempfile.mkstemp()\n", "app.run(debug=False)\n",
    "app.run(debug=os.environ.get('DEBUG') == '1')\n", "sock.bind(('127.0.0.1', 80))\n",
    "def free_port(host='127.0.0.1'):\n    with socket.socket() as s:\n        s.bind((host, 0))\n"
    "        return s.getsockname()[1]\n",
    "parser.add_argument('--host', default='127.0.0.1')\n", "if bind in ('0.0.0.0', '::'):\n    pass\n",
    "TEMPLATE = '''host = os.environ.get(\"HOST\", \"0.0.0.0\")\nos.system(cmd)'''\n",
    "requests.get(url, timeout=5, verify='/etc/ssl/ca.pem')\n",
    "def h(req):\n    name = os.path.basename(req.params['f'])\n    return open(os.path.join(BASE, name)).read()\n",
    "def h(req):\n    p = (BASE / req.params['f']).resolve()\n    if not p.is_relative_to(BASE):\n"
    "        return 404\n    return p.read_bytes()\n",
    "def h(req):\n    name = req.params['f']\n    if not NAME.fullmatch(name):\n        return 404\n"
    "    return open(BASE + name).read()\n",
    "def h(req):\n    name = req.params['f']\n    if name not in ALLOWED:\n        return 404\n"
    "    return open(BASE + name).read()\n",
    "def h(req):\n    real = os.path.realpath(os.path.join(BASE, req.params['f']))\n"
    "    if not real.startswith(BASE):\n        return 403\n    return open(real).read()\n",
    "class H(BaseHTTPRequestHandler):\n    def static(self, name):\n        if not NAME.match(name):\n"
    "            return None\n        return (STATIC / name).read_bytes()\n",
    "def h(path):\n    return open(path).read()\n", "def h(req):\n    return int(req.params['n'])\n",
    "class C:\n    def go(self):\n        return open(self.path).read()\n",
)

JS_RECALL = {
    "el.innerHTML = x;": "RT-JS-DOMXSS", "el.innerHTML += `<li>${item.name}</li>`;": "RT-JS-DOMXSS",
    "el.innerHTML = escapeHtml(a) + b;": "RT-JS-DOMXSS", "el.outerHTML = html;": "RT-JS-DOMXSS",
    "el.insertAdjacentHTML('beforeend', row);": "RT-JS-DOMXSS", "document.write(location.hash);": "RT-JS-DOMXSS",
    "el.innerHTML =\n  '<b>' +\n  name;": "RT-JS-DOMXSS", "el.innerHTML = unescapeHtml(x);": "RT-JS-DOMXSS",
    "el.innerHTML = describe(x);": "RT-JS-DOMXSS", "eval(x)": "RT-JS-EVAL", "new Function('a', body)": "RT-JS-EVAL",
}
# Rendering data written in the script is quiet (JS_QUIET); each way the data could stop being that is not.
_TILES = "const TILES = [{l: 'a'}];\n"
_EACH = "TILES.forEach(function (t) {\n"
JS_RECALL |= dict.fromkeys((
    _TILES + "TILES.push(input);\n" + _EACH + "  el.innerHTML = t.l;\n});",
    _TILES + "const z = `${TILES.push(input)}`;\n" + _EACH + "  el.innerHTML = t.l;\n});",
    "const TILES = [{l: name}];\n" + _EACH + "  el.innerHTML = t.l;\n});",
    "const TILES = [`${location.hash}`];\n" + _EACH + "  el.innerHTML = t;\n});",
    _TILES + _EACH + "  x = 1;\n});\nel.innerHTML = t.l;",
    _TILES + _EACH + "  fetch(u).then(function (t) {\n    el.innerHTML = t.body;\n  });\n});",
    _TILES + _EACH + "  t.l = location.hash;\n  el.innerHTML = t.l;\n});",
    _TILES + _EACH + "  t = data;\n  el.innerHTML = t.l;\n});",
    _TILES + "const other = TILES;\n" + _EACH + "  el.innerHTML = t.l;\n});",
    "let TILES = [{l: 'a'}];\n" + _EACH + "  el.innerHTML = t.l;\n});",
    _TILES + _EACH + "  el.innerHTML = t.l.replace('a', q);\n});",
), "RT-JS-DOMXSS")

JS_QUIET = (
    "el.innerHTML = '';", "el.innerHTML = '<b>' + 'x' + '</b>';",
    "el.innerHTML = `<li>${escapeHtml(item.name)}</li>`;", "el.innerHTML = DOMPurify.sanitize(html);",
    "el.insertAdjacentHTML('beforeend', '<hr>');", "document.write('<p>hi</p>');", "el.textContent = x;",
    "if (el.innerHTML == x) {}", "// el.innerHTML = x;", "/* document.write(x) */",
    "const s = 'el.innerHTML = x; eval(y)';", "eval('2 + 2')", "obj.eval(x)", "evaluate(x)",
    "new Function('a', 'return a')",
    "const TILES = [{l: \"a\", v: '1', s: [1, 2.5, -3]}, {l: \"b\", v: \"2\", ok: true}];\n"
    "TILES.forEach(function (t, i) {\n  el.innerHTML = '<b>' + t.l + '</b>' + (i + 1);\n});",
    "const NAMES = ['a', 'b'];\nNAMES.forEach((n) => {\n  list.insertAdjacentHTML('beforeend', `<li>${n}</li>`);\n});",
    "const ROWS = [['a', 1]];\nconst host = document.getElementById('ROWS');\n"
    "ROWS.forEach(function (r) {\n  host.innerHTML += '<td>' + r[0] + '</td>';\n});",
)

HTML_QUIET = (
    '<script src="https://cdn.example.org/a.js" integrity="sha384-abc" crossorigin></script>',
    '<script src="/static/a.js"></script>', '<!-- <script src="https://x.org/a.js"></script> -->',
    '<script type="application/ld+json">{"a": "eval(x)"}</script>',
)

DOCKER_RECALL = {
    "FROM python:latest\nUSER app\n": {"RT-DOCKER-UNPINNED"},
    "FROM registry.local:5000/team/python\nUSER app\n": {"RT-DOCKER-UNPINNED"},
    "FROM python:3.12\nUSER app\nUSER root\n": {"RT-DOCKER-ROOT"},
    "FROM python:3.12\nUSER 0\n": {"RT-DOCKER-ROOT"},
    "FROM python:3.12 AS build\nUSER app\nFROM python:3.12-slim\nCOPY --from=build /a /a\n": {"RT-DOCKER-ROOT"},
    "FROM python:3.12\nUSER app\nADD git@example.org:team/tool.git /tool\n": {"RT-DOCKER-ADDURL"},
    'FROM python:3.12\nUSER app\nADD ["https://example.org/a.tgz", "/a"]\n': {"RT-DOCKER-ADDURL"},
}

DOCKER_QUIET = (
    "FROM python:3.12-slim\nUSER app\n", "FROM registry.local:5000/team/python:3.12\nUSER app\n",
    "FROM python@sha256:" + "a" * 64 + "\nUSER app\n", "ARG BASE=python:3.12\nFROM ${BASE}\nUSER app\n",
    "FROM python:3.12 AS build\nUSER app\nFROM build\n", "FROM gcr.io/distroless/python3:nonroot\n",
    "FROM python:3.12\nUSER app\nADD --checksum=sha256:abc https://example.org/a.tgz /a\n",
    "FROM python:3.12\nUSER app\nADD ./local.tgz /a\n",
    "FROM python:3.12\nUSER app\nRUN echo hi \\\n  && echo ADD https://example.org/a /b\n",
)

ACTIONS_RECALL = {
    "steps:\n  - uses: docker://alpine:3.20\n": ("RT-GHA-UNPINNED", 2),
    "steps:\n  - uses: actions/setup-python@main\n": ("RT-GHA-UNPINNED", 2),
    "jobs:\n  build:\n    uses: team/ci/.github/workflows/build.yml@v1\n": ("RT-GHA-UNPINNED", 3),
    "steps:\n  - run: git checkout ${{ github.head_ref }}\n": ("RT-GHA-INJECT", 2),
    "steps:\n  - run: >\n      echo ${{ github.event.pull_request.body }}\n": ("RT-GHA-INJECT", 3),
}

ACTIONS_QUIET = (
    "  - uses: actions/checkout@" + "a" * 40 + "\n", "  - uses: ./local-action\n",
    "  - uses: docker://alpine@sha256:" + "b" * 64 + "\n", "  - run: echo ${{ github.event.issue.number }}\n",
    "  - run: echo ${{ github.base_ref }}\n", "    if: github.event.issue.title == 'x'\n",
    "  - env:\n      T: ${{ github.event.issue.title }}\n    run: echo \"$T\"\n",
    "  - run: |\n      echo hi\n    with:\n      x: ${{ github.event.issue.title }}\n",
)

SECRET_QUIET = (
    'key = "AKIAIOSFODNN7EXAMPLE"', 'url = "postgres://app:${DB_PASSWORD}@db/app"',
    f'url = "postgres://app:{DB_PASSWORD}@db.example.com/app"', f'url = "https://ci:{DB_PASSWORD}@build.test/x"',
    'db_password = os.environ["DB_PASSWORD"]', 'token_env = "RIHMA_TOKEN"', 'password = "changeme-please-now"',
    'token_url = "https://auth.example.org/token"',
    'sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"',
    f'password_hash = "{ENTROPY_VALUE}"', "steps = 'risk-assessor task-planner'",
)


def seeds(root: Path) -> dict[str, tuple[str, int]]:
    """{rule id: (relative path, line)} from the `seeded:` markers of a fixture tree."""
    out = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = SEED.search(line)
            for rid in (m.group(2).split() if m else []):
                out[rid] = (rel, n + 1 if m.group(1) else n)
    return out


def rules_in(hits: Iterable[tuple[str, int]]) -> set[str]:
    return {rid for rid, _ in hits}


def parses(source: str) -> bool:
    """Whether this Python can build the syntax tree: 3.12 stops at a nesting depth that 3.13 and
    later reach, and the scan then records the file as a gap instead of checking it (FR-H10-AC-4)."""
    try:
        ast.parse(source)
    except RecursionError:
        return False
    return True


def py(source: str, **kw: Any) -> set[str]:
    return rules_in(check_python(ast.parse(source), **kw))


def scan(path: Path, **kw: Any) -> Report:
    """A static scan with no external scanner on PATH, whatever this machine has."""
    return static.scan([path], which=lambda tool: None, **kw)


class RecallTest(unittest.TestCase):
    def test_FR_H10_AC_1_every_rule_catches_its_seeded_defect_at_the_marked_line(self) -> None:
        planted = seeds(VULNERABLE)
        self.assertEqual(set(planted), set(RULES), "every rule has exactly one seed, and every seed a rule")
        report = scan(VULNERABLE)
        found = {(f.rule, f.path, f.line) for f in report.findings}
        for rid, (path, line) in sorted(planted.items()):
            self.assertIn((rid, path, line), found, f"{rid} missed its seed at {path}:{line}")
        self.assertEqual(Counter(f.rule for f in report.findings), Counter(dict.fromkeys(RULES, 1)),
                         "one finding per seed: nothing else in the vulnerable product is reported")
        self.assertEqual(report.verdict, "failed")

    def test_FR_H10_AC_1_each_rule_names_a_cwe_an_owasp_2025_category_a_severity_and_a_fix(self) -> None:
        self.assertGreaterEqual(len(RULES), 20)
        for r in RULES.values():
            self.assertRegex(r.cwe, r"^CWE-\d+$", r.id)
            self.assertIn(r.owasp, OWASP_2025, r.id)
            self.assertEqual(r.level, SEVERITY_LEVEL[r.severity], r.id)
            self.assertTrue(r.fix and r.title, r.id)
        for f in scan(VULNERABLE).findings:
            rule = RULES[f.rule]
            self.assertEqual((f.cwe, f.owasp, f.layer, f.severity, f.level, f.fix),
                             (rule.cwe, rule.owasp, rule.layer, rule.severity, rule.level, rule.fix))
            self.assertEqual(f.location, f"{f.path}:{f.line}")

    def test_FR_H10_AC_1_python_rules_catch_the_variants_of_each_defect(self) -> None:
        for source, rid in PY_RECALL.items():
            with self.subTest(source=source[:120]):
                if not parses(source):         # this Python cannot build the tree: a gap (AC-4)
                    continue
                self.assertEqual(py(source), {rid})
        self.assertEqual(set(PY_RECALL.values()), {r.id for r in RULES.values() if r.layer == "python"})

    def test_FR_H10_AC_1_javascript_and_html_rules_catch_their_variants(self) -> None:
        for source, rid in JS_RECALL.items():
            with self.subTest(js=source):
                self.assertEqual(rules_in(check_javascript(source)), {rid})
        self.assertEqual(check_html('<p>\n<script>\n  el.innerHTML = location.hash;\n</script>'),
                         [("RT-JS-DOMXSS", 3)], "an inline script is checked at its own lines")
        self.assertEqual(check_html('<script src="//cdn.example.org/a.js"></script>'), [("RT-HTML-SRI", 1)])

    def test_FR_H10_AC_1_dockerfile_and_actions_rules_catch_their_variants(self) -> None:
        for source, expected in DOCKER_RECALL.items():
            with self.subTest(dockerfile=source):
                self.assertEqual(rules_in(check_dockerfile(source)), expected)
        for source, hit in ACTIONS_RECALL.items():
            with self.subTest(workflow=source):
                self.assertEqual(check_actions(source), [hit])

    def test_FR_H10_AC_1_secret_rules_catch_known_formats_high_entropy_values_and_secret_files(self) -> None:
        corp_url = "postgres://loans:" + DB_PASSWORD + "@db.example-corp.io/loans"
        for value in (AWS_KEY, GITHUB_TOKEN, SLACK_TOKEN, STRIPE_KEY, JWT, PRIVATE_KEY, DB_URL, corp_url):
            with self.subTest(secret=value[:6]):
                self.assertEqual(check_secrets("app/config.py", f"x = '{value}'\n")[0], [("RT-SECRET-PATTERN", 1)])
        self.assertEqual(check_secrets("app/config.py", f'db_password = "{ENTROPY_VALUE}"\n')[0],
                         [("RT-SECRET-ENTROPY", 1)])
        self.assertEqual(check_secrets("deploy/.env.example", f"API_TOKEN={ENTROPY_VALUE}\n")[0],
                         [("RT-SECRET-ENTROPY", 1)])
        for name, head in ((".env", ""), (".env.local", ""), ("id_ed25519", ""), ("store.p12", ""),
                           ("key.pem", PRIVATE_KEY), (".npmrc", "//registry.npmjs.org/:_authToken=abc"),
                           ("sa.json", '{"type": "service_account", "private_key": "..."}'),
                           ("prod.tfstate", ""), (".git-credentials", "")):
            with self.subTest(secret_file=name):
                self.assertIsNotNone(secret_file(f"deploy/{name}", head))


class PrecisionTest(unittest.TestCase):
    def test_FR_H10_AC_2_the_clean_twin_yields_no_finding(self) -> None:
        report = scan(CLEAN)
        self.assertEqual([f.location + " " + f.rule for f in report.findings], [])
        self.assertEqual(report.verdict, "passed")
        self.assertEqual({c.layer: c.state for c in report.coverage if not c.layer.startswith("external:")},
                         dict.fromkeys(("python", "javascript", "html", "dockerfile", "actions", "secrets"),
                                       "measured"))

    def test_FR_H10_AC_2_python_near_misses_a_careless_rule_would_report_stay_quiet(self) -> None:
        for source in PY_QUIET:
            with self.subTest(python=source):
                self.assertEqual(py(source), set())
        self.assertEqual(py("HTTPServer(('0.0.0.0', 80), H)\n", entry_point=True), set(),
                         "a container's entry point may bind all interfaces")

    def test_FR_H10_AC_2_javascript_and_html_near_misses_stay_quiet(self) -> None:
        for source in JS_QUIET:
            with self.subTest(js=source):
                self.assertEqual(check_javascript(source), [])
        for source in HTML_QUIET:
            with self.subTest(html=source):
                self.assertEqual(check_html(source), [])

    def test_FR_H10_AC_2_dockerfile_and_actions_near_misses_stay_quiet(self) -> None:
        for source in DOCKER_QUIET:
            with self.subTest(dockerfile=source):
                self.assertEqual(check_dockerfile(source), [])
        for source in ACTIONS_QUIET:
            with self.subTest(workflow=source):
                self.assertEqual(check_actions(source), [])

    def test_FR_H10_AC_2_secret_near_misses_stay_quiet(self) -> None:
        for line in SECRET_QUIET:
            with self.subTest(secret=line):
                self.assertEqual(check_secrets("app/config.py", line + "\n"), ([], []))
        for name, head in ((".env.example", ""), ("id_ed25519.pub", ""), ("cert.pem", "BEGIN CERTIFICATE"),
                           (".npmrc", "registry=https://registry.npmjs.org/"), ("app.json", '{"a": 1}')):
            with self.subTest(secret_file=name):
                self.assertIsNone(secret_file(name, head))

    def test_FR_H10_AC_2_the_red_teams_own_source_full_of_sink_names_and_secret_patterns_scans_clean(self) -> None:
        report = scan(REPO / "kernel" / "redteam")
        self.assertEqual([f"{f.location} {f.rule}" for f in report.findings], [])
        self.assertEqual(report.canaries, [], "a text that only mentions the marker is not a marker")
        self.assertEqual(report.verdict, "passed")


class OwnCapabilityTest(unittest.TestCase):
    def test_FR_H10_AC_9_the_red_team_depends_on_the_standard_library_and_the_kernel_only(self) -> None:
        modules = sorted((REPO / "kernel" / "redteam").glob("*.py"))
        self.assertGreaterEqual(len(modules), 8)
        for path in modules:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
                for name in names:
                    top = name.split(".")[0]
                    with self.subTest(module=path.name, imports=name):
                        self.assertTrue(top == "kernel" or top in sys.stdlib_module_names or top == "__future__")

    def test_FR_H10_AC_9_the_product_the_factory_scaffolds_is_scanned_without_false_alarms(self) -> None:
        from kernel.scaffold import files

        with tempfile.TemporaryDirectory() as tmp:
            for rel, text in files("Equipment loans", "loans-abc123", "demo").items():
                (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / rel).write_text(text, encoding="utf-8", newline="\n")
            dockerfile = (Path(tmp) / "Dockerfile").read_text(encoding="utf-8")
            # The image starts through the pack guard, which starts the server (FR-PT5).
            points = entry_points(dockerfile)
            self.assertTrue(is_entry_point("app/server.py", points) or is_entry_point("factory/pack_guard.py", points))
            report = scan(Path(tmp))
        # The template binds all interfaces only in its container entry point and reduces static file
        # names with basename: neither is reported. A Dockerfile with no USER runs as root, and is.
        expected = [] if re.search(r"(?m)^USER\s+(?!root\b|0\b)", dockerfile) else [("RT-DOCKER-ROOT", "Dockerfile")]
        self.assertEqual([(f.rule, f.path) for f in report.findings], expected)


if __name__ == "__main__":
    unittest.main()
