"""The commands that change anything set for a project (FR-CHG1), part of `rihmasto` (kernel/cli.py).

    rihmasto settings <pid> [--title ...] [--kind ...] [--mode ...] [--maturity ...] --reason "..." [--redo]
                     [--preview] --person Aino --persona product_owner
    rihmasto rewind <pid> --to material|questions|spec|plan --reason "..." [--preview] --person ... --persona ...
    rihmasto material add <pid> (--text "..." | --path FILE_OR_FOLDER) [--note ...] [--reintake]
                     --person ... --persona ...
    rihmasto next <pid>                what the project waits for, who can act, and how

A write is signed with --person and --persona, and a refusal is a message on stderr with exit 2. With
--preview, `settings` and `rewind` say what they would do and write nothing. `next` reads only.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import next_step, project_material, project_settings, rewind
from kernel.people import PERSONAS
from kernel.profiles import PROFILES
from kernel.store import MATURITIES, MODES, Factory

Args = argparse.Namespace


def _signer(p: argparse.ArgumentParser, required: bool = True) -> argparse.ArgumentParser:
    p.add_argument("--person", required=required, help="the named person who signs the change")
    p.add_argument("--persona", required=required, choices=PERSONAS, help="a persona granted on the project")
    return p


def _signed(args: Args) -> None:
    """A preview reads only; a change is signed by a named person and a persona."""
    if not args.preview and not (args.person and args.persona):
        raise ValueError("a change is signed: name --person and --persona (a --preview needs neither)")


def add_parsers(sub: Any) -> None:
    """Add `settings`, `rewind`, `material add` and `next` to `rihmasto`'s subcommands."""
    s = _signer(sub.add_parser("settings", help="change a project's title, kind of work, mode or maturity"), False)
    s.add_argument("pid")
    s.add_argument("--title")
    s.add_argument("--kind", choices=list(PROFILES), help="the kind of work (the work profile)")
    s.add_argument("--mode", choices=MODES)
    s.add_argument("--maturity", choices=MATURITIES)
    s.add_argument("--reason", default="", help="why: recorded with your name (required to change)")
    s.add_argument("--redo", action="store_true", help="also go back to the step the change no longer fits")
    s.add_argument("--preview", action="store_true", help="say what the change would do; write nothing")
    r = _signer(sub.add_parser("rewind", help="go back a step so it runs again; nothing is deleted"), False)
    r.add_argument("pid")
    r.add_argument("--to", required=True, choices=rewind.STEPS)
    r.add_argument("--reason", default="")
    r.add_argument("--preview", action="store_true", help="say what going back would set aside; write nothing")
    m = sub.add_parser("material", help="material added to a project later").add_subparsers(dest="sub", required=True)
    a = _signer(m.add_parser("add", help="append material to the project's request (the original is kept)"))
    a.add_argument("pid")
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--text")
    src.add_argument("--path", help="a file or a folder on this machine")
    a.add_argument("--note", default="", help="what the material is")
    a.add_argument("--reintake", action="store_true", help="the panel reads the new material now")
    sub.add_parser("next", help="what a project waits for, who can act, and the actions").add_argument("pid")


def _settings(factory: Factory, args: Args) -> dict[str, Any]:
    project = factory.project(args.pid)
    given = {"title": args.title, "kind": args.kind, "mode": args.mode, "maturity": args.maturity}
    _signed(args)
    if args.preview:
        return project_settings.preview(project, **given)
    return project_settings.change(project, person=args.person, persona=args.persona, reason=args.reason,
                                   redo=args.redo, **given)


def _rewind(factory: Factory, args: Args) -> dict[str, Any]:
    project = factory.project(args.pid)
    _signed(args)
    if args.preview:
        return rewind.preview(project, args.to)
    return rewind.rewind(project, to=args.to, person=args.person, persona=args.persona, reason=args.reason)


def _material(model: Callable[[], Any]) -> Callable[[Factory, Args], dict[str, Any]]:
    def run(factory: Factory, args: Args) -> dict[str, Any]:
        return project_material.add_material(factory.project(args.pid), person=args.person, persona=args.persona,
                                             text=args.text, path=args.path, note=args.note,
                                             reintake=args.reintake, model=model() if args.reintake else None)
    return run


def handlers(show: Callable[[Any], None], model: Callable[[], Any]) -> dict[str, Callable[[Factory, Args], None]]:
    """The commands as `rihmasto` runs them: each shows what it returns."""
    material = _material(model)
    return {"settings": lambda f, a: show(_settings(f, a)), "rewind": lambda f, a: show(_rewind(f, a)),
            "material add": lambda f, a: show(material(f, a)),
            "next": lambda f, a: show(next_step.next_step(f.project(a.pid)))}
