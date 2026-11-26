"""`rihmasto dev`, part of the command line (kernel/cli.py): a project's development work from a terminal (FR-DEV1).

    rihmasto dev board <pid>                                  the lanes and cards, as JSON
    rihmasto dev trace <pid> [--window 24h|7d|30d|all] [--who agent] [--harness claude-code] [--task T-001]
    rihmasto dev brief <pid> [--for NAME]                     the developer briefing: what's next and why
    rihmasto dev hooks <pid> [--operator NAME] [--operator-persona developer]   the session hooks' files
    rihmasto dev seen <pid> --person ... --persona ...        the next briefing counts from now
    rihmasto dev session <pid> --harness claude-code --event start|end --session ID --person ... --persona ...
                         [--branch B] [--head SHA] [--commits N] [--files-changed N] [--tasks T-001,T-002]

`dev session` is what a coding agent's session hook records (metadata only); the hooks themselves call the kernel
the same way. Nothing here writes into a repository.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from kernel import devboard, devbrief, devsessions, devtrace
from kernel.people import PERSONAS

Args = argparse.Namespace


def add_parsers(sub: Any) -> None:
    """Add `dev` to `rihmasto`'s subcommands."""
    dev = sub.add_parser("dev", help="a project's development board, trace and briefing (FR-DEV1)"
                         ).add_subparsers(dest="sub", required=True)
    for name, said in (("board", "the development board"), ("brief", "the developer briefing: what's next and why"),
                       ("trace", "every interaction of people and agents"), ("hooks", "the session hooks' files"),
                       ("seen", "record your look at the briefing"), ("session", "record a coding-agent session")):
        p = dev.add_parser(name, help=said)
        p.add_argument("pid")
        _more(name, p)


def _more(name: str, p: argparse.ArgumentParser) -> None:
    if name == "trace":
        p.add_argument("--window", default="7d")
        p.add_argument("--who", choices=list(devtrace.WHO))
        p.add_argument("--harness")
        p.add_argument("--task")
    elif name == "brief":
        p.add_argument("--for", dest="reader", help="whose last look to count from")
    elif name == "hooks":
        p.add_argument("--operator", default="<your name>")
        p.add_argument("--operator-persona", default="developer", choices=PERSONAS)
    elif name in ("seen", "session"):
        p.add_argument("--person", required=True)
        p.add_argument("--persona", required=True, choices=PERSONAS)
    if name == "session":
        p.add_argument("--harness", required=True, choices=list(devsessions.HARNESSES))
        p.add_argument("--event", required=True, choices=list(devsessions.EVENTS))
        p.add_argument("--session", required=True)
        p.add_argument("--branch")
        p.add_argument("--head")
        p.add_argument("--commits", type=int)
        p.add_argument("--files-changed", type=int)
        p.add_argument("--tasks", default="")


COMMANDS: dict[str, Callable[[Any, Args], dict[str, Any]]] = {
    "dev board": lambda f, a: devboard.board(f.project(a.pid)),
    "dev brief": lambda f, a: devbrief.briefing(f.project(a.pid), person=a.reader),
    "dev trace": lambda f, a: devtrace.trace(f.project(a.pid), window=a.window, who=a.who, harness=a.harness,
                                             task=a.task),
    "dev hooks": lambda f, a: devsessions.hooks(f.project(a.pid), person=a.operator, persona=a.operator_persona,
                                                python=sys.executable),
    "dev seen": lambda f, a: devsessions.look(f.project(a.pid), person=a.person, persona=a.persona),
    "dev session": lambda f, a: devsessions.record(
        f.project(a.pid), harness=a.harness, event=a.event, session=a.session, person=a.person, persona=a.persona,
        branch=a.branch, head=a.head, commits=a.commits, files_changed=a.files_changed,
        tasks=[t.strip() for t in a.tasks.split(",") if t.strip()]),
}


Run = Callable[[Any, Args], dict[str, Any]]


def _run(show: Callable[[Any], Any], name: str, run: Run) -> Callable[[Any, Args], int]:
    def go(f: Any, a: Args) -> int:
        try:
            show(run(f, a))
        except (ValueError, KeyError) as exc:
            said = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
            sys.stderr.write(f"rihmasto {name}: {said}\n")
            return 2
        return 0
    return go


def handlers(show: Callable[[Any], Any], say: Any = None) -> dict[str, Callable[[Any, Args], int]]:
    """The `dev` commands, each printing its answer with ``show`` (``say``, the plain printer, is not needed)."""
    return {name: _run(show, name, run) for name, run in COMMANDS.items()}
