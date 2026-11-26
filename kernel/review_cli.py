"""`rihmasto review`: since you last looked (FR-REV1), part of `rihmasto` (kernel/cli.py).

    rihmasto review [<pid>] [--since 24h] [--json] [--person P --persona X]
    rihmasto review mark <item>... --person P --persona X [--note "..."]
    rihmasto review done [--project <pid>] --person P --persona X
    rihmasto review digest SUB-001 --at 07:30 --days weekdays --tz +02:00 --person P --persona X
    rihmasto review digest off --person P --persona X

The review is a read: it records nothing. Without --person it covers the last 24 hours (or --since); with
--person it starts where that person last marked a review done. `mark` records a signed `review_marked` per
item, `done` a signed `review_done` that moves the person's marker, `digest` the person's morning digest.
A refusal is a message on stderr with exit 2. While access is enforced, the command signs as the local user
the access file names, with a persona granted on the factory.
"""

from __future__ import annotations

import argparse
import functools
from collections.abc import Callable
from typing import Any

from kernel import review, review_digest, review_marks
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace
ACTIONS = ("mark", "done", "digest")


def add_parsers(sub: Any) -> None:
    """Add `review` to `rihmasto`'s subcommands."""
    p = sub.add_parser("review", help="since you last looked: what agents shipped, what waits on you")
    p.add_argument("target", nargs="?", help="a project id; or mark, done or digest")
    p.add_argument("items", nargs="*", help="mark: the items (<project>/task/T-001); digest: a receiver or off")
    p.add_argument("--since", help="90m, 24h, 7d or a time such as 2026-11-24T06:00Z (default: your last review)")
    p.add_argument("--json", action="store_true", help="the whole review as JSON")
    p.add_argument("--project", help="done: mark one project's review done")
    p.add_argument("--person", help="the named person (needed by mark, done and digest)")
    p.add_argument("--persona", choices=PERSONAS)
    p.add_argument("--note", default="", help="mark: a note kept with the record")
    p.add_argument("--at", default="07:30", help="digest: the local time, HH:MM")
    p.add_argument("--days", default="weekdays", help="digest: weekdays, daily, or mon,wed,fri")
    p.add_argument("--tz", default="UTC", help="digest: a time zone name, or an offset such as +02:00")


def _signed(a: Args, what: str) -> tuple[str, str]:
    if not a.person or not a.persona:
        raise ValueError(f"review {what} is signed: give --person and --persona")
    return str(a.person), str(a.persona)


def text(out: dict[str, Any]) -> str:
    """The review as a person reads it in a terminal: the headline, then each group's items."""
    lines = [out["headline"], f"period: {out['since']} to {out['until']} ({out['basis']})", ""]
    for g in out["groups"]:
        if not g["count"]:
            continue
        lines.append(f"{g['label']} ({g['count']})")
        for it in g["items"]:
            by = it.get("by") or {}
            who = by.get("name") or by.get("type") or ""
            done = " [reviewed]" if it.get("reviewed") else ""
            lines.append(f"  {it['id']}  {it['title']}  ({who}){done}")
        lines.append("")
    cost = out["cost"]
    lines.append("Cost and usage: " + ("not measured: " + cost["why"] if not cost.get("measured") else
                                       f"{cost['runs']} model runs, {cost['total'].get('cloud')} {cost['currency']}"))
    return "\n".join(lines)


def run(f: Factory, a: Args, show: Callable[[Any], None], echo: Callable[[str], None]) -> None:
    action = a.target if a.target in ACTIONS else None
    if action == "mark":
        person, persona = _signed(a, "mark")
        show({"marked": review_marks.mark(f, list(a.items), person=person, persona=persona, note=a.note)})
    elif action == "done":
        person, persona = _signed(a, "done")
        show(review_marks.done(f, person=person, persona=persona, project=a.project, since=a.since))
    elif action == "digest":
        person, persona = _signed(a, "digest")
        receiver = a.items[0] if a.items else None
        show(review_digest.set_digest(f, person=person, persona=persona, subscription=receiver, at=a.at,
                                      days=a.days, tz=a.tz, off=receiver == "off"))
    else:
        if a.items:
            raise ValueError("review takes one project id; mark, done and digest take more")
        out = review.review(f, person=a.person or "", persona=a.persona or "", project=a.target, since=a.since)
        if a.json:
            show(out)
        else:
            echo(text(out))


Handler = Callable[[Factory, Args], None]


def handlers(show: Callable[[Any], None], echo: Callable[[str], None]) -> dict[str, Handler]:
    """The command as `rihmasto` runs it: JSON for a write and for --json, text for the review itself."""
    return {"review": functools.partial(_run, show, echo)}


def _run(show: Callable[[Any], None], echo: Callable[[str], None], f: Factory, a: Args) -> None:
    run(f, a, show, echo)
