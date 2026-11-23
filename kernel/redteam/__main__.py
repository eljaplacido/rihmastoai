"""python -m kernel.redteam: Rihmasto's own security checks from the command line.

    python -m kernel.redteam static <path> [<path> ...] [--root DIR] [--exclude GLOB ...] [--sarif OUT]
                                    [--markdown OUT] [--json]
    python -m kernel.redteam dynamic <project> --env <environment> [--slot SLOT] [--budget N] [--home DIR]
                                     [--sarif OUT] [--markdown OUT] [--json]
    python -m kernel.redteam rules [--dynamic] [--json]
    python -m kernel.redteam agentic <project> --surface embed|assistant [--model ...] [--via direct|http]

`agentic` red-teams an LLM-facing surface the factory runs, inside a scope a person authorised
(kernel/redteam/agentic_cli.py says how; it also exits 3 when the scope refuses, nothing sent).

`static` and `dynamic` print the summary (or the full report with --json), and write SARIF 2.1.0
for the security gate with --sarif (`rihma security ingest <pid> OUT` reads it). A scan that
measured nothing writes no SARIF: an empty log would read as a pass. `dynamic` probes the slot of
the environment the factory runs, inside a scope a person with the `it` or `compliance` persona
authorised (`kernel/redteam/scope.py`); a target the scope does not allow is refused before any
request is sent.

Exit codes: 0 passed, 1 failed (findings), 2 a usage or input error, 3 refused by the scope
(nothing was sent), 4 not measured.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from kernel.redteam import agentic_cli
from kernel.redteam.client import DEFAULT_BUDGET
from kernel.redteam.dynamic import scan_environment
from kernel.redteam.report import NothingMeasured, Report, markdown, write_sarif
from kernel.redteam.rules import catalogue
from kernel.redteam.scope import ScopeRefused
from kernel.redteam.static import scan
from kernel.roads import ENVIRONMENTS, SLOTS
from kernel.store import Factory

EXIT = {"passed": 0, "failed": 1, "not measured": 4}
REFUSED = 3


def _out(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _err(text: str) -> None:
    sys.stderr.write(f"redteam: {text}\n")


def _emit(report: Report, args: argparse.Namespace) -> int:
    """Write the files asked for, print the report, and return the exit code of its verdict."""
    code = EXIT.get(report.verdict, 1)
    if args.sarif:
        try:
            write_sarif(args.sarif, report)
        except NothingMeasured as exc:
            _err(f"not measured: {exc}")
            code = EXIT["not measured"]
    if args.markdown:
        Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown).write_text(markdown(report) + "\n", encoding="utf-8", newline="\n")
    _out(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json else markdown(report))
    return code


def _static(args: argparse.Namespace) -> int:
    try:
        report = scan(args.paths, root=args.root, exclude=args.exclude or ())
    except FileNotFoundError as exc:
        _err(str(exc))
        return 2
    return _emit(report, args)


def _dynamic(args: argparse.Namespace) -> int:
    try:
        project = Factory(args.home).project(args.project)
        report = scan_environment(project, args.env, args.slot, budget=args.budget)
    except ScopeRefused as exc:
        _err(f"refused, nothing was sent: {exc}")
        return REFUSED
    except (LookupError, ValueError) as exc:
        _err(str(exc.args[0]) if exc.args else type(exc).__name__)
        return 2
    return _emit(report, args)


def _rules(args: argparse.Namespace) -> int:
    rows = catalogue("dynamic" if args.dynamic else "static")
    if args.json:
        _out(json.dumps(rows, indent=2))
        return 0
    _out("\n".join(f"{r['id']:<20} {r['level']:<8} {r['cwe']:<9} {r['owasp']:<45} {r['title']}" for r in rows))
    return 0


def _outputs(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--sarif", help="write SARIF 2.1.0 here, for `rihma security ingest`")
    sub.add_argument("--markdown", help="also write the summary here")
    sub.add_argument("--json", action="store_true", help="print the full report as JSON")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m kernel.redteam",
                                 description="Rihmasto's own security scanning and red teaming (D-0014).")
    sub = ap.add_subparsers(dest="command", required=True)
    st = sub.add_parser("static", help="scan source and configuration with the static rules")
    st.add_argument("paths", nargs="+", help="files or folders to scan")
    st.add_argument("--root", help="the folder findings are relative to (default: the one folder scanned)")
    st.add_argument("--exclude", action="append", metavar="GLOB",
                    help="a path pattern (relative to --root) not to read, e.g. tests/fixtures/*; listed in the report")
    _outputs(st)
    st.set_defaults(run=_static)
    dy = sub.add_parser("dynamic", help="probe a deployment the factory runs, inside an authorised scope")
    dy.add_argument("project", help="the project id")
    dy.add_argument("--env", required=True, choices=ENVIRONMENTS, help="the environment whose slot is probed")
    dy.add_argument("--slot", default="current", choices=SLOTS, help="the slot (default: current)")
    dy.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="the most requests the run sends")
    dy.add_argument("--home", help="the factory home (default: RIHMA_HOME, or var/ in the repository)")
    _outputs(dy)
    dy.set_defaults(run=_dynamic)
    ru = sub.add_parser("rules", help="list a rule catalogue with CWE and OWASP Top 10 2025 ids")
    ru.add_argument("--dynamic", action="store_true", help="the dynamic layer's rules instead of the static ones")
    ru.add_argument("--json", action="store_true")
    ru.set_defaults(run=_rules)
    agentic_cli.add_parser(sub)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    code: int = args.run(args)
    return code


if __name__ == "__main__":
    sys.exit(main())
