"""The gate's tests signal from an adopted project's own suites (FR-RPJ1, kernel/gate.py ``judge_change``).

A person's workspace submission is judged by unittest's discovery first. An adopted project whose tests that
discovery never finds (a pytest suite, `npm test`, `go test`) is judged instead by the commands its adoption's
baseline ran (baseline.json ``runs``), run the way the baseline ran them (kernel/adopt.py ``run_baseline``:
offline, isolated, stopped at its limit). A suite that failed at the baseline passes here when it fails no more
tests than it did then and some test passes: that is the existing behaviour, not the change's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _test_of(suite: dict[str, Any]) -> dict[str, Any] | None:
    """A baseline run as a test command kernel/adopt.py runs, or None when it does not name one."""
    cmd = [str(w) for w in suite.get("command") or []]
    if not cmd or not suite.get("ecosystem") or not suite.get("runner"):
        return None
    return {"ecosystem": suite["ecosystem"], "runner": suite["runner"], "command": cmd,
            "tool": suite.get("tool") or cmd[0]}


def _against_baseline(got: dict[str, Any], suite: dict[str, Any]) -> dict[str, Any]:
    """A failing run that fails no more tests than the baseline did, with a test passing, is no new failure."""
    if got.get("verdict") != "failed" or suite.get("verdict") != "failed":
        return got
    now, before = got.get("counts") or {}, suite.get("counts") or {}
    failed = now.get("failed") or 0
    if before and failed <= (before.get("failed") or 0) and (now.get("passed") or 0) > 0:
        return got | {"verdict": "passed", "reason": f"{failed} failing, as at the baseline: no new failure"}
    return got


def _verdict(runs: list[dict[str, Any]]) -> str:
    verdicts = {r["verdict"] for r in runs}
    return "failed" if "failed" in verdicts else "passed" if verdicts == {"passed"} else "not measured"


def signal_own_suites(repo_dir: Path, suites: list[dict[str, Any]], *, timeout: int = 600) -> Any:
    """The tests Signal from ``suites`` (baseline runs) run in ``repo_dir``; None when none names a command."""
    from kernel.adopt import run_baseline
    from kernel.gate import Signal

    runs = []
    for suite in suites:
        test = _test_of(suite)
        if test is not None:
            runs.append(_against_baseline(run_baseline(Path(repo_dir), test, timeout=timeout), suite))
    if not runs:
        return None
    native = {"own_suites": [{k: r.get(k) for k in ("command", "verdict", "counts", "exit", "reason")} for r in runs]}
    said = "; ".join(f"{' '.join(r['command'])}: {r['verdict']}" + (f" ({r['reason']})" if r.get("reason") else "")
                     for r in runs)
    return Signal("tests", _verdict(runs), native, "the project's own suite: " + said)


def tests_or_own(repo_dir: Path, tests: Any, suites: list[dict[str, Any]] | None) -> Any:
    """The unittest signal, or, when it measured nothing and the project has its own suites, theirs."""
    if tests.verdict != "not measured" or not suites:
        return tests
    return signal_own_suites(repo_dir, suites) or tests
