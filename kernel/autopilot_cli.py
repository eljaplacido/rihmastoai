"""The commands for autopilot, delegation and staying on track (D-0017), part of `rihmasto` (kernel/cli.py).

    rihmasto autopilot start <pid> --until 8h --delegate question,approval,escalation --person Aino --persona developer
    rihmasto autopilot run <pid> | autopilot status [<pid>] | autopilot stop <pid> --person Aino --persona developer
    rihmasto autopilot relay SUB-001 --sandbox | --off --person Ilkka --persona it
    rihmasto delegation grant <pid> --kinds question --until 2d [--rule question=assume] --person ... --persona ...
    rihmasto delegation revoke <pid> DL-001 --person ... --persona ... | delegation list <pid> | delegation rules
    rihmasto track [<pid>]
    rihmasto tracking set <pid> [--checkpoints 5,6] [--hold | --no-hold] [--due YYYY-MM-DD] [--budget 400]
                          [--currency EUR] --person ... --persona ...
    rihmasto tracking look <pid> <stage> --person ... --persona ... [--note "..."]
    rihmasto tracking digest SUB-001 daily|off --person Ilkka --persona it

A write is signed with --person and --persona, and a refusal is a message on stderr with exit 2. Reads
(`autopilot status`, `delegation list`, `delegation rules`, `track`) take no signer.
"""

from __future__ import annotations

import argparse
import functools
from collections.abc import Callable
from typing import Any

from kernel import autopilot, delegation, relay, track
from kernel.canon import CARD_VERDICTS
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace
Command = Callable[[Factory, Args], Any]


def _leaf(group: Any, name: str, about: str, *positionals: str, optional: str | None = None) -> argparse.ArgumentParser:
    """A command with its positional arguments, and one that may be left out (``optional``)."""
    p: argparse.ArgumentParser = group.add_parser(name, help=about)
    for pos in positionals:
        p.add_argument(pos)
    if optional:
        p.add_argument(optional, nargs="?")
    return p


def _signer(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("--person", required=True, help="the named person who signs it")
    p.add_argument("--persona", required=True, choices=PERSONAS)
    return p


def _delegating(p: argparse.ArgumentParser, flag: str) -> argparse.ArgumentParser:
    p.add_argument(flag, dest="kinds", required=True,
                   help=f"card kinds, comma separated: {', '.join(delegation.RULES)}")
    p.add_argument("--until", required=True, help="8h, 90m, 2d or a time such as 2026-11-24T08:00Z (at most "
                                                  f"{delegation.MAX_DAYS} days)")
    p.add_argument("--rule", action="append", default=[], metavar="KIND=RULE",
                   help="a rule other than the kind's default (see `delegation rules`)")
    p.add_argument("--reason", default="")
    return _signer(p)


def add_parsers(sub: Any) -> None:
    """Add `autopilot`, `delegation`, `track` and `tracking` to `rihmasto`'s subcommands."""
    ap = sub.add_parser("autopilot", help="run on its own in a sandbox (kernel/autopilot.py)").add_subparsers(
        dest="sub", required=True)
    s = _delegating(_leaf(ap, "start", "delegate card kinds and run until a person is needed", "pid"), "--delegate")
    s.add_argument("--passes", type=int, default=autopilot.MAX_PASSES)
    s.add_argument("--arm-only", action="store_true", help="record the run and its delegation; run no pass yet")
    _leaf(ap, "run", "more passes of a running autopilot", "pid").add_argument(
        "--passes", type=int, default=autopilot.MAX_PASSES)
    _leaf(ap, "status", "the run that holds a project, its delegation and its sandbox", optional="pid")
    _signer(_leaf(ap, "stop", "stop the run: revoke its delegation, release what it held", "pid")).add_argument(
        "--reason", default="")
    r = _signer(_leaf(ap, "relay", "IT marks a relay subscription as a sandbox receiver, or not", "id"))
    r.add_argument("--off", action="store_true", help="no longer a sandbox receiver")
    r.add_argument("--sandbox", action="store_true", help="a sandbox receiver (the default)")
    dl = sub.add_parser("delegation", help="card kinds a person lets the factory's rules decide (kernel/delegation.py)"
                        ).add_subparsers(dest="sub", required=True)
    _delegating(_leaf(dl, "grant", "delegate card kinds on a project until a time", "pid"), "--kinds")
    _signer(_leaf(dl, "revoke", "stop a delegation at once", "pid", "id")).add_argument("--reason", default="")
    _leaf(dl, "list", "a project's delegations and what they decided", "pid")
    _leaf(dl, "rules", "the rules, and the kinds never delegated")
    _leaf(sub, "track", "how a project is doing against its approved plan (kernel/track.py)", optional="pid")
    tr = sub.add_parser("tracking", help="checkpoints, budget and the daily digest (kernel/track.py)").add_subparsers(
        dest="sub", required=True)
    t = _signer(_leaf(tr, "set", "a plan owner sets checkpoints and a budget", "pid"))
    stages = ", ".join(map(str, track.CHECKPOINT_STAGES))
    t.add_argument("--checkpoints", help=f"stage numbers, comma separated: {stages}")
    t.add_argument("--hold", action=argparse.BooleanOptionalAction, default=None,
                   help="a due checkpoint stops the run until a person looks")
    t.add_argument("--due", help="YYYY-MM-DD; an empty value clears it")
    t.add_argument("--budget", type=float, help="a cost budget, in the price table's currency")
    t.add_argument("--currency")
    _signer(_leaf(tr, "look", "record that you looked at a checkpoint", "pid", "stage")).add_argument(
        "--note", default="")
    _signer(_leaf(tr, "digest", "IT has a notice subscription get the daily digest", "id", "when"))


def _kinds(text: str) -> list[str]:
    return [k.strip() for k in str(text).split(",") if k.strip()]


def _rules(items: list[str]) -> dict[str, str]:
    out = {}
    for item in items:
        kind, sep, rule = item.partition("=")
        if not sep or kind.strip() not in CARD_VERDICTS:
            raise ValueError(f"a rule is KIND=RULE, such as question=assume, not {item!r}")
        out[kind.strip()] = rule.strip()
    return out


def _start(f: Factory, a: Args, model: Callable[[], Any]) -> Any:
    p = f.project(a.pid)
    run = autopilot.start(p, until=a.until, kinds=_kinds(a.kinds), person=a.person, persona=a.persona,
                          rules=_rules(a.rule), reason=a.reason)
    return run if a.arm_only else autopilot.run(p, model=model(), passes=a.passes)


def _status(f: Factory, a: Args) -> Any:
    if a.pid:
        return autopilot.status(f.project(a.pid))
    return {"runs": [autopilot.status(p) for p in f.projects() if p.path(autopilot.FILE).exists()]}


def _track(f: Factory, a: Args) -> Any:
    if a.pid:
        return track.track(f.project(a.pid))
    return {"projects": [track.summary(p) for p in f.projects() if not p.pid.startswith("_")]}


def _tracking_set(f: Factory, a: Args) -> Any:
    stages = [int(s) for s in _kinds(a.checkpoints)] if a.checkpoints is not None else None
    return track.set_tracking(f.project(a.pid), person=a.person, persona=a.persona, stages=stages, hold=a.hold,
                              due=a.due, amount=a.budget, currency=a.currency)


def _digest(f: Factory, a: Args) -> Any:
    if a.when not in ("daily", "off"):
        raise ValueError("the digest is daily, or off")
    return relay.mark(f, a.id, person=a.person, persona=a.persona, digest=a.when)


def commands(model: Callable[[], Any]) -> dict[str, Command]:
    return {
        "autopilot start": lambda f, a: _start(f, a, model),
        "autopilot run": lambda f, a: autopilot.run(f.project(a.pid), model=model(), passes=a.passes),
        "autopilot status": _status,
        "autopilot stop": lambda f, a: autopilot.stop(f.project(a.pid), person=a.person, persona=a.persona,
                                                      reason=a.reason),
        "autopilot relay": lambda f, a: relay.mark(f, a.id, person=a.person, persona=a.persona, sandbox=not a.off),
        "delegation grant": lambda f, a: delegation.grant(f.project(a.pid), _kinds(a.kinds), person=a.person,
                                                          persona=a.persona, until=a.until, rules=_rules(a.rule),
                                                          reason=a.reason),
        "delegation revoke": lambda f, a: delegation.revoke(f.project(a.pid), a.id, person=a.person,
                                                            persona=a.persona, reason=a.reason),
        "delegation list": lambda f, a: {"project": a.pid, "delegations": delegation.delegations(f.project(a.pid)),
                                         "decided": delegation.decided_under(f.project(a.pid)),
                                         "declined": delegation.declined_under(f.project(a.pid))},
        "delegation rules": lambda f, a: {"rules": delegation.RULES, "defaults": delegation.DEFAULT_RULE,
                                          "never": delegation.NEVER, "max_days": delegation.MAX_DAYS},
        "track": _track,
        "tracking set": _tracking_set,
        "tracking look": lambda f, a: track.look(f.project(a.pid), int(a.stage), person=a.person, persona=a.persona,
                                                 note=a.note),
        "tracking digest": _digest,
    }


def _shown(show: Callable[[Any], None], command: Command, f: Factory, a: Args) -> None:
    show(command(f, a))


def handlers(show: Callable[[Any], None], model: Callable[[], Any]) -> dict[str, Callable[[Factory, Args], None]]:
    """The commands as `rihmasto` runs them: each shows what it returns. ``model`` makes the analyst's model
    when a command runs the pipeline."""
    return {name: functools.partial(_shown, show, command) for name, command in commands(model).items()}
