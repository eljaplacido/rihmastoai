"""The access file's shape (D-0016, FR-M8, FR-ID1): ``rihmasto.access/1``, checked whole and strictly.

The file lives in its own folder, ``projects/_factory/access/access.json``, which IT alone may write
(``kernel.access`` reads it; docs/guides/access.md has an example). Beside it IT keeps the identity
provider's public keys, a JWKS file (``jwks.json`` unless ``proxy.keys`` names another). This module only
says what a valid file is: ``parse`` returns what it grants, or an ``AccessFileError`` naming the first
thing wrong.

``proxy`` says how IT's sign-in proxy forwards the provider's signed token (a preset: oauth2-proxy,
google-iap, aws-alb, or a generic oidc proxy), the issuer and audience the token must carry, and the
claims that give the subject, the name and the groups (``kernel.access_tokens``). The cockpit holds no
shared secret: a file that still names one, or the plain identity headers, is refused with what to write
instead. ``isolation`` names where untrusted code runs while access is enforced
(``kernel.access_isolation``): a container through the docker CLI, or a separate operating-system account.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from kernel.jwt_verify import Key
from kernel.people import PERSONAS, Identity, is_person

SCHEMA = "rihmasto.access/1"
SINGLE, ENFORCED = "single_operator", "enforced"
MODES = (SINGLE, ENFORCED)
FACTORY_SCOPE = "_factory"          # the factory's own canon (kernel.learn.FACTORY_PID)
ALL = "*"                           # a binding's scope: every project
LOCAL = "local:"
SESSION_HEADER = "X-Rihmasto-Session"   # the cockpit's own session, with access enforced
# Headers the cockpit reads for itself: never the token's header.
OWN_HEADERS = {"host", "origin", "content-type", "content-length", "cookie", SESSION_HEADER.lower()}

_HEADER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}\Z")
_PID = re.compile(r"(?:_factory|[a-z0-9][a-z0-9-]{0,80})\Z")
_ISSUER = re.compile(r"https://[^\s#?]{1,240}\Z")
SUBJECT = re.compile(r"[^\s#]{1,255}\Z")
_LOCAL = re.compile(r"local:[^\x00-\x1f#]{1,128}\Z")
_GROUP = re.compile(r"[^\x00-\x1f]{1,256}\Z")
_ORIGIN = re.compile(r"(?:https://[a-z0-9.-]{1,253}(?::\d{1,5})?|http://(?:127\.0\.0\.1|localhost):\d{1,5})\Z")
_AUDIENCE = re.compile(r"\S{1,512}\Z")
_CLAIM = re.compile(r"[A-Za-z][A-Za-z0-9_:./-]{0,63}\Z")
_KEYS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json\Z")
_SIGNER = re.compile(r"arn:aws[a-z-]*:elasticloadbalancing:\S{1,400}\Z")
_IMAGE = re.compile(r"[a-z0-9][a-z0-9._/:@-]{0,254}\Z")
_ACCOUNT = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")
_ARG = re.compile(r"[^\x00-\x1f]{1,400}\Z")
# What the shared-secret proxy of phase A read: refused, with what to write instead.
_LEGACY = ("user_header", "email_header", "groups_header", "secret_header", "secret_env")


class AccessFileError(ValueError):
    """The access file breaks a rule; the message starts with the JSON path of what is wrong."""


@dataclass(frozen=True)
class Preset:
    """How one kind of sign-in proxy forwards the token: the algorithms its provider signs with, the
    headers it may carry it in (the first is the default; none named: the file must name one), a fixed
    issuer, and for AWS ALB the load balancer's ARN in the token's header and claims kept there."""

    algorithms: tuple[str, ...]
    headers: tuple[str, ...]
    issuer: str | None = None
    signer: bool = False
    header_claims: tuple[str, ...] = ()


PRESETS = {
    # --pass-authorization-header sends the ID token as "Authorization: Bearer"; --pass-access-token
    # sends the access token in X-Forwarded-Access-Token (oauth2-proxy's flag reference).
    "oauth2-proxy": Preset(("RS256", "ES256"), ("Authorization", "X-Forwarded-Access-Token")),
    "google-iap": Preset(("ES256",), ("x-goog-iap-jwt-assertion",), issuer="https://cloud.google.com/iap"),
    "aws-alb": Preset(("ES256",), ("x-amzn-oidc-data",), signer=True, header_claims=("iss", "exp")),
    "oidc": Preset(("RS256", "ES256"), ()),
}


@dataclass(frozen=True)
class Proxy:
    """IT's sign-in proxy and the identity provider's signed token it forwards (kernel.jwt_verify)."""

    preset: str
    issuer: str
    origin: str
    audience: str
    token_header: str
    algorithm: str
    keys: str = "jwks.json"             # the JWKS file, in the access folder
    subject_claim: str = "sub"
    name_claim: str = "email"
    groups_claim: str | None = None
    signer: str | None = None           # AWS ALB: the load balancer's ARN
    clock_skew: int = 60

    @property
    def header_claims(self) -> tuple[str, ...]:
        return PRESETS[self.preset].header_claims


@dataclass(frozen=True)
class Runner:
    """Where untrusted code runs while access is enforced (``kernel.access_isolation``): a container
    through the docker CLI (``docker_cli``, a command as words), or a separate operating-system account
    through ``sudo -n -u``. ``python`` is the interpreter there; ``cells`` is the command Gnomon runs as
    there, in place of ``$GNOMON_CMD`` (``{cwd}`` in a word is the cell's folder)."""

    kind: str
    image: str | None = None
    account: str | None = None
    docker_cli: tuple[str, ...] = ("docker",)
    python: str = "python3"
    cells: tuple[str, ...] | None = None


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
    isolation: Runner | None = None     # where untrusted code runs (kernel.isolation)
    keys: Mapping[str, Key] = field(default_factory=dict)     # the provider's public keys, by key id
    keys_sha256: str | None = None      # of the key file, as read
    keys_error: str | None = None       # why the key file cannot be used: the cockpit then refuses sign-in

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


def _token_header(p: dict, preset: Preset, path: str) -> str:
    if "token_header" not in p:
        if not preset.headers:
            raise _fail(f"{path}.token_header", f"is required for the {p['preset']} preset: the header that "
                                                "carries the signed token")
        return preset.headers[0]
    name = _text(p, "token_header", path, _HEADER, "a header name")
    if preset.headers and name.lower() not in {h.lower() for h in preset.headers}:
        raise _fail(f"{path}.token_header", f"must be one of {', '.join(preset.headers)} for {p['preset']}")
    if name.lower() in OWN_HEADERS:
        raise _fail(f"{path}.token_header", "names a header the cockpit reads for itself")
    return name


def _claims(p: dict, path: str) -> dict:
    out: dict[str, str | int] = {k: _text(p, k, path, _CLAIM, "a claim name")
                                 for k in ("subject_claim", "name_claim", "groups_claim") if k in p}
    if "clock_skew" in p:
        skew = p["clock_skew"]
        if isinstance(skew, bool) or not isinstance(skew, int) or not 0 <= skew <= 300:
            raise _fail(f"{path}.clock_skew", "must be a whole number of seconds from 0 to 300")
        out["clock_skew"] = skew
    if "keys" in p:
        out["keys"] = _text(p, "keys", path, _KEYS, "a JWKS file name in the access folder, such as jwks.json")
    return out


def _proxy(obj: object) -> Proxy:
    path = "$.proxy"
    legacy = sorted(k for k in obj if k in _LEGACY) if isinstance(obj, dict) else []
    if legacy:
        raise _fail(f"{path}.{legacy[0]}", "is no longer read: the cockpit holds no shared secret and trusts no plain "
                                           "identity header; it verifies the identity provider's signed token (name a "
                                           "preset, the audience and the key file: docs/guides/access.md)")
    p = _keys(obj, path, ("preset", "issuer", "origin", "audience"),
              ("token_header", "algorithm", "keys", "subject_claim", "name_claim", "groups_claim", "signer",
               "clock_skew"))
    preset = PRESETS.get(p["preset"]) if isinstance(p["preset"], str) else None
    if preset is None:
        raise _fail(f"{path}.preset", f"must be one of {', '.join(PRESETS)}")
    issuer = _text(p, "issuer", path, _ISSUER, "the issuer's https URL, with no query or fragment")
    if preset.issuer and issuer != preset.issuer:
        raise _fail(f"{path}.issuer", f"must be {preset.issuer} for {p['preset']}")
    algorithm = p.get("algorithm", preset.algorithms[0])
    if algorithm not in preset.algorithms:
        raise _fail(f"{path}.algorithm", f"must be one of {', '.join(preset.algorithms)} for {p['preset']} "
                                         "(a public-key signature: never none or HS*)")
    signer = None
    if preset.signer:
        signer = _text(p, "signer", path, _SIGNER, "the load balancer's ARN (arn:aws:elasticloadbalancing:...)")
    elif "signer" in p:
        raise _fail(f"{path}.signer", "is read for the aws-alb preset only")
    return Proxy(preset=p["preset"], issuer=issuer, algorithm=algorithm, signer=signer,
                 origin=_text(p, "origin", path, _ORIGIN, "the https origin people open (no path)"),
                 audience=_text(p, "audience", path, _AUDIENCE, "the audience the token is issued for"),
                 token_header=_token_header(p, preset, path), **_claims(p, path))


def _isolation(obj: object) -> Runner:
    path = "$.isolation"
    i = _keys(obj, path, ("runner",), ("image", "account", "docker_cli", "python", "cells", "note"))
    kind = i["runner"]
    if kind not in ("container", "os_account"):
        raise _fail(f"{path}.runner", "must be container or os_account")
    other = "account" if kind == "container" else "image"
    if other in i:
        raise _fail(f"{path}.{other}", f"is not read for a {kind} runner")
    image = _text(i, "image", path, _IMAGE, "the image tests run in, such as python:3.12-slim") \
        if kind == "container" else None
    account = _text(i, "account", path, _ACCOUNT, "the separate account's name") if kind == "os_account" else None
    cells = _words(i, "cells", path, "the command that runs Gnomon through the runner")
    docker = _words(i, "docker_cli", path, "the docker command") if kind == "container" else None
    if kind != "container" and "docker_cli" in i:
        raise _fail(f"{path}.docker_cli", "is read for a container runner only")
    python = _text(i, "python", path, _ARG, "the interpreter's command") if "python" in i else Runner.python
    return Runner(kind, image=image, account=account, cells=cells, docker_cli=docker or Runner.docker_cli,
                  python=python)


def _words(obj: dict, key: str, path: str, what: str) -> tuple[str, ...] | None:
    """A command as a list of words (a single word may be given as text), or None when the key is absent."""
    value = obj.get(key)
    if value is None:
        return None
    words = [value] if isinstance(value, str) else value
    if not isinstance(words, list) or not 0 < len(words) <= 32 or not all(isinstance(w, str) and _ARG.match(w)
                                                                           for w in words):
        raise _fail(f"{path}.{key}", f"must be {what}, as a list of words")
    return tuple(words)


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
        group = _text(b, "group", path, _GROUP, "a group name (commas are part of it)") if "group" in b else None
        out.append(Binding(b["persona"], _scope(b["scope"], f"{path}.scope"), b.get("subject"), group))
    return tuple(out)


def parse(raw: bytes) -> Access:
    """An access file's content, checked whole; an AccessFileError names the first thing wrong."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _fail("$", f"is not valid JSON ({type(exc).__name__})") from None
    _keys(doc, "$", ("schema", "mode"), ("changed_by", "proxy", "people", "bindings", "isolation", "note"))
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
    _keys(doc, "$", ("schema", "mode", "changed_by", "proxy", "people", "bindings"), ("isolation", "note"))
    people = _people(doc["people"])
    access = Access(ENFORCED, changed_by=doc["changed_by"], proxy=_proxy(doc["proxy"]), people=people,
                    bindings=_bindings(doc["bindings"], people),
                    isolation=_isolation(doc["isolation"]) if "isolation" in doc else None)
    it_admin = Identity(str(doc["changed_by"]), "")
    if not any(b.subject and b.holds(it_admin) and b.persona == "it" and ALL in b.scope for b in access.bindings):
        raise _fail("$.changed_by", "must be a listed identity that a subject binding grants the it persona on \"*\"")
    return access
