"""``git clone`` options for a clone of the factory's own repository of a project (FR-RPJ1).

Kept in the clone for every later checkout there too (a person's terminal, the gate's worktree):

- a Git LFS file stays its pointer file. The factory's ``repo.git`` holds no LFS object (adoption never
  downloads LFS content, kernel/adopt.py), so a smudge there can only fail, and a failed smudge fails the
  whole checkout of a repository that uses LFS: the console, a workspace and a lane would never open.
  Nothing is added when git-lfs is not set up on this machine;
- on Windows, paths longer than 260 characters check out (``core.longpaths``): a game's or a monorepo's
  deep folders under a workspace's own folder.
"""

from __future__ import annotations

import os
import subprocess

_LFS_CONFIGURED: list[bool] = []
LFS_SKIP = ["-c", "filter.lfs.smudge=git-lfs smudge --skip -- %f",
            "-c", "filter.lfs.process=git-lfs filter-process --skip"]


def lfs_configured() -> bool:
    """Whether git-lfs is set up for this machine's git (asked once)."""
    if not _LFS_CONFIGURED:
        proc = subprocess.run(["git", "config", "--get", "filter.lfs.process"], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, check=False)
        _LFS_CONFIGURED.append(proc.returncode == 0 and bool(proc.stdout.strip()))
    return _LFS_CONFIGURED[0]


def clone_options() -> list[str]:
    """The options, as ``-c name=value`` pairs to put before the clone's source."""
    out = ["-c", "core.longpaths=true"] if os.name == "nt" else []
    return out + (LFS_SKIP if lfs_configured() else [])
