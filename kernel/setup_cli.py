"""`rihmasto setup`, `rihmasto project` and the automations' suggest and describe commands (FR-SET1).

    rihmasto setup <pid>                                  the project's checklist: set up, offered, not applicable
    rihmasto setup <pid> --do checks|automations|alignment --person Aino --persona developer
    rihmasto project archive <pid> [--reason "..."] --person ... --persona ...
    rihmasto project restore <pid> --person ... --persona ...
    rihmasto project remove <pid> --confirm <pid> --person ... --persona ...   (an archived one; cannot be undone)
    rihmasto project archived | project duplicates
    rihmasto automations suggest <pid>                    what its shape and state suggest, with a reason each
    rihmasto automations accept <pid> <suggestion> --person ... --persona ...
    rihmasto automations dismiss <pid> <suggestion> --person ... --persona ...
    rihmasto automations describe "every night run the tests and tell me on Teams if they fail" [--project PID]
                                  [--save --person ... --persona ...]   a draft, its summary and a dry run

kernel/cli.py adds the `setup` and `project` groups (``add_parsers``); kernel/automations_cli.py adds the
automations' commands here to its own group (``automation_parsers``).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import automation_compose as compose
from kernel import automation_suggest as suggest
from kernel import project_archive, project_setup
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace


def _signed(p: argparse.ArgumentParser, *, required: bool = True) -> argparse.ArgumentParser:
    p.add_argument("--person", required=required)
    p.add_argument("--persona", required=required, choices=PERSONAS)
    return p


def add_parsers(sub: Any) -> None:
    """`setup` and `project` on `rihmasto`'s subcommands."""
    s = sub.add_parser("setup", help="set up a project: what applies, what is in use, one click for the rest")
    s.add_argument("pid")
    s.add_argument("--do", choices=sorted(project_setup.DOERS), help="carry out an offered item, signed")
    _signed(s, required=False)
    project_archive.add_parsers(sub)


def automation_parsers(g: Any) -> None:
    """The automations' suggest, accept, dismiss and describe, in `rihmasto automations`."""
    g.add_parser("suggest", help="automations a project's shape and state suggest").add_argument("pid")
    for name in ("accept", "dismiss"):
        p = _signed(g.add_parser(name, help=f"{name} a suggested automation"))
        p.add_argument("pid")
        p.add_argument("suggestion")
    d = _signed(g.add_parser("describe", help="a draft automation from your words, with its summary and dry run"),
                required=False)
    d.add_argument("text")
    d.add_argument("--project")
    d.add_argument("--save", action="store_true", help="set the draft in your name when it checks out")
    d.add_argument("--with-model", action="store_true", help="ask the assistant model when the rules cannot read it")


def _setup(f: Factory, a: Args) -> dict[str, Any]:
    if not a.do:
        return project_setup.checklist(f, a.pid)
    if not a.person or not a.persona:
        raise ValueError("--do is signed: give --person and --persona")
    return project_setup.do(f, a.pid, a.do, person=a.person, persona=a.persona)


def _describe(f: Factory, a: Args, model: Callable[[], Any]) -> dict[str, Any]:
    project = f.project(a.project) if a.project else None
    out = compose.compose(f, a.text, project=project, model=model() if a.with_model else None)
    if a.save:
        if not (a.person and a.persona):
            raise ValueError("--save is signed: give --person and --persona")
        if not out["ok"]:
            raise ValueError(f"the draft does not check out: {out['why']}")
        from kernel import automations as au

        out["saved"] = au.add(f, out["draft"], person=a.person, persona=a.persona)
    return out


def handlers(show: Callable[[Any], None], model: Callable[[], Any]) -> dict[str, Callable[[Factory, Args], None]]:
    commands: dict[str, Callable[[Factory, Args], Any]] = {
        "setup": _setup,
        "automations suggest": lambda f, a: suggest.scan(f, a.pid),
        "automations accept": lambda f, a: suggest.accept(f, a.pid, a.suggestion, person=a.person, persona=a.persona),
        "automations dismiss": lambda f, a: suggest.dismiss(f, a.pid, a.suggestion, person=a.person,
                                                            persona=a.persona),
        "automations describe": lambda f, a: _describe(f, a, model),
    }
    out: dict[str, Callable[[Factory, Args], None]] = {
        name: (lambda c: lambda f, a: show(c(f, a)))(command) for name, command in commands.items()}
    out.update(project_archive.handlers(show))
    return out
