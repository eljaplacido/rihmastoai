"""The project's own test suite, and a command of your own whose exit code decides (FR-CHK1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel.checks import Check, Ctx, not_measured, result
from kernel.checks.tools import run_tool


def _stated(ctx: Ctx) -> str | None:
    from kernel.console import settings

    line = ctx.config.get("command") or settings(ctx.project)["commands"].get("test")
    return str(line).strip() if line else None


def _by_line(ctx: Ctx, line: str, what: str) -> dict[str, Any]:
    from kernel.console import split
    from kernel.console_offers import needs_shell

    shell = needs_shell(line) or ctx.config.get("shell") is True
    argv = [line] if shell else split(line)
    if not argv:
        return not_measured(f"the {what} is empty")
    timeout = int(ctx.config.get("timeout") or ctx.timeout)
    ran = run_tool(ctx, argv, timeout=timeout, shell=shell)
    if ran.code is None:
        return not_measured(ran.why, [f"$ {line}"])
    if ran.code == 5 and any(w in line for w in ("pytest", "unittest")):
        return not_measured(f"{line}: no test ran (exit 5)", [f"$ {line}", *ran.tail()])
    verdict = "passed" if ran.code == 0 else "failed"
    return result(verdict, f"{line}: exit {ran.code}", [f"$ {line}", *ran.tail()], exit=ran.code)


def _detected(ctx: Ctx) -> dict[str, Any]:
    from kernel import adopt
    from kernel.attach import git

    root, _ = ctx.workspace()
    files = [f for f in git(root, "ls-files", "-z", check=False).split("\0") if f]
    tests = adopt.detect_tests(Path(root), files)
    if not tests:
        return not_measured("no test command was found by rule and none is stated (state one in the console's "
                            "settings, or give this check a command)")
    lines = [" ".join(t["command"]) for t in tests]
    runs = [_by_line(ctx, line, "test command") for line in lines]
    from kernel.verdicts import combine_verdicts

    verdict = combine_verdicts([r["verdict"] for r in runs])
    evidence = [e for r in runs for e in r["evidence"]]
    summary = "; ".join(r["summary"] for r in runs)
    return result(verdict if verdict in ("passed", "failed") else "not measured", summary, evidence)


def tests(ctx: Ctx) -> dict[str, Any]:
    line = _stated(ctx)
    return _by_line(ctx, line, "test command") if line else _detected(ctx)


def custom(ctx: Ctx) -> dict[str, Any]:
    line = str(ctx.config.get("command") or "").strip()
    if not line:
        return not_measured("a custom check needs a command (its exit code decides)")
    return _by_line(ctx, line, "command")


CHECKS = (
    Check("tests", "Test suite", "the project's own test suite: the stated test command, else the one found by rule",
          tests, options=("command", "timeout", "shell"), runs_code=True, every="1d"),
    Check("custom", "Custom check", "a command of your own, run in the workspace: exit 0 passes, any other fails",
          custom, options=("command", "timeout", "shell"), needs=("command",), runs_code=True),
)
