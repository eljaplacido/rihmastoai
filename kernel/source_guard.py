"""Which local folders the cockpit may read for a person (docs/guides/inputs.md, The material map).

The cockpit runs on the machine whose files it would read, so a folder a person names there is read only:
- by a persona that may create or adopt a project (`READERS`), signed like any write;
- under the user's home folder, a root the operator configured (``RIHMASTO_SOURCE_ROOTS``, folders
  separated by the system's path separator), or a root allowed in Settings (``source_roots.json`` in the
  factory home, `allow`): IT allows one under enforced access; a single operator allows one after saying
  yes to it. Either is recorded in the factory's ledger, and takes effect at once, without a restart;
- never a system folder (the operating system, programs, devices), and never a folder of keys or
  credentials (``.ssh``, ``.gnupg``, ``.aws`` and the like), wherever it is: no allowed root changes that.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ROOTS_ENV = "RIHMASTO_SOURCE_ROOTS"
ROOTS_FILE = "source_roots.json"
READERS = ("business_owner", "product_owner", "developer", "it")
SYSTEM = ("C:/Windows", "C:/Program Files", "C:/Program Files (x86)", "C:/ProgramData", "/etc", "/usr", "/bin",
          "/sbin", "/lib", "/lib64", "/boot", "/dev", "/proc", "/sys", "/var", "/opt", "/root", "/System",
          "/Library", "/private/etc", "/private/var")
KEY_FOLDERS = frozenset({".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".config/gcloud", ".password-store"})


class SourceRefused(PermissionError):
    """A folder the cockpit may not read for this person."""


def _home(home: str | Path | None) -> Path | None:
    from kernel.store import HOME_ENV, RIHMA_HOME_ENV, RIHMASTO_HOME_ENV

    if home is not None:
        return Path(home)
    named = next((os.environ[k] for k in (RIHMASTO_HOME_ENV, RIHMA_HOME_ENV, HOME_ENV) if os.environ.get(k)), "")
    return Path(named) if named else None


def allowed(home: str | Path | None = None) -> list[dict[str, Any]]:
    """The roots allowed in Settings, with who allowed each and when."""
    from kernel.store import read_json

    where = _home(home)
    data = read_json(where / ROOTS_FILE, None) if where is not None else None
    return [r for r in (data or {}).get("roots", []) if isinstance(r, dict) and r.get("path")]


def roots(home: str | Path | None = None) -> list[Path]:
    """Where the cockpit may read: the user's home, the configured roots and the roots allowed in Settings."""
    found = [Path.home()]
    found += [Path(p) for p in os.environ.get(ROOTS_ENV, "").split(os.pathsep) if p.strip()]
    found += [Path(r["path"]) for r in allowed(home)]
    return [p.expanduser().resolve() for p in found]


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _within(path: Path, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or under it, case-insensitively (a Windows drive's folders)."""
    p, f = path.as_posix().lower().rstrip("/"), folder.lower().rstrip("/")
    return p == f or p.startswith(f + "/")


def check_folder(text: str, persona: str, home: str | Path | None = None) -> Path:
    """The folder a person named, resolved, when the cockpit may read it for them; else SourceRefused (or
    ValueError when it is no folder)."""
    if persona not in READERS:
        raise SourceRefused(f"refused: a {persona} may not have the cockpit read a folder; "
                            f"{', '.join(READERS)} may")
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("no folder given")
    path = Path(raw).expanduser().resolve()
    why = _refused(path, home)
    if why:
        raise SourceRefused(f"refused: {path} {why}")
    if not path.is_dir():
        raise ValueError(f"{path} is not a folder")
    return path


def _keys(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    pairs = {"/".join(parts[i:i + 2]) for i in range(len(parts))}
    return bool(KEY_FOLDERS & (set(parts) | pairs))


def _system(path: Path) -> str | None:
    return next((s for s in SYSTEM if _within(path, s)), None)


def _refused(path: Path, home: str | Path | None = None) -> str:
    """Why the cockpit may not read ``path``, or "". A system folder is read only where a root inside it was
    given (a home under /root, a root under /var)."""
    system = _system(path)
    rs = roots(home)
    if system and not any(_under(path, r) and _within(r, system) for r in rs):
        return f"is a system folder; the cockpit reads folders under your home or the roots in {ROOTS_ENV}"
    if not any(_under(path, r) for r in rs):
        return (f"is outside your home folder and the roots in {ROOTS_ENV} or allowed in Settings; "
                f"{suggest(path)} can be allowed in Settings > Folders the cockpit may read")
    if _keys(path):
        return "holds keys or credentials; it is never read"
    return ""


CONTAINERS = frozenset({"users", "home", "volumes", "mnt", "media", "srv", "data"})


def suggest(path: str | Path) -> str:
    """The folder to allow for ``path``: its top folder on the drive (C:\\dev for C:\\dev\\app\\src), one deeper
    under a folder that holds many people's or disks' folders (D:\\Users\\aino, /mnt/work)."""
    p = Path(path).expanduser().resolve()
    depth = 3 if len(p.parts) > 2 and p.parts[1].lower() in CONTAINERS else 2
    top = Path(*p.parts[:depth]) if len(p.parts) > depth else p
    return str(p if _system(top) or _keys(top) else top)


def offer(path: str | Path, *, enforced: bool, home: str | Path | None = None) -> dict[str, Any] | None:
    """What the refusal offers for a folder outside the allowed ones: the root to allow, and who may; None
    when allowing a root would not help (a system folder, keys)."""
    p = Path(path).expanduser().resolve()
    if _system(p) or _keys(p) or any(_under(p, r) for r in roots(home)):
        return None
    root = suggest(p)
    return {"root": root, "who": "it" if enforced else "you",
            "say": f"Ask IT to allow {root}" if enforced else f"Allow {root}"}


def _may_allow(person: str, persona: str, enforced: bool, confirmed: bool) -> None:
    """Who may allow a folder: IT under enforced access; a single operator's reader persona, after a yes."""
    from kernel.people import is_person

    if not is_person(person):
        raise SourceRefused(f"refused: {person!r} is not a person; allowing a folder is a person's act")
    if enforced and persona != "it":
        raise SourceRefused("refused: under enforced access only IT allows a folder: ask IT to allow it")
    if persona not in READERS:
        raise SourceRefused(f"refused: a {persona} may not allow a folder; {', '.join(READERS)} may")
    if not confirmed:
        raise SourceRefused("refused: say yes to allowing it first: the cockpit may then read every folder under it")


def _allowable(folder: str) -> Path:
    """The folder, resolved, when it may be allowed: never a drive's root, a system folder or one of keys."""
    p = Path(str(folder or "").strip()).expanduser().resolve()
    if not str(folder or "").strip() or len(p.parts) < 2 or p == p.parent:
        raise SourceRefused(f"refused: {p} is a drive or the file system's root; allow a folder on it, such as "
                            f"{Path(p.anchor) / 'dev'}")
    holds = any(_within(Path(s), p.as_posix()) for s in SYSTEM if Path(s).anchor == p.anchor)
    if _system(p) or holds:
        raise SourceRefused(f"refused: {p} is or holds a system folder; it is never allowed")
    if _keys(p):
        raise SourceRefused(f"refused: {p} holds keys or credentials; it is never allowed")
    if not p.is_dir():
        raise ValueError(f"{p} is not a folder")
    return p


def allow(home: str | Path, folder: str, *, person: str, persona: str, enforced: bool, confirmed: bool,
          log: Any = None) -> dict[str, Any]:
    """Allow ``folder`` (and what is under it) as a root, signed. Under enforced access only IT may; a single
    operator says yes first (``confirmed``). A system folder, a folder of keys, a drive's or the file
    system's root are refused. ``log`` records it (the factory's ledger)."""
    from kernel.store import updating_json

    _may_allow(person, persona, enforced, confirmed)
    p = _allowable(folder)
    entry = {"path": str(p), "by": person, "persona": persona}
    with updating_json(Path(home) / ROOTS_FILE, {"roots": []}) as data:
        data["roots"] = [r for r in data.get("roots", []) if Path(r.get("path", "")).resolve() != p] + [entry]
    if log is not None:
        log("source_root_allowed", {**entry, "enforced": enforced})
    return entry


def disallow(home: str | Path, folder: str, *, person: str, persona: str, enforced: bool, log: Any = None
             ) -> list[dict[str, Any]]:
    """Take back a root allowed in Settings, signed (IT under enforced access)."""
    from kernel.people import is_person
    from kernel.store import updating_json

    if not is_person(person) or (enforced and persona != "it") or persona not in READERS:
        raise SourceRefused("refused: only IT (or a single operator) takes back an allowed folder, by name")
    p = Path(str(folder or "").strip()).expanduser().resolve()
    with updating_json(Path(home) / ROOTS_FILE, {"roots": []}) as data:
        data["roots"] = [r for r in data.get("roots", []) if Path(r.get("path", "")).resolve() != p]
        left = list(data["roots"])
    if log is not None:
        log("source_root_removed", {"path": str(p), "by": person, "persona": persona})
    return left
