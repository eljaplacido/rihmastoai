"""The integration edges' commands (D-0015), part of `rihmasto` (kernel/cli.py adds them).

    rihmasto relay subscribe --sink webhook --url https://... --secret-env RELAY_SECRET --person Ilkka --persona it
    rihmasto relay subscribe --sink teams --url-env TEAMS_IT_URL --notify it --person Ilkka --persona it
    rihmasto relay subscribe --sink email --smtp-host mail.example --starttls --mail-from rihmasto@example.org
                             --mail-to it-team@example.org --notify it --person Ilkka --persona it
    rihmasto relay cockpit https://rihmasto.example.org --person Ilkka --persona it
    rihmasto relay list | relay run | relay log [--subscription SUB-001] | relay unsubscribe SUB-001 ...
    rihmasto hooks add <source> --scheme standard|github --secret-env NAME [--becomes change --project PID] ...
    rihmasto hooks add ... --bind PID [--bind PID]       a source that belongs to projects: their automations react
    rihmasto hooks bind <source> --project PID ... | hooks list | hooks remove <source> ...
    rihmasto connector validate <system> | connector status | connector check [--root DIR]
    rihmasto connector enable <system> | connector disable <system> --person Ilkka --persona it

Every configuration change is signed by a named person as IT. A secret is always the name of an
environment variable, never its value. The webhook server is `python -m embed.webhooks`.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import connectors, hooks, relay
from kernel.canon import CARD_VERDICTS
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace
Command = Callable[[Factory, Args], Any]


def _signer(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Who signs the change: a named person, as IT."""
    p.add_argument("--person", required=True, help="the person who makes the change")
    p.add_argument("--persona", required=True, choices=PERSONAS, help="it: only IT configures integrations")
    return p


def _leaf(group: Any, name: str, about: str, *positionals: str) -> argparse.ArgumentParser:
    p: argparse.ArgumentParser = group.add_parser(name, help=about)
    for pos in positionals:
        p.add_argument(pos)
    return p


def _subscribe_parser(rel: Any) -> None:
    s = _signer(_leaf(rel, "subscribe", "IT adds a subscription: a signed webhook, or notices to a channel"))
    s.add_argument("--sink", required=True, choices=relay.SINKS)
    s.add_argument("--url", help="a webhook receiver's https URL")
    s.add_argument("--url-env", help="the variable holding a URL that carries a token (Teams, Slack)")
    s.add_argument("--secret-env", help="the variable holding a webhook's signing secret")
    s.add_argument("--type", dest="types", action="append", help="an event type pattern, such as rihma.card.*")
    s.add_argument("--notify", action="append", choices=PERSONAS, help="a persona whose cards the channel hears of")
    s.add_argument("--kind", dest="kinds", action="append", choices=list(CARD_VERDICTS),
                   help="only these card kinds (questions only when named)")
    s.add_argument("--smtp-host")
    s.add_argument("--smtp-port", type=int, default=25)
    s.add_argument("--starttls", action="store_true")
    s.add_argument("--mail-from")
    s.add_argument("--mail-to", action="append")
    s.add_argument("--smtp-user-env")
    s.add_argument("--smtp-password-env")
    s.add_argument("--project", dest="projects", action="append", help="a project's own receiver: only its events")


def add_parsers(sub: Any, parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the relay, hooks and connector commands to `rihmasto`'s subcommands; returns ``parser``."""
    rel = sub.add_parser("relay", help="events and notices out (kernel/relay.py)").add_subparsers(
        dest="sub", required=True)
    _subscribe_parser(rel)
    _signer(_leaf(rel, "unsubscribe", "IT ends a subscription", "id"))
    _signer(_leaf(rel, "cockpit", "IT gives the cockpit's address, where deep links point", "url"))
    _leaf(rel, "list", "the subscriptions (secrets are names only)")
    _leaf(rel, "run", "one round of deliveries")
    lg = _leaf(rel, "log", "the delivery log, newest last")
    lg.add_argument("--subscription")
    lg.add_argument("--limit", type=int, default=50)
    hk = sub.add_parser("hooks", help="verified inbound webhooks (kernel/hooks.py)").add_subparsers(
        dest="sub", required=True)
    s = _signer(_leaf(hk, "add", "IT names an inbound source", "source"))
    s.add_argument("--scheme", required=True, choices=hooks.SCHEMES)
    s.add_argument("--secret-env", required=True)
    s.add_argument("--becomes", choices=hooks.BECOMES, default="signal")
    s.add_argument("--project", help="the project a source that becomes a change files on")
    s.add_argument("--tolerance", type=int, default=hooks.TOLERANCE)
    s.add_argument("--bind", action="append", help="a project the source belongs to; its automations react")
    b = _signer(_leaf(hk, "bind", "IT binds an inbound source to projects (none: the factory only)", "source"))
    b.add_argument("--project", dest="projects", action="append", default=[])
    _signer(_leaf(hk, "remove", "IT stops an inbound source", "source"))
    _leaf(hk, "list", "the inbound sources")
    con = sub.add_parser("connector", help="the connector model (kernel/connectors.py)").add_subparsers(
        dest="sub", required=True)
    for name, about, signed in (("validate", "check a connector folder's connector.json", False),
                                ("enable", "IT enables a connector: a connector card pins it", True),
                                ("disable", "IT turns a connector off", True)):
        p = _leaf(con, name, about, "system")
        if signed:
            _signer(p)
        if name != "disable":
            p.add_argument("--root", default=str(connectors.DEFAULT_ROOT), help="the folder of connector folders")
    for name, about in (("status", "every connector and whether it may run"),
                        ("check", "stop changed connectors and reopen their cards")):
        _leaf(con, name, about).add_argument("--root", default=str(connectors.DEFAULT_ROOT))
    return parser


# -- the handlers: each returns what the command prints ------------------------------------------------

def _subscribe(f: Factory, a: Args) -> Any:
    mail = {"host": a.smtp_host, "port": a.smtp_port, "from": a.mail_from, "to": a.mail_to or [],
            "starttls": a.starttls, "user_env": a.smtp_user_env, "password_env": a.smtp_password_env}
    return relay.subscribe(f, sink=a.sink, person=a.person, persona=a.persona, url=a.url, url_env=a.url_env,
                           secret_env=a.secret_env, types=a.types, personas=a.notify, kinds=a.kinds,
                           mail=mail if a.sink == "email" else None, projects=a.projects)


def _validate(f: Factory, a: Args) -> Any:
    doc = connectors.load(a.root, a.system)
    return {"system": a.system, "valid": True, "tools_sha256": doc["tools_sha256"],
            "read_tools": [t["name"] for t in doc["read_tools"]], "forbidden_tools": doc["forbidden_tools"]}


COMMANDS: dict[str, Command] = {
    "relay subscribe": _subscribe,
    "relay unsubscribe": lambda f, a: relay.unsubscribe(f, a.id, person=a.person, persona=a.persona),
    "relay cockpit": lambda f, a: relay.set_cockpit(f, a.url, person=a.person, persona=a.persona),
    "relay list": lambda f, a: relay.config(f),
    "relay run": lambda f, a: relay.run(f),
    "relay log": lambda f, a: {"deliveries": relay.deliveries(f, subscription=a.subscription, limit=a.limit),
                               "log_intact": relay.log_intact(f)},
    "hooks add": lambda f, a: hooks.add_source(f, a.source, scheme=a.scheme, secret_env=a.secret_env,
                                               becomes=a.becomes, project=a.project, tolerance=a.tolerance,
                                               bind=a.bind, person=a.person, persona=a.persona),
    "hooks bind": lambda f, a: hooks.bind_source(f, a.source, a.projects, person=a.person, persona=a.persona),
    "hooks remove": lambda f, a: hooks.remove_source(f, a.source, person=a.person, persona=a.persona),
    "hooks list": lambda f, a: {"sources": hooks.sources(f)},
    "connector validate": _validate,
    "connector enable": lambda f, a: connectors.enable(f, a.system, person=a.person, persona=a.persona,
                                                       root=a.root),
    "connector disable": lambda f, a: connectors.disable(f, a.system, person=a.person, persona=a.persona),
    "connector status": lambda f, a: {"connectors": connectors.status(f, root=a.root)},
    "connector check": lambda f, a: {"stopped": connectors.check(f, root=a.root)},
}


def handlers(show: Callable[[Any], None]) -> dict[str, Callable[[Factory, Args], None]]:
    """The commands as `rihmasto` runs them: each shows what its handler returns."""
    def printing(command: Command) -> Callable[[Factory, Args], None]:
        return lambda f, a: show(command(f, a))

    return {name: printing(command) for name, command in COMMANDS.items()}
