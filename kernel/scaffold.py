"""The paved-road product template: what the compiler puts in a new product's repository.

The stack is one IT agrees to in advance: a Python standard-library HTTP service that serves a
JSON API and, when a requirement needs it, plain HTML. It keeps its data in JSON files under
`DATA_DIR`. A health endpoint and request recording (for shadow tests) come built in, and the
Dockerfile packages it. Cells add behaviour by registering routes; the template is not theirs
to change.
"""

from __future__ import annotations

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
HTML. Tests call handle() directly, with no socket.
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
_LOCK = threading.Lock()


class Request:
    def __init__(self, method, path, params, query, body, headers):
        self.method, self.path, self.params = method, path, params
        self.query, self.body, self.headers = query, body, headers


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


def handle(method, path, body=None, headers=None):
    """Route one request. Returns (status, payload, content_type)."""
    method = method.upper()
    parsed = urlparse(path)
    query = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
    allowed = False
    for m, regex, fn in ROUTES:
        match = regex.match(parsed.path)
        if not match:
            continue
        allowed = True
        if m != method:
            continue
        req = Request(method, parsed.path, match.groupdict(), query, body, headers or {})
        try:
            result = fn(req)
        except Exception as exc:  # a handler bug is a 500, never a crash
            return 500, {"error": type(exc).__name__, "detail": str(exc)}, "application/json"
        if len(result) == 3:  # (status, payload, content_type), e.g. a stylesheet
            return result
        status, payload = result
        if isinstance(payload, str):
            return status, payload, "text/html; charset=utf-8"
        return status, payload, "application/json"
    if allowed:
        return 405, {"error": "method not allowed"}, "application/json"
    return 404, {"error": "not found", "path": parsed.path}, "application/json"


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


def _record(method, path, body, status):
    """Record traffic for shadow tests when TRAFFIC_LOG is set."""
    log = os.environ.get("TRAFFIC_LOG")
    if not log or path == "/health":
        return
    line = json.dumps({"at": time.time(), "method": method, "path": path, "body": body, "status": status})
    with _LOCK, open(log, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")


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
        status, payload, ctype = handle(self.command, self.path, body, dict(self.headers))
        data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        _record(self.command, self.path, body, status)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

    def log_message(self, fmt, *args):
        return


def main():
    import app.routes  # noqa: F401  (registers the product's routes)

    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    # `python -m app.server` runs this file as __main__, a second copy of the module; the routes
    # register on `app.server`. Hand over to that copy so they are the ones served.
    from app.server import main as _main

    _main()
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

TESTS_INIT_PY = '''import os
import tempfile

# Every test run gets its own data folder, so tests never share state.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="product-test-data-"))
'''

DOCKERFILE = '''FROM python:3.12-slim
WORKDIR /srv
COPY app ./app
COPY factory/look.json ./factory/look.json
ENV PORT=8080 DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8080'), timeout=3)"
CMD ["python3", "-c", "from app.server import main; main()"]
'''

VERIFY_SH = '''#!/bin/sh
# The product's check, run by the factory's gate (not by the builder's harness).
exec python3 -m unittest discover -s tests
'''

GITIGNORE = """__pycache__/
data/
.gnomon-audit/
.gnomon-sessions/
.gnomon-out/
.gnomon-jobs/
.gnomon-loops/
.gnomon-shadow/
.gnomon-skills/
.gnomon-trials/
.gnomon-inbox/
.gnomon-proposals/
.factory-tasks/
.verify/
"""


def readme(title: str, pid: str, maturity: str) -> str:
    return f"""# {title}

Built by Rihma (project `{pid}`, maturity **{maturity}**).

- `contract.json`: the requirements and acceptance criteria this product is built to.
- `app/`: the service. `python3 -m app.server` serves on `$PORT` (8080).
- `tests/`: one test per acceptance criterion, named by its id.
- `factory/verify.sh`: the check the factory's gate runs.

Change this product through the factory (a change card), not by hand. The factory's ledger
links every release to the requirement, the criterion and the test it rests on.
"""


def files(title: str, pid: str, maturity: str, look: str = "neutral") -> dict[str, str]:
    """Every file of the template, by path."""
    import json as _json

    from kernel.design_road import DESIGN_MD, LOOKS, PRODUCT_CSS

    return {
        "app/__init__.py": "",
        "app/server.py": SERVER_PY,
        "app/routes.py": ROUTES_PY,
        "app/static/product.css": PRODUCT_CSS,
        "tests/__init__.py": TESTS_INIT_PY,
        "tests/test_scaffold.py": TEST_HEALTH_PY,
        "Dockerfile": DOCKERFILE,
        "factory/verify.sh": VERIFY_SH,
        "factory/DESIGN.md": DESIGN_MD,
        "factory/look.json": _json.dumps({"look": look if look in LOOKS else "neutral"}) + "\n",
        ".gitignore": GITIGNORE,
        "README.md": readme(title, pid, maturity),
    }
