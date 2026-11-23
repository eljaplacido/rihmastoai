"""RT-PY-SQL: a SQL statement with a value from data formatted into it, at the call that runs it.

The call: `execute`, `executemany`, `executescript`, Django's `raw`, pandas' `read_sql` and
`read_sql_query`, and SQLAlchemy's `text()`. The statement: whatever its first argument may hold,
through every binding of a name (`sql = "SELECT ..."; sql += f" AND name = '{name}'"`) and through
a module function that returns it (`cur.execute(_query(name))`). A template is an f-string, `%`,
`.format()`, `+` or `" ".join([...])`, written in place or held by a constant (`FIND_USER % name`);
its SQL keywords may sit in a constant it formats in (`f"{BASE} WHERE name = '{name}'"`).

A formatted value that cannot carry data is not reported: a constant, a placeholder list for an
IN clause (`",".join("?" * len(ids))`, `",".join("?" for _ in ids)`), or a pick from a table of
fixed values written in the source (`TABLES[kind]`).
"""

from __future__ import annotations

import ast
import re

from kernel.redteam.pyast import flatten_add, last_name, own_nodes
from kernel.redteam.pycheck import Ctx

SQL_METHODS = frozenset({"execute", "executemany", "executescript", "raw", "read_sql", "read_sql_query"})
SQL_FUNCTIONS = frozenset({"pandas.read_sql", "pandas.read_sql_query", "sqlalchemy.text", "sqlalchemy.sql.text",
                           "sqlalchemy.sql.expression.text"})
SQL_TEXT = re.compile(r"(?is)\b(?:select\b.+\bfrom|insert\s+into|update\b.+\bset\b|delete\s+from|replace\s+into|"
                      r"drop\s+(?:table|view|index)|create\s+(?:table|view|index)|alter\s+table|pragma\s)")
MAX_HELPER_DEPTH = 2

Template = tuple[list[ast.expr], list[ast.expr]]


def _fixed_table(ck: Ctx, node: ast.expr) -> bool:
    """A dict, list or tuple of fixed values written in the source."""
    value = ck.resolve(node)
    if isinstance(value, ast.Dict):
        return all(ck.literal(k) for k in value.keys if k is not None) and all(ck.literal(v) for v in value.values)
    return isinstance(value, ast.List | ast.Tuple) and ck.literal(value)


def _placeholders(ck: Ctx, node: ast.Call) -> bool:
    """`",".join("?" * n)` or `",".join("?" for _ in ids)`: placeholders for an IN list, not data."""
    arg = node.args[0]
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mult):
        return ck.literal(arg.left) or ck.literal(arg.right)
    if isinstance(arg, ast.GeneratorExp | ast.ListComp):
        return ck.literal(arg.elt)
    return ck.literal(arg)


def fixed_part(node: ast.expr, ck: Ctx) -> bool:
    """A value formatted into a statement that cannot carry data into it."""
    if ck.literal(node):
        return True
    node = ck.resolve(node)
    if ck.literal(node):
        return True
    if isinstance(node, ast.Subscript):
        return _fixed_table(ck, node.value)
    if not isinstance(node, ast.Call) or not node.args:
        return False
    if last_name(node.func) == "get" and isinstance(node.func, ast.Attribute):
        return _fixed_table(ck, node.func.value) and all(ck.literal(a) for a in node.args[1:])
    return last_name(node.func) == "join" and _placeholders(ck, node)


def _text_of(ck: Ctx, node: ast.expr) -> str:
    """The SQL text a template part contributes: a string constant, or a name standing for one."""
    value = ck.constant(node.value if isinstance(node, ast.FormattedValue) else node)
    return value if isinstance(value, str) else ""


def _is_str(ck: Ctx, node: ast.expr) -> bool:
    return isinstance(ck.constant(node), str)


def _method_template(ck: Ctx, node: ast.Call) -> Template | None:
    """`TEMPLATE.format(...)` or `" ".join([...])` on a string written in the source."""
    if not (isinstance(node.func, ast.Attribute) and _is_str(ck, node.func.value)):
        return None
    if node.func.attr == "format":
        return [node.func.value], [*node.args, *(k.value for k in node.keywords)]
    if node.func.attr == "join" and node.args and isinstance(node.args[0], ast.List | ast.Tuple):
        return list(node.args[0].elts), list(node.args[0].elts)
    return None


def template(ck: Ctx, node: ast.expr) -> Template | None:
    """(the template's parts, the values formatted into it), or None when ``node`` is not one."""
    if isinstance(node, ast.JoinedStr):
        return list(node.values), [v.value for v in node.values if isinstance(v, ast.FormattedValue)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _is_str(ck, node.left):
        return [node.left], [node.right]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        parts = flatten_add(node)
        return parts, parts
    return _method_template(ck, node) if isinstance(node, ast.Call) else None


def _helper(ck: Ctx, node: ast.expr) -> ast.AST | None:
    """The module function a call names, when the module defines it."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return ck.functions.get(node.func.id)
    return None


def _returned(ck: Ctx, value: ast.expr, depth: int) -> tuple[str, bool]:
    """What a module function a call names returns, as SQL text and whether data is formatted in."""
    fn = _helper(ck, value) if depth < MAX_HELPER_DEPTH else None
    if fn is None:
        return "", False
    inner, text, dirty = ck.within(fn), "", False
    for ret in own_nodes(fn):
        if isinstance(ret, ast.Return) and ret.value is not None:
            more, flagged = built(inner, ret.value, depth + 1)
            text, dirty = text + " " + more, dirty or flagged
    return text, dirty


def _one(ck: Ctx, value: ast.expr, depth: int) -> tuple[str, bool]:
    """The SQL text and data of one expression a statement may be."""
    shape = template(ck, value)
    if shape is not None:
        parts, holes = shape
        return "".join(_text_of(ck, p) for p in parts), any(not fixed_part(h, ck) for h in holes)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value, False
    return _returned(ck, value, depth)


def built(ck: Ctx, node: ast.expr, depth: int = 0) -> tuple[str, bool]:
    """(the SQL text, whether a value from data is formatted in) of everything ``node`` may hold."""
    text, dirty = "", False
    for value, _ in ck.values.candidates(node):
        more, flagged = _one(ck, value, depth)
        text, dirty = text + " " + more, dirty or flagged
    return text, dirty


def check_sql(ck: Ctx, call: ast.Call, q: str) -> str | None:
    method = isinstance(call.func, ast.Attribute) and call.func.attr in SQL_METHODS
    if not (method or q in SQL_FUNCTIONS) or not call.args:
        return None
    text, dirty = built(ck, call.args[0])
    return "RT-PY-SQL" if dirty and SQL_TEXT.search(text) else None
