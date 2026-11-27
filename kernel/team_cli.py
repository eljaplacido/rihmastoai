"""`rihmasto access ...` for solo and team mode (D-0024 item 4, FR-PPL1; kernel/team.py).

Read only, unsigned: ``access mode`` (who works here, in plain words), ``access who <pid> <card>`` (who may
decide a card) and ``access test-token --token-file F`` (what a token from team mode's identity provider would
sign in as; the token is read, never kept or printed back).

Signed by a person, IT (``--persona it``, the default) unless said otherwise: ``access team`` and ``access solo``
(the mode; every record stays), ``access user-add``, ``access user-set``, ``access link`` (a one-use sign-in link,
printed once), ``access group`` (a provider's group to a persona), ``access role`` (a project's own roles),
``access idp`` and ``access keys-fetch`` (the identity provider and its public keys), and, as the persona given,
``access agent`` (a persona given to an agent by delegation) and ``access agent-decide`` (a named agent
decides a card within its delegation, run by its operator).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import agent_personas as kagents
from kernel import team as kteam
from kernel import team_access as kteam_access
from kernel.people import PERSONAS
from kernel.store import Factory

Handler = Callable[[Factory, argparse.Namespace], int]
SIGNED = ("access team", "access solo", "access user-add", "access user-set", "access link", "access group",
          "access role", "access idp", "access keys-fetch", "access agent", "access agent-decide")


def _signed(p: argparse.ArgumentParser, persona: str | None = "it") -> None:
    p.add_argument("--person", required=True, help="who makes the change (with access in force: you)")
    p.add_argument("--persona", choices=PERSONAS, default=persona, required=persona is None,
                   help=f"the persona you act as ({persona or 'required'})")


def _csv(text: str | None) -> list[str] | None:
    return None if text is None else [t.strip() for t in text.split(",") if t.strip()]


def _scope(text: str | None) -> Any:
    return "*" if text in (None, "", "*") else _csv(text)


def add_parsers(cmds: Any) -> None:
    """The team mode commands, under `rihmasto access`."""
    cmds.add_parser("mode", help="who works here: solo, team, or IT's access file")
    p = cmds.add_parser("who", help="who may decide a card")
    p.add_argument("project")
    p.add_argument("card")
    p = cmds.add_parser("test-token", help="what a token from team mode's identity provider signs in as")
    p.add_argument("--token-file", required=True)
    for name, about in (("team", "turn team mode on: personas become people and groups"),
                        ("solo", "go back to one person acting in every persona")):
        p = cmds.add_parser(name, help=about)
        p.add_argument("--reason", default="")
        _signed(p)
    p = cmds.add_parser("user-add", help="add a platform user")
    p.add_argument("name")
    p.add_argument("--personas", required=True, help="comma-separated, such as product_owner,developer")
    p.add_argument("--scope", default="*", help='"*" or comma-separated project ids')
    p.add_argument("--email", default="")
    p.add_argument("--identity", help="their identity at the provider (<issuer>#<subject>) or local:<os user>")
    _signed(p)
    p = cmds.add_parser("user-set", help="change a user's name, personas or scope, or (de)activate them")
    p.add_argument("user")
    p.add_argument("--name")
    p.add_argument("--personas")
    p.add_argument("--scope")
    p.add_argument("--deactivate", action="store_true")
    p.add_argument("--activate", action="store_true")
    _signed(p)
    p = cmds.add_parser("link", help="a one-use sign-in link for a user, printed once")
    p.add_argument("user")
    p.add_argument("--kind", choices=tuple(kteam.LINK_HOURS), default="invite")
    p.add_argument("--origin", default="http://127.0.0.1:8787", help="the address people open the cockpit at")
    _signed(p)
    _admin_parsers(cmds)
    _agent_parsers(cmds)


def _admin_parsers(cmds: Any) -> None:
    p = cmds.add_parser("group", help="map an identity provider's group to a persona")
    p.add_argument("group")
    p.add_argument("--to", required=True, choices=PERSONAS)
    p.add_argument("--scope", default="*")
    p.add_argument("--label", default="")
    p.add_argument("--remove", action="store_true")
    _signed(p)
    p = cmds.add_parser("role", help="the personas a user or a group holds on one project")
    p.add_argument("project")
    p.add_argument("--user")
    p.add_argument("--group")
    p.add_argument("--personas", help="comma-separated; leave out with --clear")
    p.add_argument("--clear", action="store_true")
    _signed(p)
    p = cmds.add_parser("idp", help="team mode's identity provider (Entra ID, AWS, Google or any OIDC)")
    for flag in ("preset", "issuer", "origin", "audience"):
        p.add_argument(f"--{flag}", required=True)
    for flag in ("token-header", "algorithm", "subject-claim", "name-claim", "groups-claim", "signer", "jwks-url"):
        p.add_argument(f"--{flag}")
    _signed(p)
    _signed(cmds.add_parser("keys-fetch", help="fetch the provider's public keys once from its JWKS address"))


def _agent_parsers(cmds: Any) -> None:
    p = cmds.add_parser("agent", help="give a persona you act as to an agent, by delegation")
    p.add_argument("pid")
    p.add_argument("--agent", required=True, help="the agent's name, such as ops-agent")
    p.add_argument("--agent-kind", choices=kagents.KINDS, default="bridge")
    p.add_argument("--kinds", required=True, help="comma-separated kinds of card, such as incident")
    p.add_argument("--until", default="7d", help="8h, 3d or a date and time, at most a week away")
    p.add_argument("--verdicts", help="comma-separated verdicts the agent may give (all of the kinds' by default)")
    p.add_argument("--max", type=int, help="the most decisions it makes")
    p.add_argument("--reason", default="")
    _signed(p, None)
    p = cmds.add_parser("agent-decide", help="a named agent decides a card within its delegation")
    p.add_argument("pid")
    p.add_argument("delegation")
    p.add_argument("card")
    p.add_argument("--verdict", required=True)
    p.add_argument("--as", dest="agent", required=True, help="the agent's name")
    p.add_argument("--reason", default="")
    _signed(p, None)


def _who(a: argparse.Namespace) -> dict[str, str]:
    return {"person": a.person, "persona": a.persona}


def _user_set(f: Factory, a: argparse.Namespace) -> dict:
    if a.deactivate or a.activate:
        return kteam.set_active(f, a.user, bool(a.activate), **_who(a))
    return kteam.update_user(f, a.user, name=a.name, personas=_csv(a.personas),
                             scope=_scope(a.scope) if a.scope is not None else None, **_who(a))


def _link(f: Factory, a: argparse.Namespace) -> dict:
    made = kteam.link(f, a.user, kind=a.kind, **_who(a))
    made["url"] = f"{a.origin.rstrip('/')}/#k={made.pop('token')}"
    return made


def _idp(f: Factory, a: argparse.Namespace) -> dict:
    settings = {k: getattr(a, k) for k in ("preset", "issuer", "origin", "audience", "token_header", "algorithm",
                                           "subject_claim", "name_claim", "groups_claim", "signer")}
    return kteam_access.set_idp(f, settings, jwks_url=a.jwks_url, **_who(a))


def _agent(f: Factory, a: argparse.Namespace) -> dict:
    return kagents.assign(f.project(a.pid), _csv(a.kinds) or [], agent_kind=a.agent_kind, agent=a.agent,
                          until=a.until, verdicts=_csv(a.verdicts), max_decisions=a.max, reason=a.reason, **_who(a))


def _agent_decide(f: Factory, a: argparse.Namespace) -> dict:
    return kagents.decide(f.project(a.pid), a.delegation, a.card, a.verdict, agent=a.agent,
                          reason=f"{a.reason} (run by {a.person})".strip())


def handlers(show: Callable[[Any], None]) -> dict[str, Handler]:
    """The `rihmasto access` handlers for solo and team mode."""
    table: dict[str, Callable[[Factory, argparse.Namespace], Any]] = {
        "access mode": lambda f, a: kteam_access.public(f),
        "access who": lambda f, a: kteam_access.who_decides(f, a.project, a.card.upper()),
        "access test-token": lambda f, a: kteam_access.test_token(
            f, Path(a.token_file).read_text(encoding="utf-8")),
        "access team": lambda f, a: kteam.set_mode(f, kteam.TEAM, reason=a.reason, **_who(a)),
        "access solo": lambda f, a: kteam.set_mode(f, kteam.SOLO, reason=a.reason, **_who(a)),
        "access user-add": lambda f, a: kteam.add_user(f, a.name, personas=_csv(a.personas), scope=_scope(a.scope),
                                                       email=a.email, identity=a.identity, **_who(a)),
        "access user-set": _user_set, "access link": _link,
        "access group": lambda f, a: kteam.map_group(f, a.group, a.to, scope=_scope(a.scope), label=a.label,
                                                     remove=a.remove, **_who(a)),
        "access role": lambda f, a: kteam.set_role(f, a.project, user=a.user, group=a.group,
                                                   personas=None if a.clear else _csv(a.personas) or [], **_who(a)),
        "access idp": _idp,
        "access keys-fetch": lambda f, a: kteam_access.fetch_keys(f, person=a.person, persona=a.persona),
        "access agent": _agent, "access agent-decide": _agent_decide,
    }

    def wrap(fn: Callable[[Factory, argparse.Namespace], Any]) -> Handler:
        def run(f: Factory, a: argparse.Namespace) -> int:
            out = fn(f, a)
            show(out)
            return 2 if isinstance(out, dict) and out.get("ok") is False else 0
        return run

    return {name: wrap(fn) for name, fn in table.items()}
