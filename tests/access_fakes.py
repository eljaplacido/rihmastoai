"""A stand-in for the organisation's identity provider, in pure Python (FR-ID1).

It makes RSA (RS256) and P-256 (ES256) keys and signs tokens with them, so the tests verify real
signatures without a download or a third-party package:
- RSA keys come from Miller-Rabin primes drawn from a seeded generator (test keys, never secrets);
  signatures are RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017, 8.2.1).
- ECDSA signatures on P-256 use RFC 6979's deterministic nonce (HMAC-SHA256), so a signature is the
  same every run, and RFC 6979's own P-256 test vectors (A.2.5) check the signer and the verifier.
- ``Provider`` publishes a JWKS and issues tokens in the shapes oauth2-proxy, Google IAP, AWS ALB and
  a generic OIDC proxy forward.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
import math
import random
import time
from typing import Any

from kernel.jwt_verify import _EC_PUBLIC, _G, _N, _P256, _RSA, b64url_encode, scalar_mult

SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
_SMALL = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p ** 0.5) + 1, 2))]

# RFC 6979, A.2.5: ECDSA on P-256 with SHA-256, the published private key, public key and signatures.
RFC6979_KEY = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
RFC6979_PUBLIC = (0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6,
                  0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299)
RFC6979_SIGNATURES = {
    b"sample": (0xA6E3C57DD01ABE90086538398355DD4C3B17AA873382B0F24D6129493D8AAD60,
                0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716,
                0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8),
    b"test": (0xD16B6AE827F17175E040871A1C7EC3500192C4C92677336EC2537ACAEE0008E0,
              0xF1ABB023518351CD71D881567B1EA663ED3EFCF6C5132B354F28D3B0B7D38367,
              0x019F4113742A2B14BD25926B49C649155F267E60D3814B4C0CC84250E46F0083),
}


# -- RSA ------------------------------------------------------------------------------------------------

def _probable_prime(n: int, rng: random.Random) -> bool:
    if any(n % p == 0 for p in _SMALL):
        return n in _SMALL
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for _ in range(20):
        x = pow(rng.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int, rng: random.Random) -> int:
    while True:
        candidate = rng.getrandbits(bits) | (3 << (bits - 2)) | 1
        if _probable_prime(candidate, rng):
            return candidate


@functools.lru_cache(maxsize=8)
def rsa_key(seed: int = 1, bits: int = 2048, e: int = 65537) -> tuple[int, int, int]:
    """(n, e, d): a test RSA key, the same for the same seed."""
    rng = random.Random(seed)
    while True:
        p, q = _prime(bits // 2, rng), _prime(bits // 2, rng)
        phi = (p - 1) * (q - 1)
        if p != q and math.gcd(e, phi) == 1 and (p * q).bit_length() == bits:
            return p * q, e, pow(e, -1, phi)


def pkcs1(message: bytes, size: int) -> bytes:
    """EMSA-PKCS1-v1_5 of ``message``'s SHA-256, ``size`` bytes long."""
    info = SHA256_INFO + hashlib.sha256(message).digest()
    return b"\x00\x01" + b"\xff" * (size - 3 - len(info)) + b"\x00" + info


def rsa_sign(key: tuple[int, int, int], message: bytes) -> bytes:
    n, _, d = key
    size = (n.bit_length() + 7) // 8
    return pow(int.from_bytes(pkcs1(message, size), "big"), d, n).to_bytes(size, "big")


def cube_root(x: int) -> int:
    """The integer cube root, rounded up."""
    lo, hi = 0, 1 << (x.bit_length() // 3 + 2)
    while lo < hi:
        mid = (lo + hi) // 2
        if mid ** 3 < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


# -- P-256 --------------------------------------------------------------------------------------------------

def ec_public(d: int) -> tuple[int, int]:
    point = scalar_mult(d, _G)
    assert point is not None
    return point


def rfc6979_k(d: int, digest: bytes) -> int:
    """RFC 6979, 3.2: the deterministic nonce for P-256 and HMAC-SHA256."""
    x = d.to_bytes(32, "big")
    h = (int.from_bytes(digest, "big") % _N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < _N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def ec_sign(d: int, message: bytes) -> tuple[int, int]:
    digest = hashlib.sha256(message).digest()
    k = rfc6979_k(d, digest)
    point = scalar_mult(k, _G)
    assert point is not None
    r = point[0] % _N
    s = pow(k, -1, _N) * (int.from_bytes(digest, "big") + r * d) % _N
    return r, s


def ec_key(seed: int = 1) -> int:
    return random.Random(seed).randrange(1, _N)


# -- public keys in PEM ----------------------------------------------------------------------------------------

def _der(tag: int, content: bytes) -> bytes:
    size = len(content)
    if size < 0x80:
        return bytes([tag, size]) + content
    count = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(count)]) + count + content


def _der_int(value: int) -> bytes:
    return _der(0x02, value.to_bytes(value.bit_length() // 8 + 1, "big"))    # a leading zero keeps it positive


def spki_pem(algorithm: bytes, bits: bytes) -> str:
    body = base64.b64encode(_der(0x30, algorithm + _der(0x03, bits))).decode("ascii")
    lines = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN PUBLIC KEY-----\n{lines}\n-----END PUBLIC KEY-----\n"


# -- tokens ---------------------------------------------------------------------------------------------------

def segment(obj: Any, *, pad: bool = False) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8") if not isinstance(obj, bytes) else obj
    return base64.urlsafe_b64encode(raw).decode("ascii") if pad else b64url_encode(raw)


class Provider:
    """An identity provider with one signing key: its JWKS, and tokens it signs."""

    def __init__(self, issuer: str, audience: str | None, *, alg: str = "RS256", kid: str = "test-key-1",
                 seed: int = 1) -> None:
        self.issuer, self.audience, self.alg, self.kid = issuer, audience, alg, kid
        if alg == "RS256":
            self.rsa = rsa_key(seed)
        else:
            self.d = ec_key(seed)
            self.public = ec_public(self.d)

    def jwk(self) -> dict:
        if self.alg == "RS256":
            n, e, _ = self.rsa
            return {"kty": "RSA", "kid": self.kid, "use": "sig", "alg": "RS256",
                    "n": b64url_encode(n.to_bytes((n.bit_length() + 7) // 8, "big")),
                    "e": b64url_encode(e.to_bytes(3, "big"))}
        x, y = self.public
        return {"kty": "EC", "crv": "P-256", "kid": self.kid, "use": "sig", "alg": "ES256",
                "x": b64url_encode(x.to_bytes(32, "big")), "y": b64url_encode(y.to_bytes(32, "big"))}

    def jwks(self) -> dict:
        return {"keys": [self.jwk()]}

    def pem(self) -> str:
        """The public key as PEM (SubjectPublicKeyInfo), as AWS ALB publishes its keys."""
        if self.alg == "RS256":
            n, e, _ = self.rsa
            return spki_pem(_der(0x30, _der(0x06, _RSA) + b"\x05\x00"), b"\x00" + _der(0x30, _der_int(n) + _der_int(e)))
        x, y = self.public
        return spki_pem(_der(0x30, _der(0x06, _EC_PUBLIC) + _der(0x06, _P256)),
                        b"\x00\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big"))

    def sign(self, data: bytes) -> bytes:
        if self.alg == "RS256":
            return rsa_sign(self.rsa, data)
        r, s = ec_sign(self.d, data)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def claims(self, sub: str, *, ttl: int = 3600, now: float | None = None, **extra: Any) -> dict:
        now = time.time() if now is None else now
        out: dict[str, Any] = {"iss": self.issuer, "sub": sub, "iat": int(now), "exp": int(now) + ttl}
        if self.audience is not None:
            out["aud"] = self.audience
        return out | extra

    def token(self, sub: str, *, header: dict | None = None, claims: dict | None = None, pad: bool = False,
              **extra: Any) -> str:
        """A signed token for ``sub``; ``claims`` replaces the payload whole, ``header`` adds to the header."""
        head = {"alg": self.alg, "kid": self.kid, "typ": "JWT"} | (header or {})
        body = claims if claims is not None else self.claims(sub, **extra)
        signing_input = f"{segment(head, pad=pad)}.{segment(body, pad=pad)}"
        return f"{signing_input}.{segment(self.sign(signing_input.encode('ascii')), pad=pad)}"

    def alb_token(self, sub: str, *, signer: str, client: str, ttl: int = 120, **user: Any) -> str:
        """As an AWS ALB signs x-amzn-oidc-data: iss, exp, signer and client in the header, padded base64."""
        exp = int(time.time()) + ttl
        return self.token(sub, header={"signer": signer, "client": client, "iss": self.issuer, "exp": exp},
                          claims={"sub": sub, **user}, pad=True)
