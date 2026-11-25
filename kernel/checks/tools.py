"""Running a tool in a project's workspace for a check: bounded, with a time limit, isolated when access is
enforced (kernel/console_run.py), its output read back for the check and never recorded whole."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from kernel import console_run as crun
from kernel.checks import Ctx

OUT_LIMIT = 2 * 1024 * 1024


@dataclass
class Ran:
    """How a tool ran: its exit code (None: it did not start or ran out of time), output and why."""

    code: int | None
    out: str
    why: str = ""

    def tail(self, n: int = 6) -> list[str]:
        return [line for line in self.out.strip().splitlines() if line.strip()][-n:]


def run_tool(ctx: Ctx, argv: list[str], *, timeout: int | None = None, shell: bool = False) -> Ran:
    """``argv`` in the workspace, stdin closed; every process it starts is stopped at its end."""
    from kernel.access_isolation import IsolationRequired
    from kernel.adopt import _run
    from kernel.console import _env

    cwd, kind = ctx.workspace()
    env = _env(ctx.project)
    env["PATH"] = ctx.environ.get("PATH", env.get("PATH", ""))
    if shell:
        from kernel.console import command_plan

        plan = command_plan(ctx.project, argv[0], cwd, kind, shell=True)
        plan.env = env
    else:
        argv = [sys.executable if argv[0] in ("python", "python3", "py") else argv[0], *argv[1:]]
        plan = crun.Plan(argv=list(argv), cwd=cwd, env=env, display=" ".join(argv), workspace=kind)
    try:
        plan = crun.isolate(plan)
    except IsolationRequired as exc:
        return Ran(None, "", f"not measured: {exc}")
    limit = timeout or ctx.timeout
    try:
        code, out, err = _run(plan.argv, cwd=plan.cwd, env=plan.env, timeout=limit)
    except subprocess.TimeoutExpired:
        if plan.stop_argv:
            subprocess.run(plan.stop_argv, capture_output=True, timeout=60, check=False)
        return Ran(None, "", f"not measured: it did not finish in {limit} s")
    except OSError as exc:
        return Ran(None, "", f"not measured: {argv[0]} could not start ({exc})")
    finally:
        if plan.scrub is not None and (plan.scrub / ".git").is_dir():
            from kernel import git_guard

            git_guard.scrub(plan.scrub)
    return Ran(code, (out + ("\n" + err if err.strip() else ""))[-OUT_LIMIT:])


def first_found(ctx: Ctx, *names: str) -> str | None:
    """The first of ``names`` on PATH, by its bare name (the runner finds it again where it runs)."""
    return next((n for n in names if ctx.which(n)), None)


def json_of(text: str) -> Any:
    """The JSON a tool printed, even after a line of its own talk; None when there is none."""
    import json

    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        try:
            return json.JSONDecoder().raw_decode(text[start:])[0]
        except ValueError:
            return None
