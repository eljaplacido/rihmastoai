"""The Python rules about how a program is set up rather than what it does with data: network calls
without a timeout, weak hashes for credentials, predictable temporary names, debug modes, binding
every interface, and TLS verification turned off.

Precision choices, each written down so a reader can judge them:
- a call that passes `**kwargs` may pass a timeout: it is not reported as missing one;
- a weak hash is reported only where a password, token or secret is near it (its arguments, the
  name it is assigned to, or the function's name); MD5 for a cache key is not a credential;
- binding all interfaces is allowed in a container's entry point (the module a Dockerfile's CMD or
  ENTRYPOINT runs, and what it imports), where the platform's network rules apply; a socket bound
  to port 0 (a free port, found and released) is not a server;
- a debug switch set inside `if <a debug flag>:` is off by default, and not reported.
"""

from __future__ import annotations

import ast
import re

from kernel.redteam.pyast import dotted, is_const, keyword, last_name, passes
from kernel.redteam.pycheck import Ctx

_CLIENT_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "request")
# Where each call takes its timeout: the position, or 99 when it is keyword-only (`timeout=`).
TIMEOUTS = {"urllib.request.urlopen": 2, "http.client.HTTPConnection": 2, "http.client.HTTPSConnection": 2,
            "socket.create_connection": 1, "smtplib.SMTP": 3, "smtplib.SMTP_SSL": 3, "ftplib.FTP": 4,
            "urllib.request.build_opener().open": 2,
            **{f"requests.{m}": 99 for m in _CLIENT_METHODS},
            **{f"requests.{s}().{m}": 99 for s in ("Session", "session") for m in _CLIENT_METHODS},
            **{f"urllib3.{p}().{m}": 99 for p in ("PoolManager", "HTTPConnectionPool", "HTTPSConnectionPool",
                                                  "ProxyManager") for m in ("request", "urlopen")}}
WEAK_HASHES = frozenset({"hashlib.md5", "hashlib.sha1", "Crypto.Hash.MD5.new", "Crypto.Hash.SHA1.new",
                         "Cryptodome.Hash.MD5.new", "Cryptodome.Hash.SHA1.new", "Crypto.Hash.MD5.MD5Hash",
                         "cryptography.hazmat.primitives.hashes.MD5", "cryptography.hazmat.primitives.hashes.SHA1"})
CREDENTIAL = re.compile(r"(?i)passw|passphrase|passcode|pwd|(?<![a-z])pw(?![a-z])|secret|token|api_?key|apikey|"
                        r"credential")
ALL_INTERFACES = ("0.0.0.0", "::")
# Where a server or socket call takes the address it binds.
BIND_AT = {"bind": 0, "HTTPServer": 0, "ThreadingHTTPServer": 0, "TCPServer": 0, "ThreadingTCPServer": 0,
           "UDPServer": 0, "ThreadingUDPServer": 0, "WSGIServer": 0, "make_server": 0, "run_simple": 0, "run": 0,
           "start_server": 1, "create_server": 1}
HOST_KEYWORDS = frozenset({"host", "bind", "listen", "hostname"})
HOST_OPTIONS = frozenset({"--host", "--bind", "--listen", "--address", "--addr"})
HOST_ENV = re.compile(r"(?i)host|bind|listen|addr")
CA_VARIABLES = frozenset({"CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"})
TLS_CLIENT = frozenset({"TCPConnector", "ClientSession", "ws_connect", *_CLIENT_METHODS})


def timeout(ck: Ctx, call: ast.Call, q: str) -> str | None:
    position = TIMEOUTS.get(q)
    if position is None and isinstance(call.func, ast.Attribute) and call.func.attr == "open":
        position = 2 if dotted(call.func.value) in ck.openers else None
    if position is None:
        return None
    if is_const(keyword(call, "timeout"), None):
        return "RT-PY-TIMEOUT"
    return None if passes(call, position, "timeout") else "RT-PY-TIMEOUT"


def _words(node: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def weak_hash(ck: Ctx, call: ast.Call, q: str) -> str | None:
    first = call.args[0] if call.args else None
    named = q == "hashlib.new" and isinstance(first, ast.Constant) and str(first.value).lower() in ("md5", "sha1")
    if not (q in WEAK_HASHES or named) or is_const(keyword(call, "usedforsecurity"), False):
        return None
    context = [ck.scope, *ck.targets, *(w for a in call.args for w in _words(a))]
    return "RT-PY-WEAKHASH" if CREDENTIAL.search(" ".join(context)) else None


def mktemp(ck: Ctx, call: ast.Call, q: str) -> str | None:
    return "RT-PY-MKTEMP" if q == "tempfile.mktemp" else None


def _app_like(func: ast.expr) -> bool:
    receiver = dotted(func.value) if isinstance(func, ast.Attribute) else None
    return "app" in (receiver or "").rsplit(".", 1)[-1].lower()


def debug(ck: Ctx, call: ast.Call, q: str) -> str | None:
    if ck.guarded:
        return None
    name = last_name(call.func)
    if name == "run" and (is_const(keyword(call, "debug"), True)
                          or (_app_like(call.func) and len(call.args) >= 3 and is_const(call.args[2], True))):
        return "RT-PY-DEBUG"
    if q.endswith("run_simple") and any(is_const(keyword(call, k), True) for k in ("use_debugger", "use_evalex")):
        return "RT-PY-DEBUG"
    if name in ("update", "from_mapping") and isinstance(call.func, ast.Attribute) and \
            last_name(call.func.value) == "config" and is_const(keyword(call, "DEBUG"), True):
        return "RT-PY-DEBUG"
    return "RT-PY-DEBUG" if q.endswith("DebuggedApplication") else None


def _all_interfaces(ck: Ctx, node: ast.expr | None, *, empty: bool = False) -> bool:
    """Whether ``node`` is the any-address, written there, bound earlier, or a module constant."""
    values = ALL_INTERFACES + (("",) if empty else ())
    return node is not None and ck.constant(node) in values and isinstance(ck.constant(node), str)


def _bound_address(call: ast.Call, q: str) -> tuple[ast.expr, bool] | None:
    """The address a server or socket call binds, and whether "" (any address) counts, or None. A
    socket bound to port 0 asks for a free port, and is not a server."""
    name = last_name(call.func)
    at = 0 if q == "socket.create_server" else BIND_AT.get(name)
    if at is None or len(call.args) <= at:
        return None
    first = call.args[at]
    if isinstance(first, ast.Tuple) and first.elts:
        if len(first.elts) > 1 and is_const(first.elts[1], 0):
            return None
        return first.elts[0], True
    return first, False


def _host_default(call: ast.Call) -> ast.expr | None:
    """The fallback host of `os.environ.get("HOST", ...)` or `add_argument("--host", default=...)`."""
    name = last_name(call.func)
    if name in ("get", "getenv") and len(call.args) >= 2 and isinstance(call.args[0], ast.Constant):
        return call.args[1] if HOST_ENV.search(str(call.args[0].value)) else None
    if name == "add_argument" and call.args and is_const(call.args[0], *HOST_OPTIONS):
        return keyword(call, "default")
    return None


def host_parameter_binds_all(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """`def serve(port, host="0.0.0.0")`: a server whose default is every interface."""
    args = fn.args
    positional = [*args.posonlyargs, *args.args]
    pairs = list(zip(positional[len(positional) - len(args.defaults):], args.defaults, strict=True))
    pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d is not None]
    return any(a.arg in HOST_KEYWORDS and is_const(d, *ALL_INTERFACES) for a, d in pairs)


def bind_all(ck: Ctx, call: ast.Call, q: str) -> str | None:
    if ck.entry_point:
        return None
    bound = _bound_address(call, q)
    hit = (bound is not None and _all_interfaces(ck, bound[0], empty=bound[1])) or \
        any(k.arg in HOST_KEYWORDS and _all_interfaces(ck, k.value) for k in call.keywords) or \
        _all_interfaces(ck, _host_default(call))
    return "RT-PY-BINDALL" if hit else None


def tls(ck: Ctx, call: ast.Call, q: str) -> str | None:
    verify = keyword(call, "verify")
    if (verify is not None and ck.falsy(verify) and not is_const(verify, None)) or \
            q == "ssl._create_unverified_context":
        return "RT-PY-TLS"
    off = [keyword(call, k) for k in ("ssl", "verify_ssl")]
    client = q.startswith("aiohttp.") or last_name(call.func) in TLS_CLIENT
    return "RT-PY-TLS" if client and any(v is not None and is_const(v, False) for v in off) else None


# -- assignments -----------------------------------------------------------------------------------

def debug_assign(ck: Ctx, node: ast.Assign) -> str | None:
    if not is_const(node.value, True) or ck.guarded:
        return None
    for t in node.targets:
        if isinstance(t, ast.Attribute) and t.attr == "debug":
            return "RT-PY-DEBUG"
        if isinstance(t, ast.Subscript) and is_const(t.slice, "DEBUG") and \
                isinstance(t.value, ast.Attribute) and t.value.attr == "config":
            return "RT-PY-DEBUG"
        if ck.module and isinstance(t, ast.Name) and t.id == "DEBUG":
            return "RT-PY-DEBUG"
    return None


def _environ_key(t: ast.expr) -> object:
    if isinstance(t, ast.Subscript) and dotted(t.value) in ("os.environ", "environ"):
        return t.slice.value if isinstance(t.slice, ast.Constant) else None
    return None


def tls_assign(ck: Ctx, node: ast.Assign) -> str | None:
    for t in node.targets:
        name = t.attr if isinstance(t, ast.Attribute) else ""
        if (name in ("check_hostname", "verify") and is_const(node.value, False)) or \
                (name == "verify_mode" and (dotted(node.value) or "").endswith("CERT_NONE")) or \
                (name == "_create_default_https_context" and dotted(t) == "ssl._create_default_https_context"):
            return "RT-PY-TLS"
        key = _environ_key(t)
        if (key in CA_VARIABLES and is_const(node.value, "")) or (key == "PYTHONHTTPSVERIFY" and
                                                                   is_const(node.value, "0")):
            return "RT-PY-TLS"
    return None


def bind_assign(ck: Ctx, node: ast.Assign) -> str | None:
    """A gunicorn configuration file's `bind = "0.0.0.0:8000"`."""
    if ck.entry_point or not ck.module or not ck.filename.rsplit("/", 1)[-1].startswith("gunicorn"):
        return None
    if not any(isinstance(t, ast.Name) and t.id == "bind" for t in node.targets):
        return None
    values = node.value.elts if isinstance(node.value, ast.List | ast.Tuple) else [node.value]
    for v in values:
        text = str(v.value) if isinstance(v, ast.Constant) else ""
        if text.startswith(("0.0.0.0", "[::]", ":")):
            return "RT-PY-BINDALL"
    return None
