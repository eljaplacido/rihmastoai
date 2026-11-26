"""`rihmasto evals`: Gnomon's audits, benchmarks and evals on a project, and Rihmasto's own evals of its agents
(FR-EVL1), part of `rihmasto` (kernel/cli.py).

    rihmasto evals list [<pid>]                                   the catalogue, and whether each runs here
    rihmasto evals run <pid> --eval security [--set key=value ...] --person P --persona X
    rihmasto evals history [<pid>] [--eval security]               a project's results; no project: the role evals
    rihmasto evals findings <pid>                                  the latest findings, new ones first
    rihmasto evals change <pid> <finding> --person P --persona X    make a finding a change proposal
    rihmasto evals roles [--role analyst] [--model configured --model <model>@<endpoint>] [--for <pid>]
                         --person P --persona X                    compare models on Rihma's own eval sets
    rihmasto evals carry <pid> <request>                           carry out a run the cockpit recorded (its job)

A run streams Gnomon's output as it comes and ends with its result as JSON; it is recorded (``eval_ran``). A
refusal is a message on stderr with exit 2.
"""

from __future__ import annotations

import argparse
import functools
import sys
from collections.abc import Callable
from typing import Any

from kernel import gnomon_evals as ge
from kernel import gnomon_evals_run as gr
from kernel import gnomon_evals_view as gv
from kernel import role_evals as rv
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace
Handler = Callable[[Factory, Args], int | None]


def _who(p: argparse.ArgumentParser) -> None:
    p.add_argument("--person", help="who signs it (with access enforced: your name in the access file)")
    p.add_argument("--persona", choices=PERSONAS, help="the persona you sign as")


def _pair(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("give key=value")
    k, v = text.split("=", 1)
    return k.strip(), v


def add_parsers(sub: Any) -> None:
    cmds = sub.add_parser("evals", help="Gnomon's audits, benchmarks and evals, and Rihma's own role evals"
                          ).add_subparsers(dest="sub", required=True)
    cmds.add_parser("list", help="the catalogue, and whether each runs here").add_argument("pid", nargs="?")
    p = cmds.add_parser("run", help="run one on a project now, recorded")
    p.add_argument("pid")
    p.add_argument("--eval", required=True, dest="eval_id", help=", ".join(ge.BY_ID))
    p.add_argument("--set", type=_pair, action="append", metavar="KEY=VALUE", help="a setting of the eval")
    _who(p)
    p = cmds.add_parser("history", help="a project's results over time; with no project, the role evals")
    p.add_argument("pid", nargs="?")
    p.add_argument("--eval", dest="eval_id")
    cmds.add_parser("findings", help="the latest findings of a project's audits").add_argument("pid")
    p = cmds.add_parser("change", help="make a finding a change proposal")
    p.add_argument("pid")
    p.add_argument("finding")
    _who(p)
    p = cmds.add_parser("roles", help="run Rihma's eval sets per role and compare models or endpoints")
    p.add_argument("--role", choices=rv.ROLES)
    p.add_argument("--model", action="append", help="configured, fallback or <model>@<endpoint> (again for more)")
    p.add_argument("--for", dest="for_project", help="compare for this project: confidential refuses hosted ones")
    _who(p)
    p = cmds.add_parser("carry", help="carry out a run the cockpit recorded (the cockpit's job runs this)")
    p.add_argument("pid")
    p.add_argument("request")


def _signer(a: Args) -> tuple[str, str]:
    if not a.person or not a.persona:
        raise ValueError("name --person and --persona: a run is signed")
    return a.person, a.persona


def _emit(echo: Callable[[str], None]) -> Callable[[str], None]:
    def out(line: str) -> None:
        echo(line)
        sys.stdout.flush()
    return out


def _list(show: Any, f: Factory, a: Args) -> None:
    show({"gnomon": ge.summary_line(), "evals": ge.public(f.project(a.pid) if a.pid else None),
          "role_sets": [{"id": k, **v} for k, v in rv.SETS.items()]})


def _run(show: Any, echo: Any, f: Factory, a: Args) -> int:
    person, persona = _signer(a)
    row = gr.run(f.project(a.pid), a.eval_id, person=person, persona=persona, config=dict(a.set or []),
                 emit=_emit(echo))
    show({k: row.get(k) for k in ("eval", "verdict", "summary", "scores", "issues", "new_findings", "resolved", "at",
                                  "findings")})
    return 0 if row["verdict"] != "failed" else 1


def _history(show: Any, f: Factory, a: Args) -> None:
    if a.pid is None:
        show(rv.view(f))
        return
    show({"project": a.pid, "results": gv.history(f.project(a.pid), a.eval_id)})


def _change(show: Any, f: Factory, a: Args) -> None:
    person, persona = _signer(a)
    show(gr.make_change(f.project(a.pid), a.finding, person=person, persona=persona))


def _roles(show: Any, echo: Any, f: Factory, a: Args) -> None:
    person, persona = _signer(a)
    out = rv.run(f, person=person, persona=persona, role=a.role, models=a.model, for_project=a.for_project,
                 emit=_emit(echo))
    for line in out["lines"]:
        echo(line)
    show({"runs": [{k: r.get(k) for k in ("set", "role", "candidate", "cases", "correct", "score_pct", "refused")}
                   for r in out["runs"]], "lines": out["lines"]})


def _carry(show: Any, echo: Any, f: Factory, a: Args) -> int:
    if a.request.startswith("RR-"):
        out = rv.carry(f, a.request, emit=_emit(echo))
        show({"state": "done", "lines": out["lines"]})
        return 0
    row = gr.carry(f, a.pid, a.request, emit=_emit(echo))
    show({"state": "done", "eval": row["eval"], "verdict": row["verdict"], "summary": row["summary"],
          "new_findings": row["new_findings"]})
    return 0


def handlers(show: Callable[[Any], None], echo: Callable[[str], None]) -> dict[str, Handler]:
    p = functools.partial
    return {"evals list": p(_list, show), "evals run": p(_run, show, echo), "evals history": p(_history, show),
            "evals findings": lambda f, a: show({"project": a.pid, "findings": gr.findings(f.project(a.pid))}),
            "evals change": p(_change, show), "evals roles": p(_roles, show, echo),
            "evals carry": p(_carry, show, echo)}
