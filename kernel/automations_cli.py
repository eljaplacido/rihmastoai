"""`rihmasto automations` (FR-AUT1), part of `rihmasto` (kernel/cli.py adds it).

    rihmasto automations list [--project PID] [--state active|paused] | templates | show AU-001 | history [AU-001]
    rihmasto automations add --name "Nightly re-gate" --daily 02:00 --action gate --source attached \\
                             --notify SUB-001 --person Aino --persona developer
    rihmasto automations add --template notify_on_release --subscription SUB-001 --person Ilkka --persona it
    rihmasto automations edit AU-001 [any of add's options] --person ... --persona ...
    rihmasto automations pause|resume|remove AU-001 --person ... --persona ... [--reason "..."]
    rihmasto automations run-now AU-001 [--project PID] --person ... --persona ...
    rihmasto automations dry-run AU-001        what the next tick would do; records nothing
    rihmasto automations tick                  one round, for cron or Windows Task Scheduler
    rihmasto automations install-help          the exact line that runs the tick every minute on this machine
    rihmasto automations tag PID --tag ops [--tag nightly] --person ... --persona ...

A trigger is one of --every 15m|2h|1d, --daily HH:MM, --weekly "mon HH:MM" (UTC), --on KIND (repeatable),
--hook SOURCE, --repo [--branch main]. A guard: --guard-count EVENT:N[:HOURS], --guard-branch NAME,
--guard-field KEY=VALUE, --guard-open-cards N. The scope: --project PID (repeatable), --tag, --profile,
--source attached|adopted|..., or --factory. Limits: --max-per-hour, --breaker, --quiet HH:MM-HH:MM, --dry-run.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from collections.abc import Callable
from typing import Any

from kernel import automations as au
from kernel import automations_run as run
from kernel import automations_text as words
from kernel.people import PERSONAS
from kernel.store import REPO_ROOT, Factory

Args = argparse.Namespace


def _signed(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("--person", required=True)
    p.add_argument("--persona", required=True, choices=PERSONAS)
    return p


def _spec_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--template", choices=[t["id"] for t in words.TEMPLATES])
    p.add_argument("--json", dest="spec_json", help="the whole automation as JSON (its parts, as `show` prints)")
    p.add_argument("--name")
    when = p.add_mutually_exclusive_group()
    for flag in ("--every", "--daily", "--weekly", "--hook"):
        when.add_argument(flag)
    when.add_argument("--on", action="append", help="a record kind it reacts to (repeatable)")
    when.add_argument("--repo", action="store_true", help="new commits on the repository's branch")
    p.add_argument("--branch")
    p.add_argument("--guard-count", metavar="EVENT:N[:HOURS]")
    p.add_argument("--guard-branch")
    p.add_argument("--guard-field", metavar="KEY=VALUE")
    p.add_argument("--guard-open-cards", type=int)
    p.add_argument("--action", choices=list(au.ACTIONS))
    for flag in ("--text", "--folder", "--subscription", "--target-project", "--environment"):
        p.add_argument(flag)
    p.add_argument("--probe-every", help="a probe action keeps probing production this often: 15m to 1d")
    p.add_argument("--targets", action="append")
    p.add_argument("--no-verifier", action="store_true")
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--project", dest="projects", action="append")
    for flag in ("--tag", "--profile", "--source"):
        scope.add_argument(flag)
    scope.add_argument("--factory", action="store_true")
    p.add_argument("--max-per-hour", type=int)
    p.add_argument("--breaker", type=int)
    p.add_argument("--quiet")
    p.add_argument("--dry-run", dest="rehearse", action="store_true", help="record what it would do; do nothing")
    p.add_argument("--notify", metavar="SUB-ID", help="notify this subscription of the outcome")
    p.add_argument("--notify-when", choices=("failed", "always"), default="failed")


def add_parsers(sub: Any) -> None:
    grp = sub.add_parser("automations", help="triggers, guards and actions per project (kernel/automations.py)")
    g = grp.add_subparsers(dest="sub", required=True)
    ls = g.add_parser("list", help="the automations")
    ls.add_argument("--project")
    ls.add_argument("--state", choices=("active", "paused"))
    g.add_parser("templates", help="the templates the builder starts from")
    for name in ("show", "dry-run"):
        g.add_parser(name, help=f"{name} one automation").add_argument("id")
    hist = g.add_parser("history", help="runs and changes, newest last")
    hist.add_argument("id", nargs="?")
    hist.add_argument("--project")
    hist.add_argument("--limit", type=int, default=50)
    _spec_options(_signed(g.add_parser("add", help="set an automation, in your name")))
    ed = _signed(g.add_parser("edit", help="change an automation; you own it from then on"))
    ed.add_argument("id")
    _spec_options(ed)
    for name in ("pause", "resume", "remove"):
        p = _signed(g.add_parser(name, help=f"{name} an automation"))
        p.add_argument("id")
        if name == "pause":
            p.add_argument("--reason", default="")
    rn = _signed(g.add_parser("run-now", help="run it once now, with its owner's rights"))
    rn.add_argument("id")
    rn.add_argument("--project")
    g.add_parser("tick", help="one round of every active automation")
    g.add_parser("install-help", help="how to run the tick every minute without the cockpit")
    tg = _signed(g.add_parser("tag", help="set a project's tags, for a tag scope"))
    tg.add_argument("pid")
    tg.add_argument("--tag", action="append", default=[])
    from kernel import setup_cli  # suggest, accept, dismiss and describe (FR-SET1)

    setup_cli.automation_parsers(g)


# -- from options to an automation's parts -------------------------------------------------------------------

def _trigger(a: Args) -> dict[str, Any] | None:
    if a.every or a.daily or a.weekly:
        return {"kind": "schedule", "every": a.every, "daily": a.daily, "weekly": a.weekly}
    if a.on:
        return {"kind": "event", "types": a.on}
    if a.hook:
        return {"kind": "hook", "source": a.hook}
    return {"kind": "repo", "branch": a.branch} if a.repo else None


def _guard(a: Args) -> dict[str, Any] | None:
    if a.guard_count:
        event, _, rest = a.guard_count.partition(":")
        n, _, hours = rest.partition(":")
        return {"kind": "count", "event": event, "at_least": int(n or 1), "within_hours": int(hours or 24)}
    if a.guard_branch:
        return {"kind": "branch", "is": a.guard_branch}
    if a.guard_field:
        key, _, value = a.guard_field.partition("=")
        return {"kind": "field", "key": key, "equals": value}
    return {"kind": "open_cards", "at_least": a.guard_open_cards} if a.guard_open_cards else None


def _scope(a: Args) -> dict[str, Any] | None:
    if a.projects:
        return {"kind": "project" if len(a.projects) == 1 else "projects", "projects": a.projects}
    for key in ("tag", "profile", "source"):
        if getattr(a, key):
            return {"kind": key, key: getattr(a, key)}
    return {"kind": "factory"} if a.factory else None


def _action(a: Args, base: dict[str, Any] | None) -> dict[str, Any] | None:
    given = {"kind": a.action, "text": a.text, "folder": a.folder, "subscription": a.subscription,
             "project": a.target_project, "targets": a.targets, "verifier": False if a.no_verifier else None,
             "environment": a.environment, "every": a.probe_every}
    given = {k: v for k, v in given.items() if v is not None}
    if not given:
        return None
    return {**(base or {}), **given}


def draft(a: Args, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """The parts the options give, over ``base`` (a template's draft, or the automation being edited)."""
    out = copy.deepcopy(base or {})
    if a.template:
        out = {**copy.deepcopy(next(t["draft"] for t in words.TEMPLATES if t["id"] == a.template)), **out}
    if a.spec_json:
        out.update(json.loads(a.spec_json))
    parts = {"name": a.name, "trigger": _trigger(a), "guard": _guard(a), "scope": _scope(a),
             "action": _action(a, out.get("action"))}
    out.update({k: v for k, v in parts.items() if v is not None})
    limits = {"max_per_hour": a.max_per_hour, "breaker": a.breaker, "quiet": a.quiet,
              "dry_run": True if a.rehearse else None}
    out["limits"] = {**(out.get("limits") or {}), **{k: v for k, v in limits.items() if v is not None}}
    return _notified(out, a)


def _notified(out: dict[str, Any], a: Args) -> dict[str, Any]:
    """The outcome notice: --notify, or a template's empty one filled with --subscription, or none."""
    if a.notify:
        out["notify"] = {"subscription": a.notify, "when": a.notify_when}
    elif (out.get("notify") or {}).get("subscription") == "":
        out["notify"] = dict(out["notify"], subscription=a.subscription) if a.subscription else None
    return out


def view(a: dict[str, Any], factory: Factory) -> dict[str, Any]:
    """An automation as people read it: its parts, its summary and where it stands."""
    s = run.state_of(factory, a["id"])
    return {**a, "summary": words.describe(a), "next_at": s.get("next_at"), "queue": len(s.get("queue") or []),
            "failures": s.get("failures", 0), "last": s.get("last"), "last_skip": s.get("last_skip"),
            "projects_now": [p.pid for p in au.projects_in(factory, a["scope"])]}


def listing(factory: Factory, project: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
    rows = [a for a in au.automations(factory) if state in (None, a["state"])]
    if project is not None:
        p = factory.project(project)
        rows = [a for a in rows if au.in_scope(p, a["scope"]) or a["action"].get("project") == p.pid]
    return [view(a, factory) for a in rows]


def install_help(factory: Factory) -> dict[str, Any]:
    """The lines that run `automations tick` every minute on this machine, without the cockpit."""
    home, exe = factory.home.resolve(), sys.executable
    tick = f'"{exe}" -m kernel.cli --home "{home}" automations tick'
    installed = shutil.which("rihmasto")
    return {"why": "The cockpit ticks every minute while it runs. Without it, the system's scheduler runs one tick a "
                   "minute; a tick that finds another running answers busy and changes nothing.",
            "cron": f'* * * * * cd "{REPO_ROOT}" && {tick} >> "{home / "automations" / "tick.log"}" 2>&1',
            "windows_task_scheduler": f'schtasks /Create /TN "Rihmasto automations" /SC MINUTE /MO 1 /F /TR '
                                      f'"cmd /c cd /d \\"{REPO_ROOT}\\" && {tick.replace(chr(34), chr(92) + chr(34))}"',
            "installed_command": f'"{installed}" --home "{home}" automations tick' if installed else None,
            "gnomon_loop": "A Gnomon loop may run the same tick (its [act] run is the line above); the automations "
                           "stay Rihmasto's, signed and recorded here (docs/guides/automations.md)."}


# -- the commands ---------------------------------------------------------------------------------------

def _tools(model: Callable[[], Any]) -> run.Tools:
    return run.Tools(model=model)


def _run_now(f: Factory, a: Args, model: Callable[[], Any]) -> dict[str, Any]:
    req = run.request_run(f, a.id, person=a.person, persona=a.persona, project=a.project)
    return {"requested": req, "tick": run.tick(f, _tools(model), only=a.id)}


def commands(model: Callable[[], Any]) -> dict[str, Callable[[Factory, Args], Any]]:
    def show(f: Factory, a: Args) -> dict[str, Any]:
        return {**view(au.get(f, a.id), f), "history": run.history(f, a.id, limit=20)}

    return {
        "automations list": lambda f, a: {"automations": listing(f, a.project, a.state)},
        "automations templates": lambda f, a: {"templates": words.TEMPLATES},
        "automations show": show,
        "automations history": lambda f, a: {"history": run.history(f, a.id, project=a.project, limit=a.limit)},
        "automations add": lambda f, a: view(au.add(f, draft(a), person=a.person, persona=a.persona), f),
        "automations edit": lambda f, a: view(au.edit(f, a.id, draft(a, _parts(au.get(f, a.id))), person=a.person,
                                                      persona=a.persona), f),
        "automations pause": lambda f, a: au.pause(f, a.id, person=a.person, persona=a.persona, reason=a.reason),
        "automations resume": lambda f, a: au.resume(f, a.id, person=a.person, persona=a.persona),
        "automations remove": lambda f, a: au.remove(f, a.id, person=a.person, persona=a.persona),
        "automations run-now": lambda f, a: _run_now(f, a, model),
        "automations dry-run": lambda f, a: run.dry_run(f, a.id),
        "automations tick": lambda f, a: run.tick(f, _tools(model)),
        "automations install-help": lambda f, a: install_help(f),
        "automations tag": lambda f, a: {"project": a.pid, "tags": au.set_tags(f.project(a.pid), a.tag,
                                                                               person=a.person, persona=a.persona)},
    }


def _parts(a: dict[str, Any]) -> dict[str, Any]:
    return {k: a[k] for k in ("name", "trigger", "guard", "action", "scope", "limits", "notify")}


def handlers(show: Callable[[Any], None], model: Callable[[], Any]) -> dict[str, Callable[[Factory, Args], None]]:
    """The commands as `rihmasto` runs them: each prints what it returns."""
    def printing(command: Callable[[Factory, Args], Any]) -> Callable[[Factory, Args], None]:
        return lambda f, a: show(command(f, a))

    return {name: printing(command) for name, command in commands(model).items()}
