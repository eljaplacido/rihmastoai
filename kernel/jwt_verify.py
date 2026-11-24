"""The identity provider's signed token, verified with the standard library (D-0016, FR-ID1).

IT's sign-in proxy forwards the token the organisation's identity provider signed: an OIDC ID token
(oauth2-proxy), Google IAP's ``x-goog-iap-jwt-assertion`` or AWS ALB's ``x-amzn-oidc-data``. The cockpit
verifies it itself, with the provider's public keys from a JWKS file IT puts in the access folder. So it
holds no shared secret: nothing the cockpit can read lets anyone sign in.

Two algorithms, both public-key, written with Python's integers:
- **RS256**, RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017, 8.2.2): ``s^e mod n`` is compared, whole and in
  constant time, with the encoding EMSA-PKCS1-v1_5 builds for the message's hash. Nothing is parsed out
  of the decrypted block, so trailing bytes cannot pass (the e = 3 forgery). Keys under 2048 bits are
  refused.
- **ES256**, ECDSA on P-256 with SHA-256 (FIPS 186-4, RFC 7518 3.4): the signature is r || s, 32 bytes
  each, and the public point must lie on the curve.

The algorithm is the access file's, never the token's: a token whose header names another (``none``,
HS256, RS256 for an ES256 provider) is refused before any key is used. After the signature: the issuer,
the audience, the expiry, not-before and issued-at, within the configured clock skew.

``jwk_from_pem`` turns a public key in PEM form into a JWK (AWS ALB publishes one PEM per key id):
``rihmasto access keys <kid>=<file.pem> ...`` prints the JWKS IT puts in the access folder.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

ALGORITHMS = ("RS256", "ES256")
MAX_TOKEN = 16384                   # characters: a token larger than this is refused unread
MIN_RSA_BITS = 2048
# A JWK's private members (RFC 7518 sections 6.2.2 and 6.3.2): a key file that holds one could mint tokens.
PRIVATE_MEMBERS = ("d", "p", "q", "dp", "dq", "qi", "oth", "k")
_SEGMENT = re.compile(r"[A-Za-z0-9_-]*={0,2}\Z")     # base64url; AWS ALB pads its segments with "="
# DER of DigestInfo for SHA-256 (RFC 8017, 9.2 note 1): what precedes the 32-byte hash.
_SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

# P-256 (FIPS 186-4, D.1.2.3; SEC 2): y^2 = x^3 - 3x + b over GF(p), of prime order n.
_P = 2**256 - 2**224 + 2**192 + 2**96 - 1
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)
Point = tuple[int, int] | None      # None is the point at infinity


class TokenRefused(ValueError):
    """A token that does not verify; the message says why, never what the token holds."""


class KeyFileError(ValueError):
    """A JWKS file that cannot be used; the message starts with the JSON path of what is wrong."""


# -- encodings --------------------------------------------------------------------------------------

def b64url(segment: str) -> bytes:
    """A base64url segment (RFC 7515, 2). Trailing ``=`` padding, as AWS ALB writes it, is taken."""
    if not isinstance(segment, str) or not _SEGMENT.match(segment):
        raise TokenRefused("a part of the token is not base64url")
    bare = segment.rstrip("=")
    if len(bare) % 4 == 1:
        raise TokenRefused("a part of the token is not base64url")
    try:
        return base64.urlsafe_b64decode(bare + "=" * (-len(bare) % 4))
    except (binascii.Error, ValueError):
        raise TokenRefused("a part of the token is not base64url") from None


def _b64url_int(value: object, where: str) -> int:
    if not isinstance(value, str) or not value:
        raise KeyFileError(f"{where} must be a base64url number")
    try:
        return int.from_bytes(b64url(value), "big")
    except TokenRefused:
        raise KeyFileError(f"{where} must be a base64url number") from None


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# -- keys -------------------------------------------------------------------------------------------

def _on_curve(x: int, y: int) -> bool:
    return 0 <= x < _P and 0 <= y < _P and (y * y - x * x * x + 3 * x - _B) % _P == 0


def _add(a: Point, b: Point) -> Point:
    if a is None:
        return b
    if b is None:
        return a
    (x1, y1), (x2, y2) = a, b
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    # the tangent's slope when doubling, the chord's when adding two points
    slope = ((3 * x1 * x1 - 3) * pow(2 * y1, -1, _P) if a == b else (y2 - y1) * pow(x2 - x1, -1, _P)) % _P
    x3 = (slope * slope - x1 - x2) % _P
    return x3, (slope * (x1 - x3) - y1) % _P


def scalar_mult(k: int, point: Point) -> Point:
    """``k`` times ``point`` on P-256, by double and add (public values only: no secret is used here)."""
    out: Point = None
    while k:
        if k & 1:
            out = _add(out, point)
        point = _add(point, point)
        k >>= 1
    return out


@dataclass(frozen=True)
class RsaKey:
    n: int
    e: int
    alg: str | None = None
    algorithm = "RS256"

    def verify(self, signed: bytes, signature: bytes) -> bool:
        size = (self.n.bit_length() + 7) // 8
        if len(signature) != size:
            return False
        s = int.from_bytes(signature, "big")
        if s >= self.n:
            return False
        block = pow(s, self.e, self.n).to_bytes(size, "big")
        info = _SHA256_INFO + hashlib.sha256(signed).digest()
        expected = b"\x00\x01" + b"\xff" * (size - 3 - len(info)) + b"\x00" + info
        return hmac.compare_digest(block, expected)


@dataclass(frozen=True)
class EcKey:
    x: int
    y: int
    alg: str | None = None
    algorithm = "ES256"

    def verify(self, signed: bytes, signature: bytes) -> bool:
        if len(signature) != 64:
            return False
        r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        if not (0 < r < _N and 0 < s < _N):
            return False
        e = int.from_bytes(hashlib.sha256(signed).digest(), "big")
        w = pow(s, -1, _N)
        point = _add(scalar_mult(e * w % _N, _G), scalar_mult(r * w % _N, (self.x, self.y)))
        return point is not None and point[0] % _N == r


Key = RsaKey | EcKey


def _rsa(jwk: dict, where: str) -> RsaKey:
    n, e = _b64url_int(jwk.get("n"), f"{where}.n"), _b64url_int(jwk.get("e"), f"{where}.e")
    if n.bit_length() < MIN_RSA_BITS:
        raise KeyFileError(f"{where}.n is a {n.bit_length()}-bit key; RS256 keys have at least {MIN_RSA_BITS} bits")
    if e < 3 or e % 2 == 0 or e >= n:
        raise KeyFileError(f"{where}.e is not an RSA public exponent")
    return RsaKey(n, e, jwk.get("alg"))


def _ec(jwk: dict, where: str) -> EcKey:
    x, y = _b64url_int(jwk.get("x"), f"{where}.x"), _b64url_int(jwk.get("y"), f"{where}.y")
    if not _on_curve(x, y):
        raise KeyFileError(f"{where} is not a point on P-256")
    return EcKey(x, y, jwk.get("alg"))


def _jwk(jwk: object, where: str) -> Key | None:
    """One key of the set, or None when it is not a signing key for RS256 or ES256 (left aside)."""
    if not isinstance(jwk, dict):
        raise KeyFileError(f"{where} must be an object")
    kty = jwk.get("kty")
    if kty == "oct":
        raise KeyFileError(f"{where} is a symmetric key: the cockpit takes public keys only")
    private = [p for p in PRIVATE_MEMBERS if p in jwk]
    if private:                       # whoever reads the file could sign tokens with it (FR-ID4-AC-5)
        raise KeyFileError(f"{where} holds a private key ({', '.join(private)}): the cockpit takes public keys "
                           "only; IT puts the provider's published keys (its JWKS) here, never a signing key")
    if jwk.get("use", "sig") != "sig" or jwk.get("alg") not in (None, *ALGORITHMS):
        return None
    if kty == "RSA":
        return _rsa(jwk, where)
    if kty == "EC" and jwk.get("crv") == "P-256":
        return _ec(jwk, where)
    return None


def parse_jwks(raw: bytes) -> dict[str, Key]:
    """The RS256 and ES256 signing keys of a JWKS (RFC 7517), by key id; a KeyFileError names what is wrong."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise KeyFileError("$ is not valid JSON") from None
    items = doc.get("keys") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise KeyFileError('$.keys must be a list (a JWKS: {"keys": [...]})')
    keys: dict[str, Key] = {}
    for i, jwk in enumerate(items):
        key = _jwk(jwk, f"$.keys[{i}]")
        if key is None:
            continue
        kid = jwk.get("kid")
        if not isinstance(kid, str) or not 0 < len(kid) <= 256:
            raise KeyFileError(f"$.keys[{i}].kid must name the key")
        if kid in keys:
            raise KeyFileError(f"$.keys[{i}].kid {kid!r} is listed twice")
        keys[kid] = key
    if not keys:
        raise KeyFileError("$.keys holds no RS256 or ES256 signing key")
    return keys


# -- a token --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Expect:
    """What a token must say: the access file's algorithm, issuer and audience, the clock skew allowed,
    header fields that must hold given values (AWS ALB: ``signer`` and ``client``), and claims a provider
    may put in the header instead of the payload (AWS ALB: ``iss`` and ``exp``)."""

    algorithm: str
    issuer: str
    audience: str | None
    leeway: int = 60
    header: Mapping[str, str] = field(default_factory=dict)
    header_claims: tuple[str, ...] = ()


_VERIFIED: dict[tuple[Key, str], bool] = {}          # (key, sha256 of the token) -> its signature held


def _part(segment: str, what: str) -> dict:
    try:
        doc = json.loads(b64url(segment).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise TokenRefused(f"the token's {what} is not a JSON object") from None
    if not isinstance(doc, dict):
        raise TokenRefused(f"the token's {what} is not a JSON object")
    return doc


def _algorithm(header: dict, expect: Expect) -> None:
    alg = header.get("alg")
    if alg == expect.algorithm:
        if "crit" in header:
            raise TokenRefused("the token's header asks for extensions (crit) the cockpit does not know")
        return
    if alg in (None, "", "none"):
        raise TokenRefused("the token is not signed (alg none)")
    if isinstance(alg, str) and alg.upper().startswith("HS"):
        raise TokenRefused(f"the token is signed with a shared secret ({alg}); the cockpit takes only "
                           f"{expect.algorithm}, a public-key signature")
    raise TokenRefused(f"the token is signed with {alg}; the access file names {expect.algorithm}")


def _signature(parts: list[str], header: dict, keys: Mapping[str, Key], expect: Expect) -> None:
    kid = header.get("kid")
    key = keys.get(kid) if isinstance(kid, str) else None
    if key is None:
        raise TokenRefused(f"the token's key {kid!r} is not in the key file; IT adds the provider's current keys")
    if key.algorithm != expect.algorithm or key.alg not in (None, expect.algorithm):
        raise TokenRefused(f"the key {kid!r} is not an {expect.algorithm} key")
    signed = f"{parts[0]}.{parts[1]}".encode("ascii")
    seen = (key, hashlib.sha256(signed + b"." + parts[2].encode("ascii")).hexdigest())
    if seen not in _VERIFIED:
        if len(_VERIFIED) > 512:
            _VERIFIED.clear()
        _VERIFIED[seen] = key.verify(signed, b64url(parts[2]))
    if not _VERIFIED[seen]:
        raise TokenRefused("the token's signature does not verify with the provider's key")


def _number(claims: dict, name: str) -> float | None:
    value = claims.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TokenRefused(f"the token's {name} is not a number")
    return float(value)


def _claims_hold(claims: dict, header: dict, expect: Expect, now: float) -> None:
    for name, want in expect.header.items():
        if not isinstance(header.get(name), str) or not hmac.compare_digest(header[name], want):
            raise TokenRefused(f"the token's header {name} is not the one the access file names")
    if claims.get("iss") != expect.issuer:
        raise TokenRefused("the token was issued by another issuer than the access file names")
    if expect.audience is not None:
        aud = claims.get("aud")
        if aud != expect.audience and not (isinstance(aud, list) and expect.audience in aud):
            raise TokenRefused("the token was issued for another audience than the access file names")
    exp, nbf, iat = (_number(claims, n) for n in ("exp", "nbf", "iat"))
    if exp is None:
        raise TokenRefused("the token has no expiry (exp)")
    if now >= exp + expect.leeway:
        raise TokenRefused("the token has expired; the sign-in proxy forwards a fresh one")
    if nbf is not None and now < nbf - expect.leeway:
        raise TokenRefused("the token is not valid yet (nbf)")
    if iat is not None and iat > now + expect.leeway:
        raise TokenRefused("the token was issued in the future (iat)")


def verify(token: object, keys: Mapping[str, Key], expect: Expect, *, now: float | None = None) -> tuple[dict, dict]:
    """The header and the claims of a signed token (JWS compact serialisation), once its algorithm, its
    signature and its claims hold; a TokenRefused says why not."""
    if expect.algorithm not in ALGORITHMS:
        raise TokenRefused(f"the access file names {expect.algorithm}; the cockpit verifies only {ALGORITHMS}")
    if not isinstance(token, str) or not token:
        raise TokenRefused("there is no token")
    if len(token) > MAX_TOKEN:
        raise TokenRefused(f"the token is longer than {MAX_TOKEN} characters")
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenRefused("the token is not a signed JWT (three parts)" if len(parts) != 5
                           else "the token is encrypted (JWE); the cockpit takes signed tokens")
    header = _part(parts[0], "header")
    _algorithm(header, expect)
    _signature(parts, header, keys, expect)
    claims = _part(parts[1], "payload")
    for name in expect.header_claims:
        if name not in claims and name in header:
            claims[name] = header[name]
    _claims_hold(claims, header, expect, time.time() if now is None else now)
    return header, claims


# -- public keys in PEM (AWS ALB) -------------------------------------------------------------------

_EC_PUBLIC = bytes.fromhex("2a8648ce3d0201")           # 1.2.840.10045.2.1, id-ecPublicKey
_P256 = bytes.fromhex("2a8648ce3d030107")              # 1.2.840.10045.3.1.7, prime256v1
_RSA = bytes.fromhex("2a864886f70d010101")             # 1.2.840.113549.1.1.1, rsaEncryption


def _der(data: bytes, at: int) -> tuple[int, bytes, int]:
    """One DER element at ``at``: its tag, its content and where the next element starts."""
    if at + 2 > len(data):
        raise ValueError("the key is cut short")
    tag, length, at = data[at], data[at + 1], at + 2
    if length & 0x80:
        count = length & 0x7F
        if not 0 < count <= 4 or at + count > len(data):
            raise ValueError("the key has a length it cannot have")
        length, at = int.from_bytes(data[at:at + count], "big"), at + count
    if at + length > len(data):
        raise ValueError("the key is cut short")
    return tag, data[at:at + length], at + length


def _der_seq(data: bytes) -> list[tuple[int, bytes]]:
    out, at = [], 0
    while at < len(data):
        tag, content, at = _der(data, at)
        out.append((tag, content))
    return out


def jwk_from_pem(pem: str, kid: str) -> dict[str, str]:
    """A JWK for a PEM public key (SubjectPublicKeyInfo, RFC 5280): an EC P-256 or an RSA key."""
    body = re.search(r"-----BEGIN PUBLIC KEY-----(.+?)-----END PUBLIC KEY-----", pem, re.S)
    if body is None:
        raise ValueError("not a PEM public key (-----BEGIN PUBLIC KEY-----)")
    der = base64.b64decode("".join(body.group(1).split()), validate=True)
    parts = _der_seq(_der(der, 0)[1])
    if len(parts) < 2:
        raise ValueError("not a SubjectPublicKeyInfo")
    (_, algorithm), (_, bits) = parts[:2]
    ids = [content for t, content in _der_seq(algorithm) if t == 0x06]
    public = bits[1:]                                    # a BIT STRING starts with its count of unused bits
    if ids[:2] == [_EC_PUBLIC, _P256] and len(public) == 65 and public[0] == 4:
        return {"kty": "EC", "crv": "P-256", "kid": kid, "use": "sig", "alg": "ES256",
                "x": b64url_encode(public[1:33]), "y": b64url_encode(public[33:])}
    if ids[:1] == [_RSA]:
        n, e = (int.from_bytes(content, "big") for _, content in _der_seq(_der(public, 0)[1])[:2])
        size = (n.bit_length() + 7) // 8
        return {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256", "n": b64url_encode(n.to_bytes(size, "big")),
                "e": b64url_encode(e.to_bytes((e.bit_length() + 7) // 8, "big"))}
    raise ValueError("the key is neither EC P-256 nor RSA")

