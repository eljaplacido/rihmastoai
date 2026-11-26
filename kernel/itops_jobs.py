"""Which scheduled automations are a project's own jobs, and which only watch it (FR-ITO2).

- ``scheduled``: every active scheduled automation that reaches the project, what the job check (kernel/checks/
  infra_data.py) measures for lateness and failures in a row. A paused one is left out: it was paused on purpose,
  so it is not "late"; ``paused`` lists those for the check's evidence;
- ``own_jobs``: the scheduled automations that make the project a "Scheduled job or pipeline" (kernel/itops.py):
  active, scoped to this project or a group of projects (never the platform-wide ones, which reach every project
  alike), and doing the project's work rather than watching it. An automation that runs a check, an eval, an
  assessment, a probe or a digest watches the project: the IT suggestion "Weekly IT check set" just accepted does
  not turn a web service into a job.

Reading writes nothing; automations that cannot be read give none.
"""

from __future__ import annotations

from typing import Any

# Actions that watch or report on a project: running them on a schedule does not make the project a job.
WATCHING = ("run_check", "run_eval", "run_assessment", "probe", "watch", "agent_snapshot", "align_scan",
            "review_digest", "rescan", "notify", "ask")


def _reaching(project: Any) -> list[dict[str, Any]]:
    from kernel import automations as au

    try:
        return [a for a in au.automations(project.factory) if (a.get("trigger") or {}).get("kind") == "schedule"
                and au.in_scope(project, a["scope"])]
    except (OSError, ValueError, KeyError):
        return []


def scheduled(project: Any) -> list[dict[str, Any]]:
    """The active scheduled automations that reach the project."""
    return [a for a in _reaching(project) if a.get("state", "active") == "active"]


def paused(project: Any) -> list[dict[str, Any]]:
    """The paused scheduled automations that reach the project (said as paused, never as late)."""
    return [a for a in _reaching(project) if a.get("state") == "paused"]


def own_jobs(project: Any) -> list[dict[str, Any]]:
    """The active scheduled automations that are this project's own work, not platform-wide and not watching it."""
    return [a for a in scheduled(project) if (a.get("scope") or {}).get("kind") != "factory"
            and (a.get("action") or {}).get("kind") not in WATCHING]
