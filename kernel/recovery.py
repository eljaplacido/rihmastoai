"""Never lost when something breaks (FR-NVL3): what Rihmasto says, in plain words with the next step, when a record
cannot be read, a write fails, a project was removed, or the cockpit restarted while work ran.

- ``removed``: a removed project's record in the factory's ledger (kernel/project_archive.py), so an old link says
  who removed it, when, and where its records were kept, instead of "not found".
- ``os_words``: an operating-system failure (a full disk, a read-only or locked file, a missing folder) said
  plainly, naming the file but never the full path or the errno.
- ``scope_note``: Ask Rihma's answer for a project that cannot be read or is gone, by rule: the file named, the way
  back, and the platform scope to go on in.

Standard library only; no model.
"""

from __future__ import annotations

import errno
import re
from typing import Any

from kernel.store import Factory, Project

FULL = (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC))
READ_ONLY = (errno.EACCES, errno.EPERM, errno.EROFS)


def removed(factory: Factory, pid: str) -> dict[str, Any] | None:
    """The removal of ``pid`` as the factory's ledger keeps it: title, who, when, the export file, and the sentence
    to say. None when it was never removed (or the factory has no ledger yet)."""
    from kernel.learn import factory_project

    own = factory_project(factory, create=False)
    if own is None or not pid:
        return None
    found = None
    for rec in own.ledger().of_kind("project_removed"):
        event = rec["event"]
        if (event.get("payload") or {}).get("project") == pid:
            found = event
    if found is None:
        return None
    payload = found.get("payload") or {}
    title = payload.get("title") or pid
    when = str(found.get("at") or "")[:10]
    by = payload.get("person") or "someone"
    export = payload.get("export") or "exports/removed/"
    said = (f"{title} was removed on {when or 'an earlier day'} by {by}; its records are kept in {export} "
            "(a zip of the project's folder). Go back to Projects to open another one.")
    return {"id": pid, "title": title, "at": found.get("at"), "by": by, "export": export, "said": said,
            "route": "#/projects"}


def gone(factory: Factory, pid: str) -> str:
    """What to say for a project id that is not here: removed (by whom, where its records are), else not found."""
    was = removed(factory, pid)
    if was is not None:
        return str(was["said"])
    return f"There is no project {pid} here: the link may be old or mistyped. Go back to Projects to pick one."


def os_words(exc: OSError) -> str:
    """An operating-system failure in plain words, naming only the file: what it means and what to do."""
    name = re.split(r"[\\/]", str(exc.filename))[-1] if exc.filename else "a file"   # a Windows path on any system
    if exc.errno in FULL:
        return (f"The disk is full: {name} could not be written. Nothing was recorded. Free some space, "
                "then try again.")
    if exc.errno in READ_ONLY or isinstance(exc, PermissionError):
        return (f"{name} is read-only or in use by another program, so it could not be written. Nothing was "
                "recorded. Make it writable (or close the program holding it), then try again.")
    if isinstance(exc, FileNotFoundError):
        return f"{name} is missing, so this could not be done. Nothing was recorded."
    return f"{name} could not be written ({exc.strerror or 'a disk error'}). Nothing was recorded: try again."


def is_os_failure(exc: BaseException) -> bool:
    """An error the operating system raised (it carries an errno), as opposed to a refusal by Rihmasto's rules
    (a PermissionError the kernel raises with no errno)."""
    return isinstance(exc, OSError) and exc.errno is not None


def scope_note(factory: Factory, pid: str | None) -> dict[str, Any] | None:
    """Ask Rihma's answer, by rule, when its project cannot be read or was removed; None when the project is fine
    (or was never here: that is refused as before)."""
    if not pid or pid == "_factory":
        return None
    project = Project(factory, pid)
    if project.path("project.json").exists():
        bad = project.unreadable()
        if bad is None:
            return None
        return _answer(str(bad), "Open Projects", "#/projects", reason="unreadable", file="project.json")
    was = removed(factory, pid)
    if was is None:            # never here: the asker's own mistake, refused as before (404)
        return None
    return _answer(str(was["said"]) + " I answer about the whole platform from here.", "Open Projects", "#/projects",
                   reason="removed")


def _answer(text: str, label: str, route: str, **why: Any) -> dict[str, Any]:
    fill = {"label": label, "view": "projects", "route": route, "control": None}
    return {"answer": text, "navigate": {"route": route, "control": None}, "fill": fill, "by": "why",
            "propose": [], "dropped": [], "sources": [], "why": {"view": "project", "kind": "error",
                                                                  "premise": "broken", **why}}
