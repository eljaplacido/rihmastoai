"""Embeds: a small chat that end users or business people use on a website, feeding the factory.

The owner's idea: "chop this into just a chat window and embed it on a website". An embed is
a chat widget with exactly one capability:

- **feedback:** the end users of a product's release tell the factory what they saw. Each message
  thread becomes a change card on that project (source: end user), triaged by the rules when it is
  filed, like feedback typed in the cockpit: a change request or a new requirement then waits in
  the owners' decision queue;
- **need:** people in the business describe a need. It becomes a signal in the delivery square,
  and from there a concept for a business owner to validate.

What an embed can never do: read the canon, decide anything, see other projects, or reach the
cockpit. Its chat answers only from a public brief (the product's name and what it is for) and
never from the project's records.

Safety:
- an embed is created by a product owner, business owner or IT, with a list of allowed origins
  (websites);
- its key is shown once and stored only as a hash. It is publishable, like a site key: what
  protects it is the origin list, the rate limit, and the single capability;
- a person revokes it with one call. A revoke wins over a turn in flight: the turn checks the
  embed again, under the embeds lock, right before it files;
- messages are capped in length and in rate per embed.

Turns arrive in parallel (the embed server answers each request on its own thread) while the
cockpit may create or revoke an embed. Writes of embeds.json and the filing of a turn therefore
take one lock (``_writing``): across this process's threads and across processes.

The chat's model is optional. Any failure of it (a busy lane, a timeout, an answer that is not
the JSON asked for) files the message without a model reply: a website's visitor is never left
waiting on, or refused because of, the factory's own model work.

A website reaches the embed server (``embed/server.py``), never the cockpit: the cockpit stays on
loopback and serves no widget. The snippet points at the embed server's public address, which the
cockpit is given (``--embed-base`` or ``RIHMA_EMBED_BASE``). Without one, the snippet says so and
points at the local embed server, for testing only.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import re
import secrets
import threading
from collections.abc import Iterator
from typing import Any
from urllib.parse import SplitResult, urlsplit

from kernel.canon import DecisionRefused
from kernel.filelock import locked
from kernel.model import Model, extract_json
from kernel.people import is_person
from kernel.store import Factory, read_json

KINDS = ("feedback", "need")
CREATORS = ("product_owner", "business_owner", "it")
MAX_MESSAGE = 2000
MAX_TURNS = 4
MAX_REPLY = 1000
RATE_PER_MINUTE = 20
THANKS = "Thank you. It has been passed on to the team."
# One writer of embeds.json, and one filing turn, at a time in this process; the file lock in
# _writing extends that to other processes (the cockpit, the CLI).
_FILING = threading.Lock()
_ORIGIN = re.compile(r"^(https://[a-z0-9.-]+(:\d+)?|http://(localhost|127\.0\.0\.1)(:\d+)?)$")
# Where websites reach the embed server: configured for the cockpit, else the local default for testing.
EMBED_BASE_ENV = "RIHMA_EMBED_BASE"
LOCAL_EMBED_PORT = 8790                       # `python -m embed.server` listens here by default
LOCAL_EMBED_BASE = f"http://127.0.0.1:{LOCAL_EMBED_PORT}"
_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?\Z")
_BASE_PATH = re.compile(r"(/[A-Za-z0-9._~-]+)*\Z")


def _store(factory):
    from kernel.learn import factory_project

    return factory_project(factory)


def embeds(factory: Factory) -> list:
    """Every embed, read without creating the factory's own canon (a read never writes)."""
    from kernel.learn import FACTORY_PID

    return read_json(factory.projects_dir / FACTORY_PID / "embeds.json", []) or []


def _save(factory, items) -> None:
    _store(factory).write("embeds.json", items)


@contextlib.contextmanager
def _writing(factory: Factory) -> Iterator[None]:
    """Hold embeds.json, and the filing of a turn, for one writer: this process's threads and other
    processes (a revoke from the cockpit while the embed server files) take turns."""
    with _FILING, locked(_store(factory).path(".embeds.lock")):
        yield


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create(factory: Factory, *, kind: str, origins: list, person: str, persona: str,
           project_id: str | None = None, label: str = "", brief: str = "") -> dict:
    """Create an embed. Returns it with its key; the key is never shown again."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in CREATORS:
        raise DecisionRefused(f"a {persona} may not create an embed; {', '.join(CREATORS)} may")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if kind == "feedback":
        if not project_id:
            raise ValueError("a feedback embed belongs to a project")
        factory.project(project_id)  # raises KeyError for an unknown project
    clean = []
    for o in origins or []:
        o = str(o).strip().rstrip("/").lower()
        if not _ORIGIN.match(o):
            raise ValueError(f"an origin is https://host[:port], or http://localhost for testing; got {o!r}")
        clean.append(o)
    if not clean:
        raise ValueError("an embed needs at least one allowed origin")
    key = "rk_" + secrets.token_urlsafe(24)
    with _writing(factory):
        items = embeds(factory)
        e = {"id": f"E-{len(items) + 1:03d}", "kind": kind, "project": project_id, "origins": sorted(set(clean)),
             "label": str(label)[:80], "brief": str(brief)[:600], "key_sha256": _hash(key), "state": "active",
             "created_by": person, "persona": persona, "created": factory.clock.stamp(), "messages": 0}
        items.append(e)
        _save(factory, items)
    _store(factory).log("embed_created",
                        {k: e[k] for k in ("id", "kind", "project", "origins", "created_by", "persona")})
    return {**e, "key": key}


def revoke(factory: Factory, embed_id: str, *, person: str, persona: str) -> dict:
    """Revoke an embed. It takes the embeds lock, so no turn files after it and no turn's count
    write brings the embed back."""
    if not is_person(person) or persona not in CREATORS:
        raise DecisionRefused("only a product owner, business owner or IT revokes an embed")
    if not any(x["id"] == embed_id for x in embeds(factory)):
        raise KeyError(embed_id)
    with _writing(factory):
        items = embeds(factory)
        e = next(x for x in items if x["id"] == embed_id)
        e["state"] = "revoked"
        _save(factory, items)
    _store(factory).log("embed_revoked", {"id": embed_id, "by": person, "persona": persona})
    return e


def public(e: dict) -> dict:
    """What anyone may know about an embed: never its key hash."""
    return {k: v for k, v in e.items() if k != "key_sha256"}


def embed_base(value: str | None) -> str | None:
    """The embed server's public address, checked and without a trailing slash; None when unset.

    It is https://host[:port][/path], or plain http on localhost or 127.0.0.1 for testing: the same
    rule as an embed's origins. Anything else (a query, a fragment, a user name) is a ValueError."""
    text = str(value or "").strip().rstrip("/")
    if not text:
        return None
    parts = urlsplit(text)
    if not _base_ok(parts):
        raise ValueError(f"the embed base is https://host[:port][/path], or http://127.0.0.1:<port> for testing; "
                         f"got {text[:120]!r}")
    return f"{parts.scheme}://{parts.netloc.lower()}{parts.path}"


def _base_ok(parts: SplitResult) -> bool:
    host = parts.hostname or ""
    if parts.scheme == "https":
        ok = bool(_HOST.match(host))
    else:
        ok = parts.scheme == "http" and host in ("localhost", "127.0.0.1")
    if not ok or "@" in parts.netloc or parts.query or parts.fragment:
        return False
    try:
        port = parts.port
    except ValueError:  # not a number, or out of range
        return False
    return (port is None or port > 0) and bool(_BASE_PATH.match(parts.path))


def snippet(e: dict, base_url: str | None, key: str = "<the key shown once>") -> str:
    """The script tag a website includes. ``base_url`` is the embed server's public address (never
    the cockpit's). Without one, the snippet says how to set it and points at the local embed server
    (LOCAL_EMBED_BASE), which only a browser on the same machine reaches: for testing."""
    base = embed_base(base_url) or LOCAL_EMBED_BASE
    tag = (f'<script src="{base}/e/{e["id"]}/widget.js" data-rihma-embed="{e["id"]}" '
           f'data-key="{key}" data-endpoint="{base}" defer></script>')
    if embed_base(base_url):
        return tag
    return (f"<!-- No embed server address is set: this tag points at the local embed server ({LOCAL_EMBED_BASE}), "
            f"for testing only. For a website, put your embed server's public https address in its place, and "
            f"start the cockpit with --embed-base <that address> (or set {EMBED_BASE_ENV}). -->\n{tag}")


class EmbedRefused(PermissionError):
    """A message the embed does not accept: wrong key, origin not allowed, revoked, too long or too fast."""


class BadTurn(ValueError):
    """A turn the embed cannot read. Its words are written for the website, which may show them."""


def check(factory: Factory, embed_id: str, key: str, origin: str | None) -> dict:
    e = next((x for x in embeds(factory) if x["id"] == embed_id), None)
    if e is None or e["state"] != "active":
        raise EmbedRefused("no such active embed")
    if not hmac.compare_digest(_hash(str(key or "")), e["key_sha256"]):
        raise EmbedRefused("wrong key")
    if (origin or "").rstrip("/").lower() not in e["origins"]:
        raise EmbedRefused("this website is not allowed to use the embed")
    if turned_off(factory, e):
        raise EmbedRefused("this chat is turned off")
    return e


def turned_off(factory: Factory, e: dict) -> str | None:
    """The module that is off where this embed files (FR-MOD5): Integrations, and what it files into, the
    change loop on its project for feedback or the delivery square for a need. A chat that is off takes no
    message; revoking it stays open to its owners (a core command and route, kernel/modules.py)."""
    from kernel import modules

    return modules.first_off(factory, ("integrations", "change" if e["kind"] == "feedback" else "square"),
                             e.get("project"))


def _reply_prompt(e: dict, title: str, history: list) -> str:
    convo = "\n".join(f"{m['role']}: {m['text']}" for m in history[-MAX_TURNS * 2:])
    purpose = ("tell the team what they saw while using it" if e["kind"] == "feedback"
               else "describe a need the business has")
    return f"""You are a short, friendly intake assistant on a website. People use you to {purpose}.
The product or team: {title}. {e.get('brief', '')}

You know nothing else about the product, its code or its plans, so never promise anything or
describe how it works inside. Ask at most one clarifying question when the message lacks what
someone would need to act on it (what they tried, what happened, what they expected, how often).
When it is clear enough, thank them and say it has been passed on.

The conversation so far:
{convo}

Answer with this JSON in a ```json block:
{{"reply": "your message to the person, in their language",
  "ready": true, "summary": "one or two sentences a product owner can act on"}}
Set "ready" to false only when you are asking a clarifying question.
"""


def _turns(history: Any) -> list[dict]:
    """The conversation as the widget sent it, trimmed: at most MAX_TURNS exchanges, each message
    capped. The last message must be the person's."""
    if not isinstance(history, (list, tuple)):
        raise BadTurn("the history is a list of messages")
    kept = [m for m in history if isinstance(m, dict) and m.get("role") in ("person", "assistant")][-MAX_TURNS * 2:]
    turns = [{"role": m["role"], "text": str(m.get("text", ""))[:MAX_MESSAGE]} for m in kept]
    if not turns or turns[-1]["role"] != "person" or not turns[-1]["text"].strip():
        raise BadTurn("the last message must be the person's, and not empty")
    return turns


def _title(factory: Factory, e: dict) -> str:
    """What the chat calls the product or team: the project's title, or the embed's label."""
    if e["project"]:
        return str(factory.project(e["project"]).meta.get("title") or "the product")
    return str(e["label"] or "the team")


def _answer(model: Model | None, e: dict, title: str, turns: list) -> dict | None:
    """The model's answer as {"ready", "reply", "summary"}, or None when there is no usable one.

    None covers no model, a busy lane, a timeout, any other failure of the model, and an answer that
    is not the JSON object asked for. The turn is then filed without a model reply. A question back
    with no words in it is no question: the turn is filed."""
    if model is None:
        return None
    try:
        answer = extract_json(model.ask(_reply_prompt(e, title, turns), role="assistant"))
    except Exception:  # a busy lane (LockHeld), a timeout or any model failure: file without a reply
        return None
    if not isinstance(answer, dict):
        return None
    reply = str(answer.get("reply") or "").strip()[:MAX_REPLY]
    return {"ready": bool(answer.get("ready", True)) or not reply, "reply": reply,
            "summary": str(answer.get("summary") or "").strip()}


def _file(factory: Factory, e: dict, key: str, origin: str | None, turns: list, summary: str) -> dict:
    """File the conversation as a change card or a signal, unless the embed was revoked while the
    model answered. Under the embeds lock: parallel turns never share an id, and a revoke never
    lands between the check and the filing."""
    said = "\n".join(f"{'Person' if m['role'] == 'person' else 'Assistant'}: {m['text']}" for m in turns)
    text = f"[embed {e['id']}] {summary[:600]}\n\nThe conversation:\n{said}"
    with _writing(factory):
        check(factory, e["id"], key, origin)
        if e["kind"] == "feedback":
            filed = {"kind": "change", "id": _change(factory, e, text)}
        else:
            from kernel.signals import receive

            s = receive(factory, text, channel="embed", source=f"embed {e['id']} ({e['label'] or 'chat'})")
            filed = {"kind": "signal", "id": s["id"]}
        _count(factory, e["id"])
    return filed


def _change(factory: Factory, e: dict, text: str) -> str:
    """File feedback as a change card on the embed's project and triage it by the rules, as the
    cockpit and MCP triage feedback filed there: a change request or a new requirement then waits in
    the owners' decision queue. A triage that fails leaves the card filed and untriaged, counted in
    the delivery square's end-user feedback; the turn still succeeds, so the website never sends it
    twice."""
    from kernel.change import submit, triage

    project = factory.project(e["project"])
    card = submit(project, persona="end_user", person=f"end user via embed {e['id']}", text=text)
    try:
        triage(project, card["id"], model=None)
    except (OSError, ValueError) as exc:  # a failing disk or an unreadable spec.json
        with contextlib.suppress(OSError):
            project.log("embed_triage_failed", {"card": card["id"], "embed": e["id"], "error": type(exc).__name__})
    return str(card["id"])


def _count(factory: Factory, embed_id: str) -> None:
    """Count one filed message. The caller holds _writing, and only the count changes, so a revoke
    saved before stays saved. The count is a statistic: failing to write it never fails a turn
    that is already filed."""
    items = embeds(factory)
    for x in items:
        if x["id"] == embed_id:
            x["messages"] = x.get("messages", 0) + 1
    with contextlib.suppress(OSError):
        _save(factory, items)


def converse(factory: Factory, embed_id: str, key: str, origin: str | None, history: list, *,
             model: Model | None = None, rate: RateLimit | None = None) -> dict:
    """One turn of an embed's chat. ``history`` is the conversation as the widget holds it, last message
    the person's. Files the feedback or need when it is clear enough, or after MAX_TURNS."""
    e = check(factory, embed_id, key, origin)
    if rate is not None and not rate(embed_id):
        raise EmbedRefused("too many messages: try again in a minute")
    turns = _turns(history)
    answer = _answer(model, e, _title(factory, e), turns)
    person_turns = sum(1 for m in turns if m["role"] == "person")
    if answer is not None and not answer["ready"] and person_turns < MAX_TURNS:
        return {"reply": answer["reply"], "filed": None}          # one clarifying question, nothing filed
    filed = _file(factory, e, key, origin, turns, (answer or {}).get("summary") or turns[-1]["text"])
    # A question the turn limit cut short is not shown: the thread is filed, and the widget starts afresh.
    reply = answer["reply"] if answer is not None and answer["ready"] and answer["reply"] else THANKS
    return {"reply": reply, "filed": filed}


class RateLimit:
    """At most ``per_minute`` filed turns per embed, in memory, for one server process."""

    def __init__(self, clock: Any, per_minute: int = RATE_PER_MINUTE) -> None:
        self.clock, self.per_minute = clock, per_minute
        self.seen: dict[str, list[float]] = {}

    def __call__(self, embed_id: str) -> bool:
        now = self.clock.now().timestamp()
        recent = [t for t in self.seen.get(embed_id, []) if now - t < 60]
        if len(recent) >= self.per_minute:
            self.seen[embed_id] = recent
            return False
        self.seen[embed_id] = recent + [now]
        return True
