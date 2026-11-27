"""Run the test suite in a few parallel processes, streaming each one's output as it comes.

CI uses it on Windows, where starting processes is slow and the suite no longer fits one process in the job's time.
The modules are shared out by file size so the processes finish together; each runs ``python -m unittest`` on its
share from the repository root (the tests put ``tests/`` on their own path). Exit status is 0 only when every
process passed. Usage: ``python tools/ci_run.py --shards 2``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def modules() -> list[str]:
    """Every test module as a dotted name, the acceptance ones included."""
    found = sorted((ROOT / "tests").glob("test_*.py")) + sorted((ROOT / "tests" / "acceptance").glob("test_*.py"))
    return [".".join(p.relative_to(ROOT).with_suffix("").parts) for p in found]


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
    parts = [p for p in share(modules(), max(1, args.shards)) if p]
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
