"""The one-line insights, each computed by a rule from the figures beside it (never by a model).

Each rule names the change or the extreme it found and what it rests on, in plain words:
"Builder tokens doubled against the week before (24.1K against 12.0K): 3 tasks needed 5 or more rounds."
A rule that finds nothing worth saying says what the figure is, so every tile and chart has a line.
"""

from __future__ import annotations

from kernel.insights.base import PREVIOUS_WORDS, compact


def change(what: str, now: float | None, before: float | None, window: str, unit: str = "") -> str | None:
    """How a figure moved against the window before: doubled, rose, fell, held. None when not comparable."""
    period = PREVIOUS_WORDS.get(window)
    if period is None or now is None or before is None:
        return None
    pair = f"({compact(now, unit)} against {compact(before, unit)})"
    if before == 0:
        return f"{what} went from none to {compact(now, unit)} against {period}." if now else None
    ratio = now / before
    if ratio >= 1.9:
        word = f"grew {round(ratio)}-fold" if ratio >= 2.5 else "doubled"
        return f"{what} {word} against {period} {pair}."
    if ratio >= 1.15:
        return f"{what} rose by {round((ratio - 1) * 100)}% against {period} {pair}."
    if ratio <= 0.55:
        word = "halved" if ratio > 0.3 else "fell sharply"
        return f"{what} {word} against {period} {pair}."
    if ratio <= 0.87:
        return f"{what} fell by {round((1 - ratio) * 100)}% against {period} {pair}."
    return f"{what} held steady against {period} {pair}."


def top(what: str, rows: list[dict], unit: str = "", total: float | None = None) -> str | None:
    """The largest row of a ranked list, with its share of the whole."""
    measured = [r for r in rows if r.get("value") is not None]
    if not measured:
        return None
    best = max(measured, key=lambda r: r["value"])
    whole = total if total is not None else sum(r["value"] for r in measured)
    part = f", {round(best['value'] / whole * 100)}% of the whole" if whole and len(measured) > 1 else ""
    return f"{best['label']} leads {what} with {compact(best['value'], unit)}{part}."


def count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def join(*parts: str | None) -> str | None:
    """Sentences joined; a second part follows a colon when the first ends without one."""
    found = [p.rstrip(".") for p in parts if p]
    if not found:
        return None
    return (found[0] + (": " + "; ".join(found[1:]) if len(found) > 1 else "")) + "."
