"""Small helpers over Python's `ast` for the rules: what a name resolves to, and what is a literal.

`aliases` maps each name a module imports to where it comes from (`import pickle as pk` gives
`pk -> pickle`; `from yaml import load` gives `load -> yaml.load`; a star import the names the
rules know of its module), and each name bound to such a thing (`run = os.system`), so `qualname`
can say that `pk.loads(...)` is `pickle.loads`. `getattr(os, "system")` and `__import__("os")`
are read too. A name nothing imports keeps its own spelling: `eval`, `open`.

`is_literal` is the test the rules use for "not built from data": a constant, an f-string with no
placeholder, a list or tuple of literals, a sum of literals, or a module-level constant.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
Function = ast.FunctionDef | ast.AsyncFunctionDef
# The names a star import brings in that the rules know: `from subprocess import *` makes `check_output`
# subprocess's own.
STAR_EXPORTS = {
    "subprocess": ("run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput"),
    "os": ("system", "popen", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
           "remove", "unlink", "listdir", "scandir"),
    "pickle": ("load", "loads", "Unpickler"), "marshal": ("load", "loads"), "shelve": ("open",),
    "yaml": ("load", "load_all", "unsafe_load", "unsafe_load_all"), "hashlib": ("md5", "sha1", "new"),
    "tempfile": ("mktemp",), "shutil": ("rmtree", "copy", "copy2", "copyfile", "move"),
    "requests": ("get", "post", "put", "patch", "delete", "head", "options", "request", "Session", "session"),
}
# Builtins a module may rename (`evaluate = eval`): the rules still see the builtin.
BUILTIN_SINKS = frozenset({"eval", "exec", "compile", "open", "__import__", "getattr"})
IMPORTERS = frozenset({"__import__", "importlib.import_module"})


def _imports(tree: ast.AST) -> dict[str, str]:
    """Local name -> dotted origin, from every absolute import; a star import brings the names the rules
    know of its module (`STAR_EXPORTS`), and an explicit import wins over it."""
    explicit: dict[str, str] = {}
    star: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                explicit[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                if a.name == "*":
                    star.update({n: f"{node.module}.{n}" for n in STAR_EXPORTS.get(node.module, ())})
                else:
                    explicit[a.asname or a.name] = f"{node.module}.{a.name}"
    return star | explicit


def _alias_of(node: ast.AST) -> tuple[str, ast.expr] | None:
    """(name, value) for `name = value` or `with value as name`, one plain name bound."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    if isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
        return node.optional_vars.id, node.context_expr
    return None


def aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> dotted origin: every absolute import, and every name bound to something an import or
    a builtin resolves (`run = os.system`, `evaluate = eval`, `s = requests.Session()` gives
    `requests.Session()`), so `qualname` sees through them."""
    out = _imports(tree)
    bound = [found for node in ast.walk(tree) if (found := _alias_of(node)) is not None]
    for _ in range(2):  # an alias of an alias
        for name, value in bound:
            base = value.func if isinstance(value, ast.Call) else value
            d = dotted(base)
            head = (d or "").split(".")[0]
            if d is None or not (head in out or (d == head and head in BUILTIN_SINKS)):
                continue
            q = qualname(value, out) if isinstance(value, ast.Call) else qualname(base, out)
            if q and q != name:
                out[name] = q
    return out


def dotted(node: ast.AST) -> str | None:
    """`a.b.c` for a chain of attributes on a name; None for anything else (a call, a subscript)."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _call_base(call: ast.Call, names: dict[str, str]) -> str:
    """What a call at the base of a name stands for: the module `__import__("os")` imports, the
    attribute `getattr(os, "system")` reads, or `<the function>()` (an object a constructor made)."""
    q = qualname(call.func, names)
    args = call.args
    if q in IMPORTERS and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
        return args[0].value
    if q == "getattr" and len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
        inner = qualname(args[0], names)
        return f"{inner}.{args[1].value}" if inner else ""
    return f"{q}()" if q else ""


def qualname(func: ast.AST, names: dict[str, str]) -> str:
    """The dotted name a call's function resolves to through the module's imports and aliases ("" if
    unknown): `pk.loads` is `pickle.loads`, `getattr(os, "system")` is `os.system`, `Session().get` is
    `requests.Session().get`."""
    attrs: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        base = names.get(node.id, node.id)
    elif isinstance(node, ast.Call):
        base = _call_base(node, names)
    else:
        return ""
    return ".".join([base, *reversed(attrs)]) if base else ""


def last_name(func: ast.AST) -> str:
    """The last part of a call's name: `open` for `os.open`, `loads` for `pk.loads`, "" otherwise."""
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def constants(tree: ast.Module) -> dict[str, object]:
    """Module-level names bound once to a constant: `HOST = "127.0.0.1"`."""
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def flatten_add(node: ast.expr) -> list[ast.expr]:
    """The terms of `a + b + c`, left to right, without recursion (a generated chain can be thousands
    of terms deep)."""
    out: list[ast.expr] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            stack += [n.right, n.left]
        else:
            out.append(n)
    return out


def is_literal(node: ast.AST | None, consts: dict[str, object] | None = None) -> bool:
    """Whether ``node`` is fixed in the source: no value from data can reach it."""
    if node is None or isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.JoinedStr):
        return not any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return all(is_literal(e, consts) for e in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return all(is_literal(term, consts) for term in flatten_add(node))
    if isinstance(node, ast.Name):
        return node.id in (consts or {})
    return False


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    """The value passed as ``name=`` to the call, or None."""
    return next((k.value for k in call.keywords if k.arg == name), None)


def argument(call: ast.Call, position: int, name: str) -> ast.expr | None:
    """The value passed at ``position`` or as ``name=``, or None."""
    if len(call.args) > position and not any(isinstance(a, ast.Starred) for a in call.args[: position + 1]):
        return call.args[position]
    return keyword(call, name)


def passes(call: ast.Call, position: int, name: str) -> bool:
    """Whether the call passes something at ``position`` or as ``name=`` (a ``**kwargs`` may hold it)."""
    has_star = any(k.arg is None for k in call.keywords) or any(isinstance(a, ast.Starred) for a in call.args)
    return has_star or argument(call, position, name) is not None


def is_const(node: ast.AST | None, *values: object) -> bool:
    """Whether ``node`` is a constant equal to one of ``values`` and of its type (True is not 1)."""
    if not isinstance(node, ast.Constant):
        return False
    return any(type(node.value) is type(v) and node.value == v for v in values)


def own_nodes(fn: ast.AST) -> Iterator[ast.AST]:
    """The nodes of a function's body, not those of functions or classes defined inside it."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (*FUNCTIONS, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def functions(tree: ast.AST) -> list[tuple[Function, ast.ClassDef | None]]:
    """Every function in the tree, in source order, with the class it is a method of (or None)."""
    out: list[tuple[Function, ast.ClassDef | None]] = []
    stack: list[tuple[ast.AST, ast.ClassDef | None]] = [(tree, None)]
    while stack:
        node, owner = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, FUNCTIONS):
                out.append((child, owner))
                stack.append((child, None))
            else:
                stack.append((child, child if isinstance(child, ast.ClassDef) else owner))
    return sorted(out, key=lambda pair: (pair[0].lineno, pair[0].col_offset))


def simple_assignments(fn: ast.AST) -> dict[str, ast.expr]:
    """`name = value` inside a function (the last one wins): enough to see a query built a line earlier."""
    out: dict[str, ast.expr] = {}
    nodes = sorted((n for n in own_nodes(fn) if isinstance(n, ast.Assign)), key=lambda n: (n.lineno, n.col_offset))
    for node in nodes:
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = node.value
    return out
