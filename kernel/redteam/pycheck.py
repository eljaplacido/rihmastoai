"""What every Python check knows about the place it looks at: the module's imports and aliases, what
the names of the current function hold (`pybind.Values`), the function's name, the names the
enclosing assignment binds, whether a debug flag guards the code, and whether the module is a
container's entry point.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace

from kernel.redteam.pyast import FUNCTIONS, Function, aliases, qualname
from kernel.redteam.pybind import Bound, Values, bindings, module_globals


def _is_opener(node: ast.expr, names: dict[str, str], known: set[str]) -> bool:
    """`build_opener(...)`, a name already known to hold one, or `a if c else b` of those."""
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.IfExp):
            stack += [n.body, n.orelse]
        elif (isinstance(n, ast.Name) and n.id in known) or \
                (isinstance(n, ast.Call) and qualname(n.func, names) == "urllib.request.build_opener"):
            return True
    return False


def openers(tree: ast.Module, names: dict[str, str]) -> set[str]:
    """Names bound to an opener (`urllib.request.build_opener(...)`, directly or through another name
    or a conditional): their `.open()` is a network call."""
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    out: set[str] = set()
    while True:
        found = {t.id for n in assigns if _is_opener(n.value, names, out)
                 for t in n.targets if isinstance(t, ast.Name)}
        if found <= out:
            return out
        out |= found


@dataclass
class Ctx:
    names: dict[str, str]
    values: Values
    functions: dict[str, Function] = field(default_factory=dict)
    openers: set[str] = field(default_factory=set)
    entry_point: bool = False
    filename: str = ""
    scope: str = ""
    targets: tuple[str, ...] = ()
    guarded: bool = False
    module: bool = True

    @classmethod
    def of(cls, tree: ast.Module, *, entry_point: bool = False, filename: str = "") -> Ctx:
        module: dict[str, list[Bound]] = bindings(tree)
        functions = {n.name: n for n in tree.body if isinstance(n, FUNCTIONS)}
        names = aliases(tree)
        return cls(names, Values(module, {}, module_globals(tree)), functions, openers(tree, names),
                   entry_point, filename)

    def within(self, fn: ast.AST) -> Ctx:
        """The context inside function ``fn``: its own bindings, its name."""
        values = Values(self.values.module, bindings(fn), self.values.rebound)
        return replace(self, values=values, scope=getattr(fn, "name", ""), targets=(), module=False)

    def literal(self, node: ast.AST | None) -> bool:
        return self.values.literal(node)

    def resolve(self, node: ast.expr) -> ast.expr:
        return self.values.only(node)

    def constant(self, node: ast.AST) -> object:
        return self.values.constant(node)

    def falsy(self, node: ast.expr) -> bool:
        """Whether every value ``node`` may hold is a false constant (False, 0, None, "")."""
        found = self.values.candidates(node)
        return all(isinstance(v, ast.Constant) and not v.value for v, _ in found)
