"""The Python rules: one pass over a module's syntax tree (`ast`). No code is imported or run.

Each check looks at one call or one assignment and names the rule it breaks, if any. What counts
as "built from data" is `pybind.Values.literal`'s answer: a name is fixed only when every binding
of it in its function is fixed (`cmd = "ls"` a line earlier is; `cmd += request.args["x"]`, a loop
target or a parameter is not). Request-derived paths are the dataflow heuristic in `taint.py`, SQL
is `pysql.py`, and the rules about set-up (timeouts, hashes, debug, binding, TLS) are in
`pysettings.py`.

Names are resolved through imports and aliases (`pyast.aliases`): `run = os.system`,
`getattr(os, "system")`, `__import__("os").system` and a star import are all `os.system`.

Shell commands (RT-PY-SHELL): a shell-string call (`os.system`, `os.popen`,
`asyncio.create_subprocess_shell`, ...), a subprocess call whose `shell=` is anything but a false
constant (a flag, `bool(1)`, `**{"shell": True}`), and a program list or `os.exec*` call that runs
a shell with `-c` (`["bash", "-c", cmd]`), each with a command that is not fixed. A command passed
through `shlex.quote` or `shlex.join` is fixed for the shell. A command hidden behind `*args` or
`**kwargs` is not seen, so it is reported.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import replace

from kernel.redteam import pysettings as settings
from kernel.redteam.pyast import FUNCTIONS, dotted, flatten_add, is_const, keyword, last_name, qualname
from kernel.redteam.pycheck import Ctx
from kernel.redteam.pysql import check_sql
from kernel.redteam.taint import path_hits

Hit = tuple[str, int]

SUBPROCESS = frozenset({"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output",
                        "subprocess.Popen"})
SHELL_STRING = frozenset({"os.system", "os.popen", "subprocess.getoutput", "subprocess.getstatusoutput",
                          "commands.getoutput", "commands.getstatusoutput", "platform.popen",
                          "asyncio.create_subprocess_shell"})
EXECS = frozenset({f"os.{f}" for f in ("execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
                                       "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp",
                                       "spawnvpe", "posix_spawn", "posix_spawnp")} | {"asyncio.create_subprocess_exec"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash", "fish", "csh", "tcsh", "cmd", "cmd.exe", "powershell",
                    "powershell.exe", "pwsh", "pwsh.exe"})
SHELL_FLAGS = frozenset({"-c", "/c", "/C", "/k", "/K", "-Command", "-command", "-lc", "-ic", "-ec"})
SHELL_SAFE = frozenset({"shlex.quote", "shlex.join", "pipes.quote"})
EVALS = frozenset({"eval", "exec", "builtins.eval", "builtins.exec"})
DESER = frozenset({"pickle.load", "pickle.loads", "pickle.Unpickler", "pickle._Unpickler", "pickle._load",
                   "pickle._loads", "_pickle.load", "_pickle.loads", "_pickle.Unpickler", "cPickle.load",
                   "cPickle.loads", "dill.load", "dill.loads", "dill.Unpickler", "cloudpickle.load",
                   "cloudpickle.loads", "marshal.load", "marshal.loads", "shelve.open", "jsonpickle.decode",
                   "jsonpickle.loads", "yaml.unsafe_load", "yaml.unsafe_load_all", "pandas.read_pickle",
                   "joblib.load"})
YAML_LOADS = frozenset({"yaml.load", "yaml.load_all"})
SAFE_LOADERS = ("SafeLoader", "CSafeLoader", "BaseLoader", "CBaseLoader")
MAX_DEPTH = 8
# The command a call runs, hidden behind `*args` or `**kwargs`: the rules cannot see it.
HIDDEN = ast.Starred(value=ast.Constant(None), ctx=ast.Load())


def _command(call: ast.Call, position: int, name: str) -> ast.expr | None:
    """The command a call runs (its argument at ``position`` or ``name=``), HIDDEN when `*args` or
    `**kwargs` may hold it, None when it passes none."""
    if any(isinstance(a, ast.Starred) for a in call.args[: position + 1]):
        return HIDDEN
    if len(call.args) > position:
        return call.args[position]
    found = keyword(call, name)
    return HIDDEN if found is None and any(k.arg is None for k in call.keywords) else found


def quoted(ck: Ctx, node: ast.expr, depth: int = 0) -> bool:
    """Whether a command is fixed for the shell: written in the source, or data passed through
    `shlex.quote` / `shlex.join` (whole, or in each placeholder and term)."""
    if node is HIDDEN or depth > MAX_DEPTH:
        return False
    if ck.literal(node):
        return True
    if isinstance(node, ast.Call):
        return qualname(node.func, ck.names) in SHELL_SAFE
    if isinstance(node, ast.JoinedStr):
        return all(quoted(ck, v.value, depth + 1) for v in node.values if isinstance(v, ast.FormattedValue))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return all(quoted(ck, t, depth + 1) for t in flatten_add(node))
    if isinstance(node, ast.Name):
        return all(v is not node and quoted(ck, v, depth + 1) for v, _ in ck.values.candidates(node))
    return False


def _sets_shell(ck: Ctx, node: ast.expr) -> bool:
    """`**{"shell": True}` or `**dict(shell=True)`, written there or held by a name."""
    for v, _ in ck.values.candidates(node):
        if isinstance(v, ast.Dict):
            if any(k is not None and ck.constant(k) == "shell" and not ck.falsy(val) for k, val in zip(v.keys, v.values,
                                                                                                    strict=True)):
                return True
        elif isinstance(v, ast.Call) and last_name(v.func) == "dict":
            flag = keyword(v, "shell")
            if flag is not None and not ck.falsy(flag):
                return True
    return False


def _shell_on(ck: Ctx, call: ast.Call) -> bool:
    flag = keyword(call, "shell")
    if flag is not None:
        return not ck.falsy(flag)
    return any(_sets_shell(ck, k.value) for k in call.keywords if k.arg is None)


def _argv(ck: Ctx, items: list[ast.expr]) -> bool:
    """A program list that runs a shell with `-c` and a command that is not fixed."""
    for i, item in enumerate(items):
        prog = ck.constant(item)
        if not isinstance(prog, str) or prog.replace("\\", "/").rsplit("/", 1)[-1].lower() not in SHELLS:
            continue
        for j in range(i + 1, len(items)):
            if ck.constant(items[j]) in SHELL_FLAGS:
                command = items[j + 1] if j + 1 < len(items) else None
                return command is not None and not quoted(ck, command)
        return False
    return False


def _items(ck: Ctx, node: ast.expr | None) -> list[ast.expr]:
    value = ck.resolve(node) if node is not None and node is not HIDDEN else None
    return list(value.elts) if isinstance(value, ast.List | ast.Tuple) else []


def _unquoted(ck: Ctx, cmd: ast.expr | None) -> bool:
    return cmd is not None and not quoted(ck, cmd)


def _shell(ck: Ctx, call: ast.Call, q: str) -> str | None:
    hit = False
    if q in SHELL_STRING or last_name(call.func) == "subprocess_shell":
        hit = _unquoted(ck, _command(call, 1 if last_name(call.func) == "subprocess_shell" else 0, "cmd"))
    elif q in SUBPROCESS:
        cmd = _command(call, 0, "args")
        hit = _unquoted(ck, cmd) if _shell_on(ck, call) else _argv(ck, _items(ck, cmd))
    elif q in EXECS:
        hit = _argv(ck, [e for a in call.args for e in (a.elts if isinstance(a, ast.List | ast.Tuple) else [a])])
    return "RT-PY-SHELL" if hit else None


def _eval(ck: Ctx, call: ast.Call, q: str) -> str | None:
    return "RT-PY-EVAL" if q in EVALS and call.args and not ck.literal(call.args[0]) else None


def _deser(ck: Ctx, call: ast.Call, q: str) -> str | None:
    if q in DESER:
        return "RT-PY-DESER"
    if q in YAML_LOADS:
        loader = call.args[1] if len(call.args) > 1 else keyword(call, "Loader")
        name = dotted(loader) if loader is not None else None
        return None if name and name.endswith(SAFE_LOADERS) else "RT-PY-DESER"
    if q == "torch.load" and not is_const(keyword(call, "weights_only"), True):
        return "RT-PY-DESER"
    if q == "numpy.load" and is_const(keyword(call, "allow_pickle"), True):
        return "RT-PY-DESER"
    return None


CALL_CHECKS: tuple[Callable[[Ctx, ast.Call, str], str | None], ...] = (
    _shell, _eval, _deser, check_sql, settings.timeout, settings.weak_hash, settings.mktemp, settings.debug,
    settings.bind_all, settings.tls)
ASSIGN_CHECKS: tuple[Callable[[Ctx, ast.Assign], str | None], ...] = (
    settings.debug_assign, settings.tls_assign, settings.bind_assign)


def _debug_flag(test: ast.expr) -> bool:
    """`if args.debug:`, `if DEBUG:`: a test that reads a debug flag."""
    return any("debug" in (n.id if isinstance(n, ast.Name) else n.attr).lower()
               for n in ast.walk(test) if isinstance(n, ast.Name | ast.Attribute))


def _children(node: ast.AST, ck: Ctx) -> list[tuple[ast.AST, Ctx]]:
    if isinstance(node, ast.If) and _debug_flag(node.test):
        guarded = replace(ck, guarded=True)
        return [(node.test, ck), *((n, guarded) for n in node.body), *((n, ck) for n in node.orelse)]
    return [(c, ck) for c in ast.iter_child_nodes(node)]


def _assign(node: ast.Assign, ck: Ctx, hits: set[Hit]) -> Ctx:
    """The assignment checks; the names it binds become the targets its value is judged under."""
    hits.update((rid, node.lineno) for rid in (c(ck, node) for c in ASSIGN_CHECKS) if rid)
    bound = tuple(t.id if isinstance(t, ast.Name) else t.attr for t in node.targets
                  if isinstance(t, ast.Name | ast.Attribute))
    return replace(ck, targets=ck.targets + bound)


def _check(node: ast.AST, ck: Ctx, hits: set[Hit]) -> Ctx:
    """Run the checks that apply to ``node``; returns the context its children are in."""
    if isinstance(node, FUNCTIONS):
        if not ck.entry_point and settings.host_parameter_binds_all(node):
            hits.add(("RT-PY-BINDALL", node.lineno))
        return ck.within(node)
    if isinstance(node, ast.ClassDef):
        return replace(ck, module=False, targets=())
    if isinstance(node, ast.Assign):
        return _assign(node, ck, hits)
    if isinstance(node, ast.Call):
        q = qualname(node.func, ck.names)
        hits.update((rid, node.lineno) for rid in (c(ck, node, q) for c in CALL_CHECKS) if rid)
    return ck


def check_python(tree: ast.Module, *, entry_point: bool = False, filename: str = "") -> list[Hit]:
    """Every (rule id, line) the Python rules find in one parsed module. The walk keeps no recursion:
    generated code can nest a `+` chain thousands deep."""
    root = Ctx.of(tree, entry_point=entry_point, filename=filename)
    hits: set[Hit] = set()
    stack: list[tuple[ast.AST, Ctx]] = [(tree, root)]
    while stack:
        node, ck = stack.pop()
        inner = _check(node, ck, hits)
        stack.extend(reversed(_children(node, inner)))
    hits |= {("RT-PY-PATH", line) for line in path_hits(tree, root.names)}
    return sorted(hits, key=lambda h: (h[1], h[0]))
