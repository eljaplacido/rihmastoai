"""Feeding a project never fails the whole flow (FR-HEAL1, D-0024 item 1): a scan, an adoption or an intake that
meets a timeout, a huge folder, an unreadable file or a git error degrades instead.

- ``resilient_preview`` scans a folder as kernel/material.py does, within a time budget. A scan that raises (an
  unreadable folder, a file name the system cannot decode, a git error underneath) or takes longer than the budget
  becomes a **partial** map: every file it could list, listed and not read, the folders it could not open with
  the reason, ``partial: true`` and the reason in the map's ``cut``. The person sees what was skipped and why, and
  can scan again (the next scan starts over, so nothing half-read is kept) or untick what is too large.
- ``degraded_map`` is that partial map on its own.
- ``job_incident`` turns a failed or lost background job (an adoption, an intake, a run) into an incident with its
  log's tail, so "Run it again" (the same request) is offered instead of a dead end: a job resumes where its own
  records stopped (kernel/pipeline.py), and an adoption that failed made no project, so running it again is safe.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from kernel import incidents as inc

BUDGET_S = 60.0
LIST_BUDGET_S = 10.0
LIST_MAX = 5000


def _listed(root: Path, path: Path, patterns: list[str]) -> dict[str, Any]:
    """One file's row in a partial map: listed and not read, excluded, or not readable at all."""
    from kernel.material import _excluded

    rel = path.relative_to(root).as_posix()
    row = {"path": rel, "size": 0, "format": path.suffix.lower() or "none", "kind": "other", "chars": 0}
    try:
        row["size"] = path.stat().st_size
    except OSError as exc:
        return row | {"action": "skipped", "why": f"could not be read: {type(exc).__name__}"}
    if _excluded(rel, patterns):
        return row | {"action": "skipped", "why": "excluded by you"}
    return row | {"action": "listed", "why": "listed, not read: the full scan could not finish"}


def degraded_map(folder: str | Path, exclude: Iterable[str], why: str, *, budget: float = LIST_BUDGET_S) -> dict:
    """A partial material map: the files listed (none read), the folders not opened and why, and the reason."""
    from kernel.material import SCHEMA

    root = Path(folder).expanduser().resolve()
    patterns = [p for p in exclude if str(p).strip()]
    rows: list[dict[str, Any]] = []
    dirs: list[dict[str, str]] = []
    end = time.monotonic() + budget

    def unreadable(err: OSError) -> None:
        dirs.append({"path": str(getattr(err, "filename", "") or "?"),
                     "why": f"could not be opened: {type(err).__name__}"})
    for here, _dirs, filenames in os.walk(root, onerror=unreadable, followlinks=False):
        if time.monotonic() > end:
            dirs.append({"path": Path(here).relative_to(root).as_posix() + "/",
                         "why": "not walked: the listing ran out of time"})
            break
        rows += [_listed(root, Path(here) / f, patterns) for f in sorted(filenames)]
    more = max(0, len(rows) - LIST_MAX)
    rows = rows[:LIST_MAX]
    totals = {a: sum(1 for r in rows if r["action"] == a) for a in ("read", "summarised", "listed", "skipped")}
    totals.update(files=len(rows), secrets=0, excluded=sum(1 for r in rows if r["why"] == "excluded by you"),
                  code=0, chars=0, budget=0)
    return {"schema": SCHEMA, "folder": str(root), "budget": 0, "exclude": patterns, "files": rows, "order": [],
            "inventory": None, "skipped_dirs": dirs[:200], "not_looked_at": more, "partial": True,
            "cut": [f"the scan could only list the folder: {why}. Nothing was read. Scan again, or untick the large "
                    "or unreadable parts."], "agent_context": None, "totals": totals, "request_sha256": None}


def resilient_preview(folder: str | Path, exclude: Iterable[str] = (), *, budget: float = BUDGET_S,
                      preview: Callable[..., dict] | None = None) -> tuple[dict[str, Any], str | None]:
    """The material map, or a partial one when the scan fails or runs out of time: (map, why it degraded)."""
    from kernel import material

    run = preview or material.preview
    exclude = list(exclude)
    out: dict[str, Any] = {}

    def work() -> None:
        try:
            out["map"] = run(folder, exclude)
        except Exception as exc:  # noqa: BLE001 - any failure degrades the scan; it never fails the flow
            out["error"] = exc
    t = threading.Thread(target=work, name="scan", daemon=True)
    t.start()
    t.join(budget)
    if "map" in out:
        return out["map"], None
    exc = out.get("error")
    if isinstance(exc, ValueError) and "is not a folder" in str(exc):
        raise exc
    why = (f"it took longer than {budget:.0f} s" if exc is None else
           f"{type(exc).__name__}: {inc.mask_text(exc, 200)}")
    return degraded_map(folder, exclude, why), why


def job_incident(factory: Any, job: dict[str, Any], view: dict[str, Any]) -> dict[str, Any] | None:
    """An incident for a job that failed or was lost, once per job (``job['incident']`` keeps its id)."""
    if job.get("incident") or view.get("state") not in ("failed", "unknown"):
        return None
    tail = list(view.get("log_tail") or [])[-15:]
    last = next((x for x in reversed(tail) if x.strip()), "")
    kind = "job_failed" if view["state"] == "failed" else "job_lost"
    message = last if kind == "job_failed" else "the job is unknown to the runner: lost on a restart"
    pid = job.get("project")
    try:
        doc = inc.open_incident(factory, kind=kind, where=f"job:{job.get('kind')}", message=message,
                                error_class=f"exit {view.get('code')}" if view.get("code") is not None else "",
                                project=None if pid == "_factory" else pid, by="the job runner", context={
                                    "job": {"id": job.get("id"), "kind": job.get("kind"), "state": view["state"],
                                            "code": view.get("code"), "args": job.get("args"), "log_tail": tail},
                                    "persona": (job.get("by") or {}).get("persona")})
    except (KeyError, inc.IncidentRefused, OSError):
        return None
    job["incident"] = doc["id"]
    return doc
