"""A background job in plain words: what it was working on, and, when it failed, why and what to do next
(the owner, 2026-11-25: "there would always be a follow-up to any fail that can be escalated to Rihma").

By rule, from the job's own log: the last error line the kernel printed, with the hint it gave. Ask Rihma
answers "what went wrong?" from the newest failed job's log in the factory home.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ERROR = re.compile(r"^(?:[A-Za-z_.]*(?:Error|Refused|Exception)|error|refused|fatal): (.+)$")
ASKS = re.compile(r"\b(what went wrong|why\b.{0,30}\bfail\w*|job\w* fail\w*|fail\w* (job|run|adoption)"
                  r"|J-\d{4}|mikä meni vikaan|miksi .{0,20}epäonnistu)", re.IGNORECASE)
WHAT_NEXT = {
    "private or not found": ("Sign in to GitHub on this machine (gh auth login) with an account that can read it, "
                             "then start the adoption again; or adopt a clone of it on this machine (New project, "
                             "An existing project, Browse)."),
    "did not finish": "The upstream or the network was slow: try again; if it repeats, adopt a local clone "
                      "instead.",
    "could not start": "git is not installed or not on PATH for the cockpit: install git, restart the cockpit, "
                       "try again.",
}


def reason(log: Path) -> str | None:
    """The last error the job printed, in its own words, or None when it printed none."""
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    except OSError:
        return None
    for line in reversed(lines):
        found = ERROR.match(line.strip())
        if found:
            return found.group(1).strip()[:600]
    return None


def next_step(why: str | None) -> str:
    """What to do about it."""
    if why and ("could not read Username" in why or "Authentication failed" in why):
        why = "private or not found"
    for key, step in WHAT_NEXT.items():
        if why and key in why:
            return step
    return ("Open the job's log (What it printed) for the full output; start it again once the cause is fixed, or "
            "ask Rihma with the job's id.")


def title(job: dict[str, Any]) -> str:
    """What the job was working on: for an adoption, the repository or folder it took, not the factory."""
    args = [str(a) for a in job.get("args") or []]
    if job.get("kind") == "adopt":
        where = next((a for a in args if "://" in a or a.startswith(("git@", "C:", "/", "\\")) or ":\\" in a), "")
        name = re.split(r"[\\/]", where.rstrip("/\\"))[-1].removesuffix(".git") if where else ""
        return f"Adopt {name}" if name else "Adopt a project"
    return f"{str(job.get('kind') or 'job').capitalize()} {job.get('project') or ''}".strip()


def answer(factory: Any, project: Any = None) -> dict[str, Any] | None:
    """Ask Rihma's answer about the newest failed job, by rule; None when no job failed. Asked in a project, only that
    project's jobs are read; asked outside any project, only the factory's own (an adoption): never another project's."""
    pid = project.pid if project is not None else "_factory"
    logs = sorted(Path(factory.home, "jobs").glob(f"*-{pid}-*.log"), key=lambda p: p.stat().st_mtime,
                  reverse=True)[:20]
    for log in logs:
        why = reason(log)
        if why:
            what = log.stem.split("-", 2)[-1].rsplit("-", 1)[0].replace("_factory", "the factory")
            return {"answer": f"The newest failed job ({what}, log {log.name}) stopped with: {why}\n\n"
                              f"What to do: {next_step(why)}",
                    "navigate": {"route": "#/jobs", "control": None}, "propose": [], "dropped": [], "sources": [],
                    "by": "rule", "matches": []}
    return None


def asks_about_failure(question: str) -> bool:
    """Whether a question asks why a job failed."""
    return ASKS.search(question or "") is not None
