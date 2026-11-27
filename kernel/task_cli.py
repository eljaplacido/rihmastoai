"""`rihmasto task` and `rihmasto start-here`, part of the command line (kernel/cli.py): a project's tasks you can open
and its Start here from a terminal (FR-LND1), the same as the cockpit's Tasks panel and a project's first view.

    rihmasto start-here <pid> [--for NAME]                     what Rihmasto understood, the steps now, meanwhile
    rihmasto task list <pid>                                   every task with its status and source
    rihmasto task show <pid> <task>                            one task: criteria, tests, commits, history, actions
    rihmasto task start <pid> <task> --person ... --persona ... [--note "..."]
    rihmasto task done <pid> <task> --evidence "..." --person ... --persona ...
    rihmasto task handoff <pid> <task> [--to claude-code|codex|opencode|cursor|generic] --person ... --persona ...

The writes are signed and in the ledger, as the cockpit's are; `task handoff` prints the task's brief for the agent.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import start_here, task_detail
from kernel.people import PERSONAS

Args = argparse.Namespace
AGENTS = ("claude-code", "codex", "opencode", "cursor", "generic")


def add_parsers(sub: Any) -> None:
    """Add `task` and `start-here` to `rihmasto`'s subcommands."""
    here = sub.add_parser("start-here", help="what to do in a project now, and what runs on its own (FR-LND1)")
    here.add_argument("pid")
    here.add_argument("--for", dest="reader", help="whose hidden panel to count")
    task = sub.add_parser("task", help="a project's tasks: list, open, start, mark done, hand off (FR-LND1)"
                          ).add_subparsers(dest="sub", required=True)
    for name, said in (("list", "every task with its status and source"), ("show", "one task, all of it"),
                       ("start", "start work on a task"), ("done", "mark a task done with evidence"),
                       ("handoff", "hand a task to a coding agent")):
        p = task.add_parser(name, help=said)
        p.add_argument("pid")
        if name != "list":
            p.add_argument("task")
        if name in ("start", "done", "handoff"):
            p.add_argument("--person", required=True)
            p.add_argument("--persona", required=True, choices=PERSONAS)
        if name == "start":
            p.add_argument("--note", default="")
        elif name == "done":
            p.add_argument("--evidence", required=True)
        elif name == "handoff":
            p.add_argument("--to", default="generic", choices=AGENTS)


def _handoff(f: Any, a: Args) -> dict[str, Any]:
    out = task_detail.handoff(f.project(a.pid), a.task, to=a.to, person=a.person, persona=a.persona, via="copy")
    return {"task": out["task"], "message": out["message"]["id"], "to": out["to"], "brief": out["markdown"]}


COMMANDS: dict[str, Callable[[Any, Args], dict[str, Any]]] = {
    "start-here": lambda f, a: start_here.panel(f.project(a.pid), person=a.reader),
    "task list": lambda f, a: task_detail.rows(f.project(a.pid)),
    "task show": lambda f, a: task_detail.detail(f.project(a.pid), a.task),
    "task start": lambda f, a: task_detail.start(f.project(a.pid), a.task, person=a.person, persona=a.persona,
                                                 note=a.note),
    "task done": lambda f, a: task_detail.mark_done(f.project(a.pid), a.task, person=a.person, persona=a.persona,
                                                    evidence=a.evidence),
    "task handoff": _handoff,
}


def handlers(show: Callable[[Any], Any], say: Any = None) -> dict[str, Callable[[Any, Args], int]]:
    """The commands, each printing its answer with ``show``; a refusal is one line and exit 2, as `rihmasto dev`."""
    from kernel import devcli

    return {name: devcli._run(show, name, run) for name, run in sorted(COMMANDS.items())}
