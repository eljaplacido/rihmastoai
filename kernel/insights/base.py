"""What every insights read model shares: the window, the records in it, and the shapes it answers in.

A read is over a **scope**: one project or the whole factory (every product, never Rihma's own canon), and a
**window**: the last 24 hours, 7 days, 30 days, or all of the records. The window ends at the factory clock's
now. Every number is counted from the records (the ledgers, the canons, the projects' own files and Gnomon's
own records in the lanes) and none is estimated. What has nothing to rest on is **not measured**: its value is
None, never zero, and it says why and how to get it measured.

The shapes:

- a **tile**: one figure with its label, unit, basis, an optional delta against the previous window of the
  same length, a one-line insight computed by rule, and a link to the records;
- a **chart**: rows for one form (``timeseries``, ``columns``, ``bars``, ``stack100``), its series, its basis
  and its insight line; a chart with no rows is not measured, with why and how;
- a **gap**: something this dimension cannot measure here, with why and how.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from kernel.graph_records import object_of

WINDOWS: dict[str, dt.timedelta | None] = {"24h": dt.timedelta(hours=24), "7d": dt.timedelta(days=7),
                                           "30d": dt.timedelta(days=30), "all": None}
WINDOW_WORDS = {"24h": "the last 24 hours", "7d": "the last 7 days", "30d": "the last 30 days", "all": "all records"}
PREVIOUS_WORDS = {"24h": "the 24 hours before", "7d": "the week before", "30d": "the 30 days before"}
DIMENSIONS = ("health", "compliance", "governance", "security", "drift", "qa", "usage")
LABELS = {"health": "Health", "compliance": "Compliance", "governance": "Governance", "security": "Security",
          "drift": "Context drift", "qa": "QA", "usage": "Usage"}
MAX_BUCKETS = 60


def when(text: Any) -> dt.datetime | None:
    """An ISO stamp as an aware datetime; None when there is none or it does not parse."""
    if not isinstance(text, str) or not text:
        return None
    try:
        t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def stamp(t: dt.datetime | None) -> str | None:
    return t.astimezone(dt.UTC).isoformat().replace("+00:00", "Z") if t else None


def hours(a: dt.datetime | None, b: dt.datetime | None) -> float | None:
    return round((b - a).total_seconds() / 3600, 1) if a and b else None


def median(values: list[float]) -> float | None:
    vs = sorted(values)
    if not vs:
        return None
    mid = len(vs) // 2
    return round(vs[mid] if len(vs) % 2 else (vs[mid - 1] + vs[mid]) / 2, 1)


def compact(n: float | None, unit: str = "") -> str:
    """1,284 / 12.9K / 4.2M, as a stat tile shows a number."""
    if n is None:
        return "not measured"
    a = abs(n)
    text = (f"{n / 1_000_000:.1f}M" if a >= 1_000_000 else f"{n / 1000:.1f}K" if a >= 10_000
            else f"{n:,.0f}" if float(n).is_integer() or a >= 100 else f"{n:,.2f}".rstrip("0").rstrip(".") if a >= 1
            else f"{n:.4g}")
    return f"{text} {unit}".strip() if unit and unit not in ("%",) else text + ("%" if unit == "%" else "")


def share(part: float, whole: float) -> float | None:
    return round(part / whole * 100, 1) if whole else None


class Scope:
    """One read: the projects it covers, the window, and each project's ledger read once."""

    def __init__(self, factory: Any, *, pid: str | None = None, window: str = "7d") -> None:
        if window not in WINDOWS:
            raise ValueError(f"the window is one of {', '.join(WINDOWS)}, got {window!r}")
        self.factory, self.pid, self.window = factory, pid, window
        self.now = factory.clock.now()
        span = WINDOWS[window]
        self.span = span
        self.since = self.now - span if span else None
        if pid is not None:
            project = factory.project(pid)
            if not project.path("project.json").exists():
                raise KeyError(f"no project {pid!r}")
            self.projects = [project]
        else:
            self.projects = [p for p in factory.projects() if not p.pid.startswith("_")]
        self._records: dict[str, list] = {}

    @property
    def scope(self) -> str:
        return "project" if self.pid else "factory"

    def title(self, project: Any) -> str:
        return str(project.meta.get("title") or project.pid)

    def records(self, project: Any) -> list:
        if project.pid not in self._records:
            self._records[project.pid] = [r for r in project.ledger().records()
                                          if isinstance(r, dict) and isinstance(r.get("event"), dict)]
        return self._records[project.pid]

    def inside(self, t: dt.datetime | None) -> bool:
        """Whether a time falls in the window. A record without a time is in "all" only."""
        if self.since is None:
            return True
        return t is not None and self.since <= t <= self.now

    def before(self, t: dt.datetime | None) -> bool:
        """Whether a time falls in the window before this one, of the same length."""
        if self.span is None or self.since is None or t is None:
            return False
        return self.since - self.span <= t < self.since

    def events(self, *kinds: str, previous: bool = False) -> Iterator[tuple[Any, dt.datetime | None, dict, dict]]:
        """(project, time, payload, record) of each ledger event of these kinds in the window (or the one before)."""
        test = self.before if previous else self.inside
        for p in self.projects:
            for rec in self.records(p):
                ev = rec["event"]
                if kinds and ev.get("kind") not in kinds:
                    continue
                t = when(ev.get("at"))
                if test(t):
                    yield p, t, ev.get("payload") or {}, rec

    def every(self, *kinds: str) -> Iterator[tuple[Any, dt.datetime | None, dict, dict]]:
        """Each event of these kinds whatever its time: for state that the window does not cut (the latest)."""
        for p in self.projects:
            for rec in self.records(p):
                ev = rec["event"]
                if not kinds or ev.get("kind") in kinds:
                    yield p, when(ev.get("at")), ev.get("payload") or {}, rec

    def buckets(self) -> list[tuple[dt.datetime, dt.datetime, str]]:
        """The time axis: hours over 24 hours, days over 7 and 30, days or weeks over all of the records."""
        if self.window == "24h":
            end = self.now.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
            return [(end - dt.timedelta(hours=n), end - dt.timedelta(hours=n - 1),
                     (end - dt.timedelta(hours=n)).strftime("%H:00")) for n in range(24, 0, -1)]
        end = self.now.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
        if self.span is not None:
            days = self.span.days
        else:
            first = min((t for p in self.projects for rec in self.records(p)
                         if (t := when(rec["event"].get("at")))), default=None)
            days = max(1, (end - first).days + 1) if first else 1
        step = dt.timedelta(days=1 if days <= MAX_BUCKETS else 7)
        n = -(-days // step.days)
        return [(end - step * k, end - step * (k - 1), (end - step * k).strftime("%b %d").replace(" 0", " "))
                for k in range(n, 0, -1)]

    def href(self, project: Any, view: str = "overview", focus: str | None = None) -> str:
        return f"#/p/{project.pid}/{view}" + (f"/{focus}" if focus else "")


def tile(key: str, label: str, value: float | None, *, basis: str, unit: str = "", display: str | None = None,
         line: str | None = None, why: str | None = None, how: str | None = None, href: str | None = None,
         status: str | None = None, delta: dict | None = None, sub: str | None = None) -> dict:
    """One figure. Not measured (value None) always says why and how to get it measured."""
    measured = value is not None
    if not measured and not (why and how):
        raise ValueError(f"tile {key}: a figure that is not measured says why and how")
    return {"key": key, "label": label, "value": value, "measured": measured, "unit": unit,
            "display": (display if display is not None else compact(value, unit)) if measured else "not measured",
            "basis": basis, "line": line if measured else f"Not measured: {why}.", "why": None if measured else why,
            "how": None if measured else how, "href": href, "status": status if measured else None,
            "delta": delta if measured else None, "sub": sub}


def delta(now: float | None, before: float | None, period: str) -> dict | None:
    """The change against the window before, when both were measured."""
    if now is None or before is None:
        return None
    return {"value": round(now - before, 2), "before": before, "vs": period,
            "pct": round((now - before) / before * 100, 1) if before else None}


def chart(key: str, title: str, kind: str, *, rows: list, basis: str, series: list | None = None, unit: str = "",
          line: str | None = None, why: str | None = None, how: str | None = None, note: str | None = None) -> dict:
    """One chart. With no rows it is not measured, and says why and how."""
    measured = bool(rows)
    if not measured and not (why and how):
        raise ValueError(f"chart {key}: a chart with no rows says why and how")
    return {"key": key, "title": title, "kind": kind, "rows": rows, "series": series or [], "unit": unit,
            "basis": basis, "measured": measured, "line": line if measured else f"Not measured: {why}.",
            "why": None if measured else why, "how": None if measured else how, "note": note}


def gap(what: str, why: str, how: str) -> dict:
    return {"what": what, "why": why, "how": how}


def answer(scope: Scope, dimension: str, tiles: list, charts: list, gaps: list | None = None) -> dict:
    """A dimension's read model, as the cockpit, the command line and the export read it."""
    return {"dimension": dimension, "label": LABELS[dimension], "scope": scope.scope, "project": scope.pid,
            "project_title": scope.title(scope.projects[0]) if scope.pid else None, "window": scope.window,
            "window_words": WINDOW_WORDS[scope.window], "since": stamp(scope.since), "until": stamp(scope.now),
            "projects": len(scope.projects), "tiles": tiles, "charts": charts, "gaps": gaps or []}


def series_rows(scope: Scope, points: list[tuple[Any, Any, Any]]) -> list[dict]:
    """(time, series key, amount) points summed into the scope's buckets: [{at, label, values}]."""
    axis = scope.buckets()
    sums: list[dict[str, float]] = [{} for _ in axis]
    for t, key, amount in points:
        i = next((n for n, (a, b, _) in enumerate(axis) if t is not None and a <= t < b), None)
        if i is not None:
            sums[i][key] = round(sums[i].get(key, 0) + amount, 6)
    if not any(sums):
        return []
    return [{"at": stamp(a), "label": label, "values": v} for (a, _, label), v in zip(axis, sums, strict=True)]


obj = object_of     # a record's field as a dict; anything else (absent, a string, a list) as an empty one


def first(items: list[dict[str, Any]], key: str, default: Any = None) -> Any:
    """The first item's field, or the default when there is no item."""
    return items[0].get(key, default) if items else default


def level(value: float | None, good: float, warn: float, *, higher_is_better: bool = True) -> str | None:
    """A status for a measured figure: good, warning or critical, by two thresholds."""
    if value is None:
        return None
    v, g, w = (value, good, warn) if higher_is_better else (-value, -good, -warn)
    return "good" if v >= g else "warning" if v >= w else "critical"


def unit_of(window: str) -> str:
    return "hour" if window == "24h" else "day"
