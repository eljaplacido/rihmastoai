"""A project's own test runs (FR-SRC1): its test roots, a mapped command run here, and results produced elsewhere.

- **Test roots.** A repository whose Python packages each keep their own tests (``pkg_a/pyproject.toml`` with
  ``pkg_a/tests``) fails under ``pytest`` run from its root: the imports resolve from each package's own folder.
  ``roots`` finds each one by rule, from the files alone: the nearest folder above a test file that holds a
  ``pyproject.toml``, ``setup.cfg``, ``setup.py``, ``pytest.ini``, ``tox.ini`` or ``conftest.py``; a test file
  with none above it belongs to the repository's root.
- **A run here.** Any command a person mapped for a root (``python -m pytest -q``, ``make test``, a project's own
  gate script), never shell syntax, runs as adoption runs a suite (kernel/adopt.py ``run_baseline``): in a
  temporary checkout of the revision read, offline, stdin closed, with a time limit, and through IT's isolation
  runner when access is enforced; only after a person in a runner's persona says yes, because it runs the
  project's own code on this machine. Its verdict comes from the exit code and the counts the output gives, or
  from a results file (JUnit XML, TAP or JSON) the command writes, when the mapping names one.
- **Results from elsewhere.** A results file produced by a run on another machine (a nightly gate on a build host)
  is imported with the time it was produced and the machine's name, signed: nothing runs here.

Every run is kept in ``native_runs.json`` (the latest 30), with its root, command, verdict, counts and cases.
"""

from __future__ import annotations

import datetime as dt
import re
import shlex
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from kernel import native_readers as nr

RUNS = "native_runs.json"
KEEP = 30
MARKERS = ("pyproject.toml", "setup.cfg", "setup.py", "pytest.ini", "tox.ini", "conftest.py")
PY_TEST = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py)$")
SKIP_DIRS = {"node_modules", ".venv", "venv", "site-packages", "build", "dist", ".tox", "__pycache__"}
SHELL = re.compile(r"[|&;<>`$(){}\\\n*?]")
PYTEST = "python -m pytest -q"


class RunRefused(PermissionError):
    """A run or an import that may not be made, or not by this person, or not without their yes."""


def roots(files: list[str]) -> list[dict[str, Any]]:
    """Each Python test root: its folder ('' for the repository's root), the command that runs it there, and how
    many test files it holds."""
    configs = {str(PurePosixPath(f).parent) if "/" in f else "" for f in files if PurePosixPath(f).name in MARKERS[:5]}
    found: dict[str, int] = {}
    for f in files:
        if not PY_TEST.search(f) or set(f.split("/")) & SKIP_DIRS:
            continue
        parts = f.split("/")[:-1]
        root = next(("/".join(parts[:k]) for k in range(len(parts), 0, -1) if "/".join(parts[:k]) in configs), "")
        found[root] = found.get(root, 0) + 1
    return [{"root": r, "runner": "pytest", "command": PYTEST, "test_files": n} for r, n in sorted(found.items())]


def root_note(found: list[dict[str, Any]]) -> str | None:
    """Why a run from the repository's root would mislead, when it would."""
    nested = [r["root"] for r in found if r["root"]]
    if not nested:
        return None
    return (f"{len(nested)} Python package(s) keep their own tests ({', '.join(nested[:6])}): pytest run from the "
            "repository's root does not find their imports, so each root runs on its own")


def argv(command: str) -> list[str]:
    """A command's words; shell syntax (pipes, redirects, variables, globs) is refused, never interpreted."""
    if not command or SHELL.search(command):
        raise RunRefused("refused: a test command is a program and its arguments, with no shell syntax")
    words = shlex.split(command)
    if not words:
        raise RunRefused("refused: the test command is empty")
    return words


def _keep(project: Any, run: dict[str, Any]) -> dict[str, Any]:
    runs = project.read(RUNS, None) or {"runs": []}
    n = (runs.get("n") or len(runs["runs"])) + 1
    run = {"id": f"RUN-{n}", **run}
    runs["runs"] = (runs["runs"] + [run])[-KEEP:]
    runs["n"] = n
    project.write(RUNS, runs)
    return run


def runs(project: Any) -> list[dict[str, Any]]:
    return (project.read(RUNS, None) or {}).get("runs") or []


def latest(project: Any) -> dict[str, dict[str, Any]]:
    """The latest run of each root (an imported file counts under the root it names, else 'imported')."""
    out: dict[str, dict[str, Any]] = {}
    for r in runs(project):
        root = r.get("root")
        out[str(root) if root is not None else "imported"] = r
    return out


def _counts_line(c: dict[str, int] | None) -> str:
    if not c:
        return "no counts"
    return ", ".join(f"{c[k]} {k}" for k in ("passed", "failed", "skipped", "errors") if c.get(k)) or "0 tests"


def line(r: dict[str, Any]) -> str:
    """One run in words: where, when, what."""
    if r.get("from") == "imported":
        when = r.get("produced_at") or "at a time not said"
        where = f"imported from {r.get('machine') or 'another machine'}, produced {when}"
    else:
        where = f"run here{' in ' + r['root'] if r.get('root') else ''} at {r.get('at')}"
    said = r.get("reason") if r.get("verdict") == "not measured" else _counts_line(r.get("counts"))
    return f"{r.get('name') or r.get('command')}: {r.get('verdict')} ({said}); {where}"


def _verdict(counts: dict[str, int] | None) -> str:
    if not counts or not (counts.get("passed") or counts.get("failed") or counts.get("errors")):
        return "not measured"
    return "failed" if counts.get("failed") or counts.get("errors") else "passed"


def import_results(project: Any, text: str, *, person: str, persona: str, fmt: str | None = None,
                   produced_at: str | None = None, machine: str | None = None, name: str | None = None,
                   root: str | None = None) -> dict[str, Any]:
    """Keep results produced elsewhere, signed, with the time they were produced and where."""
    from kernel.people import PERSONAS, is_person

    if not is_person(person) or persona not in PERSONAS:
        raise RunRefused("refused: imported results are signed by a named person in a persona")
    if produced_at:
        try:
            dt.datetime.fromisoformat(produced_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("produced_at is a date and time, such as 2026-11-26T03:00:00Z") from None
    got = nr.results(text, fmt)
    run = _keep(project, {"from": "imported", "name": (name or "imported results")[:120], "root": root,
                          "machine": (machine or "")[:120] or None, "produced_at": produced_at or None,
                          "at": project.factory.clock.stamp(), "format": got["format"], "counts": got["counts"],
                          "verdict": _verdict(got["counts"]), "cases": got["cases"][:5000],
                          "by": {"person": person, "persona": persona}})
    project.log("native_results_imported", {"run": run["id"], "name": run["name"], "machine": run["machine"],
                                            "produced_at": run["produced_at"], "counts": run["counts"],
                                            "verdict": run["verdict"], "person": person, "persona": persona})
    return {k: v for k, v in run.items() if k != "cases"} | {"cases": len(run["cases"])}


def _checkout(project: Any, tmp: Path) -> Path:
    """A temporary clone at the revision the sources are read from (an adopted project's upstream as fetched)."""
    from kernel import adopt
    from kernel.native_sources import where

    repo, rev = where(project)
    adopt._net(tmp, "clone", "-q", "-c", "core.autocrlf=false", str(Path(repo).resolve()), "w", timeout=600)
    work = tmp / "w"
    if rev.startswith("refs/"):
        adopt._net(work, "fetch", "-q", "origin", f"+{rev}:refs/heads/rihmasto-native-read", timeout=600)
        rev = "rihmasto-native-read"
    adopt._git(work, "checkout", "-q", "--detach", rev or "HEAD")
    return work


def _test(words: list[str]) -> dict[str, Any]:
    """A command as adoption runs a suite: pytest as Python's, anything else as a stated command."""
    pytest = words[:3] == ["python", "-m", "pytest"]
    return {"ecosystem": "python" if pytest else "stated", "runner": "pytest" if pytest else "stated",
            "tool": words[0], "command": words}


def _results_file(work: Path, cwd: Path, rel: str | None, got: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    """The cases and counts of the results file a run wrote (inside the checkout only), else its own counts."""
    file = (cwd / rel).resolve() if rel else None
    if file is None or not file.is_file() or work.resolve() not in file.parents:
        return [], got.get("counts")
    try:
        parsed = nr.results(file.read_text(encoding="utf-8", errors="replace"))
    except nr.SourceUnreadable as exc:
        got["reason"] = f"{got.get('reason')}; its results file: {exc}"
        return [], got.get("counts")
    return parsed["cases"], parsed["counts"]


def run(project: Any, root: str, *, person: str, persona: str, confirmed: bool, timeout: int | None = None,
        which: Callable[[str], str | None] = shutil.which) -> dict[str, Any]:
    """Run the mapped command of one test root, signed and confirmed; keep the run."""
    from kernel import adopt, adopt_stated
    from kernel.native_sources import mapped_roots
    from kernel.people import is_person

    if not is_person(person) or persona not in adopt_stated.RUNNERS:
        raise RunRefused(f"refused: a project's tests are run by a named {', '.join(adopt_stated.RUNNERS)}")
    want = next((r for r in mapped_roots(project) if r["root"] == root), None)
    if want is None:
        raise RunRefused("refused: only a test root mapped in the project's own sources is run; map its tests first")
    if not confirmed:
        raise RunRefused("refused: say yes first. " + adopt_stated.RUNS_CODE)
    test = _test(argv(want["command"]))
    with tempfile.TemporaryDirectory(prefix="gf-native-", ignore_cleanup_errors=True) as tmp:
        work = _checkout(project, Path(tmp))
        cwd = work / root if root else work
        if not cwd.is_dir():
            raise RunRefused(f"refused: {root} is not a folder at the revision read")
        got = adopt.run_baseline(cwd, test, timeout=timeout or adopt.SUITE_TIMEOUT, which=which)
        cases, counts = _results_file(work, cwd, want.get("results"), got)
    verdict = got["verdict"] if not cases else _verdict(counts)
    kept = _keep(project, {"from": "run here", "root": root, "command": want["command"], "name": want["command"],
                           "at": project.factory.clock.stamp(), "verdict": verdict, "counts": counts,
                           "exit": got.get("exit"), "reason": got.get("reason"), "tail": got.get("tail") or [],
                           "cases": cases[:5000], "by": {"person": person, "persona": persona}})
    project.log("native_tests_run", {"run": kept["id"], "root": root, "command": want["command"], "verdict": verdict,
                                     "counts": counts, "exit": got.get("exit"), "person": person, "persona": persona,
                                     "confirmed": adopt_stated.RUNS_CODE})
    return {k: v for k, v in kept.items() if k != "cases"} | {"cases": len(kept["cases"])}


def case_status(project: Any) -> dict[str, tuple[str, dict[str, Any]]]:
    """Each test case's latest status by name, with the run it came from (the newest run wins)."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for r in runs(project):
        for c in r.get("cases") or []:
            out[str(c["name"])] = (c["status"], r)
    return out


_SEGMENT = re.compile(r"[/\\.:#\s\[\]()]+")


def segments(name: str) -> list[str]:
    """A test's name in whole segments (folders, file, class, case): ``tests/test_a.py::test_b`` is tests, test_a,
    py, test_b. ``gate_law_01`` is one segment, never a part of ``gate_law_010`` (FR-SRC2)."""
    return [s for s in _SEGMENT.split(name.lower()) if s]


def _within(small: list[str], big: list[str]) -> bool:
    n = len(small)
    return bool(n) and any(big[i:i + n] == small for i in range(len(big) - n + 1))


def status_of(test: str, cases: dict[str, tuple[str, dict[str, Any]]]) -> tuple[str, dict[str, Any] | None]:
    """A named test's latest status: its exact name; else every case whose whole segments hold the test's (a file
    named holds its cases: the worst verdict wins), or a case whose segments end the test's name. Else not run."""
    if test in cases:
        return cases[test][0], cases[test][1]
    want = segments(test)
    found = [(status, r) for name, (status, r) in cases.items()
             if _within(want, segments(name)) or (segments(name) and want[-len(segments(name)):] == segments(name))]
    if not found:
        return "not run", None
    for verdict in ("failed", "passed"):
        hit = next((f for f in found if f[0] == verdict), None)
        if hit:
            return hit
    return found[0]
