"""Jobs that outlive the cockpit's process (FR-NVL3).

The owner's acceptance run killed the cockpit while a console run was going: its child kept running, and after the
restart the console said "Nothing has run here yet", Jobs said "No jobs in this session", Ask Rihma said nothing
ran, and the next run took the same id. Now every job the cockpit starts is written down beside its log
(``<home>/jobs/jobs.json``), with its process id once it has one and how it ended once it ends. A cockpit that
starts again reads it back:

- a job that ended is shown as it ended;
- a job whose process still runs is shown running, "from before the restart", and Stop ends its whole tree;
- a job that never ended and whose process is gone is "interrupted": the cockpit restarted while it ran, so how
  it ended is not known, and it can be run again.

Job ids go on from the highest one seen, never starting again at 1. Reads never write: ends are recorded by the
thread that saw them. Standard library only.
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from kernel.store import read_json, updating_json

NAME = "jobs.json"
KEEP = 200
INTERRUPTED = "interrupted"
KEYS = ("id", "kind", "project", "args", "log", "started", "by", "what")
_NUMBER = re.compile(r"^[A-Z]-(\d+)-")


def _file(log: str | Path) -> Path:
    return Path(log).parent / NAME


def remember(job: dict[str, Any]) -> None:
    """Write a job down beside its log, as it starts (its process id or its end may be written already)."""
    row = {k: job.get(k) for k in KEYS} | {"log": str(job["log"])}
    _update(job["log"], **row)


def _update(where: str | Path, **changes: Any) -> None:
    """Change the row of the job whose log is ``where``, or add it: the thread that runs a job may say its process
    id or its end before the cockpit has written the job down."""
    with contextlib.suppress(OSError), updating_json(_file(where), []) as rows:
        row = next((r for r in rows if isinstance(r, dict) and r.get("log") == str(where)), None)
        if row is None:
            rows.append({"log": str(where), **changes})
            del rows[:-KEEP]
        else:
            row.update(changes)


def process(log: str | Path, pid: int) -> None:
    """The job's process id, once it runs: a cockpit that starts again can tell whether it still runs."""
    _update(log, pid=int(pid))


def ended(log: str | Path, state: str, code: int | None) -> None:
    """How the job ended, written by the thread that saw it end."""
    _update(log, ended={"state": state, "code": signed_code(code)})


def signed_code(code: int | None) -> int | None:
    """An exit code as a signed number: Windows' 4294967295 is -1 (a process ended from outside)."""
    return code - 2 ** 32 if isinstance(code, int) and code >= 2 ** 31 else code


def alive(pid: Any) -> bool:
    """Whether a process with this id runs now. Never sends it a signal on Windows (os.kill would end it)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def end_tree(pid: int) -> bool:
    """End a process left running from before a restart, and everything it started."""
    if not alive(pid):
        return False
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)
    return True


class Restored:
    """The runner of the jobs a cockpit found written down when it started: their state from the record."""

    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = {str(r.get("id")): r for r in rows}

    def status(self, job_id: str) -> dict[str, Any]:
        row = self._rows.get(job_id) or {}
        end = row.get("ended")
        if isinstance(end, dict):
            return {"state": end.get("state") or "unknown", "code": end.get("code")}
        if alive(row.get("pid")):
            return {"state": "running", "code": None, "orphan": True}
        return {"state": INTERRUPTED, "code": None}

    def stop(self, job_id: str) -> bool:
        row = self._rows.get(job_id) or {}
        stopped = end_tree(row["pid"]) if isinstance(row.get("pid"), int) else False
        if stopped:
            ended(row["log"], "stopped", None)
            row["ended"] = {"state": "stopped", "code": None}
        return stopped

    def wait(self, job_id: str, timeout: float = 30) -> dict[str, Any]:
        """Nothing to wait for: a restored job's state is what its record and its process say now."""
        del timeout
        return self.status(job_id)


def restored(jobs_dir: Path) -> list[dict[str, Any]]:
    """The jobs written down in ``jobs_dir``, each with a runner that tells its state (oldest first). Read when the
    cockpit starts: a job that never ended and whose process is gone is written down as interrupted."""
    rows = [r for r in (read_json(jobs_dir / NAME, []) or []) if isinstance(r, dict) and r.get("id") and r.get("log")]
    for row in rows:
        if not isinstance(row.get("ended"), dict) and not alive(row.get("pid")):
            row["ended"] = {"state": INTERRUPTED, "code": None}
            _update(row["log"], ended=row["ended"])
    runner = Restored(rows)
    return [{**r, "args": list(r.get("args") or []), "by": r.get("by") or {}, "started": r.get("started"),
             "runner": runner, "restored": True} for r in rows]


def highest(jobs: list[dict[str, Any]], prefix: str) -> int:
    """The highest number among the job ids that start with ``prefix`` (C-0007-ab12: 7)."""
    found = [int(m.group(1)) for j in jobs if str(j.get("id", "")).startswith(prefix)
             for m in [_NUMBER.match(str(j["id"]))] if m]
    return max(found, default=0)


def interrupted(home: Path) -> list[dict[str, Any]]:
    """The jobs a cockpit restart interrupted (for Ask Rihma's answers)."""
    rows = read_json(Path(home) / "jobs" / NAME, []) or []
    return [r for r in rows if isinstance(r, dict) and (r.get("ended") or {}).get("state") == INTERRUPTED]


def running_before(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The restored jobs whose process still runs: left from before the restart."""
    return [j for j in jobs if j.get("restored") and j["runner"].status(j["id"]).get("orphan")]
