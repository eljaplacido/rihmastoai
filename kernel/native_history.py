"""A project's own sources against its history (FR-SRC2): real commits, and the latest revision fetched first.

- **Commits to the code.** The old-plan rule (kernel/native_detect.py ``staleness``) counts the commits that touched
  code after a planning document's last change, from ``git log`` over the code's paths at the revision read: a
  team that changes the same two files twenty times has twenty commits, not two. A folder that is not a git
  revision falls back to each code file's last commit (a lower bound), as before.
- **Fetch, then read.** An adopted project's sources are read from its upstream as last fetched; Read again (and a
  daily or weekly read) fetches the upstream first, so a commit pushed since is read, and says whether it moved or
  why it could not fetch. Nothing is merged and main is not moved: the watch's sync still opens its Review card.
- **Paths.** The repository a run clones is an absolute path, whatever folder the cockpit was started in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_COMMITS = 5000


def _code_specs() -> list[str]:
    from kernel.repo_structure import CODE_EXT

    return [f":(glob)**/*{ext}" for ext in CODE_EXT]


def code_commit_times(src: Any) -> list[int] | None:
    """Every commit's time that touched code at the revision read, newest first; None when it is not a git revision.
    Kept on the source, so one read asks git once."""
    have = getattr(src, "_code_commit_times", None)
    if have is not None:
        return have
    repo, rev = getattr(src, "repo", None), getattr(src, "revision", None)
    if repo is None or not rev:
        return None
    from kernel.repo_structure import _git

    raw = _git(Path(repo), "log", "-n", str(MAX_COMMITS), "--format=%ct", rev, "--", *_code_specs())
    times = sorted((int(x) for x in raw.decode("utf-8", "replace").split() if x.isdigit()), reverse=True)
    if not times:                    # git said nothing (no code, or it could not read): the files' dates decide
        return None
    src._code_commit_times = times
    return times


def absolute(path: Path | str) -> Path:
    """The repository's path, absolute: a cockpit started with a relative --home still clones it."""
    return Path(path).resolve()


def upstream_ref(project: Any) -> str:
    """The upstream branch an adopted project tracks, as adoption recorded it (``default_branch``)."""
    adopted = project.read("adopted.json", {}) or {}
    return f"refs/remotes/upstream/{adopted.get('default_branch') or adopted.get('branch') or 'main'}"


def fetch(project: Any, *, timeout: int = 120) -> dict[str, Any]:
    """Fetch an adopted project's upstream before its sources are read: whether it moved, or why it could not.
    An attached repository is read where it is: nothing to fetch."""
    from kernel import adopt
    from kernel.repo_structure import _git

    if project.meta.get("source_kind") != "adopted" or not project.path("repo.git").exists():
        return {"fetched": False, "moved": False, "why": None,
                "line": "read from the attached repository's latest commit"}
    bare, ref = absolute(project.path("repo.git")), upstream_ref(project)

    def head() -> str:
        return _git(bare, "rev-parse", "--verify", "-q", ref + "^{commit}").decode().strip()

    before = head()
    try:
        adopt._net(bare, "fetch", "-q", "--prune", "upstream", timeout=timeout)
    except RuntimeError as exc:
        why = str(exc)[:300]
        project.log("native_sources_fetch_failed", {"error": why})
        return {"fetched": False, "moved": False, "why": why,
                "line": f"the upstream could not be fetched ({why}): read from the revision fetched before"}
    after = head()
    moved = bool(after and after != before)
    return {"fetched": True, "moved": moved, "why": None, "revision": after[:12] or None,
            "line": (f"fetched the upstream: it moved to {after[:12]}, read from there" if moved
                     else "fetched the upstream: no new commit since the last fetch")}
