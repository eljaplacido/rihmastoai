"""`rihmasto context` and `rihmasto data`, part of the command line (kernel/cli.py; FR-CTX1).

    rihmasto context map <pid>                       what Rihmasto knows about the project, and where it came from
    rihmasto context packs <pid> [--persona P]       each agent role's context pack: parts, sizes, budget, prefix
    rihmasto context pack <pid> <pack> [--target T] [--question Q] [--persona P]
                                                     one pack, part by part, with what was cut and left out
    rihmasto context audit [<pid>] [--no-commands]   the compression audit; without a project, the whole factory and
                                                     its Context health per role
    rihmasto data                                    the factory home's stores, ledgers, retention and clean-up
    rihmasto data cleanup --person NAME --persona it|operations
                                                     propose a clean-up of what can go safely, signed
    rihmasto data apply <CU-id> --person NAME --persona it|operations
                                                     carry out a proposal, each item checked unchanged first

Reading writes nothing. A pack's content is printed only for a persona that may see it, and anything of the
holdout custody never.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import context_audit, context_map, context_packs, context_parts, data_stores
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace


def add_parsers(sub: Any) -> None:
    c = sub.add_parser("context", help="the data and context layer: what Rihmasto knows and what each agent reads")
    cs = c.add_subparsers(dest="sub", required=True)
    m = cs.add_parser("map", help="what Rihmasto knows about a project, and where it came from")
    m.add_argument("pid")
    ps = cs.add_parser("packs", help="each agent role's context pack, in one row each")
    ps.add_argument("pid")
    ps.add_argument("--persona", choices=PERSONAS)
    p = cs.add_parser("pack", help="one context pack, part by part")
    p.add_argument("pid")
    p.add_argument("pack", choices=list(context_packs.PACKS))
    p.add_argument("--target", help="a task (T-001), a perspective, a change card or a role, as the pack takes")
    p.add_argument("--question", help="for Ask Rihma, goal help and the agent channel: the question asked")
    p.add_argument("--persona", choices=PERSONAS, help="whose view: the content is shown to a persona allowed it")
    a = cs.add_parser("audit", help="the compression audit, for a project or the whole factory")
    a.add_argument("pid", nargs="?")
    a.add_argument("--no-commands", action="store_true", help="skip measuring the commands' JSON")
    d = sub.add_parser("data", help="the factory home's stores, ledgers, retention and clean-up")
    ds = d.add_subparsers(dest="sub", required=False)
    cu = ds.add_parser("cleanup", help="propose a clean-up of what can go safely, signed")
    cu.add_argument("--person", required=True)
    cu.add_argument("--persona", required=True, choices=PERSONAS)
    ap = ds.add_parser("apply", help="carry out a clean-up proposal")
    ap.add_argument("id", help="the proposal, such as CU-0001")
    ap.add_argument("--person", required=True)
    ap.add_argument("--persona", required=True, choices=PERSONAS)


def _pack(f: Factory, a: Args) -> dict[str, Any]:
    from kernel.custody import held_strings

    project = f.project(a.pid)
    try:
        built = context_packs.build(f, project, a.pack, target=a.target, persona=a.persona, question=a.question)
    except context_packs.Unavailable as exc:
        return {"id": a.pack, "unavailable": str(exc)}
    return context_parts.shown(built, a.persona, held_strings(f.holdouts_dir, f.projects_dir))


def handlers(emit: Callable[[Any], None]) -> dict[str, Callable[[Factory, Args], Any]]:
    return {
        "context map": lambda f, a: emit(context_map.context_map(f, f.project(a.pid))),
        "context packs": lambda f, a: emit({"project": a.pid, "packs": [
            p if "unavailable" in p else context_parts.summary(p)
            for p in context_packs.every(f, f.project(a.pid), persona=a.persona)]}),
        "context pack": lambda f, a: emit(_pack(f, a)),
        "context audit": lambda f, a: emit(context_audit.audit(f, a.pid, commands=not a.no_commands)),
        "data": lambda f, a: emit(data_stores.view(f)),
        "data cleanup": lambda f, a: emit(data_stores.propose_cleanup(f, person=a.person, persona=a.persona)),
        "data apply": lambda f, a: emit(data_stores.apply_cleanup(f, a.id, person=a.person, persona=a.persona)),
    }
