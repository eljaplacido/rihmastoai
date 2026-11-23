"""RT-PY-PATH: a request-derived path opened without a containment check. A dataflow heuristic.

The heuristic works inside one function at a time, and says so in every report:

1. **Sources.** A parameter named `request`, `req` or `environ`, and in a module that imports a
   web framework also `query`, `params`, `form`, `body`, `headers` or `qs` (a command line's
   `params` is the operator's own); the same names used free in the function (a framework's global
   `request`); every parameter of a function a route decorator registers (`@app.route("/f/<name>")`,
   `@app.get("/files/{filename}")`); in a class deriving from a `...RequestHandler`, `self.path`,
   `self.headers`, `self.rfile` and `self.request`; and anywhere, `self.get_argument(...)` and its
   Tornado relatives.
2. **Propagation.** A name assigned from an expression that holds a tainted value is tainted
   (assignments, `for` targets, `with ... as`, walrus), repeated until nothing changes.
3. **Sanitisers.** A value passed through `os.path.basename`, `secure_filename`, `safe_join`,
   `int`, `float`, `len`, `bool`, `uuid.UUID` or `hash` is clean, and so is a value looked up in a
   table written in the source (`PAGES.get(self.path)`, `PAGES[name]`). A name checked against an
   allowlist is clean when the check guards the file operation (`if name not in ALLOWED: abort()`,
   or `if name in ALLOWED: open(...)`): `in` / `not in` a collection that is not a string, a regular
   expression's `fullmatch`, or its `match` anchored at the end (`\\Z` or `$`), and only when the
   pattern admits no traversal (`[\\w./-]+` lets `../../etc/passwd` through, so it is not one). A
   denylist (`if name in BLOCKED: abort()`) is not an allowlist.
4. **Containment.** A function is not reported when it checks that the request-derived path itself,
   resolved (`realpath`, `abspath`, `normpath`, `resolve()`), stays inside its base, and the check
   guards the file operation: `is_relative_to`, `relative_to`, `commonpath`, `startswith` or
   `BASE in p.parents`, in the test of an `if` that stops (returns, raises, aborts) or holds the
   operation, in an `assert`, or a bare `relative_to` (which raises). A check that only logs, or a
   check on an unresolved path (`../` passes a lexical test), does not excuse the function.
5. **Sinks.** `open` and its relatives (`builtins.open`, `aiofiles.open`), file removal and copying,
   `send_file`, `FileResponse`, `shutil.unpack_archive`, and the `pathlib` and archive methods that
   read, write, list, delete or extract, on a tainted path.

Not followed: a value that crosses a function call (an argument to a helper that opens the file),
attributes of objects other than `self` in a handler, and data stored and read back later. Those
misses are the heuristic's honest limit, stated in the coverage note of every Python scan.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable

from kernel.redteam.pyast import FUNCTIONS, Function, functions, last_name, own_nodes, qualname

ALWAYS_SOURCES = frozenset({"request", "req", "environ"})
WEB_SOURCES = frozenset({"query", "params", "form", "body", "headers", "qs"})
WEB_MODULES = frozenset({"flask", "django", "fastapi", "starlette", "aiohttp", "tornado", "bottle", "falcon",
                         "pyramid", "sanic", "werkzeug", "quart", "litestar", "http", "wsgiref", "cgi"})
HANDLER_ATTRS = frozenset({"path", "headers", "rfile", "requestline", "request"})
GETTERS = frozenset({"get_argument", "get_arguments", "get_query_argument", "get_query_arguments",
                     "get_body_argument", "get_body_arguments", "get_cookie"})
ROUTE_DECORATORS = frozenset({"route", "get", "post", "put", "patch", "delete", "head", "options", "api_route",
                              "websocket", "add_url_rule"})
SANITISERS = frozenset({"basename", "secure_filename", "safe_join", "int", "float", "len", "bool", "UUID", "hash"})
OPENERS = frozenset({"open", "io.open", "codecs.open", "os.open", "os.remove", "os.unlink", "os.rmdir",
                     "os.listdir", "os.scandir", "os.startfile", "shutil.rmtree", "shutil.copy", "shutil.copy2",
                     "shutil.copyfile", "shutil.move", "shutil.unpack_archive", "send_file", "flask.send_file",
                     "builtins.open", "aiofiles.open", "FileResponse", "fastapi.responses.FileResponse",
                     "starlette.responses.FileResponse"})
PATH_METHODS = frozenset({"open", "read_text", "read_bytes", "write_text", "write_bytes", "unlink", "rmdir",
                          "iterdir", "touch", "mkdir", "extractall", "extract"})
CONTAINMENT = frozenset({"is_relative_to", "relative_to", "commonpath", "startswith"})
RESOLVERS = frozenset({"realpath", "abspath", "resolve", "normpath"})
STOPS = frozenset({"abort", "exit", "fail", "deny", "forbidden", "not_found", "bad_request"})
ALLOWLIST_TESTS = frozenset({"match", "fullmatch"})
# Names a traversal would use: a pattern that matches any of them is no allowlist for a path.
ESCAPES = ("../x", "..\\x", "/etc/passwd", "a/../../b", "..", "C:\\x", "\\\\host\\x")


class _Flow:
    def __init__(self, tainted: set[str], handler: bool, tables: set[str]) -> None:
        self.tainted = tainted
        self.handler = handler
        self.tables = tables

    def _table(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id in self.tables

    def _call_parts(self, node: ast.Call) -> list[ast.AST]:
        """A call's receiver and arguments; none for a sanitiser or a lookup in a fixed table."""
        func = node.func
        lookup = isinstance(func, ast.Attribute) and func.attr == "get" and self._table(func.value)
        if last_name(func) in SANITISERS or lookup:
            return []
        inner = [func.value] if isinstance(func, ast.Attribute) else []
        return [*inner, *node.args, *(k.value for k in node.keywords)]

    def _parts(self, node: ast.AST) -> list[ast.AST]:
        """What a tainted value could reach ``node`` through: a call's receiver and arguments, an
        attribute's object (none for a handler's own `self.x`), any child (none for `TABLE[x]`)."""
        if isinstance(node, ast.Attribute):
            own = self.handler and isinstance(node.value, ast.Name) and node.value.id == "self"
            return [] if own else [node.value]
        if isinstance(node, ast.Subscript) and self._table(node.value):
            return []
        if isinstance(node, ast.Call):
            return self._call_parts(node)
        return list(ast.iter_child_nodes(node))

    def _source(self, n: ast.AST) -> bool:
        if isinstance(n, ast.Name):
            return n.id in self.tainted
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
            return self.handler and n.attr in HANDLER_ATTRS
        return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in GETTERS and \
            isinstance(n.func.value, ast.Name) and n.func.value.id == "self"

    def dirty(self, node: ast.AST | None) -> bool:
        """Whether a tainted value can reach this expression's result (walked without recursion)."""
        stack = [] if node is None else [node]
        while stack:
            n = stack.pop()
            if self._source(n):
                return True
            stack.extend(self._parts(n))
        return False


def _binding(node: ast.AST) -> tuple[list[ast.AST], ast.AST | None] | None:
    """(the targets, the expression they are bound from) of one binding node, or None."""
    if isinstance(node, ast.Assign):
        return list(node.targets), node.value
    if isinstance(node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr):
        return [node.target], node.value
    if isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
        return [node.target], node.iter
    if isinstance(node, ast.withitem) and node.optional_vars is not None:
        return [node.optional_vars], node.context_expr
    return None


def _bindings(fn: Function) -> list[tuple[list[str], ast.AST]]:
    """(names bound, the expression they are bound from) for every binding in the function."""
    out: list[tuple[list[str], ast.AST]] = []
    for node in own_nodes(fn):
        found = _binding(node)
        if found is not None and found[1] is not None:
            names = [n.id for t in found[0] for n in ast.walk(t) if isinstance(n, ast.Name)]
            out.append((names, found[1]))
    return out


def compiled_patterns(tree: ast.AST, names: dict[str, str]) -> dict[str, str]:
    """Module-level names bound to `re.compile("<a literal pattern>")`: name -> pattern."""
    out: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and node.value.args and \
                qualname(node.value.func, names) == "re.compile" and isinstance(node.value.args[0], ast.Constant):
            pattern = node.value.args[0].value
            out.update((t.id, pattern) for t in node.targets if isinstance(t, ast.Name) and isinstance(pattern, str))
    return out


def tables(tree: ast.AST) -> set[str]:
    """Module-level names bound to a dict, list or tuple literal: a fixed table."""
    return {t.id for node in getattr(tree, "body", []) if isinstance(node, ast.Assign) and
            isinstance(node.value, ast.Dict | ast.List | ast.Tuple) for t in node.targets if isinstance(t, ast.Name)}


def _anchored(pattern: str | None) -> bool:
    """Whether a regular expression must match to the end of the text (`\\Z`, `\\z` or an unescaped `$`)."""
    if not pattern:
        return False
    return pattern.endswith(("\\Z", "\\z")) or (pattern.endswith("$") and not pattern.endswith("\\$"))


def _admits_traversal(pattern: str | None) -> bool:
    if pattern is None:
        return False
    try:
        compiled = re.compile(pattern)
    except re.error:
        return True
    return any(compiled.fullmatch(e) for e in ESCAPES)


def _pattern(call: ast.Call, names: dict[str, str], patterns: dict[str, str]) -> str | None:
    """The pattern of `NAME.match(x)` (NAME a compiled literal) or `re.match("<literal>", x)`, else None."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in patterns:
        return patterns[func.value.id]
    if qualname(func, names) in ("re.match", "re.fullmatch") and call.args and isinstance(call.args[0], ast.Constant):
        value = call.args[0].value
        return value if isinstance(value, str) else None
    return None


class _Guards:
    """Which tests in a function guard what follows them: the `if` each test is in, and whether that
    `if` stops (returns, raises, aborts) or holds a file operation."""

    def __init__(self, fn: Function, sink_lines: set[int]) -> None:
        self.parent: dict[int, ast.AST] = {}
        for node in own_nodes(fn):
            for child in ast.iter_child_nodes(node):
                self.parent[id(child)] = node
        for child in ast.iter_child_nodes(fn):
            self.parent[id(child)] = fn
        self.sinks = sink_lines

    def statement(self, node: ast.AST) -> tuple[ast.AST | None, bool]:
        """The statement ``node`` is part of, and whether it sits under a `not`."""
        negated = False
        current: ast.AST | None = node
        while current is not None and not isinstance(current, ast.stmt):
            parent = self.parent.get(id(current))
            if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
                negated = not negated
            current = parent
        return current, negated

    def _stops(self, body: list[ast.stmt]) -> bool:
        last = body[-1] if body else None
        if isinstance(last, ast.Return | ast.Raise | ast.Continue | ast.Break):
            return True
        return isinstance(last, ast.Expr) and isinstance(last.value, ast.Call) and last_name(last.value.func) in STOPS

    def _holds(self, body: list[ast.stmt]) -> bool:
        return any(getattr(n, "lineno", 0) in self.sinks for stmt in body for n in ast.walk(stmt))

    def guards(self, test: ast.AST, *, positive: bool) -> bool:
        """Whether ``test`` guards: true (``positive``) lets the operation run, false stops it."""
        stmt, negated = self.statement(test)
        if isinstance(stmt, ast.Assert):
            return positive != negated
        if not isinstance(stmt, ast.If):
            return False
        allows = positive != negated
        return self._holds(stmt.body) if allows else self._stops(stmt.body) and not self._holds(stmt.body)


def _regex_allows(node: ast.Call, guards: _Guards, names: dict[str, str], patterns: dict[str, str]) -> list[str]:
    """The names a guarding, end-anchored regular expression that admits no traversal allows."""
    pattern = _pattern(node, names, patterns)
    full = last_name(node.func) == "fullmatch" or _anchored(pattern)
    if full and not _admits_traversal(pattern) and guards.guards(node, positive=True):
        return [a.id for a in node.args if isinstance(a, ast.Name)]
    return []


def _membership_allows(node: ast.Compare, guards: _Guards) -> list[str]:
    """The name `name in ALLOWED` (or `not in` that stops) allows; a string is not a collection."""
    if not isinstance(node.left, ast.Name) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.In | ast.NotIn):
        return []
    if isinstance(node.comparators[0], ast.Constant):
        return []
    return [node.left.id] if guards.guards(node, positive=isinstance(node.ops[0], ast.In)) else []


def _allowlisted(fn: Function, guards: _Guards, names: dict[str, str], patterns: dict[str, str]) -> set[str]:
    """Names the function checks against an allowlist that guards the file operation."""
    out: set[str] = set()
    for node in own_nodes(fn):
        if isinstance(node, ast.Call) and last_name(node.func) in ALLOWLIST_TESTS:
            out.update(_regex_allows(node, guards, names, patterns))
        elif isinstance(node, ast.Compare):
            out.update(_membership_allows(node, guards))
    return out


def _resolved_names(fn: Function) -> set[str]:
    """Names bound to a resolved path: `p = (BASE / name).resolve()`, `real = os.path.realpath(...)`."""
    out = set()
    for targets, value in _bindings(fn):
        if isinstance(value, ast.Call) and last_name(value.func) in RESOLVERS:
            out.update(targets)
    return out


def _resolved(node: ast.AST | None, resolved: set[str]) -> bool:
    if isinstance(node, ast.Call) and last_name(node.func) == "str" and node.args:
        node = node.args[0]
    return (isinstance(node, ast.Name) and node.id in resolved) or \
        (isinstance(node, ast.Call) and last_name(node.func) in RESOLVERS)


def _parents_check(node: ast.AST, flow: _Flow, guards: _Guards, resolved: set[str]) -> bool:
    """`if BASE not in p.parents: abort()` on a resolved, request-derived `p`."""
    if not isinstance(node, ast.Compare):
        return False
    parents = next((c for c in node.comparators if isinstance(c, ast.Attribute) and c.attr == "parents"), None)
    return parents is not None and _resolved(parents.value, resolved) and flow.dirty(parents.value) and \
        guards.guards(node, positive=isinstance(node.ops[0], ast.In))


def _containment_call(node: ast.AST, flow: _Flow, guards: _Guards, resolved: set[str]) -> bool:
    """`is_relative_to`, `relative_to`, `commonpath` or `startswith` on a resolved, request-derived path,
    where it guards (or a bare `relative_to`, which raises)."""
    if not (isinstance(node, ast.Call) and last_name(node.func) in CONTAINMENT):
        return False
    receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
    candidates = [receiver] if last_name(node.func) != "commonpath" else \
        [e for a in node.args for e in (a.elts if isinstance(a, ast.List | ast.Tuple) else [a])]
    if not any(x is not None and flow.dirty(x) and _resolved(x, resolved) for x in candidates):
        return False
    stmt, _ = guards.statement(node)
    bare = isinstance(stmt, ast.Expr) and stmt.value is node and last_name(node.func) == "relative_to"
    return bare or guards.guards(node, positive=True)


def _contained(fn: Function, flow: _Flow, guards: _Guards) -> bool:
    """Whether the function checks, where it guards, that the request-derived path itself, resolved,
    stays inside its base."""
    resolved = _resolved_names(fn)
    return any(_parents_check(node, flow, guards, resolved) or _containment_call(node, flow, guards, resolved)
               for node in own_nodes(fn))


def _route(fn: Function) -> bool:
    """Whether a route decorator registers the function (`@app.route("/x")`, `@router.get("/x")`)."""
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and last_name(d.func) in ROUTE_DECORATORS:
            first = d.args[0] if d.args else None
            path = [a for a in d.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if last_name(d.func) == "route" or (path and str(path[0].value).startswith("/")) or first is None:
                return True
    return False


def _sources(fn: Function, web: bool, bound: list[tuple[list[str], ast.AST]]) -> set[str]:
    """The names that hold request data when the function starts (see the module's docstring)."""
    params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)]
    sources = ALWAYS_SOURCES | (WEB_SOURCES if web else frozenset())
    assigned = {name for bound_names, _ in bound for name in bound_names}
    used = {n.id for n in own_nodes(fn) if isinstance(n, ast.Name)}
    route_params = {p for p in params if p not in ("self", "cls")} if _route(fn) else set()
    return {p for p in params if p in sources} | (used & (sources - assigned - set(params))) | route_params


def _flow(fn: Function, handler: bool, web: bool, tables_: set[str], clean: set[str]) -> _Flow:
    bound = _bindings(fn)
    flow = _Flow(_sources(fn, web, bound) - clean, handler, tables_)
    changed = True
    while changed:
        changed = False
        for targets, value in bound:
            fresh = [n for n in targets if n not in flow.tainted and n not in clean]
            if fresh and flow.dirty(value):
                flow.tainted.update(fresh)
                changed = True
    return flow


def _sink_values(call: ast.Call, names: dict[str, str]) -> list[ast.AST]:
    """The expressions of a call that name a file: the path argument, or the path a method runs on."""
    if qualname(call.func, names) in OPENERS or (isinstance(call.func, ast.Name) and call.func.id in OPENERS):
        return [*call.args[:1], *(k.value for k in call.keywords if k.arg in ("file", "path", "src", "dst",
                                                                             "filename"))]
    if isinstance(call.func, ast.Attribute) and call.func.attr in PATH_METHODS:
        if call.func.attr in ("extractall", "extract") and any(k.arg == "filter" for k in call.keywords):
            return []
        return [call.func.value]
    return []


def _handler(owner: ast.ClassDef | None) -> bool:
    if owner is None:
        return False
    return any(last_name(b).endswith("RequestHandler") for b in owner.bases)


def _function_hits(fn: Function, owner: ast.ClassDef | None, names: dict[str, str], patterns: dict[str, str],
                   web: bool, tables_: set[str]) -> Iterable[int]:
    calls = [n for n in own_nodes(fn) if isinstance(n, ast.Call)]
    sinks = [c for c in calls if _sink_values(c, names)]
    if not sinks:
        return []
    guards = _Guards(fn, {c.lineno for c in sinks})
    flow = _flow(fn, _handler(owner), web, tables_, _allowlisted(fn, guards, names, patterns))
    if _contained(fn, flow, guards):
        return []
    return [c.lineno for c in sinks if any(flow.dirty(v) for v in _sink_values(c, names))]


def _web(tree: ast.AST) -> bool:
    """Whether the module imports a web framework (then `params`, `form`, `body`... are request data)."""
    for node in ast.walk(tree):
        modules = [a.name for a in node.names] if isinstance(node, ast.Import) else \
            [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        if any(m.split(".")[0] in WEB_MODULES for m in modules):
            return True
    return False


def path_hits(tree: ast.AST, names: dict[str, str]) -> list[int]:
    """The lines where a request-derived path reaches a file operation with no containment check."""
    lines: set[int] = set()
    patterns, fixed, web = compiled_patterns(tree, names), tables(tree), _web(tree)
    for fn, owner in functions(tree):
        if isinstance(fn, FUNCTIONS):
            lines.update(_function_hits(fn, owner, names, patterns, web, fixed))
    return sorted(lines)
