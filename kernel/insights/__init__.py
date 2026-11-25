"""Insights: health, compliance, governance, security, context drift, QA and usage, per project and factory-wide.

The owner (2026-11-24): "about the insights view, inspired by the different dimensions of Rihmasto + Gnomon +
an agentic observability stack: enable data visualization views, dashboards and insights on health,
compliance, governance, security, context drift, QA, token/skill/memory usage of projects and their agentic
features."

Each dimension is a read model over a scope (one project, or every product in the factory) and a window
(24h, 7d, 30d or all). Every number is counted from the records and none is estimated; what has nothing to
rest on says "not measured", why, and how to get it measured (kernel/insights/base.py). Each tile and chart
carries a one-line insight computed by rule (kernel/insights/lines.py). Rihmasto stays the system of record
for decisions and evidence, not telemetry (D-0017): ``kernel/insights/export.py`` writes the same figures as
JSON, CSV or OpenTelemetry-style JSON for a team's own observability tools, and sends nothing anywhere.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from kernel.insights.base import DIMENSIONS, LABELS, WINDOWS, Scope

__all__ = ["DIMENSIONS", "LABELS", "WINDOWS", "overview", "read", "summary", "tile_of"]
MODULES = {"health": "health", "compliance": "compliance", "governance": "governance", "security": "security",
           "drift": "drift", "qa": "qa", "usage": "usage"}


def read(factory: Any, dimension: str, *, pid: str | None = None, window: str = "7d") -> dict[str, Any]:
    """One dimension's read model. An unknown dimension or window is a ValueError, an unknown project a KeyError."""
    if dimension not in DIMENSIONS:
        raise ValueError(f"the dimension is one of {', '.join(DIMENSIONS)}, got {dimension!r}")
    scope = Scope(factory, pid=pid, window=window)
    out: dict[str, Any] = import_module(f"kernel.insights.{MODULES[dimension]}").read(scope)
    return out


def overview(factory: Any, *, pid: str | None = None, window: str = "7d") -> dict[str, Any]:
    """Every dimension at once, as the export and the command line without --dimension give them."""
    return {"scope": "project" if pid else "factory", "project": pid, "window": window,
            "dimensions": [read(factory, d, pid=pid, window=window) for d in DIMENSIONS]}


def tile_of(factory: Any, dimension: str, key: str, *, pid: str | None = None, window: str = "7d") -> dict[str, Any]:
    """One tile, for a widget pinned on Home: the tile and where it came from. A KeyError when there is none."""
    model = read(factory, dimension, pid=pid, window=window)
    found = next((t for t in model["tiles"] if t["key"] == key), None)
    if found is None:
        raise KeyError(f"no tile {key!r} in {dimension}")
    return {"tile": found, "dimension": dimension, "label": model["label"], "window": window, "project": pid,
            "project_title": model["project_title"], "since": model["since"], "until": model["until"]}


KEY_TILES = {"health": ("at_risk", "failures"), "compliance": ("coverage", "posture_unmet"),
             "governance": ("waiting", "time_to_decide"), "security": ("open_findings", "secret_hits"),
             "drift": ("untested", "context_trims"), "qa": ("pass_rate", "rounds_per_task"),
             "usage": ("tokens", "cost", "tool_calls")}


def summary(factory: Any, *, pid: str | None = None, window: str = "7d") -> dict[str, Any]:
    """A short picture for the assistant: a few key figures per dimension, as displayed. Figures only: no
    project's title, no insight line and no decision's reason is in it; with a project open, only that project's
    records are read."""
    out: dict[str, Any] = {"window": window, "scope": "project" if pid else "factory", "page": "#/insights"}
    for d, keys in KEY_TILES.items():
        try:
            model = read(factory, d, pid=pid, window=window)
        except Exception as exc:  # noqa: BLE001 - one unreadable dimension never empties the assistant's picture
            out[d] = {"could_not_read": type(exc).__name__}
            continue
        out[d] = {t["key"]: (t["display"] if t["measured"] else "not measured")
                  for t in model["tiles"] if t["key"] in keys}
    return out
