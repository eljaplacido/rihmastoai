"""One scheduled check run, kept from stopping the rest of its tick (FR-ITO2 with FR-CHK1).

kernel/checks/store.py ``tick`` runs every check that is due, one after another. A check whose own code breaks is
already recorded as not measured by ``_measure``; ``one`` guards what is left (recording the result, the heal hook)
so one project's broken check never keeps another project's checks from running in the same tick. What broke is
recorded as that check's result where it can be, so the check is not due again at once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel.checks import not_measured


def one(project: Any, key: str, run: Callable[[Any, str], dict[str, Any]]) -> dict[str, Any]:
    """``run(project, key)``'s verdict for the tick's list; a break is recorded and said, never raised."""
    try:
        return {"project": project.pid, "check": key, "verdict": run(project, key)["verdict"]}
    except Exception as exc:  # a broken run is said here and the tick goes on with the next check
        said = f"the scheduled run broke ({type(exc).__name__}: {exc})"
        _keep(project, key, said)
        return {"project": project.pid, "check": key, "verdict": "not measured", "error": said[:300]}


def _keep(project: Any, key: str, said: str) -> None:
    from kernel.checks import store as cstore

    entry = cstore.enabled(project).get(key)
    if entry is None:
        return
    try:
        cstore._keep(project, key, {**not_measured(said), "check": key, "kind": entry["kind"],
                                    "at": project.factory.clock.stamp(), "seconds": 0.0,
                                    "by": dict(entry.get("by") or {}), "via": "schedule"})
    except (OSError, ValueError):
        return
