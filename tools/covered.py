#!/usr/bin/env python3
"""covered: line coverage of the runtime packages, standard library only.

The fallback for a machine without coverage.py. Where coverage.py is installed, prefer it:
  python -m coverage run --source=kernel,adapters,embed,mcp -m unittest discover -s tests
  python -m coverage report

This tool runs the same unittest suite in this process and records which lines ran in
kernel/, adapters/, embed/ and mcp/. On Python 3.12 and later it listens to sys.monitoring LINE
events: each line reports once and is then switched off, so the suite runs at nearly full speed.
On 3.11 it falls back to sys.settrace, which is slower.

A statement is a line where an AST statement starts and the compiler emits code; docstrings
are not statements. A statement is covered when its first line ran. Code that runs in a child
process (a product service started by a paved road, a command line started with subprocess)
is not seen, as with coverage.py's default settings.

Exit codes: 0 measured (the suite passed), 1 measured but the suite failed, 2 internal error.

Usage:
  python tools/covered.py                 the table, and the modules under 70%
  python tools/covered.py --min 80 --json
  python tools/covered.py --pattern "test_canon*.py"
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import threading
import time
import types
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("kernel", "adapters", "embed", "mcp")
REPORT_SCHEMA = "rihma.covered/1"


# -- what can run ------------------------------------------------------------------------------

def _docstrings(tree: ast.Module) -> set[int]:
    """The lines of module, class and function docstrings."""
    out: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                out.add(first.lineno)
    return out


def _code_lines(code: types.CodeType) -> set[int]:
    """Every line the compiler emitted an instruction for, in ``code`` and the code nested in it."""
    lines: set[int] = set()
    stack = [code]
    while stack:
        c = stack.pop()
        lines |= {line for _, _, line in c.co_lines() if line is not None and line > 0}
        stack += [k for k in c.co_consts if isinstance(k, types.CodeType)]
    return lines


def statements(path: Path) -> set[int]:
    """The first lines of the statements in ``path`` that the compiler emits code for."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    starts = {n.lineno for n in ast.walk(tree) if isinstance(n, ast.stmt)} - _docstrings(tree)
    return starts & _code_lines(compile(text, str(path), "exec", dont_inherit=True))


def target_files(root: Path, packages: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for pkg in packages:
        for dirpath, dirs, files in os.walk(root / pkg):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            out += [Path(dirpath) / f for f in sorted(files) if f.endswith(".py")]
    return out


def _key(filename: str) -> str:
    return os.path.normcase(os.path.abspath(filename))


# -- what ran ------------------------------------------------------------------------------------

class Recorder:
    """The lines that ran, per target file. ``start`` and ``stop`` bracket the run."""

    def __init__(self, files: list[Path]):
        self.executed: dict[str, set[int]] = {_key(str(f)): set() for f in files}
        self._seen: dict[str, set[int] | None] = {}
        self.method = "sys.monitoring" if hasattr(sys, "monitoring") else "sys.settrace"
        self._tool: int | None = None

    def _lines_of(self, filename: str) -> set[int] | None:
        if filename not in self._seen:
            self._seen[filename] = self.executed.get(_key(filename))
        return self._seen[filename]

    def start(self) -> None:
        if self.method == "sys.monitoring":
            self._start_monitoring()
        else:
            sys.settrace(self._trace)
            threading.settrace(self._trace)

    def stop(self) -> None:
        if self.method == "sys.monitoring":
            mon: Any = vars(sys)["monitoring"]  # absent before 3.12
            mon.set_events(self._tool, 0)
            mon.register_callback(self._tool, mon.events.LINE, None)
            mon.free_tool_id(self._tool)
        else:
            sys.settrace(None)
            threading.settrace(None)

    def _start_monitoring(self) -> None:
        mon: Any = vars(sys)["monitoring"]  # absent before 3.12
        for tool in (mon.COVERAGE_ID, 3, 4):  # a tool id another monitor holds is skipped
            try:
                mon.use_tool_id(tool, "rihma-covered")
            except ValueError:
                continue
            self._tool = tool
            break
        else:
            raise RuntimeError("no free sys.monitoring tool id")
        disable = mon.DISABLE

        def on_line(code: types.CodeType, line: int) -> Any:
            lines = self._lines_of(code.co_filename)
            if lines is not None:
                lines.add(line)
            return disable  # each location reports once

        mon.register_callback(self._tool, mon.events.LINE, on_line)
        mon.set_events(self._tool, mon.events.LINE)

    def _trace(self, frame: types.FrameType, event: str, arg: object) -> Callable[..., Any] | None:
        lines = self._lines_of(frame.f_code.co_filename)
        if lines is None:
            return None

        def local(frame: types.FrameType, event: str, arg: object) -> Callable[..., Any]:
            if event == "line":
                lines.add(frame.f_lineno)
            return local

        return local


# -- the run and the report ----------------------------------------------------------------------

def run_suite(tests: str, pattern: str) -> tuple[unittest.TestResult, float]:
    started = time.monotonic()
    suite = unittest.TestLoader().discover(start_dir=tests, pattern=pattern)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=0).run(suite)
    return result, time.monotonic() - started


def _ranges(lines: list[int]) -> str:
    """[1, 2, 3, 7] -> '1-3, 7'."""
    out: list[str] = []
    for n in lines:
        if out and n == int(out[-1].split("-")[-1]) + 1:
            out[-1] = f"{out[-1].split('-')[0]}-{n}"
        else:
            out.append(str(n))
    return ", ".join(out)


def _pct(covered: int, total: int) -> float:
    return round(100.0 * covered / total, 1) if total else 100.0


def table(root: Path, files: list[Path], executed: dict[str, set[int]]) -> list[dict]:
    rows = []
    for f in files:
        stmts = statements(f)
        ran = executed.get(_key(str(f)), set())
        missed = sorted(stmts - ran)
        rows.append({"path": f.relative_to(root).as_posix(), "statements": len(stmts), "missed": len(missed),
                     "percent": _pct(len(stmts) - len(missed), len(stmts)), "missing": _ranges(missed)})
    return rows


def totals(rows: list[dict], packages: tuple[str, ...]) -> dict:
    def total(sel: list[dict]) -> dict:
        n, m = sum(r["statements"] for r in sel), sum(r["missed"] for r in sel)
        return {"statements": n, "missed": m, "percent": _pct(n - m, n)}

    by_package = {p: total([r for r in rows if r["path"].startswith(p + "/")]) for p in packages}
    return {"all": total(rows), "by_package": by_package}


def measure(args: argparse.Namespace) -> dict:
    root = Path(args.root).resolve()
    packages = tuple(args.packages)
    files = target_files(root, packages)
    os.chdir(root)  # as `python -m unittest discover -s tests` runs from the repository root
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    recorder = Recorder(files)
    recorder.start()
    try:
        result, seconds = run_suite(args.tests, args.pattern)
    finally:
        recorder.stop()
    rows = table(root, files, recorder.executed)
    return {"schema": REPORT_SCHEMA, "method": recorder.method, "python": sys.version.split()[0],
            "seconds": round(seconds, 1), "tests": result.testsRun, "failures": len(result.failures),
            "errors": len(result.errors), "skipped": len(result.skipped), "suite_passed": result.wasSuccessful(),
            "minimum": args.min, "totals": totals(rows, packages), "modules": rows,
            "under_minimum": [r["path"] for r in rows if r["percent"] < args.min]}


def render(rep: dict) -> str:
    out = [f"Line coverage by {rep['method']} on Python {rep['python']}: {rep['tests']} tests in {rep['seconds']} s"
           f" ({rep['failures']} failures, {rep['errors']} errors)", "",
           f"{'module':<32} {'stmts':>6} {'miss':>5} {'cover':>6}"]
    for r in rep["modules"]:
        out.append(f"{r['path']:<32} {r['statements']:>6} {r['missed']:>5} {r['percent']:>5}%")
    t = rep["totals"]
    out += ["", *(f"{p:<32} {x['statements']:>6} {x['missed']:>5} {x['percent']:>5}%"
                  for p, x in t["by_package"].items()),
            f"{'TOTAL':<32} {t['all']['statements']:>6} {t['all']['missed']:>5} {t['all']['percent']:>5}%", "",
            f"Modules under {rep['minimum']}%: " + (", ".join(rep["under_minimum"]) or "none")]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Line coverage of the runtime packages, standard library only.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--tests", default="tests")
    parser.add_argument("--pattern", default="test*.py")
    parser.add_argument("--packages", nargs="+", default=list(PACKAGES))
    parser.add_argument("--min", type=float, default=70.0, help="list the modules under this percentage")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        rep = measure(args)
    except Exception as exc:  # a bug in this tool, never a verdict on the code
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=2) if args.json else render(rep))
    return 0 if rep["suite_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
