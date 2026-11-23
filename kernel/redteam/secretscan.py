"""The secret rules: committed secret files, credentials with a known format, and high-entropy values
assigned to credential names.

- RT-SECRET-FILE: a file that holds secrets by its nature: `.env` (not `.env.example` and the like),
  SSH private keys, key stores, `.netrc`, `.git-credentials`, `.htpasswd`, `.pgpass`, a `.pem` or
  `.key` holding a private key, registry credentials in `.npmrc` or `.pypirc`, a cloud service
  account key, Terraform state. Its content is not scanned again: the fix is the same for all of it.
- RT-SECRET-PATTERN: a credential with a known format anywhere in a text file (`masking.PATTERNS`).
- RT-SECRET-ENTROPY: a quoted value assigned to a credential name (`api_token = "..."`,
  `"password": "..."`) that looks random (`masking.secret_like`). Configuration files
  (`.env`, `.ini`, `.yaml`, `.toml`, `Dockerfile`) are also read in the unquoted form `NAME=value`.

**Canaries.** A line whose comment holds `redteam: canary` right after its opener (`#`, `//`,
`/*`, `<!--`, `--` or `;`) is a planted secret: tests and exfiltration checks need real-looking
values. The secret rules do not report that line; the scan lists it as a canary instead, with its
location and its masked value, in the report and in the SARIF. A marker silences only its own
line, and only the secret rules. Text that merely mentions the marker (this paragraph) is not
one. A secret file that carries a marker is listed as a canary instead of reported, and its lines
are still read: a real credential on an unmarked line of it is a finding.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePosixPath

from kernel.redteam.masking import assigned_secrets, evidence, known_secrets
from kernel.redteam.report import IDLE_MARKER, IGNORED

Hit = tuple[str, int]
CanaryHit = tuple[int, str, str]  # (line, kind, masked evidence)

CANARY = re.compile(r"(?i)(?:#|//|/\*|<!--|--|;)\s*redteam:\s*canary\b")
IGNORED_MARKER = f"{IGNORED}, reported as a finding"
_TEST_FOLDERS = frozenset({"tests", "test", "testing", "fixtures", "testdata", "spec", "specs", "__tests__"})
_KEY_BODY = re.compile(r"[A-Za-z0-9+/=]{40,}")
_FIREBASE = re.compile(r"(?i)firebaseapp\.com|\bauthDomain\b|firebase(?:Config|\.initializeApp)")
_SAFE_ENV = frozenset({"example", "sample", "template", "dist", "defaults", "default", "schema"})
_KEY_FILES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"})
_CREDENTIAL_FILES = frozenset({".netrc", "_netrc", ".git-credentials", ".htpasswd", ".pgpass"})
_KEY_STORES = (".p12", ".pfx", ".jks", ".keystore", ".kdbx")
_CONFIG_SUFFIXES = (".env", ".ini", ".cfg", ".conf", ".properties", ".yaml", ".yml", ".toml")


def _environment_file(name: str) -> bool:
    """`.env`, `.env.local`, `prod.env`; not `.env.example`, `sample.env` and the like."""
    if name == ".env":
        return True
    if name.startswith(".env."):
        return name.split(".")[-1] not in _SAFE_ENV
    return name.endswith(".env") and not set(name.split(".")) & _SAFE_ENV


# (what kind of secret file, whether a file is one: by its lower-case path parts and its first bytes)
_SECRET_FILES: tuple[tuple[str, Callable[[tuple[str, ...], str], bool]], ...] = (
    ("environment file", lambda parts, head: _environment_file(parts[-1])),
    ("cloud credentials file", lambda parts, head: parts[-2:] == (".aws", "credentials")),
    ("registry credentials", lambda parts, head: parts[-2:] == (".docker", "config.json")
     and bool(re.search(r'"auth"\s*:\s*"[^"]{8,}', head))),
    ("SSH private key", lambda parts, head: parts[-1] in _KEY_FILES),
    ("key store", lambda parts, head: parts[-1].endswith(_KEY_STORES)),
    ("credentials file", lambda parts, head: parts[-1] in _CREDENTIAL_FILES),
    ("private key file", lambda parts, head: parts[-1].endswith((".pem", ".key")) and "PRIVATE KEY" in head),
    ("registry credentials", lambda parts, head: parts[-1] in (".npmrc", ".pypirc")
     and bool(re.search(r"(?i)_authtoken|password\s*[=:]", head))),
    ("cloud service account key", lambda parts, head: parts[-1].endswith(".json") and '"private_key"' in head
     and "service_account" in head),
    ("Terraform state", lambda parts, head: parts[-1].endswith(".tfstate")),
)


def secret_file(rel: str, head: str) -> str | None:
    """What kind of secret file ``rel`` is (its first bytes in ``head``), or None."""
    parts = PurePosixPath(rel.lower()).parts or ("",)
    return next((kind for kind, test in _SECRET_FILES if test(parts, head)), None)


def _real_key(kind: str, line: str, end: int, after: str) -> bool:
    """A private key header with a key after it (base64 on the same line or the next), not the header
    alone in code or docs that look for keys."""
    return kind != "private key" or bool(_KEY_BODY.search(line[end:] + "\n" + after))


def _line_secrets(line: str, after: str, config: bool, public: bool) -> list[tuple[str, str]]:
    """(rule id, kind) of each secret on a line; a value with a known format is reported once. ``after``
    is the next line; ``public`` says the file is a web app's public configuration (Firebase), whose
    browser API key is public by design."""
    everything = known_secrets(line)
    known = [(k, s, e) for k, s, e in everything if _real_key(k, line, e, after)
             and not (public and k == "Google API key")]
    found = [("RT-SECRET-PATTERN", kind) for kind, _, _ in known]
    found += [("RT-SECRET-ENTROPY", "high-entropy value") for s, e in assigned_secrets(line, config=config)
              if not any(ks < e and s < ke for _, ks, ke in everything)]
    return found


def test_path(rel: str) -> bool:
    """A file of a test suite or its fixtures: the only place a canary marker silences a secret."""
    p = PurePosixPath(rel.lower())
    return bool(set(p.parts[:-1]) & _TEST_FOLDERS) or p.name.startswith("test_") or p.name == "conftest.py" or \
        p.stem.endswith(("_test", ".test", ".spec")) or p.name.endswith(("_test.py", ".test.js", ".spec.js",
                                                                         ".test.ts", ".spec.ts"))


def check_secrets(rel: str, text: str) -> tuple[list[Hit], list[CanaryHit]]:
    """The secret findings in one text file, and the canary markers it carries. Outside a test suite a
    marker silences nothing: the secret is reported, and the marker listed as ignored."""
    name = PurePosixPath(rel).name
    config = name.lower().endswith(_CONFIG_SUFFIXES) or name.startswith(("Dockerfile", ".env")) or \
        PurePosixPath(rel.lower()).parts[-2:-1] == (".aws",)
    public = bool(_FIREBASE.search(text))
    honoured = test_path(rel)
    hits: list[Hit] = []
    canaries: list[CanaryHit] = []
    lines = text.splitlines()
    for n, line in enumerate(lines, 1):
        found = _line_secrets(line, lines[n] if n < len(lines) else "", config, public)
        if CANARY.search(line):
            kinds = [kind if honoured else f"{kind} ({IGNORED_MARKER})" for _, kind in found]
            canaries += [(n, kind, evidence(line)) for kind in kinds] or [(n, IDLE_MARKER, "")]
            if honoured:
                continue
        hits += [(rid, n) for rid, _ in found]
    return sorted(set(hits), key=lambda h: (h[1], h[0])), canaries


def check_secret_file(rel: str, text: str) -> tuple[list[Hit], list[CanaryHit]]:
    """RT-SECRET-FILE for a secret file, or a canary when a test suite's file carries the marker."""
    kind = secret_file(rel, text[:4096])
    if kind is None:
        return [], []
    marker = CANARY.search(text)
    if marker and test_path(rel):
        return [], [(text.count("\n", 0, marker.start()) + 1, f"secret file ({kind})", "")]
    return [("RT-SECRET-FILE", 1)], []


def check_file(rel: str, text: str | None) -> tuple[list[Hit], list[CanaryHit]]:
    """The secret findings of one file and the canaries it carries. A binary file (``text`` None) is
    judged by its name. A secret file is one finding; when a marker makes it a canary, its lines are
    still read, so a real credential beside the planted ones is reported."""
    hits, canaries = check_secret_file(rel, text or "")
    if text is None or hits:
        return hits, canaries
    found, marked = check_secrets(rel, text)
    planted = {line for line, _, _ in canaries}
    return found, canaries + [c for c in marked if c[0] not in planted or c[1] != IDLE_MARKER]
