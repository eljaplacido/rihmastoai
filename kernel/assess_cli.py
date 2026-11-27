"""The assessment's commands (kernel/assess.py), part of `rihmasto` (kernel/cli.py adds them).

    rihmasto assess <pid> --person Aino --persona developer [--with-model] [--ref main]
    rihmasto assessment list <pid>                       every version, with its sha256 checked
    rihmasto assessment show <pid> [--version AS-2] [--full]
    rihmasto assessment compare <pid> [--from AS-1] [--to AS-2]
    rihmasto assessment change <pid> F-2 P-1 --person Aino --persona developer [--as new_requirement]
    rihmasto assessment verdict <pid> F-4 --verdict not_relevant --reason "..." --person Aino --persona developer
    rihmasto assessment runner <pid> --command "make gates" [--results build/gates.xml] --person Aino --persona it

`assess` and `assessment change` are signed by a named person: who asked for the assessment, and who
filed a finding as a change. The rest only read.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import assess, assess_cards
from kernel.people import PERSONAS

Emit = Callable[[Any], None]


def _signer(p: argparse.ArgumentParser, about: str) -> argparse.ArgumentParser:
    p.add_argument("--person", required=True, help=about)
    p.add_argument("--persona", required=True, choices=PERSONAS)
    return p


def add_parsers(sub: Any) -> None:
    """`rihmasto assess` and `rihmasto assessment ...`, as the command line's parser adds them."""
    from kernel.change import CLASSES

    p = _signer(sub.add_parser("assess", help="assess an adopted system from every perspective (kernel/assess.py)"),
                "who asks for the assessment")
    p.add_argument("pid")
    p.add_argument("--with-model", action="store_true",
                   help="the intake panel's perspectives propose further findings (model_proposed, never facts)")
    p.add_argument("--ref", default="main", help="the branch or revision of the mirror to assess (default main)")
    cmds = sub.add_parser("assessment", help="the recorded assessments of a project").add_subparsers(
        dest="sub", required=True)
    cmds.add_parser("list", help="every version, oldest first").add_argument("pid")
    show = cmds.add_parser("show", help="one version (the latest by default), in short")
    show.add_argument("pid")
    show.add_argument("--version", help="AS-<n> or <n>")
    show.add_argument("--full", action="store_true", help="the whole record, every check with its evidence")
    cmp = cmds.add_parser("compare", help="what changed between two versions (the latest two by default)")
    cmp.add_argument("pid")
    cmp.add_argument("--from", dest="older")
    cmp.add_argument("--to", dest="newer")
    chg = _signer(cmds.add_parser("change", help="file chosen findings as change cards"), "who files the changes")
    chg.add_argument("pid")
    chg.add_argument("ids", nargs="+", help="finding ids: F-<n> (the rules') or P-<n> (the panel's)")
    chg.add_argument("--version", help="the assessment the ids are from (default: the latest)")
    chg.add_argument("--as", dest="as_class", default=assess.CLASS_DEFAULT, choices=CLASSES,
                     help="how the change is triaged (default new_requirement: a business decision first)")
    from kernel.assess_precise import VERDICTS  # a precise assessment (FR-ASP1)

    ver = _signer(cmds.add_parser("verdict", help="a finding not relevant here, or a secret a fixture or real"),
                  "who gives the verdict")
    ver.add_argument("pid")
    ver.add_argument("finding", help="a finding of the latest assessment: F-<n> or P-<n>")
    ver.add_argument("--verdict", required=True, choices=VERDICTS)
    ver.add_argument("--reason", help="why (required for not_relevant)")
    ver.add_argument("--also", nargs="*", default=[], help="findings like it, given the same verdict")
    run = _signer(cmds.add_parser("runner", help="map the command the project runs its own tests with"),
                  "who maps it")
    run.add_argument("pid")
    run.add_argument("--command", required=True, help="the project's own test command, as it states it")
    run.add_argument("--results", help="the results file it writes, in the repository (JUnit XML or JSON counts)")
    run.add_argument("--note", help="where it runs, in a few words")


def _assess(f: Any, a: argparse.Namespace, model: Callable[[], Any]) -> dict[str, Any]:
    record = assess.assess(f.project(a.pid), person=a.person, persona=a.persona,
                           model=model() if a.with_model else None, ref=a.ref)
    return assess.summary(record)


def _list(f: Any, a: argparse.Namespace) -> dict[str, Any]:
    project = f.project(a.pid)
    return {"project": a.pid, "assessments": assess.checked(project)}


def _show(f: Any, a: argparse.Namespace) -> dict[str, Any]:
    record = assess.load(f.project(a.pid), a.version)
    return record if a.full else assess.summary(record)


def handlers(emit: Emit, model: Callable[[], Any]) -> dict[str, Callable[[Any, Any], None]]:
    """The assessment's handlers. ``emit`` prints an answer; ``model`` makes the analyst's model."""
    return {
        "assess": lambda f, a: emit(_assess(f, a, model)),
        "assessment list": lambda f, a: emit(_list(f, a)),
        "assessment show": lambda f, a: emit(_show(f, a)),
        "assessment compare": lambda f, a: emit(assess.compare(f.project(a.pid), a.older, a.newer)),
        "assessment change": lambda f, a: emit(assess_cards.to_changes(
            f.project(a.pid), a.ids, person=a.person, persona=a.persona, version=a.version, as_class=a.as_class)),
        "assessment verdict": lambda f, a: emit(_verdict(f, a)),
        "assessment runner": lambda f, a: emit(_runner(f, a)),
    }


def _verdict(f: Any, a: argparse.Namespace) -> dict[str, Any]:
    from kernel.assess_precise import MARKERS, SECRET_MARKS, give

    if a.verdict in SECRET_MARKS and a.persona not in MARKERS:
        raise PermissionError(f"a secret is judged by a {', '.join(MARKERS)}, not {a.persona}")
    return give(f.project(a.pid), a.finding, a.verdict, person=a.person, persona=a.persona, reason=a.reason,
                also=a.also)


def _runner(f: Any, a: argparse.Namespace) -> dict[str, Any]:
    from kernel.assess_measure import map_runner

    return {"runner": map_runner(f.project(a.pid), command=a.command, results=a.results, note=a.note,
                                 person=a.person, persona=a.persona)}


__all__ = ["add_parsers", "handlers"]
