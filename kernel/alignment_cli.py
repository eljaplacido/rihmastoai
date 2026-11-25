"""The alignment commands (FR-ALN1, docs/guides/alignment.md), part of `rihmasto` (kernel/cli.py).

    rihmasto structure <folder> [--json]          a repository's own structure: specs, decisions, contracts,
                                                  tests, tasks, CI, quality tools, AI tools; nothing is run
    rihmasto align <pid> [--json]                 the alignment proposed for an adopted or attached project
    rihmasto align <pid> --scan --person ... --persona ...      read the repository again (signed)
    rihmasto align <pid> --drift [--json]         what changed since the scan before: new, changed, removed
    rihmasto align <pid> accept|reject <item>... --person ... --persona ... [--reason ...]
    rihmasto align <pid> edit <item> --set field=value [--set ...] --person ... --persona ...

Reading never writes. A scan and a decision are signed by a named person and persona and recorded in the
project's ledger; accepted requirements and criteria go into the project's contract, never into the
repository. A refusal is a message on stderr with exit 2.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import alignment_records as ar
from kernel import repo_structure
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace
ACTIONS = ("accept", "reject", "edit")


def add_parsers(sub: Any) -> None:
    """Add `structure` and `align` to `rihmasto`'s subcommands."""
    s = sub.add_parser("structure", help="a repository's own development structure, by rule; nothing is run")
    s.add_argument("folder")
    s.add_argument("--json", action="store_true")
    a = sub.add_parser("align", help="align an adopted or attached project with its repository's own specs and tests")
    a.add_argument("pid")
    a.add_argument("action", nargs="?", choices=ACTIONS, help="accept, reject or edit the items named after it")
    a.add_argument("items", nargs="*", help="item ids, as `rihmasto align <pid>` lists them")
    a.add_argument("--scan", action="store_true", help="read the repository again and propose (signed)")
    a.add_argument("--drift", action="store_true", help="only what changed since the scan before")
    a.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE", help="with edit: a field's new value")
    a.add_argument("--reason", default="")
    a.add_argument("--json", action="store_true")
    # Left out unless given, so reading needs no signature; a scan or a decision is refused without them.
    a.add_argument("--person", default=argparse.SUPPRESS, help="the named person who signs a scan or a decision")
    a.add_argument("--persona", default=argparse.SUPPRESS, choices=PERSONAS)


def _signer(args: Args) -> tuple[str, str]:
    person, persona = getattr(args, "person", None), getattr(args, "persona", None)
    if not (person and persona):
        raise ar.AlignRefused("a scan or a decision is signed: name --person and --persona")
    return person, persona


def _edits(args: Args) -> dict[str, dict[str, Any]]:
    if len(args.items) != 1 or not args.set:
        raise ar.AlignRefused("edit one item with one or more --set FIELD=VALUE")
    fields: dict[str, Any] = {}
    for pair in args.set:
        field, sep, value = pair.partition("=")
        if not sep or not field.strip():
            raise ar.AlignRefused(f"--set takes FIELD=VALUE, got {pair!r}")
        fields[field.strip()] = value.strip().lower() in ("1", "true", "yes", "done") if field.strip() == "done" \
            else value
    return {args.items[0]: fields}


def align(factory: Factory, args: Args) -> dict[str, Any]:
    project = factory.project(args.pid)
    if args.action:
        person, persona = _signer(args)
        if not args.items:
            raise ar.AlignRefused(f"name the items to {args.action}")
        edits = _edits(args) if args.action == "edit" else None
        return ar.decide(project, args.items, "accept" if args.action == "edit" else args.action, person=person,
                         persona=persona, edits=edits, reason=args.reason)
    if args.scan:
        person, persona = _signer(args)
        return ar.scan(project, person=person, persona=persona)
    out = ar.view(project)
    if args.drift and out.get("scanned"):
        index = {i["id"]: i for g in out["groups"] for i in g["items"]}
        d = out["drift"]
        return {"project": project.pid, "since": d["since"], "scan": out["scan"]["n"],
                "new": [_brief(index[i]) for i in d["new"]], "changed": [_brief(index[i]) for i in d["changed"]],
                "removed": d["removed"]}
    return out


def _brief(i: dict[str, Any]) -> dict[str, Any]:
    return {"id": i["id"], "group": i["group"], "title": i["title"], "status": i["status"]}


def _render_decision(out: dict[str, Any]) -> str:
    n = len(out["items"])
    what = f"{out['verdict']}ed {n} item{'' if n == 1 else 's'}: {', '.join(out['items'])}"
    return what + (f"\nThe contract is now {out['contract']} ({out['how']})." if out.get("contract") else "")


def _render_drift(out: dict[str, Any]) -> str:
    lines = [f"Drift of scan {out['scan']} since scan {out['since'] or '-'}:"]
    lines += [f"  {k}: {i['id']} [{i['group']}] {i['title']} ({i['status']})" for k in ("new", "changed")
              for i in out[k]]
    lines += [f"  removed: {i['id']} [{i['group']}] {i['title']}" for i in out["removed"]]
    return "\n".join(lines if len(lines) > 1 else lines + ["  nothing changed"])


def render(out: dict[str, Any]) -> str:
    """The alignment as a terminal shows it."""
    if "verdict" in out:
        return _render_decision(out)
    if "since" in out and "groups" not in out:
        return _render_drift(out)
    if not out.get("applies"):
        return out["why"]
    if not out.get("scanned"):
        return "Not aligned yet: `rihmasto align <pid> --scan --person \"Your Name\" --persona developer` reads it."
    return _render_view(out)


def _render_view(out: dict[str, Any]) -> str:
    s = out["scan"]
    lines = [f"Scan {s['n']} of {s['read_from']}, by {s['by']['person']} ({s['by']['persona']})",
             out["summary"]["text"], ""]
    for g in out["groups"]:
        lines.append(f"{g['label']} ({len(g['items'])}, {g['open']} to decide)")
        for i in g["items"][:60]:
            conf = f" [{i['confidence']:.2f} {i['basis']}]" if "confidence" in i else ""
            lines.append(f"  {i['id']}  {i['status']:<8} {i['title']}{conf}")
    lines += ["", "Suggested changes for your repository (never written there):"]
    lines += [f"  {x['title']}" for x in out["suggestions"]] or ["  none"]
    return "\n".join(lines)


def handlers(show: Callable[[Any], None], echo: Callable[[str], None] = print
             ) -> dict[str, Callable[[Factory, Args], None]]:
    """The commands as `rihmasto` runs them."""
    def structure(factory: Factory, args: Args) -> None:
        try:
            found = repo_structure.from_folder(args.folder)
        except ValueError as exc:
            raise ar.AlignRefused(str(exc)) from None
        if args.json:
            show(found)
        else:
            echo(repo_structure.render(found))

    def run(factory: Factory, args: Args) -> None:
        out = align(factory, args)
        if args.json:
            show(out)
        else:
            echo(render(out))

    return {"structure": structure, "align": run}
