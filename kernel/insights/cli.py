"""`rihmasto insights`: the insights on the command line, and their export to a team's own stack.

    rihmasto insights [<pid>] [--dimension health|compliance|governance|security|drift|qa|usage]
                      [--window 24h|7d|30d|all] [--json]
    rihmasto insights export [<pid>] --format json|csv|otlp-json [--out FILE] [--dimension D] [--window W]

Without a project the scope is the whole factory. ``export`` writes the file named by --out, or prints; it never
sends anything over the network (D-0017). A project whose id is "export" is named with --project.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel.insights.base import DIMENSIONS, WINDOWS
from kernel.insights.export import FORMATS

Args = argparse.Namespace
Say = Callable[[str], Any]


def add_parsers(sub: Any) -> None:
    p = sub.add_parser("insights", help="health, compliance, governance, security, context drift, QA and usage, "
                                        "from the records (kernel/insights); 'export' writes them for your own tools")
    p.add_argument("target", nargs="?", help="a project id, or 'export'")
    p.add_argument("pid", nargs="?", help="with export: the project (default: the whole factory)")
    p.add_argument("--project", help="the project, when its id is a word this command takes (such as export)")
    p.add_argument("--dimension", choices=DIMENSIONS, help="one dimension (default: all of them)")
    p.add_argument("--window", choices=list(WINDOWS), default="7d", help="the time window (default: 7d)")
    p.add_argument("--json", action="store_true", help="the read model as JSON")
    p.add_argument("--format", choices=FORMATS, default="json", help="with export: the file's format")
    p.add_argument("--out", help="with export: write this file instead of printing")


def _pid(a: Args) -> str | None:
    if a.project:
        return str(a.project)
    return a.pid if a.target == "export" else a.target


def text(model: dict[str, Any]) -> str:
    """A read model in words: each figure, its line, and how to measure what is not measured."""
    where = model["project_title"] or "the factory"
    lines = [f"{model['label']} - {where} - {model['window_words']}"]
    for t in model["tiles"]:
        sub = f" ({t['sub']})" if t.get("sub") and t["measured"] else ""
        how = "" if t["measured"] else f" To measure it: {t['how']}."
        lines += [f"  {t['label']}: {t['display']}{sub}", f"    {t['line']}{how}"]
    lines += [f"  Not measured here: {g['what']}: {g['why']}." for g in model["gaps"]]
    return "\n".join(lines)


def _show(factory: Any, a: Args, emit: Callable[[Any], None], say: Say) -> int:
    from kernel.insights import overview, read

    pid = _pid(a)
    if a.dimension:
        models = [read(factory, a.dimension, pid=pid, window=a.window)]
    else:
        models = overview(factory, pid=pid, window=a.window)["dimensions"]
    if a.json:
        emit(models[0] if a.dimension else {"dimensions": models})
    else:
        say("\n\n".join(text(m) for m in models))
    return 0


def _export(factory: Any, a: Args, say: Say) -> int:
    from kernel.insights.export import export

    out = export(factory, a.format, dimension=a.dimension, pid=_pid(a), window=a.window)
    if a.out:
        Path(a.out).write_text(out, encoding="utf-8", newline="\n")
        say(f"wrote {a.out} ({a.format}, {len(out.encode('utf-8'))} bytes); nothing was sent anywhere")
    else:
        say(out.rstrip("\n"))
    return 0


def handlers(emit: Callable[[Any], None], say: Say) -> dict[str, Callable[[Any, Args], int]]:
    """``emit`` prints an answer as JSON, ``say`` prints text."""
    return {"insights": lambda f, a: _export(f, a, say) if a.target == "export" else _show(f, a, emit, say)}
