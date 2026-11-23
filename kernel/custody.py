"""The holdout custody's one redaction module (docs/knowledge-graph.md, section 3; FR-KG1-AC-2).

What describes a holdout scenario stays in the holdout custody (FR-O3): the scenarios, what they
expected and observed, and the reasons people give when they rule on them. Every surface that serves
the factory's records outside the custody leaves that out through this module, and only this one:

- ``custody_safe``: a release's reason with what a holdout scenario expected left out. The kernel's
  own words for a failed holdout ("holdout R-1-AC-2 failed at step 2: ...") quote the scenario, so
  the criterion and the step stay and the rest is held out.
- ``held_strings``: the strings of every scenario in the custody that a builder could not already
  see in its project's spec or contract. They are read only to recognise them in output.
- ``redact``: any JSON value with those strings, and the failed-holdout detail, replaced.
- ``ledger_record``: one ledger record as served, without the fields that carry a scenario or what it
  met.

The MCP server (mcp/server.py) and delivery (kernel/deliver.py, kernel/status.py, kernel/recipes.py)
use it. The knowledge graph (kernel/graph.py) never reads the custody: it reads a release's holdout
verdicts in a closed shape, and the release's reason through ``custody_safe``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

HELD = "[held out]"
MIN_HELD = 4                     # shorter strings ("GET", "id", "ok") are too common to be a scenario's
SCENARIO_META = ("criterion", "kind", "author_role")
# Ledger fields that carry a holdout scenario or what it met, never served.
HOLDOUT_FIELDS = frozenset({"failing", "expected", "observed", "steps", "scenario", "scenarios", "trail",
                            "reauthored_because"})
# The kernel's reason for a failed holdout quotes what the scenario expected (kernel/deliver.py).
HELD_DETAIL = re.compile(r"(holdout \S+ failed at step \S+?):[^\n]*")
HOLDOUT_STEP_REASON = "a holdout failed; its details stay in the holdout custody"


def custody_safe(reason: Any) -> Any:
    """A release's reason with what a holdout scenario expected left out: the criterion and the step
    stay. Anything that is not text comes back as it is."""
    return HELD_DETAIL.sub(lambda m: f"{m.group(1)}: {HELD}", reason) if isinstance(reason, str) else reason


def scenario_strings(value: Any, out: set[str]) -> set[str]:
    """Every string value in a scenario: what it sends and what it expects."""
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            scenario_strings(v, out)
    elif isinstance(value, list):
        for v in value:
            scenario_strings(v, out)
    return out


def _visible(projects: Path, pid: str, inside: Callable[[Path], bool]) -> str:
    """What a builder of the project can already see: its spec and its contract, as text."""
    visible = ""
    for name in ("spec.json", "contract.json"):
        path = Path(projects, pid, name)
        if path.is_file() and inside(path):
            visible += path.read_text(encoding="utf-8", errors="replace")
    return visible


def _scenario_values(path: Path) -> set[str]:
    """The strings of one scenario file, its metadata (criterion, kind, author) left out."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if isinstance(doc, dict):
        doc = doc["steps"] if "steps" in doc else {k: v for k, v in doc.items() if k not in SCENARIO_META}
    return scenario_strings(doc, set())


def held_strings(holdouts: Path, projects: Path, *, inside: Callable[[Path], bool] | None = None) -> list[str]:
    """The strings of every scenario in the holdout custody (``holdouts``, one folder per project)
    that a builder could not already see in its project's spec or contract, longest first. They are
    used only to redact output. ``inside`` says whether a project file may be read at all."""
    root = Path(holdouts)
    if not root.is_dir():
        return []
    allowed = inside or (lambda path: True)
    held: set[str] = set()
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        visible = _visible(projects, folder.name, allowed)
        for path in sorted(folder.glob("*.json")):
            for s in _scenario_values(path):
                s = s.strip()
                if len(s) >= MIN_HELD and s not in visible:
                    held.add(s)
    return sorted(held, key=lambda s: (-len(s), s))


def redact(value: Any, held: list[str], *, keep: tuple[type, ...] = ()) -> Any:
    """Every string value with holdout content replaced: the failed-holdout detail, and each held
    string. Keys are the kernel's field names and stay. A value of a type in ``keep`` comes back as it
    is (the MCP server's ``Echo``: the client's own input)."""
    if keep and isinstance(value, keep):
        return value
    if isinstance(value, str):
        value = custody_safe(value)
        for h in held:
            if h in value:
                value = value.replace(h, HELD)
        return value
    if isinstance(value, dict):
        return {k: redact(v, held, keep=keep) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, held, keep=keep) for v in value]
    return value


def ledger_record(rec: Any) -> dict[str, Any]:
    """One ledger record as served: what happened, when and to what, without holdout details. The
    fields left out are named in ``redacted``."""
    if not isinstance(rec, dict):
        return {"unreadable": "a line of the ledger is not JSON"}
    raw_event = rec.get("event")
    event: dict[str, Any] = raw_event if isinstance(raw_event, dict) else {}
    payload = dict(event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}
    redacted = sorted(k for k in payload if k in HOLDOUT_FIELDS)
    for k in redacted:
        payload.pop(k)
    if str(payload.get("step", "")).startswith("holdouts") and "reason" in payload:
        payload["reason"] = HOLDOUT_STEP_REASON
        redacted.append("reason")
    out = {"seq": rec.get("seq"), "kind": event.get("kind"), "at": event.get("at"), "payload": payload,
           "hash": rec.get("hash")}
    if redacted:
        out["redacted"] = sorted(redacted)
    return out
