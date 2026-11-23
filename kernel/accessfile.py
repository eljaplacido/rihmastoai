"""The access file's shape (D-0016, FR-M8): ``rihmasto.access/1``, checked whole and strictly.

The file lives in its own folder, ``projects/_factory/access/access.json``, which IT alone may write
(``kernel.access`` reads it; docs/guides/access.md has an example). This module only says what a valid
file is: ``parse`` returns what it grants, or an ``AccessFileError`` naming the first thing wrong.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from kernel.people import PERSONAS, Identity, is_person

SCHEMA = "rihmasto.access/1"
SINGLE, ENFORCED = "single_operator", "enforced"
MODES = (SINGLE, ENFORCED)
FACTORY_SCOPE = "_factory"          # the factory's own canon (kernel.learn.FACTORY_PID)
ALL = "*"                           # a binding's scope: every project
LOCAL = "local:"
# Headers the cockpit reads for itself: never an identity header.
OWN_HEADERS = {"authorization", "host", "origin", "content-type", "content-length", "cookie"}

_HEADER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}\Z")
_ENV = re.compile(r"[A-Z_][A-Z0-9_]{0,63}\Z")
_PID = re.compile(r"(?:_factory|[a-z0-9][a-z0-9-]{0,80})\Z")
_ISSUER = re.compile(r"https://[^\s#?]{1,240}\Z")
SUBJECT = re.compile(r"[^\s#]{1,255}\Z")
_LOCAL = re.compile(r"local:[^\x00-\x1f#]{1,128}\Z")
_GROUP = re.compile(r"[^\x00-\x1f,]{1,256}\Z")
_ORIGIN = re.compile(r"(?:https://[a-z0-9.-]{1,253}(?::\d{1,5})?|http://(?:127\.0\.0\.1|localhost):\d{1,5})\Z")


class AccessFileError(ValueError):
    """The access file breaks a rule; the message starts with the JSON path of what is wrong."""


@dataclass(frozen=True)
class Proxy:
    """IT's identity-aware proxy: who it says the user is, and the secret that shows it was the proxy."""

    issuer: str
    origin: str
    user_header: str
    secret_header: str
    secret_env: str
    email_header: str | None = None
    groups_header: str | None = None


@dataclass(frozen=True)
class Binding:
    """A subject (one identity) or a group, granted one persona on some projects ("*": every one)."""

    persona: str
    scope: tuple[str, ...]
    subject: str | None = None
    group: str | None = None

    def covers(self, pid: str | None) -> bool:
        return pid is None or ALL in self.scope or pid in self.scope

    def holds(self, ident: Identity) -> bool:
        return self.subject == ident.id if self.subject is not None else self.group in ident.groups


@dataclass(frozen=True)
class Access:
    mode: str = SINGLE
    error: str | None = None
    sha256: str | None = None
    changed_by: str | None = None       # what the file says about who changed it: a claim, never checked
    proxy: Proxy | None = None
    people: Mapping[str, str] = field(default_factory=dict)       # identity -> display name
    bindings: tuple[Binding, ...] = ()

    @property
    def enforced(self) -> bool:
        return self.mode == ENFORCED


def _fail(path: str, what: str) -> AccessFileError:
    return AccessFileError(f"{path} {what}")


def _keys(obj: object, path: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict:
    if not isinstance(obj, dict):
        raise _fail(path, "must be an object")
    missing = [k for k in required if k not in obj]
    if missing:
        raise _fail(f"{path}.{missing[0]}", "is required")
    unknown = sorted(k for k in obj if k not in required and k not in optional)
    if unknown:
        raise _fail(f"{path}.{unknown[0]}", "is not a key of an access file")
    return obj


def _text(obj: dict, key: str, path: str, pattern: re.Pattern[str], what: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not pattern.match(value):
        raise _fail(f"{path}.{key}", f"must be {what}")
    return value


def _proxy(obj: object) -> Proxy:
    path = "$.proxy"
    p = _keys(obj, path, ("issuer", "origin", "user_header", "secret_header", "secret_env"),
              ("email_header", "groups_header"))
    headers = {k: _text(p, k, path, _HEADER, "a header name") for k in
               ("user_header", "secret_header", "email_header", "groups_header") if k in p}
    for key, name in headers.items():
        if name.lower() in OWN_HEADERS:
            raise _fail(f"{path}.{key}", "names a header the cockpit reads for itself")
    if len({n.lower() for n in headers.values()}) != len(headers):
        raise _fail(path, "names one header twice")
    return Proxy(issuer=_text(p, "issuer", path, _ISSUER, "the issuer's https URL, with no query or fragment"),
                 origin=_text(p, "origin", path, _ORIGIN, "the https origin people open (no path)"),
                 secret_env=_text(p, "secret_env", path, _ENV, "an environment variable name"),
                 user_header=headers["user_header"], secret_header=headers["secret_header"],
                 email_header=headers.get("email_header"), groups_header=headers.get("groups_header"))


def _people(items: object) -> dict[str, str]:
    if not isinstance(items, list) or not items:
        raise _fail("$.people", "must be a non-empty list")
    out: dict[str, str] = {}
    for i, item in enumerate(items):
        path = f"$.people[{i}]"
        entry = _keys(item, path, ("identity", "name"), ("note",))
        ident = entry["identity"]
        if not isinstance(ident, str) or not (_LOCAL.match(ident) or _is_oidc(ident)):
            raise _fail(f"{path}.identity", "must be local:<os user> or <issuer>#<subject>")
        name = entry["name"]
        if not isinstance(name, str) or not is_person(name) or name != name.strip() or len(name) > 200:
            raise _fail(f"{path}.name", "must be a person's name")
        if ident in out:
            raise _fail(f"{path}.identity", "is listed twice")
        out[ident] = name
    return out


def _is_oidc(ident: str) -> bool:
    issuer, sep, subject = ident.partition("#")
    return bool(sep) and bool(_ISSUER.match(issuer)) and bool(SUBJECT.match(subject))


def _scope(value: object, path: str) -> tuple[str, ...]:
    if value == ALL:
        return (ALL,)
    if not isinstance(value, list) or not value or len(set(map(str, value))) != len(value) or \
            not all(isinstance(v, str) and _PID.match(v) for v in value):
        raise _fail(path, 'must be "*" or a list of project ids, each once')
    return tuple(value)


def _bindings(items: object, people: Mapping[str, str]) -> tuple[Binding, ...]:
    if not isinstance(items, list) or not items:
        raise _fail("$.bindings", "must be a non-empty list")
    out = []
    for i, item in enumerate(items):
        path = f"$.bindings[{i}]"
        b = _keys(item, path, ("persona", "scope"), ("subject", "group", "note"))
        if ("subject" in b) == ("group" in b):
            raise _fail(path, "must name a subject or a group, not both")
        if b["persona"] not in PERSONAS:
            raise _fail(f"{path}.persona", f"must be one of {', '.join(PERSONAS)}")
        if "subject" in b and b["subject"] not in people:
            raise _fail(f"{path}.subject", "must be an identity listed in $.people")
        group = _text(b, "group", path, _GROUP, "a group name without commas") if "group" in b else None
        out.append(Binding(b["persona"], _scope(b["scope"], f"{path}.scope"), b.get("subject"), group))
    return tuple(out)


def parse(raw: bytes) -> Access:
    """An access file's content, checked whole; an AccessFileError names the first thing wrong."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _fail("$", f"is not valid JSON ({type(exc).__name__})") from None
    _keys(doc, "$", ("schema", "mode"), ("changed_by", "proxy", "people", "bindings", "note"))
    if doc["schema"] != SCHEMA:
        raise _fail("$.schema", f"must be {SCHEMA!r}")
    if doc["mode"] not in MODES:
        raise _fail("$.mode", f"must be one of {', '.join(MODES)}")
    if doc["mode"] == SINGLE:
        _keys(doc, "$", ("schema", "mode"), ("changed_by", "note"))      # nothing to grant: nothing else
        changed_by = doc.get("changed_by")
        if changed_by is not None and not is_person(changed_by):
            raise _fail("$.changed_by", "must name the person who changed the file")
        return Access(SINGLE, changed_by=changed_by)
    _keys(doc, "$", ("schema", "mode", "changed_by", "proxy", "people", "bindings"), ("note",))
    people = _people(doc["people"])
    access = Access(ENFORCED, changed_by=doc["changed_by"], proxy=_proxy(doc["proxy"]), people=people,
                    bindings=_bindings(doc["bindings"], people))
    it_admin = Identity(str(doc["changed_by"]), "")
    if not any(b.subject and b.holds(it_admin) and b.persona == "it" and ALL in b.scope for b in access.bindings):
        raise _fail("$.changed_by", "must be a listed identity that a subject binding grants the it persona on \"*\"")
    return access
