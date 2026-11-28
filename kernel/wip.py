"""Work in progress (FR-WIP1): what a project's own working copy holds that is not committed yet.

The owner (2026-11-27), of a game project with 1,356 uncommitted files: "rihmasto cannot actually trace project beyond
latest commit sounds not robust". Rihmasto reads a project's commits; this reads the working copy beside them, so a
person sees what they are in the middle of and is nudged, never blocked, to commit what Rihmasto cannot read yet.

Only metadata, with git and the file system, and only on this machine: the branch, how far it is ahead of or behind
its remote branch, when the last commit was made, how many files are modified, added, deleted, renamed, conflicted or
untracked (what ``.gitignore`` hides is left out) grouped by top-level area, and when the oldest of those changes was
made (a file's modification time). No file's contents are ever read, and nothing is written: git runs with
``--no-optional-locks`` (it refreshes no index), without hooks or fsmonitor (kernel/git_guard.py), and within
``TIMEOUT`` seconds. A project whose upstream is not a working copy here (a remote address, a folder that is gone or
is not git) is "not measured", with why.

=================  =================================================================================================
``working_copy``   the folder a project's work in progress is read from, or why there is none
``read``           the reading: branch, ahead/behind, last commit, counts by kind and by area, the oldest change, the
                   nudge and the sentence that says it (cached ``CACHE_S`` seconds per folder)
``step``           Start here's step when the work in progress is large or old (kernel/start_here.py)
=================  =================================================================================================
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from kernel import git_guard

TIMEOUT = 20          # seconds for one git call: a huge working copy says "not measured", never hangs a page
CACHE_S = 60          # a reading is reused this long per folder, so the Overview, Start here and Ask Rihma agree
LARGE = 50            # this many changed files is a lot to leave uncommitted: Start here nudges
OLD_DAYS = 2          # a change older than this is old enough to nudge about, however small
MAX_STAT = 20000      # files whose modification time is looked at, at most (the oldest change)
SHOWN_AREAS = 5       # areas named in the sentence; the rest are counted
PILE = 50             # an area with this many untracked files and almost nothing else changed looks generated
PILE_SHARE = 0.9      # ... when this share of its changes are untracked files: "add it to .gitignore if it is"
KINDS = ("modified", "added", "deleted", "renamed", "conflicted", "untracked")
TOP = "(top level)"   # the area of a file in the working copy's root

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def working_copy(project: Any) -> tuple[Path | None, str | None]:
    """The folder the project's work in progress is read from, or None and why it has none."""
    kind = project.meta.get("source_kind")
    if kind == "attached":
        repo = (project.meta.get("attached") or {}).get("repo")
        path = Path(repo) if repo else None
    elif kind == "adopted":
        adopted = project.read("adopted.json", {}) or {}
        if adopted.get("source_kind") not in (None, "path"):
            return None, ("it was adopted from a remote address, so there is no working copy on this machine to read; "
                          "adopt it from a folder here to see its work in progress")
        src = adopted.get("source") or project.meta.get("upstream")
        path = Path(src) if src else None
    else:
        return None, "it has no repository of its own: work in progress is read from an adopted or attached project"
    if path is None:
        return None, "no folder was recorded for its repository"
    if not path.is_dir():
        return None, f"its folder {path} is not there on this machine"
    if not (path / ".git").exists():
        return None, f"its folder {path} is not a git working copy"
    return path, None


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "--no-optional-locks", *git_guard.flags(), *args], cwd=repo, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=TIMEOUT, check=False, env={**os.environ, **git_guard.env()})


def _kind(entry: str) -> str:
    """The kind of change a porcelain v2 entry is (``1 XY ...``, ``2 XY ...``, ``u XY ...``, ``? path``)."""
    tag = entry[:1]
    if tag == "?":
        return "untracked"
    if tag == "u":
        return "conflicted"
    if tag == "2":
        return "renamed"
    xy = entry[2:4]
    if "D" in xy:
        return "deleted"
    if xy[:1] == "A":
        return "added"
    return "modified"


def _path(entry: str) -> str:
    """The path a porcelain v2 entry names (the last field; a path may hold spaces)."""
    if entry[:1] == "?":
        return entry[2:]
    fields = {"1": 8, "2": 9, "u": 10}[entry[:1]]
    return entry.split(" ", fields)[-1]


def _status(repo: Path) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """The branch headers and each changed path with its kind, from ``git status --porcelain=v2 -z``."""
    proc = _git(repo, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all")
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr.decode("utf-8", "replace").strip().splitlines() or ["git status failed"])[-1])
    heads: dict[str, str] = {}
    changes: list[tuple[str, str]] = []
    parts = proc.stdout.decode("utf-8", "surrogateescape").split("\0")
    skip = False
    for entry in parts:
        if skip:                      # a rename's second field is the path it came from
            skip = False
            continue
        if not entry:
            continue
        if entry.startswith("# "):
            key, _, value = entry[2:].partition(" ")
            heads[key] = value
        elif entry[:1] in "12u?":
            changes.append((_kind(entry), _path(entry)))
            skip = entry[:1] == "2"
    return heads, changes


def _areas(changes: list[tuple[str, str]]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for kind, path in changes:
        area = path.split("/", 1)[0] if "/" in path else TOP
        row = by.setdefault(area, {"area": area, "total": 0, **{k: 0 for k in KINDS}})
        row[kind] += 1
        row["total"] += 1
    return sorted(by.values(), key=lambda r: (-r["total"], r["area"]))


def _piles(areas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Areas that are mostly a pile of untracked files (build output, generated assets, caches): likely not work to
    commit but something .gitignore should hide."""
    return [{"area": a["area"], "untracked": a["untracked"]} for a in areas
            if a["area"] != TOP and a["untracked"] >= PILE and a["untracked"] >= PILE_SHARE * a["total"]]


def _oldest(repo: Path, changes: list[tuple[str, str]]) -> float | None:
    """The oldest modification time among the changed files still there (no contents read)."""
    oldest = None
    for _, path in [c for c in changes if c[0] != "deleted"][:MAX_STAT]:
        try:
            m = (repo / path).stat().st_mtime
        except OSError:
            continue
        oldest = m if oldest is None or m < oldest else oldest
    return oldest


def _ago(seconds: float | None) -> str:
    if seconds is None:
        return "an unknown time ago"
    s = max(0, int(seconds))
    for size, one in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size:
            n = s // size
            return f"{n} {one}{'' if n == 1 else 's'} ago"
    return "just now"


def _iso(epoch: float | None) -> str | None:
    return None if epoch is None else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _where(r: dict[str, Any]) -> str:
    """"; the last commit was 2 hours ago on main, 3 ahead and 0 behind origin/main" (or level with it)."""
    branch = f"on {r['branch']}" if r.get("branch") else "on a detached commit"
    last = f"; the last commit was {_ago(r['last_commit_age_s'])} {branch}" if r.get("last_commit_at") else f" {branch}"
    if not r.get("tracking"):
        return last
    if r["ahead"] or r["behind"]:
        return f"{last}, {r['ahead']} ahead and {r['behind']} behind {r['tracking']}"
    return f"{last}, level with {r['tracking']}"


def _work_said(r: dict[str, Any]) -> str:
    work: dict[str, int] = r["work"]
    piled = {p["area"] for p in r["piles"]}
    worked = [a["area"] for a in r["areas"] if a["area"] not in piled]
    named = ", ".join(worked[:SHOWN_AREAS])
    more = f" and {len(worked) - SHOWN_AREAS} more area(s)" if len(worked) > SHOWN_AREAS else ""
    kinds = ", ".join(f"{work[k]} {k}" for k in KINDS if work[k])
    files = "file" if work["total"] == 1 else "files"
    return (f"{work['total']} changed {files} not committed ({kinds}) across {named}{more}; the oldest change is "
            f"from {_ago(r['oldest_change_age_s'])}")


def _said(r: dict[str, Any]) -> str:
    if not r["changed"]["total"]:
        return f"Nothing uncommitted{_where(r)}."
    head = _work_said(r) if r["work"]["total"] else "No work to commit"
    said = f"{head}{_where(r)}."
    for p in r["piles"]:
        said += (f" {p['untracked']} untracked files in {p['area']}/ look generated: add {p['area']}/ to .gitignore "
                 "if they are, so they stop showing as work.")
    if r["nudge"]:
        said += " Rihmasto reads committed work only: commit what is ready so it reads it."
    return said


def _not_measured(base: dict[str, Any], why: str) -> dict[str, Any]:
    return base | {"measured": False, "why": why, "said": f"Work in progress is not measured: {why}."}


def _counts(changes: list[tuple[str, str]]) -> dict[str, int]:
    return {k: sum(1 for c in changes if c[0] == k) for k in KINDS} | {"total": len(changes)}


def _branch(heads: dict[str, str]) -> dict[str, Any]:
    """The branch, the remote branch it tracks and how far ahead of and behind it, from status's headers."""
    head = heads.get("branch.head")
    ahead = behind = 0
    if heads.get("branch.ab"):
        a, b = (heads["branch.ab"].split() + ["+0", "-0"])[:2]
        ahead, behind = abs(int(a)), abs(int(b))
    return {"branch": None if head in (None, "(detached)") else head, "tracking": heads.get("branch.upstream"),
            "ahead": ahead, "behind": behind}


def _reading(repo: Path, heads: dict[str, str], changes: list[tuple[str, str]], last: int | None,
             now: float) -> dict[str, Any]:
    areas = _areas(changes)
    piles = _piles(areas)
    piled = {p["area"] for p in piles}
    work_changes = [c for c in changes if not (c[0] == "untracked" and c[1].split("/", 1)[0] in piled)]
    work = _counts(work_changes)
    oldest = _oldest(repo, work_changes)
    age = None if oldest is None else max(0.0, now - oldest)
    r: dict[str, Any] = {
        "measured": True, "why": None, "path": str(repo), **_branch(heads), "last_commit_at": _iso(last),
        "last_commit_age_s": None if last is None else max(0.0, now - last), "changed": _counts(changes),
        "work": work, "areas": areas, "piles": piles, "oldest_change_at": _iso(oldest), "oldest_change_age_s": age}
    old = age is not None and age >= OLD_DAYS * 86400
    r["nudge"] = bool(work["total"]) and (work["total"] >= LARGE or old)
    r["said"] = _said(r)
    return r


def _last_commit(repo: Path) -> int | None:
    log = _git(repo, "log", "-1", "--format=%ct")
    out = log.stdout.strip()
    return int(out) if log.returncode == 0 and out.isdigit() else None


def read(project: Any, *, now: float | None = None, fresh: bool = False) -> dict[str, Any]:
    """The project's work in progress, or "not measured" with why. Read-only; nothing is recorded."""
    now = time.time() if now is None else now
    base = {"project": project.pid, "at": _iso(now),
            "applies": project.meta.get("source_kind") in ("adopted", "attached")}
    repo, why = working_copy(project)
    if repo is None:
        return _not_measured(base, why or "no working copy")
    key = str(repo.resolve())
    hit = _cache.get(key)
    if hit and not fresh and now - hit[0] < CACHE_S:
        return hit[1] | base
    try:
        heads, changes = _status(repo)
        last = _last_commit(repo)
    except subprocess.TimeoutExpired:
        return _not_measured(base, f"git took longer than {TIMEOUT} seconds to list the working copy's changes")
    except (OSError, RuntimeError) as e:
        return _not_measured(base, f"git could not read the working copy ({e})")
    r = _reading(repo, heads, changes, last, now)
    _cache[key] = (now, r)
    return r | base


def step(project: Any) -> dict[str, Any] | None:
    """Start here's nudge when the work in progress is large or old; None otherwise (never a blocker)."""
    if project.meta.get("source_kind") not in ("adopted", "attached"):
        return None
    r = read(project)
    if not r.get("measured") or not r.get("nudge"):
        return None
    total = r["work"]["total"]
    piled = {p["area"] for p in r["piles"]}
    names = [a["area"] for a in r["areas"] if a["area"] not in piled]
    areas = ", ".join(names[:3]) + (", and more" if len(names) > 3 else "")
    return {"id": "commit_work", "label": f"Commit your work in progress ({total} file{'s' if total != 1 else ''})",
            "why": f"{total} changed file{'s' if total != 1 else ''} across {areas}, the oldest from "
                   f"{_ago(r['oldest_change_age_s'])}: Rihmasto reads committed work only, so commit what is ready "
                   "and it reads it",
            "route": f"#/p/{project.pid}/overview", "control": "wip_card"}
