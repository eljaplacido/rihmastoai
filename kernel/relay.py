"""The relay: the factory's ledgers sent out as signed events and as notices (D-0015).

IT configures subscriptions in the factory home (`<home>/relay/subscriptions.json`, through
`rihmasto relay subscribe`). Each names a sink:

- `webhook`: every event whose type matches the subscription's patterns (kernel/events.py), as a
  CloudEvents 1.0 structured JSON body signed with Standard Webhooks v1 (`webhook-id`,
  `webhook-timestamp`, `webhook-signature`). The receiver's URL is kept; the signing secret is
  named by an environment variable, read when a delivery is signed and never stored.
- `teams`, `slack`: a notice (kernel/notices.py) for each card opened for one of the subscription's
  personas, and a follow-up when it is decided, posted to a Teams workflow webhook or a Slack
  incoming webhook. Those URLs hold their own secret, so they are named by a variable too.
- `email`: the same notice through IT's mail relay (SMTP); a password is named by a variable.

`run` is one round, one at a time. For each subscription it reads every ledger from where that
subscription stopped, in order, and checks each ledger's hash chain first: a break halts that
stream at the break. A failed delivery is tried again on the next round after a backoff (5 s, 5 min,
30 min, 2 h, 5 h, 10 h, 10 h); the subscription waits on it, so events stay in order. After the
last attempt the event is logged as failed and the stream moves on. A delivery that cannot even be
sent (a malformed URL in a variable) is a failed attempt like any other: the round goes on to the
other subscriptions. A delivery keeps its `webhook-id` on every attempt, so a receiver that comes
back gets each event once per id. Every attempt is in the delivery log (`<home>/relay/deliveries.jsonl`,
hash-chained), which names no secret and no URL: an error that quotes one reads its variable's name.
A receiver is https, or http on this machine for testing; a redirect is an answer, never followed.

A subscription starts at each ledger's head when it is made: it receives what happens next, not the
history. Nothing is sent while no subscription exists.
"""

from __future__ import annotations

import fnmatch
import http.client
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kernel import notices
from kernel.canon import DecisionRefused
from kernel.events import (
    CARD_EVENTS,
    CONTENT_TYPE,
    DEFAULT_COCKPIT,
    cloudevent,
    encode,
    heads,
    held_strings,
    tail,
    to_event,
)
from kernel.filelock import LockHeld, locked
from kernel.hooks import ENV_NAME, secret_bytes, sign_standard
from kernel.learn import factory_project
from kernel.ledgerstore import LedgerStore
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, Project, read_json, updating_json, write_json

SINKS = ("webhook", "teams", "slack", "email")
NOTICE_SINKS = ("teams", "slack", "email")
BACKOFF = (5, 300, 1800, 7200, 18000, 36000, 36000)   # seconds before attempts 2 to 8 (Standard Webhooks)
MAX_ATTEMPTS = len(BACKOFF) + 1
TIMEOUT = 10
LOOPBACK = ("127.0.0.1", "localhost", "::1")
_PATTERN = re.compile(r"rihma\.[a-z0-9_.*]{1,80}\Z")
_ADDRESS = re.compile(r"[^@\s<>,]{1,64}@[A-Za-z0-9.-]{1,190}\Z")

Post = Callable[[str, bytes, dict[str, str]], int]
Send = Callable[[dict[str, Any], EmailMessage, Mapping[str, str]], None]


# -- the transports --------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer, never followed: a receiver cannot send the relay somewhere else."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OUT = urllib.request.build_opener(_NoRedirect)
_LOCAL = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))   # no proxy on loopback


def post_json(url: str, body: bytes, headers: dict[str, str]) -> int:
    """POST a body and return the HTTP status; an error status is returned, a failed connection raises."""
    opener = _LOCAL if (urlsplit(url).hostname or "") in LOOPBACK else _OUT
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            resp.read(65536)
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        exc.close()
        return int(exc.code)


def smtp_send(mail: dict[str, Any], message: EmailMessage, environ: Mapping[str, str]) -> None:
    """Hand a notice to IT's mail relay, with STARTTLS and a login when the subscription names them."""
    with smtplib.SMTP(mail["host"], int(mail["port"]), timeout=TIMEOUT) as smtp:
        if mail.get("starttls"):
            smtp.starttls(context=ssl.create_default_context())
        if mail.get("user_env"):
            smtp.login(environ[mail["user_env"]], environ[mail["password_env"]])
        smtp.send_message(message)


def check_url(url: str) -> str:
    """A receiver's URL: https, or http on this machine for testing; no user name, no fragment, a port
    that is a number, and no space or control character (a URL from a variable is checked as it is sent)."""
    parts = urlsplit(url)
    local = parts.scheme == "http" and (parts.hostname or "") in LOOPBACK
    if not (parts.scheme == "https" or local) or not parts.hostname or "@" in parts.netloc or parts.fragment:
        raise ValueError("a receiver is an https URL (http only on 127.0.0.1, for testing), with no user name")
    try:
        port_ok = parts.port is None or parts.port > 0
    except ValueError:
        port_ok = False
    if not port_ok or any(ch.isspace() or not ch.isprintable() for ch in url):
        raise ValueError("a receiver's URL has a port that is a number and no space or control character")
    return url


# -- subscriptions, configured by IT ---------------------------------------------------------------

def _dir(factory: Factory) -> Path:
    return factory.home / "relay"


def config(factory: Factory) -> dict[str, Any]:
    """The relay's configuration: the cockpit's address for deep links, and the subscriptions."""
    cfg = read_json(_dir(factory) / "subscriptions.json", None) or {}
    return {"schema": "rihma.relay/1", "cockpit": cfg.get("cockpit", DEFAULT_COCKPIT),
            "subscriptions": list(cfg.get("subscriptions", []))}


def subscriptions(factory: Factory, *, active: bool = True) -> list[dict[str, Any]]:
    return [s for s in config(factory)["subscriptions"] if not active or s.get("state") == "active"]


def _it_signs(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a configuration change is signed by a named person")
    if persona != "it":
        raise DecisionRefused(f"a {persona} may not configure the relay: IT does")


def _env_name(value: str | None, what: str) -> str:
    if not value or not ENV_NAME.match(value):
        raise ValueError(f"name the environment variable that holds {what} (A_NAME_LIKE_THIS), not the value: "
                         "Rihmasto never stores a secret")
    return value


def _mail(mail: dict[str, Any]) -> dict[str, Any]:
    host, port = str(mail.get("host") or ""), int(mail.get("port") or 25)
    to = list(mail.get("to") or [])
    if not host or not to or not all(_ADDRESS.match(a) for a in [str(mail.get("from") or ""), *to]):
        raise ValueError("an email sink names its mail relay (--smtp-host), a sender and at least one recipient")
    if host not in LOOPBACK and not mail.get("starttls"):
        raise ValueError("a mail relay that is not on this machine is reached with STARTTLS (--starttls)")
    out = {"host": host, "port": port, "from": mail["from"], "to": to, "starttls": bool(mail.get("starttls"))}
    if mail.get("user_env") or mail.get("password_env"):
        out.update(user_env=_env_name(mail.get("user_env"), "the user name"),
                   password_env=_env_name(mail.get("password_env"), "the password"))
    return out


def _sink(sink: str, *, url: str | None, url_env: str | None, secret_env: str | None, types: list[str] | None,
          personas: list[str] | None, kinds: list[str] | None, mail: dict[str, Any] | None) -> dict[str, Any]:
    """A subscription's sink, checked: what it receives and where it goes."""
    if sink not in SINKS:
        raise ValueError(f"a sink is one of {SINKS}")
    if sink == "webhook":
        if bool(url) == bool(url_env):
            raise ValueError("a webhook names its receiver: --url, or --url-env when the URL holds a token")
        patterns = types or ["rihma.*"]
        if not all(_PATTERN.match(p) for p in patterns):
            raise ValueError("an event type pattern starts with rihma., such as rihma.card.*")
        return {"url": check_url(url) if url else None, "url_env": _env_name(url_env, "the URL") if url_env else None,
                "secret_env": _env_name(secret_env, "the signing secret"), "types": patterns}
    if url:
        raise ValueError(f"a {sink} URL holds its own secret: name the environment variable that holds it (--url-env)")
    if not personas or not set(personas) <= set(PERSONAS):
        raise ValueError(f"a notice sink serves one or more personas (--notify), from {PERSONAS}")
    out: dict[str, Any] = {"personas": sorted(set(personas)), "kinds": sorted(set(kinds or []))}
    if sink == "email":
        return out | {"mail": _mail(mail or {})}
    return out | {"url_env": _env_name(url_env, f"the {sink} webhook URL")}


def subscribe(factory: Factory, *, sink: str, person: str, persona: str, url: str | None = None,
              url_env: str | None = None, secret_env: str | None = None, types: list[str] | None = None,
              personas: list[str] | None = None, kinds: list[str] | None = None,
              mail: dict[str, Any] | None = None) -> dict[str, Any]:
    """IT adds a subscription. It starts at every ledger's head: what happens next goes out."""
    _it_signs(person, persona)
    spec = _sink(sink, url=url, url_env=url_env, secret_env=secret_env, types=types, personas=personas,
                 kinds=kinds, mail=mail)
    with updating_json(_dir(factory) / "subscriptions.json", config(factory)) as cfg:
        numbers = [int(s["id"].split("-")[1]) for s in cfg["subscriptions"]]
        sub = {"id": f"SUB-{max(numbers, default=0) + 1:03d}", "sink": sink, **spec, "state": "active",
               "by": person, "persona": persona, "at": factory.clock.stamp(), "start": heads(factory)}
        cfg["subscriptions"].append(sub)
    factory_project(factory).log("relay_subscribed", {"id": sub["id"], "sink": sink, "types": sub.get("types"),
                                                      "personas": sub.get("personas"), "by": person,
                                                      "persona": persona})
    return sub


def unsubscribe(factory: Factory, sub_id: str, *, person: str, persona: str) -> dict[str, Any]:
    """IT ends a subscription; nothing more goes to it."""
    _it_signs(person, persona)
    with updating_json(_dir(factory) / "subscriptions.json", config(factory)) as cfg:
        sub = next((s for s in cfg["subscriptions"] if s["id"] == sub_id and s["state"] == "active"), None)
        if sub is None:
            raise KeyError(f"no active subscription {sub_id!r}")
        sub.update(state="removed", removed_by=person, removed_at=factory.clock.stamp())
    factory_project(factory).log("relay_unsubscribed", {"id": sub_id, "by": person, "persona": persona})
    return dict(sub)


def set_cockpit(factory: Factory, url: str, *, person: str, persona: str) -> dict[str, Any]:
    """IT gives the cockpit's address as people reach it (behind IT's proxy): every deep link starts there."""
    _it_signs(person, persona)
    check_url(url)
    with updating_json(_dir(factory) / "subscriptions.json", config(factory)) as cfg:
        cfg["cockpit"] = url.rstrip("/")
    factory_project(factory).log("relay_cockpit_set", {"by": person, "persona": persona})
    return config(factory)


# -- one round -------------------------------------------------------------------------------------

@dataclass
class _Round:
    factory: Factory
    env: Mapping[str, str]
    post: Post
    send: Send
    now: int
    cockpit: str
    held: list[str]
    log: LedgerStore
    streams: dict[str, tuple[Project, list[dict[str, Any]], int | None]] = field(default_factory=dict)


def _wanted(sub: dict[str, Any], event: dict[str, Any]) -> bool:
    """Whether a subscription takes an event: a webhook by its type patterns; a notice sink a card
    event for a card one of its personas decides (question cards only when it names them)."""
    if sub["sink"] == "webhook":
        return any(fnmatch.fnmatchcase("rihma." + event["event_type"], p) for p in sub["types"])
    card = event.get("card") or {}
    if event["event_type"] not in CARD_EVENTS or not set(card.get("waiting") or []) & set(sub["personas"]):
        return False
    return card.get("kind") in sub["kinds"] if sub["kinds"] else card.get("kind") != "question"


def _missing(sub: dict[str, Any], env: Mapping[str, str]) -> list[str]:
    """The variables a subscription names that this process does not have: it waits, losing no attempt."""
    mail = sub.get("mail") or {}
    names = (sub.get("url_env"), sub.get("secret_env"), mail.get("user_env"), mail.get("password_env"))
    return [n for n in names if n and not env.get(n)]


def _send(rnd: _Round, sub: dict[str, Any], event: dict[str, Any]) -> int:
    """Deliver one event to one sink; the HTTP status (250 for a mail handed over)."""
    url = sub.get("url") or rnd.env.get(sub.get("url_env") or "", "")
    if sub["sink"] == "webhook":
        body = encode(cloudevent(event))
        key = secret_bytes(rnd.env[sub["secret_env"]])
        headers = {"Content-Type": CONTENT_TYPE, "User-Agent": "rihmasto-relay", "webhook-id": event["event_id"],
                   "webhook-timestamp": str(rnd.now),
                   "webhook-signature": sign_standard(key, event["event_id"], rnd.now, body)}
        return rnd.post(check_url(url), body, headers)
    notice = notices.notice_of(event) or {}
    if sub["sink"] == "email":
        mail = sub["mail"]
        rnd.send(mail, notices.render_email(notice, sender=mail["from"], to=mail["to"], now=rnd.factory.clock.now()),
                 rnd.env)
        return 250
    render = notices.render_teams if sub["sink"] == "teams" else notices.render_slack
    return rnd.post(check_url(url), encode(render(notice)), {"Content-Type": "application/json"})


def _scrub(text: str, sub: dict[str, Any], env: Mapping[str, str]) -> str:
    """An error's words with every configured secret or URL in it masked, before they are cut: a
    variable's value reads as its name (`<$NAME>`), a receiver's stored URL as `<url>`."""
    mail = sub.get("mail") or {}
    for name in (sub.get("url_env"), sub.get("secret_env"), mail.get("user_env"), mail.get("password_env")):
        if name and env.get(name):
            text = text.replace(env[name], f"<${name}>")
    if sub.get("url"):
        text = text.replace(sub["url"], "<url>")
    return text[:200]


def _deliver(rnd: _Round, sub: dict[str, Any], event: dict[str, Any], state: dict[str, Any]) -> str:
    """One attempt: `delivered`, `retry` (the subscription waits for its backoff) or `failed` (the last
    attempt; the stream moves on). Every attempt is logged."""
    attempt = int(state.get("attempts", 0)) + 1
    try:
        status: int | None = _send(rnd, sub, event)
        error = None if status is not None and 200 <= status < 300 else f"HTTP {status}"
    except (OSError, ValueError, KeyError, smtplib.SMTPException, http.client.HTTPException) as exc:
        status, error = None, _scrub(f"{type(exc).__name__}: {exc}", sub, rnd.env)
    outcome = "delivered" if error is None else "failed" if attempt >= MAX_ATTEMPTS else "retry"
    state["attempts"] = attempt if outcome == "retry" else 0
    state["next_at"] = rnd.now + BACKOFF[attempt - 1] if outcome == "retry" else None
    rnd.log.append("delivery", {"subscription": sub["id"], "sink": sub["sink"], "webhook_id": event["event_id"],
                                "type": "rihma." + event["event_type"], "project": event["stream"]["project_id"],
                                "seq": event["seq"], "attempt": attempt, "outcome": outcome, "status": status,
                                "error": error, "next_at": state["next_at"]})
    return outcome


def _stream(rnd: _Round, sub: dict[str, Any], state: dict[str, Any], pid: str, counts: dict[str, int]) -> bool:
    """Deliver one ledger's new events to one subscription; False when it must wait for a retry."""
    project, records, halted = rnd.streams[pid]
    cursors = state.setdefault("streams", {})
    for record in records[int(cursors.get(pid, sub.get("start", {}).get(pid, -1))) + 1:]:
        event = to_event(project, record, cockpit=rnd.cockpit, held=rnd.held)
        if _wanted(sub, event):
            outcome = _deliver(rnd, sub, event, state)
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome == "retry":
                return False
        cursors[pid] = record["seq"]
    if halted is not None and state.setdefault("halted", {}).get(pid) != halted:
        state["halted"][pid] = halted
        rnd.log.append("halted", {"subscription": sub["id"], "project": pid, "broken_seq": halted})
    return True


def _one(rnd: _Round, sub: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if state.get("next_at") and int(state["next_at"]) > rnd.now:
        return {"id": sub["id"], "state": "waiting", "next_at": state["next_at"]}
    missing = _missing(sub, rnd.env)
    if missing:
        return {"id": sub["id"], "state": "not configured", "missing": missing}
    counts: dict[str, int] = {}
    for pid in rnd.streams:
        if not _stream(rnd, sub, state, pid, counts):
            return {"id": sub["id"], "state": "waiting", "next_at": state["next_at"], **counts}
    return {"id": sub["id"], "state": "up to date", **counts}


def run(factory: Factory, *, environ: Mapping[str, str] | None = None, post: Post | None = None,
        send: Send | None = None) -> dict[str, Any]:
    """One round of deliveries for every active subscription; a round already running answers busy."""
    subs = subscriptions(factory)
    if not subs:
        return {"subscriptions": 0, "results": []}
    results: list[dict[str, Any]] = []
    try:
        with locked(_dir(factory) / "round.lock", blocking=False):
            rnd = _Round(factory, os.environ if environ is None else environ, post or post_json, send or smtp_send,
                         int(factory.clock.now().timestamp()), config(factory)["cockpit"], held_strings(factory),
                         LedgerStore(_dir(factory) / "deliveries.jsonl", clock=factory.clock))
            rnd.streams = {p.pid: (p, *tail(p)) for p in factory.projects()}
            cursors = read_json(_dir(factory) / "cursors.json", {}) or {}
            for sub in subs:
                results.append(_one(rnd, sub, cursors.setdefault(sub["id"], {})))
                write_json(_dir(factory) / "cursors.json", cursors)
    except LockHeld:
        return {"subscriptions": len(subs), "busy": "another relay round is running"}
    return {"subscriptions": len(subs), "results": results}


def deliveries(factory: Factory, *, subscription: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """The delivery log, newest last: every attempt and every halted stream."""
    rows = [dict(r["event"]["payload"], kind=r["event"]["kind"], at=r["event"].get("at"))
            for r in LedgerStore(_dir(factory) / "deliveries.jsonl").records() if isinstance(r, dict)]
    rows = [r for r in rows if subscription is None or r.get("subscription") == subscription]
    return rows[-limit:] if limit > 0 else rows


def log_intact(factory: Factory) -> bool:
    """Whether the delivery log's hash chain holds."""
    return bool(LedgerStore(_dir(factory) / "deliveries.jsonl").verify().intact)

