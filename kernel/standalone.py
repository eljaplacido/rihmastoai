"""The commands for using a part of Rihmasto (docs/guides/use-only-what-you-need.md), part of `rihmasto`
(kernel/cli.py adds them with one line, like kernel/graph_ask.py and kernel/integrations.py):

    rihmasto modules show [--project PID] | modules presets
    rihmasto modules set (--preset spec_only | --modules intake,plan | --enable M | --disable M | --inherit)
                         [--project PID] --person Aino --persona business_owner [--reason "..."]
    rihmasto repo attach "Title" --repo PATH [--contract FILE | --spec FILE] [--branch B] --person ... --persona ...
    rihmasto repo list | repo contract <pid> (--contract FILE | --spec FILE) --person ... --persona ...
    rihmasto repo gate <pid> [--head REV] [--base REV] [--task T-001] [--no-verifier] --person ... --persona ...
    rihmasto repo holdouts <pid> [--import DIR] [--author] [--base-url URL] --person ... --persona ...
    rihmasto repo scan <pid> [--revision REV] [--exclude GLOB] --person ... --persona ...
    rihmasto repo releases <pid> [--tag v1.0] [--check] --person ... --persona ...
    rihmasto contract export <pid> --out DIR --person ... --persona ...

Every write is signed by a named person and persona and recorded in the ledger. `repo gate` exits 0 when
the gate passed, 1 when it failed or found a violation, and 4 when it is not measured (or escalates).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import attach, gate_external, modules, repo_checks, spec_export
from kernel.integrations import _leaf  # a command with its help line and positionals, as the integrations add them
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace


def _signed(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("--person", required=True, help="the person who asks: recorded with the result")
    p.add_argument("--persona", required=True, choices=PERSONAS)
    return p


def _contract_source(p: argparse.ArgumentParser, *, required: bool) -> None:
    src = p.add_mutually_exclusive_group(required=required)
    src.add_argument("--contract", help="a contract file (gnomonfactory.contract/1); its hash is checked")
    src.add_argument("--spec", help="a spec file (JSON), compiled into a contract with no model")


def _modules_parsers(sub: Any) -> None:
    mod = sub.add_parser("modules", help="the parts of Rihmasto in use (kernel/modules.py)").add_subparsers(
        dest="sub", required=True)
    _leaf(mod, "show", "the modules, the presets, and the set in force").add_argument("--project")
    _leaf(mod, "presets", "the usual starting points: what you bring, what you get")
    s = _signed(_leaf(mod, "set", "choose the factory's set, or a project's own"))
    how = s.add_mutually_exclusive_group()
    how.add_argument("--preset", choices=list(modules.PRESETS))
    how.add_argument("--modules", help="a comma-separated list of modules")
    how.add_argument("--inherit", action="store_true", help="a project follows the factory's set again")
    s.add_argument("--enable", action="append", default=[], choices=list(modules.MODULES))
    s.add_argument("--disable", action="append", default=[], choices=list(modules.MODULES))
    s.add_argument("--project", help="give this project its own set")
    s.add_argument("--reason", default="")


def _repo_parsers(sub: Any) -> None:
    repo = sub.add_parser("repo", help="a repository of your own: gate, scan, releases (kernel/attach.py)"
                          ).add_subparsers(dest="sub", required=True)
    s = _signed(_leaf(repo, "attach", "attach a git repository on this machine; nothing is copied or written there",
                      "title"))
    s.add_argument("--repo", required=True, help="the repository's folder")
    s.add_argument("--branch", help="the branch changes are judged against (default: the checked-out one)")
    _contract_source(s, required=False)
    _leaf(repo, "list", "the attached repositories")
    _contract_source(_signed(_leaf(repo, "contract", "give an attached repository its contract", "pid")), required=True)
    s = _signed(_leaf(repo, "gate", "judge a change with the gate; you merge", "pid"))
    s.add_argument("--head", help="the change's last commit (default: HEAD; uncommitted changes are not judged)")
    s.add_argument("--base", help="where the change starts (default: where it leaves the attached branch)")
    s.add_argument("--task", help="the contract task it serves: its criteria are traced and must fail first")
    s.add_argument("--no-verifier", dest="verifier", action="store_false",
                   help="leave out the independent verifier: the gate is then not measured, never passed")
    s = _signed(_leaf(repo, "holdouts", "holdout scenarios: import, author, run against your service", "pid"))
    s.add_argument("--import", dest="import_dir", help="a folder of scenarios outside the repository")
    s.add_argument("--author", action="store_true", help="the holdout author writes the missing ones (Gnomon)")
    s.add_argument("--base-url", help="run them against the service you started here")
    s = _signed(_leaf(repo, "scan", "Rihmasto's own static scan into the security gate", "pid"))
    s.add_argument("--revision", help="a committed revision (default: HEAD)")
    s.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    s = _signed(_leaf(repo, "releases", "record the repository's releases (its tags) for evidence", "pid"))
    s.add_argument("--tag", action="append", help="only this tag; repeatable")
    s.add_argument("--check", action="store_true", help="also run the suite and the trace at each release")
    con = sub.add_parser("contract", help="the contract as files (kernel/spec_export.py)").add_subparsers(
        dest="sub", required=True)
    _signed(_leaf(con, "export", "write the spec, the contract, the check plan and a report", "pid")).add_argument(
        "--out", required=True, metavar="DIR")


def add_parsers(sub: Any) -> None:
    """`rihmasto modules ...`, `rihmasto repo ...` and `rihmasto contract export`, as kernel/cli.py adds them."""
    _modules_parsers(sub)
    _repo_parsers(sub)


# -- the handlers -----------------------------------------------------------------------------------------

def _show(f: Factory, a: Args) -> dict[str, Any]:
    view = modules.view(f)
    out = {"factory": view["factory"], "projects_with_their_own_set": view["projects"],
           "modules": [{k: m[k] for k in ("id", "label", "adds", "depends", "outputs", "planned")} | {
               "on": m["id"] in view["factory"]["modules"]} for m in view["catalogue"]],
           "core": view["core"]["adds"]}
    if a.project:
        out["project"] = {"id": a.project, **modules.project_set(f.project(a.project))}
    return out


def _set(f: Factory, a: Args) -> dict[str, Any]:
    target = f.project(a.project) if a.project else f
    listed = [m.strip() for m in a.modules.split(",") if m.strip()] if a.modules is not None else None
    return modules.set_modules(target, person=a.person, persona=a.persona, preset=a.preset, modules=listed,
                               enable=a.enable, disable=a.disable, inherit=a.inherit, reason=a.reason)


def _attach(f: Factory, a: Args) -> dict[str, Any]:
    p = attach.attach(f, a.title, repo=a.repo, person=a.person, persona=a.persona, contract=a.contract, spec=a.spec,
                      branch=a.branch)
    return {"project": p.pid, **(p.meta.get("attached") or {}), "contract": p.meta.get("contract_revision"),
            "next": (attach.attached_state(p) or {}).get("why")}


def _contract(f: Factory, a: Args) -> dict[str, Any]:
    doc = attach.give_contract(f.project(a.pid), person=a.person, persona=a.persona, contract=a.contract, spec=a.spec)
    return {"project": a.pid, "revision": (doc or {}).get("revision"), "counts": (doc or {}).get("counts")}


def handlers(emit: Callable[[Any], None], model: Callable[[], Any]) -> dict[str, Callable[[Factory, Args], Any]]:
    """The commands as `rihmasto` runs them: each prints what it returns; `repo gate` exits by its verdict."""
    def gate(f: Factory, a: Args) -> int:
        out = gate_external.gate(f.project(a.pid), person=a.person, persona=a.persona, head=a.head, base=a.base,
                                 task=a.task, verifier=a.verifier)
        emit(out)
        return gate_external.exit_code(out["verdict"], out.get("held"))

    table: dict[str, Callable[[Factory, Args], Any]] = {
        "modules show": _show,
        "modules presets": lambda f, a: {"presets": modules.view(f)["presets"]},
        "modules set": _set,
        "repo attach": _attach,
        "repo list": lambda f, a: {"attached": attach.attached(f)},
        "repo contract": _contract,
        "repo holdouts": lambda f, a: gate_external.holdouts(
            f.project(a.pid), person=a.person, persona=a.persona, import_dir=a.import_dir, author=a.author,
            base_url=a.base_url, model=model),
        "repo scan": lambda f, a: repo_checks.scan(f.project(a.pid), person=a.person, persona=a.persona,
                                                   revision=a.revision, exclude=tuple(a.exclude)),
        "repo releases": lambda f, a: repo_checks.record_releases(f.project(a.pid), person=a.person,
                                                                  persona=a.persona, only=a.tag, check=a.check),
        "contract export": lambda f, a: spec_export.export(f.project(a.pid), a.out, person=a.person,
                                                           persona=a.persona),
    }
    def printing(command: Callable[[Factory, Args], Any]) -> Callable[[Factory, Args], None]:
        return lambda f, a: emit(command(f, a))

    return {**{name: printing(command) for name, command in table.items()}, "repo gate": gate}
