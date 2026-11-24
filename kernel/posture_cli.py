"""The posture's commands (kernel/posture.py), part of `rihmasto` (kernel/cli.py adds them).

    rihmasto new "Title" --source "..." --requested-by Aino --posture regulated [--weights security=3,ux=2]
    rihmasto posture list                          the postures, their defaults and floors
    rihmasto posture preview <name> [--weights ...] [--maturity M] [--mode M] [--profile P] [--project PID]
                                                   what it would do; with --project, what changes now and later
    rihmasto posture show <pid>                    the project's posture, what it does and what holds it now
    rihmasto posture set <pid> <name> [--weights ...] [--maturity M] [--mode M] --reason "..."
                         --person Aino --persona business_owner
    rihmasto posture confirm <pid> <A-id> [--refute "the correction"] --person Aino --persona business_owner

`new` takes the mode and maturity from the posture unless they are named; a named maturity must be one
the posture runs at, and a named mode at least as strict as its own. Without --posture, `new` is as
before. A change is signed by a named person with a setter persona; loosening needs a business owner,
IT or compliance.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel.canon import Canon
from kernel.people import PERSONAS
from kernel.posture import POSTURES, effects, parse_weights, preview, public
from kernel.profiles import PROFILES
from kernel.store import MATURITIES, MODES, Factory

Args = argparse.Namespace


def _weights(text: str) -> dict[str, int]:
    """--weights as argparse reads it: a refused value is a usage error, never a traceback."""
    try:
        return parse_weights(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _tuning(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("--weights", type=_weights, default=None,
                   help="priority weights from 0 to 3, such as security=3,ux=2,speed=1 (ux, security, compliance, "
                        "speed, cost)")
    p.add_argument("--maturity", choices=MATURITIES, help="one the posture runs at (default: the posture's)")
    p.add_argument("--mode", choices=MODES, help="at least as strict as the posture's (default: the posture's)")
    return p


def add_parsers(sub: Any) -> None:
    """`rihmasto posture ...`, and --posture and --weights on `rihmasto new` and `rihmasto adopt` (added
    after them; `adopt` also takes --mode)."""
    for name in ("new", "adopt"):
        new = sub.choices[name]
        new.add_argument("--posture", choices=list(POSTURES),
                         help="how the project runs: prototype, balanced, production or regulated (sets the mode, the "
                              "maturity and what waits for a person; see `rihmasto posture preview`)")
        new.add_argument("--weights", type=_weights, default=None, help="priority weights from 0 to 3, with --posture")
        if name == "adopt":
            new.add_argument("--mode", choices=MODES, help="who answers the panel (default: the posture's, else mixed)")
        # Unnamed, the mode and maturity are the posture's, else as before (mixed, and demo for `new` or
        # production for `adopt`). The parser itself refuses a posture with a maturity or mode it does not
        # run at (`choice`).
        new.set_defaults(mode=None, maturity=None, posture_parser=new)
    cmds = sub.add_parser("posture", help="how a project runs: a posture and its weights (kernel/posture.py)"
                          ).add_subparsers(dest="sub", required=True)
    cmds.add_parser("list", help="the postures, their defaults and floors")
    p = _tuning(cmds.add_parser("preview", help="what a posture and weights would do, before anyone chooses"))
    p.add_argument("name", choices=list(POSTURES))
    p.add_argument("--profile", choices=list(PROFILES), help="the work profile (whether it has screens)")
    p.add_argument("--project", help="also say what changing this project to it would change now and later")
    cmds.add_parser("show", help="a project's posture, what it does, and what holds it now").add_argument("pid")
    p = _tuning(cmds.add_parser("set", help="choose or change a project's posture during the run, with a reason"))
    p.add_argument("pid")
    p.add_argument("name", choices=list(POSTURES))
    p.add_argument("--reason", required=True)
    p.add_argument("--person", required=True)
    p.add_argument("--persona", required=True, choices=PERSONAS)
    p = cmds.add_parser("confirm", help="a person confirms (or refutes) an assumption the posture holds a build on")
    p.add_argument("pid")
    p.add_argument("aid", metavar="A-id")
    p.add_argument("--refute", metavar="CORRECTION", help="refute it with this correction instead")
    p.add_argument("--person", required=True)
    p.add_argument("--persona", required=True, choices=PERSONAS)


def choice(args: Args) -> dict[str, Any] | None:
    """The posture `rihmasto new` was asked for, chosen by the person who asks for the project. A
    maturity or mode the posture does not run at is a usage error, as argparse gives one."""
    parser = getattr(args, "posture_parser", None)
    if not getattr(args, "posture", None):
        if getattr(args, "weights", None) and parser is not None:
            parser.error("--weights tune a posture: name one with --posture")
        return None
    try:
        effects(args.posture, args.weights, maturity=args.maturity, mode=args.mode)
    except ValueError as exc:
        if parser is None:
            raise
        parser.error(str(exc))
    return {"name": args.posture, "weights": args.weights,     # `new` names who asks, `adopt` who adopts
            "by": getattr(args, "requested_by", None) or getattr(args, "person", None),
            "persona": args.persona or "business_owner"}


def _preview(f: Factory, a: Args) -> dict[str, Any]:
    from kernel.posture_change import proposed, what_changes

    if a.project is None:
        return preview(a.name, a.weights, maturity=a.maturity, mode=a.mode, profile=a.profile)
    project = f.project(a.project)
    after = proposed(project, a.name, a.weights, maturity=a.maturity, mode=a.mode)
    return preview(a.name, a.weights, maturity=after["maturity"], mode=a.mode,
                   profile=project.meta.get("profile")) | {"project": project.pid, **what_changes(project, after)}


def _show(f: Factory, a: Args) -> dict[str, Any]:
    from kernel.posture_rules import view

    return {"project": a.pid} | view(f.project(a.pid))


def _set(f: Factory, a: Args) -> dict[str, Any]:
    from kernel.posture_change import change

    return change(f.project(a.pid), a.name, a.weights, person=a.person, persona=a.persona, reason=a.reason,
                  maturity=a.maturity, mode=a.mode)


def _confirm(f: Factory, a: Args) -> dict[str, Any]:
    from kernel.intake import render_brief

    project = f.project(a.pid)
    out = Canon(project).settle_assumption(a.aid, confirmed=a.refute is None, person=a.person, persona=a.persona,
                                           correction=a.refute or "")
    render_brief(project)
    return out


def handlers(emit: Callable[[Any], None]) -> dict[str, Callable[[Factory, Args], None]]:
    """The `rihmasto posture` handlers; ``emit`` prints an answer."""
    return {
        "posture list": lambda f, a: emit(public()),
        "posture preview": lambda f, a: emit(_preview(f, a)),
        "posture show": lambda f, a: emit(_show(f, a)),
        "posture set": lambda f, a: emit(_set(f, a)),
        "posture confirm": lambda f, a: emit(_confirm(f, a)),
    }
