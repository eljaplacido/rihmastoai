"""Named verdict vocabulary for Rihma.

The factory speaks in named verdicts, never in bare exit codes:

    passed, failed, regressed, not applicable, not measured, violation, escalate

Combining verdicts follows the precedence in FR-G3 (tightened by amendment A-0002):
failed or regressed gives failed; else violation; else escalate; else not measured (also
when every input is not applicable, or there is none); else passed. Only passed and not
applicable can combine into passed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

VERDICTS = (
    "passed",
    "failed",
    "regressed",
    "not applicable",
    "not measured",
    "violation",
    "escalate",
)


def combine_verdicts(verdicts: Iterable[str]) -> str:
    """Combine factory verdicts with the FR-G3 precedence (A-0002).

    failed or regressed -> failed; violation -> violation; escalate -> escalate;
    any not measured, or nothing but not applicable (an empty set included) -> not measured;
    otherwise passed. Only passed and not applicable can combine into passed.
    """
    values = tuple(verdicts)
    unknown = [value for value in values if value not in VERDICTS]
    if unknown:
        raise ValueError(f"unknown verdict(s): {', '.join(map(repr, unknown))}")

    if "failed" in values or "regressed" in values:
        return "failed"
    if "violation" in values:
        return "violation"
    if "escalate" in values:
        return "escalate"
    if "not measured" in values or all(value == "not applicable" for value in values):
        return "not measured"
    return "passed"


def validate_translation_table(table: Mapping[int, str]) -> None:
    """Reject a translation table that maps a non-zero native exit to passed.

    FR-G3-AC-2: nothing maps to ``passed`` by configuration. Exit 0 is the
    only native exit that may translate to ``passed``; every other entry must
    use some other named verdict.
    """
    if not isinstance(table, Mapping):
        raise ValueError("translation table must be a mapping")

    for native_exit, verdict in table.items():
        if verdict not in VERDICTS:
            raise ValueError(f"native exit {native_exit!r} maps to {verdict!r}, which is not a named verdict")
        if native_exit != 0 and verdict == "passed":
            raise ValueError(
                f"native exit {native_exit!r} must not map to 'passed'; "
                "only exit 0 may translate to passed"
            )


__all__ = ["VERDICTS", "combine_verdicts", "validate_translation_table"]
