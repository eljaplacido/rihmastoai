"""Any folder as an existing project (docs/brownfield.md, Any folder).

kernel/adopt.py adopts a git repository. A folder that is not one is first **snapshotted** here: the files
that pass the scan's skip rules (kernel/material.py: no dependencies, caches or build output, nothing that
may hold secrets, nothing the person excluded) are copied into a new git repository under the factory home
(``snapshots/``) and committed as the baseline. The person's folder is never changed. That repository is
then adopted like any other, and stays the upstream a later sync reads; a changed folder is adopted again.

A folder that holds no code at all, only documents, is not adopted: it is material for a new project, and
the refusal says so. Either way the folder's documents are scanned as context for the panel and the coming
assessment, kept in the project (material.json and material.md) with a ledger record of the counts.
"""

from __future__ import annotations

import secrets
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from kernel import material
from kernel.store import slugify, write_text

SNAPSHOTS = "snapshots"
NO_CODE = ("{folder} holds no code, only documents: there is nothing to adopt. Start a new project from it "
           "instead (New project, A need or a spec, with the folder as the material; or `rihmasto new \"Title\" "
           "--source {folder}`)")
BASELINE = "Baseline snapshot of {folder}: a folder that is not a git repository (the folder is never changed)"


class NoCode(ValueError):
    """The folder holds only documents."""


def is_git(folder: str | Path) -> bool:
    proc = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=folder, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, check=False)
    return proc.returncode == 0


def check_code(folder: str | Path, exclude: Iterable[str] = (), *, tree: Any = None) -> dict[str, Any]:
    """The folder's map, when it holds code; NoCode when it holds only documents."""
    mp = material.scan(folder, exclude, tree=tree)
    if not material.has_code(mp):
        raise NoCode(NO_CODE.format(folder=Path(folder)))
    return mp


def _git(cwd: Path, *args: str) -> str:
    from kernel.lanes import _git as kernel_git

    return kernel_git(cwd, "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", *args)


def snapshot(home: Path, folder: str, exclude: Iterable[str] = (), *, documents: bool = False
             ) -> tuple[str, dict[str, Any]]:
    """Copy what passes the scan's rules into a new repository under ``home``/snapshots and commit it as the
    baseline. Returns the repository's path and what was taken. NoCode when the folder holds no code, unless
    ``documents``: a folder of documents adopted to track and evaluate the work (FR-RPJ1)."""
    from kernel.lanes import GIT_ID
    from kernel.material_git import WorkTree, is_repo_root

    src = Path(folder).resolve()
    # A git repository's working copy is taken as git sees it: what its .gitignore keeps out is never copied.
    tree = WorkTree(src) if is_repo_root(src) else None
    mp = material.scan(src, exclude, tree=tree) if documents else check_code(src, exclude, tree=tree)
    if not any(r["action"] != "skipped" and not r.get("archive") for r in mp["files"]):
        raise NoCode(f"{src} holds nothing to take: every file is skipped")
    dest = home / SNAPSHOTS / f"{slugify(src.name) or 'folder'}-{secrets.token_hex(3)}"
    dest.mkdir(parents=True)
    try:
        _git(dest, "init", "-q", "-b", "main")
        copied = 0
        for row in mp["files"]:
            if row["action"] == "skipped" or row.get("archive"):   # an archive's entries travel inside it
                continue
            target = dest / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / row["path"], target)
            copied += 1
        _git(dest, "add", "-A", "-f")
        _git(dest, *GIT_ID, "commit", "-q", "--no-verify", "-m", BASELINE.format(folder=src.as_posix()))
        revision = _git(dest, "rev-parse", "HEAD")
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    t = mp["totals"]
    return str(dest), {"from": src.as_posix(), "repository": dest.as_posix(), "revision": revision,
                       "copied": copied, "skipped": t["skipped"], "secrets": t["secrets"], "excluded": t["excluded"],
                       "not_looked_at": mp["not_looked_at"], "skipped_dirs": len(mp["skipped_dirs"])}


def context(checkout: Path, exclude: Iterable[str] = ()) -> tuple[dict[str, Any], str]:
    """The documents of an adopted checkout, scanned: the map and the text built from it."""
    mp, text, _ = material.gather(checkout, exclude)
    return mp, text


def hold(project: Any, taken: dict[str, Any], *, person: str, persona: str, confidential: bool) -> None:
    """Record what adoption scanned and snapshotted, and the confidential setting, in the project."""
    from kernel.confidential import mark

    snap = taken.get("snapshot")
    if snap:
        project.log("snapshot_taken", {**snap, "person": person, "persona": persona,
                                       "why": "the folder is not a git repository: its files that pass the scan's "
                                              "rules are the baseline; the folder itself is never changed"})
    mp, text = taken.get("material") or (None, "")
    if mp is not None:
        mp = {**mp, "folder": snap["from"] if snap else mp["folder"], "for": "context for the panel and the "
              "coming assessment; nothing was sent to a model"}
        material.record(project, mp, person=person, persona=persona, confirmed="adopted: scanned, not sent")
        write_text(project.path("material.md"), text + "\n" if text else "")
        if mp.get("agent_context"):           # how the team's AI tools are set up (kernel/agent_context.py)
            from kernel.ide import record

            record(project, mp["agent_context"], at=taken.get("baseline") or "")
    if confidential:
        mark(project, person=person, persona=persona)
