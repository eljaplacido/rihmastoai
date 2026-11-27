"""The alignment triage on the command line (FR-ORG1, kernel/alignment_triage.py), part of `rihmasto` (kernel/cli.py).

    rihmasto align-triage <pid> [--json]                      the triage: counts by origin, the advice, the actions
    rihmasto align-triage <pid> --impact ITEM... [--verdict accept|reject|defer] [--json]
                                                              what deciding those items would do; nothing is written
    rihmasto align-triage <pid> --do reject_stale|defer_convention|accept_current|restore [ITEM...]
                                  --person ... --persona ...  one triage action, signed
    rihmasto align-triage <pid> --do defer ITEM... --person ... --persona ...

Reading never writes. An action is signed and recorded in the project's ledger; the repository is never written. A
refusal is a message on stderr with exit 2.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import alignment_impact as imp
from kernel import alignment_records as ar
from kernel import alignment_triage as tri
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace


def add_parsers(sub: Any) -> None:
    a = sub.add_parser("align-triage", help="what to do with an alignment's items: where each comes from, its "
                                            "impact, and the triage actions")
    a.add_argument("pid")
    a.add_argument("items", nargs="*", help="item ids, for --impact, --do defer or --do restore")
    # --impact and --do take their items themselves: a positional after a flag is refused by Python 3.11's argparse
    a.add_argument("--impact", nargs="*", default=None, metavar="ITEM",
                   help="what deciding the items named would do (writes nothing)")
    a.add_argument("--verdict", choices=("accept", "reject", "defer"), default="accept")
    a.add_argument("--do", nargs="+", metavar="ACTION",
                   help="the triage action to take (signed), followed by any item ids")
    a.add_argument("--json", action="store_true")
    # Left out unless given, so reading needs no signature; an action is refused without them.
    a.add_argument("--person", default=argparse.SUPPRESS, help="the named person who signs the action")
    a.add_argument("--persona", default=argparse.SUPPRESS, choices=PERSONAS)


def run(factory: Factory, args: Args) -> dict[str, Any]:
    project = factory.project(args.pid)
    if args.do:
        action, do_items = args.do[0], args.do[1:]
        if action not in tri.ACTIONS:
            raise ar.AlignRefused(f"unknown triage action {action!r}; choose from {', '.join(tri.ACTIONS)}")
        person, persona = getattr(args, "person", None), getattr(args, "persona", None)
        if not (person and persona):
            raise ar.AlignRefused("a triage action is signed: name --person and --persona")
        out = tri.act(project, action, person=person, persona=persona, items=(do_items or args.items) or None)
        return {k: v for k, v in out.items() if k != "alignment"}
    if args.impact is not None:
        return imp.impact(project, args.impact or args.items, args.verdict)
    view = ar.view(project)
    if not view.get("scanned"):
        raise ar.AlignRefused(f"{project.pid} has not been aligned yet: rihmasto align {project.pid} --scan reads it")
    return {"project": project.pid, "scan": view["scan"]["n"], "triage": view["triage"],
            "groups": {g["id"]: g["origins"] | {"open": g["open"], "deferred": g["deferred"]} for g in view["groups"]}}


def render(out: dict[str, Any]) -> str:
    if "done" in out:
        return out["said"]
    if "verdict" in out:
        return "\n".join([out["said"], "Items: " + ", ".join(out["items"])])
    t = out["triage"]
    lines = [t["said"], ""] + [f"- {a['text']}" for a in t["advice"]] + [""]
    lines += [f"{a['label']} ({a['count']}): rihmasto align-triage {out['project']} --do {a['do']} --person ... "
              f"--persona ...\n  {a['impact']}" for a in t["actions"]]
    lines += ["", "By group (to decide: from your project / Rihmasto's convention / may be an old plan):"]
    lines += [f"  {g}: {c['open']} ({c['project']} / {c['convention']} / {c['old']})"
              + (f", {c['deferred']} deferred" if c["deferred"] else "") for g, c in out["groups"].items()]
    return "\n".join(lines)


def handlers(show: Callable[[Any], None], echo: Callable[[str], None] = print
             ) -> dict[str, Callable[[Factory, Args], None]]:
    def go(factory: Factory, args: Args) -> None:
        out = run(factory, args)
        if args.json:
            show(out)
        else:
            echo(render(out))

    return {"align-triage": go}
