"""A folder's git side, for the scan and the New project dialog (docs/brownfield.md, Uncommitted work and
Workspaces).

- **The last commit, scanned.** Adopting a git repository adopts its last commit, never the files beside it.
  `GitTree` lets kernel/material.py scan exactly that: the committed files and their committed contents
  (a file changed since is read from git, an unchanged one from disk), so the scan's numbers are the
  adoption's.
- **Uncommitted work.** `working_changes` counts the changes that are not in the last commit and the
  untracked files (ignored files are not counted): the dialog says they will not be included, and offers
  the working copy as it is now instead.
- **Where it came from.** `origin` is the repository's origin address with any user or token taken out, so
  the same repository is known again when it is cloned twice (kernel/adopt_seen.py).
- **Workspaces.** `workspace` finds the git repositories a folder holds (to two levels), with their commits
  and uncommitted counts, and the copies beside them (``_snapshot``, ``-copy``, ``-experiment``, ``-prep``
  and the like, kernel.material_kinds.COPY).

Every git call here reads: it never fetches, never writes the repository and never asks for a credential.
"""

from __future__ import annotations

import io
import os
import subprocess
import urllib.parse
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import IO, Any

from kernel import material_kinds as mk

MAX_REPOS = 40
_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "GCM_INTERACTIVE": "never", "GIT_OPTIONAL_LOCKS": "0"}


def git(cwd: Path, *args: str, timeout: int = 120) -> str | None:
    """A read-only git call's output, or None when git fails (or is missing)."""
    try:
        proc = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=cwd, capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=timeout, check=False,
                              env={**os.environ, **_ENV})
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None


def is_repo_root(folder: Path) -> bool:
    """Whether ``folder`` is the top of a git repository (not a folder inside one)."""
    return (folder / ".git").exists()


def head(folder: Path) -> str | None:
    out = git(folder, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    return out.strip() if out else None


def working_changes(folder: Path) -> dict[str, int]:
    """The changes not in the last commit: tracked files changed (staged or not) and untracked files."""
    out = git(folder, "status", "--porcelain=v1", "-z", "--untracked-files=all") or ""
    changed = untracked = 0
    for item in out.split("\0"):
        if len(item) < 3:
            continue
        if item.startswith("??"):
            untracked += 1
        elif item[:2] != "!!":
            changed += 1
    return {"uncommitted": changed, "untracked": untracked}


def _clean_url(url: str) -> str:
    """An address without its user, password, query or fragment, lower-cased host, no trailing .git or /."""
    text = url.strip()
    if "://" in text:
        parts = urllib.parse.urlsplit(text)
        host = (parts.hostname or "").lower() + (f":{parts.port}" if parts.port else "")
        text = f"{parts.scheme.lower()}://{host}{parts.path}"
    elif "@" in text.split(":", 1)[0]:                  # git@host:org/repo
        text = text.split("@", 1)[1]
    text = text.rstrip("/")
    return text[:-4] if text.lower().endswith(".git") else text


def same_origin_key(url: str | None) -> str | None:
    """A key two addresses of one repository share: host and path, whatever the scheme."""
    if not url:
        return None
    text = _clean_url(url)
    text = text.split("://", 1)[1] if "://" in text else text.replace(":", "/", 1)
    return text.lower() or None


def origin(folder: Path) -> str | None:
    """The repository's origin address, credentials taken out; None when it has none."""
    out = git(folder, "config", "--get", "remote.origin.url")
    return _clean_url(out) if out and out.strip() else None


class GitTree:
    """A repository's last commit as kernel/material.py walks a folder: its files and their committed text."""

    def __init__(self, root: Path, rev: str = "HEAD") -> None:
        self.root = root
        self.rev = rev
        listing = git(root, "ls-tree", "-r", "-z", "--long", "--full-tree", rev, timeout=300)
        if listing is None:
            raise ValueError(f"{root} has no commit to scan")
        self.entries: dict[str, tuple[str, str, int]] = {}
        for item in listing.split("\0"):
            if "\t" not in item:
                continue
            meta, path = item.split("\t", 1)
            mode, kind, sha, size = meta.split()
            self.entries[path] = (mode, sha, int(size) if size.isdigit() else 0)
        diff = git(root, "diff", "--name-only", "-z", rev) or ""
        self.changed = {p for p in diff.split("\0") if p}
        # A person's own AI tool settings (CLAUDE.local.md, .claude/settings.local.json) are ignored by git, so the
        # commit does not hold them; they are still said, as skipped and never read (kernel/agent_context.py).
        from kernel.agent_context import sub_kind

        ignored = git(root, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory") or ""
        self.personal = {p for p in ignored.split("\0") if p and sub_kind(p) == "personal"}

    def walk(self, patterns: list[str], progress: Any, excluded: Any, max_files: int
             ) -> tuple[list[str], list[dict[str, Any]], int]:
        files: list[str] = []
        dirs: dict[str, str] = {}
        more = 0
        for path in sorted({*self.entries, *self.personal}):
            mode = self.entries[path][0] if path in self.entries else "100644"
            parts = PurePosixPath(path).parts
            why = None
            for i in range(len(parts) - 1):
                folder = "/".join(parts[:i + 1])
                if folder + "/" in dirs:
                    why = "seen"
                    break
                pat = excluded(folder, patterns)
                why = f"excluded by you ({pat})" if pat else mk.skipped_dir(parts[i], False)
                if why:
                    dirs[folder + "/"] = why
                    break
            if why:
                continue
            if mode == "160000":
                dirs[path + "/"] = "a submodule: its own repository, not walked"
                continue
            if mode == "120000":
                continue                                  # a link is never followed
            if progress is not None:
                progress.seen(str(PurePosixPath(path).parent))
            if len(files) >= max_files:
                more += 1
            else:
                files.append(path)
        return files, [{"path": k, "why": v} for k, v in dirs.items()], more

    def size(self, rel: str) -> int:
        return self.entries[rel][2] if rel in self.entries else (self.root / rel).stat().st_size

    def _disk(self, rel: str) -> Path | None:
        path = self.root / rel
        return path if rel not in self.changed and path.is_file() and not path.is_symlink() else None

    def read(self, rel: str) -> bytes:
        disk = self._disk(rel)
        if disk is not None:
            return disk.read_bytes()
        try:
            proc = subprocess.run(["git", "cat-file", "blob", self.entries[rel][1]], cwd=self.root,
                                  capture_output=True, stdin=subprocess.DEVNULL, timeout=120, check=True,
                                  env={**os.environ, **_ENV})
        except (OSError, subprocess.SubprocessError) as exc:
            raise OSError(f"git could not read {rel}") from exc
        return proc.stdout

    def open(self, rel: str) -> IO[bytes]:
        disk = self._disk(rel)
        return disk.open("rb") if disk is not None else io.BytesIO(self.read(rel))


# -- workspaces ------------------------------------------------------------------------------------------

def _children(folder: Path, depth: int) -> Iterator[Path]:
    try:
        kids = sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink())
    except OSError:
        return
    for kid in kids:
        if kid.name == ".git" or mk.skipped_dir(kid.name, (kid / "pyvenv.cfg").is_file()):
            continue
        yield kid
        if depth > 1 and not is_repo_root(kid):
            yield from _children(kid, depth - 1)


def is_copy(rel: str) -> bool:
    """Whether a path sits in a folder named like a copy of another (``x_snapshot``, ``x-copy``, ``x-prep``)."""
    return any(mk.COPY.fullmatch(part) for part in PurePosixPath(rel).parts[:-1])


def _repo_view(root: Path, repo: Path) -> dict[str, Any]:
    rel = repo.relative_to(root).as_posix()
    commits = git(repo, "rev-list", "--count", "HEAD")
    last = git(repo, "log", "-1", "--format=%cI")
    return {"path": rel, "folder": str(repo), "commits": int(commits) if commits and commits.strip().isdigit() else 0,
            "last_commit": last.strip() if last else None, "origin": origin(repo), **working_changes(repo),
            "copy": bool(mk.COPY.fullmatch(repo.name))}


def workspace(root: Path) -> dict[str, Any] | None:
    """The git repositories ``root`` holds (to two levels) and the copies beside them, or None when it is a
    repository itself or holds none."""
    if is_repo_root(root):
        return None
    repos: list[dict[str, Any]] = []
    copies: list[str] = []
    for kid in _children(root, 2):
        rel = kid.relative_to(root).as_posix()
        if is_repo_root(kid) and len(repos) < MAX_REPOS:
            repos.append(_repo_view(root, kid))
        elif mk.COPY.fullmatch(kid.name) and not any(rel.startswith(c + "/") for c in copies):
            copies.append(rel)
    if not repos:
        return None
    _copies_of(repos)
    return {"repositories": repos, "copies": copies,
            "several": len([r for r in repos if not r["copy"]]) > 1 or bool(copies) or any(r["copy"] for r in repos)}


def _copies_of(repos: list[dict[str, Any]]) -> None:
    """Name the repository each copy-named one copies (``app_snapshot`` of ``app``), when it is there."""
    names = {PurePosixPath(r["path"]).name.lower(): r["path"] for r in repos if not r["copy"]}
    for r in repos:
        base = mk.COPY_BASE.sub("", PurePosixPath(r["path"]).name).lower()
        r["copy_of"] = names.get(base) if r["copy"] and names.get(base) != r["path"] else None
