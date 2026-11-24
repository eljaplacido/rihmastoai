"""The kernel's own git in a folder untrusted code could write: a lane after a cell, a checkout after a
suite (D-0016, FR-ID4).

With an isolation runner, a cell (a container that mounts its lane, or a separate account) and a suite run
by a separate account can write the lane's ``.git`` as well as its files. Git runs commands its repository
names: hooks (``.git/hooks``, or ``core.hooksPath``), ``core.fsmonitor``, filter, diff and merge drivers,
a signing program, the hooks of whatever repository a remote's address points to, and any of these from a
file the config includes. The kernel runs git there as the account that runs Rihmasto, so whatever ran
before it must not be able to choose what that git runs. Two layers:

- ``scrub(repo)`` before the kernel's git touches a folder untrusted code had: ``.git`` must be a real
  folder (not a link, not a ``gitdir:`` file pointing elsewhere); the config is rewritten from the few keys
  a clone sets (``KEPT``), every other key dropped, includes and worktree configs with them, and origin's
  address set back to the product repository when the caller knows it; every hook file is removed; a
  linked ``config``, ``hooks`` or ``info`` is unlinked rather than followed, and a ``commondir`` file
  (which would send git to another repository's config and hooks) is removed. What would make the
  kernel's git see other commits than the ones there are goes too: replace refs, ``info/grafts``, a
  ``shallow`` file and object alternates; origin's fetch refspec is git's default again.
- ``flags()`` and ``env()``: each kernel git call there also names an empty hooks folder of this process's
  own, and turns fsmonitor, signing, submodule recursion, a submodule's dirty check, replace refs and
  grafts off, so a hook or a setting planted between two scrubs, or in a submodule's own config, does not
  run either.
- ``nested(repo)``: a repository inside the lane (a ``.git`` below its top, or a gitlink in its index or
  HEAD) carries a config of its own that git would run if it looked inside, and survives ``clean -fdx``.
  The kernel refuses a lane's work that holds one (``refuse_nested``) and removes it before the next
  checkout (``unnest``).

``Tampered`` is raised when ``.git`` is not a folder the kernel can trust; a lane's checkout clones anew.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

# The keys a clone writes (and the kernel's own checkout sets); anything else in a lane's config is dropped.
KEPT = re.compile(r"core\.(repositoryformatversion|filemode|bare|logallrefupdates|symlinks|ignorecase"
                  r"|precomposeunicode|autocrlf)|extensions\.(objectformat|refstorage)"
                  r"|remote\.origin\.(url|fetch)|branch\..+\.(remote|merge)", re.IGNORECASE | re.DOTALL)
_HOOKS: list[str] = []
_GRAFTS: list[str] = []
DEFAULT_FETCH = "+refs/heads/*:refs/remotes/origin/*"
GITLINK = b"160000 "
# What a cell could leave in .git to change which commits the kernel's git sees (a clone has none of them).
SEEN_AS_OTHER = ("info/grafts", "shallow", "objects/info/alternates", "objects/info/http-alternates")


class Tampered(RuntimeError):
    """A folder's ``.git`` is not one the kernel can run git in: untrusted code replaced it."""


def _no_hooks() -> str:
    """An empty folder this process made (0700): no cell or separate account can put a hook in it."""
    if not _HOOKS or not os.path.isdir(_HOOKS[0]):
        _HOOKS[:] = [tempfile.mkdtemp(prefix="rihmasto-no-hooks-")]
    return _HOOKS[0]


def flags() -> list[str]:
    """``git <flags> ...``: no hook, no fsmonitor, no signing program, no replace ref, and no look inside a
    submodule, whatever the repository says."""
    return ["-c", f"core.hooksPath={_no_hooks()}", "-c", "core.fsmonitor=false", "-c", "commit.gpgSign=false",
            "-c", "tag.gpgSign=false", "-c", "core.untrackedCache=false", "-c", "submodule.recurse=false",
            "-c", "fetch.recurseSubmodules=false", "-c", "core.useReplaceRefs=false",
            "-c", "diff.ignoreSubmodules=all", "-c", "status.submoduleSummary=false"]


def env() -> dict[str, str]:
    """The variables every kernel git call there adds: no replace refs, and an empty grafts file of this
    process's own in place of the repository's ``info/grafts``."""
    if not _GRAFTS or not os.path.isfile(_GRAFTS[0]):
        fd, path = tempfile.mkstemp(prefix="rihmasto-no-grafts-")
        os.close(fd)
        _GRAFTS[:] = [path]
    return {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_GRAFT_FILE": _GRAFTS[0]}


def git(repo: str | Path, origin: str | Path | None = None) -> list[str]:
    """The kernel's git for ``repo`` after untrusted code ran there: scrubbed first, then hardened."""
    scrub(repo, origin)
    return ["git", *flags()]


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def _kept(config: Path) -> list[tuple[str, str]]:
    """The KEPT keys of ``config``, read by git itself (a file it is given: no include is followed)."""
    proc = subprocess.run(["git", "config", "--file", str(config), "--list", "-z"], cwd=_no_hooks(),
                          capture_output=True, stdin=subprocess.DEVNULL, check=False)
    if proc.returncode != 0:
        raise Tampered(f"{config} is not a config git can read")
    out = []
    for entry in proc.stdout.decode("utf-8", "replace").split("\0"):
        key, given, value = entry.partition("\n")
        value = value if given else "true"           # a bare key is a boolean true
        if key and KEPT.fullmatch(key):
            out.append((key, value))
    return out


def _render(entries: list[tuple[str, str]], origin: str | None) -> str:
    sections: dict[tuple[str, str | None], list[tuple[str, str]]] = {}
    for key, value in entries:
        section, _, rest = key.partition(".")
        sub, _, name = rest.rpartition(".")
        if section.lower() == "remote" and (name.lower() == "fetch" or (name.lower() == "url" and origin is not None)):
            continue                                  # origin's refspec is git's default again (below)
        if section.lower() == "branch" and name.lower() == "remote" and value != "origin":
            continue                                  # a branch tracks origin, or nothing
        sections.setdefault((section.lower(), sub or None), []).append((name, value))
    if origin is not None:
        sections.setdefault(("remote", "origin"), []).insert(0, ("url", origin))
    if ("remote", "origin") in sections:
        sections[("remote", "origin")].append(("fetch", DEFAULT_FETCH))
    lines = ["# Rewritten by the kernel (kernel/git_guard.py): only the keys a clone sets are kept."]
    for (head, under), items in sections.items():
        lines.append(f"[{head}]" if under is None else f"[{head} {_quote(under)}]")
        lines += [f"\t{name} = {_quote(value)}" for name, value in items]
    return "\n".join(lines) + "\n"


def _unlink_link(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir() and path.name in ("hooks", "info")):
        path.unlink()


def scrub(repo: str | Path, origin: str | Path | None = None) -> None:
    """Make ``repo``'s ``.git`` safe for the kernel's git again (see the module's text)."""
    dot = Path(repo) / ".git"
    if dot.is_symlink() or not dot.is_dir():
        raise Tampered(f"{dot} is not a folder (a link, or a gitdir file pointing elsewhere): the kernel runs "
                       "no git there")
    for name in ("config", "hooks", "info"):
        _unlink_link(dot / name)
    config = dot / "config"
    if config.is_dir():
        raise Tampered(f"{config} is a folder: the kernel runs no git there")
    entries = _kept(config) if config.exists() else []
    mode = (config.stat().st_mode & 0o664) if config.exists() else 0o644
    text = _render(entries, None if origin is None else str(origin))
    fd, tmp = tempfile.mkstemp(prefix=".config-", dir=dot)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.chmod(tmp, mode or 0o644)                      # a separate account's git still reads it (the cell's)
    os.replace(tmp, config)                           # replaces a link itself, never what it points to
    # commondir would point git at another repository's config and hooks; a clone has none
    for stale in ("config.worktree", "info/attributes", "commondir", *SEEN_AS_OTHER):
        if (dot / stale).is_file() or (dot / stale).is_symlink():
            (dot / stale).unlink()
    _drop_replace_refs(dot)
    hooks = dot / "hooks"
    if hooks.is_dir():
        for hook in hooks.iterdir():
            if hook.name.endswith(".sample") and hook.is_file() and not hook.is_symlink():
                continue
            if hook.is_dir() and not hook.is_symlink():
                shutil.rmtree(hook, ignore_errors=True)
            else:
                hook.unlink()


def _drop_replace_refs(dot: Path) -> None:
    """No ``refs/replace/*``, loose or packed: a replace ref makes git show one commit as another."""
    replace = dot / "refs" / "replace"
    if replace.is_symlink() or replace.is_file():
        replace.unlink()
    elif replace.is_dir():
        remove(replace)
    packed = dot / "packed-refs"
    if packed.is_file() and not packed.is_symlink():
        given = packed.read_bytes().splitlines(keepends=True)
        kept, dropping = [], False
        for line in given:
            if not line.startswith(b"^"):             # a peeled line belongs to the ref above it
                dropping = line.split(b" ", 1)[-1].startswith(b"refs/replace/")
            if not dropping:
                kept.append(line)
        if len(kept) != len(given):
            packed.write_bytes(b"".join(kept))


def _is_dotgit(name: str) -> bool:
    return name.rstrip(". ").casefold() == ".git"     # .GIT, .git. and ".git " are .git on Windows


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _dotgits(top: Path) -> list[Path]:
    """Every ``.git`` (folder, file or link) below ``top``'s own, found without following a link."""
    found = []
    for root, dirs, files in os.walk(top):
        here = Path(root)
        found += [here / name for name in (*dirs, *files) if _is_dotgit(name) and here != top]
        dirs[:] = [d for d in dirs if not _is_dotgit(d) and not _linked(here / d)]
    return found


def _gitlinks(top: Path, *listing: str) -> set[str]:
    proc = subprocess.run(["git", *flags(), *listing], cwd=top, capture_output=True, check=False,
                          stdin=subprocess.DEVNULL, env={**os.environ, **env()})
    return {e.partition(b"\t")[2].decode("utf-8", "replace") for e in proc.stdout.split(b"\0")
            if e.startswith(GITLINK)}


def nested(repo: str | Path, base: str | None = None) -> list[str]:
    """The repositories inside ``repo``: a ``.git`` below its top, and a gitlink in its index or HEAD that
    the product's ``base`` does not hold (an adopted repository's own submodule stays; its folder is
    empty, since the kernel never checks a submodule out)."""
    top = Path(repo)
    found = {p.relative_to(top).as_posix() for p in _dotgits(top)}
    links = _gitlinks(top, "ls-files", "-s", "-z") | _gitlinks(top, "ls-tree", "-r", "-z", "HEAD")
    return sorted(found | (links - (_gitlinks(top, "ls-tree", "-r", "-z", base) if base else set())))


def refuse_nested(repo: str | Path, base: str | None = None) -> None:
    """Tampered when ``repo`` holds a repository of its own: git would run that repository's config (its
    filter drivers) when it checks whether it changed, as the account that runs Rihmasto."""
    found = nested(repo, base)
    if found:
        raise Tampered(f"{Path(repo).name} holds a repository inside it ({', '.join(found[:5])}): the kernel "
                       "runs no git over it and takes none of this work; a cell writes plain files only")


def unnest(repo: str | Path) -> None:
    """Remove every ``.git`` below ``repo``'s top before the kernel's git runs there (a lane's next checkout)."""
    for path in _dotgits(Path(repo)):
        if _linked(path) or not path.is_dir():
            try:
                path.unlink()
            except OSError:
                os.rmdir(path)                        # a directory link or junction on Windows
        else:
            remove(path)


def remove(path: Path) -> None:
    """Remove a lane the kernel no longer trusts, read-only files (git's objects on Windows) included;
    a link inside it is removed, never followed."""
    def writable(func: Callable[[str], object], target: str, _exc: object) -> None:
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable)
    else:
        shutil.rmtree(path, onerror=writable)
