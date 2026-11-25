"""`rihmasto journey`: the guided journeys on the command line (FR-JRN1, docs/guides/guided-journeys.md).

- ``rihmasto journey list``: the journeys and their steps;
- ``rihmasto journey next [--project PID]``: the next best step, a project's through its journey, or which project
  needs what;
- ``rihmasto journey <name> [--project PID]``: one journey, each step measured from the records, with its command.

Read only: it signs and writes nothing (the steps' own commands do, each signed).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import journey_chat as jc
from kernel import journey_state as js
from kernel import journeys as kj
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace
MARK = {"done": "x", "skipped": "-", "under_way": "~", "todo": " "}


def add_parsers(sub: Any) -> None:
    """Add `journey` to `rihmasto`'s subcommands."""
    p = sub.add_parser("journey", help="a guided journey and the next step, from the records "
                                       "(docs/guides/guided-journeys.md)")
    p.add_argument("name", choices=(*kj.JOURNEYS, "list", "next"),
                   help="a journey, list (every journey), or next (the next best step)")
    p.add_argument("--project", help="the project to measure it on")
    p.add_argument("--persona", choices=PERSONAS, help="whose words: a business persona reads business words")
    p.add_argument("--json", action="store_true", help="the read model as JSON")


def lines(prog: dict[str, Any]) -> list[str]:
    """A journey's steps as lines: [x] done, [~] under way, [-] skipped, [ ] to do, > the next one."""
    out = [f"{prog['label']}" + (f": {prog['title']}" if prog.get("title") else "")
           + f" ({prog['done']} of {prog['total']} done)"]
    for s in prog["steps"]:
        nxt = ">" if s["id"] == prog["next"] else " "
        out.append(f"{nxt}[{MARK.get(s['state'], ' ')}] {s['title']}" + (" (optional)" if s["optional"] else "")
                   + (f": {s['said']}" if s["said"] else ""))
        if s["id"] == prog["next"] and s["command"]:
            out.append(f"      {s['command'].split('   ')[0]}")
    return out


def _project(f: Factory, a: Args) -> Any:
    return f.project(a.project) if a.project else None


def run(f: Factory, a: Args, emit: Callable[[Any], None], show: Callable[[str], None]) -> int:
    if a.name == "list":
        rows = kj.catalogue(a.persona)
        if a.json:
            emit({"journeys": rows})
        else:
            for j in rows:
                show(f"{j['label']} ({j['name']}): {j['about']}")
                show("  " + "; ".join(s["title"] + (" (optional)" if s["optional"] else "") for s in j["steps"]))
        return 0
    project = _project(f, a)
    if a.name == "next":
        out = jc.next_answer(f, project, persona=a.persona)
        if a.json:
            emit(out)
            return 0
        show(out["answer"])
        if out.get("journey"):
            show("\n".join(lines(out["journey"])))
        return 0
    prog = js.progress(f, a.name, project=project, persona=a.persona)
    if a.json:
        emit(prog)
    else:
        show(jc.journey_text(prog))
        show("\n".join(lines(prog)))
    return 0


def handlers(emit: Callable[[Any], None], show: Callable[[str], None] = print
             ) -> dict[str, Callable[[Factory, Args], int | None]]:
    return {"journey": lambda f, a: run(f, a, emit, show)}
