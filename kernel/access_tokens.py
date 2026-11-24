"""The cockpit's sign-in while access is enforced: the identity provider's signed token (D-0016, FR-ID1).

IT's sign-in proxy forwards, on every request, the token the organisation's identity provider signed:
- **oauth2-proxy** passes the OIDC ID token as ``Authorization: Bearer`` (``--pass-authorization-header``),
  or the access token in ``X-Forwarded-Access-Token`` (``--pass-access-token``) where the provider issues
  it as a JWT for this audience;
- **Google IAP** signs ``x-goog-iap-jwt-assertion`` with ES256 (issuer ``https://cloud.google.com/iap``);
- an **AWS Application Load Balancer** signs ``x-amzn-oidc-data`` with ES256. Its token's header names
  the load balancer (``signer``) and the client id (``client``), and carries ``iss`` and ``exp``;
- any other **OIDC** proxy forwards the token in the header the access file names.

The cockpit verifies the token itself (``kernel.jwt_verify``) with the provider's public keys, from a
JWKS file IT keeps beside the access file (``jwks.json`` unless ``proxy.keys`` names another), by key id.
The algorithm is the access file's, never the token's. The identity is ``<issuer>#<subject>``; the name
is the access file's, else the ``proxy.name_claim`` (``email`` unless named); the groups are the
``proxy.groups_claim`` as the token lists them, a JSON list, so a comma is part of a group's name
(Entra ID: ``groups`` or ``roles``; Okta and Keycloak: ``groups``; Cognito: ``cognito:groups``). A claim
name with dots that is not a claim itself is read as a path (``realm_access.roles``).

So the cockpit holds no shared secret. The key file holds public keys only: nothing the cockpit's
process can read, from its environment to its memory, lets anyone sign in as someone else. A token is
refused when it is missing, sent twice, signed with another algorithm or another key, issued by
another issuer or for another audience, expired, or not valid yet.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from kernel.accessfile import SUBJECT, Access, Proxy
from kernel.jwt_verify import Expect, Key, KeyFileError, TokenRefused, parse_jwks, verify

MAX_GROUPS = 1000                   # names in a token's groups claim
_KEYS: dict[str, tuple[Mapping[str, Key], str | None]] = {}   # sha256 of a key file -> (its keys, why unusable)


class Headers(Protocol):
    """A request's headers (``http.client.HTTPMessage``): every value a header name has."""

    def get_all(self, name: str, failobj: Any = ..., /) -> Any: ...


@dataclass(frozen=True)
class SignedIn:
    """What a verified token says: the subject, the name and groups it carries, and when it expires."""

    subject: str
    name: str | None
    groups: tuple[str, ...]
    expires: float


# -- the provider's keys ----------------------------------------------------------------------------------

def with_keys(folder: Path, access: Access) -> Access:
    """``access`` with the identity provider's public keys from the access folder. A key file that is
    missing or not usable leaves ``keys_error``: then nobody signs in to the cockpit, while the command
    line, which signs as the local user, works on."""
    proxy = access.proxy
    if proxy is None or access.error is not None:
        return access
    try:
        raw = (folder / proxy.keys).read_bytes()
    except FileNotFoundError:
        return replace(access, keys_error=f"the key file {proxy.keys} is not in the access folder (IT puts the "
                                          "identity provider's public keys there, as a JWKS)")
    except OSError as exc:
        return replace(access, keys_error=f"the key file {proxy.keys} cannot be read ({type(exc).__name__})")
    sha = hashlib.sha256(raw).hexdigest()
    if sha not in _KEYS:
        if len(_KEYS) > 64:
            _KEYS.clear()
        try:
            _KEYS[sha] = (parse_jwks(raw), None)
        except KeyFileError as exc:
            _KEYS[sha] = ({}, f"the key file {proxy.keys} is not usable: {exc}")
    keys, why = _KEYS[sha]
    if why is None and not any(k.algorithm == proxy.algorithm for k in keys.values()):
        why = f"the key file {proxy.keys} holds no {proxy.algorithm} key, the algorithm the access file names"
    return replace(access, keys=keys, keys_sha256=sha, keys_error=why)


# -- a request's token -----------------------------------------------------------------------------------

def expect(proxy: Proxy) -> Expect:
    """What a token must say, from the access file: AWS ALB names the load balancer and the client id in
    the token's header, and keeps ``iss`` and ``exp`` there; every other preset names the audience."""
    if proxy.signer is not None:
        return Expect(proxy.algorithm, proxy.issuer, None, proxy.clock_skew,
                      header={"signer": proxy.signer, "client": proxy.audience}, header_claims=proxy.header_claims)
    return Expect(proxy.algorithm, proxy.issuer, proxy.audience, proxy.clock_skew)


def once(headers: Headers, name: str) -> str:
    """The one value of a header the proxy sets. More than one is refused: a proxy that appends its value
    to a client's copy instead of replacing it would let the client choose."""
    values = headers.get_all(name) or []
    if len(values) > 1:
        raise TokenRefused(f"the request carries the {name} header more than once; the sign-in proxy sets it once")
    return str(values[0]).strip() if values else ""


def token_of(proxy: Proxy, headers: Headers) -> str:
    """The signed token in the header the access file names (``Authorization``: its Bearer value)."""
    raw = once(headers, proxy.token_header)
    if raw and proxy.token_header.lower() == "authorization":
        scheme, _, raw = raw.partition(" ")
        if scheme.lower() != "bearer":
            raise TokenRefused("the Authorization header carries no Bearer token")
    if not raw.strip():
        raise TokenRefused(f"the request carries no signed token in {proxy.token_header}")
    return raw.strip()


def claim(claims: Mapping[str, Any], name: str) -> Any:
    """A claim by its name, else, for a name with dots, by its path (Keycloak's ``realm_access.roles``)."""
    if name in claims:
        return claims[name]
    value: Any = claims
    for part in name.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def groups_of(claims: Mapping[str, Any], name: str | None) -> tuple[str, ...]:
    """The groups claim as the token lists them: each name whole, commas and all. None named: no groups."""
    value = claim(claims, name) if name else None
    if value is None:
        return ()
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or len(items) > MAX_GROUPS or not all(isinstance(g, str) for g in items):
        raise TokenRefused(f"the token's {name} claim is not a list of group names")
    return tuple(g for g in items if g)


def signed_in(access: Access, headers: Headers, *, now: float | None = None) -> SignedIn:
    """The subject, name, groups and expiry of the request's token, once it verifies (TokenRefused: why not).
    ``access`` has its proxy and keys (``with_keys``)."""
    proxy = access.proxy
    if proxy is None:
        raise TokenRefused("the access file names no sign-in proxy")
    _, claims = verify(token_of(proxy, headers), access.keys, expect(proxy), now=now)
    subject = claim(claims, proxy.subject_claim)
    if not isinstance(subject, str) or not SUBJECT.match(subject):
        raise TokenRefused(f"the token names no subject in its {proxy.subject_claim} claim")
    name = claim(claims, proxy.name_claim)
    name = name.strip() if isinstance(name, str) and name.strip() and len(name) <= 200 else None
    return SignedIn(subject, name, groups_of(claims, proxy.groups_claim), float(claims["exp"]))
