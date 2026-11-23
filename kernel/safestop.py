"""Safe stop is a first-class state (FR-J3; Linear's agent guidelines: "stop immediately when asked").

A person may ask a project to pause. The factory does not cut a Gnomon cell off mid-step. It
stops at the next safe point: between tasks, or between a task's repair rounds. It records where
it stopped, and stays paused until a person resumes. Pausing and resuming are decisions, signed
with a person and a persona like any other: with access enforced (D-0016) the kernel checks again that
the identity signing them holds that persona on the project (kernel.access.require).
"""

from __future__ import annotations

from kernel.people import PERSONAS, is_person

MAY_PAUSE = ("business_owner", "product_owner", "developer", "operations", "it")


def request_pause(project, *, person: str, persona: str, reason: str = "") -> dict:
    _check(project, person, persona)
    state = {"requested_by": person, "persona": persona, "reason": reason,
             "at": project.factory.clock.stamp(), "stopped_at": None}
    project.update_meta(pause=state)
    project.log("pause_requested", {"by": person, "persona": persona, "reason": reason})
    return state


def resume(project, *, person: str, persona: str) -> None:
    _check(project, person, persona)
    was = project.meta.get("pause")
    project.update_meta(pause=None)
    project.log("resumed", {"by": person, "persona": persona, "was_paused_at": (was or {}).get("stopped_at")})


def paused(project) -> bool:
    return bool(project.meta.get("pause"))


def stop_here(project, *, where: str) -> None:
    state = dict(project.meta.get("pause") or {})
    state["stopped_at"] = where
    project.update_meta(pause=state)
    project.log("paused_at_safe_point", {"where": where, "requested_by": state.get("requested_by")})


def _check(project, person: str, persona: str) -> None:
    from kernel.access import require
    from kernel.canon import DecisionRefused

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in PERSONAS or persona not in MAY_PAUSE:
        raise DecisionRefused(f"a {persona} may not pause or resume a project (may: {MAY_PAUSE})")
    require(project, person, persona)
