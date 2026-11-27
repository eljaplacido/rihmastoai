"""Run the test suite in a few parallel processes, streaming each one's output as it comes.

CI uses it on Windows, where starting processes is slow and the suite no longer fits one process in the job's time.
The browser tests (every module that drives Chrome, directly or through another test module) all run in ONE
process, one after another: two Chromes and two cockpits starting at once on a small CI machine time out at random
(the sign-in page never arrives), so they never run side by side. The other modules are shared out by file size
among the remaining processes. Each runs ``python -m unittest`` on its share from the repository root (the tests put
``tests/`` on their own path). Exit status is 0 only when every process passed.
Usage: ``python tools/ci_run.py --shards 2`` (one browser process and one other).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
DRIVER = "test_ui_drive"
IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)


def modules() -> list[str]:
    """Every test module as a dotted name, the acceptance ones included."""
    found = sorted(TESTS.glob("test_*.py")) + sorted((TESTS / "acceptance").glob("test_*.py"))
    return [".".join(p.relative_to(ROOT).with_suffix("").parts) for p in found]


def _local_imports(path: Path) -> set[str]:
    """The modules of ``tests/`` that a file imports (by bare name, as the tests import each other)."""
    names = {(a or b).split(".")[-1] for a, b in IMPORT.findall(path.read_text(encoding="utf-8", errors="replace"))}
    return {n for n in names if (TESTS / f"{n}.py").is_file()}


def drives_browser(name: str, _seen: set[str] | None = None) -> bool:
    """Whether a test module drives Chrome: it imports the driver, or a test module that does."""
    seen = _seen if _seen is not None else set()
    path = ROOT / (name.replace(".", "/") + ".py")
    for dep in _local_imports(path):
        if dep == DRIVER:
            return True
        if dep not in seen:
            seen.add(dep)
            if drives_browser(f"tests.{dep}", seen):
                return True
    return False


def share(names: list[str], count: int) -> list[list[str]]:
    """The modules dealt out to ``count`` processes, the largest first, each to the lightest so far."""
    size = {n: (ROOT / (n.replace(".", "/") + ".py")).stat().st_size for n in names}
    out: list[list[str]] = [[] for _ in range(count)]
    load = [0] * count
    for name in sorted(names, key=lambda n: -size[n]):
        i = load.index(min(load))
        out[i].append(name)
        load[i] += size[name]
    return out


def run_one(index: int, names: list[str], results: dict[int, int]) -> None:
    proc = subprocess.Popen([sys.executable, "-u", "-m", "unittest", "-v", *names], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    assert proc.stdout is not None
    for line in proc.stdout:
        print(f"[{index}] {line.rstrip()}", flush=True)
    results[index] = proc.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=int, default=2)
    args = parser.parse_args(argv)
    names = modules()
    browser = [n for n in names if n != f"tests.{DRIVER}" and drives_browser(n)] + [f"tests.{DRIVER}"]
    rest = [n for n in names if n not in browser]
    parts = [p for p in [browser, *share(rest, max(1, args.shards - 1))] if p]
    print(f"browser modules in one process: {len(browser)}; others: {len(rest)}", flush=True)
    results: dict[int, int] = {}
    threads = [threading.Thread(target=run_one, args=(i, p, results)) for i, p in enumerate(parts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    bad = [i for i, code in sorted(results.items()) if code != 0]
    print(f"shards: {len(parts)}; failed: {bad or 'none'}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
