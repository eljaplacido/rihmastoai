"""`rihmasto agentobs`, part of the command line (kernel/cli.py); docs/guides/agent-observability.md is the guide.

    rihmasto agentobs status                                  the hub's address, whether it answers, its projects
    rihmasto agentobs settings --url URL [--token-env NAME] [--private] [--hosted] [--reason ...]
                               --person ... --persona it      IT sets the hub's address (--clear removes it)
    rihmasto agentobs show <pid> [--persona developer]        a project's Agent sessions view, as JSON
    rihmasto agentobs map <pid> (--hub-project ID | --suggested | --unmap) --person ... --persona developer|it
    rihmasto agentobs snapshot <pid> --person ... --persona developer|it

`map` and `snapshot` belong to the Agent observability module: with it off for the project they are refused,
with the command that turns it on. Nothing here writes into a repository or installs anything.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from kernel.agentobs import HUB, set_settings, settings
from kernel.agentobs.client import HubError, HubUnreachable, from_settings
from kernel.agentobs.mapping import candidates, map_project, suggest
from kernel.canon import DecisionRefused
from kernel.people import PERSONAS

Args = argparse.Namespace
Show = Callable[[Any], Any]


def add_parsers(sub: Any) -> None:
    """Add `agentobs` to `rihmasto`'s subcommands."""
    ao = sub.add_parser("agentobs", help="what the IDE agents did in a project's repository, read from your agent "
                                         "observability hub (docs/guides/agent-observability.md)"
                        ).add_subparsers(dest="sub", required=True)
    ao.add_parser("status", help="the hub's address, whether it answers, and its projects")
    s = ao.add_parser("settings", help="IT sets the hub's address")
    s.add_argument("--url", default="")
    s.add_argument("--clear", action="store_true", help="remove the address")
    s.add_argument("--token-env", default="", help="the environment variable that holds the hub's token, if any")
    s.add_argument("--private", action="store_true", help="the address is on your own network")
    s.add_argument("--hosted", action="store_true", help="IT consents to a hosted hub (https only)")
    s.add_argument("--reason", default="")
    show = ao.add_parser("show", help="a project's Agent sessions view")
    show.add_argument("pid")
    show.add_argument("--persona", default="developer", choices=PERSONAS)
    m = ao.add_parser("map", help="map a project to the hub's project for its repository")
    m.add_argument("pid")
    which = m.add_mutually_exclusive_group(required=True)
    which.add_argument("--hub-project")
    which.add_argument("--suggested", action="store_true", help="the hub project that matches the repository")
    which.add_argument("--unmap", action="store_true")
    m.add_argument("--reason", default="")
    snap = ao.add_parser("snapshot", help="record what the hub shows for a project in its ledger")
    snap.add_argument("pid")
    for p in (s, m, snap):
        p.add_argument("--person", required=True)
        p.add_argument("--persona", required=True, choices=PERSONAS)


def _status(f: Any, a: Args) -> dict[str, Any]:
    out: dict[str, Any] = {"settings": settings(f)}
    hub = from_settings(f)
    if hub is None:
        return out | {"hub": {"configured": False, "why": f"no address is set for {HUB}"}}
    try:
        return out | {"hub": {"configured": True, "reachable": True, **hub.health()}, "projects": hub.projects()}
    except (HubUnreachable, HubError) as exc:
        return out | {"hub": {"configured": True, "reachable": False, "error": str(exc)}}


def _settings(f: Any, a: Args) -> dict[str, Any]:
    if not a.clear and not a.url:
        raise ValueError("give the hub's address with --url, or --clear to remove it")
    return set_settings(f, url="" if a.clear else a.url, token_env=a.token_env, private=a.private, hosted=a.hosted,
                        person=a.person, persona=a.persona, reason=a.reason)


def _show(f: Any, a: Args) -> dict[str, Any]:
    from kernel.agentobs.view import build

    return build(f, f.project(a.pid), persona=a.persona)


def _map(f: Any, a: Args) -> dict[str, Any]:
    project = f.project(a.pid)
    hub_project, how = "" if a.unmap else (a.hub_project or ""), "chosen"
    if a.suggested:
        hub = from_settings(f)
        if hub is None:
            raise ValueError(f"no address is set for {HUB}: IT sets it with `rihmasto agentobs settings`")
        found = suggest(candidates(project), hub.projects())
        if found is None:
            raise ValueError("the hub knows no project for this repository: choose one with --hub-project")
        hub_project, how = found["id"], "suggested"
    doc = map_project(project, hub_project, person=a.person, persona=a.persona, how=how, reason=a.reason)
    return {"project": project.pid, "mapping": doc}


def _snapshot(f: Any, a: Args) -> dict[str, Any]:
    from kernel.agentobs.snapshot import record

    return record(f, f.project(a.pid), person=a.person, persona=a.persona)


COMMANDS: dict[str, Callable[[Any, Args], dict[str, Any]]] = {
    "agentobs status": _status, "agentobs settings": _settings, "agentobs show": _show, "agentobs map": _map,
    "agentobs snapshot": _snapshot}


def _run(show: Show, name: str, run: Callable[[Any, Args], dict[str, Any]]) -> Callable[[Any, Args], int]:
    def go(f: Any, a: Args) -> int:
        try:
            show(run(f, a))
        except (DecisionRefused, ValueError, KeyError, HubUnreachable, HubError) as exc:
            said = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
            sys.stderr.write(f"rihmasto {name}: {said}\n")
            return 2
        return 0
    return go


def handlers(show: Show) -> dict[str, Callable[[Any, Args], int]]:
    return {name: _run(show, name, run) for name, run in COMMANDS.items()}
