"""The infrastructure checks' settings, read strictly (FR-ITO2): a setting that names no usable target is said, never
taken for "nothing to measure" or for a failure of the service.

- ``url`` (app): each an http or https address with a host;
- ``targets`` (tls): each an http or https address with a host (an http one is read and skipped: it has no
  certificate);
- ``hosts`` (dns): each ``host``, ``host:port`` or an address with a host;
- ``expires`` (integration): each ``NAME=YYYY-MM-DD``.

``problems`` lists what is wrong in a check's settings. kernel/checks/store.py refuses to enable a check with any,
and each check says "not measured" with them when an older setting is wrong, so a bad setting never opens an
incident with a remedy for something else.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse
from typing import Any

from kernel.checks import infra_targets as tg

KINDS = ("app", "tls", "dns", "integration")


def host_entry(value: str) -> tuple[str, int] | None:
    """The host and port of a ``hosts`` entry: an address, ``host:port`` or a bare host (port 443)."""
    if "://" in value:
        return tg.host_port(value)
    name, _, port = value.rpartition(":") if ":" in value else (value, "", "443")
    if not name or not port.isdigit() or not 0 < int(port) < 65536 or any(c in name for c in "/ @"):
        return None
    return name, int(port)


def _address(value: str) -> bool:
    parts = urllib.parse.urlsplit(value)
    return parts.scheme in ("http", "https") and tg.host_port(value) is not None


def _expiry(value: str) -> bool:
    name, sep, day = value.partition("=")
    if not (sep and name.strip() and day.strip()):
        return False
    try:
        dt.date.fromisoformat(day.strip())
    except ValueError:
        return False
    return True


RULES: dict[str, tuple[Any, str]] = {
    "url": (_address, "is not an http or https address with a host"),
    "targets": (_address, "is not an http or https address with a host"),
    "hosts": (lambda v: host_entry(v) is not None, "is not a host, host:port or an address with a host"),
    "expires": (_expiry, "is not NAME=YYYY-MM-DD (a credential's name and the date it expires)"),
}


def problems(kind: str, config: dict[str, Any]) -> list[str]:
    """What is wrong in an infrastructure check's settings, each said once; none for another kind of check."""
    if kind not in KINDS:
        return []
    out = []
    for key, (ok, said) in RULES.items():
        out += [f"{key} {value!r} {said}" for value in tg.as_list(config.get(key)) if not ok(value)]
    return out


def unusable(kind: str, config: dict[str, Any]) -> str | None:
    """The "not measured" reason when a setting is wrong, or None."""
    bad = problems(kind, config)
    if not bad:
        return None
    return ("the check's settings name no usable target: " + "; ".join(bad[:5]) + " (change them on Health, then "
            "run the check again)")
