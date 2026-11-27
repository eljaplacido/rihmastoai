"""`rihmasto sources`: a project's own sources in a terminal (FR-SRC1, kernel/native_sources.py).

    rihmasto sources show <pid>                          what is mapped, detected, old plans, runs, the trace
    rihmasto sources map <pid> --key KEY | --kind K --glob G [--field id=key ...] [--every E] --person P --persona R
    rihmasto sources change <pid> SRC-n [--glob G] [--field ...] [--every E] --person P --persona R
    rihmasto sources stop <pid> SRC-n [--reason R] --person P --persona R
    rihmasto sources read <pid> --person P --persona R
    rihmasto sources use-anyway <pid> PATH --person P --persona R
    rihmasto sources import <pid> FILE [--format junit|tap|json] [--produced-at T] [--machine M] --person P --persona R
    rihmasto sources run <pid> ROOT --yes --person P --persona R     runs the project's own code on this machine

Each write is signed and in the project's ledger; nothing is written to the repository.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import native_apply, native_sources, native_tests
from kernel.people import PERSONAS

Args = argparse.Namespace
SIGNED = ("map", "change", "stop", "read", "use-anyway", "import", "run")


def add_parsers(sub: Any) -> None:
    src = sub.add_parser("sources", help="a project's own requirements, findings, tasks and test results (FR-SRC1)"
                         ).add_subparsers(dest="sub", required=True)
    for name, said in (("show", "what is mapped and detected, old plans, runs and the trace"),
                       ("map", "map a detected source (--key) or one you name (--kind, --glob)"),
                       ("change", "change a mapped source"), ("stop", "stop reading a mapped source"),
                       ("read", "read every mapped source again"),
                       ("use-anyway", "use a planning document although it may be an old plan"),
                       ("import", "import a results file produced elsewhere"),
                       ("run", "run a mapped test root's command (it runs the project's own code: --yes)")):
        p = src.add_parser(name, help=said)
        p.add_argument("pid")
        _more(name, p)
        if name in SIGNED:
            p.add_argument("--person", required=True)
            p.add_argument("--persona", required=True, choices=PERSONAS)


def _more(name: str, p: argparse.ArgumentParser) -> None:
    if name in ("map", "change"):
        if name == "change":
            p.add_argument("source")
        p.add_argument("--key", help="a detected source's key, as `sources show` lists it")
        p.add_argument("--kind", choices=list(native_sources.KINDS))
        p.add_argument("--glob")
        p.add_argument("--field", action="append", default=[], metavar="FIELD=KEY",
                       help=f"a field mapping ({', '.join(native_sources.FIELDS)}); repeatable")
        p.add_argument("--every", choices=list(native_sources.EVERY))
    elif name == "stop":
        p.add_argument("source")
        p.add_argument("--reason", default="")
    elif name == "use-anyway":
        p.add_argument("path")
    elif name == "import":
        p.add_argument("file")
        p.add_argument("--format", choices=["junit", "tap", "json"])
        p.add_argument("--produced-at")
        p.add_argument("--machine")
        p.add_argument("--name")
    elif name == "run":
        p.add_argument("root", help="the test root's folder; '.' for the repository's root")
        p.add_argument("--yes", action="store_true", help="yes: run the project's own code on this machine")


def _spec(a: Args) -> dict[str, Any] | None:
    fields = dict(f.split("=", 1) for f in a.field if "=" in f)
    spec = {k: v for k, v in (("kind", a.kind), ("glob", a.glob)) if v}
    return spec | ({"mapping": fields} if fields else {}) or None


def _who(a: Args) -> dict[str, str]:
    return {"person": a.person, "persona": a.persona}


COMMANDS: dict[str, Callable[[Any, Args], dict[str, Any]]] = {
    "sources show": lambda f, a: native_apply.view(f.project(a.pid)),
    "sources map": lambda f, a: native_sources.map_source(f.project(a.pid), key=a.key, spec=_spec(a), every=a.every,
                                                         **_who(a)),
    "sources change": lambda f, a: native_sources.map_source(f.project(a.pid), sid=a.source, spec=_spec(a),
                                                            every=a.every, **_who(a)),
    "sources stop": lambda f, a: native_sources.stop(f.project(a.pid), a.source, reason=a.reason, **_who(a)),
    "sources read": lambda f, a: {k: len(v) if isinstance(v, list) else v for k, v in native_sources.read(
        f.project(a.pid), why="asked in a terminal", fetch=True, **_who(a)).items()},
    "sources use-anyway": lambda f, a: native_sources.use_anyway(f.project(a.pid), a.path, **_who(a)),
    "sources import": lambda f, a: native_tests.import_results(
        f.project(a.pid), Path(a.file).read_text(encoding="utf-8", errors="replace"), fmt=a.format,
        produced_at=a.produced_at, machine=a.machine, name=a.name or Path(a.file).name, **_who(a)),
    "sources run": lambda f, a: native_tests.run(f.project(a.pid), "" if a.root in (".", "") else a.root.strip("/"),
                                                 confirmed=bool(a.yes), person=a.person, persona=a.persona),
}


def _run(show: Callable[[Any], Any], name: str, fn: Callable[[Any, Args], dict[str, Any]]) -> Callable[[Any, Args],
                                                                                                       int]:
    def go(factory: Any, a: Args) -> int:
        from kernel.access import AccessRefused

        try:
            show(fn(factory, a))
        except (native_sources.SourcesRefused, native_tests.RunRefused) as exc:
            if isinstance(exc, AccessRefused):
                raise
            sys.stderr.write(f"rihmasto {name}: {exc}\n")
            return 2
        return 0
    return go


def handlers(show: Callable[[Any], Any], say: Any = None) -> dict[str, Callable[[Any, Args], int]]:
    return {name: _run(show, name, fn) for name, fn in COMMANDS.items()}
