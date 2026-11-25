"""The command line of the console and the checks (FR-CON1, FR-CHK1).

    rihmasto console <pid> --person ... --persona developer -- npm test
    rihmasto console <pid> --gnomon "add a health endpoint" [--role builder] [--yes] --person ... --persona ...
    rihmasto console <pid> --offers | --allow developer,it,operations | --state test="pytest -q"
    rihmasto shell <pid> --person ... --persona ...
    rihmasto checks list [<pid>] | history <pid> [<check>] | tick
    rihmasto checks enable <pid> <check> [--set key=value ...] [--every 1d] [--on-fail signal,change] [--all-projects]
    rihmasto checks disable|run <pid> <check> --person ... --persona ...

A console run streams its output as it comes and exits with the command's own exit code (1 when it was
stopped, ran out of time or did not start); it is recorded like a run from the cockpit (``console_ran``).
"""

from __future__ import annotations

import argparse
import shlex
import sys
from collections.abc import Callable
from typing import Any

from kernel import console as kconsole
from kernel import console_term
from kernel.canon import DecisionRefused
from kernel.checks import health as chealth
from kernel.checks import public
from kernel.checks import store as cstore
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace


def _who(p: argparse.ArgumentParser) -> None:
    p.add_argument("--person", help="who runs it (with access enforced: your name in the access file)")
    p.add_argument("--persona", choices=PERSONAS, help="the persona you act as")


def _pair(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("give name=value")
    name, value = text.split("=", 1)
    return name.strip(), value


def _console_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--gnomon", metavar="TEXT", help="ask Gnomon to do this (gnomon task), instead of a command")
    p.add_argument("--role", help="the Gnomon role, with --gnomon")
    p.add_argument("--yes", action="store_true", help="with --gnomon: let Gnomon apply gated changes without asking")
    p.add_argument("--shell", action="store_true", help="run the command line through the shell (pipes, &&)")
    p.add_argument("--timeout", type=int, help=f"seconds before it is stopped (default {kconsole.DEFAULT_TIMEOUT})")
    p.add_argument("--offers", action="store_true", help="list the commands the console offers here, and run nothing")
    p.add_argument("--allow", metavar="PERSONAS", help="IT: the personas that may use the console here (comma between)")
    p.add_argument("--state", type=_pair, action="append", metavar="NAME=LINE", help="state a project command")
    _who(p)


class _Rest(argparse.Action):
    """Everything after the project: its options up to ``--``, then the command line, word for word. Parsed
    here, so ``console <pid> --persona developer -- npm test`` reads the same on every Python argparse."""

    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace, values: Any,
                 option_string: str | None = None) -> None:
        words = list(values or [])
        if "--" in words:
            cut = words.index("--")
            options, command = words[:cut], words[cut + 1:]
        else:
            options, command = (words, []) if words and words[0].startswith("-") else ([], words)
        if options:
            again = argparse.ArgumentParser(prog=parser.prog, add_help=False)
            _console_options(again)
            known = again.parse_args(options)
            for key, value in vars(known).items():
                if value not in (None, False):
                    setattr(namespace, key, value)
        setattr(namespace, self.dest, command)


def add_parsers(sub: Any) -> None:
    p = sub.add_parser("console", help="run a command, or ask Gnomon, in a project's workspace (recorded)")
    p.add_argument("pid")
    _console_options(p)
    p.add_argument("command", nargs=argparse.REMAINDER, action=_Rest, help="after --: the command line")
    p = sub.add_parser("shell", help="an interactive subshell in a project's workspace (recorded as opened)")
    p.add_argument("pid")
    _who(p)
    cmds = sub.add_parser("checks", help="checks for maintenance and administration, and their results"
                          ).add_subparsers(dest="sub", required=True)
    cmds.add_parser("list", help="the catalogue, or a project's checks and their last results").add_argument(
        "pid", nargs="?")
    p = cmds.add_parser("history", help="a project's check results")
    p.add_argument("pid")
    p.add_argument("check", nargs="?")
    cmds.add_parser("tick", help="run every check that is due (from cron or Windows Task Scheduler)")
    p = cmds.add_parser("enable", help="enable or change a check on a project (or on every project)")
    p.add_argument("pid")
    p.add_argument("check")
    p.add_argument("--set", type=_pair, action="append", metavar="KEY=VALUE", help="a setting of the check")
    p.add_argument("--every", help="run it on a schedule: 15m, 6h, 1d")
    p.add_argument("--on-fail", help="what a failure does: signal, change (comma between)")
    p.add_argument("--all-projects", action="store_true", help="also on every other project where you may")
    _who(p)
    for name, text in (("disable", "disable a check on a project"), ("run", "run a check now, and record it")):
        p = cmds.add_parser(name, help=text)
        p.add_argument("pid")
        p.add_argument("check")
        _who(p)


def _signer(args: Args) -> tuple[str, str]:
    if not args.person or not args.persona:
        raise ValueError("name --person and --persona: a run is signed")
    return args.person, args.persona


def _console(f: Factory, args: Args, emit: Callable[[Any], None]) -> int:
    project = f.project(args.pid)
    if args.offers:
        emit({"workspace": kconsole.workspace(project, args.person), "offers": kconsole.offered(project, args.person)})
        return 0
    person, persona = _signer(args)
    if args.allow or args.state:
        emit(kconsole.set_settings(project, person=person, persona=persona,
                                   personas=[p.strip() for p in args.allow.split(",")] if args.allow else None,
                                   commands=dict(args.state) if args.state else None))
        return 0
    words = list(args.command or [])
    if not args.gnomon and not words:
        raise ValueError("give the command after --, or --gnomon \"what to do\"")
    request = {"gnomon": args.gnomon, "role": args.role, "yes": args.yes} if args.gnomon else \
        {"line": shlex.join(words) if len(words) != 1 else words[0], "shell": args.shell}

    def echo(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    out = kconsole.run(project, request, person=person, persona=persona, timeout=args.timeout, echo=echo)
    emit({k: out[k] for k in ("state", "code", "seconds", "workspace", "log")})
    return out["code"] if out["state"] in ("done", "failed") and isinstance(out["code"], int) else 1


def _shell(f: Factory, args: Args, emit: Callable[[Any], None]) -> int:
    person, persona = _signer(args)
    out = console_term.subshell(f.project(args.pid), person=person, persona=persona)
    emit(out)
    return 0


def _settings(args: Args) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in args.set or []:
        out[key] = int(value) if value.isdigit() else (value.lower() == "true" if value.lower() in ("true", "false")
                                                       else [v.strip() for v in value.split(",")] if key == "deny"
                                                       else value)
    return out


def _enable(f: Factory, args: Args) -> list[dict[str, Any]]:
    person, persona = _signer(args)
    on_fail = [x.strip() for x in args.on_fail.split(",") if x.strip()] if args.on_fail else None
    first = f.project(args.pid)
    targets = [first] + ([p for p in f.projects() if p.pid != first.pid and not p.pid.startswith("_")]
                         if args.all_projects else [])
    done = []
    for project in targets:
        try:
            if project is not first:
                cstore.sign_on(project, person, persona)
            done.append({"project": project.pid, **cstore.enable(project, args.check, person=person, persona=persona,
                                                                 config=_settings(args), every=args.every,
                                                                 on_fail=on_fail)})
        except DecisionRefused as exc:
            if project is first:
                raise
            done.append({"project": project.pid, "refused": str(exc)})
    return done


def _list(f: Factory, args: Args) -> dict[str, Any]:
    if args.pid:
        return chealth.project_health(f.project(args.pid))
    return {"catalogue": public(), "health": chealth.factory_health(f)["line"]}


def _run(f: Factory, args: Args, emit: Callable[[Any], None]) -> int:
    person, persona = _signer(args)
    row = cstore.run(f.project(args.pid), args.check, person=person, persona=persona, via="command line")
    emit(row)
    return {"passed": 0, "failed": 1}.get(row["verdict"], 4)


def handlers(emit: Callable[[Any], None]) -> dict[str, Callable[[Factory, Args], Any]]:
    """The console's and the checks' handlers; ``emit`` prints an answer."""
    return {
        "console": lambda f, a: _console(f, a, emit),
        "shell": lambda f, a: _shell(f, a, emit),
        "checks list": lambda f, a: emit(_list(f, a)),
        "checks history": lambda f, a: emit(cstore.results(f.project(a.pid), a.check, 50)),
        "checks tick": lambda f, a: emit({"ran": cstore.tick(f)}),
        "checks enable": lambda f, a: emit(_enable(f, a)),
        "checks disable": lambda f, a: emit(cstore.disable(f.project(a.pid), a.check, person=_signer(a)[0],
                                                           persona=_signer(a)[1])),
        "checks run": lambda f, a: _run(f, a, emit),
    }
