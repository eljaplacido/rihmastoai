"""`rihmasto scan`, and a folder's preview before `new`, `intake` and `adopt` (docs/guides/inputs.md).

    rihmasto scan <folder> [--exclude GLOB] [--json]     what would be read, summarised, listed and skipped, and
                                                         why, and the characters it comes to; sends nothing
    rihmasto new "Title" --source <folder> [--exclude GLOB] [--yes] [--confidential] [--build-without-waiting] ...
    rihmasto intake <pid> --source <folder> [--exclude GLOB] [--yes]
    rihmasto adopt "Title" --source <folder|repo|url> [--exclude GLOB] [--confidential] ...

A folder given to `new` or `intake` is scanned first, and its map is shown on stderr. Nothing is sent to a
model until the person confirms: `--yes`, or "y" at the prompt when a terminal is attached. Without either
nothing is created and the command exits 2. The confirmed map is recorded in the project with the person
who confirmed it. `--confidential` keeps the project on local models (kernel/confidential.py).

The `new`, `intake` and `adopt` handlers live here (kernel/cli.py is at its size limit); this module also
adds their --exclude, --yes and --confidential options to the parsers kernel/cli.py made.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import confidential, material
from kernel.ide import overview

Emit = Callable[[Any], None]
SHOWN = 40          # rows of one group shown on a terminal; the rest are counted
GROUP_TITLE = {"read": "Read in full", "summarised": "Summarised", "listed": "Listed only, not read",
               "skipped": "Skipped"}


def add_parsers(sub: Any) -> None:
    """`rihmasto scan`, and --exclude, --yes and --confidential on the `new`, `intake` and `adopt` parsers."""
    p = sub.add_parser("scan", help="what Rihmasto would read of a folder, and why; sends nothing")
    p.add_argument("folder")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="drop files; repeatable")
    p.add_argument("--json", action="store_true", help="the material map as JSON")
    b = sub.add_parser("baseline", help="an adopted project: run a test command its instructions state as its "
                                        "baseline (it runs the project's own code: --yes says you agree)")
    b.add_argument("pid")
    b.add_argument("--command", required=True, help="the stated command, exactly as the instructions state it")
    b.add_argument("--person", required=True)
    b.add_argument("--persona", required=True)
    b.add_argument("--yes", action="store_true", help="yes: run the project's own code on this machine")
    for name in ("new", "intake", "adopt"):
        q = sub.choices[name]
        q.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                       help="a folder source: drop matching files (a path, a glob or a folder); repeatable")
        if name != "adopt":
            q.add_argument("--yes", action="store_true", help="send what the folder's scan shows without asking")
        if name == "new":
            q.add_argument("--build-without-waiting", action="store_true",
                           help="at explore or demo, build the spec without waiting for your go-ahead")
        if name != "intake":
            q.add_argument("--confidential", action="store_true",
                           help="confidential: keep on local models (refused while a role's endpoint is hosted)")
        if name == "adopt":
            q.add_argument("--working-copy", action="store_true",
                           help="a git repository: adopt its working copy as it is now (a snapshot), not its "
                                "last commit")
            q.add_argument("--documents", action="store_true",
                           help="a folder of documents only: adopt it to track and evaluate the work")


def _size(n: int) -> str:
    return f"{n:,} chars"


def _group(mp: dict[str, Any], action: str) -> list[str]:
    """One group of the map: its files with their kind, size and why; code files as one count."""
    rows = [r for r in mp["files"] if r["action"] == action]
    code = [r for r in rows if r["kind"] == "code" and action == "listed" and r["why"].startswith("code:")]
    rows = [r for r in rows if r not in code]
    out = [f"{GROUP_TITLE[action]} ({len(rows) + len(code)}):"]
    for r in rows[:SHOWN]:
        what = f"{r['kind']}, {_size(r['chars'])}" if r["chars"] else r["kind"]
        out.append(f"  {r['path']}  [{what}]" + (f"  {r['why']}" if r["why"] else ""))
    if len(rows) > SHOWN:
        out.append(f"  ... and {len(rows) - SHOWN} more")
    if code:
        out.append(f"  {len(code)} code files: counted in the code inventory, not read")
    return [*out, ""]


def render(mp: dict[str, Any], send_to: dict[str, Any] | None = None) -> str:
    """The map as a person reads it on a terminal, grouped by what happens to each file."""
    t = mp["totals"]
    out = [f"Scan of {mp['folder']} (nothing has been sent)", ""]
    for action in material.ACTIONS:
        out += _group(mp, action)
    out += overview(mp.get("agent_context"))       # how the folder's AI tools are set up (kernel/ide.py)
    if mp["skipped_dirs"]:
        out.append("Folders not walked: " + ", ".join(f"{d['path']} ({d['why']})" for d in mp["skipped_dirs"][:12]))
    out += [f"Cut: {c}" for c in mp["cut"][:SHOWN]]
    more = len(mp["cut"]) - SHOWN
    out += [f"Cut: {more} more files for the budget (all of them: --json)"] if more > 0 else []
    where = ""
    if send_to and send_to.get("endpoint"):
        where = (f" to the {send_to['role']} role's endpoint {send_to['endpoint']!r} ({send_to['host']}, "
                 f"{'local' if send_to['local'] else 'hosted'})")
    out.append(f"Total: {t['chars']:,} of {t['budget']:,} characters would be sent{where}.")
    return "\n".join(out) + "\n"


def _confirmed(mp: dict[str, Any], args: argparse.Namespace) -> str:
    """How the person confirmed sending the map ("--yes" or "at the terminal"), or "" when they did not."""
    sys.stderr.write(render(mp, confidential.send_to("analyst")) + "\n")
    if getattr(args, "yes", False):
        return "--yes"
    if sys.stdin.isatty() and sys.stderr.isatty():
        sys.stderr.write("Send this to the model endpoint? [y/N] ")
        sys.stderr.flush()
        if input().strip().lower() in ("y", "yes"):
            return "at the terminal"
    sys.stderr.write("Nothing was sent and nothing was created: confirm with --yes to send what the scan shows.\n")
    return ""


def _folder(args: argparse.Namespace) -> Path | None:
    source = getattr(args, "source", None)
    try:
        return Path(source).resolve() if source and Path(source).is_dir() else None
    except (OSError, ValueError):
        return None


def _request(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """The intake arguments for the request (a folder's scanned and confirmed text), with its map, or None
    when the person did not confirm."""
    if getattr(args, "source_file", None):
        return {"source": Path(args.source_file).read_text(encoding="utf-8"), "literal": True}, None
    folder = _folder(args)
    if folder is None:
        return {"source": str(args.source)}, None
    mp, text, _ = material.gather(folder, args.exclude)
    how = _confirmed(mp, args)
    return ({"source": text, "literal": True}, mp | {"confirmed": how}) if how else None


def _refused(name: str, exc: Exception) -> int:
    sys.stderr.write(f"rihmasto {name}: {exc}\n")
    return 2


def _new(factory: Any, args: argparse.Namespace, emit: Emit, model: Callable[[], Any]) -> int | None:
    from kernel.intake import intake
    from kernel.posture_cli import choice

    persona = args.persona or "business_owner"
    posture = choice(args)    # --posture and --weights (kernel/posture_cli.py): a misfit is a usage error first
    if args.confidential and (why := confidential.refusal(["analyst"])):
        return _refused("new", confidential.ConfidentialRefused(why))
    asked = _request(args)
    if asked is None:
        return 2
    src, mp = asked
    p = factory.new_project(args.title, maturity=args.maturity, mode=args.mode, posture=posture,
                            profile=None if args.profile == "auto" else args.profile)
    if args.confidential:
        confidential.mark(p, person=args.requested_by, persona=persona)
    from kernel.go_ahead import choose as wait_or_not

    wait_or_not(p, wait=not args.build_without_waiting, person=args.requested_by, persona=persona, where="rihmasto new")
    if mp is not None:
        material.record(p, mp, person=args.requested_by, persona=persona, confirmed=mp.pop("confirmed"))
    out = intake(p, **src, model=model(), requested_by=args.requested_by)
    emit({"project": p.pid, **{k: v for k, v in out.items() if k != "readings"}})
    return None


def _intake(factory: Any, args: argparse.Namespace, emit: Emit, model: Callable[[], Any]) -> int | None:
    from kernel.intake import intake

    p = factory.project(args.pid)
    asked = _request(args)
    if asked is None:
        return 2
    src, mp = asked
    if mp is not None:
        material.record(p, mp, person=args.requested_by, persona=args.persona, confirmed=mp.pop("confirmed"))
    try:
        out = intake(p, **src, model=model(), requested_by=args.requested_by)
    except confidential.ConfidentialRefused as exc:
        return _refused("intake", exc)
    emit({k: v for k, v in out.items() if k != "readings"})
    return None


def _progress(step: str) -> None:
    """An adoption's step as it starts, on stderr: a terminal shows it, and the cockpit's job log carries it to
    the walkthrough that waits on the job (kernel/walkthrough_flows.py progress_of)."""
    sys.stderr.write(f"adopt: {step}\n")
    sys.stderr.flush()


def _adopt(factory: Any, args: argparse.Namespace, emit: Emit) -> int | None:
    from kernel.adopt import adopt
    from kernel.posture import for_new_project
    from kernel.posture_cli import choice

    posture = choice(args)      # --posture and --weights: its maturity and mode unless named, else production, mixed
    maturity, mode, _ = for_new_project(posture, args.maturity, args.mode) if posture else \
        (args.maturity or "production", args.mode or "mixed", None)
    p = adopt(factory, args.title, source=args.source, intent=args.intent, person=args.person, persona=args.persona,
              base_url=args.base_url, maturity=maturity, mode=mode, posture=posture, exclude=tuple(args.exclude),
              profile=None if args.profile == "auto" else args.profile, confidential=args.confidential,
              progress=_progress, working_copy=bool(getattr(args, "working_copy", False)),
              documents=bool(getattr(args, "documents", False)))
    meta, adopted = p.meta, p.read("adopted.json") or {}
    mp = p.read("material.json") or {}
    emit({"project": p.pid, "stage": meta["stage"], "intent": meta.get("intent"), "profile": meta.get("profile"),
          **_kind_said(p, adopted), "baseline": adopted.get("baseline"), "snapshot": adopted.get("snapshot"),
          "characterisation": {k: (p.read("baseline.json") or {}).get(k) for k in ("verdict", "reason")},
          "contract": meta.get("contract_revision"), "documents": mp.get("totals"),
          "confidential": bool(meta.get("confidential")),
          **({"confidential_note": why} if meta.get("confidential") and (why := confidential.refusal(
              confidential.ROLES)) else {})})
    return None


def _kind_said(p: Any, adopted: dict[str, Any]) -> dict[str, Any]:
    """Which kind of work an adoption took and why, or the question card that asks a person (kernel/adopt_kind.py)."""
    from kernel.adopt_kind import line
    from kernel.canon import Canon
    from kernel.profiles import PROFILE_QUESTION

    asked = [q["card"] for q in Canon(p).questions("open") if q["text"] == PROFILE_QUESTION and q.get("card")]
    return {"profile_basis": line(adopted.get("profile") or {}).removeprefix("- "),
            **({"kind_asked": asked[0]} if asked else {})}


def _baseline(factory: Any, args: argparse.Namespace, emit: Emit) -> int | None:
    """`rihmasto baseline <pid> --command "..." --yes`: a stated test command as the baseline (FR-RPJ1)."""
    from kernel.adopt_stated import StatedRefused, run

    try:
        got = run(factory.project(args.pid), args.command, person=args.person, persona=args.persona,
                  confirmed=bool(args.yes))
    except StatedRefused as exc:
        return _refused("baseline", exc)
    emit({"project": args.pid, **{k: got[k] for k in ("verdict", "reason", "command", "revision")}})
    return None


def _scan(args: argparse.Namespace, emit: Emit) -> int | None:
    try:
        mp = material.preview(args.folder, args.exclude)
    except ValueError as exc:
        return _refused("scan", exc)
    if args.json:
        emit(mp)
    else:
        sys.stdout.write(render(mp, confidential.send_to("analyst")))
    return None


def handlers(emit: Emit, model: Callable[[], Any]) -> dict[str, Callable[[Any, argparse.Namespace], int | None]]:
    """The `scan`, `new`, `intake` and `adopt` handlers. ``emit`` prints JSON, ``model`` makes the analyst's model
    (asked only once the person confirmed what is sent)."""
    return {"scan": lambda f, a: _scan(a, emit), "baseline": lambda f, a: _baseline(f, a, emit),
            "new": lambda f, a: _new(f, a, emit, model),
            "intake": lambda f, a: _intake(f, a, emit, model), "adopt": lambda f, a: _adopt(f, a, emit)}
