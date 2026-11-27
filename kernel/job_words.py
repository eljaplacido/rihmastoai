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
                  r"|[JC]-\d{4}|mikä meni vikaan|miksi .{0,20}epäonnistu)", re.IGNORECASE)
WHAT_NEXT = {
    "private or not found": ("Sign in to GitHub on this machine (gh auth login) with an account that can read it, "
                             "then start the adoption again; or adopt a clone of it on this machine (New project, "
                             "An existing project, Browse)."),
    "did not finish": "The upstream or the network was slow: try again; if it repeats, adopt a local clone "
                      "instead.",
    "could not start": "git is not installed or not on PATH for the cockpit: install git, restart the cockpit, "
                       "try again.",
}


INTERRUPTED = "interrupted"
RESTARTED = ("Interrupted by a cockpit restart: the cockpit stopped while it ran, so how it ended is not known and "
             "nothing after that was kept")
FOOTER = re.compile(r"^\[exit (-?\d+) after ([\d.]+) s\]$")


def _ended_from_outside(lines: list[str]) -> str | None:
    """A run whose footer says it exited with a negative code (Windows' 4294967295 is -1, a POSIX signal is -9):
    something outside ended it."""
    for line in reversed(lines[-5:]):
        found = FOOTER.match(line.strip())
        if found:
            code = int(found.group(1))
            code = code - 2 ** 32 if code >= 2 ** 31 else code
            if code < 0:
                return (f"The process was ended from outside after {float(found.group(2)):.0f} s (exit {code}), by "
                        "the system or a person: it finished nothing, and nothing was recorded")
            return None
    return None


def reason(log: Path) -> str | None:
    """The last error the job printed, in its own words, or None when it printed none."""
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    except OSError:
        return None
    outside = _ended_from_outside(lines)        # FR-NVL3: a killed run is said as one
    if outside:
        return outside
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
    if why and ("ended from outside" in why or why.startswith("Interrupted by a cockpit restart")):
        return "Run it again (Re-run): nothing it would have recorded was kept."
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
    from kernel.job_registry import interrupted

    restarted = {Path(r["log"]).name for r in interrupted(Path(factory.home))}
    for log in logs:
        why = reason(log) or (RESTARTED if log.name in restarted else None)
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
