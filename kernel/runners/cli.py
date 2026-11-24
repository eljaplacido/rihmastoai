"""`rihmasto runners`, part of the command line (kernel/cli.py). docs/guides/harnesses.md is the guide.

    rihmasto runners list [--project PID]       what runs each role, for the factory and each project, and every choice
    rihmasto runners check [RUNNER]             each runner on this machine: found or not, its version; and Docker
    rihmasto runners set <builder|verifier> <runner> [--project PID] [--version V] [--model M] [--family F]
                         [--command "agent --task {prompt_file} --cwd {workdir}"] [--sandbox off|docker] [--image I]
                         [--endpoint HOST:PORT ...] [--reason ...] --person ... --persona it|developer

`set` to gnomon applies at once; any other runner opens a card that IT decides in the factory's Inbox
(`rihmasto decide _factory <C-id> approve --person ... --persona it`), with the runner's version pinned.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel.people import PERSONAS
from kernel.runners import ROLES, RUNNERS
from kernel.runners import choice as rchoice
from kernel.store import Factory

Show = Callable[[Any], Any]
Args = argparse.Namespace


def add_parsers(sub: Any) -> None:
    """Add `runners` to `rihmasto`'s subcommands."""
    rn = sub.add_parser("runners", help="which harness runs the factory's cells (docs/guides/harnesses.md)"
                        ).add_subparsers(dest="sub", required=True)
    rn.add_parser("list", help="what runs each role, and every choice").add_argument("--project")
    rn.add_parser("check", help="each runner on this machine and its version").add_argument(
        "runner", nargs="?", choices=list(RUNNERS))
    s = rn.add_parser("set", help="choose a role's runner: gnomon at once, another on an IT card")
    s.add_argument("role", choices=list(ROLES))
    s.add_argument("runner", choices=list(RUNNERS))
    s.add_argument("--project", help="a project's own choice (default: the factory's)")
    s.add_argument("--version", help="the version to pin (default: the one found on this machine)")
    s.add_argument("--model", help="the model the harness uses")
    s.add_argument("--family", help="the model family it answers with (the verifier's must differ)")
    s.add_argument("--command", help="the command runner's line, with {prompt_file} and {workdir}")
    s.add_argument("--sandbox", choices=list(rchoice.SANDBOXES), default="off")
    s.add_argument("--image", help="the docker sandbox's image, one that holds the harness")
    s.add_argument("--endpoint", action="append", default=[], help="HOST:PORT the sandboxed harness may reach")
    s.add_argument("--reason", default="")
    s.add_argument("--person", required=True, help="the named person who signs it")
    s.add_argument("--persona", required=True, choices=PERSONAS)


def _check(f: Factory, a: Args) -> dict[str, Any]:
    from kernel.runners.detect import detect
    from kernel.runners.sandbox import docker_status

    latest = {c["runner"]: c for c in rchoice.choices(f)}
    names = [a.runner] if a.runner else list(RUNNERS)
    return {"runners": [detect(n, latest.get(n)) for n in names], "docker": docker_status()}


def _set(f: Factory, a: Args) -> dict[str, Any]:
    return rchoice.propose(f, role=a.role, runner=a.runner, scope=a.project, person=a.person, persona=a.persona,
                           reason=a.reason, version=a.version, model=a.model, family=a.family, command=a.command,
                           sandbox=a.sandbox, image=a.image, endpoints=a.endpoint)


def commands() -> dict[str, Callable[[Factory, Args], Any]]:
    return {"runners list": lambda f, a: rchoice.view(f, pid=a.project, look=False),
            "runners check": _check, "runners set": _set}


def _printed(show: Show, run: Callable[[Factory, Args], Any]) -> Callable[[Factory, Args], None]:
    """A command as `rihmasto` runs it: its result printed by ``show``."""
    return lambda f, a: show(run(f, a))


def handlers(show: Show) -> dict[str, Callable[[Factory, Args], None]]:
    return {name: _printed(show, run) for name, run in commands().items()}
