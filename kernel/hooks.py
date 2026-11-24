"""Inbound webhooks: verified doorbells from other systems (D-0015).

A webhook is a doorbell, never a decision. IT names each source in the factory home
(`<home>/hooks/sources.json`, through `rihmasto hooks add`): its scheme, the environment variable that
holds its secret (the secret itself is never stored), and what a ring becomes. IT may bind a source to
projects (`--bind`, `rihmasto hooks bind`): each ring is then recorded in their ledgers too, so their
automations react to it (kernel/automations.py). A delivery is accepted only when:

- its body is at most MAX_BODY bytes;
- its signature verifies: Standard Webhooks v1 (`webhook-id`, `webhook-timestamp` within the
  source's tolerance, `webhook-signature` HMAC-SHA256), or GitHub's `X-Hub-Signature-256`, keyed by
  `X-GitHub-Delivery`;
- its id was not seen before (replay protection; a repeat is answered 200 and stores nothing).

An accepted ring keeps only external ids (an event name, an action, a repository, a number, a pushed
branch, a `ref`), never text from the body, and becomes one **signal** in the delivery square, or one **change
proposal** on a named project, with its ref. A second ring for a ref whose signal is still new, or
whose change card is still open, adds nothing. Nothing an outside system sends decides a card.
Reading the item itself is a connector's job, through Gnomon (kernel/connectors.py).

The same Standard Webhooks scheme signs what the relay sends out (kernel/relay.py, `sign_standard`).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kernel.canon import Canon, DecisionRefused
from kernel.learn import factory_project
from kernel.people import is_person
from kernel.store import Factory, read_json, updating_json

SCHEMES = ("standard", "github")
BECOMES = ("signal", "change")
MAX_BODY = 64 * 1024          # bytes; a doorbell carries ids, never a document
TOLERANCE = 300               # seconds a Standard Webhooks timestamp may differ from the clock
GITHUB_KEEP = 7 * 24 * 3600   # seconds a GitHub delivery id is remembered (GitHub sends no timestamp)
MAX_SEEN = 10000              # delivery ids remembered per source
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
_MSG_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_WORD = re.compile(r"[a-z_]{1,40}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/#@+-]{0,199}\Z")


class HookRefused(ValueError):
    """A delivery the factory does not accept, with the HTTP status that says why."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


# -- Standard Webhooks v1, both ways ----------------------------------------------------------------

def secret_bytes(value: str) -> bytes:
    """A Standard Webhooks key: the base64 after `whsec_`, or the value's own bytes for a plain
    shared secret (as n8n, Zapier and Make let a person type one)."""
    if value.startswith("whsec_"):
        try:
            return base64.b64decode(value[len("whsec_"):], validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("a whsec_ secret is base64 after the prefix") from None
    return value.encode("utf-8")


def sign_standard(key: bytes, msg_id: str, timestamp: int, body: bytes) -> str:
    """The `webhook-signature` of one message: `v1,` and base64 HMAC-SHA256 over `id.timestamp.body`."""
    mac = hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode("ascii")


def verify_standard(headers: Mapping[str, str], body: bytes, key: bytes, *, now: int,
                    tolerance: int = TOLERANCE) -> str:
    """The `webhook-id` of a delivery whose Standard Webhooks signature and timestamp hold."""
    msg_id, stamp = headers.get("webhook-id", ""), headers.get("webhook-timestamp", "")
    signatures = headers.get("webhook-signature", "")
    if not (msg_id and stamp and signatures):
        raise HookRefused(401, "missing webhook-id, webhook-timestamp or webhook-signature")
    if not _MSG_ID.match(msg_id) or not stamp.isdigit():
        raise HookRefused(401, "a malformed webhook-id or webhook-timestamp")
    if abs(now - int(stamp)) > tolerance:
        raise HookRefused(401, "the timestamp is outside the tolerance")
    expected = sign_standard(key, msg_id, int(stamp), body)
    if not any(hmac.compare_digest(s, expected) for s in signatures.split() if s.startswith("v1,")):
        raise HookRefused(401, "the signature does not verify")
    return msg_id


def verify_github(headers: Mapping[str, str], body: bytes, key: bytes) -> str:
    """The `X-GitHub-Delivery` id of a delivery whose `X-Hub-Signature-256` holds."""
    expected = "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(headers.get("x-hub-signature-256", ""), expected):
        raise HookRefused(401, "the signature does not verify")
    delivery = headers.get("x-github-delivery", "")
    if not _MSG_ID.match(delivery):
        raise HookRefused(400, "a malformed X-GitHub-Delivery")
    return delivery


# -- sources, configured by IT -----------------------------------------------------------------------

def _path(factory: Factory, name: str) -> Path:
    return factory.home / "hooks" / name


def sources(factory: Factory) -> list[dict[str, Any]]:
    """The configured sources, removed ones included (they answer 404)."""
    return list((read_json(_path(factory, "sources.json"), {}) or {}).get("sources", []))


def _it_signs(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a configuration change is signed by a named person")
    if persona != "it":
        raise DecisionRefused(f"a {persona} may not configure inbound webhooks: IT does")


def _bound(factory: Factory, projects: list[str] | None) -> list[str]:
    return [factory.project(str(p)).pid for p in dict.fromkeys(projects or [])]


def add_source(factory: Factory, source_id: str, *, scheme: str, secret_env: str, person: str, persona: str,
               becomes: str = "signal", project: str | None = None, tolerance: int = TOLERANCE,
               bind: list[str] | None = None) -> dict[str, Any]:
    """IT names an inbound source: its scheme, its secret's variable and what a ring becomes. ``bind`` names
    the projects the source belongs to: each ring is recorded in their ledgers too, so their automations
    react to it (kernel/automations.py, a hook trigger)."""
    _it_signs(person, persona)
    if not SOURCE_ID.match(source_id):
        raise ValueError("a source id is lower-case letters, digits and hyphens, at most 40")
    if scheme not in SCHEMES or becomes not in BECOMES:
        raise ValueError(f"scheme is one of {SCHEMES} and becomes one of {BECOMES}")
    if not ENV_NAME.match(secret_env):
        raise ValueError("name the environment variable that holds the secret (A_NAME_LIKE_THIS), not the "
                         "secret: Rihmasto never stores one")
    if (becomes == "change") != bool(project):
        raise ValueError("a source that becomes a change names its project (--project), and only then")
    if project:
        factory.project(project)
    if not 30 <= int(tolerance) <= 3600:
        raise ValueError("the tolerance is 30 to 3600 seconds")
    src = {"id": source_id, "scheme": scheme, "secret_env": secret_env, "becomes": becomes, "project": project,
           "projects": _bound(factory, bind), "tolerance": int(tolerance), "state": "active", "by": person,
           "persona": persona, "at": factory.clock.stamp()}
    with updating_json(_path(factory, "sources.json"), {"schema": "rihma.hook-sources/1", "sources": []}) as data:
        data["sources"] = [s for s in data["sources"] if s["id"] != source_id] + [src]
    keys = ("id", "scheme", "becomes", "project", "projects", "by", "persona")
    factory_project(factory).log("hook_source_added", {k: src[k] for k in keys})
    return src


def bind_source(factory: Factory, source_id: str, projects: list[str], *, person: str,
                persona: str) -> dict[str, Any]:
    """IT binds an inbound source to projects (none: to the factory only): its rings go to their ledgers too."""
    _it_signs(person, persona)
    pids = _bound(factory, projects)
    with updating_json(_path(factory, "sources.json"), {"schema": "rihma.hook-sources/1", "sources": []}) as data:
        src = next((s for s in data["sources"] if s["id"] == source_id and s["state"] == "active"), None)
        if src is None:
            raise KeyError(f"no active inbound source {source_id!r}")
        src["projects"] = pids
    factory_project(factory).log("hook_source_bound", {"id": source_id, "projects": pids, "by": person,
                                                       "persona": persona})
    return dict(src)


def remove_source(factory: Factory, source_id: str, *, person: str, persona: str) -> dict[str, Any]:
    """IT stops a source: its deliveries answer 404 from then on."""
    _it_signs(person, persona)
    with updating_json(_path(factory, "sources.json"), {"schema": "rihma.hook-sources/1", "sources": []}) as data:
        src = next((s for s in data["sources"] if s["id"] == source_id and s["state"] == "active"), None)
        if src is None:
            raise KeyError(f"no active inbound source {source_id!r}")
        src.update(state="removed", removed_by=person, removed_at=factory.clock.stamp())
    factory_project(factory).log("hook_source_removed", {"id": source_id, "by": person, "persona": persona})
    return dict(src)


# -- one ring --------------------------------------------------------------------------------------

def _github_ids(headers: Mapping[str, str], doc: dict[str, Any]) -> dict[str, Any]:
    """A GitHub ring's ids: its event and action, the repository, and the issue or pull request number."""
    repo = doc["repository"].get("full_name") if isinstance(doc.get("repository"), dict) else None
    item: dict[str, Any] = next((doc[k] for k in ("issue", "pull_request") if isinstance(doc.get(k), dict)), {})
    number = item.get("number") if isinstance(item.get("number"), int) else None
    named = {"event": headers.get("x-github-event", ""), "action": doc.get("action")}
    ids: dict[str, Any] = {"system": "GitHub"}
    ids.update({k: v for k, v in named.items() if isinstance(v, str) and _WORD.match(v)})
    if isinstance(repo, str) and _REPO.match(repo):
        ids["ref"] = f"gh:{repo}" + (f"#{number}" if number is not None else "")
    return ids


def _standard_ids(source_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    ids: dict[str, Any] = {"system": source_id}
    event = doc.get("type") or doc.get("event")
    if isinstance(event, str) and _REF.match(event):
        ids["event"] = event
    ref = next((v for v in (doc.get("ref"), doc.get("subject"), doc.get("id")) if isinstance(v, str)
                and _REF.match(v)), None)
    if ref:
        ids["ref"] = ref if ":" in ref else f"{source_id}:{ref}"
    return ids


def doorbell_ids(src: dict[str, Any], headers: Mapping[str, str], body: bytes) -> dict[str, Any]:
    """The external ids a ring carries; its text is never read. A ring that names no item is refused."""
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HookRefused(400, "the body is not JSON") from None
    if not isinstance(doc, dict):
        raise HookRefused(400, "the body is not a JSON object")
    ids = _github_ids(headers, doc) if src["scheme"] == "github" else _standard_ids(src["id"], doc)
    if "ref" not in ids:
        raise HookRefused(422, "the ring names no item: a ref, a subject or an id")
    pushed = doc.get("ref")             # a push names its branch: refs/heads/<name>
    if isinstance(pushed, str) and pushed.startswith("refs/heads/") and _REF.match(pushed[11:]):
        ids["branch"] = pushed[11:]
    return ids


def _remember(seen: dict[str, Any], source_id: str, msg_id: str, now: int, keep: int) -> None:
    mine = {k: v for k, v in (seen.get(source_id) or {}).items() if now - int(v) <= keep}
    mine[msg_id] = now
    seen[source_id] = dict(sorted(mine.items(), key=lambda kv: kv[1])[-MAX_SEEN:])


def _ring_text(src: dict[str, Any], ids: dict[str, Any]) -> str:
    """A ring's words: its ids and nothing else, so the triage's word match reads only what the ring named."""
    what = " ".join(str(ids[k]) for k in ("system", "event", "action") if ids.get(k))
    return f"[doorbell {src['id']} ref {ids['ref']}] {what} on {ids['ref']}"


def _become(factory: Factory, src: dict[str, Any], ids: dict[str, Any]) -> dict[str, Any]:
    """The signal or change proposal a ring becomes, or the one it repeats."""
    from kernel import signals
    from kernel.change import submit

    text = _ring_text(src, ids)
    if src["becomes"] == "change":
        project = factory.project(src["project"])
        marker = text.split("]")[0] + "]"
        same = [c for c in Canon(project).cards(kind="change") if str(c["payload"].get("text", "")).startswith(marker)]
        if same:
            return {"repeat_of": same[0]["id"]}
        card = submit(project, persona="stakeholder", person=f"webhook {src['id']}", text=text)
        return {"change": card["id"], "project": project.pid}
    same = [s for s in signals.signals(factory, "new") if s.get("ref") == ids["ref"]]
    if same:
        return {"repeat_of": same[0]["id"]}
    sig = signals.receive(factory, text, channel="feed", source=f"webhook {src['id']}", ref=ids["ref"])
    return {"signal": sig["id"]}


def _verified(src: dict[str, Any], headers: Mapping[str, str], body: bytes, env: Mapping[str, str],
              now: int) -> str:
    value = env.get(src["secret_env"])
    if not value:
        raise HookRefused(503, "this source is not configured on the server")
    try:
        key = secret_bytes(value) if src["scheme"] == "standard" else value.encode("utf-8")
    except ValueError:
        raise HookRefused(503, "this source is not configured on the server") from None
    if src["scheme"] == "github":
        return verify_github(headers, body, key)
    return verify_standard(headers, body, key, now=now, tolerance=int(src.get("tolerance", TOLERANCE)))


def turned_off(factory: Factory, src: dict[str, Any]) -> str | None:
    """The module that is off where this source files (FR-MOD5): Integrations, and what a ring becomes, a
    change on its project or a signal in the delivery square. A ring then stores nothing (403); removing
    the source stays open to IT (`hooks remove` is core, kernel/modules.py)."""
    from kernel import modules

    return modules.first_off(factory, ("integrations", "change" if src["becomes"] == "change" else "square"),
                             src.get("project"))


def receive(factory: Factory, source_id: str, headers: Mapping[str, str], body: bytes, *,
            environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """One delivery to `/hooks/<source_id>`: the HTTP status to answer and what it became. Raises
    HookRefused, having stored nothing, for anything it does not accept."""
    src = next((s for s in sources(factory) if s["id"] == source_id and s["state"] == "active"), None)
    if src is None:
        raise HookRefused(404, "no such source")
    if len(body) > MAX_BODY:
        raise HookRefused(413, "the body is too large")
    lower = {k.lower(): v for k, v in headers.items()}
    now = int(factory.clock.now().timestamp())
    msg_id = _verified(src, lower, body, os.environ if environ is None else environ, now)
    if turned_off(factory, src):   # told only to a sender whose signature holds
        raise HookRefused(403, "this source is turned off")
    keep = GITHUB_KEEP if src["scheme"] == "github" else 2 * int(src.get("tolerance", TOLERANCE))
    with updating_json(_path(factory, "seen.json"), {}) as seen:
        if msg_id in (seen.get(source_id) or {}):
            return {"status": 200, "accepted": False, "reason": "already received"}
        ids = doorbell_ids(src, lower, body)
        became = _become(factory, src, ids)
        _remember(seen, source_id, msg_id, now, keep)
    if "repeat_of" not in became:
        _record_ring(factory, src, msg_id, ids, became)
    return {"status": 202, "accepted": True, **became}


def _record_ring(factory: Factory, src: dict[str, Any], msg_id: str, ids: dict[str, Any],
                 became: dict[str, Any]) -> None:
    """``hook_received`` in the factory's ledger, and in each project the source is bound to, so their
    automations react to it (kernel/automations.py)."""
    record = {"source": src["id"], "id": msg_id, "ref": ids["ref"], **became,
              **({"branch": ids["branch"]} if ids.get("branch") else {})}
    factory_project(factory).log("hook_received", record)
    for pid in src.get("projects") or []:
        factory.project(pid).log("hook_received", record)
