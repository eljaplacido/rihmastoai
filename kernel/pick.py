"""Choose a folder or a file by browsing (FR-PICK1; docs/guides/inputs.md, Choose a folder or a file).

Every field of the cockpit that takes a path on the cockpit's machine offers Browse: the places to start from
and one folder's contents, read here, under the same rules as every read (kernel/source_guard.py):

- **Places**: the folders this person chose before (kept in the home per person, beside the walkthroughs'),
  the configured roots (``RIHMASTO_SOURCE_ROOTS``, those allowed in Settings), the home folder and the drives,
  each with whether the cockpit may read it and why not.
- **A folder's contents**: its subfolders (and files, when asked) sorted by name, each with whether it is a git
  repository, whether a project here already holds it (adopted or attached), when it last changed and whether
  the cockpit may read it. Dot folders, ``node_modules``, ``.venv`` and the like are folded; a long folder says
  how many more there are, and a filter is searched in the whole folder, so it finds those too. A link that leads out of the allowed folders is never followed.
- **Outside the allowed folders** a single operator may still look at a folder's subfolders, by name only (no
  files), to find the one to allow; under enforced access such a folder is refused. A system folder or a folder
  of keys is never listed, wherever it is.

Listing reads and records nothing. Whatever is chosen is checked again by source_guard before any use.
"""

from __future__ import annotations

import os
import string
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kernel import source_guard as ksource

MAX_ROWS = 300            # rows of each kind shown; the rest are counted ("N more")
FOLDED = frozenset({"node_modules", ".venv", "venv", "env", "__pycache__", ".git", ".hg", ".svn", ".tox", ".nox",
                    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".nuxt", ".cache", ".gradle", ".idea",
                    ".vscode", "bower_components", "$recycle.bin", "system volume information", "appdata"})
NEVER = "never"


def _key(path: str | Path) -> str:
    return os.path.normcase(str(path))


def _why(path: Path, home: Path | None) -> str:
    """Why the cockpit may not read ``path``, or ""."""
    try:
        return ksource._refused(path, home)
    except (OSError, ValueError) as exc:
        return f"cannot be read here: {exc}"


def _never(path: Path, home: Path | None) -> bool:
    """A folder of keys, or a system folder no root was given inside: never read, and allowing a root does not
    change it (as source_guard)."""
    if ksource._keys(path):
        return True
    system = ksource._system(path)
    if system is None:
        return False
    return not any(ksource._under(path, r) and ksource._within(r, system) for r in ksource.roots(home))


def _place(path: Path, label: str, kind: str, home: Path | None) -> dict[str, Any]:
    why = _why(path, home)
    return {"path": str(path), "label": label, "kind": kind, "readable": not why, "why": why or None,
            "exists": path.is_dir()}


def drives() -> list[Path]:
    """The drives of this computer: the letters that exist on Windows, the file system's root elsewhere."""
    if os.name != "nt":
        return [Path("/")]
    listed = getattr(os, "listdrives", None)
    names = list(listed()) if callable(listed) else [f"{c}:\\" for c in string.ascii_uppercase]
    return [Path(n) for n in names if os.path.isdir(n)]


def places(factory: Any, person: str) -> list[dict[str, Any]]:
    """Where browsing starts: recent folders, the roots, the home folder and the drives, each once."""
    from kernel import walkthrough as wk

    home = factory.home
    rows = [_place(Path(p), Path(p).name or p, "recent", home)
            for p in (wk.recent(factory, person) if person else []) if "://" not in p and Path(p).is_dir()]
    env = [p for p in os.environ.get(ksource.ROOTS_ENV, "").split(os.pathsep) if p.strip()]
    rows += [_place(Path(p).expanduser().resolve(), p, "root", home) for p in env]
    rows += [_place(Path(r["path"]), r["path"], "root", home) for r in ksource.allowed(home)]
    rows.append(_place(Path.home(), "Home", "home", home))
    rows += [_place(d, str(d), "drive", home) for d in drives()]
    seen: set[str] = set()
    out = []
    for r in rows:
        if _key(r["path"]) not in seen:
            seen.add(_key(r["path"]))
            out.append(r)
    return out


def known(factory: Any) -> dict[str, dict[str, str]]:
    """The local folders projects here hold: adopted from (or snapshotted from), or attached, by path."""
    from kernel.adopt import is_adopted

    out: dict[str, dict[str, str]] = {}
    for p in factory.projects():
        if p.pid.startswith("_"):
            continue
        a = (p.read("adopted.json") or {}) if is_adopted(p) else {}
        held = [("adopted", a.get("source")), ("adopted", (a.get("snapshot") or {}).get("from")),
                ("attached", (p.meta.get("attached") or {}).get("repo"))]
        for how, where in held:
            if where and "://" not in str(where):
                out.setdefault(_key(Path(str(where)).expanduser().resolve()),
                               {"project": p.pid, "title": str(p.meta.get("title") or p.pid), "how": how})
    return out


def _stamp(st: os.stat_result | None) -> str | None:
    return datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if st else None


def _stat(entry: os.DirEntry[str]) -> os.stat_result | None:
    try:
        return entry.stat(follow_symlinks=False)
    except OSError:
        return None


def _target(entry: os.DirEntry[str]) -> tuple[Path, bool]:
    """Where an entry leads, and whether it is a link (a symbolic link, a junction) that leads elsewhere."""
    here = Path(entry.path)
    try:
        there = here.resolve()
    except (OSError, RuntimeError):
        return here, True
    return there, entry.is_symlink() or _key(there) != _key(here.absolute())


def _folder_row(entry: os.DirEntry[str], ctx: dict[str, Any]) -> dict[str, Any]:
    target, link = _target(entry)
    why = _why(target, ctx["home"])
    never = _never(target, ctx["home"])
    if link and why and not never:
        why = "a link that leads out of the allowed folders: it is not followed"
    row: dict[str, Any] = {"name": entry.name, "path": entry.path, "link": link, "readable": not why,
                           "why": why or None, "never": never, "modified": _stamp(_stat(entry)),
                           "project": ctx["known"].get(_key(target))}
    row["git"] = not never and not (link and why) and (Path(entry.path) / ".git").exists()
    if why and not never and not link and not ctx["enforced"]:
        row["allow"] = ksource.suggest(target)
    return row


def _file_row(entry: os.DirEntry[str]) -> dict[str, Any]:
    st = _stat(entry)
    return {"name": entry.name, "path": entry.path, "size": st.st_size if st else None, "modified": _stamp(st),
            "link": entry.is_symlink()}


def _is_dir(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_dir()
    except OSError:
        return False


def _folded(name: str) -> bool:
    return name.startswith(".") or name.lower() in FOLDED


def _entries(path: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(path) as it:
            return sorted(it, key=lambda e: (e.name.lower(), e.name))
    except OSError as exc:
        raise ValueError(f"{path} could not be listed: {exc.strerror or exc}") from None


def crumbs(path: Path) -> list[dict[str, str]]:
    """The trail from the drive (or /) to ``path``, each with the path to go back to."""
    trail = [*reversed(path.parents), path]
    return [{"name": p.name or str(p), "path": str(p)} for p in trail]


def _capped(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    return rows[:MAX_ROWS], max(0, len(rows) - MAX_ROWS)


def resolve(text: str | None) -> Path:
    """The folder a person named, resolved (their home folder when none was named, a file's folder for a file)."""
    raw = str(text or "").strip().strip('"')
    path = Path(raw).expanduser() if raw else Path.home()
    if not path.is_absolute():
        raise ValueError(f"{raw} is not a full path: give it from the drive (C:\\...) or from / or ~")
    path = path.resolve()
    return path.parent if path.is_file() else path


def _here(factory: Any, path: Path, *, enforced: bool) -> dict[str, Any]:
    """What the listed folder itself is: readable or why not, and what may be done about it."""
    home = factory.home
    why = _why(path, home)
    if _never(path, home):
        raise ksource.SourceRefused(f"refused: {path} {why or 'is never read'}")
    if why and enforced:
        offer = ksource.offer(path, enforced=True, home=home)
        hint = f": {offer['say']}" if offer else ""
        raise ksource.SourceRefused(f"refused: {path} {why}{hint}")
    offer = ksource.offer(path, enforced=enforced, home=home) if why and len(path.parts) > 1 else None
    return {"path": str(path), "name": path.name or str(path), "readable": not why, "why": why or None,
            "offer": offer, "parent": str(path.parent) if path.parent != path else None, "crumbs": crumbs(path),
            "git": (path / ".git").exists(), "project": known(factory).get(_key(path))}


def _matching(entries: list[os.DirEntry[str]], q: str) -> list[os.DirEntry[str]]:
    """The entries whose names hold ``q`` (any case), so the filter finds what lies past the cap."""
    text = q.strip().casefold()
    return [e for e in entries if text in e.name.casefold()] if text else entries


def listing(factory: Any, text: str | None, *, persona: str, files: bool = False, enforced: bool = False,
            q: str = "") -> dict[str, Any]:
    """One folder's subfolders (and files, when asked and readable), for the folder browser; with ``q``, only
    those whose names hold it, searched in the whole folder before the cap."""
    if persona not in ksource.READERS:
        raise ksource.SourceRefused(f"refused: a {persona} may not have the cockpit read a folder; "
                                    f"{', '.join(ksource.READERS)} may")
    path = resolve(text)
    if not path.is_dir():
        raise ValueError(f"{path} is not a folder")
    out = _here(factory, path, enforced=enforced)
    ctx = {"home": factory.home, "known": known(factory), "enforced": enforced}
    entries = _matching(_entries(path), q)
    out["q"] = q.strip()
    dirs = [e for e in entries if _is_dir(e)]
    rows = [_folder_row(e, ctx) for e in dirs if not _folded(e.name)]
    hidden = [_folder_row(e, ctx) for e in dirs if _folded(e.name)]
    out["folders"], out["more"] = _capped(rows)
    out["hidden"], out["hidden_more"] = _capped(hidden)
    shown = [_file_row(e) for e in entries if not _is_dir(e) and not e.name.startswith(".")] \
        if files and out["readable"] else []
    out["files"], out["files_more"] = _capped(shown)
    out["files_listed"] = bool(files and out["readable"])
    return out


def describe(factory: Any, text: str, *, persona: str, enforced: bool) -> dict[str, Any]:
    """A path chosen in the computer's own dialog, as the browser shows it: readable here, or why not."""
    path = Path(text).expanduser().resolve()
    folder = path.is_dir()
    why = _why(path if folder else path.parent, factory.home)
    if persona not in ksource.READERS:
        why = f"a {persona} may not have the cockpit read a folder"
    offer = ksource.offer(path if folder else path.parent, enforced=enforced, home=factory.home) if why else None
    return {"path": str(path), "kind": "folder" if folder else "file", "readable": not why, "why": why or None,
            "offer": offer}


def platform() -> str:
    return "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"
