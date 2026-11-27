"""Where a project's Gnomon files are, and what they declare (FR-GNP1).

The files read are `.gnomon/config.toml` and `.gnomon/policy.toml`, each at most 256 KB, parsed as TOML; of the
rest of `.gnomon/` only the names of its folders are looked at (``skills``, ``trials``, ``loops``). They are read
from the project's local working copy when it has one (an attached repository's folder, or the folder an adopted
project came from), else from the main branch of Rihmasto's own copy of the repository. No other file is opened,
nothing is run in the repository and nothing is written.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any

FILES = ("config.toml", "policy.toml")
FOLDERS = ("skills", "trials", "loops")
MAX_BYTES = 256 * 1024


def _git(cwd: Path, *args: str) -> str:
    """git's answer in ``cwd``, or "" (no hooks, nothing prompted, nothing fetched)."""
    from kernel.agent_context import _git as safe_git

    try:
        return safe_git(cwd, *args).decode("utf-8", "replace")
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        return ""


def where(project: Any) -> dict[str, Any]:
    """The project's working copy folder, its repository copy, and what kind of project it is."""
    kind = project.meta.get("source_kind")
    folder: Path | None = None
    if kind == "attached":
        repo = (project.meta.get("attached") or {}).get("repo")
        folder = Path(repo) if repo else None
    elif kind == "adopted":
        source = str(project.meta.get("upstream") or "")
        folder = Path(source) if source and "://" not in source and not source.startswith("git@") else None
    bare = project.path("repo.git")
    return {"kind": kind, "folder": folder if folder is not None and folder.is_dir() else None,
            "bare": bare if Path(bare).is_dir() else None}


def _parse(text: str, name: str) -> tuple[dict[str, Any] | None, str | None]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        return None, f"{name} is larger than {MAX_BYTES // 1024} KB, so it was not read"
    try:
        return tomllib.loads(text), None
    except tomllib.TOMLDecodeError as exc:
        return None, f"{name} is not TOML Rihmasto can read ({exc})"


def _from_folder(folder: Path) -> dict[str, Any] | None:
    root = folder / ".gnomon"
    if not root.is_dir():
        return None
    out: dict[str, Any] = {"source": "folder", "at": str(folder), "files": {}, "problems": [], "folders": []}
    for name in FILES:
        path = root / name
        if path.is_file():
            parsed, problem = _parse(path.read_text(encoding="utf-8", errors="replace"), name)
            out["files"][name] = parsed
            if problem:
                out["problems"].append(problem)
    out["folders"] = [n for n in FOLDERS if (root / n).is_dir()]
    return out


def _from_bare(bare: Path) -> dict[str, Any] | None:
    listed = set(_git(bare, "ls-tree", "--name-only", "main", ".gnomon/").splitlines())
    if not listed:
        return None
    out: dict[str, Any] = {"source": "repository", "at": "main of Rihmasto's copy of the repository", "files": {},
                           "problems": [], "folders": [n for n in FOLDERS if f".gnomon/{n}" in listed]}
    for name in FILES:
        if f".gnomon/{name}" in listed:
            parsed, problem = _parse(_git(bare, "show", f"main:.gnomon/{name}"), name)
            out["files"][name] = parsed
            if problem:
                out["problems"].append(problem)
    return out


def read(project: Any) -> dict[str, Any]:
    """What the project's Gnomon files declare: ``found`` False with ``why`` when there are none to read."""
    w = where(project)
    if w["folder"] is None and w["bare"] is None:
        return {"found": False, "why": "this project has no local working copy and no repository Rihmasto holds"}
    got = (_from_folder(w["folder"]) if w["folder"] is not None else None) or (
        _from_bare(w["bare"]) if w["bare"] is not None else None)
    if got is None:
        place = w["folder"] or "the repository"
        return {"found": False, "why": f"there is no .gnomon folder in {place}: Gnomon is not set up for this "
                                       "project yet", "folder": str(w["folder"]) if w["folder"] else None}
    got["found"] = True
    got["folder"] = str(w["folder"]) if w["folder"] else None
    return got
