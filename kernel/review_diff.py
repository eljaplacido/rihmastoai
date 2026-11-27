"""What a change touched, for the review (FR-REV1): diff stats and a short preview, read from git, never written.

A task a builder cell merged lives in the project's own repository (``repo.git``): its change runs from the
parent of its first round's commit to the revision that was merged. A commit gated from a developer's IDE
(kernel/gate_external.py) lives in their attached repository, from the base to the head the gate judged.
Both are read with ``git diff`` between two commits, which changes nothing in either repository. A revision
is a hexadecimal commit id or nothing is run: no name from a record ever reaches git as an option. When git
or a commit is missing, the stats say "not measured" and why, never zero.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

_SHA = re.compile(r"[0-9a-f]{7,64}\Z")
TIMEOUT = 15
MAX_DIFF_BYTES = 60_000
MAX_FILES = 200


def _git(where: list[str], *args: str) -> str | None:
    """git's output, or None when git is missing, fails or takes too long."""
    try:
        done = subprocess.run(["git", *where, *args], capture_output=True, timeout=TIMEOUT, check=False,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")


def _where(project: Any, repository: str | None) -> tuple[list[str] | None, str]:
    """git's first arguments for the repository a change lives in, or None and why not."""
    if repository:
        path = Path(repository)
        return (["-C", str(path)], "") if path.is_dir() else (None, "the attached repository is not on this machine")
    bare = project.path("repo.git")
    return (["--git-dir", str(bare)], "") if bare.is_dir() else (None, "the project has no repository yet")


def _revisions(base: str | None, head: str | None, parent_of_base: bool) -> tuple[str, str] | None:
    if not (isinstance(base, str) and isinstance(head, str) and _SHA.match(base) and _SHA.match(head)):
        return None
    return (base + "^" if parent_of_base else base), head


def _numstat(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        rows.append({"path": path, "added": int(added) if added.isdigit() else None,
                     "deleted": int(deleted) if deleted.isdigit() else None})
    return rows


def not_measured(why: str) -> dict[str, Any]:
    return {"measured": False, "why": why}


def change(project: Any, *, base: str | None, head: str | None, repository: str | None = None,
           parent_of_base: bool = False, preview: bool = False) -> dict[str, Any]:
    """The diff stats of ``base``..``head`` (the base's parent with ``parent_of_base``): files, lines added
    and deleted; with ``preview``, each file's own counts and the diff itself, cut at a size a person reads."""
    where, why = _where(project, repository)
    if where is None:
        return not_measured(why)
    revs = _revisions(base, head, parent_of_base)
    if revs is None:
        return not_measured("the record names no commit range")
    out = _git(where, "diff", "--numstat", "--no-renames", revs[0], revs[1], "--")
    if out is None:
        return not_measured("git could not read the change (git missing, or the commits are gone)")
    rows = _numstat(out)
    stats: dict[str, Any] = {"measured": True, "files": len(rows), "base": revs[0], "head": revs[1],
                             "added": sum(r["added"] or 0 for r in rows),
                             "deleted": sum(r["deleted"] or 0 for r in rows),
                             "binary": sum(1 for r in rows if r["added"] is None)}
    if not preview:
        return stats
    text = _git(where, "diff", "--no-color", "--no-ext-diff", "--no-renames", revs[0], revs[1], "--") or ""
    cut = len(text.encode("utf-8")) > MAX_DIFF_BYTES
    if cut:
        text = text.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore")
        text = text[:text.rfind("\n") + 1] if "\n" in text else text
    return stats | {"per_file": rows[:MAX_FILES], "diff": text, "cut": cut}
