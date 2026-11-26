"""The morning review digest (FR-REV1): the review as a message, at the time a person sets, held back when
nothing happened.

A person sets their digest: the time (``07:30``), their time zone (``Europe/Helsinki`` where the machine has
the zone database, or an offset such as ``+02:00``), the days (``weekdays``, ``daily`` or ``mon,wed,fri``)
and the receiver, one of the Teams, Slack or mail subscriptions IT configured for their persona (kernel/
relay.py). The setting is theirs, signed, and in the factory's ledger (``review_digest_set``).

The relay carries it: each round (``rihmasto relay run``, scheduled by IT every few minutes) sends a digest
that is due, once on each of its local days, as one notice with one link back to the Review page. Its period
starts at the later of the person's last review and the last digest, so a morning never repeats yesterday's.
When nothing happened in that period the digest is held back and the delivery log says so. A project an
autopilot binds to its sandbox is left out for a receiver that is not a sandbox receiver; only how many were
left out is said. Nothing in the message decides anything: a person decides in the cockpit.

The automations engine, where one is installed, runs the same digest from its template ``TEMPLATE``
("Morning review digest"); without one, the relay round above is the mechanism, as for the daily Track digest.
"""

from __future__ import annotations

import datetime as dt
import http.client
import re
import smtplib
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import read_json, updating_json

TEMPLATE = {"id": "morning-review-digest", "label": "Morning review digest",
            "trigger": {"kind": "schedule", "at": "07:30", "days": "weekdays"},
            "action": "send the person's review (kernel/review_digest.py) to their receiver",
            "holds_back": "when nothing happened since the last review or digest", "decides": "nothing"}
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_SETS = {"weekdays": DAY_NAMES[:5], "daily": DAY_NAMES}
_AT = re.compile(r"([01]\d|2[0-3]):([0-5]\d)\Z")
_OFFSET = re.compile(r"([+-])(\d{2}):(\d{2})\Z")
OPEN_LABEL = "Open the Review"
NOTICE_SINKS = ("teams", "slack", "email")
SHOWN_PER_GROUP = 3


def _file(factory: Any) -> Any:
    return factory.home / "review" / "digests.json"


def zone(tz: str) -> dt.tzinfo:
    """A time zone by name (the zone database) or by offset (``+02:00``); ``UTC`` always."""
    text = str(tz or "").strip()
    if text.upper() in ("UTC", "Z", ""):
        return dt.UTC
    m = _OFFSET.match(text)
    if m:
        minutes = int(m.group(2)) * 60 + int(m.group(3))
        return dt.timezone(dt.timedelta(minutes=minutes if m.group(1) == "+" else -minutes))
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(text)
    except (ImportError, ValueError, OSError, KeyError):
        raise ValueError(f"time zone {text!r} is not known on this machine: give its offset, such as +02:00") from None


def days_of(text: str) -> list[str]:
    raw = str(text or "weekdays").strip().lower()
    if raw in DAY_SETS:
        return list(DAY_SETS[raw])
    days = [d.strip()[:3] for d in raw.split(",") if d.strip()]
    if not days or any(d not in DAY_NAMES for d in days):
        raise ValueError("days are weekdays, daily, or a list such as mon,wed,fri")
    return [d for d in DAY_NAMES if d in days]


def digests(factory: Any, person: str | None = None) -> list[dict[str, Any]]:
    rows = read_json(_file(factory), []) or []
    return [r for r in rows if person is None or r.get("person") == person]


def receivers(factory: Any, persona: str | None = None) -> list[dict[str, Any]]:
    """The notice subscriptions a digest may go to: Teams, Slack or mail, serving the persona."""
    from kernel.relay import subscriptions

    return [{"id": s["id"], "sink": s["sink"], "personas": s.get("personas", [])} for s in subscriptions(factory)
            if s["sink"] in NOTICE_SINKS and (persona is None or persona in (s.get("personas") or []))]


def _schedule(factory: Any, persona: str, subscription: str | None, at: str, days: str, tz: str) -> dict[str, Any]:
    """A digest's time, days, zone and receiver, checked; ValueError says what is wrong."""
    if not _AT.match(str(at or "")):
        raise ValueError("the time is HH:MM, such as 07:30")
    zone(tz)
    ids = [r["id"] for r in receivers(factory, persona)]
    if subscription not in ids:
        raise ValueError(f"the receiver is one of the Teams, Slack or mail subscriptions IT set for the {persona} "
                         f"persona: {', '.join(ids) or 'none yet'}")
    return {"at": at, "days": days_of(days), "tz": str(tz or "UTC").strip() or "UTC", "subscription": subscription}


def set_digest(factory: Any, *, person: str, persona: str, subscription: str | None, at: str = "07:30",
               days: str = "weekdays", tz: str = "UTC", off: bool = False) -> dict[str, Any]:
    """A person sets their morning digest, or turns it off. Signed, and recorded in the factory's ledger."""
    from kernel.access import require
    from kernel.learn import FACTORY_PID, factory_project
    from kernel.store import Project

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a digest is set by the person who gets it")
    if persona not in PERSONAS:
        raise DecisionRefused(f"persona must be one of {', '.join(PERSONAS)}")
    require(factory_project(factory, create=False) or Project(factory, FACTORY_PID), person, persona)
    entry: dict[str, Any] = {"person": person, "persona": persona, "off": bool(off), "set_at": factory.clock.stamp()}
    if not off:
        entry |= _schedule(factory, persona, subscription, at, days, tz)
    with updating_json(_file(factory), []) as rows:
        rows[:] = [r for r in rows if r.get("person") != person] + [entry]
    factory_project(factory).log("review_digest_set", {k: v for k, v in entry.items() if k != "set_at"})
    return entry


def due_day(entry: dict[str, Any], now: dt.datetime, sent: dict[str, Any]) -> str | None:
    """The person's local day when their digest is due now and was not sent (or held back) that day."""
    if entry.get("off") or not entry.get("at"):
        return None
    local = now.astimezone(zone(entry.get("tz", "UTC")))
    if DAY_NAMES[local.weekday()] not in entry.get("days", []) or local.strftime("%H:%M") < entry["at"]:
        return None
    day = local.date().isoformat()
    return None if sent.get("day") == day else day


def notice(factory: Any, entry: dict[str, Any], *, cockpit: str, subscription: dict[str, Any], day: str,
           since: str | None) -> dict[str, Any]:
    """The digest's notice: the review's headline, each group's count with its first items, and one link.
    ``happened`` False: nothing happened in the period, and the relay holds it back."""
    from kernel.autopilot import outbound_hold
    from kernel.notices import defang
    from kernel.review import review

    held: list[str] = []

    def visible(pid: str) -> bool:
        try:
            p = factory.project(pid)
        except KeyError:
            return False
        if not pid.startswith("_") and outbound_hold(p, subscription):
            held.append(pid)
            return False
        return True

    seen = review(factory, person=entry["person"], persona=entry["persona"], since=since, visible=visible, diffs=False)
    key = re.sub(r"[^a-z0-9]+", "-", entry["person"].lower()).strip("-")[:40]
    return {"digest": True, "event_id": f"review-{subscription['id']}-{key}-{day}", "card_kind": None,
            "headline": seen["headline"], "detail": "\n".join(_lines(seen, held, defang)),
            "link": cockpit.rstrip("/") + "/#/review", "open_label": OPEN_LABEL, "day": day, "counts": seen["counts"],
            "held": held, "happened": seen["happened"], "since": seen["since"], "until": seen["until"]}


def _lines(seen: dict[str, Any], held: list[str], defang: Any) -> list[str]:
    """Each group's count with its first items, the cost when priced, and how many projects were left out."""
    lines = []
    for g in (g for g in seen["groups"] if g["count"]):
        lines.append(f"- {g['label']}: {g['count']}")
        lines += [f"  - {defang(it.get('project_title') or it.get('project') or '')}: {defang(it['title'])[:160]}"
                  for it in g["items"][:SHOWN_PER_GROUP]]
    spent = seen["cost"].get("total", {}).get("cloud") if seen["cost"].get("measured") else None
    if spent is not None:
        lines.append(f"- Cost: {spent:.2f} {seen['cost']['currency']} over {seen['cost']['runs']} model runs")
    if held:
        lines.append(f"- {len(held)} more {'project is' if len(held) == 1 else 'projects are'} bound to an "
                     "autopilot's sandbox and not listed here until a person stops the run")
    lines.append("Review, decide and mark it reviewed in Rihmasto: nothing in this message decides anything.")
    return lines


def _post(rnd: Any, sub: dict[str, Any], n: dict[str, Any], post: Any, scrub: Any) -> tuple[int | None, str | None]:
    """One attempt: the HTTP status (250 for a mail handed over) and the error, if any, with secrets masked."""
    try:
        status = post(rnd, sub, n)
    except (OSError, ValueError, KeyError, smtplib.SMTPException, http.client.HTTPException) as exc:
        return None, scrub(f"{type(exc).__name__}: {exc}", sub, rnd.env)
    return status, None if status is not None and 200 <= status < 300 else f"HTTP {status}"


def relay_round(rnd: Any, sub: dict[str, Any], state: dict[str, Any], post: Any, scrub: Any) -> list[str]:
    """Send the digests due on this subscription (kernel/relay.py calls it each round): delivered, retry or
    held back, each in the delivery log. ``post`` hands a notice to the sink; ``scrub`` masks an error."""
    if sub["sink"] not in NOTICE_SINKS:
        return []
    from kernel.review import last_reviewed

    now, outcomes = rnd.factory.clock.now(), []
    marks = state.setdefault("review_digest", {})
    mine = [e for e in digests(rnd.factory) if e.get("subscription") == sub["id"]
            and e.get("persona") in (sub.get("personas") or [])]
    for entry in mine:
        sent = marks.get(entry["person"], {})
        day = due_day(entry, now, sent)
        if day is None:
            continue
        since = max([s for s in (last_reviewed(rnd.factory, entry["person"]), sent.get("until")) if s], default=None)
        n = notice(rnd.factory, entry, cockpit=rnd.cockpit, subscription=sub, day=day, since=since)
        status, error = _post(rnd, sub, n, post, scrub) if n["happened"] else (None, None)
        outcome = "held back" if not n["happened"] else "delivered" if error is None else "retry"
        if outcome != "retry":
            marks[entry["person"]] = {"day": day, "until": n["until"]}
        rnd.log.append("review_digest", {"subscription": sub["id"], "sink": sub["sink"], "person": entry["person"],
                                         "day": day, "outcome": outcome, "status": status, "error": error,
                                         "counts": n["counts"], "sandbox_held": n["held"]})
        outcomes.append(outcome)
    return outcomes
