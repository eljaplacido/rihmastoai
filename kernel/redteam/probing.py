"""What every dynamic probe shares: the routes of the project's fixed interface, the run, and an
honest tally of what each layer measured.

Routes come from the spec's interface (`kernel/spec.py` `interface_of`): a method and a path whose
`{parameters}` the probes fill. A row whose path is not plain printable ASCII is left out, so the
spec can never smuggle a header or a second request into a probe.

A **tally** turns what came back into coverage, never assuming a pass:
- `measured`: every request the layer planned was answered and judged;
- `partial`: some were not (no answer, a 429 before the probe could judge, the budget or the scope
  stopped the layer, a route skipped), and the reason says which;
- `not measured`: nothing was judged, with the reason; a layer with nothing to probe (no write
  route) is not applicable as well.
"""

from __future__ import annotations

import re
import secrets
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from kernel.redteam.client import Answer, Client
from kernel.redteam.report import Coverage, Finding
from kernel.redteam.rules import DYNAMIC_RULES

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
WRITES = ("POST", "PUT", "PATCH")
MAX_ROUTES = 40
# Stands in for a path parameter in a probe that is not about that parameter: it names no real record.
PROBE_VALUE = "rihmasto-probe"
# Stands in for a path parameter where the probe wants the page itself (security headers, CORS).
PAGE_VALUE = "1"
JSON = {"Content-Type": "application/json"}
NO_INTERFACE = "the project's spec declares no interface"
_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PATH = re.compile(r"/[A-Za-z0-9_.~{}/:@!$&'()*+,;=%-]*")


@dataclass(frozen=True)
class Route:
    """One row of the interface: a method and a path pattern such as `/items/{id}`."""

    method: str
    path: str

    @property
    def params(self) -> list[str]:
        return _PARAM.findall(self.path)

    def fill(self, value: str, *, encoded: bool = False) -> str:
        """The path with every parameter set to ``value`` (percent-encoded here unless ``encoded``)."""
        text = value if encoded else urllib.parse.quote(value, safe="")
        return _PARAM.sub(lambda _m: text, self.path)

    def fill_last(self, value: str, *, encoded: bool = False) -> str:
        """The path with its last parameter set to ``value`` and any other to `PAGE_VALUE`."""
        text = value if encoded else urllib.parse.quote(value, safe="")
        names = self.params
        out = self.path
        for name in names[:-1]:
            out = out.replace("{" + name + "}", PAGE_VALUE, 1)
        return out.replace("{" + names[-1] + "}", text, 1) if names else out


# The root of the deployment as a route, for probes of paths no interface names.
ROOT = Route("GET", "/{path}")


def routes_of(interface: Iterable[Any]) -> list[Route]:
    """The interface's routes that a probe may use, in order, without repeats, at most `MAX_ROUTES`."""
    out: list[Route] = []
    for row in interface or []:
        if not isinstance(row, Mapping):
            continue
        route = Route(str(row.get("method", "")).upper(), str(row.get("path", "")))
        if route.method in METHODS and _PATH.fullmatch(route.path) and route not in out:
            out.append(route)
    return out[:MAX_ROUTES]


@dataclass
class Tally:
    """What one layer sent and could judge."""

    layer: str
    answered: int = 0
    unanswered: int = 0
    limited: int = 0
    gaps: list[str] = field(default_factory=list)
    stopped: str = ""
    applicable: bool = True

    def count(self, answer: Answer, *, judged: bool | None = None) -> Answer:
        """Count an answer. ``judged`` overrides the default: an answer, but not a 429, is judged."""
        if judged is None:
            judged = answer.answered and answer.status != 429
            if answer.status == 429:
                self.limited += 1
                return answer
        if judged:
            self.answered += 1
        else:
            self.unanswered += 1
        return answer

    def gap(self, reason: str) -> None:
        self.gaps.append(reason)

    def _shortfalls(self) -> list[str]:
        out = [self.stopped] if self.stopped else []
        if self.unanswered:
            out.append(f"{self.unanswered} request(s) got no answer")
        if self.limited:
            out.append(f"{self.limited} request(s) were refused with 429 before they could be judged")
        return out + self.gaps

    def coverage(self, reason: str) -> Coverage:
        if not self.applicable:
            return Coverage(self.layer, "not measured", reason, 0, applicable=False)
        short = self._shortfalls()
        if not self.answered:
            why = "; ".join(short) or "nothing was sent"
            return Coverage(self.layer, "not measured", f"nothing judged: {why}", 0, short)
        if short:
            text = "; ".join(x for x in [reason, *short] if x)
            return Coverage(self.layer, "partial", text, self.answered, short)
        return Coverage(self.layer, "measured", reason, self.answered)


@dataclass
class Run:
    """One dynamic run: the client, the interface's routes, and the findings so far."""

    client: Client
    routes: list[Route]
    findings: list[Finding] = field(default_factory=list)
    keys: set[tuple[str, str]] = field(default_factory=set)
    nonce: str = field(default_factory=lambda: secrets.token_hex(4))
    halted: str = ""

    @property
    def reads(self) -> list[Route]:
        return [r for r in self.routes if r.method == "GET"]

    @property
    def writes(self) -> list[Route]:
        return [r for r in self.routes if r.method in WRITES]

    def found(self, rule_id: str, route: str, evidence: str, *, once: bool = False) -> None:
        """Record a finding, once per rule and route (or once per run with ``once``)."""
        key = (rule_id, "" if once else route)
        if key not in self.keys:
            self.keys.add(key)
            self.findings.append(Finding.of(DYNAMIC_RULES[rule_id], route, 1, evidence))
