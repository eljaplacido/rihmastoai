"""The governance glue: the same rules for every runner, checked after the run (D-0019, FR-HRN1).

Gnomon enforces a task's write scope and protected paths while it runs. Another harness does not, so after its run
the kernel checks, at the very revision the gate judges:

- **scope:** every path the change touches is inside the task's write scope;
- **protected:** no protected path is touched (the contract, the specs, the factory's files, `.gnomon/`), as the gate
  already checks for every cell;
- **custody:** the working copy holds nothing from the holdout custody, and the custody is not inside it;
- and then the gate's own signals: the suite, the trace, fail-first and the independent verifier.

A violation of any of them makes the combined verdict a violation, so the change never merges whatever the harness
said; the holdouts still run at acceptance, as for every change.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from kernel import git_guard
from kernel.gate import GateResult, Signal, _conclude, judge

SKIP_DIRS = {".git", ".factory-tasks", "__pycache__", "node_modules", ".venv"}
HASH_LIMIT = 4_000_000


def _glob(pattern: str) -> re.Pattern:
    """A write-scope pattern as a regular expression: ``**`` crosses folders, ``*`` and ``?`` do not."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z", re.IGNORECASE)


def in_scope(path: str, scope: list[str]) -> bool:
    name = path.replace("\\", "/").lstrip("/")
    return any(_glob(p.replace("\\", "/").lstrip("/")).match(name) for p in scope)


def changed_paths(repo_dir: Path, base: str, head: str) -> list[str]:
    """Every path a change from ``base`` to ``head`` touches (a rename is a delete and an add), read through the
    kernel's guarded git."""
    proc = subprocess.run(["git", *git_guard.flags(), "-c", "core.quotePath=false", "diff", "--name-only",
                           "--no-renames", "-z", f"{base}...{head}", "--"], cwd=repo_dir, capture_output=True,
                          env={**os.environ, **git_guard.env()}, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"git diff {base[:12]}...{head[:12]} failed in {repo_dir}: "
                           f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    return [n.decode("utf-8", "replace") for n in proc.stdout.split(b"\0") if n]


def signal_scope(repo_dir: Path, base: str, head: str, scope: list[str]) -> Signal:
    """A violation when the change writes outside the task's write scope."""
    touched = changed_paths(repo_dir, base, head)
    outside = [p for p in touched if not in_scope(p, scope)]
    native = {"scope": list(scope), "touched": len(touched), "outside": outside[:50]}
    if outside:
        return Signal("scope", "violation", native,
                      "the change writes outside the task's write scope (" + ", ".join(scope) + "): "
                      + ", ".join(outside[:10]))
    return Signal("scope", "passed", native, f"{len(touched)} path(s), every one inside " + ", ".join(scope))


def _digests(folder: Path, limit: int = 2000) -> set[str]:
    out: set[str] = set()
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = Path(root, name)
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= HASH_LIMIT:
                continue
            out.add(hashlib.sha256(path.read_bytes()).hexdigest())
            if len(out) >= limit:
                return out
    return out


def custody_problem(custody: Path, workdir: Path) -> str | None:
    """Why a working copy is not apart from the holdout custody, or None when it is."""
    custody, workdir = Path(custody).resolve(), Path(workdir).resolve()
    if custody == workdir or custody.is_relative_to(workdir) or workdir.is_relative_to(custody):
        return f"the working copy and the holdout custody overlap ({workdir})"
    if not custody.is_dir():
        return None
    held = _digests(custody)
    if held and held & _digests(workdir):
        return "a file in the working copy is the same as one in the holdout custody"
    return None


def signal_custody(custody: Path, workdir: Path) -> Signal:
    why = custody_problem(custody, workdir)
    if why:
        return Signal("custody", "violation", {"apart": False}, why)
    return Signal("custody", "passed", {"apart": True}, "the working copy holds nothing from the holdout custody")


def judge_after_run(repo_dir: Path, contract: dict[str, Any], task_id: str, base: str, head: str, *,
                    custody: Path, verifier_runner: Any = None) -> GateResult:
    """The gate for a round another harness ran: the gate's own signals, then scope and custody beside them."""
    task = next(t for t in contract["tasks"] if t["id"] == task_id)
    scope = list((task.get("scope") or {}).get("write") or [])
    result = judge(repo_dir, contract, task_id, base, head, verifier_runner=verifier_runner)
    extra = [signal_scope(repo_dir, base, head, scope), signal_custody(custody, repo_dir)]
    return _conclude(GateResult(task=task_id, base=base, head=head, signals=[*result.signals, *extra]))
