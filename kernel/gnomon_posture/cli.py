"""`rihmasto gnomon-posture`, part of the command line (kernel/cli.py); docs/guides/gnomon-posture.md is the guide.

    rihmasto gnomon-posture show <pid> [--persona developer]   the project's Gnomon posture, as JSON
    rihmasto gnomon-posture propose <pid> <GP-id> --person ... --persona developer|it
                                                               file one suggestion as a change card

Reading writes nothing; nothing here applies a suggestion, writes into a repository or grants Gnomon any trust.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel.people import PERSONAS

Args = argparse.Namespace
Show = Callable[[Any], Any]


def add_parsers(sub: Any) -> None:
    """Add `gnomon-posture` to `rihmasto`'s subcommands."""
    gp = sub.add_parser("gnomon-posture", help="how well Gnomon governs a project and what to tighten, from its own "
                                               "Gnomon files (docs/guides/gnomon-posture.md)"
                        ).add_subparsers(dest="sub", required=True)
    show = gp.add_parser("show", help="the project's Gnomon posture")
    show.add_argument("pid")
    show.add_argument("--persona", default="developer", choices=PERSONAS)
    pr = gp.add_parser("propose", help="file one suggestion as a change card, to decide")
    pr.add_argument("pid")
    pr.add_argument("suggestion", help="the suggestion's id (GP-...), as `rihmasto gnomon-posture show` lists it")
    pr.add_argument("--person", required=True)
    pr.add_argument("--persona", required=True, choices=PERSONAS)


def _show(f: Any, a: Args) -> dict[str, Any]:
    from kernel.gnomon_posture.view import build

    return build(f, f.project(a.pid), persona=a.persona)


def _propose(f: Any, a: Args) -> dict[str, Any]:
    from kernel.gnomon_posture.view import propose

    return propose(f, f.project(a.pid), a.suggestion, person=a.person, persona=a.persona)


COMMANDS: dict[str, Callable[[Any, Args], dict[str, Any]]] = {"gnomon-posture show": _show,
                                                              "gnomon-posture propose": _propose}


def handlers(show: Show) -> dict[str, Callable[[Any, Args], int]]:
    """Each command; a refusal is said on stderr with exit 2, as the other commands' are."""
    from kernel.agentobs.cli import _run

    return {name: _run(show, name, run) for name, run in COMMANDS.items()}
