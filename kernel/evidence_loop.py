"""People in the loop in an evidence pack (kernel/evidence_pack.py, kernel/hitl.py, FR-HITL1).

A person's signed answer to an ask (a governance decision, a legal answer, a team member's reply), from inside or
from outside through a one-use link, is human oversight as much as a decision on a card. The pack carries them in
``people-in-the-loop.json``, from the same ledger read as the rest of the bundle: every ask, every signed answer
(who, as which persona, from outside or not, through which link) and every change to how strictly a check family
is enforced (who set it, at which level, for this project or all of them). The at-a-glance count of decisions by
people counts them, and the human-oversight control names the file.
"""

from __future__ import annotations

from typing import Any

FILE = "people-in-the-loop.json"
ART14_BY = ("decisions.json: every decision signed by a named person and persona; {file}: {n} signed answer(s) from "
            "people in the loop ({outside} from outside, through a one-use link) and {changes} enforcement change(s); "
            "the autonomy cap in capability-pack.json")


def loop_file(records: list) -> dict[str, Any]:
    """Every ask, signed answer and enforcement change people in the loop made, from the ledger's records."""
    # the pack's own reading of its records (the pack imports this module, so it is read here)
    from kernel.evidence_pack import _of

    answers = _of(records, "hitl_answered")
    return {"answers": answers, "asks": _of(records, "hitl_asked"),
            "enforcement": _of(records, "hitl_enforcement_set"),
            "counts": {"answers": len(answers), "outside": sum(1 for a in answers if a.get("external")),
                       "enforcement": len(_of(records, "hitl_enforcement_set"))},
            "note": "signed answers to asks put to a persona or a named person, inside Rihmasto or outside it through "
                    "a one-use link; each is also in ledger.jsonl"}


def decisions_line(files: dict[str, Any]) -> str:
    """The README's line on decisions by people: the decisions and the signed answers, and where each is."""
    decided = len(files.get("decisions.json") or [])
    loop = files.get(FILE) or {}
    counts = loop.get("counts") or {}
    answers = counts.get("answers", 0)
    gates = len(files.get("gates.json") or [])
    if not answers:
        return f"- Decisions by people: {decided}. Gate verdicts: {gates}."
    return (f"- Decisions by people: {decided + answers} ({decided} in `decisions.json`, {answers} signed answer(s) "
            f"from people in the loop in `{FILE}`, {counts.get('outside', 0)} of them from outside). "
            f"Gate verdicts: {gates}.")


def oversight(controls: list[dict[str, Any]], files: dict[str, Any]) -> list[dict[str, Any]]:
    """The human-oversight control naming the signed answers too, where there are any."""
    counts = (files.get(FILE) or {}).get("counts") or {}
    if not counts.get("answers") and not counts.get("enforcement"):
        return controls
    by = ART14_BY.format(file=FILE, n=counts.get("answers", 0), outside=counts.get("outside", 0),
                         changes=counts.get("enforcement", 0))
    return [dict(c, by=by) if c["control"] == "ai-act:art14" else c for c in controls]


def answered(files: dict[str, Any]) -> int:
    """How many signed answers people in the loop gave."""
    return ((files.get(FILE) or {}).get("counts") or {}).get("answers", 0)
