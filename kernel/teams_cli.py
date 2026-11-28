"""`rihmasto teams`, `rihmasto vocab` and `rihmasto scope`, part of the command line (kernel/cli.py): teams, the words a
team or a project gives Rihmasto's terms, and what applies where, from a terminal (FR-TM1, FR-TM2, FR-TM3), the same as
the cockpit's Settings and a project's Vocabulary.

    rihmasto teams list                                   every team with its members and projects
    rihmasto teams which <pid>                            the team a project is in
    rihmasto teams create NAME [--member X ...] --person ... --persona it [--reason ...]
    rihmasto teams set TEAM [--name N] [--add X ...] [--remove X ...] --person ... --persona it
    rihmasto teams move <pid> TEAM --person ... --persona it|business_owner|product_owner [--reason ...]
    rihmasto teams undo (--team TEAM | --project PID) --person ... --persona ...
    rihmasto vocab show [--project PID | --team TEAM]     each term: shipped, the team's, the project's, in force
    rihmasto vocab preview (--project PID | --team TEAM) [--term ID] [--label ...] ...   what would read differently
    rihmasto vocab set (--project PID | --team TEAM) [--term ID] [--label ...] [--describe ...] [--synonym X ...]
                       [--hide | --show] [--means kind:ID] [--reset] --reason ... --person ... --persona ...
    rihmasto vocab undo (--project PID | --team TEAM) --person ... --persona ...
    rihmasto scope show [--project PID]                   every setting: its scopes and where its value comes from

The writes are signed and in the ledger, as the cockpit's are; a change of words changes how records are read, never
the records.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import scope_table, teams, vocab, vocab_edit
from kernel.people import PERSONAS

Args = argparse.Namespace


def _signed(p: argparse.ArgumentParser) -> None:
    p.add_argument("--person", required=True)
    p.add_argument("--persona", required=True, choices=PERSONAS)
    p.add_argument("--reason", default="")


def _where(p: argparse.ArgumentParser, *, required: bool) -> None:
    g = p.add_mutually_exclusive_group(required=required)
    g.add_argument("--project")
    g.add_argument("--team")


def _words(p: argparse.ArgumentParser) -> None:
    p.add_argument("--term", help="kind:<id>, rel:<id>, attr:<key> or custom:<slug>; none makes a custom term")
    p.add_argument("--label")
    p.add_argument("--describe", dest="description")
    p.add_argument("--synonym", action="append", dest="synonyms")
    hide = p.add_mutually_exclusive_group()
    hide.add_argument("--hide", action="store_true")
    hide.add_argument("--show", action="store_true")
    p.add_argument("--means", help="a custom term means this kind of record: kind:<id>")
    p.add_argument("--reset", action="store_true", help="give the term back to the layer below")


def add_parsers(sub: Any) -> None:
    """Add `teams`, `vocab` and `scope` to `rihmasto`'s subcommands."""
    t = sub.add_parser("teams", help="teams, each tied to projects (FR-TM1)").add_subparsers(dest="sub", required=True)
    t.add_parser("list", help="every team, with its members and projects")
    which = t.add_parser("which", help="the team a project is in")
    which.add_argument("pid")
    make = t.add_parser("create", help="make a team (IT)")
    make.add_argument("name")
    make.add_argument("--member", action="append", dest="members")
    _signed(make)
    change = t.add_parser("set", help="rename a team or add and remove members (IT)")
    change.add_argument("team")
    change.add_argument("--name")
    change.add_argument("--add", action="append")
    change.add_argument("--remove", action="append")
    _signed(change)
    move = t.add_parser("move", help="move a project to another team (IT or the project's owner)")
    move.add_argument("pid")
    move.add_argument("team")
    _signed(move)
    undo = t.add_parser("undo", help="put back what the last change of a team, or of a project's team, replaced")
    g = undo.add_mutually_exclusive_group(required=True)
    g.add_argument("--team")
    g.add_argument("--project")
    _signed(undo)
    v = sub.add_parser("vocab", help="the words a team or a project gives Rihmasto's terms (FR-TM2)"
                       ).add_subparsers(dest="sub", required=True)
    show = v.add_parser("show", help="each term: shipped, the team's, the project's, which is in force")
    _where(show, required=False)
    prev = v.add_parser("preview", help="how a change would read, and how much reads differently")
    _where(prev, required=True)
    _words(prev)
    setter = v.add_parser("set", help="give a term another word here (IT for a team, IT or the owner for a project)")
    _where(setter, required=True)
    _words(setter)
    _signed(setter)
    vundo = v.add_parser("undo", help="give the earlier reading back exactly")
    _where(vundo, required=True)
    _signed(vundo)
    sc = sub.add_parser("scope", help="what applies where (FR-TM3)").add_subparsers(dest="sub", required=True)
    sc.add_parser("show", help="every setting: its scopes and where its value comes from").add_argument("--project")


def _fields(a: Args) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("label", "description", "means", "synonyms"):
        if getattr(a, key, None) is not None:
            out[key] = getattr(a, key)
    if getattr(a, "hide", False) or getattr(a, "show", False):
        out["hidden"] = True if a.hide else None
    return out


def _scope(f: Any, a: Args) -> tuple[str, str]:
    if a.project:
        f.project(a.project)
        return "project", a.project
    return "team", a.team


def _show(f: Any, a: Args) -> dict[str, Any]:
    project = f.project(a.project) if a.project else None
    eff = vocab.effective(f, project, a.team) if project or a.team else vocab.context(f, None, f.projects())
    changed = [r for r in eff["terms"].values() if r["scope"] != "shipped"]
    return {"team": eff["team"], "project": eff["project"], "terms": changed or "every term reads as shipped"}


def _vocab_set(f: Any, a: Args) -> dict[str, Any]:
    scope, owner = _scope(f, a)
    return vocab_edit.set_term(f, scope, owner, term=a.term, fields=_fields(a), reset=a.reset, person=a.person,
                               persona=a.persona, reason=a.reason)


def _vocab_undo(f: Any, a: Args) -> dict[str, Any]:
    scope, owner = _scope(f, a)
    return vocab_edit.undo(f, scope, owner, person=a.person, persona=a.persona)


COMMANDS: dict[str, Callable[[Any, Args], dict[str, Any]]] = {
    "teams list": lambda f, a: teams.describe(f),
    "teams which": lambda f, a: teams.of_project(f, f.project(a.pid)),
    "teams create": lambda f, a: teams.create(f, a.name, members_=a.members, person=a.person, persona=a.persona,
                                              reason=a.reason),
    "teams set": lambda f, a: teams.update(f, a.team, name=a.name, add=a.add, remove=a.remove, person=a.person,
                                           persona=a.persona, reason=a.reason),
    "teams move": lambda f, a: teams.move_project(f, f.project(a.pid), a.team, person=a.person, persona=a.persona,
                                                  reason=a.reason),
    "teams undo": lambda f, a: teams.undo(f, team=a.team, project=f.project(a.project) if a.project else None,
                                          person=a.person, persona=a.persona),
    "vocab show": _show,
    "vocab preview": lambda f, a: vocab_edit.preview(f, *_scope(f, a), term=a.term, fields=_fields(a), reset=a.reset),
    "vocab set": _vocab_set,
    "vocab undo": _vocab_undo,
    "scope show": lambda f, a: scope_table.describe(f, f.project(a.project) if a.project else None),
}


def handlers(show: Callable[[Any], Any], say: Any = None) -> dict[str, Callable[[Any, Args], int]]:
    """The commands, each printing its answer with ``show``; a refusal is one line and exit 2, as `rihmasto dev`."""
    from kernel import devcli

    return {name: devcli._run(show, name, COMMANDS[name]) for name in sorted(COMMANDS)}
