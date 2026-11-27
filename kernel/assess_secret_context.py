"""A secret's context read more strictly (FR-ASP2; kernel/assess_precise.py reads it).

An independent check of FR-ASP1 found a real credential hidden from "worth acting on": anything inside a URL path
was "likely not a secret", even a known credential format or a URL that is itself the credential (a chat webhook,
a bot's URL); a value beside a URL on the same line was never looked at; words like "dummy" made a value fake
outside the tests, and "latest" counted as "test"; and a fixture mark kept for a file covered any secret added to
that file later. By rule, with no model:

- **A URL can be the credential.** A webhook or bot URL of a known service (`credential_url`), or a known
  credential format anywhere in the URL (`known_in_url`), is possibly real, whatever its path looks like.
- **A value beside a URL is judged on its own** (`loose_values`): a random-looking quoted or assigned value left
  on the line once the URLs are taken out keeps the line from being "only a URL path".
- **Fake by its words, only in a test suite's files** (`fake_value`): a word that says so (fixture, example,
  dummy, test, fake, sample, mock, ...) must stand as a word of its own (`latest` is no `test`), and a known
  credential format or a provider's test-mode key (`sk_test_`) is never fake. Outside the tests, words say
  nothing: the red team already leaves placeholders out.
- **A mark covers what was marked** (`line_mark`): a fixture or real mark keeps a fingerprint of each secret line
  of the file it was given for; a value added later is judged by the rule again, and its row says the mark does
  not cover it.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from kernel.redteam.masking import known_secrets, secret_like

# URLs that carry the credential in their path: (what it is, pattern).
CREDENTIAL_URLS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a Slack webhook", re.compile(r"(?i)\bhooks\.slack\.com/(?:services|workflows|triggers)/[\w/-]{8,}")),
    ("a Discord webhook", re.compile(r"(?i)\b(?:discord|discordapp)\.com/api/(?:v\d+/)?webhooks/\d+/[\w-]{8,}")),
    ("a Telegram bot's URL", re.compile(r"(?i)\bapi\.telegram\.org/(?:file/)?bot\d{3,}:[\w-]{20,}")),
    ("a Microsoft Teams webhook", re.compile(r"(?i)(?:\.webhook\.office\.com|outlook\.office\.com)/webhook[\w]*/")),
    ("a Zapier webhook", re.compile(r"(?i)\bhooks\.zapier\.com/hooks/catch/\d+/\w+")),
    ("a Mattermost or Rocket.Chat incoming hook", re.compile(r"(?i)/hooks/[a-z0-9]{20,}(?:/|$)")),
)
IN_LINKS = ("JSON Web Token", "password in a URL")    # a link's own token, or a password the query rule judges
TEST_MODE_KEY = re.compile(r"\b[rsp]k_test_[A-Za-z0-9]{16,}")
FAKE_WORDS = frozenset(("fixture", "fixtures", "example", "dummy", "test", "fake", "sample", "placeholder", "changeme",
                        "mock", "redacted", "lorem", "stub", "notasecret"))
_SEGMENTS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_QUOTED = re.compile(r"""(["'`])([^"'`\s]{12,})\1""")
_ASSIGNED = re.compile(r"""[:=]\s*([^\s"'`,;)]{12,})""")


def credential_url(url: str) -> str | None:
    """What a URL is when it is itself a credential (a webhook or a bot's URL), or None."""
    return next((what for what, rx in CREDENTIAL_URLS if rx.search(url)), None)


def known_in_url(url: str) -> str | None:
    """The kind of a known credential format inside a URL (a GitHub token in a path), or None. A signed token in a
    link's path (a JSON Web Token) is how attachment and share links are made: the URL-path judgement keeps it."""
    found = [k for k in known_secrets(url) if k[0] not in IN_LINKS]
    if not found and TEST_MODE_KEY.search(url):
        return "payment provider's test-mode key"
    return found[0][0] if found else None


def url_reason(urls: list[str]) -> str | None:
    """Why a secret on a line with ``urls`` is to be treated as real because of a URL, or None."""
    for u in urls:
        what = credential_url(u)
        if what:
            return f"the URL is {what}: its path is the credential, treat it as real"
        kind = known_in_url(u)
        if kind:
            return f"a {kind} sits inside the URL: a known credential format, treat it as real"
    return None


def loose_values(rest: str) -> list[str]:
    """Random-looking values left on a line once its URLs are taken out (a key beside a link)."""
    found = [m.group(2) for m in _QUOTED.finditer(rest)] + [m.group(1) for m in _ASSIGNED.finditer(rest)]
    return [v for v in found if secret_like(v)]


def words(value: str) -> list[str]:
    """A value's own words: split at anything not a letter or digit, and at a change of case."""
    return [w.lower() for part in re.split(r"[^A-Za-z0-9]+", value) for w in _SEGMENTS.findall(part)]


def jwt_says(value: str) -> str | None:
    """The fake word a JSON Web Token's own payload carries (a token a test suite made for itself: its subject or
    tenant says "fixture"), or None. Only the word is named, never the token or its claims."""
    import base64
    import json

    parts = value.split(".")
    if len(parts) != 3 or not parts[0].startswith("eyJ"):
        return None
    try:
        raw = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    for claim in claims.values():
        if isinstance(claim, str):
            hit = next((w for w in words(claim) if w in FAKE_WORDS), None)
            if hit:
                return hit
    return None


def fake_value(value: str, *, in_tests: bool = True) -> str | None:
    """Why a value in a test suite's file is obviously not a real secret, or None. Outside the tests, None."""
    if in_tests:
        made = jwt_says(value)
        if made:
            return f"a token made for a test: its own payload says \"{made}\""
    if not in_tests or known_secrets(value) or TEST_MODE_KEY.search(value):
        return None
    plain = re.sub(r"[-_.:/ ]", "", value)
    if len(plain) >= 6 and len(set(plain.lower())) <= 2:
        return f"one character over and over ({value[:2]}...)"
    said = words(value)
    joined = "".join(said)
    hit = next((w for w in said if w in FAKE_WORDS or re.fullmatch(r"x{4,}", w)), None)
    if hit is None and "notasecret" in joined:
        hit = "not a secret"
    return f"it says \"{hit}\"" if hit else None


def line_mark(pid: str, line: str) -> str:
    """A fingerprint of a secret's line, for the mark a person gives its file: never the value itself."""
    return hashlib.sha256(f"{pid}\n{line.strip()}".encode("utf-8", errors="replace")).hexdigest()[:20]


def covers(mark: dict[str, Any], check: dict[str, Any]) -> bool:
    """Whether a person's mark on a file covers this finding: the line was among those marked (a mark kept before
    fingerprints were kept covers the file, as it did)."""
    lines = mark.get("lines")
    return lines is None or check.get("line_mark") in set(lines)


def not_covered(mark: dict[str, Any]) -> str:
    """What a finding's row says when its file was marked but its value was not."""
    who = f"{mark.get('person')} ({mark.get('persona')})"
    said = "fixture" if mark.get("mark") == "fixture" else "real secret"
    return (f"; {who} marked other values in this file a {said}"
            f" on {str(mark.get('at', ''))[:10]}, not this one: the mark covers only the values marked")


__all__ = ["CREDENTIAL_URLS", "FAKE_WORDS", "covers", "credential_url", "fake_value", "known_in_url", "line_mark",
           "loose_values", "not_covered", "url_reason", "words"]
