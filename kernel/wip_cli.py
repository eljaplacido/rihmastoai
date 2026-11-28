"""`rihmasto wip`: a project's work in progress in a terminal (FR-WIP1, kernel/wip.py), as its Overview shows it.

    rihmasto wip <pid> [--json]     what its working copy holds that is not committed: by kind and area, the oldest
                                    change, the branch against its remote, and whether Start here nudges to commit

Reading only: nothing is recorded and nothing is written to the repository. A project whose upstream is not a working
copy on this machine says "not measured" with why (exit 0: that is an answer, not an error).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import wip

Args = argparse.Namespace


def add_parsers(sub: Any) -> None:
    p = sub.add_parser("wip", help="a project's work in progress: what its working copy holds uncommitted (FR-WIP1)")
    p.add_argument("pid")
    p.add_argument("--json", action="store_true", help="the reading as JSON")


def render(r: dict[str, Any]) -> str:
    lines = [r["said"]]
    if not r.get("measured"):
        return lines[0]
    piled = {p["area"] for p in r.get("piles") or []}
    for a in r["areas"][:10]:
        kinds = ", ".join(f"{a[k]} {k}" for k in wip.KINDS if a[k])
        lines.append(f"  {a['area']}: {kinds}" + (" (looks generated)" if a["area"] in piled else ""))
    if len(r["areas"]) > 10:
        lines.append(f"  … and {len(r['areas']) - 10} more area(s)")
    lines.append("Start here nudges to commit it." if r["nudge"]
                 else "Start here does not nudge: it is small and recent.")
    return "\n".join(lines)


def handlers(show: Callable[[Any], Any], echo: Callable[[str], Any] = print) -> dict[str, Callable[[Any, Args], int]]:
    def go(factory: Any, args: Args) -> int:
        r = wip.read(factory.project(args.pid), fresh=True)
        if args.json:
            show(r)
        else:
            echo(render(r))
        return 0

    return {"wip": go}
