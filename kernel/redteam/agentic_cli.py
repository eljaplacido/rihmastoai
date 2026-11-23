"""`python -m kernel.redteam agentic`: red-team an LLM-facing surface the factory runs, from the command line.

    python -m kernel.redteam agentic <project> --surface embed|assistant [--model worst-case|gnomon|none]
                                     [--via direct|http] [--category C ...] [--home DIR]
                                     [--sarif OUT] [--markdown OUT] [--json]

It runs inside a scope a person with the `it` or `compliance` persona authorised for that surface
(`kernel/redteam/scope.py`). `--model worst-case` (the default) is a scripted model on the attacker's
side: a clean run shows the factory's guards hold even when the model is compromised. `--model
gnomon` asks the real model, where the server would run it (the embed chat in its own lane, the
assistant in the analyst lane). `--via http` starts the factory's own server on 127.0.0.1 (the embed
server, or the cockpit) on the sandbox and drives it over loopback, with that server's model (`none`
or `gnomon`).

Exit codes: 0 passed, 1 failed (findings), 2 a usage or input error, 3 refused by the scope (nothing
was sent), 4 not measured.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kernel.model import Model
from kernel.redteam.agentic_report import AgenticReport, markdown, write_sarif
from kernel.redteam.report import NothingMeasured
from kernel.redteam.scope import SURFACES

EXIT = {"passed": 0, "failed": 1, "not measured": 4}
USAGE, REFUSED = 2, 3
MODELS = ("worst-case", "gnomon", "none")


def _err(text: str) -> None:
    """Say why on standard error, prefixed like the red team's other commands."""
    sys.stderr.write("redteam: " + text + "\n")


def model_for(choice: str, surface: str) -> Model | None:
    """The model the surface asks in process: the worst case, the real one (as the server would run
    it: the embed chat in its own lane, the assistant in the analyst lane), or none."""
    if choice == "none":
        return None
    if choice == "worst-case":
        from kernel.model import FakeModel
        from kernel.redteam.surfaces import worst_case

        return FakeModel(worst_case)
    from kernel.lanes import ensure_analyst_lane, lanes_root, load_routing
    from kernel.model import GnomonModel

    if surface == "embed":
        return GnomonModel(ensure_analyst_lane(load_routing(), root=lanes_root() / "embed"), timeout=60)
    return GnomonModel(ensure_analyst_lane(load_routing()), timeout=180)


def _run(args: argparse.Namespace) -> AgenticReport:
    from kernel.redteam.agentic import run
    from kernel.store import Factory

    project = Factory(args.home).project(args.project)
    if args.via == "http":
        from kernel.redteam.launch import cockpit_server, embed_server

        serve = (embed_server if args.surface == "embed" else cockpit_server)(args.model)
        return run(project, args.surface, model=None, model_label=f"{args.model} (the server's own)", via="http",
                   serve=serve, categories=args.category)
    return run(project, args.surface, model=model_for(args.model, args.surface), model_label=args.model,
               categories=args.category)


def _write(report: AgenticReport, args: argparse.Namespace, code: int) -> int:
    if args.sarif:
        try:
            write_sarif(args.sarif, report)
        except NothingMeasured as exc:
            _err(f"not measured: {exc}")
            code = EXIT["not measured"]
    text = markdown(report)
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(text + "\n", encoding="utf-8", newline="\n")
    out = json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json else text
    sys.stdout.write(out + "\n")
    return code


def command(args: argparse.Namespace) -> int:
    """Run the agentic red team as the arguments say; the exit code."""
    from kernel.redteam.corpus import CorpusError
    from kernel.redteam.scope import ScopeRefused

    if args.via == "http" and args.model == "worst-case":
        _err("over http the server runs its own model (none or gnomon); the worst case runs with --via direct")
        return USAGE
    try:
        report = _run(args)
    except ScopeRefused as exc:
        _err(f"refused, nothing was sent: {exc}")
        return REFUSED
    except (KeyError, ValueError, CorpusError, OSError) as exc:
        _err(str(exc))
        return USAGE
    return _write(report, args, EXIT.get(report.verdict, 1))


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add `agentic` to the red team's command line."""
    ag = sub.add_parser("agentic", help="red-team an LLM-facing surface the factory runs (embed chat, assistant)")
    ag.add_argument("project", help="the project whose surface is red-teamed, and whose ledger holds the scope")
    ag.add_argument("--surface", choices=SURFACES, required=True)
    ag.add_argument("--model", choices=MODELS, default="worst-case",
                    help="worst-case (a scripted attacker's model, the default), gnomon (the real model) or none")
    ag.add_argument("--via", choices=("direct", "http"), default="direct",
                    help="direct: the surface's kernel code in process; http: the factory's own server on loopback")
    ag.add_argument("--category", action="append",
                    help="only this category of the payload corpus (repeatable), e.g. action_abuse")
    ag.add_argument("--home", help="the factory home (default $RIHMA_HOME, $GNOMONFACTORY_HOME or var/)")
    ag.add_argument("--sarif", help="write SARIF 2.1.0 here, for `rihma security ingest`")
    ag.add_argument("--markdown", help="also write the summary here")
    ag.add_argument("--json", action="store_true", help="print the full report as JSON")
    ag.set_defaults(run=command)
