"""Notices: one card, one link (D-0015).

A notice tells a channel that a card waits for one of its personas, or that such a card was decided.
It carries the card's kind, its cleaned and redacted title (kernel/events.py), the personas it waits
on, and exactly one link: the card in the cockpit's Inbox (`<cockpit>/#/p/<pid>/inbox/<card>`). A
title can come from outside, so `defang` removes an address with a scheme, `www.` or `//` in it,
writes a bare domain, a dotted address or a mail address as `evil[.]com` and `boss[at]evil[.]com`,
and breaks a Markdown inline link apart: Teams, Slack and mail clients make no second link of it. A
follow-up says who decided, with which verdict, as which persona.

A notice has no approve button and no reply-to-approve: a person decides in the Inbox, signed with
their name and persona, and nothing in a chat or a mail can stand in for that.

It is rendered for three sinks, and sent through the relay (kernel/relay.py) only when IT configured
one:

- **Teams:** a message with one Adaptive Card 1.4 attachment and one `Action.OpenUrl`, the body a
  Teams workflow ("when a Teams webhook request is received") posts to a channel;
- **Slack:** an incoming-webhook body with a fallback `text`, one section and one link button;
- **email:** a plain-text message for IT's mail relay, marked `Auto-Submitted: auto-generated`.
"""

from __future__ import annotations

import datetime as dt
import re
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from kernel.events import CARD_EVENTS

KIND_LABEL = {"question": "Question", "approval": "Approval", "validation": "Validation",
              "deploy_gate": "Deploy gate", "incident": "Incident", "change": "Change", "escalation": "Escalation",
              "road": "Paved road", "trust": "Trust", "holdout_ruling": "Holdout ruling", "concept": "Concept",
              "update": "Update", "connector": "Connector"}
PERSONA_LABEL = {"business_owner": "business owner", "product_owner": "product owner",
                 "concept_evaluator": "concept evaluator", "end_user": "end user", "it": "IT"}
OPEN_LABEL = "Open in the Inbox"
NOT_HERE = "Decide in Rihmasto's Inbox: nothing in this message decides the card."


LINK_REMOVED = "(link removed)"
# An address a chat or mail client would link: with a scheme (`https://`, or one that needs no
# slashes, such as `mailto:`), starting `www.`, or starting `//`. It is removed.
_LINKISH = re.compile(r"(?i)(?:\b(?:[a-z][a-z0-9+.-]*://|(?:mailto|tel|sms|callto|sip|sips|xmpp|skype|msteams|"
                      r"slack|tg|whatsapp|javascript|vbscript|data|file|ftp|news|irc|magnet|ms-[a-z-]+):"
                      r"|www\.)|(?<![\w:/])//(?=\w))[^\s<>()\[\]]*[^\s<>()\[\].,;:!?'\"]")
# What a client links without a scheme: a bare domain (`evil.com/login`), a dotted address and a mail
# address. Their dots and their @ are written so that no client reads them as one: evil[.]com, a[at]b.
_DOTTED_QUAD = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_DOMAIN_DOT = re.compile(r"(?<=[^\W_])[.\u3002\uff0e\uff61](?=[^\W\d_]{2})")
_AT = re.compile(r"(?<=\S)[@\uff20](?=\S)")


def _who(personas: list[str]) -> str:
    names = [PERSONA_LABEL.get(p, p) for p in personas]
    return ", ".join(names[:-1]) + (" or " if len(names) > 1 else "") + names[-1] if names else "a person"


def defang(text: object) -> str:
    """Words a chat or a mail client cannot turn into a second link: a title can come from outside (an
    end user's feedback names its change card). An address with a scheme, `www.` or `//` is removed; a
    bare domain, a dotted address or a mail address keeps its words with its dots written `[.]` and its
    @ `[at]`; Markdown's inline link (`[words](address)`) is broken apart. The card's own link is added
    after, never passed here."""
    out = _LINKISH.sub(LINK_REMOVED, str(text))
    out = _DOTTED_QUAD.sub(lambda m: m.group(0).replace(".", "[.]"), out)
    out = _AT.sub("[at]", _DOMAIN_DOT.sub("[.]", out))
    return out.replace("](", "] (")


def notice_of(event: dict[str, Any]) -> dict[str, Any] | None:
    """The notice a card event makes; None for any other event."""
    card = event.get("card")
    if event.get("event_type") not in CARD_EVENTS or not isinstance(card, dict):
        return None
    out: dict[str, Any] = {"event_id": event["event_id"], "project": event["stream"]["project_id"],
                           "card": card["id"], "card_kind": card.get("kind"),
                           "title": defang(card.get("title") or card["id"]),
                           "waiting": list(card.get("waiting") or []), "link": card["link"],
                           "at": event.get("occurred_at"), "decided": None}
    if event["event_type"] == "card.decided":
        actor = event.get("actor") or {}
        person = actor.get("id")
        out["decided"] = {"verdict": event.get("correlation", {}).get("verdict"),
                          "person": defang(person) if person else None, "persona": actor.get("persona"),
                          "delegation": event.get("correlation", {}).get("delegation")}
    return out


def lines(notice: dict[str, Any]) -> tuple[str, str]:
    """(the headline, the detail) a notice says in every sink. The daily Track digest (kernel/track.py)
    brings its own, made of defanged words."""
    if notice.get("digest"):
        return str(notice["headline"]), str(notice["detail"])
    label = KIND_LABEL.get(str(notice.get("card_kind")), "Card")
    decided = notice.get("decided")
    if decided:
        persona = PERSONA_LABEL.get(str(decided.get("persona")), decided.get("persona") or "a persona")
        by = f", by delegation {decided['delegation']}" if decided.get("delegation") else ""
        return (f"Decided: {label.lower()} {notice['card']}, {notice['title']}",
                f"{decided.get('verdict') or 'decided'} by {decided.get('person') or 'a person'}, as {persona}{by}. "
                f"Project {notice['project']}.")
    return (f"{label} {notice['card']} waits for {_who(notice['waiting'])}: {notice['title']}",
            f"Project {notice['project']}. {NOT_HERE}")


def render_teams(notice: dict[str, Any]) -> dict[str, Any]:
    """The body a Teams workflow webhook takes: one Adaptive Card with one OpenUrl action."""
    head, detail = lines(notice)
    card = {"type": "AdaptiveCard", "version": "1.4",
            "body": [{"type": "TextBlock", "text": head, "weight": "Bolder", "wrap": True},
                     {"type": "TextBlock", "text": detail, "wrap": True, "isSubtle": True}],
            "actions": [{"type": "Action.OpenUrl", "title": OPEN_LABEL, "url": notice["link"]}]}
    return {"type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}


def _slack_escape(text: str) -> str:
    """Slack's three control characters, escaped so a title cannot make a link or a mention."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_slack(notice: dict[str, Any]) -> dict[str, Any]:
    """The body a Slack incoming webhook takes: fallback text, one section and one link button."""
    head, detail = (_slack_escape(s) for s in lines(notice))
    return {"text": head,
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{head}*\n{detail}"}},
                       {"type": "actions", "elements": [{"type": "button", "url": notice["link"],
                                                         "text": {"type": "plain_text", "text": OPEN_LABEL}}]}]}


def render_email(notice: dict[str, Any], *, sender: str, to: list[str], now: dt.datetime) -> EmailMessage:
    """A plain-text mail with the one link. Its Message-ID is the event's id, so a relay that sends it
    twice sends the same message, and no host name is looked up to make one."""
    head, detail = lines(notice)
    msg = EmailMessage()
    msg["Subject"] = f"[Rihmasto] {head}"[:200]
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Date"] = format_datetime(now)
    msg["Message-ID"] = f"<{notice['event_id']}@rihmasto.invalid>"
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(f"{head}\n\n{detail}\n\n{OPEN_LABEL}:\n{notice['link']}\n")
    return msg
