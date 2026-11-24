"""The paved-road product template: what the compiler puts in a new product's repository.

The stack is one IT agrees to in advance: a Python standard-library HTTP service that serves a
JSON API and, when a requirement needs it, plain HTML. It keeps its data in JSON files under
`DATA_DIR`. A health endpoint, request recording (for shadow tests) and `factory/pack_guard.py`
(the pack check at a site, FR-PT5, from kernel/scaffold_guard.py) come built in, and the
Dockerfile packages it, starting through the guard. Cells add behaviour by registering routes; the
template is not theirs to change. The road-contract tests (`ROAD_CONTRACT_TESTS`) check the road's
platform facts in every product, and no cell may change them.
"""

from __future__ import annotations

from kernel.scaffold_guard import PACK_GUARD_PY

SERVER_PY = r'''"""The product's HTTP service. Built by Rihma on the paved road: standard library only.

Add behaviour by registering routes in app/routes.py (or modules it imports):

    from app.server import route, load_data, save_data

    @route("POST", "/items")
    def create_item(req):
        items = load_data("items", [])
        items.append(req.body)
        save_data("items", items)
        return 201, req.body

A handler gets a Request and returns (status, body). A dict or list body is sent as JSON, a str as
HTML. It may also return (status, body, content_type), or (status, body, content_type, headers) with
a list of (name, value) response headers. Tests call handle() directly, with no socket: it runs the
handler without the guards. respond() is the service as the network sees it, guards included.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROUTES = []
GUARDS = []  # each runs before every route's handler (app/sign_in.py adds one when the product has it)
HEADER_HOOKS = []  # functions (method, path, request headers, status) -> extra response headers
_LOCK = threading.Lock()


class Request:
    def __init__(self, method, path, params, query, body, headers, raw=b""):
        self.method, self.path, self.params = method, path, params
        self.query, self.body, self.headers, self.raw = query, body, headers, raw
        self.handler, self.user, self.out_headers = None, None, []


def guard(fn):
    """Run ``fn(req)`` before every route's handler: it returns None to let the request through, or a
    response that answers it instead. It may add response headers to ``req.out_headers``."""
    GUARDS.append(fn)
    return fn


def route(method, pattern):
    """Register a handler for METHOD and a path pattern such as "/items/{id}"."""
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def register(fn):
        ROUTES.append((method.upper(), regex, fn))
        return fn

    return register


def data_dir():
    return os.environ.get("DATA_DIR", "data")


def load_data(name, default):
    try:
        with open(os.path.join(data_dir(), name + ".json"), encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def save_data(name, value):
    os.makedirs(data_dir(), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=data_dir(), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(data_dir(), name + ".json"))


def _shaped(result, extra):
    """A handler's result as (status, payload, content_type, headers)."""
    status, payload = result[0], result[1]
    if len(result) > 2:  # (status, payload, content_type[, headers]), e.g. a stylesheet
        ctype = result[2]
    else:
        ctype = "text/html; charset=utf-8" if isinstance(payload, str) else "application/json"
    return status, payload, ctype, list(result[3] if len(result) > 3 else []) + list(extra)


def _dispatch(method, path, body, headers, guards, raw=b""):
    """Route one request: the guards first, in order, then its route's handler. A guard sees every
    request, one that matches no route included, so it answers before a 404 or 405 would. ``raw`` is
    the body's bytes, for a signature."""
    method = method.upper()
    parsed = urlparse(path)
    query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
    found, allowed = None, False
    for m, regex, fn in ROUTES:
        match = regex.match(parsed.path)
        if match:
            allowed = True
            if m == method:
                found = (fn, match.groupdict())
                break
    req = Request(method, parsed.path, found[1] if found else {}, query, body, headers or {}, raw)
    req.handler = found[0] if found else None
    try:
        result = next((r for r in (check(req) for check in guards) if r is not None), None)
        if result is None and found:
            result = found[0](req)
    except Exception as exc:  # a handler bug is a 500, never a crash
        return 500, {"error": type(exc).__name__, "detail": str(exc)}, "application/json", list(req.out_headers)
    if result is None:
        result = (405, {"error": "method not allowed"}) if allowed else (404, {"error": "not found",
                                                                               "path": parsed.path})
    return _shaped(result, req.out_headers)


def respond(method, path, body=None, headers=None, raw=b""):
    """The service as the network sees it: every guard (app/sign_in.py adds one when the product has
    sign-in), then the route's handler. Returns (status, payload, content_type, headers), headers a
    list of (name, value). The HTTP server answers every request through it."""
    return _dispatch(method, path, body, headers, GUARDS, raw)


def handle(method, path, body=None, headers=None, raw=b""):
    """A route's handler, without the guards: a handler's own logic, as the product's tests check it.
    Returns (status, payload, content_type). respond() is what the network sees."""
    return _dispatch(method, path, body, headers, (), raw)[:3]


_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC_TYPES = {".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".js": "text/javascript; charset=utf-8"}


def _look():
    """The look the product was given at intake (factory/look.json), neutral by default."""
    try:
        with open(os.path.join(_HERE, "..", "factory", "look.json"), encoding="utf-8") as fh:
            return json.load(fh).get("look", "neutral")
    except (OSError, ValueError):
        return "neutral"


def esc(text):
    """Escape text for HTML. Use it for every value that came from a person or the data."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def page(title, body, *, nav=None):
    """A complete HTML page in the product's design system (factory/DESIGN.md).

    ``body`` is HTML you built with esc() for every value; ``nav`` is a list of (label, href)."""
    links = "".join(f'<a href="{esc(h)}">{esc(l)}</a>' for l, h in (nav or []))
    return (f'<!doctype html><html lang="en" data-look="{esc(_look())}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{esc(title)}</title><link rel="stylesheet" href="/static/product.css"></head>'
            f'<body><header class="bar"><span class="name">{esc(title)}</span>'
            f'<nav aria-label="Main">{links}</nav></header><main class="page">{body}</main></body></html>')


@route("GET", "/static/{name}")
def static_file(req):
    name = os.path.basename(req.params["name"])
    ext = os.path.splitext(name)[1]
    path = os.path.join(_HERE, "static", name)
    if ext not in _STATIC_TYPES or not os.path.isfile(path):
        return 404, {"error": "not found"}
    with open(path, encoding="utf-8") as fh:
        return 200, fh.read(), _STATIC_TYPES[ext]


@route("GET", "/health")
def health(req):
    return 200, {"status": "ok", "version": os.environ.get("APP_VERSION", "dev")}


# Paths whose requests never reach the traffic log, because they carry passwords (app/sign_in.py).
UNRECORDED = set()


def _record(method, path, body, status):
    """Record traffic for shadow tests when TRAFFIC_LOG is set."""
    log = os.environ.get("TRAFFIC_LOG")
    if not log or path == "/health" or urlparse(path).path in UNRECORDED:
        return
    line = json.dumps({"at": time.time(), "method": method, "path": path, "body": body, "status": status})
    with _LOCK, open(log, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")


def _headers(message):
    """The request's headers by name. A header sent more than once keeps every value, joined with
    ", " as HTTP reads a list, so a check on it sees them all, never only the first."""
    out = {}
    for name, value in message.items():
        out[name] = out[name] + ", " + value if name in out else value
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "gnomonfactory-product"

    def _serve(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = None
        if raw:
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = raw.decode("utf-8", "replace")
        status, payload, ctype, extra = respond(self.command, self.path, body, _headers(self.headers), raw)
        data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for name, value in extra:
            self.send_header(name, value)
        for hook in HEADER_HOOKS:
            for key, value in hook(self.command, self.path, dict(self.headers), status).items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)
        _record(self.command, self.path, body, status)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _serve

    def log_message(self, fmt, *args):
        return


def main():
    import app.routes  # noqa: F401  (registers the product's routes)

    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()


def _load_sign_in():
    """Load app/sign_in.py when the product has one (the paved road adds it to a login-ready web
    app). An error inside it stops the service: a product with sign-in never serves without it."""
    try:
        import app.sign_in  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name != "app.sign_in":
            raise


if __name__ == "__main__":
    # `python -m app.server` runs this file as __main__, a second copy of the module; the routes
    # register on `app.server`. Hand over to that copy so they are the ones served.
    from app.server import main as _main

    _main()
else:
    _load_sign_in()
'''

ROUTES_PY = '''"""The product's routes. Cells add handlers here, or in modules imported from here."""

from app.server import load_data, route, save_data  # noqa: F401
'''

TEST_HEALTH_PY = '''import unittest

import app.routes  # noqa: F401
from app.server import handle


class ScaffoldTest(unittest.TestCase):
    def test_SCAFFOLD_health_answers_ok(self):
        status, body, _ = handle("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_SCAFFOLD_unknown_path_is_404(self):
        status, _, _ = handle("GET", "/no-such-path")
        self.assertEqual(status, 404)

    def test_SCAFFOLD_the_design_system_is_served(self):
        status, body, ctype = handle("GET", "/static/product.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", ctype)
        self.assertIn("--accent", body)
        self.assertEqual(handle("GET", "/static/../server.py")[0], 404)

    def test_SCAFFOLD_page_links_the_design_system_and_escapes_values(self):
        from app.server import esc, page
        html = page("<T>", "<p>" + esc("<b>x</b>") + "</p>", nav=[("Home", "/")])
        self.assertIn('href="/static/product.css"', html)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)
        self.assertNotIn("<T>", html)
        self.assertIn('data-look="', html)


if __name__ == "__main__":
    unittest.main()
'''

# The road-contract tests (FR-DF1-AC-2): the paved road's platform facts, checked in every product
# by the product's own suite. The road owns the file. No builder cell may edit or remove it: the gate
# refuses a change that touches it (kernel/lanes.py PROTECTED), as it refuses one to the contract.
ROAD_CONTRACT_TESTS = "tests/test_road_contract.py"
TEST_ROAD_CONTRACT_PY = r'''"""The paved road's contract with this product. The road owns this file: no builder cell
may edit or remove it, and the factory's gate refuses a change that touches it.

- GET /health answers 200 with {"status": "ok", "version": <APP_VERSION>}: delivery checks the
  version of every release.
- The service binds the address in HOST, default 0.0.0.0 (every interface inside its container),
  and the port in PORT. Who can reach it is the road's job, not the product's.
"""

import json
import os
import re
import subprocess
import sys
import unittest

import app.routes  # noqa: F401
from app.server import handle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Starts the service as the roads do, with the server class replaced: it says which address it
# would bind, and binds nothing. Once with no HOST or PORT, once with the road's own.
PROBE = (
    "import json, os\n"
    "import app.server as server\n"
    "class Bound(Exception):\n"
    "    pass\n"
    "def bound(address, handler):\n"
    "    raise Bound(address)\n"
    "server.ThreadingHTTPServer = bound\n"
    "seen = []\n"
    "for host, port in ((None, None), ('192.0.2.10', '18081')):\n"
    "    if host:\n"
    "        os.environ['HOST'], os.environ['PORT'] = host, port\n"
    "    try:\n"
    "        server.main()\n"
    "    except Bound as exc:\n"
    "        seen.append([exc.args[0][0], int(exc.args[0][1])])\n"
    "print(json.dumps(seen))\n"
)
_SEEN = []


def bound_addresses():
    """The addresses the service binds with no HOST or PORT set, and with HOST and PORT given."""
    if not _SEEN:
        env = {k: v for k, v in os.environ.items() if k not in ("HOST", "PORT")}
        proc = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True,
                              timeout=60)
        lines = proc.stdout.strip().splitlines()
        if proc.returncode != 0 or not lines:
            raise AssertionError("the service did not start as the road starts it: " + proc.stderr[-800:])
        _SEEN.append([tuple(a) for a in json.loads(lines[-1])])
    return _SEEN[0]


class RoadContractTest(unittest.TestCase):
    def test_ROAD_health_answers_ok_with_the_release_version(self):
        saved = os.environ.get("APP_VERSION")
        os.environ["APP_VERSION"] = "road-check-1"
        try:
            status, body, ctype = handle("GET", "/health")
        finally:
            if saved is None:
                os.environ.pop("APP_VERSION", None)
            else:
                os.environ["APP_VERSION"] = saved
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        self.assertEqual((body.get("status"), body.get("version")), ("ok", "road-check-1"))

    def test_ROAD_the_service_binds_every_interface_unless_HOST_says_otherwise(self):
        seen = bound_addresses()
        self.assertEqual(len(seen), 2, "the service did not hand its address to the road's server class")
        self.assertEqual(seen[0][0], "0.0.0.0")

    def test_ROAD_the_service_binds_the_HOST_and_PORT_the_road_gives(self):
        seen = bound_addresses()
        self.assertEqual(seen[-1], ("192.0.2.10", 18081))
        with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as fh:
            dockerfile = fh.read()
        self.assertIsNone(re.search(r"HOST\s*=\s*\S*(127\.0\.0\.1|localhost)", dockerfile))


if __name__ == "__main__":
    unittest.main()
'''

TESTS_INIT_PY = '''import os
import tempfile

# Every test run gets its own data folder, so tests never share state.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="product-test-data-"))
'''

DOCKERFILE = '''FROM python:3.12-slim
WORKDIR /srv
COPY app ./app
COPY factory/look.json ./factory/look.json
COPY factory/pack_guard.py ./factory/pack_guard.py
ENV PORT=8080 DATA_DIR=/data PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8080'), timeout=3)"
CMD ["python3", "factory/pack_guard.py"]
'''

VERIFY_SH = '''#!/bin/sh
# The product's check, run by the factory's gate (not by the builder's harness).
exec python3 -m unittest discover -s tests
'''

GITIGNORE = "".join(f"{d}/\n" for d in ("__pycache__", "data", *(".gnomon-" + g for g in (
    "audit", "sessions", "out", "jobs", "loops", "shadow", "skills", "trials", "inbox", "proposals")),
    ".factory-tasks", ".verify"))


def readme(title: str, pid: str, maturity: str) -> str:
    return f"""# {title}

Built by Rihma (project `{pid}`, maturity **{maturity}**).

- `contract.json`: the requirements and acceptance criteria this product is built to.
- `app/`: the service. `python3 -m app.server` serves on `$PORT` (8080).
- `tests/`: one test per acceptance criterion, named by its id.
- `tests/test_road_contract.py`: the paved road's own checks (GET /health with the release
  version; the bind from `HOST`, default 0.0.0.0). The road owns it: never edit or remove it.
- `factory/verify.sh`: the check the factory's gate runs.
- `factory/pack_guard.py`: the image starts through it. Where a site mounts the capability pack
  beside the image, `/health` answers 503 until the pack, the files and the pack's status check out.

Change this product through the factory (a change card), not by hand. The factory's ledger
links every release to the requirement, the criterion and the test it rests on.
"""


def files(title: str, pid: str, maturity: str, look: str = "neutral", template: str = "web-service", *,
          sign_in: bool = False) -> dict[str, str]:
    """Every file of the template, by path: the web service's, or a small capability's built on it
    (``template="capability"``, kernel/capability_template.py). ``sign_in`` adds the road's sign-in
    (kernel/scaffold_auth.py), for a product asked to be a login-ready web app."""
    import json as _json

    from kernel.design_road import DESIGN_MD, LOOKS, PRODUCT_CSS

    if sign_in:
        from kernel.scaffold_auth import with_sign_in

        return with_sign_in(files(title, pid, maturity, look, template))
    base = {
        "app/__init__.py": "",
        "app/server.py": SERVER_PY,
        "app/routes.py": ROUTES_PY,
        "app/static/product.css": PRODUCT_CSS,
        "tests/__init__.py": TESTS_INIT_PY,
        "tests/test_scaffold.py": TEST_HEALTH_PY,
        ROAD_CONTRACT_TESTS: TEST_ROAD_CONTRACT_PY,
        "Dockerfile": DOCKERFILE,
        "factory/verify.sh": VERIFY_SH,
        "factory/DESIGN.md": DESIGN_MD,
        "factory/look.json": _json.dumps({"look": look if look in LOOKS else "neutral"}) + "\n",
        "factory/pack_guard.py": PACK_GUARD_PY,
        ".gitignore": GITIGNORE,
        "README.md": readme(title, pid, maturity),
    }
    if template == "capability":
        from kernel.capability_template import capability_files

        return capability_files(base, title, pid, maturity)
    return base
