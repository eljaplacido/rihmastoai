"""The events an automation reacts to (FR-AUT1), the life-cycle steps and their transitions first (D-0023).

D-0023: "Every transition is visible, recorded, and can trigger an automation." Each transition below is a
record in a ledger, written where the transition happens, and an automation's event trigger names it by the
name on the left. Where a record already said it, that record is used, with its verdict where one record kind
holds more than one outcome; two records were added for transitions nothing said plainly before:
``first_build_passed`` (kernel/dispatch.py) and ``release_reached_test`` (kernel/deliver.py).

=========================  ==========================================================================
concept_validated          ``created_from_concept`` in the new project (kernel/signals.py)
plan_approved              ``plan_approved`` (kernel/plan.py), or ``go_ahead_given`` with Go at explore
                           and demo, where the look at the spec is the approval (kernel/go_ahead.py)
first_build_passed         ``first_build_passed``: every task merged through the gate, the first time
release_reached_test       ``release_reached_test``: a release deployed to a test road (preview, demo
                           or staging) and its smoke check passed (kernel/deliver.py)
promoted                   ``promoted``: a release promoted to production (kernel/deliver.py)
rolled_back                ``rolled_back`` (kernel/operate.py)
check_failed               ``probe_failed`` (a probe on production) or ``release_failed`` (a release's
                           step, its smoke check or its holdouts, failed)
gate_failed, gate_passed   ``gate`` with that verdict
=========================  ==========================================================================

Any other record kind may be named as it is (``release_done``, ``question_added``, ...).
"""

from __future__ import annotations

import re
from typing import Any

# A name a person picks, and the records it matches: (record kind, verdict or None for any).
EVENT_ALIASES: dict[str, tuple[tuple[str, str | None], ...]] = {
    "gate_failed": (("gate", "failed"),), "gate_passed": (("gate", "passed"),),
    "card_waiting": (("card_opened", None),),
    "concept_validated": (("created_from_concept", None),),
    "plan_approved": (("plan_approved", None), ("go_ahead_given", "go")),
    "check_failed": (("probe_failed", None), ("release_failed", None)),
}
# The life-cycle transitions, in the order a capability lives them (D-0023).
LIFECYCLE = ("concept_validated", "plan_approved", "first_build_passed", "release_reached_test", "promoted",
             "rolled_back", "check_failed")
COMMON_EVENTS = (*LIFECYCLE, "release_done", "release_failed", "gate_failed", "gate_passed", "question_added",
                 "card_waiting", "change_submitted", "adopted", "material_added", "upstream_synced", "hook_received",
                 "incident_opened", "probe_failed", "decision", "signal_received", "project_created")


def records_of(name: str) -> tuple[tuple[str, str | None], ...]:
    """The records an event name matches: its alias's, or the record kind of that name."""
    return EVENT_ALIASES.get(name, ((name, None),))


ENVIRONMENTS = ("preview", "demo", "staging", "production")
_EVERY = re.compile(r"(\d{1,4})([mhd])\Z")


def probe_fields(factory: Any, a: dict[str, Any]) -> dict[str, Any]:
    """The probe action's parts: where it probes (empty: the environment the event names, else production) and,
    optionally, how often it keeps probing production from then on, the probe check enabled (``every``, 15m to
    1d)."""
    env, every = str(a.get("environment") or ""), str(a.get("every") or "")
    if env and env not in ENVIRONMENTS:
        raise ValueError(f"a probe's environment is one of {', '.join(ENVIRONMENTS)}, or empty: the event's")
    m = _EVERY.match(every)
    if every and not (m and 15 <= int(m.group(1)) * {"m": 1, "h": 60, "d": 1440}[m.group(2)] <= 1440):
        raise ValueError("a probe check is enabled every 15m to 1d")
    return {"environment": env or None, "every": every or None}


def seconds_of(every: str) -> int:
    m = _EVERY.match(every)
    return int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)] if m else 0
