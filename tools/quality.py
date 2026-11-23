#!/usr/bin/env python3
"""quality: the factory's own code-quality gate (criterion FR-O8-AC-5).

Standard library only, no model. It reads the Python files of the runtime packages (kernel/,
adapters/, embed/, mcp/), the cockpit server, the tools and the tests, and reports per file and
in total:
- unused imports, unused local variables (assignments, `except ... as`, loop variables), and
  names imported twice;
- annotation coverage: public functions and methods with full parameter and return annotations;
- function length, and functions over 60 lines;
- cyclomatic complexity (1 + each if, loop, conditional expression, except handler, match case,
  comprehension clause and extra boolean operand), and functions over 15;
- module size, and modules over 500 lines;
- duplicated function bodies (an identical AST dump once the docstring is removed);
- bare `except:`, and `except Exception` with neither a comment nor a re-raise;
- print() in library code (anything but command lines, servers, tools and tests);
- mutable default arguments;
- TODO and FIXME markers;
- CR line endings and trailing whitespace;
- in the runtime packages, imports that leave the standard library.

The gate (--gate):
- **Hard rules** fail on any finding: a file that does not parse, a third-party import in a
  runtime package, a bare except, a mutable default, a file with CR line endings.
- **Ratchet:** every other count is held at or below its value in tools/quality_baseline.json.
  A count that grows fails the gate. A count that falls is reported, so the baseline can be
  lowered in the same change with --write-baseline. Size, length, complexity, annotation and
  duplicate counts cover the code outside tests/, so a new test is not held to them.

ruff and mypy are optional. When this interpreter can import them, or RIHMA_QA_PYTHON names an
interpreter that can, their counts are measured with fixed settings (ruff --isolated, mypy with
no config file) and held to the baseline while the tool versions match the baseline's.
Otherwise they read "not measured", and the stdlib rules still apply.

Exit codes: 0 passed, 1 failed (a hard rule broke or a count grew), 2 a usage or internal error
(a bug in this tool, never a verdict on the code).

Usage:
  python tools/quality.py                      a readable summary
  python tools/quality.py --json               the full report
  python tools/quality.py --gate               hard rules and ratchet; exit 1 on failure
  python tools/quality.py --write-baseline     record today's counts (review the diff)
  python tools/quality.py --no-external        skip ruff and mypy even when available
  python tools/quality.py --mypy-strict        also count `mypy --strict` errors on kernel/
  python tools/quality.py --prompts            model-facing prompt sizes on a fake project
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tokenize
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeGuard

REPORT_SCHEMA = "rihma.quality/1"
BASELINE_SCHEMA = "rihma.quality_baseline/1"
ROOT = Path(__file__).resolve().parent.parent

SCOPE = ("kernel", "adapters", "cockpit/server.py", "embed", "mcp", "tools", "tests")
RUNTIME = ("kernel/", "adapters/", "embed/", "mcp/")  # stdlib-only: what a factory run imports
SKIP_DIRS = {"__pycache__", "fixtures", "static", "screenshots"}
# Files whose interface is print(): command lines, servers, tools and tests.
PRINT_OK = re.compile(r"^(tools/|tests/|kernel/cli\.py$|[a-z_]+/server\.py$)")
MAX_FUNCTION_LINES = 60
MAX_COMPLEXITY = 15
MAX_MODULE_LINES = 500
MIN_DUPLICATE_NODES = 8  # a body smaller than this (pass, return x) is not worth reporting
MUTABLE_CALLS = {"list", "dict", "set", "bytearray", "defaultdict", "OrderedDict", "Counter", "deque"}
MARKER = re.compile(r"\b(TODO|FIXME)\b")
NOQA = re.compile(r"#\s*noqa(?::\s*(?P<codes>[A-Z0-9, ]+))?", re.IGNORECASE)
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
BRANCHES = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.match_case)

HARD = ("unparsable_files", "third_party_imports", "bare_excepts", "mutable_defaults", "non_lf_files")
RATCHET = ("unused_imports", "unused_locals", "duplicate_imports", "unexplained_broad_excepts", "library_prints",
           "todo_markers", "trailing_whitespace_lines",
           # outside tests/ only
           "unannotated_public_functions", "long_functions", "complex_functions", "large_modules",
           "duplicate_bodies")
EXTERNAL = ("ruff_findings", "mypy_errors", "mypy_strict_kernel_errors")
FINDINGS = ("unused_imports", "unused_locals", "duplicate_imports", "prints", "mutable_defaults",
            "bare_excepts", "third_party", "markers")

QA_PYTHON_ENV = "RIHMA_QA_PYTHON"
RUFF_PATHS = ("kernel", "adapters", "embed", "mcp", "cockpit/server.py", "tools")
RUFF_ARGS = ("--isolated", "--select", "E,F,W,B,I,UP,SIM", "--line-length", "120", "--target-version", "py311")
MYPY_PATHS = ("kernel", "adapters", "embed", "mcp")
MYPY_ARGS = ("--ignore-missing-imports", "--python-version", "3.11", "--config-file", "",
             "--show-error-codes", "--no-error-summary", "--no-pretty", "--no-color-output")
MYPY_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?:\d+:)? error: (?P<msg>.*?)(?:  \[(?P<code>[a-z0-9-]+)\])?$")

Function = ast.FunctionDef | ast.AsyncFunctionDef


# -- reading a file ------------------------------------------------------------------------------

def iter_files(root: Path) -> list[Path]:
    """The Python files in scope, in a stable order."""
    out: list[Path] = []
    for entry in SCOPE:
        path = root / entry
        if path.is_file():
            out.append(path)
        elif path.is_dir():
            for dirpath, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
                out += [Path(dirpath) / f for f in sorted(files) if f.endswith(".py")]
    return out


def first_party(root: Path) -> set[str]:
    """Top-level names this repository provides: its packages and modules, and the test helpers."""
    names = {p.name for p in root.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    names |= {p.stem for p in root.glob("*.py")}
    if (root / "tests").is_dir():
        names |= {p.stem for p in (root / "tests").glob("*.py")}
    return names | {"tests", "tools"}


def comments_of(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


def _noqa(comments: dict[int, str], first: int, last: int, code: str) -> bool:
    for line in range(first, last + 1):
        m = NOQA.search(comments.get(line, ""))
        if m and (not m.group("codes") or code in m.group("codes").upper()):
            return True
    return False


def trailing_whitespace(data: bytes) -> list[int]:
    lines = (line.rstrip(b"\r") for line in data.split(b"\n"))
    return [n for n, line in enumerate(lines, 1) if line != line.rstrip(b" \t")]


# -- names: what a scope reads -------------------------------------------------------------------

def _annotation_names(ann: ast.AST | None) -> set[str]:
    """Names inside string annotations, such as "Factory" or list["Project"]."""
    names: set[str] = set()
    for c in ast.walk(ann) if ann is not None else ():
        if isinstance(c, ast.Constant) and isinstance(c.value, str):
            with contextlib.suppress(SyntaxError):
                names |= {x.id for x in ast.walk(ast.parse(c.value, mode="eval")) if isinstance(x, ast.Name)}
    return names


def _reads(node: ast.AST) -> set[str]:
    """The names one node reads (not its children)."""
    if isinstance(node, ast.Name):
        return set() if isinstance(node.ctx, ast.Store) else {node.id}
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    if isinstance(node, (ast.arg, ast.AnnAssign)):
        return _annotation_names(node.annotation)
    return set()


def _header(fn: Function) -> list[ast.AST]:
    """What a def evaluates in its enclosing scope: decorators, defaults and annotations. The
    return annotation travels as an unnamed parameter, so its string form is read too."""
    a = fn.args
    params = a.posonlyargs + a.args + a.kwonlyargs + [p for p in (a.vararg, a.kwarg) if p is not None]
    returns = [ast.arg(arg="", annotation=fn.returns)] if fn.returns is not None else []
    return [*fn.decorator_list, *a.defaults, *[d for d in a.kw_defaults if d is not None], *params, *returns]


def own_code(scope: ast.AST) -> tuple[list[ast.AST], list[Function]]:
    """(the nodes that run in ``scope`` itself, the functions defined directly in it). Class bodies
    and lambdas count as part of the scope that holds them."""
    nodes: list[ast.AST] = []
    inner: list[Function] = []
    stack: list[ast.AST] = list(getattr(scope, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, DEFS):
            inner.append(node)
            stack += _header(node)
            continue
        nodes.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return nodes, inner


def _uses(nodes: list[ast.AST]) -> set[str]:
    return set().union(*(_reads(n) for n in nodes))


def _import_names(stmt: ast.AST) -> Iterator[tuple[tuple, str, str]]:
    """(key, the name a read must use, the name a second import would repeat) per imported name."""
    if isinstance(stmt, ast.Import):
        for a in stmt.names:
            yield (a.name,), a.asname or a.name.split(".")[0], a.asname or a.name
    elif isinstance(stmt, ast.ImportFrom) and stmt.module != "__future__":
        for a in stmt.names:
            if a.name != "*":
                yield (stmt.level, stmt.module, a.name), a.asname or a.name, a.asname or a.name


def _dunder_all(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets) \
                and isinstance(node.value, (ast.List, ast.Tuple)):
            out |= {e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return out


class ImportCheck:
    """Unused imports and names imported twice, scope by scope. A module-level import is unused
    when no code reads it, counting a function's reads only where no local import shadows it."""

    def __init__(self, tree: ast.Module, comments: dict[int, str], is_init: bool):
        self.comments, self.is_init = comments, is_init
        self.unused: list[dict] = []
        self.twice: list[dict] = []
        self.module_keys: dict[tuple, int] = {}
        self.scope(tree, exported=frozenset(_dunder_all(tree)))

    def scope(self, scope: ast.AST, exported: frozenset[str] = frozenset()) -> tuple[set[str], set[str]]:
        """Check ``scope``'s imports. Returns (names read here or below, names its imports bind)."""
        nodes, inner = own_code(scope)
        stmts = sorted((n for n in nodes if isinstance(n, (ast.Import, ast.ImportFrom))), key=lambda n: n.lineno)
        self._twice(stmts, module=isinstance(scope, ast.Module))
        reaching = _uses(nodes) | exported
        for fn in inner:
            below, bound = self.scope(fn)
            reaching |= below - bound
        bound_here = set()
        for stmt in stmts:
            for _, name, _ in _import_names(stmt):
                bound_here.add(name)
                last = stmt.end_lineno or stmt.lineno
                if name not in reaching and not self.is_init and not _noqa(self.comments, stmt.lineno, last, "F401"):
                    self.unused.append({"line": stmt.lineno, "name": name})
        return reaching, bound_here

    def _twice(self, stmts: list[ast.Import | ast.ImportFrom], *, module: bool) -> None:
        keys: dict[tuple, int] = {}
        names: dict[str, int] = {}
        for stmt in stmts:
            for key, _, name in _import_names(stmt):
                where = {"line": stmt.lineno, "name": name}
                if key in keys or name in names:
                    self.twice.append({**where, "first_line": keys.get(key) or names[name],
                                       "why": "imported again in the same scope"})
                elif not module and key in self.module_keys:
                    self.twice.append({**where, "first_line": self.module_keys[key],
                                       "why": "already imported by the module"})
                keys.setdefault(key, stmt.lineno)
                names.setdefault(name, stmt.lineno)
        if module:
            self.module_keys = keys


# -- locals --------------------------------------------------------------------------------------

def _targets(node: ast.AST) -> Iterator[tuple[str, int]]:
    """Local names a statement binds that a reader should use: plain assignments, walrus,
    `except ... as`, and loop variables."""
    if isinstance(node, ast.Assign):
        yield from ((t.id, node.lineno) for t in node.targets if isinstance(t, ast.Name))
    elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and isinstance(node.target, ast.Name) \
            and node.value is not None:
        yield node.target.id, node.lineno
    elif isinstance(node, ast.ExceptHandler) and node.name:
        yield node.name, node.lineno
    elif isinstance(node, (ast.For, ast.AsyncFor)):
        yield from ((t.id, node.lineno) for t in ast.walk(node.target) if isinstance(t, ast.Name))


def check_locals(fn: Function) -> list[dict]:
    """Local names bound in a function and read neither in it nor in a function nested in it."""
    params = {a.arg for a in ast.walk(fn.args) if isinstance(a, ast.arg)}
    declared: set[str] = set()
    bound: dict[str, int] = {}
    stack: list[ast.AST] = [n for n in fn.body if not isinstance(n, NESTED)]
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            declared |= set(node.names)
        for name, line in _targets(node):
            bound.setdefault(name, line)
        stack.extend(c for c in ast.iter_child_nodes(node) if not isinstance(c, NESTED))
    used = set().union(*(_reads(n) for n in ast.walk(fn)))
    if {"locals", "vars"} & used:
        return []
    skip = used | declared | params
    return [{"line": line, "name": name} for name, line in sorted(bound.items(), key=lambda x: x[1])
            if name not in skip and not name.startswith("_")]


# -- functions -----------------------------------------------------------------------------------

def complexity(fn: Function) -> int:
    """1 + each branch, loop, handler, match case, comprehension clause and extra boolean operand.
    Functions and classes nested in ``fn`` count on their own."""
    score, stack = 1, list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, BRANCHES):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            score += 1 + len(node.ifs)
        stack.extend(ast.iter_child_nodes(node))
    return score


def fully_annotated(fn: Function, is_method: bool) -> bool:
    a = fn.args
    params = a.posonlyargs + a.args + a.kwonlyargs
    static = any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in fn.decorator_list)
    if is_method and not static and params:
        params = params[1:]  # self or cls
    params += [p for p in (a.vararg, a.kwarg) if p is not None]
    if any(p.annotation is None for p in params):
        return False
    if fn.returns is None:
        return fn.name == "__init__" and bool(params)  # mypy reads such an __init__ as typed
    return True


def is_public(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def body_key(fn: Function) -> tuple[str, int] | None:
    """A hash of the function's parameters and body, docstring removed, with its size in nodes."""
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    size = sum(1 for b in body for _ in ast.walk(b))
    if size < MIN_DUPLICATE_NODES:
        return None
    parts = [ast.dump(fn.args), *(ast.dump(b) for b in body), ast.dump(fn.returns) if fn.returns else ""]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest(), size


def functions_of(tree: ast.Module) -> Iterator[tuple[Function, str, bool, bool]]:
    """(function, qualified name, is a method, is nested in a function), in source order."""
    def visit(node: ast.AST, prefix: str, parent: str) -> Iterator[tuple[Function, str, bool, bool]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, DEFS):
                q = f"{prefix}{child.name}"
                yield child, q, parent == "class", parent == "function"
                yield from visit(child, q + ".", "function")
            elif isinstance(child, ast.ClassDef):
                yield from visit(child, f"{prefix}{child.name}.", "function" if parent == "function" else "class")
            else:
                yield from visit(child, prefix, parent)
    yield from visit(tree, "", "module")


def function_rows(tree: ast.Module) -> tuple[list[dict], list[dict], list[dict]]:
    """(one row per function, unused locals, body keys for duplicate detection)."""
    rows, unused, bodies = [], [], []
    for fn, qual, is_method, nested in functions_of(tree):
        row = {"name": qual, "line": fn.lineno, "lines": (fn.end_lineno or fn.lineno) - fn.lineno + 1,
               "complexity": complexity(fn), "nested": nested}
        if not nested:
            row.update(public=is_public(fn.name), annotated=fully_annotated(fn, is_method))
        rows.append(row)
        unused += [{**u, "function": qual} for u in check_locals(fn)]
        key = body_key(fn)
        if key:
            bodies.append({"key": key[0], "nodes": key[1], "name": qual, "line": fn.lineno})
    return rows, unused, bodies


# -- statements ----------------------------------------------------------------------------------

def is_mutable(node: ast.AST) -> bool:
    if isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    if isinstance(node, ast.Call):
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        return name in MUTABLE_CALLS
    return False


def _broad(t: ast.AST | None) -> bool:
    names = t.elts if isinstance(t, ast.Tuple) else [t]
    return any(isinstance(n, ast.Name) and n.id in ("Exception", "BaseException") for n in names)


def check_handler(node: ast.ExceptHandler, comments: dict[int, str]) -> dict | None:
    """A bare or broad handler, and whether a comment or a re-raise explains it."""
    if node.type is None:
        return {"line": node.lineno, "bare": True, "explained": False}
    if not _broad(node.type):
        return None
    first_body = node.body[0].lineno if node.body else node.lineno
    commented = any(n in comments for n in range(node.lineno, first_body + 1))
    stack: list[ast.AST] = [n for n in node.body if not isinstance(n, NESTED)]
    reraised = False
    while stack and not reraised:
        n = stack.pop()
        reraised = isinstance(n, ast.Raise)
        stack.extend(c for c in ast.iter_child_nodes(n) if not isinstance(c, NESTED))
    return {"line": node.lineno, "bare": False, "explained": commented or reraised,
            "why": "re-raises" if reraised else "commented" if commented else "neither"}


def _main_lines(tree: ast.Module, rows: list[dict]) -> set[int]:
    """Lines under `if __name__ == "__main__":` or inside a function named main."""
    lines: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.If) and "'__main__'" in ast.dump(node.test) and "__name__" in ast.dump(node.test):
            lines |= set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    for r in rows:
        if r["name"].split(".")[-1] == "main":
            lines |= set(range(r["line"], r["line"] + r["lines"]))
    return lines


def _imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module]
    return []


def _mutable_defaults(node: Function | ast.Lambda) -> list[dict]:
    defaults = node.args.defaults + [d for d in node.args.kw_defaults if d is not None]
    return [{"line": d.lineno, "function": getattr(node, "name", "<lambda>")} for d in defaults if is_mutable(d)]


def _is_print(node: ast.AST) -> TypeGuard[ast.Call]:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"


def statement_findings(tree: ast.Module, rel: str, comments: dict[int, str], first: set[str],
                       rows: list[dict]) -> dict[str, list]:
    out: dict[str, list] = {"bare_excepts": [], "broad_excepts": [], "prints": [], "mutable_defaults": [],
                            "third_party": []}
    main = None if PRINT_OK.match(rel) else _main_lines(tree, rows)
    allowed = sys.stdlib_module_names | first | {"__future__"} if rel.startswith(RUNTIME) else None
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            h = check_handler(node, comments)
            if h:
                out["bare_excepts" if h.pop("bare") else "broad_excepts"].append(h)
        elif isinstance(node, (*DEFS, ast.Lambda)):
            out["mutable_defaults"] += _mutable_defaults(node)
        elif main is not None and _is_print(node) and node.lineno not in main:
            out["prints"].append({"line": node.lineno})
        elif allowed is not None and isinstance(node, (ast.Import, ast.ImportFrom)):
            out["third_party"] += [{"line": node.lineno, "module": m} for m in _imported_modules(node)
                                   if m.split(".")[0] not in allowed]
    return out


# -- one file, and the tree ----------------------------------------------------------------------

def analyse_file(path: Path, rel: str, first: set[str]) -> dict:
    data = path.read_bytes()
    rep: dict = {"path": rel, "lines": data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
                 "cr_characters": data.count(b"\r"), "trailing_whitespace": trailing_whitespace(data)}
    try:
        text = data.decode("utf-8")
        tree = ast.parse(text, filename=rel)
    except (UnicodeDecodeError, SyntaxError, ValueError) as exc:
        rep["unparsable"] = f"{type(exc).__name__}: {exc}"
        return rep
    comments = comments_of(text)
    imports = ImportCheck(tree, comments, path.name == "__init__.py")
    rows, unused_locals, bodies = function_rows(tree)
    rep.update(functions=rows, unused_imports=imports.unused, duplicate_imports=imports.twice,
               unused_locals=unused_locals, bodies=bodies,
               markers=[{"line": n, "text": c.strip()[:120]} for n, c in sorted(comments.items()) if MARKER.search(c)])
    rep.update(statement_findings(tree, rel, comments, first, rows))
    return rep


def _in_code(path: str) -> bool:
    return not path.startswith("tests/")


def duplicate_groups(files: list[dict]) -> list[list[dict]]:
    groups: dict[str, list[dict]] = {}
    for f in files:
        for b in f.pop("bodies", []):
            groups.setdefault(b["key"], []).append({"path": f["path"], "name": b["name"], "line": b["line"],
                                                    "nodes": b["nodes"]})
    dups = [g for g in groups.values() if len(g) > 1]
    return sorted(dups, key=lambda g: (-len(g) * g[0]["nodes"], g[0]["path"]))


def _package_is(pkg: str) -> Callable[[str], bool]:
    return lambda path: path.split("/")[0] == pkg


def annotation_table(files: list[dict]) -> dict:
    by_file = {}
    for f in files:
        public = [fn for fn in f.get("functions", []) if fn.get("public")]
        by_file[f["path"]] = {"public": len(public), "annotated": sum(fn["annotated"] for fn in public),
                              "missing": [fn["name"] for fn in public if not fn["annotated"]]}

    def total(pred: Callable[[str], bool]) -> dict:
        rows = [a for p, a in by_file.items() if pred(p)]
        pub, ok = sum(a["public"] for a in rows), sum(a["annotated"] for a in rows)
        return {"public": pub, "annotated": ok, "percent": round(100 * ok / pub, 1) if pub else None}

    packages = sorted({p.split("/")[0] for p in by_file})
    by_package = {pkg: total(_package_is(pkg)) for pkg in packages}
    return {"by_file": by_file, "by_package": by_package,
            "code": total(_in_code), "runtime": total(lambda p: p.startswith(RUNTIME)),
            "tests": total(lambda p: not _in_code(p))}


def _count(files: list[dict], key: str, pred: Callable[[dict], bool] = lambda x: True) -> int:
    return sum(1 for f in files for x in f.get(key, []) if pred(x))


def hygiene_counts(files: list[dict]) -> dict[str, int]:
    """The counts over every file in scope, tests included."""
    return {
        "unparsable_files": sum(1 for f in files if "unparsable" in f),
        "third_party_imports": _count(files, "third_party"),
        "bare_excepts": _count(files, "bare_excepts"),
        "mutable_defaults": _count(files, "mutable_defaults"),
        "non_lf_files": sum(1 for f in files if f["cr_characters"]),
        "unused_imports": _count(files, "unused_imports"),
        "unused_locals": _count(files, "unused_locals"),
        "duplicate_imports": _count(files, "duplicate_imports"),
        "unexplained_broad_excepts": _count(files, "broad_excepts", lambda b: not b["explained"]),
        "library_prints": _count(files, "prints"),
        "todo_markers": _count(files, "markers"),
        "trailing_whitespace_lines": _count(files, "trailing_whitespace"),
    }


def _code_only(rows: list[dict]) -> list[dict]:
    return [x for x in rows if _in_code(x["path"])]


def structure_counts(files: list[dict], report: dict) -> dict[str, int]:
    """The counts over the code outside tests/."""
    missing = sum(len(a["missing"]) for p, a in report["annotation"]["by_file"].items() if _in_code(p))
    groups = [_code_only(g) for g in report["duplicates"]]
    return {
        "unannotated_public_functions": missing,
        "long_functions": len(_code_only(report["long_functions"])),
        "complex_functions": len(_code_only(report["complex_functions"])),
        "large_modules": sum(1 for f in _code_only(files) if f["lines"] > MAX_MODULE_LINES),
        "duplicate_bodies": sum(len(g) - 1 for g in groups if g),  # the copies beyond the first
    }


def analyse(root: Path) -> dict:
    root = Path(root)
    first = first_party(root)
    files = [analyse_file(p, p.relative_to(root).as_posix(), first) for p in iter_files(root)]
    fns = [{"path": f["path"], **fn} for f in files for fn in f.get("functions", [])]
    report: dict = {
        "schema": REPORT_SCHEMA, "root": str(root),
        "summary": {"files": len(files), "lines": sum(f["lines"] for f in files),
                    "code_lines": sum(f["lines"] for f in files if _in_code(f["path"])),
                    "test_lines": sum(f["lines"] for f in files if not _in_code(f["path"])),
                    "functions": len(fns)},
        "duplicates": duplicate_groups(files),
        "annotation": annotation_table(files),
        "long_functions": sorted((x for x in fns if x["lines"] > MAX_FUNCTION_LINES), key=lambda x: -x["lines"]),
        "complex_functions": sorted((x for x in fns if x["complexity"] > MAX_COMPLEXITY),
                                    key=lambda x: -x["complexity"]),
        "large_modules": sorted(({"path": f["path"], "lines": f["lines"]} for f in files
                                 if f["lines"] > MAX_MODULE_LINES), key=lambda x: -x["lines"]),
    }
    report["counts"] = hygiene_counts(files) | structure_counts(files, report)
    report["files"] = files
    return report


# -- ruff and mypy, when available ---------------------------------------------------------------

def qa_python() -> tuple[str | None, str]:
    """The interpreter that has ruff and mypy, and where it came from."""
    env = os.environ.get(QA_PYTHON_ENV)
    if env:
        return env, QA_PYTHON_ENV
    import importlib.util

    if importlib.util.find_spec("ruff") or importlib.util.find_spec("mypy"):
        return sys.executable, "this interpreter"
    return None, ""


def tool_version(py: str, module: str) -> str | None:
    try:
        proc = subprocess.run([py, "-m", module, "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"\d+\.\d+(\.\d+)?", proc.stdout or "")
    return m.group(0) if proc.returncode == 0 and m else None


def _relative(name: str, root: Path) -> str:
    p = Path(name)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return p.as_posix()
    return p.as_posix()


def run_ruff(py: str, root: Path) -> dict:
    version = tool_version(py, "ruff")
    if version is None:
        return {"measured": False, "reason": "not measured: ruff not installed"}
    paths = [p for p in RUFF_PATHS if (root / p).exists()]
    cmd = [py, "-m", "ruff", "check", *paths, *RUFF_ARGS, "--output-format", "json", "--no-cache", "--exit-zero"]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=600)
    try:
        findings = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        reason = f"not measured: no JSON from ruff ({proc.stderr[-200:]})"
        return {"measured": False, "version": version, "reason": reason}
    return {"measured": True, "version": version, "command": " ".join(["ruff", "check", *paths, *RUFF_ARGS]),
            "count": len(findings), "by_code": dict(Counter(f.get("code") or "syntax" for f in findings).most_common()),
            "findings": [{"path": _relative(f["filename"], root), "line": f["location"]["row"], "code": f.get("code"),
                          "message": f.get("message")} for f in findings]}


def parse_mypy(stdout: str) -> list[dict]:
    matches = (MYPY_LINE.match(line.strip()) for line in (stdout or "").splitlines())
    return [{"path": m["path"].replace("\\", "/"), "line": int(m["line"]), "code": m["code"] or "misc",
             "message": m["msg"]} for m in matches if m]


def mypy_command(py: str, root: Path, strict: bool) -> list[str]:
    """mypy on the runtime packages, or `--strict` on kernel/, with no config file and a cache
    outside the repository."""
    paths = ["kernel"] if strict else [p for p in MYPY_PATHS if (root / p).exists()]
    name = "rihma-quality-mypy-strict" if strict else "rihma-quality-mypy"
    flags = [*MYPY_ARGS, *(["--strict"] if strict else [])]
    return [py, "-m", "mypy", *paths, *flags, "--cache-dir", str(Path(tempfile.gettempdir()) / name)]


def run_mypy(py: str, root: Path, *, strict: bool = False) -> dict:
    version = tool_version(py, "mypy")
    if version is None:
        return {"measured": False, "reason": "not measured: mypy not installed"}
    cmd = mypy_command(py, root, strict)
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=1200)
    errors = parse_mypy(proc.stdout)
    if proc.returncode not in (0, 1) or (proc.returncode == 1 and not errors):
        tail = (proc.stderr or proc.stdout or "")[-300:]
        return {"measured": False, "version": version, "reason": f"not measured: mypy exit {proc.returncode} ({tail})"}
    shown = ["mypy"] + [a or '""' for a in cmd[3:cmd.index("--cache-dir")]]
    return {"measured": True, "version": version, "strict": strict, "seconds": round(time.monotonic() - started, 1),
            "command": " ".join(shown), "count": len(errors), "files": len({e["path"] for e in errors}),
            "by_code": dict(Counter(e["code"] for e in errors).most_common()), "errors": errors}


def external(root: Path, *, strict: bool = False) -> dict:
    py, source = qa_python()
    if py is None:
        reason = "not measured: ruff/mypy not installed"
        return {"python": None, "ruff": {"measured": False, "reason": reason},
                "mypy": {"measured": False, "reason": reason}}
    out = {"python": py, "source": source, "ruff": run_ruff(py, root), "mypy": run_mypy(py, root)}
    if strict:
        out["mypy_strict"] = run_mypy(py, root, strict=True)
    return out


def external_counts(ext: dict) -> tuple[dict[str, int], dict[str, str]]:
    """(counts, tool versions) from what ruff and mypy measured."""
    counts, versions = {}, {}
    for key, name in (("ruff_findings", "ruff"), ("mypy_errors", "mypy"), ("mypy_strict_kernel_errors", "mypy_strict")):
        r = ext.get(name) or {}
        if r.get("measured"):
            counts[key] = r["count"]
            versions[name.split("_")[0]] = r["version"]
    return counts, versions


# -- the gate ------------------------------------------------------------------------------------

def _tool_of(key: str) -> str | None:
    return "mypy" if key.startswith("mypy") else "ruff" if key.startswith("ruff") else None


def gate(counts: dict, versions: dict, baseline: dict | None) -> dict:
    """Hard rules, then the ratchet against the baseline."""
    result: dict = {"failures": [], "lowered": [], "not_measured": []}
    result["failures"] += [f"hard rule {k}: {counts[k]} (must be 0)" for k in HARD if counts.get(k, 0) > 0]
    if baseline is None:
        result["failures"].append("no baseline: run `python tools/quality.py --write-baseline` and commit it")
    held, tools = (baseline or {}).get("counts", {}), (baseline or {}).get("tools", {})
    for key in (k for k in RATCHET + EXTERNAL if k in held):
        tool = _tool_of(key)
        if key not in counts:
            result["not_measured"].append(key)
        elif tool and tools.get(tool) != versions.get(tool):
            result["not_measured"].append(f"{key} ({tool} {versions.get(tool)}; the baseline's is {tools.get(tool)})")
        elif counts[key] > held[key]:
            result["failures"].append(f"{key}: {counts[key]}, above its baseline {held[key]}")
        elif counts[key] < held[key]:
            result["lowered"].append(f"{key}: {counts[key]}, below its baseline {held[key]}; lower the baseline")
    result["passed"] = not result["failures"]
    return result


def read_baseline(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def write_baseline(path: Path, counts: dict, versions: dict, previous: dict | None) -> dict:
    held = dict(counts)
    for key in EXTERNAL:  # a tool not measured now keeps its count, so a machine without ruff never drops it
        if key not in held and previous and key in previous.get("counts", {}):
            held[key] = previous["counts"][key]
    doc = {"schema": BASELINE_SCHEMA,
           "note": "Counts the gate holds (tools/quality.py --gate). Lower a count when it falls; raise one "
                   "only with a reason in the commit message.",
           "thresholds": {"function_lines": MAX_FUNCTION_LINES, "complexity": MAX_COMPLEXITY,
                          "module_lines": MAX_MODULE_LINES},
           "tools": {**(previous or {}).get("tools", {}), **versions},
           "counts": {k: held[k] for k in HARD + RATCHET + EXTERNAL if k in held}}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(doc, indent=2) + "\n")
    return doc


# -- the readable summary ------------------------------------------------------------------------

def _pct(a: dict) -> str:
    return "-" if a["percent"] is None else f"{a['annotated']}/{a['public']} {a['percent']}%"


def _file_findings(f: dict) -> int:
    n = sum(len(f.get(k, [])) for k in FINDINGS) + len(f["trailing_whitespace"])
    return n + sum(1 for b in f.get("broad_excepts", []) if not b["explained"])


def render_files(report: dict) -> list[str]:
    out = ["Per file: lines, functions, annotated/public, over 60 lines, over complexity 15, findings"]
    for f in report["files"]:
        a = report["annotation"]["by_file"].get(f["path"], {"public": 0, "annotated": 0})
        fns = f.get("functions", [])
        flags = ("  UNPARSABLE" if "unparsable" in f else "") + ("  CR" if f["cr_characters"] else "")
        out.append(f"  {f['path']:<34} {f['lines']:>5} {len(fns):>4}  {a['annotated']:>3}/{a['public']:<3} "
                   f"{sum(fn['lines'] > MAX_FUNCTION_LINES for fn in fns):>3} "
                   f"{sum(fn['complexity'] > MAX_COMPLEXITY for fn in fns):>3} {_file_findings(f):>4}{flags}")
    out += ["", "Annotation coverage by package (public functions and methods fully annotated):"]
    out += [f"  {pkg:<20} {_pct(a)}" for pkg, a in report["annotation"]["by_package"].items()]
    out.append(f"  {'runtime packages':<20} {_pct(report['annotation']['runtime'])}   "
               f"all code but tests {_pct(report['annotation']['code'])}")
    return out


def render_structure(report: dict) -> list[str]:
    out: list[str] = []
    for title, rows in ((f"Functions over {MAX_FUNCTION_LINES} lines", report["long_functions"]),
                        (f"Functions over complexity {MAX_COMPLEXITY}", report["complex_functions"])):
        out += ["", f"{title} ({len(rows)}):"]
        out += [f"  {r['path']}:{r['line']} {r['name']}: {r['lines']} lines, complexity {r['complexity']}"
                for r in rows]
    out += ["", f"Modules over {MAX_MODULE_LINES} lines: "
            + (", ".join(f"{m['path']} ({m['lines']})" for m in report["large_modules"]) or "none")]
    out += ["", f"Duplicated function bodies ({len(report['duplicates'])} groups):"]
    out += [f"  {g[0]['nodes']} nodes: " + ", ".join(f"{m['path']}:{m['line']} {m['name']}" for m in g)
            for g in report["duplicates"]]
    return out


LISTINGS: tuple[tuple[str, str, Callable[[dict], str]], ...] = (
    ("Unused imports", "unused_imports", lambda x: x["name"]),
    ("Unused local variables", "unused_locals", lambda x: f"{x['name']} in {x['function']}"),
    ("Names imported twice", "duplicate_imports", lambda x: f"{x['name']} ({x['why']}, line {x['first_line']})"),
    ("Broad excepts with neither a comment nor a re-raise", "broad_excepts", lambda x: "except Exception"),
    ("print() in library code", "prints", lambda x: "print()"),
    ("Mutable default arguments", "mutable_defaults", lambda x: x["function"]),
    ("Bare excepts", "bare_excepts", lambda x: "except:"),
    ("Third-party imports in a runtime package", "third_party", lambda x: x["module"]),
    ("TODO and FIXME markers", "markers", lambda x: x["text"]),
)


def render_findings(report: dict) -> list[str]:
    out: list[str] = []
    for title, key, fmt in LISTINGS:
        rows = [f"  {f['path']}:{x['line']} {fmt(x)}" for f in report["files"] for x in f.get(key, [])
                if key != "broad_excepts" or not x["explained"]]
        out += ["", f"{title} ({len(rows)}):"] + rows
    ws = [f"{f['path']} ({len(f['trailing_whitespace'])})" for f in report["files"] if f["trailing_whitespace"]]
    cr = [f["path"] for f in report["files"] if f["cr_characters"]]
    return out + ["", "Trailing whitespace: " + (", ".join(ws) or "none"),
                  "CR line endings: " + (", ".join(cr) or "none")]


def render_external(report: dict) -> list[str]:
    out: list[str] = [""]
    for name, r in (report.get("external") or {}).items():
        if not isinstance(r, dict):
            continue
        top = ", ".join(f"{k} {v}" for k, v in list(r.get("by_code", {}).items())[:8])
        out.append(f"{name} {r['version']}: {r['count']} ({top})" if r.get("measured") else f"{name}: {r['reason']}")
    return out


def render_counts(report: dict) -> list[str]:
    held = (report.get("baseline") or {}).get("counts", {})
    out = ["", "Counts:"]
    for key in (k for k in HARD + RATCHET + EXTERNAL if k in report["counts"]):
        base = f" (baseline {held[key]})" if key in held else ""
        out.append(f"  {'hard   ' if key in HARD else 'ratchet'} {key:<30} {report['counts'][key]}{base}")
    g = report.get("gate")
    if g:
        out += ["", "GATE PASSED" if g["passed"] else "GATE FAILED"]
        out += [f"  FAIL {x}" for x in g["failures"]] + [f"  lower {x}" for x in g["lowered"]]
        out += [f"  not measured: {x}" for x in g["not_measured"]]
    return out


def render(report: dict) -> str:
    s = report["summary"]
    head = [f"Rihma code quality: {s['files']} files, {s['lines']} lines ({s['code_lines']} code, "
            f"{s['test_lines']} tests), {s['functions']} functions, measured in {report.get('seconds', '?')} s", ""]
    return "\n".join(head + render_files(report) + render_structure(report) + render_findings(report)
                     + render_counts(report))


# -- prompt sizes on a fake project ---------------------------------------------------------------

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class PromptSizes:
    """Every model-facing text, measured on a realistic project built with tests/factory_fakes.py:
    characters, and tokens approximated as characters / 4. A prompt that cannot be built here is
    reported as not measured, never guessed."""

    def __init__(self, root: Path):
        self.root = root
        self.rows: list[dict] = []

    def add(self, name: str, where: str, text: str | None, note: str = "") -> None:
        size = None if text is None else len(text)
        self.rows.append({"prompt": name, "where": where, "chars": size,
                          "tokens": None if size is None else round(size / 4), "note": note})

    def build(self, name: str, where: str, make: Callable[[], str]) -> None:
        try:
            self.add(name, where, make())
        except Exception as exc:  # a prompt that cannot be built here is not measured, never guessed
            self.add(name, where, None, f"not measured: {type(exc).__name__}: {exc}"[:200])

    def surface(self) -> None:
        from kernel import lanes

        g = self.root / ".gnomon"
        init = lanes.scaffold_system_md()
        self.add("Gnomon init prompt (prefix of both lanes)", "kernel/lanes.py", init)
        self.add("Analyst lane system.md", "kernel/lanes.py ANALYST_RULES", init + lanes.ANALYST_RULES)
        self.add("Product lane system.md", "kernel/lanes.py PRODUCT_RULES", init + lanes.PRODUCT_RULES)
        self.add("Factory's own system.md", ".gnomon/system.md", (g / "system.md").read_text(encoding="utf-8"))
        tools = (g / "tools.toml").read_text(encoding="utf-8")
        self.add("Tool descriptions, all declared", ".gnomon/tools.toml",
                 "\n".join(re.findall(r'^description = "(.*)"$', tools, re.MULTILINE)))
        m = re.search(r'^continue_message = "(.*)"$', (g / "config.toml").read_text(encoding="utf-8"), re.MULTILINE)
        self.add("[turn] continue_message", ".gnomon/config.toml", m.group(1) if m else None)

    def stages(self, project: Any, model: Any) -> dict:
        from kernel.compile import author_holdouts, compile_project
        from kernel.intake import intake
        from kernel.spec import make_spec, spec_prompt

        intake(project, IDEA, model=model, requested_by="Aino")
        for _, text in model.calls:
            who = re.search(r"You are the \*\*(\w+)\*\* perspective", text)
            label = f"Intake perspective: {who.group(1)}" if who else "Intake opinions"
            self.add(label, "kernel/intake.py", text)
        model.calls.clear()
        make_spec(project, model=model)
        self.add("Spec", "kernel/spec.py spec_prompt", model.calls[0][1] if model.calls else None)
        self.build("Spec, redrafted after a rejected plan", "kernel/spec.py spec_prompt(feedback)",
                   lambda: spec_prompt(project, "The approver must be optional."))
        model.calls.clear()
        contract = compile_project(project)
        author_holdouts(project, model=model)
        self.add("Holdout scenarios", "kernel/compile.py holdout_prompt", model.calls[0][1] if model.calls else None)
        return contract

    def per_task(self, project: Any, contract: dict) -> None:
        from kernel.change import amend_prompt, triage_prompt
        from kernel.dispatch import envelope
        from kernel.gate import verifier_prompt

        base, spec = "0" * 40, project.read("spec.json")
        self.build("Builder envelope, T-001", "kernel/dispatch.py envelope",
                   lambda: envelope(project, contract, "T-001", base=base))
        self.build("Builder envelope, a repair round", "kernel/dispatch.py envelope(round_no=1)",
                   lambda: envelope(project, contract, "T-001", base=base, round_no=1,
                                    objections=["fail_first: no test fails at base", "tests: 1 failing"]))
        self.build("Verifier", "kernel/gate.py verifier_prompt", lambda: verifier_prompt(contract, "T-001", base))
        self.build("Triage", "kernel/change.py triage_prompt", lambda: triage_prompt(
            spec, "Adding an item with an empty name crashes, and the list should be sorted by name.", "end_user"))
        self.build("Amend", "kernel/change.py amend_prompt", lambda: amend_prompt(
            spec, {"class": "change_request", "source": "business_owner", "text": "The approver should be optional."}))

    def chats(self, factory: Any, project: Any) -> None:
        from kernel import assistant, embeds, signals

        q = "Where do I approve the plan, and what is waiting on me?"
        ui = {"widgets": ["now", "health", "queue", "evidence", "timeline", "live", "costs", "lessons"],
              "layout": [{"widget": w, "size": "M", "view": "list"} for w in ("now", "health", "queue", "evidence")]}

        def ask(layout: dict | None) -> str:
            return str(assistant.prompt(q, assistant.snapshot(factory, project=project), persona="product_owner",
                                        view="decide", hints=assistant.find_in_map(q), ui=layout))

        self.build("Cockpit assistant", "kernel/assistant.py prompt", lambda: ask(None))
        self.build("Cockpit assistant, with a layout", "kernel/assistant.py prompt(ui)", lambda: ask(ui))
        e = {"kind": "feedback", "brief": "Track who borrowed the team's drills and laptops, and when they come back."}
        history = [{"role": "person", "text": "The list did not load this morning."},
                   {"role": "assistant", "text": "Sorry about that. Which page were you on, and what did you see?"},
                   {"role": "person", "text": "The loans page. It showed an error 500."}]
        self.build("Embed reply", "kernel/embeds.py _reply_prompt",
                   lambda: embeds._reply_prompt(e, "Equipment loans", history))
        self.build("Signal concept", "kernel/signals.py _concept_prompt",
                   lambda: signals._concept_prompt("We need a way to book the meeting rooms.", factory.projects()))

    def measure(self) -> dict:
        import shutil

        for p in (str(self.root / "tests"), str(self.root)):
            if p not in sys.path:
                sys.path.insert(0, p)
        from factory_fakes import script

        from kernel.model import FakeModel
        from kernel.store import Factory, FixedClock

        self.surface()
        tmp = Path(tempfile.mkdtemp(prefix="rihma-prompts-"))
        try:
            factory = Factory(tmp / "home", clock=FixedClock())
            project = factory.new_project("Equipment loans", mode="assume", maturity="demo")
            self.per_task(project, self.stages(project, FakeModel(script)))
            self.chats(factory, project)
        except Exception as exc:  # the rest of the chain is not measured; what was measured stays
            self.add("(the chain stopped here)", "", None, f"not measured: {type(exc).__name__}: {exc}"[:200])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return {"schema": "rihma.prompt_sizes/1", "tokens": "approximate: characters / 4", "rows": self.rows}


def render_prompts(doc: dict) -> str:
    out = [f"{'prompt':<44} {'chars':>7} {'~tokens':>8}  where", ""]
    for r in doc["rows"]:
        chars, tokens = ("-", "-") if r["chars"] is None else (str(r["chars"]), str(r["tokens"]))
        note = f"  ({r['note']})" if r["note"] else ""
        out.append(f"{r['prompt']:<44} {chars:>7} {tokens:>8}  {r['where']}{note}")
    return "\n".join(out)


# -- the command line ----------------------------------------------------------------------------

def measure(args: argparse.Namespace) -> dict:
    root = Path(args.root).resolve()
    baseline_path = Path(args.baseline) if args.baseline else root / "tools" / "quality_baseline.json"
    started = time.monotonic()
    report = analyse(root)
    ext = {} if args.no_external else external(root, strict=args.mypy_strict)
    if ext:
        report["external"] = ext
    ext_counts, versions = external_counts(ext)
    report["counts"].update(ext_counts)
    baseline = read_baseline(baseline_path)
    if args.write_baseline:
        baseline = write_baseline(baseline_path, report["counts"], versions, baseline)
    report["baseline"] = baseline
    if args.gate or args.write_baseline:
        report["gate"] = gate(report["counts"], versions, baseline)
    report["seconds"] = round(time.monotonic() - started, 2)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rihma's code-quality report and gate (FR-O8-AC-5).")
    parser.add_argument("--root", default=str(ROOT), help="the repository to measure")
    parser.add_argument("--baseline", default=None, help="default: <root>/tools/quality_baseline.json")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--gate", action="store_true", help="apply the hard rules and the ratchet; exit 1 on failure")
    parser.add_argument("--write-baseline", action="store_true", help="record today's counts as the baseline")
    parser.add_argument("--no-external", action="store_true", help="skip ruff and mypy")
    parser.add_argument("--mypy-strict", action="store_true", help="also count mypy --strict errors on kernel/")
    parser.add_argument("--prompts", action="store_true", help="measure the model-facing prompts on a fake project")
    args = parser.parse_args(argv)
    try:
        if args.prompts:
            doc = PromptSizes(Path(args.root).resolve()).measure()
            print(json.dumps(doc, indent=2) if args.json else render_prompts(doc))
            return 0
        report = measure(args)
    except Exception as exc:  # a bug in this tool, never a verdict on the code
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return 1 if args.gate and not report["gate"]["passed"] else 0


if __name__ == "__main__":
    sys.exit(main())
