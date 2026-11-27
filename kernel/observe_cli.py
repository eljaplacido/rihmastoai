"""`rihmasto share`, part of the command line (kernel/cli.py): observer links from a terminal (FR-SHR1).

    rihmasto share link [pid] --hours 1|24|168 [--guest NAME] [--confidential] [--intake]
                        [--base http://127.0.0.1:8787] --person ... --persona ...
    rihmasto share revoke OL-001 --person ... --persona ...
    rihmasto share list

`share link` without a project shares every project (confidential ones only with --confidential). The address is
printed once, for the person to pass on: nothing is sent anywhere. The guest opens it on the cockpit's machine or
through an ssh tunnel, which is an ssh login on this host: only from a restricted account that forwards the one
port (docs/guides/observer-links.md).
"""

from __future__ import annotations

import argparse
import functools
import sys
from collections.abc import Callable
from typing import Any

from kernel import observe
from kernel.people import PERSONAS

Args = argparse.Namespace


def add_parsers(sub: Any) -> None:
    """Add `share` to `rihmasto`'s subcommands."""
    share = sub.add_parser("share", help="observer links: a read-only view of your work (FR-SHR1)"
                           ).add_subparsers(dest="sub", required=True)
    link = share.add_parser("link", help="make an observer link, shown once")
    link.add_argument("pid", nargs="?", help="the project to share (none: every project)")
    link.add_argument("--hours", type=int, default=1, choices=sorted(observe.DURATIONS))
    link.add_argument("--guest", default="")
    link.add_argument("--confidential", action="store_true", help="include confidential projects (explicit)")
    link.add_argument("--intake", action="store_true", help="let the guest suggest answers to intake questions")
    link.add_argument("--base", default="http://127.0.0.1:8787", help="the cockpit's address as the guest opens it")
    revoke = share.add_parser("revoke", help="end an observer link at once")
    revoke.add_argument("link")
    for p in (link, revoke):
        p.add_argument("--person", required=True)
        p.add_argument("--persona", required=True, choices=PERSONAS)
    share.add_parser("list", help="the observer links, who is watching, when each was last opened")


def _link(f: Any, a: Args) -> dict[str, Any]:
    made = observe.create(f, scope="project" if a.pid else "platform", project=a.pid, hours=a.hours, guest=a.guest,
                          person=a.person, persona=a.persona, confidential=a.confidential, intake=a.intake)
    address = observe.url(a.base, made.pop("token"))
    return {"link": observe.public(f, made), "url": address, "shown_once": True,
            "said": "Pass it on yourself: Rihmasto sends nothing. It is not shown again."}


COMMANDS: dict[str, Callable[[Any, Args], dict[str, Any]]] = {
    "share link": _link,
    "share revoke": lambda f, a: {"link": observe.revoke(f, a.link, person=a.person, persona=a.persona)},
    "share list": lambda f, a: {"links": [observe.public(f, r) for r in observe.links(f)]},
}


def _carry_out(show: Callable[[Any], Any], name: str, f: Any, a: Args) -> int:
    """One `share` command: its answer printed, or why not on stderr with exit 2, never a traceback."""
    try:
        out = COMMANDS[name](f, a)
    except KeyError as exc:
        sys.stderr.write(f"rihmasto {name}: {exc.args[0] if exc.args else exc}\n")
        return 2
    except ValueError as exc:                  # a refusal (DecisionRefused) too
        sys.stderr.write(f"rihmasto {name}: {exc}\n")
        return 2
    show(out)
    return 0


def handlers(show: Callable[[Any], Any], say: Any = None) -> dict[str, Callable[[Any, Args], int]]:
    """The `share` commands, each printing its answer with ``show`` (``say`` is not needed)."""
    return {name: functools.partial(_carry_out, show, name) for name in COMMANDS}
