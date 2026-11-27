"""`rihmasto itops`: what IT checks for a project, and any assessment from a terminal or cron (FR-ITO1), part of
`rihmasto` (kernel/cli.py).

    rihmasto itops show [<pid>]                                    a project's check set with why; no project: the
                                                                   defaults per solution type
    rihmasto itops apply <pid> --person P --persona X              turn on the set's checks not on yet
    rihmasto itops assess <pid> --target infra --person P --persona X
                                                                   run any assessment now (code, gnomon:<eval>,
                                                                   evalset:<id>, check:<key>, family:<kind>,
                                                                   alignment, optimise, infra)

Each write is signed and recorded as the cockpit's is. A refusal is a message on stderr with exit 2.
"""

from __future__ import annotations

import argparse
import functools
from collections.abc import Callable
from typing import Any

from kernel import itops, itops_assess
from kernel.evals_cli import (
    _who,  # --person and --persona, as every signed command takes them
)
from kernel.store import Factory

Args = argparse.Namespace


def add_parsers(sub: Any) -> None:
    cmds = sub.add_parser("itops", help="what IT checks for a project, by solution type, and any assessment"
                          ).add_subparsers(dest="sub", required=True)
    cmds.add_parser("show", help="a project's IT check set with why; no project: the defaults per type"
                    ).add_argument("pid", nargs="?")
    p = cmds.add_parser("apply", help="turn on the set's checks not on yet, signed")
    p.add_argument("pid")
    _who(p)
    p = cmds.add_parser("assess", help="run any assessment on a project now, signed")
    p.add_argument("pid")
    p.add_argument("--target", default="infra", help=", ".join(itops_assess.TARGETS))
    _who(p)


def _signer(a: Args) -> tuple[str, str]:
    if not a.person or not a.persona:
        raise ValueError("name --person and --persona: it is signed")
    return a.person, a.persona


def _show(show: Callable[[Any], None], f: Factory, a: Args) -> None:
    show(itops.check_set(f.project(a.pid)) if a.pid else itops.platform(f))


def _apply(show: Callable[[Any], None], f: Factory, a: Args) -> None:
    person, persona = _signer(a)
    out = itops.apply(f.project(a.pid), person=person, persona=persona)
    show({"enabled": out["enabled"], "skipped": out["skipped"], "line": out["set"]["line"]})


def _assess(show: Callable[[Any], None], f: Factory, a: Args) -> int:
    person, persona = _signer(a)
    out = itops_assess.run(f.project(a.pid), a.target, person=person, persona=persona, via="command line")
    show(out)
    return 1 if out.get("verdict") == "failed" else 0


def handlers(show: Callable[[Any], None], echo: Callable[[str], None]) -> dict[str, Any]:
    p = functools.partial
    return {"itops show": p(_show, show), "itops apply": p(_apply, show), "itops assess": p(_assess, show)}
