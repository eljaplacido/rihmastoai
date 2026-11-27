"""Running one console command (FR-CON1): line-streamed output to a job log, a timeout and a stop.

A command runs in a process group (a job object on Windows) of its own, stdin closed, its output and errors
written line by line to the job's log as they come. There is no pseudo-terminal, on Windows or Linux: a
program that draws the whole screen or waits for keys belongs in a real terminal ("Open a terminal here",
``rihmasto shell``). When the time runs out, or a person presses Stop, every process the command started is
stopped (``kernel.adopt._stop``), and so is a container the docker CLI left behind.

With access enforced (D-0016) it runs through IT's isolation runner, as the gate's tests do: in a container
with no network, the workspace mounted at /work, or as the separate account through sudo; a Gnomon run goes
the way every Gnomon cell goes (``kernel.access_isolation.cell``). Without a usable runner it does not run
(``IsolationRequired``). A checkout a separate account ran in is scrubbed afterwards (``kernel.git_guard``).

``Jobs`` keeps the runs the cockpit started: each is a thread, with its state for the Jobs page.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kernel import access_isolation as kisolation
from kernel import job_registry

POLL = 0.1
READ_LIMIT = 64 * 1024
ENDED = ("done", "failed", "stopped", "timed_out", "not_started", "interrupted")


@dataclass
class Plan:
    """One command as it will run: its argv before any runner wraps it, where, with what, and its record."""

    argv: list[str]
    cwd: Path
    env: dict[str, str]
    display: str
    kind: str = "command"            # command, or gnomon
    shell: bool = False
    workspace: str = "working_copy"
    isolated: str | None = None
    stop_argv: list[str] = field(default_factory=list)
    scrub: Path | None = None


def _program(argv: list[str], env: dict[str, str]) -> list[str]:
    """argv with its program found on PATH as the shell finds it (npm's ``npm.cmd`` on Windows)."""
    found = shutil.which(argv[0], path=env.get("PATH")) if argv and os.sep not in argv[0] else None
    return [found or argv[0], *argv[1:]]


def _container(r: Any, plan: Plan) -> None:
    name = f"rihmasto-console-{secrets.token_hex(6)}"
    argv = plan.argv
    program = r.python if argv[0] in (sys.executable, "python", "python3") else Path(argv[0]).name
    if plan.shell:
        argv, program = ["sh", "-c", plan.display], "sh"
    plan.argv = [*r.docker_cli, "run", "--rm", "--name", name, "--network", "none", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp",
                 *kisolation._container_user(), *kisolation._bind(plan.cwd.resolve(), "/work"),
                 "--workdir", "/work", "--env", "HOME=/tmp", "--env", "PYTHONUNBUFFERED=1", str(r.image),
                 program, *argv[1:]]
    plan.stop_argv = [*r.docker_cli, "rm", "-f", name]
    plan.isolated = "container"


def isolate(plan: Plan) -> Plan:
    """The plan as it runs here: as it is (single operator), or through IT's isolation runner. Raises
    IsolationRequired when access is enforced and nothing can isolate it."""
    if plan.kind == "gnomon":
        runner = kisolation.runner(kisolation.CELL)
        plan.argv = kisolation.cell(plan.argv, plan.cwd)
        plan.isolated = runner.kind if runner is not None else None
        return plan
    runner = kisolation.runner(kisolation.SUITE)
    if runner is None:
        plan.argv = _program(plan.argv, plan.env)
        return plan
    if runner.kind == "container":
        _container(runner, plan)
        return plan
    program = runner.python if plan.argv[0] == sys.executable else plan.argv[0]
    plan.argv = [kisolation.SUDO, "-n", "-u", str(runner.account), "--", "env", "HOME=/tmp", "PYTHONUNBUFFERED=1",
                 program, *plan.argv[1:]]
    plan.isolated, plan.scrub = "os_account", plan.cwd
    return plan


def read_log(path: Path, offset: int = 0, *, ended: bool = True, limit: int = READ_LIMIT) -> tuple[str, int]:
    """The log's text from ``offset``, up to ``limit`` bytes, and where the next read starts. While the run
    goes on, only whole lines are given: a line still being written waits for the next read."""
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, int(offset)))
            data = fh.read(limit)
    except OSError:
        return "", offset
    if not ended and len(data) < limit and not data.endswith(b"\n"):
        cut = data.rfind(b"\n")
        data = data[:cut + 1] if cut >= 0 else b""
    return data.decode("utf-8", errors="replace"), offset + len(data)


def _halt(proc: subprocess.Popen[bytes], job: int | None, plan: Plan) -> None:
    from kernel.adopt import _stop

    _stop(proc, job)
    if plan.stop_argv:
        with contextlib.suppress(OSError, subprocess.SubprocessError):     # the container may be gone already
            subprocess.run(plan.stop_argv, capture_output=True, timeout=60, check=False)


def _wait(proc: subprocess.Popen[bytes], job: int | None, plan: Plan, stop: threading.Event, timeout: float,
          tick: Callable[[], None]) -> str:
    started = time.monotonic()
    state = ""
    while proc.poll() is None:
        tick()
        if stop.is_set():
            state = "stopped"
        elif time.monotonic() - started > timeout:
            state = "timed_out"
        if state:
            break
        time.sleep(POLL)
    _halt(proc, job, plan)        # whatever it started, stopped too, as adoption's runs are
    tick()
    return state or ("done" if proc.returncode == 0 else "failed")


def _footer(state: str, code: int | None, seconds: float, timeout: float) -> str:
    if state == "stopped":
        return f"[stopped by a person after {seconds:.1f} s]"
    if state == "timed_out":
        return f"[stopped: the time limit of {timeout:.0f} s ran out]"
    return f"[exit {job_registry.signed_code(code)} after {seconds:.1f} s]"


def header(plan: Plan, log_path: Path) -> None:
    """The log's first lines: the command line and where it runs."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    where = f"{plan.workspace} workspace" + (f", isolated ({plan.isolated})" if plan.isolated else "")
    with open(log_path, "ab") as log:
        log.write(f"$ {plan.display}\n[in the {where}]\n".encode())


def execute(plan: Plan, log_path: Path, *, stop: threading.Event | None = None, timeout: float = 600,
            echo: Callable[[str], None] | None = None, headed: bool = False) -> dict[str, Any]:
    """Run ``plan`` (already isolated) with its output streamed to ``log_path``, and to ``echo`` as it comes
    when given (``headed``: the log's header is written already). Returns state (done, failed, stopped,
    timed_out, not_started), exit code and seconds."""
    from kernel.adopt import _spawn

    stop = stop or threading.Event()
    started = time.monotonic()
    pos = log_path.stat().st_size if log_path.exists() else 0
    if not headed:
        header(plan, log_path)

    def tick() -> None:
        nonlocal pos
        if echo is not None:
            text, pos = read_log(log_path, pos, ended=False)
            if text:
                echo(text)

    with open(log_path, "ab") as log:
        try:
            proc, job = _spawn(plan.argv, cwd=plan.cwd, env=plan.env, out=log, err=log)
        except OSError as exc:
            log.write(f"[could not start: {exc}]\n".encode())
            log.flush()
            tick()
            return {"state": "not_started", "code": None, "seconds": 0.0, "why": str(exc)[:300]}
        job_registry.process(log_path, proc.pid)      # a cockpit that restarts can tell whether it still runs
        state = _wait(proc, job, plan, stop, timeout, tick)
        seconds = round(time.monotonic() - started, 2)
        code = job_registry.signed_code(proc.returncode) if state in ("done", "failed") else None
        log.write(("\n" + _footer(state, code, seconds, timeout) + "\n").encode())
        log.flush()
    tick()
    if plan.scrub is not None and (plan.scrub / ".git").is_dir():
        from kernel import git_guard

        git_guard.scrub(plan.scrub)
    return {"state": state, "code": code, "seconds": seconds}


class Jobs:
    """The console runs this process started: each a thread, its stop switch and how it ended."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, dict[str, Any]] = {}
        self._n = 0

    def start(self, plan: Plan, log_path: Path, *, timeout: float,
              on_end: Callable[[dict[str, Any]], None]) -> str:
        with self._lock:
            self._n += 1
            job_id = f"C-{self._n:04d}-{secrets.token_hex(2)}"
            run: dict[str, Any] = {"state": "running", "code": None, "stop": threading.Event()}
            self._runs[job_id] = run
        header(plan, log_path)                     # on disk before the answer: the run's log exists at once

        def work() -> None:
            try:
                out = execute(plan, log_path, stop=run["stop"], timeout=timeout, headed=True)
            except Exception as exc:  # a bug in one run ends that run, recorded, never the cockpit
                out = {"state": "failed", "code": None, "seconds": 0.0, "why": f"{type(exc).__name__}: {exc}"[:300]}
            try:
                job_registry.ended(log_path, out["state"], out.get("code"))   # for a cockpit that restarts (FR-NVL3)
                on_end(out)              # recorded before the run reads as ended
            finally:
                with self._lock:
                    run.update(state=out["state"], code=out.get("code"))

        threading.Thread(target=work, name=f"console-{job_id}", daemon=True).start()
        return job_id

    def at_least(self, n: int) -> None:
        """Run ids go on from ``n`` (the highest an earlier cockpit gave), never again from 1 (FR-NVL3)."""
        with self._lock:
            self._n = max(self._n, int(n))

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(job_id)
            return {"state": run["state"], "code": run["code"]} if run else {"state": "unknown", "code": None}

    def stop(self, job_id: str) -> bool:
        """Ask a run to stop; False when it is not running (ended, or not known here)."""
        with self._lock:
            run = self._runs.get(job_id)
            if run is None or run["state"] != "running":
                return False
            run["stop"].set()
            return True

    def wait(self, job_id: str, timeout: float = 30) -> dict[str, Any]:
        """Wait for a run to end (tests, the command line); its status then."""
        deadline = time.monotonic() + timeout
        while self.status(job_id)["state"] == "running" and time.monotonic() < deadline:
            time.sleep(POLL)
        return self.status(job_id)


JOBS = Jobs()
