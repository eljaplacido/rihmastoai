"""The paved road's sign-in, for a product asked to be a web app people sign in to (the `login_web_app`
output of kernel/outputs.py).

`with_sign_in(files)` adds to the template of kernel/scaffold.py:
- `app/sign_in.py` (SIGN_IN_PY): local accounts with salted PBKDF2-SHA256 hashes, an HttpOnly,
  SameSite=Lax session cookie (Secure over TLS), a CSRF token on every form and state-changing request,
  a lockout after repeated failures, the first admin from the environment at first start, and the
  organisation's own sign-in (OIDC) through an identity-aware proxy, as docs/guides/access.md sets one
  up for the cockpit;
- `tests/test_road_sign_in.py` (kernel/scaffold_auth_tests.py): the sign-in's own checks, which run with
  the product's whole suite at every gate;
- `factory/SIGN-IN.md`: how the people who run the product set it up;
- a Dockerfile that runs the service as an unprivileged user, owning /data.

The road owns `app/sign_in.py` and its tests: no builder cell may change them (kernel/lanes.py
PROTECTED). The service loads the sign-in itself when the file is there (`_load_sign_in` in
app/server.py), so a product with sign-in never serves without it.
"""

from __future__ import annotations

from kernel.scaffold_auth_docs import README_SECTION, SIGN_IN_MD
from kernel.scaffold_auth_tests import TEST_SIGN_IN_PY

SIGN_IN_FILE = "app/sign_in.py"
ROAD_SIGN_IN_TESTS = "tests/test_road_sign_in.py"
SIGN_IN_GUIDE = "factory/SIGN-IN.md"
# What a product's app/server.py carries when it can load a sign-in: templates before it cannot.
SIGN_IN_HOOK = "def _load_sign_in():"

SIGN_IN_PY = r'''"""Sign-in for this product, from the paved road: a web app people sign in to. The road owns this
file and tests/test_road_sign_in.py: no builder cell may change either, and the factory's gate refuses a
change that touches them. factory/SIGN-IN.md tells the people who run the product how to set it up.

- Every request passes the guard below before its route's handler. GET /health, /static/ and the sign-in
  page are open; any other request needs a signed-in person. A page a browser asks for is sent to
  /sign-in; anything else answers 401.
- Local accounts live in DATA_DIR/accounts.json, each password as a salted PBKDF2-SHA256 hash. A password
  is never stored, logged or written to the traffic log.
- A session is a random token in an HttpOnly, SameSite=Lax cookie, Secure when the request came over TLS
  (the road's ingress says X-Forwarded-Proto: https, or PUBLIC_URL starts with https://). Sessions live in
  this process's memory and end at sign-out or after SESSION_HOURS: a restart signs everyone out.
- Every form and every state-changing request (POST, PUT, PATCH, DELETE) carries a CSRF token: the
  session's own, in the form field `csrf` or the X-CSRF-Token header. The sign-in form carries one bound
  to a cookie of its own, before there is a session.
- After MAX_FAILURES failed sign-ins in a row an account waits LOCK_MINUTES. The answer never says
  whether the name exists, is locked, or the password was wrong.
- At first start, with no account yet, FIRST_ADMIN_USER and FIRST_ADMIN_PASSWORD (at least MIN_PASSWORD
  characters) create the first admin, who sets a new password at first sign-in. Both leave the
  environment once read.
- The organisation's own sign-in (OIDC) works through an identity-aware proxy in front of the product:
  SIGN_IN_MODE=proxy, and SIGN_IN_PROXY_SECRET shared with the proxy. A request is signed in as the user
  the proxy names in SIGN_IN_PROXY_USER_HEADER (default X-Forwarded-Email) only when it carries the
  proxy's secret in SIGN_IN_PROXY_SECRET_HEADER (default X-Proxy-Secret), each header exactly once.

In a handler, req.user is {"name": ..., "role": "admin" or "user", "csrf": ...}: require_role(req, "admin")
refuses anyone else, and csrf_field(req) is the hidden field every form needs. In a test,
session_headers("name") signs a request in; handle() runs a handler without the guard, respond() as the
network sees it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, quote

from app.server import UNRECORDED, esc, guard, load_data, page, route, save_data

ITERATIONS = 600_000            # PBKDF2-SHA256 rounds for a new hash (OWASP's figure, 2023)
MIN_PASSWORD = 12
MAX_FAILURES = 5
LOCK_MINUTES = 15
SESSION_HOURS = 8
COOKIE, FORM_COOKIE = "session", "sign_in_form"
OPEN = {("GET", "/health"), ("GET", "/sign-in"), ("POST", "/sign-in")}
CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
PASSWORD_PATHS = {"/account", "/account/password", "/sign-out"}
HEADERS = [("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin"),
           ("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
PAGE_CSP = ("Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
FAILED = ("Sign-in failed: check the name and the password. After %d failed tries in a row an account waits "
          "%d minutes." % (MAX_FAILURES, LOCK_MINUTES))
_SAFE_NEXT = re.compile(r"/(?!/)[A-Za-z0-9/_.~-]{0,300}")
_SESSIONS = {}
_LOCK = threading.Lock()
_KEY = secrets.token_bytes(32)  # signs the proxy mode's CSRF tokens; a new one at every start
_DUMMY = []
UNRECORDED.update({"/sign-in", "/account/password", "/accounts"})


def now():
    return time.time()


# -- passwords and accounts

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def check_password(password, stored):
    try:
        scheme, rounds, salt, digest = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(rounds))
        return scheme == "pbkdf2_sha256" and hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError, AttributeError):
        return False


def accounts():
    return load_data("accounts", {}) or {}


def add_account(name, password, role="user", *, must_change=False):
    name = str(name or "").strip()
    if not name or len(name) > 120 or role not in ("admin", "user"):
        raise ValueError("an account needs a name of at most 120 characters, and the role admin or user")
    if len(password or "") < MIN_PASSWORD:
        raise ValueError("a password has at least %d characters" % MIN_PASSWORD)
    hashed = hash_password(password)
    with _LOCK:
        known = accounts()
        if name in known:
            raise ValueError("that account exists already")
        known[name] = {"role": role, "hash": hashed, "failures": 0, "locked_until": 0, "must_change": must_change}
        save_data("accounts", known)
    return name


def first_admin_from_env():
    """The first admin, from FIRST_ADMIN_USER and FIRST_ADMIN_PASSWORD, while there is no account. Both
    leave the environment either way, so no process this one starts inherits the password."""
    name = os.environ.pop("FIRST_ADMIN_USER", "")
    password = os.environ.pop("FIRST_ADMIN_PASSWORD", "")
    if not name or accounts():
        return None
    return add_account(name, password, "admin", must_change=True)


def _dummy_hash():
    if not _DUMMY:
        _DUMMY.append(hash_password(secrets.token_urlsafe(16)))
    return _DUMMY[0]


def attempt(name, password):
    """The account a name and password sign in to, or None. A wrong password, an unknown name and a
    locked account cost the same work and get the same answer."""
    account = accounts().get(name)
    if account is None or account.get("locked_until", 0) > now():
        check_password(password, account["hash"] if account else _dummy_hash())
        return None
    ok = check_password(password, account["hash"])
    with _LOCK:
        known = accounts()
        acc = known.get(name)
        if acc is None:
            return None
        acc["failures"] = 0 if ok else acc.get("failures", 0) + 1
        acc["locked_until"] = 0
        if acc["failures"] >= MAX_FAILURES:
            acc["failures"], acc["locked_until"] = 0, now() + LOCK_MINUTES * 60
        save_data("accounts", known)
    return {"name": name, "role": acc["role"], "must_change": bool(acc.get("must_change"))} if ok else None


# -- sessions, headers and cookies

def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_session(user):
    token = secrets.token_urlsafe(32)
    with _LOCK:
        _SESSIONS[_digest(token)] = dict(user, csrf=secrets.token_urlsafe(32), expires=now() + SESSION_HOURS * 3600)
    return token


def session_headers(name, role="user"):
    """Headers that sign a test's request in as ``name``: the session cookie and its CSRF token."""
    token = _new_session({"name": name, "role": role, "must_change": False})
    return {"Cookie": "%s=%s" % (COOKIE, token), "X-CSRF-Token": _SESSIONS[_digest(token)]["csrf"]}


def _values(req, name):
    low = name.lower()
    return [str(v) for k, v in (req.headers or {}).items() if k.lower() == low]


def _one(req, name):
    """A header's value when it was sent exactly once, else None (app/server.py joins repeats with ", ")."""
    found = _values(req, name)
    return found[0].strip() if len(found) == 1 and "," not in found[0] else None


def _cookies(req, name):
    found = []
    for raw in _values(req, "Cookie"):
        for part in raw.replace(",", ";").split(";"):
            key, sep, value = part.strip().partition("=")
            if sep and key == name:
                found.append(value)
    return found


def _tls(req):
    return _one(req, "X-Forwarded-Proto") == "https" or os.environ.get("PUBLIC_URL", "").startswith("https://")


def _cookie(req, name, value, max_age, path="/", same_site="Lax"):
    parts = ["%s=%s" % (name, value), "Path=" + path, "HttpOnly", "SameSite=" + same_site, "Max-Age=%d" % max_age]
    return "Set-Cookie", "; ".join(parts + (["Secure"] if _tls(req) else []))


def _fields(req):
    if isinstance(req.body, dict):
        return {str(k): str(v) for k, v in req.body.items() if isinstance(v, (str, int))}
    if isinstance(req.body, str):
        return {k: v[0] for k, v in parse_qs(req.body, keep_blank_values=True).items()}
    return {}


def _same(sent, expected):
    return bool(sent) and bool(expected) and hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8"))


def _proxy_mode():
    return os.environ.get("SIGN_IN_MODE", "local") == "proxy"


def _session_user(req):
    tokens = _cookies(req, COOKIE)
    if len(tokens) != 1:
        return None
    with _LOCK:
        user = _SESSIONS.get(_digest(tokens[0]))
        if user is not None and user["expires"] <= now():
            del _SESSIONS[_digest(tokens[0])]
            user = None
    return {k: v for k, v in user.items() if k != "expires"} if user else None


def _proxy_user(req):
    secret = os.environ.get("SIGN_IN_PROXY_SECRET", "")
    sent = _one(req, os.environ.get("SIGN_IN_PROXY_SECRET_HEADER", "X-Proxy-Secret"))
    name = _one(req, os.environ.get("SIGN_IN_PROXY_USER_HEADER", "X-Forwarded-Email"))
    if not _same(sent, secret) or not name or len(name) > 200:
        return None
    admins = {a.strip() for a in os.environ.get("SIGN_IN_PROXY_ADMINS", "").split(",") if a.strip()}
    csrf = hmac.new(_KEY, name.encode("utf-8"), hashlib.sha256).hexdigest()
    return {"name": name, "role": "admin" if name in admins else "user", "csrf": csrf, "must_change": False}


# -- the guard

def _wants_page(req):
    return req.method == "GET" and any("text/html" in v for v in _values(req, "Accept"))


def _redirect(location, headers=()):
    return 303, "", "text/html; charset=utf-8", [("Location", location), *headers]


def _next(value):
    return value if isinstance(value, str) and _SAFE_NEXT.fullmatch(value) else "/"


@guard
def sign_in_guard(req):
    req.out_headers.extend(HEADERS)
    if (req.method, req.path) in OPEN or req.path.startswith("/static/"):
        return None
    user = _proxy_user(req) if _proxy_mode() else _session_user(req)
    if user is None:
        if _wants_page(req):
            return _redirect("/sign-in?next=" + quote(_next(req.path), safe="/"))
        return 401, {"error": "sign in first", "sign_in": "/sign-in"}
    req.user = user
    if req.method in CHANGING and not _same(_one(req, "X-CSRF-Token") or _fields(req).get("csrf"), user["csrf"]):
        return 403, {"error": "the CSRF token is missing or wrong: reload the page and try again"}
    if user.get("must_change") and req.path not in PASSWORD_PATHS:
        return _redirect("/account") if _wants_page(req) else (403, {"error": "set a new password first, at /account"})
    return None


def require_role(req, role):
    """None when the signed-in person has ``role``, else the answer that refuses them."""
    return None if (req.user or {}).get("role") == role else (403, {"error": "only an %s may do this" % role})


def csrf_field(req):
    return '<input type="hidden" name="csrf" value="%s">' % esc((req.user or {}).get("csrf", ""))


# -- the pages

def _form(action, fields, button, token, extra=""):
    rows = "".join('<div class="field"><label for="%s">%s</label><input id="%s" name="%s" type="%s" autocomplete="%s"'
                   ' required></div>' % (n, esc(label), n, n, kind, auto) for n, label, kind, auto in fields)
    return ('<form class="form" method="post" action="%s"><input type="hidden" name="csrf" value="%s">%s%s'
            '<button class="button" type="submit">%s</button></form>' % (action, esc(token), extra, rows, esc(button)))


def _sign_in_html(token, target, message):
    note = '<p class="error" role="alert">%s</p>' % esc(message) if message else ""
    if not accounts():
        note += ('<p class="hint">No account yet: whoever runs this product sets FIRST_ADMIN_USER and '
                 'FIRST_ADMIN_PASSWORD at its first start (factory/SIGN-IN.md).</p>')
    fields = [("username", "Name", "text", "username"), ("password", "Password", "password", "current-password")]
    extra = '<input type="hidden" name="next" value="%s">' % esc(target)
    return page("Sign in", '<section class="card"><h1>Sign in</h1>%s%s</section>'
                % (note, _form("/sign-in", fields, "Sign in", token, extra)))


def _form_answer(req, status, message, target="/"):
    token = secrets.token_urlsafe(32)
    cookie = _cookie(req, FORM_COOKIE, token, 3600, path="/sign-in", same_site="Strict")
    if isinstance(req.body, dict) or not (isinstance(req.body, str) or _wants_page(req)):
        return status, ({"csrf": token} if status == 200 else {"error": message, "csrf": token}), "application/json", [
            cookie]
    return status, _sign_in_html(token, target, message), "text/html; charset=utf-8", [cookie, PAGE_CSP]


@route("GET", "/sign-in")
def sign_in_page(req):
    if _proxy_mode():
        return _redirect("/")
    return _form_answer(req, 200, "", _next(req.query.get("next")))


@route("POST", "/sign-in")
def sign_in(req):
    if _proxy_mode():
        return 404, {"error": "sign-in is the organisation's, at its proxy"}
    fields, form = _fields(req), _cookies(req, FORM_COOKIE)
    target = _next(fields.get("next"))
    if len(form) != 1 or not _same(fields.get("csrf") or _one(req, "X-CSRF-Token"), form[0]):
        return _form_answer(req, 403, "The sign-in form expired: load it again.", target)
    user = attempt(fields.get("username", "").strip(), fields.get("password", ""))
    if user is None:
        return _form_answer(req, 401, FAILED, target)
    token = _new_session(user)
    headers = [_cookie(req, COOKIE, token, SESSION_HOURS * 3600),
               _cookie(req, FORM_COOKIE, "", 0, path="/sign-in", same_site="Strict")]
    if isinstance(req.body, dict):
        csrf = _SESSIONS[_digest(token)]["csrf"]
        return 200, {"name": user["name"], "role": user["role"], "csrf": csrf}, "application/json", headers
    return _redirect("/account" if user["must_change"] else target, headers)


@route("POST", "/sign-out")
def sign_out(req):
    if _proxy_mode():
        return _redirect(os.environ.get("SIGN_IN_PROXY_SIGN_OUT", "/oauth2/sign_out"))
    with _LOCK:
        for token in _cookies(req, COOKIE):
            _SESSIONS.pop(_digest(token), None)
    return _redirect("/sign-in", [_cookie(req, COOKIE, "", 0)])


@route("GET", "/account")
def account_page(req):
    user = req.user or {}
    if not _wants_page(req):
        return 200, {"name": user.get("name"), "role": user.get("role"), "must_change": user.get("must_change")}
    body = '<section class="card"><h1>Your account</h1><p>Signed in as <b>%s</b> (%s).</p>' % (
        esc(user.get("name")), esc(user.get("role")))
    if user.get("must_change"):
        body += '<p class="error" role="alert">Set a new password before you go on.</p>'
    if not _proxy_mode():
        body += _form("/account/password", [("current", "Current password", "password", "current-password"),
                                            ("new", "New password", "password", "new-password")],
                      "Set the new password", user.get("csrf", ""))
    body += _form("/sign-out", [], "Sign out", user.get("csrf", "")) + "</section>"
    if user.get("role") == "admin" and not _proxy_mode():
        rows = "".join("<li>%s (%s)</li>" % (esc(n), esc(a["role"])) for n, a in sorted(accounts().items()))
        body += ('<section class="card"><h2>Accounts</h2><ul>%s</ul>' % rows
                 + _form("/accounts", [("username", "Name", "text", "off"), ("password", "Password", "password",
                                                                             "new-password")],
                         "Add an account", user.get("csrf", "")) + "</section>")
    return 200, page("Your account", body), "text/html; charset=utf-8", [PAGE_CSP]


@route("POST", "/account/password")
def change_password(req):
    user, fields = req.user or {}, _fields(req)
    if attempt(user.get("name"), fields.get("current", "")) is None:
        return 403, {"error": FAILED}
    if len(fields.get("new", "")) < MIN_PASSWORD or fields.get("new") == fields.get("current"):
        return 400, {"error": "a new password has at least %d characters and differs from the old one" % MIN_PASSWORD}
    hashed = hash_password(fields["new"])
    with _LOCK:
        known = accounts()
        known[user["name"]].update(hash=hashed, must_change=False)
        save_data("accounts", known)
        for session in _SESSIONS.values():
            if session["name"] == user["name"]:
                session["must_change"] = False
    return _redirect("/account") if isinstance(req.body, str) else (200, {"changed": True})


@route("POST", "/accounts")
def create_account(req):
    refused = require_role(req, "admin")
    if refused:
        return refused
    fields = _fields(req)
    try:
        add_account(fields.get("username"), fields.get("password"), fields.get("role") or "user")
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return _redirect("/account") if isinstance(req.body, str) else (201, {"name": fields.get("username").strip()})


first_admin_from_env()
'''

def has_sign_in_hook(server_text: str) -> bool:
    """Whether a product's app/server.py can load a sign-in (templates before the hook cannot)."""
    return SIGN_IN_HOOK in server_text


def unprivileged(dockerfile: str) -> str:
    """The Dockerfile with the service running as an unprivileged user that owns /data."""
    out = dockerfile.replace("ENV PORT=", "RUN mkdir -p /data && chown 10001:10001 /data\nENV PORT=", 1)
    out = out.replace("EXPOSE ", "USER 10001:10001\nEXPOSE ", 1)
    if "USER 10001:10001" not in out or "chown 10001:10001 /data" not in out:
        raise ValueError("the template's Dockerfile has no ENV PORT= or EXPOSE line to place the user around")
    return out


def sign_in_files() -> dict[str, str]:
    """The files the road adds to a product for sign-in, by path."""
    return {SIGN_IN_FILE: SIGN_IN_PY, ROAD_SIGN_IN_TESTS: TEST_SIGN_IN_PY, SIGN_IN_GUIDE: SIGN_IN_MD}


def with_sign_in(files: dict[str, str]) -> dict[str, str]:
    """The template's files with the road's sign-in added: the sign-in, its tests, its guide, the README's
    section and an unprivileged Dockerfile."""
    out = dict(files)
    out.update(sign_in_files())
    out["Dockerfile"] = unprivileged(out["Dockerfile"])
    out["README.md"] = out["README.md"].rstrip("\n") + "\n" + README_SECTION
    return out
