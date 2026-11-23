"""The encodings a leaked canary may come out in, and how each is undone for the canary search.

`decodings(text)` yields (form, decoded text) for every encoding the search knows:

- base64 (standard, URL-safe, unpadded, cut at either end: tokens are padded, never cut, and tried
  at every offset), also when its pieces are separated by white space, dots, pipes, quote markers or
  Markdown; base32 in either case; base85 and Ascii85; uuencode;
- hex runs, and numbers written one per character: decimal codes (`75 101 115`), C bytes (`0x4b`,
  `\\x4b`), octal escapes (`\\113`), binary octets (`01001011`), and `\\U0000004b` / `\\u{4b}` escapes;
- ROT47 of the text.

`letter_forms(flat)` yields what a text folded to letters and digits may hide: every Caesar shift
(ROT13 among them), Atbash, and letters interleaved with a filler (every second or third letter).
"""

from __future__ import annotations

import base64
import binascii
import re
from collections import Counter
from collections.abc import Iterable

_B64 = re.compile(r"[A-Za-z0-9+/_-]{12,}={0,2}")
_B32 = re.compile(r"[A-Za-z2-7]{16,}={0,6}")
_B85 = re.compile(r"[0-9A-Za-z!#$%&()*+\-;<=>?@^_`{|}~]{20,}")
_A85 = re.compile(r"<~(.+?)~>", re.S)
_HEX_RUN = re.compile(r"[0-9a-fA-F]{16,}")
_NOT_B64 = re.compile(r"[^A-Za-z0-9+/=_-]+")
_DECIMAL = re.compile(r"(?<![\w.])(\d{2,3})(?![\w.])")
_C_BYTE = re.compile(r"(?:0x|\\x)([0-9a-fA-F]{2})")
_OCTAL = re.compile(r"\\([0-7]{3})")
_BINARY = re.compile(r"(?<![01])([01]{8})(?![01])")
_UNICODE = re.compile(r"\\U([0-9a-fA-F]{8})|\\u\{([0-9a-fA-F]{1,6})\}")
_UU_LINE = re.compile(r"^[!-`][ -`]{4,61}$", re.M)
MIN_CODES = 8


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="ignore")


def _b64(token: str) -> Iterable[str]:
    body = token.rstrip("=").replace("-", "+").replace("_", "/")
    for start in range(4):
        part = body[start:]
        part += "=" * (-len(part) % 4)
        try:
            yield _text(base64.b64decode(part, validate=False))
        except (binascii.Error, ValueError):
            continue


def _b32(token: str) -> Iterable[str]:
    body = token.rstrip("=").upper()
    for start in range(8):
        part = body[start:]
        part += "=" * (-len(part) % 8)
        try:
            yield _text(base64.b32decode(part))
        except (binascii.Error, ValueError):
            continue


def _b85(token: str) -> Iterable[str]:
    for decode in (base64.b85decode, base64.a85decode):
        try:
            yield _text(decode(token))
        except (binascii.Error, ValueError):
            continue


def _hex(run: str) -> Iterable[str]:
    for start in (0, 1):
        body = run[start:]
        body = body[:len(body) - len(body) % 2]
        try:
            yield _text(bytes.fromhex(body))
        except ValueError:
            continue


def _codes(numbers: list[int]) -> str:
    return "".join(chr(n) for n in numbers if 32 <= n < 0x110000 and n != 0x7f)


def _numeric(text: str) -> Iterable[tuple[str, str]]:
    """Characters written as numbers: decimal codes, C bytes, octal escapes, binary octets, long escapes."""
    decimal = [int(m) for m in _DECIMAL.findall(text) if 32 <= int(m) < 127]
    if len(decimal) >= MIN_CODES:
        yield "codes", _codes(decimal)
    for form, pattern, base in (("codes", _C_BYTE, 16), ("codes", _OCTAL, 8), ("codes", _BINARY, 2)):
        found = [int(m, base) for m in pattern.findall(text)]
        if len(found) >= MIN_CODES:
            yield form, _text(bytes(n for n in found if n < 256))
    if _UNICODE.search(text):
        yield "escaped", _UNICODE.sub(lambda m: chr(min(int(m.group(1) or m.group(2), 16), 0x10FFFF)), text)


def _uu(text: str) -> Iterable[str]:
    lines = _UU_LINE.findall(text)
    out = []
    for line in lines:
        try:
            out.append(binascii.a2b_uu(line))
        except (binascii.Error, ValueError):
            continue
    if out:
        yield _text(b"".join(out))


def rot47(text: str) -> str:
    return "".join(chr(33 + (ord(c) - 33 + 47) % 94) if 33 <= ord(c) <= 126 else c for c in text)


def decodings(text: str) -> Iterable[tuple[str, str]]:
    """(form, decoded text) for every encoding of the text the search knows (see the module's docstring)."""
    joined = _NOT_B64.sub("", text)
    for variant in dict.fromkeys((text, re.sub(r"\s+", "", text), joined)):
        for token in _B64.findall(variant):
            yield from (("base64", out) for out in _b64(token))
        for token in _B32.findall(variant):
            yield from (("base32", out) for out in _b32(token))
    for token in _B85.findall(text):
        yield from (("base85", out) for out in _b85(token))
    for body in _A85.findall(text):
        yield from (("base85", out) for out in _b85(body.strip()))
    for run in _HEX_RUN.findall(re.sub(r"[^0-9a-fA-F]+", "", text)):
        yield from (("hex", out) for out in _hex(run))
    yield from _numeric(text)
    yield from (("uuencode", out) for out in _uu(text))
    yield "rot47", rot47(text)


def _shift(flat: str, n: int) -> str:
    return "".join(chr((ord(c) - 97 + n) % 26 + 97) if "a" <= c <= "z" else c for c in flat)


def letter_forms(flat: str) -> Iterable[tuple[str, str]]:
    """(form, folded text) for what letter games hide in an already folded text (`a-z0-9` only)."""
    yield "rot13", _shift(flat, 13)
    for n in range(1, 26):
        if n != 13:
            yield "caesar", _shift(flat, n)
    yield "atbash", "".join(chr(219 - ord(c)) if "a" <= c <= "z" else c for c in flat)
    for step in (2, 3):
        for start in range(step):
            yield "interleaved", flat[start::step]
    for filler, _ in Counter(flat).most_common(2):
        yield "interleaved", flat.replace(filler, "")
