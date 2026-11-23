"""What a secret looks like, and how evidence is shown without one.

A report never carries a secret. Every evidence snippet is passed through `mask` and then
trimmed. `mask` keeps at most a sixth (and never more than four characters) of anything that
looks like a credential and replaces the rest with `*`. The same patterns feed the secret rules
(`secretscan.py`), so what the scan finds is what the mask hides.

`secret_like` is the entropy test for a value assigned to a credential name: long enough, mixed
character classes, and random-looking (Shannon entropy in bits per character), and not a
placeholder, an environment variable's name or a template reference.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Credentials with a known format: (name, pattern). Each pattern is anchored on its format's own
# prefix, so ordinary text does not match it.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{50,255})\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,250}\b")),
    ("Stripe live key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,250}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,250}")),
    ("OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,250}\b")),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ ){0,3}PRIVATE KEY-----")),
    # Group 1 is the password, group 2 the host: the password is what is judged and masked. A `$` may be
    # in it; `${` starts a template reference, not a password.
    ("password in a URL",
     re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://[A-Za-z0-9._%-]{1,64}:((?:[^\s:/@'\"`<>{}$]|\$(?!\{)){6,128})"
                r"@([A-Za-z0-9.-]+)")),
)
# Hosts reserved for documentation (RFC 2606): a URL there is an example, whatever its password.
EXAMPLE_HOST = re.compile(r"(?i)(?:\A|\.)example(?:\.(?:com|org|net))?\Z|\.(?:test|invalid)\Z")
PLACEHOLDER = re.compile(r"(?i)example|sample|dummy|placeholder|changeme|change_me|redacted|your[_-]|xxxx|\*\*\*|"
                         r"\.\.\.|<[^>]*>|\$\{|\{\{|%\(|^(?:test|fake|none|null|secret|password|token)$")
# A credential name ends with what it holds: `api_token`, `DB_PASSWORD`, `client_secret`, `SECRET_KEY`,
# `DB_PASS`, `auth`; `token_url` and `password_hash` do not match, since what they hold is not the
# credential itself.
CREDENTIAL_NAME = (r"(?:[A-Za-z_][\w.-]*?)?(?:secret|passw(?:or)?d|passwd|pwd|pass|passphrase|token|api[_-]?key|apikey|"
                   r"access[_-]?key|private[_-]?key|auth[_-]?key|signing[_-]?key|client[_-]?secret|credential|"
                   r"(?:secret|encryption|master|hmac|session|crypto|crypt|cipher|aes|jwt|jwt[_-]?secret|app|"
                   r"django|flask|license|webhook|db|database)[_-]?key|auth)s?")
# `name = "value"`, `"name": "value"`, `name: str = "value"`, `name => 'value'`: group 3 is the value.
QUOTED_ASSIGNMENT = re.compile(
    r"""["']?\b(""" + CREDENTIAL_NAME + r""")\b["']?\s*(?::\s*[A-Za-z_][\w\[\], |.]*\s*)?(?:=|:|=>|:=)\s*"""
    r"""[rbuRBU]?(["'])([^"'\n]{8,256})\2""", re.I)
# `NAME=value` or `name: value` in configuration files: group 2 is the value.
UNQUOTED_ASSIGNMENT = re.compile(r"^\s*(?:export\s+|ENV\s+)?(" + CREDENTIAL_NAME +
                                 r")\s*[=:]\s*([^\s\"'#]{8,256})\s*(?:#.*)?$", re.I)
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:[_.-][a-z0-9]+)*\Z")
_HEX_TOKEN = re.compile(r"[0-9a-f]{16,}\Z")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{20,}")
MAX_EVIDENCE = 160


def entropy(value: str) -> float:
    """Shannon entropy of the characters of ``value``, in bits per character."""
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _classes(value: str) -> int:
    return sum((any(c.islower() for c in value), any(c.isupper() for c in value),
                any(c.isdigit() for c in value), any(not c.isalnum() for c in value)))


def placeholder(value: str) -> bool:
    """A value that says it is not real: an example, a template reference, a blank to fill in."""
    return bool(PLACEHOLDER.search(value))


def word_like(value: str) -> bool:
    """A lowercase name (`risk-assessor`, `user_profile_v2`, `zq-road-secret-6618`), not a random token:
    identifier-shaped, with few digits or with at least two words in it. A lowercase hex or base36 key
    that starts with a letter is not one."""
    if not _IDENTIFIER.match(value) or _HEX_TOKEN.match(value):
        return False
    words = [part for part in re.split(r"[_.-]", value) if len(part) >= 3 and part.isalpha()]
    return sum(c.isdigit() for c in value) <= max(2, len(value) // 10) or len(words) >= 2


def secret_like(value: str) -> bool:
    """Whether a value assigned to a credential name looks like a real secret, not a word. A short one
    (8 to 11 characters, a password) must mix at least three kinds of character."""
    if len(value) < 8 or placeholder(value) or any(c.isspace() for c in value):
        return False
    if _ENV_NAME.match(value) or word_like(value) or value.startswith(("http://", "https://", "/")):
        return False
    classes, bits = _classes(value), entropy(value)
    if len(value) < 12:
        return classes >= 3 and bits >= 2.8
    return (classes >= 3 and bits >= 3.0) or (classes >= 2 and bits >= 3.5 and len(value) >= 20)


def known_secrets(text: str) -> list[tuple[str, int, int]]:
    """Every credential with a known format in ``text``: (kind, start, end), placeholders left out.
    For a pattern with groups, group 1 is the secret itself and the only part judged and masked: a
    password `example123` is a placeholder; `db.example-corp.io` in the host does not make one."""
    out = []
    for name, pattern in PATTERNS:
        for m in pattern.finditer(text):
            group = 1 if pattern.groups else 0
            host = m.group(2) if pattern.groups >= 2 else ""
            if not placeholder(m.group(group)) and not EXAMPLE_HOST.search(host):
                out.append((name, m.start(group), m.end(group)))
    return out


def assigned_secrets(line: str, *, config: bool = False) -> list[tuple[int, int]]:
    """Spans of the values on ``line`` assigned to a credential name that look like real secrets.
    ``config``: also the unquoted `NAME=value` form of configuration files."""
    spans = [m.span(3) for m in QUOTED_ASSIGNMENT.finditer(line) if secret_like(m.group(3))]
    m = UNQUOTED_ASSIGNMENT.match(line) if config else None
    if m and secret_like(m.group(2)):
        spans.append(m.span(2))
    return spans


def _random_token(value: str) -> bool:
    """A long token with letters and digits that looks random; `SimpleHTTPRequestHandler` is a name."""
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value) and secret_like(value)


def _hide(value: str) -> str:
    """At most a sixth of the value and never more than four characters stay readable (`ghp_`,
    `AKI`), enough to tell kinds apart and too little to narrow a guess; the rest is `*`."""
    keep = min(4, len(value) // 6)
    return value[:keep] + "*" * min(max(len(value) - keep, 4), 12)


def _assigned_spans(text: str) -> list[tuple[int, int]]:
    out, start = [], 0
    for line in text.splitlines(keepends=True):
        out += [(start + s, start + e) for s, e in assigned_secrets(line, config=True)]
        start += len(line)
    return out


def mask(text: str) -> str:
    """``text`` with every credential (known format, or assigned to a credential name) and every long
    random-looking token masked."""
    spans = [(s, e) for _, s, e in known_secrets(text)] + _assigned_spans(text)
    spans += [(m.start(), m.end()) for m in _LONG_TOKEN.finditer(text) if _random_token(m.group(0))]
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, last = [], 0
    for start, end in merged:
        out += [text[last:start], _hide(text[start:end])]
        last = end
    out.append(text[last:])
    return "".join(out)


def trim(text: str, limit: int = MAX_EVIDENCE) -> str:
    """One line of evidence: whitespace collapsed, cut to ``limit`` characters."""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "\u2026"


def evidence(text: str) -> str:
    """A snippet fit for a report: masked first, then trimmed, so a cut never reveals a secret's tail."""
    return trim(mask(text))
