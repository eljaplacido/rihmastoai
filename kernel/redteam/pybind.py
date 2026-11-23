"""What a name can hold where the Python rules read it: every binding in its scope, not the last one.

A rule asks whether a value is fixed in the source (`Values.literal`). A name is fixed only when
every binding of it in its function is fixed: a parameter, a loop target, `with ... as`, an
unpacking, an import, a `global` or a walrus whose value is not fixed make it data. `cmd += x`
adds `x` to what it holds. A name the function never binds is the module's: fixed when every
module-level binding of it is fixed and no function rebinds it with `global`. A parameter that
shadows a module constant is the parameter, and a default value (`def run(cmd=CMD)`) does not
fix it: a caller passes anything.

`Values.candidates` gives every expression a name may hold (through other names, to a fixed
depth), for the rules that read a value's shape (a SQL template built over several lines).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field

from kernel.redteam.pyast import FUNCTIONS, flatten_add, own_nodes

MAX_DEPTH = 8


@dataclass(frozen=True)
class Bound:
    """One binding: the expression bound (None when the rules cannot see it), and whether it is `+=`."""

    value: ast.expr | None
    added: bool = False


def _names_in(target: ast.AST) -> list[str]:
    return [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]


def _visible(node: ast.AST) -> list[tuple[str, Bound]] | None:
    """The bindings whose value the rules can see (assignments, `+=`, walrus), or None for another node."""
    if isinstance(node, ast.Assign):
        return [(n, Bound(node.value if isinstance(t, ast.Name) else None)) for t in node.targets
                for n in _names_in(t)]
    if isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
        return [(node.target.id, Bound(node.value))]
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        added = isinstance(node.op, ast.Add)
        return [(node.target.id, Bound(node.value if added else None, added=added))]
    if isinstance(node, ast.NamedExpr):
        return [(node.target.id, Bound(node.value))]
    return None


def _unseen_names(node: ast.AST) -> list[str]:
    """Names a node binds to values the rules cannot see: loop and `with` targets, handlers, imports,
    `global`, match captures."""
    if isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
        return _names_in(node.target)
    if isinstance(node, ast.withitem) and node.optional_vars is not None:
        return _names_in(node.optional_vars)
    if isinstance(node, ast.Import | ast.ImportFrom):
        return [(a.asname or a.name).split(".")[0] for a in node.names]
    if isinstance(node, ast.Global | ast.Nonlocal):
        return list(node.names)
    name = getattr(node, "name", None) if isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) else None
    return [name] if isinstance(name, str) else []


def _targets(node: ast.AST) -> list[tuple[str, Bound]]:
    """(name, binding) for every name one statement binds."""
    seen = _visible(node)
    return seen if seen is not None else [(n, Bound(None)) for n in _unseen_names(node)]


def _parameters(fn: ast.AST) -> list[str]:
    if not isinstance(fn, (*FUNCTIONS, ast.Lambda)):
        return []
    a = fn.args
    names = [x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs)]
    return names + [x.arg for x in (a.vararg, a.kwarg) if x is not None]


def _scope_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    if isinstance(scope, ast.Module):
        stack: list[ast.AST] = list(scope.body)
        while stack:
            node = stack.pop()
            yield node
            if not isinstance(node, (*FUNCTIONS, ast.ClassDef, ast.Lambda)):
                stack.extend(ast.iter_child_nodes(node))
        return
    yield from own_nodes(scope)


def bindings(scope: ast.AST) -> dict[str, list[Bound]]:
    """Every binding of every name in one scope (a function, or the module without its functions)."""
    out: dict[str, list[Bound]] = {name: [Bound(None)] for name in _parameters(scope)}
    for node in _scope_nodes(scope):
        if isinstance(node, (*FUNCTIONS, ast.ClassDef)):
            out.setdefault(node.name, []).append(Bound(None))
            continue
        for name, bound in _targets(node):
            out.setdefault(name, []).append(bound)
    return out


def module_globals(tree: ast.Module) -> set[str]:
    """Names some function declares `global`: any function may rebind them."""
    return {n for node in ast.walk(tree) if isinstance(node, ast.Global) for n in node.names}


@dataclass
class Values:
    """What names hold in one function (``local``) of a module (``module``)."""

    module: dict[str, list[Bound]]
    local: dict[str, list[Bound]] = field(default_factory=dict)
    rebound: set[str] = field(default_factory=set)

    def bound(self, name: str) -> list[Bound] | None:
        """The bindings that reach a use of ``name``: the function's own, else the module's."""
        if name in self.local:
            return self.local[name]
        if name in self.module and name not in self.rebound:
            return self.module[name]
        return None

    def _parts(self, node: ast.AST) -> list[ast.AST] | None:
        """The parts a composite value is fixed by (all of them must be), or None for anything else."""
        if isinstance(node, ast.JoinedStr):
            return [v.value for v in node.values if isinstance(v, ast.FormattedValue)]
        if isinstance(node, ast.List | ast.Tuple | ast.Set):
            return list(node.elts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return list(flatten_add(node))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult | ast.Mod):
            return [node.left, node.right]
        return None

    def literal(self, node: ast.AST | None, depth: int = 0) -> bool:
        """Whether ``node`` is fixed in the source: no value from data can reach it."""
        if node is None or depth > MAX_DEPTH:
            return node is None
        if isinstance(node, ast.Constant):
            return True
        parts = self._parts(node)
        if parts is not None:
            return all(self.literal(p, depth + 1) for p in parts)
        if not isinstance(node, ast.Name):
            return False
        found = self.bound(node.id)
        if not found:
            return False
        return all(b.value is not None and self.literal(b.value, depth + 1) for b in found)

    def candidates(self, node: ast.expr, depth: int = 0) -> list[tuple[ast.expr, bool]]:
        """Every expression ``node`` may hold, with whether it was added by `+=`; a name the rules cannot
        see through stays itself."""
        if not isinstance(node, ast.Name) or depth > MAX_DEPTH:
            return [(node, False)]
        found = self.bound(node.id)
        if not found:
            return [(node, False)]
        out: list[tuple[ast.expr, bool]] = []
        for b in found:
            if b.value is None:
                out.append((node, False))
            else:
                out += [(v, b.added or added) for v, added in self.candidates(b.value, depth + 1)]
        return out

    def only(self, node: ast.expr) -> ast.expr:
        """The one expression a name holds, when it is bound once to a visible value; else ``node``."""
        found = self.bound(node.id) if isinstance(node, ast.Name) else None
        if found and len(found) == 1 and found[0].value is not None and not found[0].added:
            return found[0].value
        return node

    def constant(self, node: ast.AST) -> object:
        """The constant a name (or a constant) stands for, or None."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            found = self.bound(node.id)
            if found and len(found) == 1 and isinstance(found[0].value, ast.Constant) and not found[0].added:
                return found[0].value.value
        return None
