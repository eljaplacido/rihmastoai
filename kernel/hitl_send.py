"""Sending asks and nudges where people are (FR-HITL1): the relay's channels, and WhatsApp behind a provider setting.

The owner (2026-11-25): "it could be also pushed to WhatsApp or any communication channel or web embedding".

- **To a persona inside:** a notice through every Teams, Slack or email subscription IT made for that persona
  (kernel/relay.py, kernel/notices.py), with one link back: the project's People in the loop view. A webhook
  subscription already receives every ask and answer as an event (``rihma.hitl_asked``, ``rihma.hitl_answered``)
  when the relay runs.
- **To a person outside:** their one-use link (kernel/hitl_links.py), sent the moment it is made (the token is
  never kept): by WhatsApp, by email through an email subscription's mail relay, into a Teams or Slack channel's
  subscription, or not sent at all (``copy``: the person who made it passes it on).
- **WhatsApp** goes through the provider IT names: Twilio's Messages API or Meta's WhatsApp Cloud API, with the
  provider's URL and the **name** of the environment variable that holds its key. Rihmasto never stores a key.
  Tests use a stand-in on this machine; a URL is https, or http on 127.0.0.1.

Each send is in the relay's delivery log (which names no URL, no key and no link) and in the project's ledger.
Nothing sent ever decides: an answer is given on the page or in the cockpit, signed. A send with nowhere to go says
what would make it go (which subscription IT adds, or which setting).
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import smtplib
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

from kernel import hitl, notices, relay
from kernel.canon import DecisionRefused
from kernel.hooks import ENV_NAME
from kernel.learn import factory_project
from kernel.ledgerstore import LedgerStore
from kernel.people import is_person
from kernel.store import Factory, Project

PROVIDERS = ("twilio", "meta")
Post = Callable[[str, bytes, dict[str, str]], int]
Send = Callable[[dict[str, Any], EmailMessage, Mapping[str, str]], None]
_ERRORS = (OSError, ValueError, KeyError, smtplib.SMTPException, http.client.HTTPException)


# -- channels, set by IT -------------------------------------------------------------------------------------

def channels(factory: Factory, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """What a send can use: the relay's notice subscriptions, WhatsApp's provider, and where links point."""
    env = os.environ if environ is None else environ
    wa = (hitl.settings(factory).get("channels") or {}).get("whatsapp") or {}
    subs = [{"id": s["id"], "sink": s["sink"], "personas": s.get("personas") or [], "projects": s.get("projects") or []}
            for s in relay.subscriptions(factory) if s["sink"] in relay.NOTICE_SINKS]
    return {"relay": subs,
            "whatsapp": {"provider": wa.get("provider"), "key_env": wa.get("key_env"), "sender": wa.get("sender"),
                         "configured": bool(wa.get("provider")),
                         "key_present": bool(wa.get("key_env") and env.get(wa["key_env"]))},
            "link_base": (hitl.settings(factory).get("channels") or {}).get("link_base")}


def set_whatsapp(factory: Factory, *, provider: str | None, url: str | None, key_env: str | None,
                 sender: str | None, person: str, persona: str, link_base: str | None = None) -> dict[str, Any]:
    """IT names WhatsApp's provider (or none) and where outside reviewers' links point. Never a key: its name."""
    if not is_person(person) or persona != "it":
        raise DecisionRefused("IT sets the channels: a named person as IT")
    wa: dict[str, Any] = {}
    if provider:
        if provider not in PROVIDERS:
            raise ValueError(f"the WhatsApp provider is {' or '.join(PROVIDERS)}")
        if not key_env or not ENV_NAME.match(key_env):
            raise ValueError("name the environment variable that holds the provider's key (A_NAME_LIKE_THIS), not "
                             "the key: Rihmasto never stores a secret")
        wa = {"provider": provider, "url": relay.check_url(str(url or "")), "key_env": key_env,
              "sender": str(sender or "").strip()[:40] or None}
    base = relay.check_url(link_base).rstrip("/") if link_base else None
    factory_project(factory)
    with hitl.updating_settings(factory) as cfg:
        cfg.setdefault("channels", {})["whatsapp"] = wa
        cfg["channels"]["link_base"] = base
    factory_project(factory).log("hitl_channels_set", {"whatsapp": wa.get("provider"), "key_env": wa.get("key_env"),
                                                       "link_base_set": bool(base), "person": person,
                                                       "persona": persona})
    return channels(factory)


# -- WhatsApp -----------------------------------------------------------------------------------------------

def whatsapp_request(cfg: dict[str, Any], to: str, text: str, key: str) -> tuple[str, bytes, dict[str, str]]:
    """(url, body, headers) for one text message: Twilio's form, or Meta Cloud API's JSON."""
    if cfg["provider"] == "twilio":
        body = urlencode({"To": "whatsapp:" + to, "From": "whatsapp:" + str(cfg.get("sender") or ""),
                          "Body": text}).encode("utf-8")
        auth = base64.b64encode(key.encode("utf-8")).decode("ascii")
        return cfg["url"], body, {"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {auth}"}
    body = json.dumps({"messaging_product": "whatsapp", "recipient_type": "individual", "to": to.lstrip("+"),
                       "type": "text", "text": {"preview_url": False, "body": text}}).encode("utf-8")
    return cfg["url"], body, {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}


def _whatsapp(factory: Factory, to: str, text: str, env: Mapping[str, str],
              post: Post) -> tuple[int | None, str | None]:
    cfg = (hitl.settings(factory).get("channels") or {}).get("whatsapp") or {}
    if not cfg.get("provider"):
        return None, "WhatsApp is not set up: IT names the provider in People in the loop, Channels"
    key = env.get(cfg["key_env"] or "")
    if not key:
        return None, f"the provider's key is not in ${cfg['key_env']} on this machine: IT sets that variable"
    url, body, headers = whatsapp_request(cfg, to, text, key)
    try:
        status = post(relay.check_url(url), body, headers)
    except _ERRORS as exc:
        return None, f"{type(exc).__name__}: {str(exc).replace(key, '<$' + cfg['key_env'] + '>')}"[:200]
    return status, None if 200 <= status < 300 else f"HTTP {status}"


# -- one send -----------------------------------------------------------------------------------------------

def _round(factory: Factory, env: Mapping[str, str], post: Post | None, send: Send | None) -> Any:
    return SimpleNamespace(factory=factory, env=env, post=post or relay.post_json, send=send or relay.smtp_send,
                           cockpit=relay.config(factory)["cockpit"])


def _log(factory: Factory, **row: Any) -> None:
    LedgerStore(factory.home / "relay" / "deliveries.jsonl", clock=factory.clock).append("hitl_delivery", row)


def _notice(project: Project, item: dict[str, Any], link: str, *, head: str, detail: str, n: str) -> dict[str, Any]:
    return {"digest": True, "event_id": f"hitl-{project.pid}-{item['id']}-{n}", "headline": notices.defang(head),
            "detail": notices.defang(detail), "link": link, "open_label": "Answer in Rihmasto"}


def _to_subs(rnd: Any, project: Project, personas: list[str], notice: dict[str, Any]) -> list[dict[str, Any]]:
    """Hand a notice to every notice subscription for one of these personas on this project."""
    out = []
    for sub in relay.subscriptions(rnd.factory):
        if sub["sink"] not in relay.NOTICE_SINKS or not set(personas) & set(sub.get("personas") or []):
            continue
        if sub.get("projects") and project.pid not in sub["projects"]:
            continue
        out.append(_post(rnd, sub, notice))
    return out


def _post(rnd: Any, sub: dict[str, Any], notice: dict[str, Any]) -> dict[str, Any]:
    missing = relay._missing(sub, rnd.env)
    if missing:
        return {"subscription": sub["id"], "sink": sub["sink"], "outcome": "not configured",
                "error": f"IT sets {', '.join('$' + m for m in missing)} on this machine"}
    try:
        status: int | None = relay._post_notice(rnd, sub, notice)
        error = None if status is not None and 200 <= status < 300 else f"HTTP {status}"
    except _ERRORS as exc:
        status, error = None, relay._scrub(f"{type(exc).__name__}: {exc}", sub, rnd.env)
    return {"subscription": sub["id"], "sink": sub["sink"], "outcome": "delivered" if error is None else "failed",
            "status": status, "error": error}


def _view_link(rnd: Any, project: Project) -> str:
    return f"{rnd.cockpit.rstrip('/')}/#/p/{project.pid}/loop"


def _nowhere(persona: str) -> str:
    return (f"No channel reaches the {persona.replace('_', ' ')} yet: it waits in People in the loop. IT adds one with "
            f"`rihmasto relay subscribe --sink teams --notify {persona} --url-env TEAMS_URL` (or slack, or email)")


def send_ask(project: Project, ask_id: str, *, person: str, persona: str, environ: Mapping[str, str] | None = None,
             post: Post | None = None, send: Send | None = None) -> dict[str, Any]:
    """Send one open ask to the persona it is put to, through their channels, with a link back."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a send is signed by a named person")
    item = hitl.get(project, ask_id)
    if item["state"] != "open":
        raise ValueError(f"{ask_id} is answered: nothing to send")
    rnd = _round(project.factory, os.environ if environ is None else environ, post, send)
    to = item["to"]["persona"]
    head = f"{hitl.FAMILY_LABEL[item['family']]} {item['kind']} for the {to.replace('_', ' ')}: {item['text'][:140]}"
    notice = _notice(project, item, _view_link(rnd, project), head=head,
                     detail=f"Asked by {item['by']}. Answer it in Rihmasto: nothing in this message answers it.",
                     n=f"send{len(item.get('nudged') or {})}")
    results = _to_subs(rnd, project, [to], notice)
    for r in results:
        _log(project.factory, project=project.pid, ask=ask_id, kind="send", **r)
    project.log("hitl_sent", {"ask": ask_id, "to_persona": to, "channels": [r["subscription"] for r in results],
                              "delivered": sum(r["outcome"] == "delivered" for r in results), "person": person,
                              "persona": persona})
    return {"ask": ask_id, "results": results, "said": _said(results, to)}


def _said(results: list[dict[str, Any]], persona: str) -> str:
    if not results:
        return _nowhere(persona)
    done = [r for r in results if r["outcome"] == "delivered"]
    failed = [f"{r['subscription']} ({r.get('error')})" for r in results if r["outcome"] != "delivered"]
    return (f"Sent to {len(done)} channel(s)." if done else "Not sent.") + \
           (f" Not delivered: {'; '.join(failed)}." if failed else "")


def send_link(project: Project, link: dict[str, Any], address_url: str, *, environ: Mapping[str, str] | None = None,
              post: Post | None = None, send: Send | None = None) -> dict[str, Any]:
    """Send a new link to the person outside by the channel the link names ("copy": the maker passes it on)."""
    contact = link.get("contact") or {}
    channel = contact.get("channel", "copy")
    if channel == "copy":
        return {"channel": "copy", "outcome": "to copy", "said": "Pass it on yourself: it opens once."}
    env = os.environ if environ is None else environ
    rnd = _round(project.factory, env, post, send)
    head = notices.defang(f"{link['created_by']} asks you {len(link['asks'])} question(s) through Rihmasto"
                          + (f" about {link['context']}" if link.get("context") else ""))
    if channel == "whatsapp":
        status, error = _whatsapp(project.factory, contact["address"], f"{head}. Open once: {address_url}", env,
                                  rnd.post)
        row = {"channel": "whatsapp", "outcome": "delivered" if error is None else "failed", "status": status,
               "error": error}
    else:
        row = _link_by_relay(rnd, project, link, channel, contact, address_url, head)
    _log(project.factory, project=project.pid, link=link["id"], kind="link", **{k: v for k, v in row.items()
                                                                                if k != "said"})
    row["said"] = row.get("said") or ("Sent by " + channel + "." if row["outcome"] == "delivered"
                                      else f"Not sent by {channel}: {row.get('error')}. Copy the link instead.")
    return row


def _link_by_relay(rnd: Any, project: Project, link: dict[str, Any], channel: str, contact: dict[str, Any],
                   address_url: str, head: str) -> dict[str, Any]:
    """A link by email (an email subscription's mail relay, to the person's own address) or into a channel."""
    subs = [s for s in relay.subscriptions(rnd.factory) if s["sink"] == channel
            and (channel == "email" or s["id"] == contact.get("address"))]
    if not subs:
        return {"channel": channel, "outcome": "failed", "error": f"no {channel} subscription is set up by IT"}
    sub = dict(subs[0])
    if channel == "email":
        sub["mail"] = dict(sub["mail"], to=[contact["address"]])
    notice = {"digest": True, "event_id": f"hitl-{link['id']}", "headline": head,
              "detail": "Open the link once; it shows only the questions put to you.", "link": address_url,
              "open_label": "Open your questions"}
    return {"channel": channel, **{k: v for k, v in _post(rnd, sub, notice).items() if k in ("outcome", "status",
                                                                                             "error")}}
