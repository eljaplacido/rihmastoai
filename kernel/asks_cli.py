"""Machines, asks between agents and machines, and the reachability doctor on the command line (FR-XAG1, FR-RCH1).

    rihmasto machines list
    rihmasto machines add NAME --reach ssh|https|hand [--address A] [--os windows|linux|macos] [--agent NAME ...]
                          [--note N] --person ... --persona developer|it
    rihmasto machines remove NAME --person ... --persona developer|it
    rihmasto reach TARGET                       test a machine, a project's working copy, an https:// address or
                                                github: the verdict, the fix, and a drafted ask (records nothing)
    rihmasto asks list [--project PID]          what waits on other agents (all projects, or one)
    rihmasto asks put <pid> --to AGENT --text T [--why W] [--expects E] [--machine M] [--days N]
                          --person ... --persona ...
    rihmasto asks copy <pid> AK-0001 --person ... --persona ...      the message for the other agent (delivered)
    rihmasto asks answer <pid> AK-0001 --text T --person ... --persona ...   file the answer that came back
    rihmasto asks withdraw <pid> AK-0001 --person ... --persona ...
    rihmasto asks link <pid> AK-0001 [--hours N] [--base URL] --person ... --persona ...  a reply link, shown once

A refusal is one line and exit 2, as `rihmasto dev`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from kernel import asks, hitl_links, machines, reach
from kernel.people import PERSONAS

Args = argparse.Namespace
LOCAL_BASE = "http://127.0.0.1:8787"


def _signed(p: argparse.ArgumentParser) -> None:
    p.add_argument("--person", required=True)
    p.add_argument("--persona", required=True, choices=PERSONAS)


def _ask(p: argparse.ArgumentParser) -> None:
    p.add_argument("pid")
    p.add_argument("aid", help="the ask's id, such as AK-0001")
    _signed(p)


def add_parsers(sub: Any) -> None:
    m = sub.add_parser("machines", help="the machines your agents and working copies are on (FR-XAG1)"
                       ).add_subparsers(dest="sub", required=True)
    m.add_parser("list", help="every machine, how it is reached, its system and agents")
    add = m.add_parser("add", help="add a machine, or change the one of that name")
    add.add_argument("name")
    add.add_argument("--reach", choices=machines.REACH, default=None)
    add.add_argument("--address", default=None, help="an ssh alias or user@host, or an https:// address")
    add.add_argument("--os", choices=machines.SYSTEMS, default=None)
    add.add_argument("--agent", action="append", default=None, help="an agent that runs there (repeat)")
    add.add_argument("--note", default=None)
    _signed(add)
    rm = m.add_parser("remove", help="remove a machine")
    rm.add_argument("name")
    _signed(rm)
    r = sub.add_parser("reach", help="test a connection: the verdict, the fix and a drafted ask (FR-RCH1)")
    r.add_argument("target", help="a machine, a project id, an https:// address, or github")
    a = sub.add_parser("asks", help="asks to agents on this and other machines (FR-XAG1)"
                       ).add_subparsers(dest="sub", required=True)
    a.add_parser("list", help="what waits on other agents").add_argument("--project", default=None)
    put = a.add_parser("put", help="put a question to a named agent")
    put.add_argument("pid")
    put.add_argument("--to", required=True)
    put.add_argument("--text", required=True)
    put.add_argument("--why", default="")
    put.add_argument("--expects", default="")
    put.add_argument("--machine", default=None)
    put.add_argument("--days", type=int, default=None)
    _signed(put)
    copy_p = a.add_parser("copy", help="the message for the other agent, to paste there")
    _ask(copy_p)
    copy_p.add_argument("--plain", action="store_true", help="print only the paste-ready message text, not JSON")
    answer = a.add_parser("answer", help="file the answer that came back")
    _ask(answer)
    answer.add_argument("--text", required=True)
    _ask(a.add_parser("withdraw", help="withdraw an ask"))
    link = a.add_parser("link", help="a reply link the other agent answers through, shown once")
    _ask(link)
    link.add_argument("--hours", type=int, default=None)
    link.add_argument("--base", default=LOCAL_BASE, help="where the link points: the cockpit's trusted https front")


def _machine_fields(a: Args) -> dict[str, Any]:
    fields = {"name": a.name, "reach": a.reach, "address": a.address, "os": a.os, "agents": a.agent, "note": a.note}
    return {k: v for k, v in fields.items() if v is not None}


def _list(f: Any, a: Args) -> dict[str, Any]:
    if a.project:
        return {"project": a.project, "asks": asks.listed(f.project(a.project))}
    return asks.summary(f)


def _link(f: Any, a: Args) -> dict[str, Any]:
    return asks.reply_link(f.project(a.pid), a.aid, person=a.person, persona=a.persona, base=a.base, hours=a.hours,
                           local=hitl_links.local_only(a.base))


COMMANDS: dict[str, Callable[[Any, Args], dict[str, Any]]] = {
    "machines list": lambda f, a: machines.describe(f),
    "machines add": lambda f, a: machines.add(f, _machine_fields(a), person=a.person, persona=a.persona),
    "machines remove": lambda f, a: machines.remove(f, a.name, person=a.person, persona=a.persona),
    "reach": lambda f, a: reach.doctor(f, a.target),
    "asks list": _list,
    "asks put": lambda f, a: asks.create(f.project(a.pid), to=a.to, text=a.text, why=a.why, expects=a.expects,
                                         machine=a.machine, days=a.days, person=a.person, persona=a.persona),
    "asks copy": lambda f, a: asks.copy_text(f.project(a.pid), a.aid, person=a.person, persona=a.persona),
    "asks answer": lambda f, a: asks.answer(f.project(a.pid), a.aid, a.text, person=a.person, persona=a.persona),
    "asks withdraw": lambda f, a: asks.withdraw(f.project(a.pid), a.aid, person=a.person, persona=a.persona),
    "asks link": _link,
}


def handlers(show: Callable[[Any], Any], say: Any = None) -> dict[str, Callable[[Any, Args], int]]:
    """The commands, each printing its answer with ``show``; a refusal is one line and exit 2, as `rihmasto dev`."""
    from kernel import devcli

    out: dict[str, Callable[[Any, Args], int]] = {}
    for name in sorted(COMMANDS):          # machines, reach, asks: one refusal is one line, exit 2
        if name == "asks copy":
            def _copy(f: Any, a: Args) -> int:
                def emit(res: Any) -> Any:
                    if getattr(a, "plain", False):
                        sys.stdout.write(str(res["text"]) + "\n")
                        return None
                    return show(res)
                return devcli._run(emit, "asks copy", COMMANDS["asks copy"])(f, a)
            out[name] = _copy
        else:
            out[name] = devcli._run(show, name, COMMANDS[name])
    return out
